"""
Hybrid Agentic Workflow
İlk tur: 3 model yarışması → Kazanan seçimi
İkinci tur: Kazanan < eşik ise feedback döngüsü
"""

import os
import csv
import json
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import TypedDict, Dict, Any, List, Optional

from dotenv import load_dotenv
from langgraph.graph import StateGraph, END

from module.advanced_judge import AdvancedCodeJudge
from module.llm_clients import call_codellama, call_deepseek, call_gemini, get_model_names
from module.llm_judge import LLMJudge
from module.feedback_agent import generate_cot_feedback, format_suggestions_for_prompt

load_dotenv()

# --- CSV Logging Utility ---
def log_request_to_csv(
    user_prompt: str,
    winner_model: str,
    initial_code: str,
    llm_deficiencies: str,
    final_code: str,
    improvements_made: str,
    score_change_text: str,
    iteration_count: int,
    judge_model: str,
    log_file: str = "logs/workflow_log.csv"
):
    """
    Append workflow summary to CSV file with detailed configuration and output.
    """
    # Create logs directory if it doesn't exist
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # Check if file exists to determine if we need to write headers
    file_exists = os.path.isfile(log_file)
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Prepare row data
    row_data = [
        user_prompt[:1000].replace("\n", " "),
        winner_model,
        initial_code,
        llm_deficiencies,
        final_code,
        improvements_made,
        score_change_text,
        iteration_count,
        judge_model
    ]
    
    with open(log_file, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        # Write header if file is new
        if not file_exists:
            writer.writerow([
                "Prompt",
                "Winner_Model",
                "Initial_Code",
                "LLM_Deficiencies",
                "Final_Code",
                "Improvements_Made",
                "Score_Change",
                "Iteration_Count",
                "Judge_Model"
            ])
        
        # Write data row
        writer.writerow(row_data)


# --- Dynamic Threshold Utility ---
def calculate_dynamic_threshold(prompt: str) -> float:
    """
    Prompt karmaşıklığına göre dinamik kalite eşiği hesapla.
    
    Basit işlemler (aritmetik, tek satırlık) için düşük eşik,
    karmaşık algoritmalar için yüksek eşik.
    
    Returns:
        float: 55.0 - 75.0 arası threshold değeri
    """
    prompt_lower = prompt.lower()
    
    # Token sayısı (basit yaklaşım)
    word_count = len(prompt.split())
    
    # Karmaşıklık göstergeleri
    complexity_keywords = [
        'algorithm', 'algoritma', 'sort', 'search', 'binary', 'tree',
        'graph', 'recursive', 'dynamic', 'fibonacci', 'linked list',
        'hash', 'queue', 'stack', 'class', 'oop', 'design pattern',
        'api', 'database', 'async', 'thread', 'parallel'
    ]
    
    # Basitlik göstergeleri
    simple_keywords = [
        'topla', 'çıkar', 'çarp', 'böl', 'hesapla', 'yaz', 'print',
        '+', '-', '*', '/', 'kare', 'küp', 'katları', 'hello',
        'merhaba', 'basit', 'simple', 'basic'
    ]
    
    # Skor hesapla
    complexity_score = 0
    
    # Karmaşıklık keyword kontrolü
    for keyword in complexity_keywords:
        if keyword in prompt_lower:
            complexity_score += 10
    
    # Basitlik keyword kontrolü
    for keyword in simple_keywords:
        if keyword in prompt_lower:
            complexity_score -= 8
    
    # Word count bazlı ayarlama
    if word_count <= 5:
        complexity_score -= 10
    elif word_count >= 15:
        complexity_score += 5
    
    # Threshold hesapla (55-75 arası)
    base_threshold = 65.0
    threshold = base_threshold + (complexity_score / 5)
    
    # Sınırla
    threshold = max(55.0, min(75.0, threshold))
    
    print(f"📊 Dinamik Threshold: {threshold:.1f} (prompt karmaşıklık skoru: {complexity_score})")
    
    return threshold

# --- State Definition ---
class HybridState(TypedDict):
    """Hybrid workflow state"""
    prompt: str
    iteration_count: int
    max_iterations: int
    quality_threshold: float

    # Configuration
    static_weight: float
    llm_weight: float
    metric_weights: Optional[Dict[str, int]]

    # Round 1 Data
    round1_codes: Dict[str, str]
    round1_scores: Dict[str, Any]

    # Recursive Loop State
    current_code: str
    current_score: float
    previous_code_snapshot: str
    previous_categories: Dict[str, float]
    winner_model: str
    winner_code: str         # İlk turda seçilen kazanan kodu
    winner_score: float      # İlk turda kazananın skoru
    final_quality_score: float
    consecutive_no_improvement: int

    # Separate Analysis Results
    static_analysis_result: Dict[str, Any]
    llm_evaluation_result: Dict[str, Any]
    hybrid_score: float

    # Feedback
    quality_profile: str
    feedback_iterations: List[Dict[str, Any]]

    # Results
    final_code: str
    final_score: float
    status: str              # "direct_output" | "improved_via_feedback"
    judge_reasoning: str



# --- Node 1: Generator Node (Kod Oluşturma) ---
def generator_node(state: HybridState) -> HybridState:
    """
    Düğüm 1: Kod oluşturma düğümü. 
    İlk turda 3 model kullanır, sonraki turlarda kazananla devam eder.
    """
    prompt = state["prompt"]
    iteration = state.get("iteration_count", 0)
    
    if iteration == 0:
        print(f"\n{'='*60}")
        print(f"🏁 DÜĞÜM 1: İLK KOD OLUŞTURMA (3 MODEL - PARALEL)")
        print(f"{'='*60}\n")
        
        # Model isimlerini dinamik al (Ollama veya Cloud)
        model_names = get_model_names()
        
        def safe_call(name, func, p):
            try:
                print(f"  🚀 {name} başlatıldı...")
                res = func(p)
                print(f"  ✅ {name} tamamlandı.")
                return name, res
            except Exception as e:
                print(f"  ❌ {name} HATASI: {e}")
                return name, f"Error: {str(e)}"

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(safe_call, model_names["model_1"], call_codellama, prompt),
                executor.submit(safe_call, model_names["model_2"], call_deepseek, prompt),
                executor.submit(safe_call, model_names["model_3"], call_gemini, prompt)
            ]
            results = [f.result() for f in futures]
            codes = dict(results)

            for model_name, code in codes.items():
                preview = code.replace("\n", " ")[:50]
                print(f"  📝 {model_name} çıktısı ({len(code)} karakter): {preview}...")

        return {"round1_codes": codes}
    else:
        print(f"\n{'='*60}")
        print(f"🔄 DÜĞÜM 1: KOD İYİLEŞTİRME (İterasyon {iteration})")
        print(f"{'='*60}\n")
        
        # Geliştirilmiş ve daha direktif prompt oluştur
        quality_profile = state.get('quality_profile', '')
        current_code = state.get('current_code', '')
        
        enhanced_prompt = f"""# KOD İYİLEŞTİRME GÖREVİ

## Orijinal İstek
{prompt}

## Mevcut Kod
```python
{current_code}
```

## [KRİTİK] YARGICI GERİ BİLDİRİMİ (ÖNCELİK 1)
Aşağıdaki sorunlar tespit edilmiştir ve kodun kabul edilmesi için BUNLARI ÇÖZMEN ZORUNLUDUR:
{quality_profile}

## YAZILIM MÜHENDİSLİĞİ STANDARTLARI (ÖNCELİK 2)
Yukarıdaki Kritik Geri Bildirimleri KESİNLİKLE uyguladıktan sonra, kodun genel kalitesini korumak için şu standartları da sağla:
- Bütün sınıf ve fonksiyonlara detaylı Docstring ekle.
- Tüm parametrelere ve dönüş değerlerine Type Hints ekle.
- Beklenmedik hatalara karşı Error handling (try-except) ekle.
- Değişken isimlerini daha anlamlı yap.

⚠️ ÖNEMLİ: En büyük önceliğin [KRİTİK] YARGICI GERİ BİLDİRİMİ kısmındaki spesifik eksikleri gidermektir! ASLA halüsinasyon yapma, istenmeyen modül ekleme.
⚠️ SADECE saf Python kodu üret, açıklama yazma!"""
        
        winner_model = state["winner_model"]
        model_names = get_model_names()
        
        # Determine which function to call based on which model won
        if winner_model == model_names.get("model_1"):
            new_code = call_codellama(enhanced_prompt)
        elif winner_model == model_names.get("model_2"):
            new_code = call_deepseek(enhanced_prompt)
        else:
            new_code = call_gemini(enhanced_prompt)
            
        # Yeni kodu kaydet VE önceki kodu snapshot olarak sakla
        return {
            "previous_code_snapshot": state["current_code"],  # Generator çalışmadan ÖNCEKİ kod
            "current_code": new_code
        }

