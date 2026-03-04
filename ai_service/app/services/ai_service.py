"""AI Service for OpenAI integration"""
from typing import Optional, List, Dict, Any
from ..core.config import settings
import os
import logging

logger = logging.getLogger(__name__)

# Initialize OpenAI client lazily to avoid blocking startup
_client = None
_openai_api_key = None

def _get_openai_client():
    """Lazy initialization of OpenAI client"""
    global _client, _openai_api_key
    if _client is None:
        try:
            from openai import OpenAI
            _openai_api_key = os.getenv('OPENAI_API_KEY', settings.openai_api_key)
            if _openai_api_key:
                _client = OpenAI(api_key=_openai_api_key)
                logger.info("OpenAI client initialized successfully")
            else:
                logger.warning("OpenAI API key not configured")
        except ImportError:
            logger.warning("OpenAI library not installed")
        except Exception as e:
            logger.error(f"Error initializing OpenAI client: {e}")
    return _client

# For backward compatibility
client = None  # Will be set lazily
openai_api_key = ''  # Will be set lazily


def is_ai_available() -> bool:
    """Check if OpenAI API is configured"""
    global client, openai_api_key
    client = _get_openai_client()
    openai_api_key = _openai_api_key or ''
    return client is not None and openai_api_key != ''


def chat_completion(messages: List[Dict[str, str]], model: str = "gpt-4o-mini", temperature: float = 0.7) -> Optional[str]:
    """Send a chat completion request to OpenAI"""
    if not is_ai_available():
        raise ValueError('OpenAI API key not configured')
    
    try:
        ai_client = _get_openai_client()
        if not ai_client:
            raise ValueError('OpenAI client not initialized')
        response = ai_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature
        )
        return response.choices[0].message.content
    except Exception as e:
        raise ValueError(f'OpenAI API error: {str(e)}')


def analyze_email(email_content: str, subject: str = "", from_sender: str = "") -> Dict[str, Any]:
    """Analyze an email and extract key information"""
    full_email = f"Subject: {subject}\nFrom: {from_sender}\n\n{email_content}"
    
    prompt = f"""Analyze the following email and provide:
1. A brief summary (2-3 sentences)
2. Key points or action items
3. Sentiment (positive, neutral, or negative)
4. Priority level (high, medium, or low)
5. Suggested response (if applicable)

Email:
{full_email}

Please format your response as JSON with keys: summary, keyPoints, sentiment, priority, suggestedResponse"""
    
    messages = [
        {"role": "system", "content": "You are an email analysis assistant. Always respond with valid JSON."},
        {"role": "user", "content": prompt}
    ]
    
    try:
        response = chat_completion(messages, temperature=0.3)
        if response:
            import json
            return json.loads(response)
    except Exception as e:
        pass
    
    return {
        "summary": email_content[:200],
        "keyPoints": [],
        "sentiment": "neutral",
        "priority": "medium",
        "suggestedResponse": ""
    }


def generate_email_response(email_content: str, subject: str = "", tone: str = "professional") -> str:
    """Generate a response to an email"""
    prompt = f"""Write a {tone} email response to the following email:

Subject: {subject}

{email_content}

Response:"""
    
    messages = [
        {"role": "system", "content": f"You are a helpful assistant that writes {tone} email responses."},
        {"role": "user", "content": prompt}
    ]
    
    return chat_completion(messages, temperature=0.7) or "Unable to generate response"


def analyze_spreadsheet_data(data: List[List[str]], context: str = "") -> Dict[str, Any]:
    """Analyze spreadsheet data and provide insights"""
    data_text = "\n".join(["\t".join(row) for row in data[:50]])
    
    prompt = f"""Analyze the following spreadsheet data and provide:
1. A brief overview of what the data represents
2. Key insights or patterns
3. Notable trends or anomalies
4. Recommendations (if applicable)

{context}

Data:
{data_text}

Please format your response as JSON with keys: overview, insights, trends, recommendations"""
    
    messages = [
        {"role": "system", "content": "You are a data analysis assistant. Always respond with valid JSON."},
        {"role": "user", "content": prompt}
    ]
    
    try:
        response = chat_completion(messages, temperature=0.3)
        if response:
            import json
            return json.loads(response)
    except Exception as e:
        pass
    
    return {
        "overview": "Data analysis unavailable",
        "insights": [],
        "trends": [],
        "recommendations": []
    }


