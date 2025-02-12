from fastapi import APIRouter, UploadFile, File, HTTPException
import base64
import requests
import os
import logging

import os
from dotenv import load_dotenv

load_dotenv() 

router = APIRouter(prefix="/api/voice_chat", tags=["Voice Chat"])  # Using prefix and tags

API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
VOICE_API_KEY = os.getenv("ZHIPU_API_KEY")

logging.basicConfig(level=logging.INFO)

def encode_audio_to_base64(audio_file_path):
    with open(audio_file_path, "rb") as audio_file:
        return base64.b64encode(audio_file.read()).decode("utf-8")

@router.post("/")
async def voice_chat(file: UploadFile = File(...)):
    """
    Receive user audio files, call the large model interface, and return text and audio responses
    """
    audio_path = f"temp_{file.filename}"
    try:
        with open(audio_path, "wb") as buffer:
            buffer.write(await file.read())

        encoded_audio = encode_audio_to_base64(audio_path)
        payload = {
            "model": "glm-4-voice",
            "messages": [{"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": encoded_audio, "format": "wav"}}]}],
            "max_tokens": 1024
        }
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {VOICE_API_KEY}"}

        response = requests.post(API_URL, headers=headers, json=payload, timeout=15)
        os.remove(audio_path)

        if response.status_code == 200:
            result = response.json()
            text_response = result.get("choices", [{}])[0].get("message", {}).get("content", "No text response received.")
            audio_data_base64 = result.get("choices", [{}])[0].get("message", {}).get("audio", {}).get("data", "")
            return {"response": text_response, "audio": audio_data_base64}
        else:
            raise HTTPException(status_code=500, detail=f"API Error: {response.status_code}, {response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
