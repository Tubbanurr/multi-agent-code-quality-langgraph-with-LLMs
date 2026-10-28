"""
ollama_client.py — Yerel Ollama LLM servisiyle iletişim modülü.

Tasarım Prensipleri:
  - DRY: Üç coder fonksiyonu tek bir _call_coder() yardımcısıyla çalışır.
  - Sabit Sistem Promptları: _SYSTEM_PROMPTS sözlüğünde tek noktada yönetilir.
  - Spesifik Exception: Geniş `except Exception` yerine beklenen tipler yakalanır.
"""

import json
import os
import re
from typing import Any, Dict, Optional

import requests
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(), override=True)

# ---------------------------------------------------------------------------
# Konfigürasyon
# ---------------------------------------------------------------------------

OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Model sistem promptları — her coder için tek noktadan yönetilir (DRY)
_SYSTEM_PROMPTS: Dict[str, str] = {
    "coder_1": (
        "You are an expert Python programmer. Write a full, working Python implementation. "
        "Output ONLY the code. No markdown backticks, no markdown blocks, "
        "no 'Sure, here is...', no explanations. "
        "Just the code itself starting from imports or function definition."
    ),
    "coder_2": (
        "You are an expert Python coder. Output raw Python code ONLY. "
        "STRICTLY FORBIDDEN: Do not write '.ipynb', do not write file names, "
        "do not write explanations. "
        "Start directly with 'import' or 'def'. No markdown backticks."
    ),
    "coder_3": (
        "You are a STRICT Python code generator. Output raw Python code ONLY. "
        "NO markdown, NO explanations, NO conversational text, NO hashtags. "
        "If you cannot generate code, output 'print(\"Error\")'. "
        "Example start: import os"
    ),
}


# ---------------------------------------------------------------------------
# Konfigürasyon Yardımcıları
# ---------------------------------------------------------------------------

def get_ollama_models() -> Dict[str, str]:
    """Her çağrıda .env'yi yeniden okuyarak model listesini döner."""
    load_dotenv(override=True)
    return {
        "judge":   os.getenv("OLLAMA_JUDGE_MODEL",    "deepseek-r1:1.5b"),
        "coder_1": os.getenv("OLLAMA_CODER_MODEL_1",  "qwen2.5-coder:7b"),
        "coder_2": os.getenv("OLLAMA_CODER_MODEL_2",  "qwen2.5-coder:3b"),
        "coder_3": os.getenv("OLLAMA_CODER_MODEL_3",  "gemma2:2b"),
    }


def check_ollama_available() -> bool:
    """Ollama servisinin çalışıp çalışmadığını kontrol eder."""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/version", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def list_ollama_models() -> list:
    """Ollama'da yüklü modellerin listesini döner."""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=10)
        if response.status_code == 200:
            return [m["name"] for m in response.json().get("models", [])]
        return []
    except requests.RequestException:
        return []


# ---------------------------------------------------------------------------
# Generic API Çağrıları
# ---------------------------------------------------------------------------

def call_ollama(
    model: str,
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.1,
    max_tokens: int = 2048,
    timeout: int = 1800,
) -> str:
    """
    Ollama /api/generate uç noktasına tek turlu istek gönderir.

    Returns:
        Üretilen metin veya hata mesajı.
    """
    if not check_ollama_available():
        return "Ollama Error: Service not available. Please start Ollama."

    payload: Dict[str, Any] = {
        "model":  model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if system_prompt:
        payload["system"] = system_prompt

    try:
        response = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json=payload,
            timeout=timeout,
        )
        if response.status_code == 200:
            return response.json().get("response", "")
        return f"Ollama Error: HTTP {response.status_code}"

    except requests.Timeout:
        return f"Ollama Error: Request timeout ({timeout}s)"
    except requests.RequestException as exc:
        return f"Ollama Error: {exc}"


def call_ollama_chat(
    model: str,
    messages: list,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    timeout: int = 1800,
    format_json: bool = False,
) -> str:
    """
    Ollama /api/chat uç noktasına çok turlu mesaj gönderir.

    Args:
        format_json: True ise JSON çıktısı zorunlu kılınır.

    Returns:
        Üretilen metin veya hata mesajı.
    """
    if not check_ollama_available():
        return "Ollama Error: Service not available. Please start Ollama."

    payload: Dict[str, Any] = {
        "model":   model,
        "messages": messages,
        "stream":  False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if format_json:
        payload["format"] = "json"

    try:
        response = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json=payload,
            timeout=timeout,
        )
        if response.status_code == 200:
            return response.json().get("message", {}).get("content", "")
        return f"Ollama Error: HTTP {response.status_code}"

    except requests.Timeout:
        return f"Ollama Error: Request timeout ({timeout}s)"
    except requests.RequestException as exc:
        return f"Ollama Error: {exc}"


