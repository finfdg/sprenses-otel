# Döviz Kurları Modülü

## Genel Bilgi

| Özellik | Değer |
|---|---|
| **Modül Kodu** | `finance.doviz` |
| **Üst Modül** | `finance` (Finans) |
| **Frontend Rota** | `/dashboard/finans/doviz` |
| **Backend Prefix** | `/api/finance/exchange-rates/` |
| **İzin** | `finance.doviz` → `can_view` (salt okunur modül) |

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `backend/app/models/exchange_rate.py` | `ExchangeRate` SQLAlchemy modeli |
| `backend/app/schemas/exchange_rate.py` | Pydantic şemaları |
| `backend/app/routers/finance/exchange_rates.py` | API endpoint'leri |
| `backend/app/utils/tcmb.py` | TCMB XML çekme ve ayrıştırma |
| `backend/cron_fetch_exchange_rates.py` | Cron scripti (toplu + günlük) |

### Frontend
| Dosya | Açıklama |
|---|---|
| `frontend/src/routes/dashboard/finans/doviz/+page.svelte` | Döviz kurları sayfası |
| `frontend/src/lib/types/exchange-rate.ts` | TypeScript tipleri |

### Sistem
| Dosya | Açıklama |
|---|---|
| `/etc/systemd/system/sprenses-exchange-rates.service` | Systemd one-shot servisi |
| `/etc/systemd/system/sprenses-exchange-rates.timer` | Saatlik zamanlayıcı |

### Veritabanı Migration
| Dosya | Açıklama |
|---|---|
| `backend/alembic/versions/b94c752c1560_add_doviz_module.py` | Tablo + modül kaydı |

## Veritabanı Şeması

### `exchange_rates` Tablosu

| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | `INTEGER` PK | Otomatik artan ID |
| `date` | `DATE NOT NULL` | Kur tarihi |
| `currency_code` | `VARCHAR(3) NOT NULL` | Döviz kodu: USD, EUR, GBP |
| `currency_name` | `VARCHAR(50)` NULL | Türkçe ad (ör: ABD DOLARI) |
| `unit` | `INTEGER DEFAULT 1` | Birim |
| `forex_buying` | `NUMERIC(12,4)` NULL | Döviz alış |
| `forex_selling` | `NUMERIC(12,4)` NULL | Döviz satış |
| `banknote_buying` | `NUMERIC(12,4)` NULL | Efektif alış |
| `banknote_selling` | `NUMERIC(12,4)` NULL | Efektif satış |
| `source` | `VARCHAR(20) DEFAULT 'tcmb'` | `"tcmb"` veya `"carried"` |
| `created_at` | `TIMESTAMPTZ` | Kayıt zamanı |

**İndeksler:**
- `ix_exchange_rates_date` — Tarih indeksi
- `ix_exchange_rates_currency_code` — Döviz kodu indeksi
- `uq_exchange_rate_date_currency` — UNIQUE: (date, currency_code)

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| `GET` | `/api/finance/exchange-rates/latest` | `view` | En son kurlar + EUR/USD parite |
| `GET` | `/api/finance/exchange-rates/history` | `view` | Tarihçe (paginated) |
| `GET` | `/api/finance/exchange-rates/chart` | `view` | Grafik verisi (tarih + alış/satış) |
| `GET` | `/api/finance/exchange-rates/parity/history` | `view` | EUR/USD parite tarihçesi |

### Sorgu Parametreleri

**`/history`:**
- `currency_code` (zorunlu): `USD`, `EUR`, `GBP`
- `start_date`, `end_date` (opsiyonel): Tarih aralığı
- `page`, `page_size`: Sayfalama

**`/chart`:**
- `currency_code` (zorunlu): `USD`, `EUR`, `GBP`
- `days` (varsayılan: 90, min: 7, max: 1095): Son N gün

**`/parity/history`:**
- `days` (varsayılan: 90, min: 7, max: 1095): Son N gün

## EUR/USD Parite Hesabı

```
parite = EUR_forex_selling / USD_forex_selling
```

## Veri Kaynağı

- **TCMB Tarihsel:** `https://www.tcmb.gov.tr/kurlar/YYYYMM/DDMMYYYY.xml`
- **Dövizler:** USD, EUR, GBP
- **Başlangıç tarihi:** 2023-01-01
- **Hafta sonu/tatil:** Önceki iş gününün kuru taşınır (`source="carried"`)
- **Güncelleme:** Saatlik systemd timer (her saat :30'da)

## Frontend UI Yapısı

### Güncel Kur Kartları (üst)
- 4'lü grid: USD/TRY, EUR/TRY, GBP/TRY, EUR/USD Parite
- Her kart: döviz alış, döviz satış, efektif alış, efektif satış

### SVG Grafik (orta)
- Döviz sekmeleri: USD | EUR | GBP | EUR/USD Parite
- Süre seçici: 30G | 90G | 6A | 1Y | Tümü
- SVG polyline chart (harici kütüphane yok)
- Hover tooltip

### Tarihçe Tablosu (alt)
- Döviz filtresi (tabs)
- Desktop tablo + mobil kartlar
- Sayfalama
- Kaynak badge: yeşil=TCMB, gri=Taşıma

## Cron Script Kullanımı

```bash
# İlk kurulum (toplu çekme)
cd /home/ec2-user/otel/backend
source venv/bin/activate
python cron_fetch_exchange_rates.py --bulk

# Günlük güncelleme (systemd timer otomatik çalıştırır)
python cron_fetch_exchange_rates.py
```

## Geliştirme Kuralları

1. Kullanıcı tarafından veri girişi **yoktur** — tüm veri TCMB'den çekilir
2. `can_use` izni bu modülde **gerekmez** (salt okunur modül)
   - **Onay akışı istisnası:** Modülde hiç POST/PATCH/DELETE mutasyon endpoint'i olmadığından `check_approval` uygulanamaz (onay akışı kavramı salt-okunur modülde geçersiz) — bilinçli muafiyet
3. Bulk fetch sadece bir kez çalıştırılır (`--bulk` parametresi)
4. Kur bulunamazsa önceki iş gününün kuru taşınır (asla boş gün kalmaz)
5. TCMB istekleri arasında 0.5s bekleme (rate limiting)
6. Unique constraint sayesinde tekrar çalıştırma güvenlidir