def analyze_document(content: str, title: str = "") -> Dict[str, Any]:
    """Analyze a document and extract key information"""
    full_doc = f"Title: {title}\n\n{content[:5000]}"
    
    prompt = f"""Analyze the following document and provide:
1. A brief summary
2. Main topics or themes
3. Key points
4. Action items (if any)

Document:
{full_doc}

Please format your response as JSON with keys: summary, topics, keyPoints, actionItems"""
    
    messages = [
        {"role": "system", "content": "You are a document analysis assistant. Always respond with valid JSON."},
        {"role": "user", "content": prompt}
    ]
    
    try:
        response = chat_completion(messages, temperature=0.3)
        if response:
            import json
            return json.loads(response)
    except Exception as e:
        pass
    
    return {
        "summary": content[:200],
        "topics": [],
        "keyPoints": [],
        "actionItems": []
    }


def analyze_rate_sheet(
    parsed_data: Dict[str, Any],
    file_name: str,
    existing_rate_sheets: Optional[List[Dict[str, Any]]] = None,
    prompt: Optional[str] = None
) -> Dict[str, Any]:
    """Analyze a rate sheet and extract structured data"""
    import json
    
    # Use provided prompt (from rate sheet service) or build default one
    if prompt:
        # Use the comprehensive prompt provided by rate sheet service
        user_prompt = prompt
    else:
        # Build a basic prompt if none provided
        user_prompt = f"""You are an expert freight forwarding rate sheet analyzer. Analyze the following rate sheet file and extract structured data.

FILE NAME: {file_name}

PARSED DATA STRUCTURE:
{json.dumps(parsed_data, indent=2, default=str)}

TASK:
1. Identify the rate sheet type (ocean_freight, air_freight, land_freight, multimodal, unknown)
2. Extract carrier/shipping line name
3. Identify validity period (valid_from, valid_to, effective_date)
4. Extract all routes with origin/destination ports, routing, transit times, pricing tiers
5. Extract surcharges (BAF, CAF, EBS, PSS, etc.)
6. Extract additional charges
7. Extract remarks and special conditions

Return a JSON object with rate_sheet_type, carrier_name, validity, routes, relationships, etc.
"""
        # Add existing rate sheets context if provided
        if existing_rate_sheets:
            user_prompt += f"\n\nEXISTING RATE SHEETS (for relationship detection):\n{json.dumps(existing_rate_sheets, indent=2, default=str)}"
    
    messages = [
        {"role": "system", "content": "You are an expert freight forwarding rate sheet analyzer. Always respond with valid JSON only, no markdown formatting."},
        {"role": "user", "content": user_prompt}
    ]
    
    try:
        response = chat_completion(messages, temperature=0.3)
        if response:
            # Try to parse JSON from response
            # Sometimes the response might have markdown code blocks
            cleaned_response = response.strip()
            if "```json" in cleaned_response:
                cleaned_response = cleaned_response.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned_response:
                cleaned_response = cleaned_response.split("```")[1].split("```")[0].strip()
            
            analysis = json.loads(cleaned_response)
            return {"analysis": analysis}
    except json.JSONDecodeError as e:
        # If JSON parsing fails, try to extract JSON from response
        import re
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            try:
                analysis = json.loads(json_match.group())
                return {"analysis": analysis}
            except:
                pass
    except Exception as e:
        # Log error but continue to fallback
        pass
    
    # Fallback response
    return {
        "analysis": {
            "rate_sheet_type": "unknown",
            "carrier_name": None,
            "title": file_name,
            "validity": {
                "valid_from": None,
                "valid_to": None,
                "effective_date": None
            },
            "routes": [],
            "relationships": {
                "is_related": False,
                "relationship_type": "independent",
                "related_to_rate_sheets": [],
                "confidence_score": 0,
                "reasoning": "AI analysis failed"
            },
            "detected_format": "unknown",
            "confidence_score": 0,
            "extraction_notes": "AI analysis unavailable"
        }
    }


def general_chat(message: str, conversation_history: List[Dict[str, str]] = None) -> str:
    """General chat completion"""
    messages = [
        {"role": "system", "content": "You are a helpful AI assistant integrated into a freight forwarding application."}
    ]
    
    if conversation_history:
        messages.extend(conversation_history)
    
    messages.append({"role": "user", "content": message})
    
    return chat_completion(messages) or "I'm sorry, I couldn't process your request."
