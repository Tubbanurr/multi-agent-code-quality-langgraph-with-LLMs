"""
complexity_analyzer.py — Radon ile döngüsel karmaşıklık (Cyclomatic Complexity) analizi.

Sorumluluklar:
  - Radon CC hesapla                  → 15 puan
  - Radon başarısız olursa AST fallback
"""

import ast
import json
import subprocess
import sys
from typing import Dict, Any

from .base import BaseAnalyzer


class ComplexityAnalyzer(BaseAnalyzer):
    """
    Radon cc aracını çalıştırarak döngüsel karmaşıklığı ölçer.
    Radon sonuç üretemezse fonksiyon varlığına bakar ve AST ile tahmin eder.
    """

    def analyze(self, code: str, temp_file: str = None) -> Dict[str, Any]:
        return {"complexity": self.analyze_complexity(code, temp_file)}

    def analyze_complexity(self, code: str, temp_file: str = None) -> Dict[str, Any]:
        """
        Radon CC analizi; temp_file verilmişse onu kullanır.
        Maks 15 puan.
        """
        result: Dict[str, Any] = {
            "average_complexity": 0,
            "max_complexity":     0,
            "score":              0,
            "error":              None,
        }

        # Fonksiyon sayısını AST ile önceden belirle
        try:
            tree = ast.parse(code)
            fn_count = sum(
                1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
            )
        except SyntaxError:
            fn_count = 0
            tree = None

        if not temp_file:
            result["error"] = "No temp file provided — skipped"
            result["score"] = 10  # Nötr puan
            return result

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "radon", "cc", temp_file, "-j"],
                capture_output=True,
                text=True,
                timeout=15,
            )

            radon_found = False
            if proc.stdout:
                try:
                    data = json.loads(proc.stdout)
                    complexities = []
                    for _, file_data in data.items():
                        items = file_data if isinstance(file_data, list) else [file_data]
                        for item in items:
                            if isinstance(item, dict):
                                complexities.append(item.get("complexity", 0))
                    if complexities:
                        result["average_complexity"] = sum(complexities) / len(complexities)
                        result["max_complexity"]     = max(complexities)
                        radon_found = True
                except json.JSONDecodeError:
                    pass

            avg = result["average_complexity"]

            if avg == 0:
                if not radon_found and fn_count > 0 and tree:
                    # AST fallback: dal sayısından tahmin
                    branches = sum(
                        1
                        for n in ast.walk(tree)
                        if isinstance(n, (ast.If, ast.For, ast.While,
                                         ast.ExceptHandler, ast.BoolOp))
                    )
                    estimated = (branches / fn_count) + 1
                    result["average_complexity"] = round(estimated, 1)
                    result["error"] = "Radon fallback: AST tahmini"
                    avg = estimated
                elif fn_count == 0:
                    result["score"] = 10  # Script tipi kod, orta puan
                    return result

            # Puanlama
            if avg <= 5:
                result["score"] = 15
            elif avg <= 10:
                result["score"] = 12
            elif avg <= 15:
                result["score"] = 8
            else:
                result["score"] = 5

        except subprocess.TimeoutExpired:
            result["error"] = "Radon timeout"
        except FileNotFoundError:
            result["error"] = "Radon not installed"
        except Exception as exc:
            result["error"] = str(exc)

        return result
