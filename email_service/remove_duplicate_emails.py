#!/usr/bin/env python3
"""
Script to find and remove duplicate emails from the vector database.

Duplicates are identified by the same (user_id, gmail_message_id) combination.
This script keeps the first occurrence and removes all duplicates.
"""
import sys
import os
import asyncio
import httpx
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from microservices.email_service.app.core.config import settings
from microservices.email_service.app.services.email_service import EMAILS_COLLECTION, _generate_email_id

async def find_and_remove_duplicates():
    """Find and remove duplicate emails"""
    print("🔍 Finding duplicate emails...")
    
    # We need to query all emails to find duplicates
    # Since there's no "list all" endpoint, we'll use a broad query
    async with httpx.AsyncClient() as client:
        # Query with a very generic term to get all emails
        # We'll get a large number of results
        response = await client.post(
            f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/query",
            json={
                "query_texts": ["email"],
                "n_results": 10000  # Large number to get all emails
            },
            timeout=60.0
        )
        
        if response.status_code != 200:
            print(f"❌ Failed to query emails: HTTP {response.status_code}")
            print(response.text)
            return
        
        data = response.json()
        results = data.get("results", {})
        ids = results.get("ids", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        
        print(f"📊 Found {len(ids)} emails in database")
        
        # Group by (user_id, gmail_message_id) to find duplicates
        email_map = {}  # (user_id, gmail_message_id) -> list of (email_id, metadata)
        duplicates_to_remove = []
        
        for i, metadata in enumerate(metadatas):
            user_id = metadata.get("user_id")
            gmail_message_id = metadata.get("gmail_message_id")
            
            if not user_id or not gmail_message_id:
                continue
            
            key = (str(user_id), gmail_message_id)
            email_id = ids[i]
            
            if key not in email_map:
                email_map[key] = []
            
            email_map[key].append((email_id, metadata))
        
        # Find duplicates
        for key, emails in email_map.items():
            if len(emails) > 1:
                user_id, gmail_message_id = key
                print(f"\n⚠️  Found {len(emails)} duplicates for user_id={user_id}, gmail_message_id={gmail_message_id}")
                
                # Keep the first one (oldest by created_at if available)
                emails_sorted = sorted(emails, key=lambda x: x[1].get("created_at", ""))
                keep_email = emails_sorted[0]
                remove_emails = emails_sorted[1:]
                
                print(f"   ✅ Keeping: {keep_email[0]}")
                for email_id, _ in remove_emails:
                    print(f"   ❌ Removing: {email_id}")
                    duplicates_to_remove.append(email_id)
        
        if not duplicates_to_remove:
            print("\n✅ No duplicates found!")
            return
        
        print(f"\n🗑️  Removing {len(duplicates_to_remove)} duplicate emails...")
        
        # Remove duplicates
        removed_count = 0
        for email_id in duplicates_to_remove:
            delete_response = await client.delete(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/documents/{email_id}",
                timeout=30.0
            )
            
            if delete_response.status_code == 200:
                removed_count += 1
                print(f"   ✅ Removed {email_id}")
            else:
                print(f"   ❌ Failed to remove {email_id}: HTTP {delete_response.status_code}")
        
        print(f"\n✅ Removed {removed_count} duplicate emails!")
        print(f"📊 Remaining emails: {len(ids) - removed_count}")

if __name__ == "__main__":
    asyncio.run(find_and_remove_duplicates())
