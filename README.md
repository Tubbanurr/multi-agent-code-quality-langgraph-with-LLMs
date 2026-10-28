# Çok Ajanlı Kod Üretimi ve Çok Boyutlu Kod Kalite Analiz Sistemi

**Multi-Agent Code Generation & Multi-Dimensional Code Quality Analysis**

LangGraph ile orkestre edilen, yerel LLM'lerle kod üreten, ürettiği kodu hibrit (statik + semantik) bir
değerlendirme hattıyla altı boyutta puanlayan ve sonuçları Chain-of-Thought geri besleme döngüsüne sokarak
kod belirlenen kalite eşiğini geçene kadar kendi kendini iyileştiren çok ajanlı bir sistem — insan müdahalesi
olmadan.

Kocaeli Üniversitesi Bilgisayar Mühendisliği lisans bitirme projesi.
**TÜBİTAK 2209-B** programı desteğiyle (Başvuru No: 1139B412504245), **HAVELSAN SUIT Plus** teknik
mentörlüğünde geliştirildi.

---

## Problem

LLM'ler hızlı kod yazıyor, ancak ürettikleri kod mantıksal hatalar, standart ihlalleri ve bakım sorunları
içerebiliyor. Literatürdeki mevcut yaklaşımlar üretilen kodu çoğunlukla tek eksende değerlendiriyor — çalışıyor
mu? — ve orada duruyor. Değerlendirmenin sonucunu alıp harekete geçen bir döngü yok.

Bu sistem o döngüyü kapatıyor. Üretilen kod altı boyutta ölçülüyor, zayıf çıkan boyutlar hedefli bir
Chain-of-Thought talimatına dönüştürülüyor ve model kodu yeniden üretiyor. Puan eşiği geçene kadar döngü
devam ediyor.

## Nasıl çalışıyor

```
Prompt
  │
  ▼
Kod Üretimi Modülü ──────────────► Aday kod
  (Qwen2.5-Coder / Mistral / CodeLlama)
  │                                     │
  │                                     ▼
  │                      Kod Kalite Değerlendirme Modülü
  │                      ├─ Statik analiz     (70 puan)
  │                      │  AST · karmaşıklık · lint · güvenlik · coverage
  │                      └─ LLM semantik yargı (30 puan)
  │                         semantik hizalama · sağlamlık
  │                                     │
  │                                     ▼
  │                        Birleşik skor ≥ eşik?
  │                                     │
  └──── CoT geri besleme talimatı ◄─ Hayır │ Evet ──► Nihai kod
```

### Hibrit puanlama — 6 kategoride 100 puan

| Kategori | Tür | Ağırlık |
|---|---|---|
| Kod kalitesi (okunabilirlik, yorum yoğunluğu) | Statik | 20 |
| Teknik borç (Pylint skoru, hata sayısı) | Statik | 20 |
| Test & Build (AST geçerliliği, try-except kalitesi) | Statik | 15 |
| Stil & standart (PEP8 uyumu, karmaşıklık eşikleri) | Statik | 15 |
| Semantik hizalama (prompt uyumu, isimlendirme) | LLM yargı | 15 |
| Sağlamlık & güvenilirlik (Bandit, tanımlayıcı netliği) | LLM yargı | 15 |

Statik analiz deterministik ve ucuz; LLM yargısı ise statik araçların göremediğini kapsıyor — kodun prompt'a
gerçekten cevap verip vermediğini, isimlendirme ve yapısının anlamlı olup olmadığını. İkisi tek başına yeterli
olmadığı için puan tamamen bir modele bırakılmak yerine 70/30 bölündü.

## Sonuçlar

Üç zorluk seviyesine yayılmış 109 kontrollü prompt üzerinde, üç yerel model karşılaştırılarak ölçüldü.

| Seviye | Prompt | Başlangıç | Final | Ort. artış | İyileşme oranı |
|---|---|---|---|---|---|
| Kolay | 36 | 91,5 | 92,7 | +1,17 | %83,3 |
| Orta | 36 | 87,6 | 89,9 | +2,36 | %58,3 |
| Zor | 37 | 84,8 | 88,3 | +3,51 | %59,5 |
| **Genel** | **109** | **87,9** | **90,3** | **+2,36** | **%67,0** |

Kazanç zorlukla birlikte artıyor; beklenen tablo bu, çünkü kolay promptlar zaten tavana yakın başlıyor ve
döngünün toparlayacağı fazla bir şey kalmıyor.

