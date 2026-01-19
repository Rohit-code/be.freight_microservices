from fastapi import APIRouter, HTTPException, Request
from typing import List, Dict, Any, Optional
from ..services.vector_service import (
    create_collection,
    add_documents,
    query_collection,
    delete_collection,
    list_collections,
    get_collection_info,
    get_document,
    update_document_metadata,
    delete_document,
)

router = APIRouter(prefix="/api/vector", tags=["vector"])


@router.post("/collections")
async def create_collection_endpoint(request: Request):
    """Create a new collection"""
    try:
        body_data = await request.json()
        collection_name = body_data.get('name')
        
        if not collection_name:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: name",
            )
        
        result = create_collection(collection_name)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create collection: {str(e)}",
        )


@router.post("/collections/{collection_name}/documents")
async def add_documents_endpoint(collection_name: str, request: Request):
    """Add documents to a collection"""
    try:
        body_data = await request.json()
        documents = body_data.get('documents', [])
        metadatas = body_data.get('metadatas', [])
        ids = body_data.get('ids', [])
        
        if not documents:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: documents",
            )
        
        result = add_documents(collection_name, documents, metadatas, ids)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add documents: {str(e)}",
        )


@router.post("/collections/{collection_name}/query")
async def query_collection_endpoint(collection_name: str, request: Request):
    """Query a collection using semantic search"""
    try:
        body_data = await request.json()
        query_texts = body_data.get('query_texts', [])
        n_results = body_data.get('n_results', 10)
        
        if not query_texts:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: query_texts",
            )
        
        result = query_collection(collection_name, query_texts, n_results)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query collection: {str(e)}",
        )


@router.get("/collections/{collection_name}/documents/{doc_id}")
async def get_document_endpoint(collection_name: str, doc_id: str):
    """Get a specific document by ID"""
    try:
        result = get_document(collection_name, doc_id)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get document: {str(e)}",
        )


@router.patch("/collections/{collection_name}/documents/{doc_id}")
async def update_document_metadata_endpoint(collection_name: str, doc_id: str, request: Request):
    """Update document metadata"""
    try:
        body_data = await request.json()
        metadata = body_data.get('metadata', {})
        
        result = update_document_metadata(collection_name, doc_id, metadata)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update document: {str(e)}",
        )


@router.delete("/collections/{collection_name}/documents/{doc_id}")
async def delete_document_endpoint(collection_name: str, doc_id: str):
    """Delete a specific document"""
    try:
        result = delete_document(collection_name, doc_id)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete document: {str(e)}",
        )


@router.delete("/collections/{collection_name}")
async def delete_collection_endpoint(collection_name: str):
    """Delete a collection"""
    try:
        result = delete_collection(collection_name)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete collection: {str(e)}",
        )


@router.get("/collections")
async def list_collections_endpoint():
    """List all collections"""
    try:
        result = list_collections()
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list collections: {str(e)}",
        )


@router.get("/collections/{collection_name}")
async def get_collection_info_endpoint(collection_name: str):
    """Get collection information"""
    try:
        result = get_collection_info(collection_name)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get collection info: {str(e)}",
        )
