"""Gmail API service"""
import base64
from typing import Optional, List, Dict, Any
from googleapiclient.discovery import build
from ..utils.google_api import get_gmail_service, get_user_google_credentials
from ..models import User


async def list_emails(user: User, max_results: int = 20, page_token: Optional[str] = None) -> Dict[str, Any]:
    """List Gmail messages with pagination"""
    import asyncio
    
    # Build credentials in async context, then use sync Gmail client in a thread.
    credentials = await get_user_google_credentials(user)

    def _fetch_messages_sync():
        service = build('gmail', 'v1', cache_discovery=False, credentials=credentials)
        if hasattr(service, "_http") and service._http:
            service._http.timeout = 20

        list_params = {
            'userId': 'me',
            'maxResults': max_results
        }
        if page_token:
            list_params['pageToken'] = page_token

        results = service.users().messages().list(**list_params).execute()
        messages = results.get('messages', [])
        next_page_token = results.get('nextPageToken')

        message_list = []
        for msg in messages:
            message = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata',
                metadataHeaders=['From', 'To', 'Cc', 'Bcc', 'Subject', 'Date']
            ).execute()

            headers = {h['name']: h['value'] for h in message['payload'].get('headers', [])}

            def count_attachments(part):
                """Recursively count attachments in message parts"""
                count = 0
                if part.get('filename') and part.get('body', {}).get('attachmentId'):
                    count += 1
                if 'parts' in part:
                    for subpart in part['parts']:
                        count += count_attachments(subpart)
                return count

            payload = message.get('payload', {})
            attachment_count = count_attachments(payload)
            has_attachments = attachment_count > 0

            message_list.append({
                'id': message['id'],
                'threadId': message['threadId'],
                'snippet': message.get('snippet', ''),
                'from': headers.get('From', ''),
                'to': headers.get('To', ''),
                'cc': headers.get('Cc', ''),
                'bcc': headers.get('Bcc', ''),
                'subject': headers.get('Subject', ''),
                'date': headers.get('Date', ''),
                'hasAttachments': has_attachments,
                'attachmentCount': attachment_count,
            })

        return {
            'messages': message_list,
            'total': len(message_list),
            'nextPageToken': next_page_token,
            'hasMore': bool(next_page_token)
        }

    return await asyncio.to_thread(_fetch_messages_sync)


async def get_email_detail(user: User, message_id: str) -> Dict[str, Any]:
    """Get full details of a specific Gmail message"""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    
    service = await get_gmail_service(user)
    
    def _get_message():
        message = service.users().messages().get(
            userId='me',
            id=message_id,
            format='full',
            metadataHeaders=['From', 'To', 'Cc', 'Bcc', 'Subject', 'Date', 'Delivered-To']
        ).execute()
        return message
    
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as executor:
        message = await loop.run_in_executor(executor, _get_message)
    
    payload = message.get('payload', {})
    
    # Extract headers recursively
    def extract_headers(part, collected_headers=None):
        if collected_headers is None:
            collected_headers = {}
        
        if 'headers' in part:
            for header in part['headers']:
                header_name = header['name']
                header_value = header['value']
                if header_name not in collected_headers:
                    collected_headers[header_name] = header_value
                elif header_name == 'To' and not collected_headers.get('To'):
                    collected_headers[header_name] = header_value
        
        if 'parts' in part:
            for subpart in part['parts']:
                extract_headers(subpart, collected_headers)
        
        return collected_headers
    
    headers = extract_headers(payload)
    
    # Check if this is a sent message
    label_ids = message.get('labelIds', [])
    is_sent = 'SENT' in label_ids
    
    to_header = headers.get('To', '')
    if not to_header and is_sent:
        to_header = headers.get('Delivered-To', '') or headers.get('Envelope-To', '')
    
    # Extract email body
    html_body = ''
    plain_body = ''
    
    def extract_body(part):
        nonlocal html_body, plain_body
        
        if part.get('mimeType') == 'text/plain':
            data = part.get('body', {}).get('data', '')
            if data:
                text = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                if text and not plain_body:
                    plain_body = text
        elif part.get('mimeType') == 'text/html':
            data = part.get('body', {}).get('data', '')
            if data:
                html = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                if html and not html_body:
                    html_body = html
        
        if 'parts' in part:
            for subpart in part['parts']:
                extract_body(subpart)
    
    extract_body(payload)
    body = html_body if html_body else plain_body
    
    # Extract attachments
    attachments = []
    
    def extract_attachments(part):
        if part.get('filename') and part.get('body', {}).get('attachmentId'):
            attachments.append({
                'filename': part.get('filename', ''),
                'mimeType': part.get('mimeType', ''),
                'size': part.get('body', {}).get('size', 0),
                'attachmentId': part.get('body', {}).get('attachmentId', ''),
            })
        
        if 'parts' in part:
            for subpart in part['parts']:
                extract_attachments(subpart)
    
    extract_attachments(payload)
    
    return {
        'id': message['id'],
        'threadId': message['threadId'],
        'snippet': message.get('snippet', ''),
        'from': headers.get('From', ''),
        'to': to_header,
        'cc': headers.get('Cc', ''),
        'bcc': headers.get('Bcc', ''),
        'subject': headers.get('Subject', ''),
        'date': headers.get('Date', ''),
        'body': body,
        'attachments': attachments,
        'attachmentCount': len(attachments),
        'isSent': is_sent,
    }


