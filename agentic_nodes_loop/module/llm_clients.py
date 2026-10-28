import os
import requests
from groq import Groq
from dotenv import load_dotenv, find_dotenv
import time

load_dotenv()

# --- Configuration ---
USE_OLLAMA = os.getenv("USE_OLLAMA", "false").lower() == "true"

# Initialize cloud clients (fallback)
groq_client = None
deepseek_client = None
gemini_client = None

try:
    groq_api_key = os.getenv("GROQ_API_KEY")
    if groq_api_key:
        groq_client = Groq(api_key=groq_api_key)
except Exception as e:
    print(f"Error initializing Groq client: {e}")

# DeepSeek client
try:
    from openai import OpenAI
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_api_key:
        deepseek_client = OpenAI(
            api_key=deepseek_api_key,
            base_url="https://api.deepseek.com"
        )
except Exception as e:
    print(f"Error initializing DeepSeek client: {e}")

# Gemini client
try:
    import google.generativeai as genai
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if gemini_api_key:
        genai.configure(api_key=gemini_api_key)
        gemini_client = genai.GenerativeModel('gemini-2.0-flash-exp')
except Exception as e:
    print(f"Error initializing Gemini client: {e}")


# --- Ollama Functions (conditional import) ---
if USE_OLLAMA:
    try:
        from module.ollama_client import (
            call_coder_1,
            call_coder_2,
            call_coder_3,
            check_ollama_available,
            get_ollama_models
        )
        OLLAMA_AVAILABLE = check_ollama_available()
        if OLLAMA_AVAILABLE:
            print("✅ Ollama aktif - Yerel modeller kullanılacak")
        else:
            print("⚠️ Ollama servisi bulunamadı - Cloud API'lere fallback")
    except ImportError:
        OLLAMA_AVAILABLE = False
        print("⚠️ Ollama modülü bulunamadı - Cloud API'lere fallback")
else:
    OLLAMA_AVAILABLE = False


# --- Code Generation Functions ---

def call_codellama(prompt: str) -> str:
    """
    Generates code using the first model slot.
    
    - Ollama mode: Qwen2.5-Coder (best open-source code model)
    - Cloud mode: Llama 3.3 70B via Groq
    """
    if USE_OLLAMA and OLLAMA_AVAILABLE:
        models = get_ollama_models()
        print(f"  📡 {models['coder_1']} (Ollama) kullanılıyor...")
        return call_coder_1(prompt)
    
    # Fallback to Groq
    if not groq_client:
        return "Groq API Key missing or client init failed."
        
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are an expert Python programmer. Write clean, efficient code. Output ONLY the code or markdown with code blocks. Do not be conversational."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_completion_tokens=2048
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"CodeLlama API Error: {str(e)}"


def call_deepseek(prompt: str) -> str:
    """
    Generates code using the second model slot.
    
    - Ollama mode: DeepSeek-R1 (Ollama)
    - Cloud mode: DeepSeek V3 via DeepSeek API
    """
    if USE_OLLAMA and OLLAMA_AVAILABLE:
        models = get_ollama_models()
        print(f"  📡 {models['coder_2']} (Ollama) kullanılıyor...")
        return call_coder_2(prompt)
    
    # Fallback to DeepSeek API
    if not deepseek_client:
        return "DeepSeek API Key missing or client init failed."
    
    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are an expert Python programmer. Write clean, efficient code. Output ONLY the code."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=2048
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"DeepSeek API Error: {str(e)}"


def call_gemini(prompt: str) -> str:
    """
    Generates code using the third model slot.
    
    - Ollama mode: Llama 3.2 (great instruction following)
    - Cloud mode: Gemini 2.0 Flash via Google API
    
    Includes retry with exponential backoff for 429 rate-limit errors.
    """
    if USE_OLLAMA and OLLAMA_AVAILABLE:
        models = get_ollama_models()
        print(f"  📡 {models['coder_3']} (Ollama) kullanılıyor...")
        return call_coder_3(prompt)
    
    # Fallback to Gemini API
    if not gemini_client:
        return "Gemini API Key missing or client init failed."

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = gemini_client.generate_content(
                f"You are an expert Python programmer. Write clean, efficient code. Output ONLY the code.\n\n{prompt}",
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 2048
                }
            )
            return response.text
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "rate limit" in err_msg.lower():
                if attempt < max_retries - 1:
                    backoff = 2 ** attempt * 5
                    print(f"Gemini rate limit hit, sleeping {backoff}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(backoff)
                    continue
            return f"Gemini API Error: {err_msg}"
    return "Gemini API Error: exceeded retry attempts"


# --- Model Names for Display ---

def get_model_names() -> dict:
    """Return display names for the current model configuration."""
    # .env'yi yeniden yükle (sunucu yeniden başlatılmadan model değişimine izin verir)
    load_dotenv(find_dotenv(), override=True)
    use_ollama_dynamic = os.getenv("USE_OLLAMA", "false").lower() == "true"
    
    if use_ollama_dynamic:
        try:
            from module.ollama_client import get_ollama_models, check_ollama_available
            if check_ollama_available():
                models = get_ollama_models()
                return {
                    "model_1": models["coder_1"],
                    "model_2": models["coder_2"],
                    "model_3": models["coder_3"]
                }
        except Exception as e:
            print(f"Error getting dynamic model names: {e}")
            
    return {
        "model_1": "Llama 3.3 70B (Groq)",
        "model_2": "DeepSeek V3",
        "model_3": "Gemini 2.0 Flash"
    }