# --- Node 2: Static Analyzer Node (Statik Analiz Düğümü) ---
def static_analyzer_node(state: HybridState) -> HybridState:
    """
    Düğüm 2: Statik analiz düğümü (AST, Pylint, Radon, Bandit, Flake8).
    """
    prompt = state["prompt"]
    iteration = state.get("iteration_count", 0)
    metric_weights = state.get("metric_weights", None)
    
    print(f"\n{'='*60}")
    print(f"🔍 DÜĞÜM 2: STATİK ANALİZ")
    print(f"{'='*60}\n")
    
    from module.advanced_judge import AdvancedCodeJudge
    judge = AdvancedCodeJudge(metric_weights=metric_weights)
    
    if iteration == 0:
        round1_codes = state["round1_codes"]
        static_results = {}
        for model, code in round1_codes.items():
            result = judge.score_code(code)
            static_results[model] = result
            display_score = (result["static_total"] / 70) * 100
            print(f"📊 {model} Statik Skor: {display_score:.1f}/100")
        return {"static_analysis_result": static_results}
    else:
        new_code = state["current_code"]
        result = judge.score_code(new_code)
        display_score = (result["static_total"] / 70) * 100
        print(f"📊 Statik Analiz Skoru: {display_score:.1f}/100")
        return {"static_analysis_result": result}


