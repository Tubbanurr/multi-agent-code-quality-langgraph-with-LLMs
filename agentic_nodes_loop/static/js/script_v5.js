// Global Functions (attached to window for direct HTML access)
window.copyCode = function (elementId) {
    const codeElement = document.getElementById(elementId);
    if (!codeElement) {
        console.error("Copy failed: Element not found", elementId);
        return;
    }

    const text = codeElement.innerText || codeElement.textContent || "";
    if (!text) return;

    const triggerFeedback = () => {
        const container = codeElement.closest('.code-container') || codeElement.closest('.comparison-col');
        const btn = container ? container.querySelector('.copy-btn') : null;
        if (btn) {
            const originalText = btn.textContent;
            btn.textContent = "Copied!";
            btn.classList.add("copied");
            setTimeout(() => {
                btn.textContent = originalText;
                btn.classList.remove("copied");
            }, 2000);
        }
    };

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text)
            .then(() => triggerFeedback())
            .catch(err => {
                console.warn("Modern copy failed, trying fallback...", err);
                if (window.fallbackCopyTextToClipboard(text)) triggerFeedback();
            });
    } else {
        if (window.fallbackCopyTextToClipboard(text)) triggerFeedback();
    }
};

window.fallbackCopyTextToClipboard = function (text) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    textArea.style.left = "-9999px";
    textArea.style.top = "0";
    textArea.style.opacity = "0";
    textArea.setAttribute("readonly", "");
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    textArea.setSelectionRange(0, 999999);

    let successful = false;
    try {
        successful = document.execCommand('copy');
    } catch (err) {
        console.error('Fallback copy failed:', err);
    }
    document.body.removeChild(textArea);
    return successful;
};

// Error Handler
window.onerror = function (message, source, lineno, colno, error) {
    console.error(`JS HATA: ${message} @ ${source}:${lineno}:${colno}`);
    return false;
};

async function generate() {
    const prompt = document.getElementById("prompt").value;
    if (!prompt) return alert("Lütfen bir prompt girin");

    const btn = document.getElementById("btn-generate");
    const loader = document.getElementById("loader");

    // UI Loading
    btn.disabled = true;
    loader.style.display = "inline-block";

    // Hide sections
    document.getElementById("round1-section").style.display = "none";
    document.getElementById("winner-section").style.display = "none";

    try {
        const response = await fetch("/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt })
        });

        if (!response.ok) throw new Error("API Hatası");

        const data = await response.json();
        console.log("Sonuç:", data);

        // Round 1: 3 model kodları göster (HYBRID SCORES)
        showRound1(data.round1_codes, data.round1_scores);

        // Kazanan ve feedback
        showWinner(data);

    } catch (error) {
        alert("Hata: " + error.message);
    } finally {
        btn.disabled = false;
        loader.style.display = "none";
    }
}

