"""AI Service for OpenAI integration"""
from typing import Optional, List, Dict, Any
from ..core.config import settings
import os

# Initialize OpenAI client
try:
    from openai import OpenAI
    openai_api_key = os.getenv('OPENAI_API_KEY', '')
    client = OpenAI(api_key=openai_api_key) if openai_api_key else None
except ImportError:
    client = None
    openai_api_key = ''


def is_ai_available() -> bool:
    """Check if OpenAI API is configured"""
    return client is not None and openai_api_key != ''


def chat_completion(messages: List[Dict[str, str]], model: str = "gpt-4o-mini", temperature: float = 0.7) -> Optional[str]:
    """Send a chat completion request to OpenAI"""
    if not is_ai_available():
        raise ValueError('OpenAI API key not configured')
    
    try:
        response = client.chat.completions.create(
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


def general_chat(message: str, conversation_history: List[Dict[str, str]] = None) -> str:
    """General chat completion"""
    messages = [
        {"role": "system", "content": "You are a helpful AI assistant integrated into a freight forwarding application."}
    ]
    
    if conversation_history:
        messages.extend(conversation_history)
    
    messages.append({"role": "user", "content": message})
    
    return chat_completion(messages) or "I'm sorry, I couldn't process your request."