# --- Node 3: LLM Judge Node (LLM Değerlendirme Düğümü) ---
def llm_judge_node(state: HybridState) -> HybridState:
    """
    Düğüm 3: LLM semantic değerlendirme düğümü.
    """
    prompt = state["prompt"]
    iteration = state.get("iteration_count", 0)

    print(f"\n{'='*60}")
    print(f"🤖 DÜĞÜM 3: LLM SEMANTIC DEĞERLENDİRME")
    print(f"{'='*60}\n")

    llm_judge = LLMJudge()

    if iteration == 0:
        round1_codes = state["round1_codes"]
        llm_results = {}
        for model, code in round1_codes.items():
            time.sleep(2)  # Ollama/RAM için nefes molası
            result = llm_judge.evaluate_code(code, prompt)
            llm_results[model] = result
            display_score = (result["semantic_score"] / 30) * 100
            print(f"📊 {model} LLM Skor: {display_score:.1f}/100")
            if result.get("error"):
                print(f"   ⚠️ Hata: {result.get('reasoning', 'Unknown error')}")
            else:
                print(f"   💬 Reasoning: {result.get('reasoning', '')[:100]}...")
        return {"llm_evaluation_result": llm_results}
    else:
        new_code = state["current_code"]
        result = llm_judge.evaluate_code(new_code, prompt)
        display_score = (result["semantic_score"] / 30) * 100
        print(f"📊 LLM Semantic Skor: {display_score:.1f}/100")
        if result.get("error"):
            print(f"   ⚠️ Hata: {result.get('reasoning', 'Unknown error')}")
        return {"llm_evaluation_result": result}


