"""
lint_analyzer.py — Pylint, Flake8 ve Formatting analizleri.

Sorumluluklar:
  - Pylint genel kod kalitesi   → 15 puan
  - Flake8 PEP8 uyumu           → 15 puan
  - Regex tabanlı formatting    →  5 puan
"""

import re
import subprocess
import sys
from typing import Dict, Any

from .base import BaseAnalyzer


class LintAnalyzer(BaseAnalyzer):
    """
    Dış lint araçlarını (Pylint, Flake8) çalıştıran analizör.
    Kod zaten diske yazılmış temp_file yolunu alır; kendi yazmaz.
    """

    def analyze(self, code: str, temp_file: str = None) -> Dict[str, Any]:
        return {
            "pylint":     self.analyze_pylint(temp_file),
            "style":      self.analyze_style(temp_file),
            "formatting": self.analyze_formatting(code),   # Regex tabanlı, dosya gerekmez
        }

    # ------------------------------------------------------------------
    # Pylint
    # ------------------------------------------------------------------
    def analyze_pylint(self, temp_file: str) -> Dict[str, Any]:
        """
        Pylint ile kapsamlı kod kalitesi kontrolü.
        Sonuç 10 üzerinden alınır, 15 puana ölçeklenir.
        """
        result: Dict[str, Any] = {
            "raw_score":    0.0,
            "scaled_score": 0,
            "issues":       [],
            "error":        None,
        }

        if not temp_file:
            return result

        try:
            proc = subprocess.run(
                [
                    sys.executable, "-m", "pylint", temp_file,
                    "--score=yes",
                    "--disable=missing-docstring,missing-module-docstring,"
                    "missing-function-docstring,invalid-name",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                env={**__import__("os").environ, "PAGER": "cat"},
            )

            full_output = proc.stdout + proc.stderr
            score_match = re.search(
                r"Your code has been rated at ([\d\.]+)/10", full_output
            )
            if score_match:
                raw = float(score_match.group(1))
                result["raw_score"]    = raw
                result["scaled_score"] = int((raw / 10) * 15)
            else:
                # Araç puan veremezse nötr taban
                if not proc.stderr or "error" not in proc.stderr.lower():
                    result["raw_score"]    = 7.0
                    result["scaled_score"] = 10

        except subprocess.TimeoutExpired:
            result["error"] = "Pylint timeout"
        except FileNotFoundError:
            # Araç yoksa ortamı cezalandırma
            result["error"]        = "Pylint not installed"
            result["raw_score"]    = 10.0
            result["scaled_score"] = 15
        except Exception as exc:
            result["error"] = str(exc)

        return result

    # ------------------------------------------------------------------
    # Flake8 (PEP8 Stili)
    # ------------------------------------------------------------------
    def analyze_style(self, temp_file: str) -> Dict[str, Any]:
        """
        Flake8 ile PEP8 uyum denetimi.
        Formül: (1 - violations / MAX_VIOLATIONS) * 15
        """
        MAX_VIOLATIONS = 20
        result: Dict[str, Any] = {"violations": 0, "score": 15, "error": None}

        if not temp_file:
            return result

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "flake8", temp_file, "--count",
                 "--max-line-length=120"],
                capture_output=True,
                text=True,
                timeout=15,
            )

            if proc.stdout:
                lines = proc.stdout.strip().split("\n")
                if lines[-1].isdigit():
                    violations             = int(lines[-1])
                    result["violations"]   = violations
                    ratio                  = min(violations / MAX_VIOLATIONS, 1.0)
                    result["score"]        = round((1 - ratio) * 15)

        except subprocess.TimeoutExpired:
            result["error"] = "Flake8 timeout"
        except FileNotFoundError:
            result["error"] = "Flake8 not installed"
        except Exception as exc:
            result["error"] = str(exc)

        return result

    # ------------------------------------------------------------------
    # Formatting (Regex)
    # ------------------------------------------------------------------
    def analyze_formatting(self, code: str) -> Dict[str, Any]:
        """
        Tutarlı girintileme, satır uzunluğu ve whitespace kontrolü.
        Harici araç gerektirmez. Maks 5 puan.
        """
        result: Dict[str, Any] = {"score": 5, "issues": []}
        lines = code.splitlines()

        tab_space_mix    = 0
        long_lines       = 0
        trailing_ws      = 0
        consecutive_blank = 0
        max_consec       = 0
        prev_blank       = False

        for line in lines:
            if line.strip() and "\t" in line and " " in line[: len(line) - len(line.lstrip())]:
                tab_space_mix += 1
            if len(line) > 120:
                long_lines += 1
            if line != line.rstrip():
                trailing_ws += 1
            if line.strip() == "":
                consecutive_blank = consecutive_blank + 1 if prev_blank else 1
                max_consec = max(max_consec, consecutive_blank)
                prev_blank = True
            else:
                consecutive_blank = 0
                prev_blank = False

        score = 5
        if tab_space_mix > 0:
            score -= 2
            result["issues"].append(f"Tab/space mixing ({tab_space_mix} lines)")
        if long_lines > 3:
            score -= 1
            result["issues"].append(f"Lines >120 chars ({long_lines} lines)")
        if trailing_ws > 3:
            score -= 1
            result["issues"].append(f"Trailing whitespace ({trailing_ws} lines)")
        if max_consec > 2:
            score -= 1
            result["issues"].append(f"Excessive blank lines (max {max_consec} in a row)")

        result["score"] = max(0, score)
        return result
