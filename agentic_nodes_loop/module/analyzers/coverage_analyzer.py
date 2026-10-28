"""
coverage_analyzer.py — Pytest + pytest-cov ile test kapsama ölçümü.

Sorumluluklar:
  - Geçici test dosyası üretip pytest çalıştır
  - Kapsama yüzdesi → 10 puan
"""

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, Any

from .base import BaseAnalyzer


class CoverageAnalyzer(BaseAnalyzer):
    """
    Kodun içindeki public fonksiyonlar için minimal test senaryoları üretir
    ve pytest-cov ile kapsama oranını ölçer.

    Not: temp_file burada kullanılmaz; kendi tmp_dir'i yönetir
    çünkü src.py + test_src.py şeklinde bir alt dizin gerektirir.
    """

    def analyze(self, code: str, temp_file: str = None) -> Dict[str, Any]:
        return {"coverage": self.analyze_test_coverage(code)}

    def analyze_test_coverage(self, code: str) -> Dict[str, Any]:
        """
        Kodun fonksiyonlarını keşfeder, basit çağrılar içeren test dosyası
        üretir ve coverage oranı üzerinden 0-10 puan döner.
        """
        result: Dict[str, Any] = {"coverage": 0.0, "score": 0, "error": None}

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            result["error"] = f"Syntax error: {exc}"
            return result

        functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
        ]

        tmp_dir   = None
        try:
            tmp_dir   = tempfile.mkdtemp()
            src_file  = os.path.join(tmp_dir, "src.py")
            test_file = os.path.join(tmp_dir, "test_src.py")

            with open(src_file, "w", encoding="utf-8") as f:
                f.write(code)

            test_lines = [
                "import sys, os",
                f"sys.path.insert(0, r'{tmp_dir}')",
                "from src import *",
                "",
            ]
            for fn in functions:
                n_args = len(fn.args.args)
                args   = ", ".join(["0"] * n_args)
                test_lines += [
                    f"def test_{fn.name}():",
                    f"    try: {fn.name}({args})",
                    f"    except: pass",
                    "",
                ]

            if not functions:
                test_lines += ["def test_script():", "    pass", ""]

            with open(test_file, "w", encoding="utf-8") as f:
                f.write("\n".join(test_lines))

            proc = subprocess.run(
                [
                    sys.executable, "-m", "pytest", test_file,
                    "--cov=src", "--cov-report=term-missing",
                    "-q", "--tb=no",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=tmp_dir,
            )

            output = proc.stdout + proc.stderr
            cov_match = re.search(r"src\.py\s+\d+\s+\d+\s+(\d+)%", output)
            if not cov_match:
                cov_match = re.search(r"\b(\d{1,3})%", output)

            if cov_match:
                pct              = int(cov_match.group(1))
                result["coverage"] = pct / 100.0
                result["score"]    = round(result["coverage"] * 10)

        except subprocess.TimeoutExpired:
            result["error"] = "Coverage timeout"
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        return result
