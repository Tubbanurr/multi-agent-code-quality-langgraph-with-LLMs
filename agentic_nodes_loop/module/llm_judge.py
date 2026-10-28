"""
llm_judge.py — LLM tabanlı Semantik Kod Değerlendirici

Destekler:
  - Ollama (yerel): DeepSeek-R1 ile Chain-of-Thought
  - Groq (bulut):   Llama 3.3 70B

Düzeltmeler:
  - Tekrarlı get_model_name() metodu kaldırıldı (ikinci tanım birincisini eziyordu).
  - Circular import engeli için _clean_code() private fonksiyon eklendi.
  - Tüm inline import'lar modül başına taşındı.
"""

import json
import os
import re
from typing import Dict, Any

from dotenv import load_dotenv
from module.ollama_client import (
    check_ollama_available,
    get_ollama_models,
    call_deepseek_r1_judge,
    validate_code,
)

load_dotenv()

USE_OLLAMA: bool = os.getenv("USE_OLLAMA", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Private Yardımcı — Circular import olmadan clean_code sağlar
# ---------------------------------------------------------------------------

def _clean_code(text: str) -> str:
    """Markdown veya karışık içerikten saf Python kodunu çeker."""
    matches = re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    if matches:
        return max(matches, key=len).strip()
    return text.strip()


# ---------------------------------------------------------------------------
# LLMJudge Sınıfı
# ---------------------------------------------------------------------------

class LLMJudge:
    """
    LLM tabanlı semantik kod kalitesi değerlendirici.

    - Ollama modu:  DeepSeek-R1 (CoT reasoning ile)
    - Cloud modu:   Llama 3.3 70B via Groq
    """

    def __init__(self):
        self.use_ollama         = USE_OLLAMA
        self.ollama_available   = False
        self.groq_client        = None
        self.model              = "llama-3.3-70b-versatile"

        if self.use_ollama:
            self.ollama_available = check_ollama_available()
            if self.ollama_available:
                judge_model = get_ollama_models()["judge"]
                print(f"  🤖 LLM Judge: {judge_model} (Ollama)")

        if not self.ollama_available:
            try:
                from groq import Groq
                api_key = os.getenv("GROQ_API_KEY")
                if api_key:
                    self.groq_client = Groq(api_key=api_key)
                    print("  🤖 LLM Judge: Llama 3.3 70B (Groq)")
            except ImportError:
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_model_name(self) -> str:
        """Aktif judge modelinin adını döner."""
        if self.use_ollama and self.ollama_available:
            judge_model = os.getenv("OLLAMA_JUDGE_MODEL", "deepseek-r1:1.5b")
            return f"{judge_model} (Ollama)"
        if self.groq_client:
            return "Llama 3.3 70B (Groq)"
        return "None (Fallback)"

    def evaluate_code(self, code: str, prompt: str) -> Dict[str, Any]:
        """
        Kodu semantik olarak değerlendirir.

        Returns:
            {
                "semantic_score": 0-30,
                "breakdown": {
                    "identifier_clarity": 0-5,
                    "prompt_adherence":   0-10,
                    "naming_alignment":   0-5,
                    "test_reliability":   0-10,
                },
                "reasoning":        str,
                "chain_of_thought": str,
                "error":            bool,
            }
        """
        clean = _clean_code(code)

        if not validate_code(clean):
            return self._get_fallback_result(
                "Output detected as non-code/hallucination. Scoring zero.",
                error=False,
            )

        if self.use_ollama and self.ollama_available:
            return self._evaluate_with_ollama(clean, prompt)

        return self._evaluate_with_groq(clean, prompt)

    # ------------------------------------------------------------------
    # Private: Backend Değerlendiriciler
    # ------------------------------------------------------------------

    def _evaluate_with_ollama(self, code: str, prompt: str) -> Dict[str, Any]:
        """DeepSeek-R1 (Ollama) ile değerlendirir."""
        try:
            return call_deepseek_r1_judge(code, prompt)
        except Exception as exc:
            return self._get_fallback_result(f"Ollama evaluation failed: {exc}")

    def _evaluate_with_groq(self, code: str, prompt: str) -> Dict[str, Any]:
        """Llama 3.3 70B (Groq) ile değerlendirir."""
        if not self.groq_client:
            return self._get_fallback_result("GROQ_API_KEY not configured")

        system_prompt = """You are a highly critical Senior Python Architect and Code Reviewer.
Your goal is to provide a TOUGH and UNBIASED evaluation. DO NOT give high scores unless the code is truly exceptional.

Evaluate the code based on these specific semantic criteria (Max 30 points total):

1. **Identifier Clarity** (0-5):
   - 5: Perfect PEP8 naming, perfectly descriptive.
   - 3-4: Mostly clear but some vague names.
   - 1-2: Poor or generic names.
   - 0: Obfuscated or meaningless.

2. **Prompt Adherence** (0-10):
   - 10: Implements ALL requirements perfectly, including edge cases.
   - 7-9: Implements core logic but misses a minor constraint.
   - 4-6: Significant missing features.
   - 0-3: Fails to understand the prompt.

3. **Naming Alignment** (0-5):
   - 5: Uses domain-specific terminology perfectly.
   - 1-4: Inconsistent or generic terminology.

4. **Logic & Reliability** (0-10):
   - 10: Robust, optimized, handles errors, high quality.
   - 0-9: Deduct points for inefficiency, lack of error handling, or bugs.

Deduct 1-2 points from `test_reliability` for:
- Hardcoded values
- Bad architectural choices or inefficiencies

Return ONLY a valid JSON object:
{
  "identifier_clarity": <number 0-5>,
  "prompt_adherence":   <number 0-10>,
  "naming_alignment":   <number 0-5>,
  "test_reliability":   <number 0-10>,
  "reasoning": "<detailed explanation of score deductions IN TURKISH LANGUAGE>"
}"""

        user_prompt = f"""Original Request: {prompt}

Generated Code:
```python
{code}
```

Evaluate this code and return JSON scores."""

        try:
            response = self.groq_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0.1,
                max_completion_tokens=512,
                response_format={"type": "json_object"},
            )

            parsed = json.loads(response.choices[0].message.content)
            breakdown = {
                "identifier_clarity": min(5,  max(0, int(parsed.get("identifier_clarity", 0)))),
                "prompt_adherence":   min(10, max(0, int(parsed.get("prompt_adherence",   0)))),
                "naming_alignment":   min(5,  max(0, int(parsed.get("naming_alignment",   0)))),
                "test_reliability":   min(10, max(0, int(parsed.get("test_reliability",   0)))),
            }
            return {
                "semantic_score":   sum(breakdown.values()),
                "breakdown":        breakdown,
                "reasoning":        parsed.get("reasoning", "Evaluated via Groq."),
                "chain_of_thought": "",
                "error":            False,
            }

        except json.JSONDecodeError as exc:
            return self._get_fallback_result(f"JSON decode error: {exc}")
        except Exception as exc:
            return self._get_fallback_result(f"LLM evaluation failed: {exc}")

    # ------------------------------------------------------------------
    # Private: Fallback Sonuç
    # ------------------------------------------------------------------

    def _get_fallback_result(
        self, error_message: str, *, error: bool = True
    ) -> Dict[str, Any]:
        """Değerlendirme başarısız olduğunda döndürülen sıfırlı sonuç."""
        return {
            "semantic_score": 0,
            "breakdown": {
                "identifier_clarity": 0,
                "prompt_adherence":   0,
                "naming_alignment":   0,
                "test_reliability":   0,
            },
            "reasoning":        f"LLM evaluation unavailable: {error_message}",
            "chain_of_thought": "",
            "error":            error,
        }