# ---------------------------------------------------------------------------
# Kod Doğrulama
# ---------------------------------------------------------------------------

def validate_code(code: str) -> bool:
    """LLM çıktısının geçerli kod olup olmadığını kontrol eder (halüsinasyon tespiti)."""
    if not code:
        return False

    clean     = code.strip().lower()
    JUNK_TAGS = {"ipynb", "untitled", ".py", "markdown", "python", "sure", "here"}

    if len(clean) < 10 and clean in JUNK_TAGS:
        return False

    if clean.startswith("sure") and "def " not in code and "import " not in code:
        return False

    MAJOR_MARKERS = ["def ", "import ", " = ", "class ", "print("]
    has_major = any(m in code.strip() for m in MAJOR_MARKERS)

    return has_major


# ---------------------------------------------------------------------------
# Kod Üretim Yardımcısı (DRY)
# ---------------------------------------------------------------------------

def _call_coder(model_key: str, prompt: str, system_prompt: str) -> str:
    """
    Belirtilen model slotu için Ollama'ya kod üretim isteği gönderir.
    Çıktı geçersizse bir kez yeniden dener (sıcaklık artırılır).
    """
    models = get_ollama_models()    # tek çağrı, sonuç değişkene atanır
    model  = models[model_key]

    code = call_ollama(
        model=model,
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=0.1,
        max_tokens=2048,
    )

    if not validate_code(code) or ".ipynb" in code.lower():
        print(f"⚠️ {model} hallucination detected, retrying...")
        code = call_ollama(
            model=model,
            prompt=f"CRITICAL: Write ACTUAL Python code for: {prompt}",
            system_prompt=system_prompt + " START IMMEDIATELY WITH 'import' OR 'def'.",
            temperature=0.3,    # sıcaklık artırılarak çeşitlilik sağlanır
        )
    return code


# ---------------------------------------------------------------------------
# Public Kod Üretim Fonksiyonları
# ---------------------------------------------------------------------------

def call_coder_1(prompt: str) -> str:
    """OLLAMA_CODER_MODEL_1 modeliyle kod üretir."""
    return _call_coder("coder_1", prompt, _SYSTEM_PROMPTS["coder_1"])


def call_coder_2(prompt: str) -> str:
    """OLLAMA_CODER_MODEL_2 modeliyle kod üretir."""
    return _call_coder("coder_2", prompt, _SYSTEM_PROMPTS["coder_2"])


def call_coder_3(prompt: str) -> str:
    """OLLAMA_CODER_MODEL_3 modeliyle kod üretir."""
    return _call_coder("coder_3", prompt, _SYSTEM_PROMPTS["coder_3"])


# ---------------------------------------------------------------------------
# DeepSeek-R1 Judge
# ---------------------------------------------------------------------------

def safe_int_extract(val: Any) -> int:
    """'0-1', '5/10', ' 8 ' gibi LLM çıktılarından tamsayı çıkarır."""
    if isinstance(val, int):
        return val
    if not val:
        return 0

    s = str(val).strip()
    if "-" in s:
        parts = re.findall(r"\d+", s)
        if parts:
            return max(int(p) for p in parts)
    if "/" in s:
        parts = re.findall(r"\d+", s)
        if parts:
            return int(parts[0])
    match = re.search(r"\d+", s)
    return int(match.group()) if match else 0


