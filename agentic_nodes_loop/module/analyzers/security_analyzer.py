"""
security_analyzer.py — Bandit ile güvenlik açığı taraması.

Sorumluluklar:
  - HIGH / MEDIUM / LOW seviyeli güvenlik sorunlarını tespit et
  - Sadece bilgi amaçlı; final skora doğrudan katkıda bulunmaz
    (Robustness & Safety kategorisini LLM Judge besler)
"""

import json
import subprocess
import sys
from typing import Dict, Any

from .base import BaseAnalyzer


class SecurityAnalyzer(BaseAnalyzer):
    """
    Bandit güvenlik tarayıcısını çalıştırır.
    Sonuçlar ek bağlam olarak hybrid score sözlüğüne eklenir.
    """

    def analyze(self, code: str, temp_file: str = None) -> Dict[str, Any]:
        return {"security": self.analyze_security(temp_file)}

    def analyze_security(self, temp_file: str) -> Dict[str, Any]:
        """
        Bandit JSON çıktısını parse eder; sorun sayısını ve önem seviyesini döner.
        Başlangıç puanı 15; her HIGH -5, MEDIUM -3, LOW -1.
        """
        result: Dict[str, Any] = {
            "issues_count":   0,
            "severity_high":  0,
            "severity_medium": 0,
            "severity_low":   0,
            "score":          15,
            "error":          None,
        }

        if not temp_file:
            return result

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "bandit", temp_file, "-f", "json"],
                capture_output=True,
                text=True,
                timeout=15,
            )

            if proc.stdout:
                try:
                    data    = json.loads(proc.stdout)
                    issues  = data.get("results", [])
                    result["issues_count"] = len(issues)

                    for issue in issues:
                        sev = issue.get("issue_severity", "LOW")
                        if sev == "HIGH":
                            result["severity_high"]   += 1
                            result["score"]           -= 5
                        elif sev == "MEDIUM":
                            result["severity_medium"] += 1
                            result["score"]           -= 3
                        else:
                            result["severity_low"]    += 1
                            result["score"]           -= 1

                    result["score"] = max(0, result["score"])

                except json.JSONDecodeError:
                    pass

        except subprocess.TimeoutExpired:
            result["error"] = "Bandit timeout"
        except FileNotFoundError:
            result["error"] = "Bandit not installed"
        except Exception as exc:
            result["error"] = str(exc)

        return result
