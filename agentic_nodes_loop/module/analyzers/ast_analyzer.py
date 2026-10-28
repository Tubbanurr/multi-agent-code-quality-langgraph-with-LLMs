"""
ast_analyzer.py — AST tabanlı analizler.

Sorumluluklar:
  - Sözdizimi (syntax) doğrulama          →  5 puan
  - Type hint kapsama oranı               →  bilgi amaçlı
  - Error handling kalitesi               → 10 puan
  - Riskli operasyon tespiti (I/O, ağ…)  → dahili yardımcı
"""

import ast
from typing import Dict, Any

from .base import BaseAnalyzer


class ASTAnalyzer(BaseAnalyzer):
    """
    Python'un kendi AST modülüyle kodu inceler;
    harici araç çalıştırmaz, dolayısıyla her zaman hızlıdır.
    """

    # analyze() burada temp_file gerekmez (saf Python), ama imzayı koruyoruz.
    def analyze(self, code: str, temp_file: str = None) -> Dict[str, Any]:
        return {
            "syntax":        self.analyze_ast(code),
            "type_hints":    self.analyze_type_hints(code),
            "error_handling": self.analyze_error_handling(code),
        }

    # ------------------------------------------------------------------
    # Sözdizimi Kontrolü
    # ------------------------------------------------------------------
    def analyze_ast(self, code: str) -> Dict[str, Any]:
        """AST parse ile sözdizimi hatası var mı kontrol eder. Maks 5 puan."""
        result: Dict[str, Any] = {"syntax_valid": False, "score": 0, "error": None}

        if not code.strip():
            return result

        try:
            ast.parse(code)
            result["syntax_valid"] = True
            result["score"] = 5
        except SyntaxError as exc:
            result["error"] = f"Syntax Error at line {exc.lineno}: {exc.msg}"
        except Exception as exc:
            result["error"] = str(exc)

        return result

    # ------------------------------------------------------------------
    # Type Hint Kapsama
    # ------------------------------------------------------------------
    def analyze_type_hints(self, code: str) -> Dict[str, Any]:
        """Fonksiyonlardaki tip ipucu oranını ölçer. Bilgi amaçlıdır."""
        result: Dict[str, Any] = {
            "functions_with_hints": 0,
            "total_functions":      0,
            "coverage":             0.0,
            "score":                0,
            "error":                None,
        }

        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    result["total_functions"] += 1
                    has_hints = node.returns is not None or any(
                        arg.annotation is not None for arg in node.args.args
                    )
                    if has_hints:
                        result["functions_with_hints"] += 1

            if result["total_functions"] > 0:
                result["coverage"] = (
                    result["functions_with_hints"] / result["total_functions"]
                )
                result["score"] = int(result["coverage"] * 5)

        except Exception as exc:
            result["error"] = str(exc)

        return result

    # ------------------------------------------------------------------
    # Error Handling
    # ------------------------------------------------------------------
    def analyze_error_handling(self, code: str) -> int:
        """
        Risk farkındalıklı hata yönetimi puanı. Maks 10 puan.

        Basit/güvenli kodlar 10 alır; riskli ama korumasız kod ceza yer.
        """
        try:
            tree = ast.parse(code)
            risk_info = self._check_risk_level(tree)

            has_try              = False
            has_raise            = False
            has_assert           = False
            has_bare_except      = False
            has_broad_exception  = False
            has_specific_except  = False

            for node in ast.walk(tree):
                if isinstance(node, ast.Try):
                    has_try = True
                    for handler in node.handlers:
                        if handler.type is None:
                            has_bare_except = True
                        elif (
                            isinstance(handler.type, ast.Name)
                            and handler.type.id == "Exception"
                        ):
                            has_broad_exception = True
                        else:
                            has_specific_except = True
                if isinstance(node, ast.Raise):
                    has_raise = True
                if isinstance(node, ast.Assert):
                    has_assert = True

            score = 10

            unprotected_high = sum(
                1 for _, p_try, _ in risk_info["high_risks"] if not p_try
            )
            unprotected_low = sum(
                1
                for r, p_try, p_with in risk_info["low_risks"]
                if not p_try and r != "io"
            )
            unprotected_io = sum(
                1
                for r, p_try, p_with in risk_info["low_risks"]
                if r == "io" and not p_try and not p_with
            )

            if unprotected_high > 0:
                score -= 4
            elif unprotected_low > 0 or unprotected_io > 0:
                score -= 2

            if (
                (unprotected_high > 0 or unprotected_low > 0)
                and not has_try
                and (has_raise or has_assert)
            ):
                score = min(10, score + 1)

            if has_bare_except:
                score -= 3
            elif has_broad_exception and not has_specific_except:
                score -= 1

            return max(0, min(score, 10))

        except Exception:
            # Sözdizimi hatası varsa string tabanlı basit puan
            score = 5
            if "try:" in code:
                score += 2
            if "except " in code:
                score += 2
                if "Exception" in code:
                    score -= 1
            if "except:" in code:
                score -= 3
            if "with open" in code:
                score += 2
            if "raise " in code or "assert " in code:
                score += 1
            return max(0, min(score, 10))

    # ------------------------------------------------------------------
    # Dahili Yardımcı: Risk Seviyesi Tespiti
    # ------------------------------------------------------------------
    def _check_risk_level(self, tree: ast.AST) -> Dict[str, Any]:
        """Riskli operasyonları (ağ, DB, eval, dosya) AST'ta tespit eder."""
        HIGH_RISK = {
            "requests": "network",  "urllib": "network",
            "http":     "network",  "socket": "network",
            "sqlite3":  "database", "sqlalchemy": "database",
        }
        LOW_RISK = {
            "json":     "parsing",  "pickle":   "parsing",
            "yaml":     "parsing",  "xml":      "parsing",
            "os":       "system",   "subprocess": "system",
            "shutil":   "system",   "glob":     "system",
            "pathlib":  "system",   "pandas":   "data_parsing",
            "csv":      "data_parsing",
        }

        found_high: set = set()
        found_low:  set = set()

        def is_protected(target_node, ptype=ast.Try):
            for node in ast.walk(tree):
                if isinstance(node, ptype):
                    for child in ast.walk(node):
                        if child is target_node:
                            return True
            return False

        for node in ast.walk(tree):
            found_type = risk_level = None

            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".")[0]
                    if base in HIGH_RISK:
                        found_type, risk_level = HIGH_RISK[base], "high"
                    elif base in LOW_RISK:
                        found_type, risk_level = LOW_RISK[base], "low"

            elif isinstance(node, ast.ImportFrom) and node.module:
                base = node.module.split(".")[0]
                if base in HIGH_RISK:
                    found_type, risk_level = HIGH_RISK[base], "high"
                elif base in LOW_RISK:
                    found_type, risk_level = LOW_RISK[base], "low"

            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in ("eval", "exec"):
                        found_type, risk_level = "volatile", "high"
                    elif node.func.id in ("open", "input"):
                        found_type, risk_level = "io", "low"
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in ("remove", "rmdir", "rmtree", "unlink"):
                        found_type, risk_level = "destructive_io", "high"

            if isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Div, ast.Mod, ast.FloorDiv)
            ):
                if not isinstance(node.right, ast.Constant):
                    found_type, risk_level = "potential_zero_division", "low"

            if found_type:
                p_try  = is_protected(node, ast.Try)
                p_with = is_protected(node, ast.With)
                data   = (found_type, p_try, p_with)
                if risk_level == "high":
                    found_high.add(data)
                else:
                    found_low.add(data)

        return {
            "has_high_risk": len(found_high) > 0,
            "has_low_risk":  len(found_low) > 0,
            "high_risks":    list(found_high),
            "low_risks":     list(found_low),
        }
