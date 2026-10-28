from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict
import os
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

from module.llm_clients import call_codellama, call_deepseek, call_gemini, get_model_names
from module.agentic_workflow import run_hybrid_workflow  # NEW: Hybrid workflow

app = FastAPI(title="HAVELSAN Hybrid Code Generator")

# Static files setup
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class PromptRequest(BaseModel):
    prompt: str
    static_weight: float = 0.7
    llm_weight: float = 0.3
    metric_weights: Dict[str, int] = None

@app.get("/", response_class=HTMLResponse)
def serve_index():
    with open("templates/index.html", "r", encoding="utf-8") as file:
        return file.read()

@app.get("/models")
def get_models_endpoint():
    """Return configured model names."""
    return get_model_names()

@app.post("/generate")
def generate_endpoint(req: PromptRequest) -> Dict:
    """
    Hybrid Workflow Endpoint
    1. İlk tur: 3 model kod üretir
    2. 4 metrikle analiz → Kazanan seçilir  
    3. Eşik kontrolü:
       - >= 80 → Direkt çıktı
       - < 80 → Feedback döngüsü (sadece kazananla)
    """
    result = run_hybrid_workflow(
        prompt=req.prompt,
        quality_threshold=85.0,
        max_iterations=11,
        static_weight=req.static_weight,
        llm_weight=req.llm_weight,
        metric_weights=req.metric_weights
    )
    return result

if __name__ == "__main__":
    import uvicorn
    # Set a very high keep-alive timeout (e.g. 1 hour = 3600 seconds)
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True, timeout_keep_alive=3600)