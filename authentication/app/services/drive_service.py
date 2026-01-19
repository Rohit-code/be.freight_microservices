"""Google Drive API service"""
from typing import Optional, Dict, Any, List
from ..utils.google_api import get_drive_service
from ..models import User


async def list_drive_files(
    user: User,
    max_results: int = 50,
    page_token: Optional[str] = None,
    mime_type: Optional[str] = None
) -> Dict[str, Any]:
    """List files in Google Drive with pagination"""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    
    service = await get_drive_service(user)
    
    def _list_files():
        files_request = service.files().list(
            pageSize=max_results,
            fields="nextPageToken, files(id, name, mimeType, size, createdTime, modifiedTime, webViewLink)"
        )
        
        if page_token:
            files_request.pageToken(page_token)
        
        if mime_type:
            files_request.q(f"mimeType='{mime_type}'")
        
        return files_request.execute()
    
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as executor:
        results = await loop.run_in_executor(executor, _list_files)
    
    files = results.get('files', [])
    next_page_token = results.get('nextPageToken')
    
    return {
        'files': files,
        'total': len(files),
        'nextPageToken': next_page_token,
        'hasMore': bool(next_page_token)
    }
