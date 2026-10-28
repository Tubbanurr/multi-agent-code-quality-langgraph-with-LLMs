"""
Chain-of-Thought Feedback Agent

Yerel (Ollama) veya bulut (Groq) LLM kullanarak dinamik,
bağlama özgü kod iyileştirme önerileri üretir.

Tasarım Kalıpları:
  - Strategy Pattern: LLM backend seçimi dict dispatch ile
  - Sabit Merkezi Tanım: Kategori max. değerleri tek noktada (_CAT_MAX)
"""

import json
import os
import re
from typing import Dict, Any, List

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

USE_OLLAMA: bool = os.getenv("USE_OLLAMA", "false").lower() == "true"

# Kategori maksimum puanları — advanced_judge.py ile senkronizedir.
# Burası değişirse feedback'teki metrikler de otomatik güncellenir.
_CAT_MAX: Dict[str, int] = {
    "1_Kod_Kalitesi":       20,
    "2_Teknik_Borc":        20,
    "3_Test_Build":         15,
    "4_Stil_Standart":      15,
    "5_Semantic_Alignment": 15,
    "6_Robustness_Safety":  15,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_cot_feedback(
    code: str,
    original_prompt: str,
    static_analysis: Dict[str, Any],
    llm_evaluation: Dict[str, Any],
    previous_score: float = 0,
    current_score: float = 0,
) -> Dict[str, Any]:
    """
    Chain-of-Thought kullanarak dinamik feedback ve öneriler üretir.

    LLM başarısız olursa statik analiz bazlı akıllı fallback devreye girer.
    """
    system_prompt, user_prompt = _build_prompts(
        code, original_prompt, static_analysis, llm_evaluation,
        previous_score, current_score,
    )

    # Strategy Pattern: backend seçimi sabit dict üzerinden
    backend = _BACKEND_STRATEGIES.get(USE_OLLAMA, _call_groq_cot)
    result = backend(system_prompt, user_prompt)

    # Fallback: LLM başarısız olduysa statik analize dayanarak öneri üret
    if result.get("error") or not result.get("suggestions"):
        smart = _generate_smart_fallback_suggestions(static_analysis, llm_evaluation, code)
        if smart:
            result["suggestions"] = smart
            result["summary"]     = "Statik analize dayalı öneriler üretildi."

    return result


def format_suggestions_for_prompt(suggestions: List[Dict]) -> str:
    """Önerileri LLM'e gönderilecek metin formatına dönüştürür."""
    if not suggestions:
        return "Genel kod kalitesini artır."
    lines = [
        f"- [{s.get('area', 'Genel')}]: {s.get('issue', '')} -> {s.get('action', '')}"
        for s in suggestions
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt Oluşturma
# ---------------------------------------------------------------------------

def _build_prompts(
    code: str,
    original_prompt: str,
    static_analysis: Dict[str, Any],
    llm_evaluation: Dict[str, Any],
    previous_score: float,
    current_score: float,
) -> tuple[str, str]:
    """System ve user prompt'larını oluşturur."""
    breakdown         = static_analysis.get("breakdown", {})
    hybrid_categories = llm_evaluation.get("categories", {})
    llm_reasoning     = llm_evaluation.get("reasoning", "")

    context = f"""## Kod Analiz Sonuçları

### Skorlar
- Hybrid Skor: {current_score}/100 (Önceki: {previous_score}/100)
- Statik Analiz (Temel): {static_analysis.get('static_total', 0):.1f}/70

### 6 Kategori Detaylı Skorları
- 1. Kod Kalitesi:        {hybrid_categories.get('1_Kod_Kalitesi', 0)}/{_CAT_MAX['1_Kod_Kalitesi']}
- 2. Teknik Borç:         {hybrid_categories.get('2_Teknik_Borc', 0)}/{_CAT_MAX['2_Teknik_Borc']}
- 3. Test & Build:        {hybrid_categories.get('3_Test_Build', 0)}/{_CAT_MAX['3_Test_Build']}
- 4. Stil & Standart:     {hybrid_categories.get('4_Stil_Standart', 0)}/{_CAT_MAX['4_Stil_Standart']}
- 5. Semantic Alignment:  {hybrid_categories.get('5_Semantic_Alignment', 0)}/{_CAT_MAX['5_Semantic_Alignment']}
- 6. Robustness & Safety: {hybrid_categories.get('6_Robustness_Safety', 0)}/{_CAT_MAX['6_Robustness_Safety']}

### Statik Metrik Detayları
- Pylint:           {breakdown.get('pylint', {}).get('raw_score', 0):.1f}/10
- Karmaşıklık:      {breakdown.get('complexity', {}).get('average_complexity', 0):.1f}
- Güvenlik:         {breakdown.get('security', {}).get('issues_count', 0)} açık
- Stil (PEP8):      {breakdown.get('style', {}).get('violations', 0)} ihlal
- Yorum Yoğunluğu:  {breakdown.get('comments', {}).get('density', 0) * 100:.1f}%

### LLM Semantic Değerlendirmesi
- Reasoning: {llm_reasoning}"""

    system_prompt = """Sen uzman bir Python kod reviewer'ısın. Sana verilen kod analiz sonuçlarını değerlendirip, ÖNCELİKLİ ve SPESİFİK iyileştirme önerileri üreteceksin.

Chain-of-Thought (adım adım düşünme) yöntemiyle analiz yap:
1. Önce en kritik sorunları tespit et
2. Sorunları etkiye göre önceliklendir (1=en yüksek, 3=düşük)
3. Her sorun için somut çözüm öner

SADECE aşağıdaki JSON formatında yanıt ver (markdown veya açıklama YOK):
{
  "suggestions": [
    {
      "priority": 1,
      "area": "Hata Yönetimi|Dokümantasyon|Güvenlik|Karmaşıklık|İsimlendirme",
      "issue": "<sorun açıklaması - TÜRKÇE>",
      "action": "<iyileştirme aksiyonu - TÜRKÇE>",
      "code_example": "isteğe bağlı kod örneği"
    }
  ],
  "summary": "1-2 cümlelik genel Türkçe özet"
}"""

    user_prompt = f"""Orijinal İstek: {original_prompt}

Kod:
```python
{code}
```

{context}

Bu kodu iyileştirmek için öncelikli önerilerini JSON formatında ver."""

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# LLM Backend'leri (Strategy Pattern)
# ---------------------------------------------------------------------------

def _call_ollama_cot(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    """Ollama (yerel) backend'ini kullanarak CoT feedback üretir."""
    try:
        from module.ollama_client import call_ollama_chat, OLLAMA_MODELS
        response = call_ollama_chat(
            model=OLLAMA_MODELS.get("judge", "deepseek-r1:7b"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ]
        )
        return _parse_cot_response(response)
    except Exception as exc:
        return {"error": True, "suggestions": [], "summary": str(exc)}


def _call_groq_cot(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    """Groq (bulut) backend'ini kullanarak CoT feedback üretir."""
    try:
        from groq import Groq
        client   = Groq(api_key=os.getenv("GROQ_API_KEY"))
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.2,
        )
        return _parse_cot_response(response.choices[0].message.content)
    except Exception as exc:
        return {"error": True, "suggestions": [], "summary": str(exc)}


# Strategy dispatch tablosu — yeni backend eklemek = tek satır
_BACKEND_STRATEGIES: Dict[bool, Any] = {
    True:  _call_ollama_cot,
    False: _call_groq_cot,
}


# ---------------------------------------------------------------------------
# Yardımcı Fonksiyonlar
# ---------------------------------------------------------------------------

def _parse_cot_response(response: str) -> Dict[str, Any]:
    """LLM çıktısını ayrıştırır; <think> bloğunu CoT olarak çıkarır."""
    chain_of_thought = ""
    json_response    = response

    if "<think>" in response and "</think>" in response:
        think_match = re.search(r"<think>(.*?)</think>", response, re.DOTALL)
        if think_match:
            chain_of_thought = think_match.group(1).strip()
            json_response    = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()

    try:
        if "```json" in json_response:
            match = re.search(r"```json\s*(.*?)\s*```", json_response, re.DOTALL)
            if match:
                json_response = match.group(1)

        parsed = json.loads(json_response)
        return {
            "suggestions":     parsed.get("suggestions", []),
            "chain_of_thought": chain_of_thought,
            "summary":         parsed.get("summary", ""),
            "error":           False,
        }
    except (json.JSONDecodeError, AttributeError) as exc:
        return {
            "error":           True,
            "suggestions":     [],
            "chain_of_thought": chain_of_thought,
            "summary":         f"JSON parse error: {exc}",
        }


def _generate_smart_fallback_suggestions(
    static_analysis: Dict[str, Any],
    llm_evaluation: Dict[str, Any],
    code: str,
) -> List[Dict[str, Any]]:
    """LLM başarısız olursa statik analiz sonuçlarına dayalı öneriler üretir."""
    suggestions: List[Dict[str, Any]] = []
    breakdown = static_analysis.get("breakdown", {})

    if breakdown.get("comments", {}).get("density", 0) < 0.1:
        suggestions.append({
            "priority": 2,
            "area":     "Documentation",
            "issue":    "Yorum yoğunluğu çok düşük",
            "action":   "Kodun anlaşılırlığını artırmak için docstring ve yorum ekle",
        })

    if breakdown.get("style", {}).get("violations", 0) > 5:
        suggestions.append({
            "priority": 2,
            "area":     "Style",
            "issue":    "Çok sayıda PEP8 ihlali var",
            "action":   "Kod stilini PEP8 standartlarına göre düzelt",
        })

    if "try" not in code and len(code) > 100:
        suggestions.append({
            "priority": 1,
            "area":     "Robustness",
            "issue":    "Hata yönetimi blokları (try-except) eksik",
            "action":   "Kritik operasyonlar için hata yakalama mekanizması ekle",
        })

    return suggestions[:3]