# --- Node 4: Hybrid Scorer Node (Hibrit Skor Birleştirme Düğümü) ---
def hybrid_scorer_node(state: HybridState) -> HybridState:
    """
    Düğüm 4: Static ve LLM sonuçlarını birleştirip hybrid skor hesapla.
    """
    iteration = state.get("iteration_count", 0)
    static_weight = state.get("static_weight", 0.7)
    llm_weight = state.get("llm_weight", 0.3)
    metric_weights = state.get("metric_weights", None)
    
    print(f"\n{'='*60}")
    print(f"⚖️  DÜĞÜM 4: HİBRİT SKOR BİRLEŞTİRME")
    print(f"   (Ağırlıklar - Statik: {static_weight}, LLM: {llm_weight})")
    print(f"{'='*60}\n")
    
    from module.advanced_judge import AdvancedCodeJudge
    judge = AdvancedCodeJudge(metric_weights=metric_weights)
    
    if iteration == 0:
        # İLK TUR: 3 modelin hybrid skorlarını hesapla
        static_results = state["static_analysis_result"]
        llm_results = state["llm_evaluation_result"]
        
        hybrid_scores = {}
        full_analysis = {}
        
        for model in static_results.keys():
            static_analysis = static_results[model]
            llm_evaluation = llm_results[model]
            
            # Hybrid skor hesapla
            hybrid_result = judge.get_hybrid_score(static_analysis, llm_evaluation)
            hybrid_scores[model] = hybrid_result["total_score"]
            full_analysis[model] = hybrid_result
            
            print(f"📊 {model} Toplam Skor: {hybrid_result['total_score']}/100")
        
        # Kazananı bul
        winner = max(hybrid_scores, key=hybrid_scores.get)
        
        # DÜZELTME: Kalite puanı olarak KAZANANIN skorunu kullan (ortalama değil!)
        # Eski: final_quality_score = sum(hybrid_scores.values()) / len(hybrid_scores)
        final_quality_score = hybrid_scores[winner]
        
        print(f"\n🏆 Kazanan: {winner} (Skor: {final_quality_score}/100)")
        
        # Kalite Profili Oluştur
        quality_parts = []
        for model, analysis in full_analysis.items():
            total = analysis.get("total_score", 0)
            static = analysis.get("static_total", 0)
            llm = analysis.get("llm_total", 0)
            reasoning = analysis.get("reasoning", "")
            
            quality_parts.append(f"### {model}")
            quality_parts.append(f"- Hybrid Skor: {total}/100 (Statik: {static:.1f}/70 (%{(static/70*100):.1f} Başarı) | LLM: {llm}/30 (%{(llm/30*100):.1f} Başarı))")
            quality_parts.append(f"- Değerlendirme: {reasoning}")
        
        quality_profile = "\n".join(quality_parts)
        
        # İLK TURDA SPESİFİK ÖNERİLER EKLE
        winner_analysis = full_analysis[winner]
        breakdown = winner_analysis.get("static_analysis", {}).get("breakdown", {})
        initial_suggestions = []
        
        if breakdown.get("syntax", {}).get("score", 0) < 15:
            initial_suggestions.append("- Kod yapısını iyileştir: Docstring ekle, class ve function kullan")
        if breakdown.get("complexity", {}).get("average_complexity", 0) > 10:
            initial_suggestions.append("- Karmaşıklığı azalt: Büyük fonksiyonları böl, nested if'leri azalt")
        if breakdown.get("pylint", {}).get("raw_score", 0) < 7:
            initial_suggestions.append("- Pylint uyarılarını düzelt ve kod kalitesini artır")
        if breakdown.get("style", {}).get("violations", 0) > 5:
            initial_suggestions.append("- PEP8 standartlarına uy (satır uzunluğu, boşluk kullanımı vb.)")
        
        if initial_suggestions:
            quality_profile += "\n\n## ÖNCELİKLİ İYİLEŞTİRMELER:\n" + "\n".join(initial_suggestions)
        
        print(f"\n📋 QUALITY PROFILE OLUŞTURULDU ({len(quality_profile)} karakter)\n")
        
        # 4_categories'i kazanandan al
        winner_4_categories = static_results[winner].get("4_categories", {})
        
        return {
            "round1_scores": full_analysis,
            "winner_model": winner,
            "winner_code": state["round1_codes"][winner],
            "current_code": state["round1_codes"][winner],
            "winner_score": hybrid_scores[winner],
            "final_quality_score": final_quality_score,
            "current_score": hybrid_scores[winner],
            "hybrid_score": hybrid_scores[winner],
            "quality_profile": quality_profile,
            "previous_categories": winner_analysis.get("categories", {}),
            "previous_code_snapshot": state["round1_codes"][winner],
            "iteration_count": iteration + 1,
            "consecutive_no_improvement": 0
        }
    else:
        # FEEDBACK TURU: İyileştirilen kodun hybrid skorunu hesapla
        previous_code = state.get("previous_code_snapshot", "")
        new_code = state["current_code"]
        previous_score = state["current_score"]
        previous_categories = state.get("previous_categories", {})
        
        static_analysis = state["static_analysis_result"]
        llm_evaluation = state["llm_evaluation_result"]
        
        # Hybrid skor hesapla
        hybrid_result = judge.get_hybrid_score(static_analysis, llm_evaluation)
        new_score = hybrid_result["total_score"]
        new_categories = hybrid_result.get("categories", {})
        
        print(f"📊 Yeni Toplam Skor: {new_score}/100")
        
        # Chain-of-Thought Feedback Agent ile dinamik öneriler üret
        print(f"\n🧠 CoT Feedback Agent çalışıyor...")
        cot_feedback = generate_cot_feedback(
            code=new_code,
            original_prompt=state["prompt"],
            static_analysis=static_analysis,
            llm_evaluation=llm_evaluation,
            previous_score=previous_score,
            current_score=new_score
        )

        suggestions      = cot_feedback.get("suggestions", [])
        cot_summary      = cot_feedback.get("summary", "")
        chain_of_thought = cot_feedback.get("chain_of_thought", "")

        if suggestions:
            print(f"✅ {len(suggestions)} dinamik öneri üretildi")
            for s in suggestions[:3]:
                print(f"   [{s.get('priority', '?')}] {s.get('area', 'Genel')}: {s.get('action', '')[:50]}...")
        else:
            print("⚠️  Öneri üretilemedi, fallback kullanılıyor")
            suggestions = [{"priority": 2, "area": "Genel", "issue": "Kod kalitesi düşük",
                            "action": "Docstring, type hints ve error handling ekle"}]
        
        # Metrik değişimlerini hesapla (6 yeni kategori)
        metric_changes = {}
        for cat_name, new_val in new_categories.items():
            old_val = previous_categories.get(cat_name, 0)
            metric_changes[cat_name] = new_val - old_val
        
        # Feedback geçmişini güncelle
        feedback_iter = state.get("feedback_iterations", [])
        
        # Önceki kodu doğru şekilde al
        if iteration == 1:
            previous_code_for_display = state.get("winner_code", "") or state.get("previous_code_snapshot", "")
        else:
            previous_code_for_display = previous_code if previous_code else state.get("previous_code_snapshot", "")
        
        feedback_iter.append({
            "iteration": iteration,
            "previous_code": previous_code_for_display,
            "new_code": new_code,
            "previous_score": previous_score,
            "new_score": new_score,
            "score_improvement": new_score - previous_score,
            "suggestions": suggestions,
            "reasoning": llm_evaluation.get("reasoning", ""),
            "chain_of_thought": chain_of_thought,
            "static_breakdown": static_analysis.get("breakdown", {}),
            "metric_changes": metric_changes,
            "previous_categories": previous_categories,
            "new_categories": new_categories
        })
        
        # Kalite profilini güncelle - DİNAMİK ÖNERİLER ile
        reasoning = llm_evaluation.get("reasoning", "")
        feedback_text = format_suggestions_for_prompt(suggestions)
        
        # ROLLBACK MEKANİZMASI: Skor düştüyse önceki kodu koru
        rollback_applied = False
        final_code = new_code
        final_score = new_score
        final_categories = new_categories
        
        consecutive_no_improvement = state.get("consecutive_no_improvement", 0)
        
        if new_score <= previous_score:
            consecutive_no_improvement += 1
        else:
            consecutive_no_improvement = 0
            
        if new_score < previous_score:  # En ufak bir düşüş olsa bile kabul etmiyoruz
            print(f"⚠️  ROLLBACK: Skor {previous_score:.1f} → {new_score:.1f} düştü. Önceki daha iyi kod korunuyor.")
            rollback_applied = True
            final_code = previous_code
            final_score = previous_score
            final_categories = previous_categories
        else:
            if new_score == previous_score:
                print(f"⚠️  DEĞİŞİKLİK YOK: Skor {previous_score:.1f} (sabit kaldı).")
            else:
                print(f"✅ İyileştirme: {previous_score:.1f} → {new_score:.1f}")
        
        new_quality_profile = f"""### İTERASYON {iteration} FEEDBACK (CoT)

**Mevcut Skor**: {previous_score}/100 → {new_score}/100 (Değişim: {new_score - previous_score:+.1f})
{f"**⚠️ ROLLBACK UYGULANDI** - Önceki kod korundu" if rollback_applied else ""}

**LLM Semantic Değerlendirmesi**:
{reasoning}

**🧠 Chain-of-Thought Dinamik Öneriler**:
{feedback_text}

{f"**Özet**: {cot_summary}" if cot_summary else ""}

**ÖNEMLİ**: Yukarıdaki ÖNCELİKLİ önerileri DİKKATLE uygula. Yüksek öncelikli olanları MUTLAKA düzelt."""
        
        print(f"\n📋 UPDATED QUALITY PROFILE ({len(new_quality_profile)} karakter):")
        print(new_quality_profile[:500] + "..." if len(new_quality_profile) > 500 else new_quality_profile)
        print()
        
        return {
            "current_code": final_code,  # Rollback varsa önceki, yoksa yeni kod
            "current_score": final_score,
            "final_quality_score": final_score,
            "hybrid_score": final_score,
            "feedback_iterations": feedback_iter,
            "quality_profile": new_quality_profile,
            "previous_categories": final_categories,
            "iteration_count": iteration + 1,
            "consecutive_no_improvement": consecutive_no_improvement
        }


