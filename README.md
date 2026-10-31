# 🚢 Aliağa Lojistik & Tedarik Zinciri Tahmin Paneli

Aliağa (İzmir) sanayi ve liman bölgesindeki **liman trafiğini** ve **petrokimya / enerji lojistiğini** sentetik verilerle simüle eden, geleceğe yönelik **tahmin** üreten ve sonuçları **Streamlit** üzerinde interaktif harita ve grafiklerle sunan bir analiz panelidir.

> ⚠️ **Not:** Panelde kullanılan tüm veriler rastgele üretilmiş **sentetik** verilerdir. Terminal koordinatları yaklaşık/temsilidir. Gerçek operasyonel kararlar için kullanılmamalıdır.

---

## İçindekiler
- [Özellikler](#özellikler)
- [Kurulum ve çalıştırma](#kurulum-ve-çalıştırma)
- [Panel sekmeleri](#panel-sekmeleri)
- [Veri modeli](#veri-modeli)
- [Tahmin yöntemi](#tahmin-yöntemi)
- [Senaryo analizi](#senaryo-analizi)
- [Stok simülasyonu](#stok-simülasyonu)
- [Gerçek veriye geçiş](#gerçek-veriye-geçiş)
- [Proje yapısı](#proje-yapısı)
- [Sınırlamalar ve geliştirme fikirleri](#sınırlamalar-ve-geliştirme-fikirleri)

---

## Özellikler

- 5 terminal (Tüpraş İskeleleri, Petkim Limanı, Ege Gaz LNG, Nemrut / Habaş, İzdemir Limanı) ve 6 ürün grubu için **2 yıllık günlük sentetik veri**
- Mevsimsellik, hafta sonu etkisi, büyüme trendi, gürültü ve **fırtına kaynaklı liman kapanışları**
- Trend + haftalık/yıllık mevsimsellik içeren, **güven aralıklı** ve **geriye dönük testli (backtest)** tahmin modeli
- **Senaryo analizi:** talep şoku ve liman kapanışı simülasyonu
- **Rıhtım doluluğu** tahmini ve tıkanıklık uyarısı
- **Ham petrol tank stoğu** simülasyonu ve emniyet stoğu uyarıları
- PyDeck ile terminal haritası ve küresel ithalat/ihracat **akış (arc) haritası**
- Plotly ile etkileşimli grafikler, CSV olarak veri indirme

## Kurulum ve çalıştırma

Python 3.9+ önerilir.

```bash
# (isteğe bağlı) sanal ortam
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# bağımlılıklar
pip install -r requirements.txt

# paneli başlat
streamlit run aliaga_lojistik_paneli.py
```

Tarayıcıda genellikle `http://localhost:8501` adresinde açılır.

## Panel sekmeleri

Kenar çubuğundaki filtreler (terminal, ürün, geçmiş pencere) ve senaryo kaydırıcıları tüm sekmeleri etkiler. Tedarik Zinciri sekmesi terminal/ürün filtrelerinden bağımsızdır, ancak senaryo kaydırıcılarını kullanır.

| Sekme | İçerik |
|---|---|
| 📊 **Genel Bakış** | KPI kartları (yük, gemi çağrısı, bekleme süresi, doluluk, 30 günlük tahmin), haftalık ürün bazlı alan grafiği, terminal bazlı yük, gün × ay gemi ısı haritası, doluluk–bekleme dağılımı |
| 🗺️ **Harita** | Aliağa terminalleri (yüke göre boyutlanan daireler) ve küresel akışlar (mavi: giriş/ithalat, turuncu: çıkış/ihracat) |
| 🔮 **Tahmin** | Seçilen seri için tahmin + %95 aralık, baz ve senaryo karşılaştırması, MAPE, rıhtım doluluk tahmini, haftalık tahmin tablosu |
| 🛢️ **Tedarik Zinciri** | Tüpraş ham petrol tank stoğu simülasyonu, emniyet stoğu uyarıları |
| 🧾 **Veri** | Filtrelenmiş veri tablosu ve CSV indirme |

### Kenar çubuğu parametreleri

| Parametre | Açıklama |
|---|---|
| Terminaller / Ürünler | Analiz kapsamı |
| Geçmiş pencere | 30 / 90 / 180 / 365 gün (KPI ve grafikler için) |
| Tahmin ufku | 14–120 gün |
| Talep şoku | −%30 ile +%30 arası talep değişimi |
| Liman kapanışı | 0–7 gün ve başlangıç tarihi |

## Veri modeli

`generate_data()` iki tablo üretir.

**Kargo tablosu** (terminal × ürün × gün)

| Sütun | Açıklama |
|---|---|
| `date` | Tarih |
| `terminal` | Terminal adı |
| `product` | Ürün grubu |
| `direction` | `Giriş` (ithalat) veya `Çıkış` (ihracat) |
| `tonnes` | Günlük yük (ton) |

**Terminal trafiği tablosu** (terminal × gün)

| Sütun | Açıklama |
|---|---|
| `vessels` | Günlük gemi çağrısı |
| `berths` | Rıhtım sayısı |
| `berth_util` | Rıhtım doluluğu = gemi × 1,3 gün / rıhtım sayısı |
| `wait_h` | Ortalama bekleme süresi (saat) |
| `weather_closure` | O gün fırtına kapanışı var mı |

Üretim mantığı: `ton = taban × mevsimsellik × hafta içi/sonu × trend × log-normal gürültü × liman faktörü`. Kış aylarında (Kasım–Mart) fırtına olasılığı daha yüksektir; fırtına gününde hacim düşer, ertesi gün telafi yoğunluğu oluşur. Gemi sayısı ton / ortalama parti büyüklüğünden Poisson dağılımıyla, bekleme süresi ise doluluk ve hava durumundan türetilir.

## Tahmin yöntemi

Ek bağımlılık gerektirmeyen, yalnızca `numpy` ile yazılmış bir regresyon modelidir:

- **Özellikler:** sabit terim + doğrusal trend + haftalık (periyot 7, 3. derece) ve yıllık (periyot 365,25, 3. derece) Fourier terimleri
- **Eğitim:** en küçük kareler; fırtına gibi aşırı düşük günler (kalıntı < −2,5σ) dışlanarak bir kez yeniden fit edilir
- **Aralık:** ±1,96σ, ufuk uzadıkça genişleyen %95 güven bandı
- **Doğrulama:** son 28 gün hariç tutularak eğitilir ve bu dönemde **MAPE** hesaplanır

## Senaryo analizi

- **Talep şoku:** tahmin edilen tüm değerler `(1 + şok%)` ile çarpılır.
- **Liman kapanışı:** kapanış günlerinde hacim sıfırlanır; kaybedilen hacim kapanıştan sonraki 7 güne eşit dağıtılarak telafi edilir.

## Stok simülasyonu

Tüpraş ham petrol girişlerinin tahmini ile sabit işleme hızı arasındaki farktan günlük tank stoğu hesaplanır:

```
stok[t] = min(kapasite, max(0, stok[t-1] + giriş[t] - işleme))
```

Alt / beklenen / üst tahmin sınırları için üç yol simüle edilir. Beklenen stok emniyet seviyesinin altına düşerse hata, yalnızca kötü senaryoda düşerse uyarı gösterilir.

## Gerçek veriye geçiş

Tek değişiklik noktası `generate_data()` fonksiyonudur. Kendi veri kaynağınızdan (AIS, liman istatistikleri, ERP vb.) yukarıdaki iki tabloyu aynı sütun adlarıyla döndürürseniz panelin geri kalanı değişmeden çalışır. Terminal koordinatları, rıhtım sayıları ve rotalar `TERMINALS`, `PRODUCTS` ve `ROUTES` sabitlerinden düzenlenir.

## Proje yapısı

```
.
├── aliaga_lojistik_paneli.py   # Tüm uygulama (veri, model, arayüz)
├── requirements.txt
└── README.md
```

Kod bölümleri: sabitler → sentetik veri üretimi → tahmin modeli → senaryo/stok fonksiyonları → Streamlit arayüzü.

## Sınırlamalar ve geliştirme fikirleri

- Model basit bir regresyondur; ani şokları, bayram/tatil etkilerini ve dış değişkenleri (petrol fiyatı, kur, hava tahmini) içermez.
- Akış haritasındaki rota payları sabit varsayımdır.
- Fikirler: gerçek AIS verisi entegrasyonu, Prophet/SARIMA gibi alternatif modeller ve model karşılaştırması, hava durumu API'si ile kapanış tahmini, demuraj maliyeti hesabı, çoklu ürün için tank stoğu simülasyonu.

## Lisans

Lisansınızı buraya ekleyin (ör. MIT).