def call_deepseek_r1_judge(code: str, prompt: str) -> Dict[str, Any]:
    """
    DeepSeek-R1 ile Chain-of-Thought tabanlı kod değerlendirmesi.

    <think>...</think> bloklarını CoT olarak ayrıştırır.
    Maksimum 30 puan: identifier_clarity(5) + prompt_adherence(10)
                      + naming_alignment(5) + test_reliability(10)
    """
    system_prompt = """You are a highly critical Senior Python Architect and Code Reviewer.
Your goal is to provide a TOUGH and UNBIASED evaluation. DO NOT give high scores unless the code is truly exceptional.

Evaluate the code based on these specific semantic criteria (Max 30 points total):

1. **Identifier Clarity** (0-5):
   - 5: Perfect PEP8 naming, perfectly descriptive.
   - 3-4: Mostly clear but some vague names (e.g., 'data', 'temp').
   - 1-2: Poor names (e.g., 'a', 'b', 'list1').
   - 0: Obfuscated or completely meaningless.

2. **Prompt Adherence** (0-10):
   - 10: Implements ALL requirements perfectly, including edge cases.
   - 7-9: Implements core logic but misses a minor constraint or edge case.
   - 4-6: Significant missing features or logic errors.
   - 0-3: Fails to understand the prompt or produces completely wrong algorithm.

3. **Naming Alignment** (0-5):
   - 5: Uses domain-specific terminology perfectly.
   - 3-4: Acceptable domain names but generic in places.
   - 1-2: Inconsistent or wrong terminology for the requested domain.
   - 0: Completely random names.

4. **Logic & Reliability** (0-10):
   - 10: Robust, optimized, handles errors, no race conditions, high quality.
   - 7-9: Logic is correct but could be more efficient or lacks advanced error handling.
   - 4-6: Works for simple cases but crashes on empty input or invalid types.
   - 0-3: Broken logic, infinite loops, or major bugs.

Deduct points from `test_reliability` for:
- Hardcoded values that should be parameters (-1)
- Redundant logic (-1)
- Bad architectural choices (-1)

Return ONLY a valid JSON object:
{"identifier_clarity":<0-5>,"prompt_adherence":<0-10>,"naming_alignment":<0-5>,"test_reliability":<0-10>,"reasoning":"<detailed explanation IN TURKISH>"}"""

    user_prompt = f"""Original Request: {prompt}

Generated Code:
```python
{code}
```

Evaluate this code and return JSON scores."""

    response = call_ollama_chat(
        model=get_ollama_models()["judge"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=1024,
        timeout=1800,
        format_json=True,
    )

    if not response or not response.strip():
        return {
            "semantic_score": 0,
            "breakdown":      {"identifier_clarity": 0, "prompt_adherence": 0,
                               "naming_alignment": 0, "test_reliability": 0},
            "reasoning":      "Ollama Hatası: Boş yanıt.",
            "chain_of_thought": "",
            "error":          True,
        }

    # <think> bloğunu CoT olarak ayır
    chain_of_thought = ""
    json_response    = response

    if "<think>" in response and "</think>" in response:
        think_match = re.search(r"<think>(.*?)</think>", response, re.DOTALL)
        if think_match:
            chain_of_thought = think_match.group(1).strip()
            json_response    = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()

    # Ekstra konuşma metni varsa JSON bloğunu çıkar
    json_match = re.search(r"(\{.*\})", json_response, re.DOTALL)
    if json_match:
        json_response = json_match.group(1)

    try:
        parsed = json.loads(json_response)

        breakdown = {
            "identifier_clarity": min(5,  max(0, safe_int_extract(parsed.get("identifier_clarity", 0)))),
            "prompt_adherence":   min(10, max(0, safe_int_extract(parsed.get("prompt_adherence",   0)))),
            "naming_alignment":   min(5,  max(0, safe_int_extract(parsed.get("naming_alignment",   0)))),
            "test_reliability":   min(10, max(0, safe_int_extract(parsed.get("test_reliability",   0)))),
        }
        return {
            "semantic_score":   sum(breakdown.values()),
            "breakdown":        breakdown,
            "reasoning":        parsed.get("reasoning", "Evaluated."),
            "chain_of_thought": chain_of_thought,
            "error":            False,
        }

    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        # Regex tabanlı acil kurtarma (kısmi/bozuk JSON için)
        print(f"  ⚠️ JSON Parse Error: {exc}. Attempting recovery...")

        fallback = {"identifier_clarity": 0, "prompt_adherence": 0,
                    "naming_alignment": 0, "test_reliability": 0}

        for key in fallback:
            match = re.search(rf'"{key}"\s*:\s*"?([\d\-/]+)"?', json_response)
            if match:
                fallback[key] = safe_int_extract(match.group(1))

        reasoning_match = re.search(r'"reasoning"\s*:\s*"(.*?)"', json_response)
        reasoning = (reasoning_match.group(1) if reasoning_match
                     else "Değerlendirme başarılı (kısmi yanıttan kurtarıldı).")

        if sum(fallback.values()) > 0:
            return {
                "semantic_score":   sum(fallback.values()),
                "breakdown":        fallback,
                "reasoning":        reasoning,
                "chain_of_thought": chain_of_thought,
                "error":            False,
            }

        return {
            "semantic_score":   0,
            "breakdown":        fallback,
            "reasoning":        f"Ayrıştırma hatası: {exc}",
            "chain_of_thought": chain_of_thought,
            "error":            True,
        }