# --- Finalize Node ---
def finalize_node(state: HybridState) -> HybridState:
    """Süreci sonlandırır."""
    
    # Extract reasoning from the latest iteration or the winner
    if state.get("feedback_iterations"):
        reasoning = state["feedback_iterations"][-1].get("reasoning", "")
    else:
        # Getting reasoning from round 1 specific to the winner
        winner = state["winner_model"]
        reasoning = state["round1_scores"].get(winner, {}).get("breakdown", {}).get("llm_evaluation", {}).get("reasoning", "")
        
    return {
        "final_code": state["current_code"],
        "final_score": state["current_score"],
        "round1_codes": state.get("round1_codes", {}),
        "round1_scores": state.get("round1_scores", {}),
        "winner_model": state.get("winner_model", ""),
        "winner_score": state.get("winner_score", 0),
        "feedback_iterations": state.get("feedback_iterations", []),
        "status": "improved_via_feedback" if state["iteration_count"] > 1 else "direct_output",
        "judge_reasoning": reasoning
    }

# --- Decision Node: Devam edilsin mi? ---
def should_continue(state: HybridState) -> str:
    """Eşik kontrolü ve döngü kararı."""
    score = state["final_quality_score"]
    threshold = state.get("quality_threshold", 70.0)
    iteration = state.get("iteration_count", 0)
    consecutive = state.get("consecutive_no_improvement", 0)
    
    print(f"\n⚖️  DÖNGÜ KONTROLÜ:")
    print(f"   Mevcut Kalite Puanı: {score:.2f}, Eşik: {threshold}, İterasyon: {iteration}, İyileşmeme: {consecutive}/4")
    
    max_iters = state.get("max_iterations", 3)
    
    if score >= threshold:
        print(f"   ✅ Hedef sağlandı ({threshold}). Sonlandırılıyor...\n")
        return "finalize"
    elif consecutive >= 4:
        print(f"   🛑 Art arda 4 iterasyon iyileşme sağlanamadı ({consecutive}/4). Erken sonlandırılıyor...\n")
        return "finalize"
    elif iteration >= max_iters:
        print(f"   ⚠️  Maksimum iterasyon sayısına ({max_iters}) ulaşıldı. Sonlandırılıyor...\n")
        return "finalize"
    else:
        print("   🔄 Kalite yetersiz. Feedback döngüsü devam ediyor...\n")
        return "generate"