Model karşılaştırması da benzer bir sonuç verdi. Kolay görevlerde üç model neredeyse birbirinin yerine
geçebilirken, Qwen2.5-Coder:7b orta seviyede %72,2, zor seviyede %64,9 kazanma oranına ulaştı — asenkron
programlama, eşzamanlılık, metaclass kullanımı, güvenli ifade değerlendirme gibi görevlerde. Basit fonksiyon
yazımında model seçimi az önemli, ötesinde ise kritik.

Örnek bir koşu: bir `remove_duplicates` implementasyonu ilk geçişte 74/100 aldı (tip anotasyonu yok, docstring
yok, edge-case kontrolü eksik). İki iterasyon sonra 89/100'e çıktı; generic typing, belgelenmiş bir sözleşme ve
O(n²) üyelik kontrolünün O(n) olarak yeniden yazılmasıyla.

## Mimari

```
agentic_nodes_loop/
├── main.py                     FastAPI uygulaması, endpoint'ler, web arayüzü
├── module/
│   ├── agentic_workflow.py     LangGraph state graph — düğümler, kenarlar, döngü kontrolü
│   ├── llm_clients.py          Groq / DeepSeek / Gemini istemcileri (anahtarlar env'den)
│   ├── ollama_client.py        Yerel model çalıştırıcı (Qwen, Mistral, CodeLlama)
│   ├── feedback_agent.py       Skorları CoT revizyon talimatına dönüştürür
│   ├── llm_judge.py            Semantik değerlendirme (30 puan)
│   ├── advanced_judge.py       /analyze-advanced endpoint'i için genişletilmiş yargı
│   └── analyzers/
│       ├── base.py             Ortak analyzer arayüzü
│       ├── ast_analyzer.py     Sözdizimi geçerliliği, yapısal kontroller
│       ├── complexity_analyzer.py   Cyclomatic complexity (Radon)
│       ├── lint_analyzer.py    Pylint + Flake8
│       ├── security_analyzer.py     Bandit
│       ├── coverage_analyzer.py     pytest-cov
│       └── content_analyzer.py Docstring, yorum, isimlendirme yoğunluğu
├── static/ · templates/        Dashboard arayüzü
└── requirements.txt
```

Her analyzer `base.py`'deki aynı arayüzü uyguluyor ve bağımsız test edilebiliyor — yedinci bir metrik eklemek,
puanlama çekirdeğini değiştirmeyi değil tek bir dosya eklemeyi gerektiriyor. Ajanlar da aynı mantıkla ayrıldı:
üretim, yargılama ve geri besleme, LangGraph state graph'ında tek sorumluluklu ayrı düğümler.

## Çalıştırma

Python 3.10+ ve yerel modeller için [Ollama](https://ollama.com) gerekiyor.

```bash
git clone https://github.com/ctnasu/langgraph-multi-agent-code-quality.git
cd langgraph-multi-agent-code-quality/agentic_nodes_loop

python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

ollama pull qwen2.5-coder:7b
ollama pull mistral
ollama pull codellama
```

Servis üzerinden çalışan modelleri de kullanmak isterseniz `agentic_nodes_loop/` altında bir `.env` dosyası
oluşturun. Üçü de opsiyonel — sistem yalnızca Ollama ile çalışır.

```
GROQ_API_KEY=...
DEEPSEEK_API_KEY=...
GEMINI_API_KEY=...
```

Ardından sunucuyu başlatın:

```bash
uvicorn main:app --reload
```

Arayüz: `http://127.0.0.1:8000`

## Teknolojiler

`Python` · `FastAPI` · `LangGraph` · `LangChain` · `Ollama` · `Pylint` · `Radon` · `Bandit` · `Flake8` ·
`pytest-cov` · `mypy`

## Ekip

Üç kişilik bir lisans bitirme projesi olarak geliştirildi:
[Zeynep Palabıyık](mailto:zeynppalabiyik@gmail.com),
[Asude Çetin](https://github.com/ctnasu) ve
[Tuba Nur Aksın](https://github.com/Tubbanurr).

Benim çalışmam ağırlıklı olarak LangGraph orkestrasyon katmanı, Chain-of-Thought geri besleme ajanı ve
yukarıdaki sonuçları üreten değerlendirme altyapısı üzerineydi.

Akademik danışmanlık: Prof. Dr. Sevinç İlhan Omurca (Kocaeli Üniversitesi).
Sanayi mentörlüğü: Büşra Nur Ergen (HAVELSAN SUIT Plus).
