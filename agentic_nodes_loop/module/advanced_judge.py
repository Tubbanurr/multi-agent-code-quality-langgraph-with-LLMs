"""
advanced_judge.py — Orkestratör (Facade)

Sorumluluk:
  1. TempCodeManager ile kodu diske TEK SEFER yazar.
  2. Tüm analizörleri (Strategy Pattern) sırayla çalıştırır.
  3. Sonuçları 6-kategori 100-puanlık hibrit skalaya derler.

Dışa bakan public API değişmedi:
  judge = AdvancedCodeJudge()
  static = judge.score_code(code)
  hybrid = judge.get_hybrid_score(static, llm_eval)
"""

import re
from typing import Dict, Any, Optional

from module.analyzers import (
    TempCodeManager,
    ASTAnalyzer,
    LintAnalyzer,
    ComplexityAnalyzer,
    SecurityAnalyzer,
    CoverageAnalyzer,
    ContentAnalyzer,
)


class AdvancedCodeJudge:
    """
    Modüler statik kod kalitesi değerlendirici.

    Her analiz motoru ayrı bir sınıfta bulunur (analyzers/ paketi).
    Bu sınıf yalnızca motorları koordine eder ve sonuçları birleştirir.
    """

    def __init__(self, metric_weights: Optional[Dict[str, int]] = None):
        # Analizörler — listeye yeni motor eklemek tek satırdır
        self._ast        = ASTAnalyzer()
        self._lint       = LintAnalyzer()
        self._complexity = ComplexityAnalyzer()
        self._security   = SecurityAnalyzer()
        self._coverage   = CoverageAnalyzer()
        self._content    = ContentAnalyzer()

        # Özel ağırlık desteği (geriye dönük uyumluluk)
        self.weights: Dict[str, int] = {
            "cyclomatic_complexity": 15, "comment_density":   5,
            "identifier_clarity":   5,  "code_smells":       15,
            "duplication":          5,  "test_coverage":     10,
            "compile_success":      5,  "static_lint":       10,
            "formatting":           5,  "prompt_adherence":  10,
            "naming_alignment":     5,  "error_handling":    10,
        }
        if metric_weights:
            self.weights.update(metric_weights)

    # ------------------------------------------------------------------
    # Public: Statik Analiz
    # ------------------------------------------------------------------
    def clean_code(self, text: str) -> str:
        """Markdown veya karışık içerikten saf Python kodunu çeker."""
        matches = re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
        if matches:
            return max(matches, key=len).strip()
        return text.strip()

    def score_code(self, raw_code: str) -> Dict[str, Any]:
        """
        Ana statik puanlama fonksiyonu.

        Kodu temizler, diske TEK SEFER yazar (TempCodeManager),
        ardından tüm analizörleri tek dosya üzerinde çalıştırır.

        Returns:
            {
              "static_total": int,          # 0-70 arası
              "breakdown": { ... }          # her analizörün ham çıktısı
            }
        """
        code = self.clean_code(raw_code)

        # İçerik denetimi: Kod mu, yoksa paragraf mı?
        substance = self._has_substance(code)

        # ── Tüm analizörleri TempCodeManager ile tek dosya üzerinde çalıştır ──
        with TempCodeManager(code) as tmp:
            ast_res        = self._ast.analyze(code, tmp)
            lint_res       = self._lint.analyze(code, tmp)
            complexity_res = self._complexity.analyze(code, tmp)
            security_res   = self._security.analyze(code, tmp)
            coverage_res   = self._coverage.analyze(code)     # kendi tmp_dir yönetiyor

        content_res = self._content.analyze(code)             # araç gerektirmez

        # Kısa erişim isimleri
        syntax_res     = ast_res["syntax"]
        type_hints_res = ast_res["type_hints"]
        error_res      = ast_res["error_handling"]
        pylint_res     = lint_res["pylint"]
        style_res      = lint_res["style"]
        format_res     = lint_res["formatting"]
        cc_res         = complexity_res["complexity"]
        sec_res        = security_res["security"]
        cov_res        = coverage_res["coverage"]
        comment_res    = content_res["comments"]
        dup_res        = content_res["duplication"]

        # İçerik yoksa tümünü sıfırla
        if not substance:
            cc_res["score"]        = 0
            comment_res["score"]   = 0
            pylint_res["scaled_score"] = 0
            pylint_res["raw_score"]    = 0
            dup_res["score"]       = 0
            style_res["score"]     = 0
            format_res["score"]    = 0
            error_res              = 0
            cov_res["score"]       = 0
            syntax_res["syntax_valid"] = False

        # ── Statik toplam (maks 70) ──
        # 15(CC) + 5(Comments) + 15(Pylint) + 5(Dup) + 5(Syntax) + 15(Style) + 10(Error)
        static_total = (
            cc_res["score"]            +   # 15
            comment_res["score"]       +   #  5
            pylint_res["scaled_score"] +   # 15
            dup_res["score"]           +   #  5
            syntax_res["score"]        +   #  5
            style_res["score"]         +   # 15
            error_res                      # 10
        )

        return {
            "static_total": static_total,
            "breakdown": {
                "complexity":     cc_res,
                "comments":       comment_res,
                "pylint":         pylint_res,
                "duplication":    dup_res,
                "syntax":         syntax_res,
                "coverage":       cov_res,
                "style":          style_res,
                "format":         format_res,
                "error_handling": error_res,
                "security":       sec_res,
                "type_hints":     type_hints_res,
            },
        }

    # ------------------------------------------------------------------
    # Public: Hibrit Skor (Static + LLM)
    # ------------------------------------------------------------------
    def get_hybrid_score(
        self, static_data: Dict[str, Any], llm_eval: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Statik ve LLM sonuçlarını 6-kategori 100-puanlık skalaya derler.
        %70 Statik / %30 LLM dağılımını kesin olarak korur.
        """
        bd = static_data["breakdown"]

        # 1. Kod Kalitesi (20 pts — Statik)
        cat1 = (
            min(15, bd["complexity"]["score"])
            + bd["comments"]["score"]
        )

        # 2. Teknik Borç (20 pts — Statik)
        # Type Hints ZORUNLULUK DEĞILDIR: Sadece kullanıldığında Teknik borcu azaltan "Bonus" etkisindedir.
        cat2_base = (
            min(15, int(bd["pylint"]["raw_score"] * 1.5))
            + min(5, bd["duplication"]["score"])
        )
        cat2 = min(20, cat2_base + bd["type_hints"]["score"])

        # 3. Test & Build (15 pts — Statik)
        compile_pts = 5 if bd["syntax"]["syntax_valid"] else 0
        error_pts   = bd["error_handling"]
        cat3        = compile_pts + error_pts

        # 4. Stil & Standart (15 pts — Statik)
        cat4 = min(15, bd["style"]["score"])

        # 5. Semantic Alignment (15 pts — LLM)
        cat5 = llm_eval["breakdown"].get("prompt_adherence", 0) + \
               llm_eval["breakdown"].get("naming_alignment", 0)

        # 6. Robustness & Safety (15 pts — LLM)
        cat6 = llm_eval["breakdown"].get("test_reliability", 0) + \
               llm_eval["breakdown"].get("identifier_clarity", 0)

        total = cat1 + cat2 + cat3 + cat4 + cat5 + cat6

        return {
            "total_score":  int(total),
            "static_total": static_data["static_total"],
            "llm_total":    llm_eval["semantic_score"],
            "categories": {
                "1_Kod_Kalitesi":        cat1,
                "2_Teknik_Borc":         cat2,
                "3_Test_Build":          cat3,
                "4_Stil_Standart":       cat4,
                "5_Semantic_Alignment":  cat5,
                "6_Robustness_Safety":   cat6,
            },
            "static_analysis":  static_data,
            "llm_evaluation":   llm_eval,
            "reasoning":        llm_eval.get("reasoning", ""),
            "chain_of_thought": llm_eval.get("chain_of_thought", ""),
        }

    # ------------------------------------------------------------------
    # Dahili Yardımcı
    # ------------------------------------------------------------------
    def _has_substance(self, code: str) -> bool:
        """Kodun gerçek anlam taşıyıp taşımadığını denetler."""
        stripped      = code.strip()
        major_markers = ["def ", "import ", " = ", "class ", "print("]
        has_major     = any(m in stripped for m in major_markers)

        if len(stripped) > 40:
            return has_major
        if len(stripped) > 5 and has_major:
            return True
        if len(stripped) > 0 and has_major:
            return True
        return False


# ------------------------------------------------------------------
# Public Fonksiyon: 3 kodu karşılaştır (geriye dönük uyumluluk)
# ------------------------------------------------------------------
def advanced_judge(
    code_1: str, code_2: str, code_3: str, prompt: str
) -> Dict[str, Any]:
    """
    Üç kod parçacığını karşılaştırır ve en iyi skoru alanı kazanan seçer.
    """
    judge = AdvancedCodeJudge()

    from module.llm_judge import LLMJudge
    from module.llm_clients import get_model_names

    llm_judge   = LLMJudge()
    model_names = get_model_names()

    all_results: Dict[str, Any] = {}
    for i, code in enumerate([code_1, code_2, code_3], 1):
        name          = model_names.get(f"model_{i}", f"Model {i}")
        static        = judge.score_code(code)
        llm_eval      = llm_judge.evaluate_code(code, prompt)
        all_results[name] = judge.get_hybrid_score(static, llm_eval)

    winner = max(all_results, key=lambda k: all_results[k]["total_score"])

    return {
        "winner":    winner,
        "results":   all_results,
        "reasoning": all_results[winner]["reasoning"],
    }