# --- Graph Construction ---
workflow = StateGraph(HybridState)

# 4 ayrı node ekleniyor
workflow.add_node("generator", generator_node)
workflow.add_node("static_analyzer", static_analyzer_node)  # YENİ
workflow.add_node("llm_judge", llm_judge_node)              # YENİ
workflow.add_node("hybrid_scorer", hybrid_scorer_node)      # YENİ (eski judge yerine)
workflow.add_node("finalize", finalize_node)

workflow.set_entry_point("generator")

# Akış sırası: generator → static_analyzer → llm_judge → hybrid_scorer
workflow.add_edge("generator", "static_analyzer")
workflow.add_edge("static_analyzer", "llm_judge")
workflow.add_edge("llm_judge", "hybrid_scorer")

# Conditional: feedback veya finalize
workflow.add_conditional_edges(
    "hybrid_scorer",
    should_continue,
    {
        "generate": "generator",  # Feedback loop
        "finalize": "finalize"
    }
)

workflow.add_edge("finalize", END)

hybrid_graph = workflow.compile()


# --- Public Interface ---
def run_hybrid_workflow(prompt: str, 
                       quality_threshold: float = None, 
                       max_iterations: int = 3,
                       static_weight: float = 0.7,
                       llm_weight: float = 0.3,
                       metric_weights: Dict[str, int] = None) -> Dict[str, Any]:
    """
    Hybrid workflow çalıştır
    
    Args:
        prompt: Kullanıcı prompt'u
        quality_threshold: Kalite eşiği (None ise dinamik hesaplanır)
        max_iterations: Maksimum iterasyon sayısı
        static_weight: Statik analiz ağırlığı (default 0.7)
        llm_weight: LLM değerlendirme ağırlığı (default 0.3)
        metric_weights: Statik analiz metrik ağırlıkları (opsiyonel)
    """
    # Dinamik threshold hesapla veya verilen değeri kullan
    if quality_threshold is None:
        quality_threshold = calculate_dynamic_threshold(prompt)
    
    print(f"\n{'='*60}")
    print(f"🚀 HYBRID WORKFLOW BAŞLIYOR")
    print(f"{'='*60}")
    print(f"Prompt: {prompt[:100]}...")
    print(f"Kalite Eşiği: {quality_threshold}/100 {'(📊 Dinamik)' if quality_threshold != 70.0 else ''}")
    print(f"Max İterasyon: {max_iterations}")
    print(f"Ağırlıklar: Static={static_weight}, LLM={llm_weight}")
    if metric_weights:
        print(f"Özel Metrik Ağırlıkları: {metric_weights}")
    print(f"{'='*60}\n")
    
    initial_state = {
        "prompt":                    prompt,
        "iteration_count":           0,
        "max_iterations":            max_iterations,
        "quality_threshold":         quality_threshold,
        "static_weight":             static_weight,
        "llm_weight":                llm_weight,
        "metric_weights":            metric_weights,
        "round1_codes":              {},
        "round1_scores":             {},
        "current_code":              "",
        "current_score":             0.0,
        "previous_code_snapshot":    "",
        "previous_categories":       {},
        "winner_model":              "",
        "winner_code":               "",
        "winner_score":              0.0,
        "final_quality_score":       0.0,
        "consecutive_no_improvement": 0,
        "static_analysis_result":    {},
        "llm_evaluation_result":     {},
        "hybrid_score":              0.0,
        "quality_profile":           "",
        "feedback_iterations":       [],
        "final_code":                "",
        "final_score":               0.0,
        "status":                    "",
        "judge_reasoning":           "",
    }
    
    result = hybrid_graph.invoke(
        initial_state,
        config={"recursion_limit": 50}
    )
    
    print(f"\n{'='*60}")
    print(f"✨ WORKFLOW TAMAMLANDI")
    print(f"{'='*60}")
    print(f"Durum: {result['status']}")
    print(f"Son Skor: {result['final_score']}/100")
    print(f"{'='*60}\n")
    
    _log_workflow_result(
        result=result,
        prompt=prompt,
        quality_threshold=quality_threshold,
        max_iterations=max_iterations,
        static_weight=static_weight,
        llm_weight=llm_weight,
    )
    return result