async def download_attachment(user: User, message_id: str, attachment_id: str) -> bytes:
    """Download a Gmail attachment"""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    
    service = await get_gmail_service(user)
    
    def _get_attachment():
        attachment = service.users().messages().attachments().get(
            userId='me',
            messageId=message_id,
            id=attachment_id
        ).execute()
        return base64.urlsafe_b64decode(attachment['data'])
    
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as executor:
        file_data = await loop.run_in_executor(executor, _get_attachment)
    
    return file_data


async def get_user_signature(user: User, token: Optional[str] = None):
    """Get user's email signature from user service, or extract from Gmail sent messages as fallback"""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    import re
    import httpx
    from ..core.config import settings
    
    # First, try to fetch signature from user service
    if token:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{settings.USER_SERVICE_URL}/api/user/profiles/me",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    profile_data = response.json()
                    signature = profile_data.get('signature')
                    if signature and signature.strip():
                        # Convert plain text signature to HTML if needed
                        # Replace newlines with <br> for HTML
                        signature_html = signature.replace('\n', '<br>')
                        return signature_html, None
        except Exception as e:
            # Log error but continue to fallback
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to fetch signature from user service: {e}")
    
    # Fallback: Extract signature from Gmail sent messages
    service = await get_gmail_service(user)
    
    def _get_recent_messages():
        results = service.users().messages().list(
            userId='me',
            q='in:sent',
            maxResults=10
        ).execute()
        return results.get('messages', [])
    
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as executor:
        messages = await loop.run_in_executor(executor, _get_recent_messages)
    
    if not messages:
        return None, None
    
    for msg in messages:
        try:
            def _get_message():
                return service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='full'
                ).execute()
            
            sent_message = await loop.run_in_executor(executor, _get_message)
            payload = sent_message.get('payload', {})
            message_id = msg['id']
            
            # Extract HTML and images
            html_parts = []
            embedded_images = {}
            all_parts = []
            
            def extract_html_and_images(part):
                mime_type = part.get('mimeType', '')
                all_parts.append(part)
                
                if mime_type.startswith('multipart/'):
                    if 'parts' in part:
                        for subpart in part['parts']:
                            extract_html_and_images(subpart)
                    return
                
                headers = part.get('headers', [])
                content_id = None
                for header in headers:
                    if header.get('name', '').lower() == 'content-id':
                        content_id = header.get('value', '').strip('<>')
                
                if mime_type == 'text/html':
                    data = part.get('body', {}).get('data', '')
                    if data:
                        html_body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                        html_parts.append(html_body)
                
                if mime_type.startswith('image/'):
                    attachment_id = part.get('body', {}).get('attachmentId')
                    if attachment_id:
                        img_cid = content_id or part.get('filename', f'image_{len(embedded_images)}')
                        embedded_images[img_cid] = {
                            'attachment_id': attachment_id,
                            'mime_type': mime_type,
                            'filename': part.get('filename', f'image.{mime_type.split("/")[1]}'),
                            'content_id': content_id
                        }
                
                if 'parts' in part:
                    for subpart in part['parts']:
                        extract_html_and_images(subpart)
            
            extract_html_and_images(payload)
            
            # Download images asynchronously
            for img_cid, img_info in list(embedded_images.items()):
                if 'attachment_id' in img_info:
                    try:
                        def _get_attachment():
                            attachment = service.users().messages().attachments().get(
                                userId='me',
                                messageId=message_id,
                                id=img_info['attachment_id']
                            ).execute()
                            return base64.urlsafe_b64decode(attachment['data'])
                        
                        image_data = await loop.run_in_executor(executor, _get_attachment)
                        embedded_images[img_cid]['data'] = image_data
                        del embedded_images[img_cid]['attachment_id']
                    except Exception:
                        del embedded_images[img_cid]
            
            html_content = ''.join(html_parts)
            
            if not html_content:
                continue
            
            # Extract signature from gmail_signature div
            sig_match = re.search(r'<div[^>]*class=["\']gmail_signature["\'][^>]*>(.*)', html_content, re.DOTALL | re.IGNORECASE)
            if sig_match:
                remaining = sig_match.group(0)
                div_count = remaining.count('<div') - remaining.count('</div>')
                pos = len(sig_match.group(0))
                signature_html = sig_match.group(0)
                
                while pos < len(remaining) and div_count > 0:
                    next_close = remaining.find('</div>', pos)
                    if next_close == -1:
                        signature_html += remaining[pos:]
                        break
                    signature_html += remaining[pos:next_close + 6]
                    div_count -= 1
                    pos = next_close + 6
                    if div_count == 0:
                        break
                
                signature = signature_html.strip()
                if signature and len(signature) > 20:
                    return signature, embedded_images
            
            # Try delimiter-based extraction
            for delimiter in [
                r'<br[^>]*>\s*--\s*<br[^>]*>',
                r'\n--\s*\n',
            ]:
                parts = re.split(delimiter, html_content, flags=re.IGNORECASE | re.DOTALL)
                if len(parts) > 1:
                    signature = parts[-1].strip()
                    if signature and len(signature) > 10:
                        return signature, embedded_images
                        
        except Exception:
            continue
    
    return None, None


