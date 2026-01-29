#!/usr/bin/env python3
"""
Migration script to update existing ChromaDB rate sheet documents with pricing data.
Run this ONCE after deploying the fix to embedding_service.py that includes pricing in semantic content.
"""
import asyncio
import sys
import os

# Add the rate_sheet_service to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'rate_sheet_service'))

from rate_sheet_service.app.core.database import AsyncSessionLocal
from rate_sheet_service.app.models.structured_data import RateSheetStructuredData
from rate_sheet_service.app.services.embedding_service import EmbeddingService
from sqlalchemy import select
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def update_chromadb_with_pricing():
    """
    Re-process all rate sheets to add pricing data to ChromaDB.
    """
    logger.info("Starting ChromaDB pricing data migration...")
    
    embedding_service = EmbeddingService()
    
    async with AsyncSessionLocal() as session:
        # Get all active rate sheets
        result = await session.execute(
            select(RateSheetStructuredData).where(
                RateSheetStructuredData.is_active == True
            )
        )
        rate_sheets = result.scalars().all()
        
        logger.info(f"Found {len(rate_sheets)} active rate sheets to update")
        
        for idx, rs in enumerate(rate_sheets, 1):
            try:
                logger.info(f"[{idx}/{len(rate_sheets)}] Updating {rs.file_name} (ID: {rs.rate_sheet_id})")
                
                # Build structured data from JSONB columns
                rate_sheet_data = {
                    "file_name": rs.file_name,
                    "carrier_name": rs.carrier_name,
                    "rate_sheet_type": rs.rate_sheet_type,
                    "title": rs.title,
                    "validity": {
                        "valid_from": rs.valid_from.isoformat() if rs.valid_from else None,
                        "valid_to": rs.valid_to.isoformat() if rs.valid_to else None,
                        "effective_date": rs.effective_date.isoformat() if rs.effective_date else None,
                    },
                    "routes": rs.routes_json or [],
                    "relationships": {
                        "is_related": rs.is_related,
                        "relationship_type": rs.relationship_type,
                        "related_to_rate_sheets": rs.related_rate_sheet_ids or [],
                    },
                    "extraction_notes": f"Migrated to include pricing data on {os.popen('date').read().strip()}"
                }
                
                # Build new semantic content with pricing
                new_content = embedding_service._build_semantic_content(rate_sheet_data, {})
                
                # Update ChromaDB document
                try:
                    # Try to get existing doc first
                    existing = await embedding_service.vector_service.get_document(
                        collection_name="rate_sheets",
                        document_id=rs.rate_sheet_id
                    )
                    
                    if existing:
                        # Update existing document
                        await embedding_service.vector_service.update_document(
                            collection_name="rate_sheets",
                            document_id=rs.rate_sheet_id,
                            document=new_content,
                            metadata={
                                "organization_id": str(rs.organization_id),
                                "user_id": rs.user_id,
                                "file_name": rs.file_name,
                                "carrier_name": rs.carrier_name or "Unknown",
                                "rate_sheet_type": rs.rate_sheet_type or "ocean_freight",
                                "status": rs.status,
                                "migrated_pricing": "true"
                            }
                        )
                        logger.info(f"  ✅ Updated ChromaDB document")
                    else:
                        logger.warning(f"  ⚠️  Document not found in ChromaDB, skipping")
                
                except Exception as e:
                    logger.error(f"  ❌ Error updating ChromaDB: {e}")
                    
            except Exception as e:
                logger.error(f"  ❌ Error processing rate sheet {rs.rate_sheet_id}: {e}", exc_info=True)
    
    logger.info("Migration complete!")


if __name__ == "__main__":
    asyncio.run(update_chromadb_with_pricing())