// ═══════════════════════════════════════════
// 2. PARTICLE FIELD - Mouse-interactive
// ═══════════════════════════════════════════
(function initParticles() {
    const canvas = document.createElement('canvas');
    canvas.id = 'particle-canvas';
    document.body.prepend(canvas);
    const ctx = canvas.getContext('2d');
    let particles = [];
    let mouse = { x: -999, y: -999 };
    const PARTICLE_COUNT = 120;
    const CONNECT_DIST = 150;

    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }
    window.addEventListener('resize', resize);
    resize();

    document.addEventListener('mousemove', e => {
        mouse.x = e.clientX;
        mouse.y = e.clientY;
    });

    class Particle {
        constructor() {
            this.x = Math.random() * canvas.width;
            this.y = Math.random() * canvas.height;
            this.vx = (Math.random() - 0.5) * 0.4;
            this.vy = (Math.random() - 0.5) * 0.4;
            this.r = Math.random() * 2.2 + 0.8;
            this.alpha = Math.random() * 0.5 + 0.2;
        }
        update() {
            // Mouse repel
            const dx = this.x - mouse.x;
            const dy = this.y - mouse.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < 150) {
                const force = (150 - dist) / 150 * 0.02;
                this.vx += dx / dist * force;
                this.vy += dy / dist * force;
            }
            this.x += this.vx;
            this.y += this.vy;
            // Wrap around
            if (this.x < 0) this.x = canvas.width;
            if (this.x > canvas.width) this.x = 0;
            if (this.y < 0) this.y = canvas.height;
            if (this.y > canvas.height) this.y = 0;
            // Damping
            this.vx *= 0.999;
            this.vy *= 0.999;
        }
        draw() {
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(140, 160, 255, ${this.alpha})`;
            ctx.fill();
        }
    }

    for (let i = 0; i < PARTICLE_COUNT; i++) particles.push(new Particle());

    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => { p.update(); p.draw(); });
        // Connection lines
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x;
                const dy = particles[i].y - particles[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < CONNECT_DIST) {
                    ctx.beginPath();
                    ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = `rgba(120, 180, 255, ${0.18 * (1 - dist / CONNECT_DIST)})`;
                    ctx.lineWidth = 0.5;
                    ctx.stroke();
                }
            }
        }
        requestAnimationFrame(animate);
    }
    animate();
})();

// ═══════════════════════════════════════════
// 7. SCORE RING - SVG animated circle
// ═══════════════════════════════════════════
function getScoreColor(score) {
    if (score >= 85) return '#f97316';   // Orange/Gold
    if (score >= 65) return '#3b82f6';   // Blue
    if (score >= 45) return '#f59e0b';   // Amber
    return '#64748b';                    // Gray
}

function createScoreRing(score, size = 95) {
    const r = (size / 2) - 7;
    const circ = 2 * Math.PI * r;
    const offset = circ * (1 - score / 100);
    const color = getScoreColor(score);
    const glowId = `glow-${Math.random().toString(36).slice(2, 8)}`;

    return `
        <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="--ring-color: ${color};">
            <defs>
                <filter id="${glowId}">
                    <feGaussianBlur stdDeviation="3" result="blur"/>
                    <feMerge>
                        <feMergeNode in="blur"/>
                        <feMergeNode in="SourceGraphic"/>
                    </feMerge>
                </filter>
            </defs>
            <!-- Background ring -->
            <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none"
                    stroke="rgba(255,255,255,0.05)" stroke-width="6"/>
            <!-- Score ring with glow -->
            <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none"
                    stroke="${color}" stroke-width="6"
                    stroke-dasharray="${circ}" stroke-dashoffset="${offset}"
                    transform="rotate(-90 ${size / 2} ${size / 2})" stroke-linecap="round"
                    filter="url(#${glowId})"
                    style="transition: stroke-dashoffset 1.2s cubic-bezier(0.4, 0, 0.2, 1);"/>
            <!-- Score number -->
            <text x="${size / 2}" y="${size / 2 - 3}" text-anchor="middle" dominant-baseline="central"
                  fill="white" font-size="${size * 0.3}" font-weight="800"
                  font-family="Inter, sans-serif">${score}</text>
            <!-- HYBRID label -->
            <text x="${size / 2}" y="${size / 2 + 15}" text-anchor="middle"
                  fill="${color}" font-size="${size * 0.09}" font-weight="700"
                  letter-spacing="0.15em" font-family="Inter, sans-serif">HYBRID</text>
        </svg>
    `;
}

// ═══════════════════════════════════════════
// SHOW ROUND 1 - Enhanced with all effects
// ═══════════════════════════════════════════
function showRound1(codes, scoresData) {
    document.getElementById("round1-section").style.display = "block";

    const modelKeys = Object.keys(codes);
    const modelSlots = ["model-1", "model-2", "model-3"];

    // Find winner model
    let maxScore = -1;
    let winnerModel = '';
    modelKeys.forEach(name => {
        const s = scoresData[name]?.total_score || 0;
        if (s > maxScore) { maxScore = s; winnerModel = name; }
    });

    modelKeys.forEach((modelName, index) => {
        const slotId = modelSlots[index] || `model-${index}`;
        const code = codes[modelName] || "Kod üretilemedi";
        const scoreData = scoresData[modelName];
        const isWinner = modelName === winnerModel;

        // 10. Winner card glow
        const card = document.getElementById(`score-${slotId}`)?.closest('.model-card');
        if (card) {
            if (isWinner) card.classList.add('winner-card');
            else card.classList.remove('winner-card');
        }

        // Model header with number + winner badge
        const headerElement = document.getElementById(`header-${slotId}`);
        if (headerElement) {
            const nameParts = modelName.split(':');
            const mainName = nameParts[0] || modelName;
            const subName = nameParts.slice(1).join(':') || '';

            headerElement.innerHTML = `
                <span class="model-number">${index + 1}</span>
                <span class="model-name-text">
                    ${mainName}
                    ${subName ? `<span class="model-name-sub">${subName}</span>` : ''}
                </span>
                ${isWinner ? '<span class="winner-badge">👑 KAZANAN</span>' : ''}
            `;
        }

        // Display code
        const codeElement = document.getElementById(`code-${slotId}`);
        if (codeElement) codeElement.textContent = code;

        // Score panel
        const scorePanel = document.getElementById(`score-${slotId}`);
        if (!scorePanel) {
            console.error(`Missing element: score-${slotId}`);
            return;
        }

        if (!scoreData || scoreData.is_error) {
            scorePanel.innerHTML = `
                <div style="padding: 1.5rem; text-align: center; background: rgba(239, 68, 68, 0.05); border-radius: 8px; border: 1px solid rgba(239, 68, 68, 0.2);">
                    <div style="font-weight: 700; color: #ef4444; font-size: 1.1rem;">API HATASI</div>
                    <div style="margin-top: 0.5rem; color: #94a3b8; font-size: 0.85rem;">Model kod üretemedi</div>
                </div>
            `;
            return;
        }

        const hybridScore = scoreData.total_score || 0;
        const staticScore = scoreData.static_total || 0;
        const llmScore = scoreData.llm_total || 0;

        const categories = scoreData.categories || {};
        const staticAnalysis = scoreData.static_analysis || {};
        const llmEvaluation = scoreData.llm_evaluation || {};
        const staticBreakdown = staticAnalysis.breakdown || {};
        const llmBreakdown = llmEvaluation.breakdown || {};

        scorePanel.innerHTML = `
            <!-- 7. Score Ring + Details -->
            <div class="score-display">
                <div class="score-circle-container">
                    ${createScoreRing(hybridScore)}
                </div>
                <div class="score-details">
                    <div class="score-detail-row">
                        <span class="detail-icon" style="background: #3b82f6; color: #3b82f6;"></span>
                        <span class="detail-label">Statik Analiz</span>
                        <span class="detail-value">${staticScore.toFixed(0)}/70</span>
                    </div>
                    <div class="score-detail-row">
                        <span class="detail-icon" style="background: #8b5cf6; color: #8b5cf6;"></span>
                        <span class="detail-label">LLM Değerlendirme</span>
                        <span class="detail-value">${llmScore}/30</span>
                    </div>
                </div>
            </div>
            
            <!-- 6 Hybrid Categories -->
            <div class="categories-container">
                <div class="categories-title">Kalite Metrikleri (6 Kategori)</div>
                
                <div class="category-item">
                    <div class="category-header">
                        <span class="category-label">1. Kod Kalitesi</span>
                        <span class="category-value">${categories["1_Kod_Kalitesi"] || 0}/20</span>
                    </div>
                    <div class="progress-bar"><div class="progress-fill" style="width: ${(categories["1_Kod_Kalitesi"] || 0) / 20 * 100}%; background: #3b82f6; color: #3b82f6;"></div></div>
                </div>
                <div class="category-item">
                    <div class="category-header">
                        <span class="category-label">2. Teknik Borç</span>
                        <span class="category-value">${categories["2_Teknik_Borc"] || 0}/20</span>
                    </div>
                    <div class="progress-bar"><div class="progress-fill" style="width: ${(categories["2_Teknik_Borc"] || 0) / 20 * 100}%; background: #f59e0b; color: #f59e0b;"></div></div>
                </div>
                <div class="category-item">
                    <div class="category-header">
                        <span class="category-label">3. Test & Build</span>
                        <span class="category-value">${categories["3_Test_Build"] || 0}/15</span>
                    </div>
                    <div class="progress-bar"><div class="progress-fill" style="width: ${(categories["3_Test_Build"] || 0) / 15 * 100}%; background: #10b981; color: #10b981;"></div></div>
                </div>
                <div class="category-item">
                    <div class="category-header">
                        <span class="category-label">4. Stil & Standart</span>
                        <span class="category-value">${categories["4_Stil_Standart"] || 0}/15</span>
                    </div>
                    <div class="progress-bar"><div class="progress-fill" style="width: ${(categories["4_Stil_Standart"] || 0) / 15 * 100}%; background: #6366f1; color: #6366f1;"></div></div>
                </div>
                <div class="category-item">
                    <div class="category-header">
                        <span class="category-label">5. Semantic Alignment</span>
                        <span class="category-value">${categories["5_Semantic_Alignment"] || 0}/15</span>
                    </div>
                    <div class="progress-bar"><div class="progress-fill" style="width: ${(categories["5_Semantic_Alignment"] || 0) / 15 * 100}%; background: #ec4899; color: #ec4899;"></div></div>
                </div>
                <div class="category-item">
                    <div class="category-header">
                        <span class="category-label">6. Robustness & Safety</span>
                        <span class="category-value">${categories["6_Robustness_Safety"] || 0}/15</span>
                    </div>
                    <div class="progress-bar"><div class="progress-fill" style="width: ${(categories["6_Robustness_Safety"] || 0) / 15 * 100}%; background: #ef4444; color: #ef4444;"></div></div>
                </div>
            </div>
            
            <!-- LLM Semantic Evaluation -->
            <div class="llm-evaluation">
                <div class="llm-title">LLM Semantic Değerlendirme</div>
                <div class="llm-breakdown">
                    <div><span>Identifier Clarity:</span><span class="llm-score-value">${llmBreakdown.identifier_clarity || 0}/5</span></div>
                    <div><span>Prompt Adherence:</span><span class="llm-score-value">${llmBreakdown.prompt_adherence || 0}/10</span></div>
                    <div><span>Naming Alignment:</span><span class="llm-score-value">${llmBreakdown.naming_alignment || 0}/5</span></div>
                    <div><span>Logic & Reliability:</span><span class="llm-score-value">${llmBreakdown.test_reliability || 0}/10</span></div>
                </div>
                ${llmEvaluation.chain_of_thought ? `
                    <details class="cot-thinking" style="margin-top: 0.75rem; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-radius: 8px; padding: 0.5rem;">
                        <summary style="cursor: pointer; font-weight: 600; color: #a78bfa; display: flex; align-items: center; gap: 0.5rem;">
                            <span style="animation: pulse 2s infinite;">🧠</span> CoT (Düşünce Süreci)
                        </summary>
                        <div style="margin-top: 0.5rem; font-size: 0.8rem; color: #94a3b8; line-height: 1.6; font-family: monospace; white-space: pre-wrap; max-height: 200px; overflow-y: auto; padding: 0.5rem; background: rgba(0,0,0,0.3); border-radius: 4px;">
                            ${llmEvaluation.chain_of_thought}
                        </div>
                    </details>
                ` : ''}
                ${llmEvaluation.reasoning ? `
                    <details style="margin-top: 0.75rem;">
                        <summary style="cursor: pointer; font-weight: 600; color: #94a3b8;">💬 LLM Reasoning</summary>
                        <p style="margin-top: 0.5rem; font-size: 0.82rem; color: #94a3b8; line-height: 1.6;">
                            ${llmEvaluation.reasoning}
                        </p>
                    </details>
                ` : ''}
            </div>
            
            <!-- Detaylı Statik Analiz -->
            <details>
                <summary>Detaylı Statik Metrikler</summary>
                <div class="details-content">
                    <div><strong>Syntax/AST:</strong> ${staticBreakdown.syntax?.score || 0}/5</div>
                    <div><strong>Pylint:</strong> ${staticBreakdown.pylint?.scaled_score || 0}/15 (Raw: ${staticBreakdown.pylint?.raw_score?.toFixed(2) || 0}/10)</div>
                    <div><strong>Karmaşıklık:</strong> ${staticBreakdown.complexity?.score || 0}/15 (Max: ${staticBreakdown.complexity?.max_complexity || 0})</div>
                    <div><strong>Stil (PEP8):</strong> ${staticBreakdown.style?.score || 0}/15 (İhlal: ${staticBreakdown.style?.violations || 0})</div>
                    <div><strong>Yorum Yoğunluğu:</strong> ${staticBreakdown.comments?.score || 0}/5 (%${((staticBreakdown.comments?.density || 0) * 100).toFixed(1)})</div>
                    <div><strong>Kod Tekrarı:</strong> ${staticBreakdown.duplication?.score || 0}/5 (%${((staticBreakdown.duplication?.duplication_ratio || 0) * 100).toFixed(1)})</div>
                    <div><strong>Hata Yönetimi:</strong> ${staticBreakdown.error_handling || 0}/10</div>
                </div>
            </details>
        `;
    });

    Prism.highlightAll();
}

function showWinner(data) {
    document.getElementById("winner-section").style.display = "block";

    const winnerInfo = document.getElementById("winner-info");
    if (!winnerInfo) {
        console.error("Missing element: winner-info");
        return;
    }
    const statusText = data.status === "direct_output"
        ? "Eşik sağlandı - Direkt çıktı"
        : "Feedback döngüsü ile iyileştirildi";

    const hybridScore = data.final_score || 0;
    const initialScore = data.winner_score || 0;

    winnerInfo.innerHTML = `
        <div class="winner-title">Kazanan Model</div>
        <h2 class="winner-model">${data.winner_model}</h2>
        <div class="winner-stats">
            <strong>Başlangıç Skoru:</strong> ${initialScore}/100 &rarr; 
            <strong>Final Skor:</strong> ${hybridScore}/100
            <span style="color: ${hybridScore > initialScore ? '#10b981' : '#ef4444'}; font-weight: bold; margin-left: 10px;">
                (${hybridScore > initialScore ? '+' : ''}${(hybridScore - initialScore).toFixed(1)} puan)
            </span>
        </div>
        <div class="winner-status">
            <strong>Durum:</strong> ${statusText}
        </div>
    `;

    // Feedback iterationslarını göster (detaylı)
    if (data.feedback_iterations && data.feedback_iterations.length > 0) {
        document.getElementById("feedback-section").style.display = "block";
        showDetailedFeedback(data.feedback_iterations);
    } else {
        document.getElementById("feedback-section").style.display = "none";
    }

    // Final kodu göster
    document.getElementById("final-code").textContent = data.final_code;
    Prism.highlightElement(document.getElementById("final-code"));
}

function showDetailedFeedback(iterations) {
    const container = document.getElementById("feedback-iterations");
    if (!container) {
        console.error("Missing element: feedback-iterations");
        return;
    }
    container.innerHTML = "";

    iterations.forEach((iter, index) => {
        const improvement = iter.score_improvement || 0;
        const improvementClass = improvement > 0 ? 'positive' : (improvement < 0 ? 'negative' : 'neutral');

        const iterDiv = document.createElement("div");
        iterDiv.className = "feedback-iteration-detailed";
        iterDiv.innerHTML = `
            <div class="iteration-header">
                <h4>İterasyon ${iter.iteration}</h4>
                <div class="iteration-scores">
                    <span class="score-badge prev">${iter.previous_score}/100</span>
                    <span class="arrow">→</span>
                    <span class="score-badge new ${improvementClass}">${iter.new_score}/100</span>
                    <span class="improvement ${improvementClass}">
                        (${improvement > 0 ? '+' : ''}${improvement.toFixed(1)})
                    </span>
                </div>
            </div>
            
            <!-- Chain-of-Thought Thinking -->
            ${iter.chain_of_thought ? `
            <details class="cot-thinking" style="margin-bottom: 1rem; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-radius: 8px; padding: 0.75rem;">
                <summary style="cursor: pointer; font-weight: 600; color: #a78bfa; display: flex; align-items: center; gap: 0.5rem;">
                    <span style="animation: pulse 2s infinite;">🧠</span> CoT Düşünce Süreci
                </summary>
                <div style="margin-top: 0.5rem; font-size: 0.8rem; color: #94a3b8; line-height: 1.6; font-family: monospace; white-space: pre-wrap; max-height: 150px; overflow-y: auto; padding: 0.5rem; background: rgba(0,0,0,0.3); border-radius: 4px;">
                    ${iter.chain_of_thought}
                </div>
            </details>
            ` : ''}
            
            <!-- İyileştirme Önerileri -->
            <div class="suggestions-box">
                <div class="suggestions-title">🎯 Dinamik Öneriler:</div>
                ${iter.suggestions && iter.suggestions.length > 0 ?
                iter.suggestions.map(s => `
                        <div class="suggestion-item" style="border-left: 3px solid ${s.priority === 1 ? '#ef4444' : s.priority === 2 ? '#f59e0b' : '#22c55e'}; padding-left: 0.5rem; margin-bottom: 0.5rem;">
                            <div class="suggestion-area" style="font-weight: 600; color: ${s.priority === 1 ? '#ef4444' : s.priority === 2 ? '#f59e0b' : '#22c55e'};">[${s.priority === 1 ? 'KRİTİK' : s.priority === 2 ? 'ÖNEMLİ' : 'DÜŞÜK'}] ${s.area}</div>
                            <div class="suggestion-issue" style="font-size: 0.85rem;">Sorun: ${s.issue || ''}</div>
                            <div class="suggestion-action" style="font-size: 0.85rem; font-weight: 500;">Aksiyon: ${s.action || ''}</div>
                        </div>
                    `).join('')
                : '<div style="color: #999;">Genel iyileştirmeler</div>'
            }
            </div>
            
            <!-- Metrik Değişimleri -->
            <div class="metric-changes">
                <div class="metric-changes-title">Metrik Değişimleri:</div>
                <div class="metric-changes-grid">
                    ${Object.entries(iter.metric_changes || {}).map(([metric, change]) => {
                const changeClass = change > 0 ? 'positive' : (change < 0 ? 'negative' : 'neutral');
                return `
                            <div class="metric-change-item">
                                <span class="metric-name">${getMetricLabel(metric)}:</span>
                                <span class="metric-change ${changeClass}">
                                    ${change > 0 ? '+' : ''}${change}
                                </span>
                            </div>
                        `;
            }).join('')}
                </div>
            </div>
            
            <!-- Kod Karşılaştırması -->
            <details class="code-comparison">
                <summary>Kod Değişimini Gör (Öncesi vs Sonrası)</summary>
                <div class="comparison-grid">
                    <div class="comparison-col">
                        <div class="comparison-label">Önceki Kod (${iter.previous_score}/100)</div>
                        <div class="code-container" style="height: auto; max-height: 400px;">
                            <button class="copy-btn" onclick="copyCode('prev-code-${index}')">Copy</button>
                            <pre><code id="prev-code-${index}" class="language-python">${iter.previous_code || 'N/A'}</code></pre>
                        </div>
                    </div>
                    <div class="comparison-col">
                        <div class="comparison-label">İyileştirilmiş Kod (${iter.new_score}/100)</div>
                        <div class="code-container" style="height: auto; max-height: 400px;">
                            <button class="copy-btn" onclick="copyCode('new-code-${index}')">Copy</button>
                            <pre><code id="new-code-${index}" class="language-python">${iter.new_code || 'N/A'}</code></pre>
                        </div>
                    </div>
                </div>
            </details>
        `;
        container.appendChild(iterDiv);
    });

    // Re-highlight kod blokları
    container.querySelectorAll('pre code').forEach(block => {
        Prism.highlightElement(block);
    });
}

// Initial load
document.addEventListener("DOMContentLoaded", () => {
    updateModelHeaders();
});

async function updateModelHeaders() {
    try {
        const response = await fetch("/models");
        const models = await response.json();

        document.getElementById("header-model-1").textContent = models.model_1 || "Model 1";
        document.getElementById("header-model-2").textContent = models.model_2 || "Model 2";
        document.getElementById("header-model-3").textContent = models.model_3 || "Model 3";
    } catch (err) {
        console.error("Modeller yüklenemedi:", err);
    }
}

function getMetricLabel(metric) {
    const labels = {
        '1_Kod_Kalitesi': 'Kod Kalitesi',
        '2_Teknik_Borc': 'Teknik Borç',
        '3_Test_Build': 'Test & Build',
        '4_Stil_Standart': 'Stil & Standart',
        '5_Semantic_Alignment': 'Semantic Alignment',
        '6_Robustness_Safety': 'Robustness & Safety',
        'reliability': 'Güvenilirlik',
        'maintainability': 'Sürdürülebilirlik',
        'duplications': 'Kod Tekrarı',
        'complexity': 'Karmaşıklık'
    };
    return labels[metric] || metric;
}


// End of Script