async def send_email(
    user: User,
    to: str,
    subject: str,
    body: str,
    include_signature: bool = True,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """Send an email via Gmail with signature support"""
    import asyncio
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.mime.image import MIMEImage
    import re

    credentials = await get_user_google_credentials(user)
    
    # Get signature if requested
    signature_html = None
    embedded_images = None
    if include_signature:
        signature_html, embedded_images = await get_user_signature(user, token)
    
    # Determine if body is HTML
    is_html = '<' in body and '>' in body and ('<br' in body or '<div' in body or '<p' in body)
    
    if is_html or signature_html:
        if embedded_images:
            msg = MIMEMultipart('related')
        else:
            msg = MIMEMultipart('alternative')
        
        alt_part = MIMEMultipart('alternative')
        
        # Plain text version
        plain_body = body
        if signature_html:
            plain_signature = re.sub(r'<[^>]+>', '', signature_html)
            plain_signature = plain_signature.replace('&nbsp;', ' ')
            plain_signature = re.sub(r'\s+', ' ', plain_signature).strip()
            plain_body += '\n\n--\n' + plain_signature
        
        alt_part.attach(MIMEText(plain_body, 'plain'))
        
        # HTML version
        html_body = body
        if signature_html:
            html_body += '<br><br>--<br>' + signature_html
        elif not is_html:
            html_body = html_body.replace('\n', '<br>')
        
        alt_part.attach(MIMEText(html_body, 'html'))
        msg.attach(alt_part)
        
        # Attach embedded images
        if embedded_images:
            for content_id, image_info in embedded_images.items():
                img = MIMEImage(image_info['data'], _subtype=image_info['mime_type'].split('/')[1])
                img.add_header('Content-ID', f'<{content_id}>')
                img.add_header('Content-Disposition', 'inline', filename=image_info['filename'])
                msg.attach(img)
    else:
        msg = MIMEText(body)
        if signature_html:
            plain_signature = re.sub(r'<[^>]+>', '', signature_html)
            plain_signature = plain_signature.replace('&nbsp;', ' ')
            plain_signature = re.sub(r'\s+', ' ', plain_signature).strip()
            body += '\n\n--\n' + plain_signature
            msg = MIMEText(body)
    
    msg['To'] = to
    msg['Subject'] = subject
    
    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')

    def _send_sync():
        service = build('gmail', 'v1', cache_discovery=False, credentials=credentials)
        if hasattr(service, "_http") and service._http:
            service._http.timeout = 20
        return service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()

    result = await asyncio.to_thread(_send_sync)
    
    return {
        'message': 'Email sent successfully',
        'messageId': result.get('id'),
        'signature_included': bool(signature_html) if include_signature else False
    }


# ========== GMAIL PUSH NOTIFICATIONS (PUB/SUB) ==========

async def setup_gmail_watch(user: User) -> Dict[str, Any]:
    """
    Set up Gmail push notifications for a user.
    This subscribes the user's Gmail to send notifications via Pub/Sub.
    Must be renewed every 7 days (Gmail requirement).
    """
    import asyncio
    from ..core.config import settings
    
    if not settings.gmail_pubsub_topic:
        raise ValueError("Gmail Pub/Sub topic not configured")
    
    credentials = await get_user_google_credentials(user)
    
    def _setup_watch_sync():
        service = build('gmail', 'v1', cache_discovery=False, credentials=credentials)
        
        # Set up watch request
        watch_request = {
            'topicName': settings.gmail_pubsub_topic,
            'labelIds': ['INBOX'],  # Watch inbox only
            'labelFilterBehavior': 'INCLUDE'
        }
        
        result = service.users().watch(userId='me', body=watch_request).execute()
        return result
    
    result = await asyncio.to_thread(_setup_watch_sync)
    
    return {
        'historyId': result.get('historyId'),
        'expiration': result.get('expiration'),
        'message': 'Gmail watch set up successfully'
    }


async def stop_gmail_watch(user: User) -> Dict[str, Any]:
    """Stop Gmail push notifications for a user"""
    import asyncio
    
    credentials = await get_user_google_credentials(user)
    
    def _stop_watch_sync():
        service = build('gmail', 'v1', cache_discovery=False, credentials=credentials)
        service.users().stop(userId='me').execute()
        return True
    
    await asyncio.to_thread(_stop_watch_sync)
    
    return {'message': 'Gmail watch stopped'}


async def get_history_since(user: User, history_id: str, max_results: int = 50) -> Dict[str, Any]:
    """
    Get Gmail history (changes) since a specific historyId.
    Used when we receive a push notification to get new messages.
    """
    import asyncio
    
    credentials = await get_user_google_credentials(user)
    
    def _get_history_sync():
        service = build('gmail', 'v1', cache_discovery=False, credentials=credentials)
        
        try:
            results = service.users().history().list(
                userId='me',
                startHistoryId=history_id,
                historyTypes=['messageAdded'],
                maxResults=max_results
            ).execute()
            
            history = results.get('history', [])
            new_message_ids = []
            
            for record in history:
                messages_added = record.get('messagesAdded', [])
                for msg in messages_added:
                    message = msg.get('message', {})
                    msg_id = message.get('id')
                    if msg_id:
                        new_message_ids.append(msg_id)
            
            return {
                'newMessageIds': list(set(new_message_ids)),  # Remove duplicates
                'historyId': results.get('historyId'),
                'count': len(set(new_message_ids))
            }
            
        except Exception as e:
            # If historyId is too old, Gmail returns 404
            if '404' in str(e) or 'notFound' in str(e):
                return {
                    'newMessageIds': [],
                    'historyId': None,
                    'error': 'History expired, need full sync'
                }
            raise
    
    return await asyncio.to_thread(_get_history_sync)