# --- Private: Loglama Yardımcısı ---
def _log_workflow_result(
    result: Dict[str, Any],
    prompt: str,
    quality_threshold: float,
    max_iterations: int,
    static_weight: float,
    llm_weight: float,
) -> None:
    """Workflow sonucunu CSV ve Excel'e yazar."""
    try:
        request_id   = f"REQ_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
        model_names  = get_model_names()
        round1_scores = result.get("round1_scores", {})

        winner_data  = round1_scores.get(result.get("winner_model"), {})
        cats         = winner_data.get("categories", {})
        model_scores = {
            "cat1": cats.get("1_Kod_Kalitesi", 0),
            "cat2": cats.get("2_Teknik_Borc", 0),
            "cat3": cats.get("3_Test_Build", 0),
            "cat4": cats.get("4_Stil_Standart", 0),
            "cat5": cats.get("5_Semantic_Alignment", 0),
            "cat6": cats.get("6_Robustness_Safety", 0),
        }

        iteration_count = max(0, result.get("iteration_count", 0) - 1)
        final_score     = result.get("final_score", 0.0)
        winner_score    = result.get("winner_score", 0.0)
        score_diff      = final_score - winner_score
        
        score_change_text = f"{winner_score:.1f} -> {final_score:.1f} ({score_diff:+.1f})"
        
        status = (
            "MAX_ITER_REACHED"
            if iteration_count >= max_iterations and final_score < quality_threshold
            else "SUCCESS"
        )

        judge_model = LLMJudge().get_model_name()
        
        # Yapılan iyileştirmeleri feedback_iterations'tan topla
        feedback_iterations = result.get("feedback_iterations", [])
        improvements_list = []
        for i, iter_data in enumerate(feedback_iterations, 1):
            iter_improvements = []
            for suggestion in iter_data.get("suggestions", []):
                action = suggestion.get("action", "")
                if action:
                    iter_improvements.append(f"- {action}")
            if iter_improvements:
                improvements_list.append(f"İterasyon {i}:\n" + "\n".join(iter_improvements))
        
        improvements_made = "\n\n".join(improvements_list) if improvements_list else "İyileştirme gerekmedi."

        log_request_to_csv(
            user_prompt=prompt,
            winner_model=result.get("winner_model", "Unknown"),
            initial_code=result.get("winner_code", ""),
            llm_deficiencies=winner_data.get("reasoning", ""),
            final_code=result.get("final_code", ""),
            improvements_made=improvements_made,
            score_change_text=score_change_text,
            iteration_count=iteration_count,
            judge_model=judge_model,
        )
        print(f"📝 Kapsamlı log kaydedildi: {request_id}")

        # Excel raporu oluştur (ayrı modül gerektirmez)
        try:
            import pandas as pd
            from openpyxl.styles import Font, PatternFill, Alignment

            csv_path   = "logs/workflow_log.csv"
            excel_path = "logs/workflow_report.xlsx"

            df = pd.read_csv(csv_path)
            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Workflow_Report")
                ws = writer.sheets["Workflow_Report"]

                header_fill = PatternFill(start_color="D7E4BC", end_color="D7E4BC", fill_type="solid")
                header_font = Font(bold=True)
                for cell in ws[1]:
                    cell.fill      = header_fill
                    cell.font      = header_font
                    cell.alignment = Alignment(horizontal="center", vertical="center")

                wrap_alignment = Alignment(wrap_text=True, vertical="top")
                for col_cells in ws.columns:
                    # Sabit bir maksimum genişlik vererek yazının alta sarılmasını (wrap_text) sağlıyoruz
                    ws.column_dimensions[col_cells[0].column_letter].width = 60
                    for cell in col_cells:
                        if cell.row > 1: # Başlık hücresi hariç
                            cell.alignment = wrap_alignment

            print(f"  ✅ Excel raporu başarıyla güncellendi: {excel_path}")
        except Exception as excel_err:
            print(f"⚠️  Excel güncelleme hatası: {excel_err}")

    except Exception as exc:
        print(f"❌ Loglama hatası: {exc}")
        traceback.print_exc()

