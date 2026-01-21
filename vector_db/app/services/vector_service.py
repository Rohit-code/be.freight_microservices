"""Vector DB Service using Sentence Transformers (BGE model)"""
from typing import List, Dict, Any, Optional
import json
import os
import uuid
from pathlib import Path
import pickle
import numpy as np
from ..core.config import settings
import logging

logger = logging.getLogger(__name__)

# Storage paths
MICROSERVICES_ROOT = Path(__file__).parent.parent.parent.parent
VECTOR_DB_PATH = MICROSERVICES_ROOT / settings.chroma_db_path
VECTOR_DB_PATH.mkdir(parents=True, exist_ok=True)

# Global embedding model (lazy loaded)
_embedding_model = None

def get_embedding_model():
    """Get the sentence transformer model (lazy loading)"""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading BGE embedding model...")
            _embedding_model = SentenceTransformer("BAAI/bge-base-en-v1.5")
            logger.info("BGE embedding model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise
    return _embedding_model


class VectorCollection:
    """Vector collection using Sentence Transformers embeddings"""
    
    def __init__(self, name: str, path: Path):
        self.name = name
        self.path = path
        self.documents: List[str] = []
        self.metadatas: List[Dict[str, Any]] = []
        self.ids: List[str] = []
        self.embeddings: Optional[np.ndarray] = None
        self._load()
    
    def _get_file_path(self) -> Path:
        return self.path / f"{self.name}.pkl"
    
    def _load(self):
        """Load collection from disk"""
        file_path = self._get_file_path()
        if file_path.exists():
            try:
                with open(file_path, 'rb') as f:
                    data = pickle.load(f)
                    self.documents = data.get('documents', [])
                    self.metadatas = data.get('metadatas', [])
                    self.ids = data.get('ids', [])
                    self.embeddings = data.get('embeddings')
                    logger.info(f"Loaded collection '{self.name}' with {len(self.documents)} documents")
            except Exception as e:
                logger.error(f"Error loading collection {self.name}: {e}")
    
    def _save(self):
        """Save collection to disk"""
        file_path = self._get_file_path()
        with open(file_path, 'wb') as f:
            pickle.dump({
                'documents': self.documents,
                'metadatas': self.metadatas,
                'ids': self.ids,
                'embeddings': self.embeddings
            }, f)
        logger.info(f"Saved collection '{self.name}' with {len(self.documents)} documents")
    
    def _create_embeddings(self, texts: List[str]) -> np.ndarray:
        """Create embeddings for texts using BGE model"""
        model = get_embedding_model()
        # BGE model recommends adding instruction prefix for retrieval
        # For queries: "Represent this sentence for searching relevant passages: "
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.array(embeddings)
    
    def add(self, documents: List[str], metadatas: List[Dict[str, Any]], ids: List[str]):
        """Add documents to collection with embeddings. Updates existing documents if ID already exists."""
        if not documents:
            return
        
        # Check for existing IDs and update them instead of creating duplicates
        new_documents = []
        new_metadatas = []
        new_ids = []
        indices_to_update = []
        
        for i, doc_id in enumerate(ids):
            try:
                existing_idx = self.ids.index(doc_id)
                # Document exists - update it instead of creating duplicate
                indices_to_update.append((existing_idx, i))
            except ValueError:
                # Document doesn't exist - will be added as new
                new_documents.append(documents[i])
                new_metadatas.append(metadatas[i] if metadatas else {})
                new_ids.append(doc_id)
        
        # Update existing documents
        for existing_idx, new_idx in indices_to_update:
            self.documents[existing_idx] = documents[new_idx]
            self.metadatas[existing_idx] = metadatas[new_idx] if metadatas else {}
            # Regenerate embedding for updated document
            new_embedding = self._create_embeddings([documents[new_idx]])
            if self.embeddings is not None:
                self.embeddings[existing_idx] = new_embedding[0]
        
        # Add new documents
        if new_documents:
            new_embeddings = self._create_embeddings(new_documents)
            
            # Append to existing data
            self.documents.extend(new_documents)
            self.metadatas.extend(new_metadatas)
            self.ids.extend(new_ids)
            
            # Update embeddings array
            if self.embeddings is None:
                self.embeddings = new_embeddings
            else:
                self.embeddings = np.vstack([self.embeddings, new_embeddings])
        
        self._save()
        updated_count = len(indices_to_update)
        added_count = len(new_documents)
        if updated_count > 0:
            logger.info(f"Updated {updated_count} existing document(s) and added {added_count} new document(s) to collection '{self.name}'")
        else:
            logger.info(f"Added {added_count} documents to collection '{self.name}'")
    
    def query(self, query_texts: List[str], n_results: int = 10) -> Dict[str, Any]:
        """Query collection for similar documents using cosine similarity"""
        if self.embeddings is None or len(self.documents) == 0:
            return {
                'ids': [[] for _ in query_texts],
                'documents': [[] for _ in query_texts],
                'metadatas': [[] for _ in query_texts],
                'distances': [[] for _ in query_texts]
            }
        
        # Create embeddings for queries
        # Add BGE retrieval prefix for better results
        prefixed_queries = [f"Represent this sentence for searching relevant passages: {q}" for q in query_texts]
        query_embeddings = self._create_embeddings(prefixed_queries)
        
        all_ids = []
        all_documents = []
        all_metadatas = []
        all_distances = []
        
        for query_embedding in query_embeddings:
            # Calculate cosine similarity (embeddings are already normalized)
            similarities = np.dot(self.embeddings, query_embedding)
            
            # Get top n results
            top_indices = np.argsort(similarities)[::-1][:n_results]
            
            result_ids = [self.ids[i] for i in top_indices if similarities[i] > 0]
            result_docs = [self.documents[i] for i in top_indices if similarities[i] > 0]
            result_metas = [self.metadatas[i] for i in top_indices if similarities[i] > 0]
            # Convert similarity to distance (1 - similarity)
            result_distances = [float(1 - similarities[i]) for i in top_indices if similarities[i] > 0]
            
            all_ids.append(result_ids[:n_results])
            all_documents.append(result_docs[:n_results])
            all_metadatas.append(result_metas[:n_results])
            all_distances.append(result_distances[:n_results])
        
        return {
            'ids': all_ids,
            'documents': all_documents,
            'metadatas': all_metadatas,
            'distances': all_distances
        }
    
    def count(self) -> int:
        """Return document count"""
        return len(self.documents)
    
    def get_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get document by ID"""
        try:
            idx = self.ids.index(doc_id)
            return {
                'id': self.ids[idx],
                'document': self.documents[idx],
                'metadata': self.metadatas[idx]
            }
        except ValueError:
            return None
    
    def update_metadata(self, doc_id: str, metadata_updates: Dict[str, Any]) -> bool:
        """Update metadata for a document"""
        try:
            idx = self.ids.index(doc_id)
            self.metadatas[idx].update(metadata_updates)
            self._save()
            return True
        except ValueError:
            return False
    
    def delete_document(self, doc_id: str) -> bool:
        """Delete a document by ID"""
        try:
            idx = self.ids.index(doc_id)
            self.documents.pop(idx)
            self.metadatas.pop(idx)
            self.ids.pop(idx)
            if self.embeddings is not None:
                self.embeddings = np.delete(self.embeddings, idx, axis=0)
                if len(self.embeddings) == 0:
                    self.embeddings = None
            self._save()
            return True
        except ValueError:
            return False
    
    def delete(self):
        """Delete collection file"""
        file_path = self._get_file_path()
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted collection '{self.name}'")


# Collection cache
_collections: Dict[str, VectorCollection] = {}


def _get_collection(name: str) -> Optional[VectorCollection]:
    """Get collection by name"""
    if name not in _collections:
        collection_file = VECTOR_DB_PATH / f"{name}.pkl"
        if collection_file.exists():
            _collections[name] = VectorCollection(name, VECTOR_DB_PATH)
    return _collections.get(name)


def create_collection(collection_name: str) -> Dict[str, Any]:
    """Create a new collection"""
    try:
        existing = _get_collection(collection_name)
        if existing:
            return {
                "message": f"Collection '{collection_name}' already exists",
                "collection_name": collection_name,
                "id": collection_name
            }
        
        collection = VectorCollection(collection_name, VECTOR_DB_PATH)
        collection._save()
        _collections[collection_name] = collection
        
        return {
            "message": f"Collection '{collection_name}' created successfully",
            "collection_name": collection_name,
            "id": collection_name
        }
    except Exception as e:
        logger.error(f"Error creating collection: {e}")
        raise


def add_documents(
    collection_name: str,
    documents: List[str],
    metadatas: Optional[List[Dict[str, Any]]] = None,
    ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Add documents to a collection"""
    try:
        collection = _get_collection(collection_name)
        if not collection:
            raise ValueError(f"Collection '{collection_name}' does not exist. Create it first.")
        
        # Generate IDs if not provided
        if not ids:
            ids = [str(uuid.uuid4()) for _ in documents]
        
        # Ensure metadatas list matches documents length
        if metadatas is None:
            metadatas = [{}] * len(documents)
        elif len(metadatas) != len(documents):
            metadatas = metadatas + [{}] * (len(documents) - len(metadatas))
        
        collection.add(documents, metadatas, ids)
        
        return {
            "message": f"Added {len(documents)} documents to collection '{collection_name}'",
            "collection_name": collection_name,
            "count": len(documents),
            "ids": ids
        }
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error adding documents: {e}")
        raise


def query_collection(
    collection_name: str,
    query_texts: List[str],
    n_results: int = 10
) -> Dict[str, Any]:
    """Query a collection"""
    try:
        collection = _get_collection(collection_name)
        if not collection:
            raise ValueError(f"Collection '{collection_name}' does not exist.")
        
        results = collection.query(query_texts, n_results)
        
        return {
            "collection_name": collection_name,
            "query_texts": query_texts,
            "n_results": n_results,
            "results": results
        }
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error querying collection: {e}")
        raise


def get_document(collection_name: str, doc_id: str) -> Dict[str, Any]:
    """Get a document by ID"""
    try:
        collection = _get_collection(collection_name)
        if not collection:
            raise ValueError(f"Collection '{collection_name}' does not exist.")
        
        doc = collection.get_by_id(doc_id)
        if not doc:
            raise ValueError(f"Document '{doc_id}' not found in collection '{collection_name}'.")
        
        return doc
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error getting document: {e}")
        raise


def update_document_metadata(collection_name: str, doc_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Update document metadata"""
    try:
        collection = _get_collection(collection_name)
        if not collection:
            raise ValueError(f"Collection '{collection_name}' does not exist.")
        
        success = collection.update_metadata(doc_id, metadata)
        if not success:
            raise ValueError(f"Document '{doc_id}' not found in collection '{collection_name}'.")
        
        return {
            "message": f"Updated metadata for document '{doc_id}'",
            "collection_name": collection_name,
            "doc_id": doc_id
        }
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error updating document metadata: {e}")
        raise


def delete_document(collection_name: str, doc_id: str) -> Dict[str, Any]:
    """Delete a document"""
    try:
        collection = _get_collection(collection_name)
        if not collection:
            raise ValueError(f"Collection '{collection_name}' does not exist.")
        
        success = collection.delete_document(doc_id)
        if not success:
            raise ValueError(f"Document '{doc_id}' not found in collection '{collection_name}'.")
        
        return {
            "message": f"Deleted document '{doc_id}'",
            "collection_name": collection_name,
            "doc_id": doc_id
        }
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error deleting document: {e}")
        raise


def delete_collection(collection_name: str) -> Dict[str, Any]:
    """Delete a collection"""
    try:
        collection = _get_collection(collection_name)
        if not collection:
            raise ValueError(f"Collection '{collection_name}' does not exist.")
        
        collection.delete()
        if collection_name in _collections:
            del _collections[collection_name]
        
        return {
            "message": f"Collection '{collection_name}' deleted successfully",
            "collection_name": collection_name
        }
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error deleting collection: {e}")
        raise


def list_collections() -> Dict[str, Any]:
    """List all collections"""
    try:
        collections = []
        for file_path in VECTOR_DB_PATH.glob("*.pkl"):
            name = file_path.stem
            collection = _get_collection(name)
            if collection:
                collections.append({
                    "name": name,
                    "id": name,
                    "metadata": {},
                    "count": collection.count()
                })
        
        return {
            "collections": collections,
            "count": len(collections)
        }
    except Exception as e:
        logger.error(f"Error listing collections: {e}")
        raise


def get_collection_info(collection_name: str) -> Dict[str, Any]:
    """Get collection information"""
    try:
        collection = _get_collection(collection_name)
        if not collection:
            raise ValueError(f"Collection '{collection_name}' does not exist.")
        
        return {
            "collection_name": collection_name,
            "id": collection_name,
            "metadata": {},
            "count": collection.count()
        }
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error getting collection info: {e}")
        raise
