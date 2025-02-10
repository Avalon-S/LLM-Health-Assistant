from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
import os
import logging
from pydantic import BaseModel
import requests
from jose import jwt, JWTError
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone
import os
from dotenv import load_dotenv

load_dotenv() 

logging.basicConfig(level=logging.INFO)

# Initialize APIRouter
router = APIRouter(prefix="/api/health_chat", tags=["Health Chat"])

# ====== Zhipu API Configuration ======
ZHIPU_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY")

# ====== Pinecone Configuration ======
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = "healthassistant"
embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

pc = Pinecone(api_key=PINECONE_API_KEY, environment="us-east-1-aws")
pinecone_index = pc.Index(INDEX_NAME)

# ====== PubMed API Configuration ======
PUBMED_API_URL = "http://localhost:8000/api/query_pubmed"

# JWT Configuration
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Verify JWT
def verify_token(token: str):
    """
    Verify JWT and extract username
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise JWTError
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

# Keyword Matching Rules
PINECONE_KEYWORDS = [
    "my personal info", "personal history", "previous conversation", "past chat", "my data",
    "my name", "my age", "my profile", "my records", "my history"
]
PUBMED_KEYWORDS = [
    "paper", "study", "research", "pubmed", "clinical trial", "medical journal", "scientific article",
    "medical research", "case study", "clinical evidence"
]

# Pydantic Request Model
class ChatRequest(BaseModel):
    prompt: str

def should_query_pinecone(user_input: str) -> bool:
    """
    Return True if the user's query contains Pinecone-related keywords
    """
    return any(keyword in user_input.lower() for keyword in PINECONE_KEYWORDS)

def should_query_pubmed(user_input: str) -> bool:
    """
    Return True if the user's query contains PubMed-related keywords
    """
    return any(keyword in user_input.lower() for keyword in PUBMED_KEYWORDS)

def query_pinecone(user_query: str, username: str, top_k: int = 3):
    """
    Query Pinecone for historical chat records
    """
    try:
        query_vector = embedding_model.encode([user_query])[0].tolist()
        results = pinecone_index.query(vector=query_vector, top_k=top_k, include_metadata=True, namespace=username)
        return [r["metadata"]["text"] for r in results.get("matches", [])] if results.get("matches") else []
    except Exception as e:
        logging.error(f"Error querying Pinecone: {e}")
        return []

def query_pubmed(user_query: str):
    """
    Query PubMed literature through `query_pubmed.py`
    """
    try:
        response = requests.post(PUBMED_API_URL, json={"query": user_query})
        if response.status_code == 200:
            return response.json().get("results", [])
        else:
            logging.error(f"PubMed API Error: {response.status_code}, {response.text}")
            return ["Error fetching PubMed data"]
    except Exception as e:
        logging.error(f"Error connecting to PubMed API: {e}")
        return ["Error connecting to PubMed API"]

import re

def store_chat_in_pinecone(username: str, user_input: str, model_response: str):
    """
    Store user chat history in Pinecone
    """
    try:
        # Ensure Vector ID contains only ASCII characters
        sanitized_user_input = re.sub(r'[^\x00-\x7F]+', '', user_input)  # Remove non-ASCII characters
        user_vector_id = f"user-{username}-{sanitized_user_input[:10]}"
        model_vector_id = f"model-{username}-{sanitized_user_input[:10]}"

        vector = embedding_model.encode([user_input])[0].tolist()
        pinecone_index.upsert([(user_vector_id, vector, {"text": user_input})], namespace=username)

        vector_response = embedding_model.encode([model_response])[0].tolist()
        pinecone_index.upsert([(model_vector_id, vector_response, {"text": model_response})], namespace=username)
    except Exception as e:
        logging.error(f"Error storing chat in Pinecone: {e}")

@router.post("/")
def chat_with_model(request: ChatRequest, token: str = Depends(oauth2_scheme)):
    """
    Process user health consultation requests
    """
    username = verify_token(token)
    logging.info(f"Received request from {username}: prompt={request.prompt}")

    user_input = request.prompt
    retrieved_context = ""

    # Query Pinecone for historical chat records
    if should_query_pinecone(user_input):
        chat_history = query_pinecone(user_input, username)
        if chat_history:
            retrieved_context += "### Previous Conversations:\n" + "\n".join(chat_history) + "\n"

    # Query PubMed for related research
    if should_query_pubmed(user_input):
        pubmed_results = query_pubmed(user_input)
        if pubmed_results:
            retrieved_context += "### Relevant Research from PubMed:\n" + "\n".join(pubmed_results) + "\n"

    # Construct final prompt
    final_prompt = f"""
    You are an AI health assistant. Answer the user's question concisely and accurately.

    **User Question:** {user_input}

    **Relevant Context (from Expert System):** {retrieved_context}

    Provide a well-structured, professional response with a disclaimer that you are not a substitute for professional medical advice.
    """

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ZHIPU_API_KEY}"
    }
    payload = {
        "model": "glm-4-plus",
        "messages": [{"role": "user", "content": final_prompt}],
        "temperature": 0.5,
        "max_tokens": 1000
    }

    response = requests.post(ZHIPU_API_URL, headers=headers, json=payload)

    if response.status_code == 200:
        model_response = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        store_chat_in_pinecone(username, user_input, model_response)
        return {"response": model_response}
    else:
        logging.error(f"Zhipu API Error: {response.status_code}, {response.text}")
        raise HTTPException(status_code=500, detail=f"Zhipu API Error: {response.status_code}, {response.text}")
