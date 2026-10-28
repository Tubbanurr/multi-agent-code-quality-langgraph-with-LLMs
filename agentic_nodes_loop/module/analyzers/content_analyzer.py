"""
content_analyzer.py — Yorum yoğunluğu ve kod tekrar tespiti.

Sorumluluklar:
  - Yorum / docstring yoğunluğu → 5 puan
  - Blok tabanlı tekrar oranı   → 5 puan
"""

from typing import Dict, Any

from .base import BaseAnalyzer


class ContentAnalyzer(BaseAnalyzer):
    """
    Harici araç gerektirmeyen, saf Python tabanlı analizler.
    Satır okuma ve sliding-window blok karşılaştırması ile çalışır.
    """

    def analyze(self, code: str, temp_file: str = None) -> Dict[str, Any]:
        return {
            "comments":    self.analyze_comments(code),
            "duplication": self.analyze_duplications(code),
        }

    # ------------------------------------------------------------------
    # Yorum Yoğunluğu
    # ------------------------------------------------------------------
    def analyze_comments(self, code: str) -> Dict[str, Any]:
        """
        Yorum ve docstring satırlarının toplam satıra oranı.
        İdeal aralık: %5–40. Maks 5 puan.
        """
        result: Dict[str, Any] = {
            "density":       0.0,
            "score":         0,
            "total_lines":   0,
            "comment_lines": 0,
        }

        lines       = code.splitlines()
        valid_lines = [l for l in lines if l.strip()]
        result["total_lines"] = len(valid_lines)

        if result["total_lines"] == 0:
            return result

        comment_lines     = 0
        in_multiline      = False
        multiline_char    = ""

        for line in valid_lines:
            stripped = line.strip()

            if not in_multiline and stripped.startswith("#"):
                comment_lines += 1
                continue

            q3d = stripped.count('"""')
            q3s = stripped.count("'''")

            if in_multiline:
                comment_lines += 1
                if (multiline_char == '"""' and q3d > 0) or (
                    multiline_char == "'''" and q3s > 0
                ):
                    in_multiline = False
            else:
                if q3d > 0 and q3d % 2 != 0:
                    in_multiline = True
                    multiline_char = '"""'
                    comment_lines += 1
                elif q3s > 0 and q3s % 2 != 0:
                    in_multiline = True
                    multiline_char = "'''"
                    comment_lines += 1
                elif (q3d > 0 and q3d % 2 == 0) or (q3s > 0 and q3s % 2 == 0):
                    comment_lines += 1

        result["comment_lines"] = comment_lines
        result["density"]       = comment_lines / result["total_lines"]

        if result["total_lines"] < 10 and result["comment_lines"] == 0:
            result["score"] = 5
        elif 0.05 <= result["density"] <= 0.65:
            # Toleransı %65'e kadar çıkardık, Pydoc/Docstring eklendiğinde ceza yemez
            result["score"] = 5
        elif result["density"] > 0.65:
            # Sadece koddan 2/3 oranında fazla yorum (aşırı şişirme) varsa puan kırılır
            result["score"] = 3
        elif result["density"] > 0:
            result["score"] = 4
        else:
            result["score"] = 0

        return result

    # ------------------------------------------------------------------
    # Kod Tekrarı (Duplication)
    # ------------------------------------------------------------------
    def analyze_duplications(self, code: str) -> Dict[str, Any]:
        """
        3-satırlık kayan pencere (sliding window) ile tekrarlayan blokları bulur.
        Maks 5 puan.
        """
        result: Dict[str, Any] = {
            "total_lines":      0,
            "unique_lines":     0,
            "duplicate_lines":  0,
            "duplication_ratio": 0.0,
            "score":            5,
            "error":            None,
        }

        try:
            code_lines = [
                line.strip()
                for line in code.strip().split("\n")
                if line.strip() and not line.strip().startswith("#")
            ]

            result["total_lines"] = len(code_lines)
            if result["total_lines"] == 0:
                return result

            BLOCK_SIZE      = 3
            duplicate_idx   = set()
            TRIVIAL_TOKENS  = {"continue", "break", "pass", "return", "else:"}

            if result["total_lines"] >= BLOCK_SIZE:
                seen_blocks: set = set()
                for i in range(len(code_lines) - BLOCK_SIZE + 1):
                    block    = tuple(code_lines[i : i + BLOCK_SIZE])
                    is_trivial = all(
                        len(l) < 5 or l in TRIVIAL_TOKENS for l in block
                    )
                    if not is_trivial:
                        if block in seen_blocks:
                            for j in range(i, i + BLOCK_SIZE):
                                duplicate_idx.add(j)
                        else:
                            seen_blocks.add(block)

            result["duplicate_lines"]   = len(duplicate_idx)
            result["unique_lines"]      = result["total_lines"] - result["duplicate_lines"]
            result["duplication_ratio"] = result["duplicate_lines"] / result["total_lines"]

            ratio = result["duplication_ratio"]
            if ratio == 0:
                result["score"] = 5
            elif ratio < 0.1:
                result["score"] = 4
            elif ratio < 0.2:
                result["score"] = 3
            elif ratio < 0.3:
                result["score"] = 2
            else:
                result["score"] = 1

        except Exception as exc:
            result["error"] = str(exc)

        return result
