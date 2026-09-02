"""Finansal değişmezler — kod değişikliğinin sessiz tutar kaymasına yol açıp açmadığını ölçer.

Bu modül `denetim_finans_parmak_izi.py` tarafından okunur. Her değişmez, kod dışında
hiçbir şey değişmediğinde AYNI değeri üretmelidir; eski kod ile yeni kod arasında bir
sayı oynuyorsa deploy engellenir.

KURALLAR (yeni değişmez eklerken):
  · SALT-OKUNUR olmalı. Ölçüm `SET TRANSACTION READ ONLY` içinde koşar; yazan yol hata
    verir (bu kasıtlı — hata da bir değerdir ve iki ölçümde aynıysa kapıyı bozmaz).
  · DETERMİNİSTİK olmalı. `date.today()` gibi zamana bağlı yollar iki ölçüm arasında
    gün dönerse kayar; A/A2 kontrol ölçümü bunu yakalar ve kapıyı atlar.
  · HIZLI olmalı. Koşu başına ÜÇ kez çalışır.
  · Gerçek servis/endpoint fonksiyonunu çağır — ham SQL toplamı kod yolundaki hatayı görmez.

Bu dosya `cron_denetim_auto.DEPLOY_BLOCKERS` listesindedir: otomasyon kendi kapısını
değiştirip geçemez.

ÜRETİM NOTU: ilk sürüm 5 ajanlı bir kod taramasıyla çıkarıldı (2026-07-25) ve her
değişmez canlı üretim veritabanında ölçülerek doğrulandı.
"""
# ruff: noqa: E501


def _inv_avans_bakiye_birlesik(db, ref_date=None):
    """Acente avans bakiyeleri: `_merged_advances(db)` GERÇEK servis fonksiyonu çağrılır (`GET /sales-invoices/advances` + `/summary`'nin avans bloğu bunu kullanır). 340 'Alınan Avanslar' defteri + 120 net-alacak havuzunun birleşimi, `_norm_tokens` token kesişimiyle mükerrer eleme ve para birimi bazında toplam ölçülür. Dedup mantığı ya da FIFO havuzu değişirse toplam oynar. Ölçüm öncesi cache invalidate edilir. Canlı: 35 acente, EUR 6,08 M + TL 9,91 M, 0,17 sn.

    Önem: kritik · Kaynak: app/services/sales_invoice_service.py:144
    """
    from app.services.sales_invoice_service import _invalidate_compute_cache, _merged_advances
    _invalidate_compute_cache()
    merged, total_by_cur = _merged_advances(db)
    kaynak = {"340": 0, "120": 0}
    kalan_kaynak = {"340": 0.0, "120": 0.0}
    for x in merged:
        kaynak[x["source"]] += 1
        kalan_kaynak[x["source"]] = round(kalan_kaynak[x["source"]] + x["remaining"], 2)
    result = {
        "acente_adet": len(merged),
        "toplam_by_currency": {k: round(v, 2) for k, v in total_by_cur.items()},
        "kaynak_adet": kaynak,
        "kaynak_kalan": kalan_kaynak,
    }
    return result


def _inv_cari_net_borc_toplami(db, ref_date=None):
    """FIFO'nun girdisi olan net borç haritası (_get_vendor_net_debts): borç−alacak < 0 olan carilerin toplam net borcu + cari sayısı. Ödeme yasaklısı cariler BİLEREK hariçtir — bu filtre kaybolursa/genişlerse toplam sessizce şişer. Canlı referans: 42.037.794,96 TL / 171 cari (FIFO toplamıyla birebir aynı olmalı; sapma FIFO kırpmasının bozulduğunu gösterir).

    Önem: kritik · Kaynak: app/services/vendor_fifo.py:239
    """
    from app.services.vendor_fifo import _get_vendor_net_debts
    debts = _get_vendor_net_debts(db)
    result = {"toplam": round(sum(debts.values()), 2), "cari_sayisi": len(debts)}
    return result


def _inv_cari_ozet_kpi(db, ref_date=None):
    """Cariler sayfasının özet kartlarını besleyen GERÇEK endpoint fonksiyonu doğrudan çağrılır (get_vendors_summary(db=db, _=None) — Depends parametreleri elle geçilir). Toplam borç/alacak/bakiye, negatif bakiyeli cari sayısı ve toplamı, yasaklı sayısı, sıfır-olmayan cari sayısı, vadesi geçmiş toplam/fatura/cari sayısı tek ölçümde sabitlenir. negative_total_eur ÇIKARILIR (TCMB kur cronu iki ölçüm arasında koşarsa yanlış alarm üretir). Canlı referans: bakiye −22.791.402,67 · overdue_total 8.160.577,63.

    Önem: kritik · Kaynak: app/routers/finance/cariler/vendors.py:42
    """
    from app.routers.finance.cariler.vendors import get_vendors_summary
    res = get_vendors_summary(db=db, _=None)
    res.pop("negative_total_eur", None)
    result = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in res.items()}
    return result


def _inv_cek_durum_para_birimi_toplami(db, ref_date=None):
    """Çeklerin durum × para birimi kırılımında adet, TL tutarı ve orijinal döviz tutarı toplamı (pending/paid/cancelled × TL/EUR). `checks_summary` yalnızca toplam/bekleyen/vadesi-geçen verir; iptal ve ödenmiş kırılımı ile TL-döviz ikilisi burada çıpalanır. `apply_check_status()` iptal kademesi (eşleşme kaldırma + FE invalidate) bu dağılımı bozarsa hemen görünür.

    Önem: kritik · Kaynak: backend/app/services/check_service.py:17
    """
    from sqlalchemy import func

    from app.models.check import Check
    rows = (db.query(Check.status, Check.currency,
                     func.count(Check.id),
                     func.coalesce(func.sum(Check.amount_tl), 0),
                     func.coalesce(func.sum(Check.amount_currency), 0))
            .group_by(Check.status, Check.currency)
            .order_by(Check.status, Check.currency)
            .all())
    result = {"%s|%s" % (s, c): {"adet": int(n), "tl": round(float(tl), 2), "doviz": round(float(dv), 2)}
              for s, c, n, tl, dv in rows}
    return result


def _inv_cek_ozeti_endpoint(db, ref_date=None):
    """Çek özeti: toplam/bekleyen/vadesi geçen adet ve tutar + bekleyenin EUR karşılığı. GERÇEK KOD YOLU: `checks_summary()` endpoint fonksiyonu doğrudan çağrılır. EUR karşılığı, TL çekleri `max(ExchangeRate.date)` tarihli `forex_buying` kuruna bölüp EUR çekleri doğrudan ekleyen özel mantıktan geçer (FIN-001 sınıfı kur çevrim hatalarının görüneceği yer). DİKKAT: 'vadesi geçen' hesabı `date.today()` kullanır.

    Önem: kritik · Kaynak: backend/app/routers/finance/checks.py:313
    """
    from app.routers.finance.checks import checks_summary
    r = checks_summary(db=db, _=None)
    eur = r["pending_amount_eur"]
    result = {"toplam_adet": int(r["total_count"]),
              "toplam_tutar": round(float(r["total_amount"]), 2),
              "bekleyen_adet": int(r["pending_count"]),
              "bekleyen_tutar": round(float(r["pending_amount"]), 2),
              "bekleyen_tutar_eur": (round(float(eur), 2) if eur is not None else None),
              "vadesi_gecen_adet": int(r["overdue_count"]),
              "vadesi_gecen_tutar": round(float(r["overdue_amount"]), 2)}
    return result


def _inv_fe_acik_defter_toplami(db, ref_date=None):
    """finance_events'in ham defteri: eşleşmemiş (is_matched=False) kayıtların para birimi × yön kırılımında adedi ve `amount` toplamı. Rapor katmanının ALTINDAKİ veri; tarihe hiç bağlı olmadığından gün dönse bile yanlış alarm üretmez → en güvenilir kapı. Rapor sayıları değişip bu değişmiyorsa hata okuma/çevrim yolunda, ikisi birden değişiyorsa yazıcı (upsert) tarafındadır. Canlı taban: TRY:-1 3.230 kayıt / 875.056.238,76 · EUR:-1 451 / 23.061.169,46.

    Önem: kritik · Kaynak: backend/app/models/finance_event.py:60
    """
    from sqlalchemy import func

    from app.models.finance_event import FinanceEvent
    _rows = (db.query(FinanceEvent.currency, FinanceEvent.direction,
                      func.count(FinanceEvent.id),
                      func.coalesce(func.sum(FinanceEvent.amount), 0))
             .filter(FinanceEvent.is_matched == False)
             .group_by(FinanceEvent.currency, FinanceEvent.direction).all())
    result = dict(sorted({"%s:%s" % ((c or "?"), d): [int(n), round(float(s), 2)]
                          for c, d, n, s in _rows}.items()))
    return result


def _inv_fe_amount_try_tutarliligi(db, ref_date=None):
    """FIN-001 'hayalet para' imzasının doğrudan ölçümü: (a) TRY kayıtlarda amount_try ile amount'un 0,01'den fazla saptığı satır sayısı — bayat amount_try tam olarak 696 bin TL'lik hayalet parayı üretmişti; (b) döviz kayıtlarda amount_try NULL sayısı (USD/GBP çevrim körlüğü); (c) tüm tabloda ve yalnız açık kayıtlarda amount_try toplamı. Bu sayıların SIFIR olması gerekmiyor — canlı taban 2 sapan TRY + 634 NULL döviz; DEĞİŞMEMELERİ gerekiyor.

    Önem: kritik · Kaynak: backend/app/services/finance_event_service.py:154
    """
    from sqlalchemy import func

    from app.models.finance_event import FinanceEvent
    _drift = db.query(func.count(FinanceEvent.id)).filter(
        FinanceEvent.currency.in_(("TRY", "TL")),
        FinanceEvent.amount_try.isnot(None),
        func.abs(FinanceEvent.amount_try - FinanceEvent.amount) > 0.01).scalar() or 0
    _fxnull = db.query(func.count(FinanceEvent.id)).filter(
        ~FinanceEvent.currency.in_(("TRY", "TL")),
        FinanceEvent.amount_try.is_(None)).scalar() or 0
    _tot = db.query(func.coalesce(func.sum(FinanceEvent.amount_try), 0)).scalar() or 0
    _tot_open = db.query(func.coalesce(func.sum(FinanceEvent.amount_try), 0)).filter(
        FinanceEvent.is_matched == False).scalar() or 0
    result = {"try_amount_try_sapan": int(_drift),
              "doviz_amount_try_null": int(_fxnull),
              "amount_try_toplam": round(float(_tot), 2),
              "amount_try_toplam_acik": round(float(_tot_open), 2)}
    return result


def _inv_fifo_cari_bazli_parmak_izi(db, ref_date=None):
    """FIFO kalanlarının CARİ BAZINDA dağılımının sha256 özeti (ilk 16 hane) + cari sayısı. Toplam değişmeden firmalar arasında tutar kayması (ör. sıralama/kırpma mantığı bozulup borcun yanlış cariye yazılması) yalnız bu değişmezde yakalanır — genel toplam bunu gizler. Deterministik ve hızlı (0,04 sn). Canlı referans: 7106448022d050cb / 171 cari.

    Önem: kritik · Kaynak: app/services/vendor_fifo.py:66
    """
    import hashlib
    from collections import defaultdict

    from app.models.vendor_transaction import VendorTransaction
    from app.services.vendor_fifo import calculate_fifo_amounts
    fifo = calculate_fifo_amounts(db)
    per = defaultdict(float)
    if fifo:
        rows = (db.query(VendorTransaction.id, VendorTransaction.vendor_id)
                .filter(VendorTransaction.id.in_(list(fifo.keys()))).all())
        for r in rows:
            per[r.vendor_id] += fifo.get(r.id, 0.0)
    payload = ";".join("%d:%.2f" % (vid, per[vid]) for vid in sorted(per))
    result = {"hash": hashlib.sha256(payload.encode()).hexdigest()[:16], "cari_sayisi": len(per)}
    return result


def _inv_fifo_kalan_toplam(db, ref_date=None):
    """FIFO motorunun (calculate_fifo_amounts) ürettiği ödenmemiş fatura kalanlarının toplamı ve kalem sayısı. Cari modülünün ÇEKİRDEK sayısı: ödeme planı, vadesi geçmiş kartı, nakit akım vendor_payment olayları, aylık bakiye sekmesi — hepsi bu tek fonksiyondan türer. Kod yolu birebir çağrılır (app/services/vendor_fifo.py:66). Canlı referans: toplam 42.037.794,96 TL / 870 kalem.

    Önem: kritik · Kaynak: app/services/vendor_fifo.py:66
    """
    from app.services.vendor_fifo import calculate_fifo_amounts
    fifo = calculate_fifo_amounts(db)
    result = {"toplam": round(sum(fifo.values()), 2), "kalem_sayisi": len(fifo)}
    return result


def _inv_fx_event_eur_cevrim(db, ref_date=None):
    """Finans kalemi → EUR çevrim çekirdeği `t_account._event_eur` 2026'daki TÜM döviz (TRY/TL dışı) finance_events satırı için tek tek çağrılır; para birimi bazında EUR toplamı + çevrilemeyen (kursuz) kalem sayısı ölçülür. USD çapraz kur formülünü (amount × USD alış / EUR alış) ve 'amount_try'a bakılmaz' kuralını (FIN-001 düzeltmesi) kilitler. Endpoint Depends + rate-limit istediğinden iç saf hesaplayıcı çağrılır.

    Önem: kritik · Kaynak: backend/app/routers/finance/cash_flow/t_account.py:166
    """
    from datetime import date

    from app.models.finance_event import FinanceEvent
    from app.routers.finance.cash_flow.t_account import _event_eur
    _cache = {}
    _events = (
        db.query(FinanceEvent)
        .filter(FinanceEvent.event_date >= date(2026, 1, 1),
                FinanceEvent.event_date <= date(2026, 12, 31),
                FinanceEvent.currency.isnot(None),
                FinanceEvent.currency.notin_(["TRY", "TL"]))
        .order_by(FinanceEvent.id)
        .all()
    )
    _by = {}
    _skipped = 0
    for _fe in _events:
        _v = _event_eur(db, _fe, _cache)
        if _v is None:
            _skipped += 1
            continue
        _k = (_fe.currency or "?").upper()
        _by[_k] = round(_by.get(_k, 0.0) + _v, 2)
    result = {"cevrilen_eur_toplam": round(sum(_by.values()), 2), "para_birimi_bazinda": _by,
              "kalem_sayisi": len(_events), "kursuz_atlanan": _skipped}
    return result


def _inv_fx_ledger_rate_sabit(db, ref_date=None):
    """Sedna-eşdeğer defter kuru (`fx_service.ledger_rate`) sabit 4 tarih × 4 para birimi için. Gerçek servis fonksiyonu çağrılır. T-1 semantiğini (value_date − 1 gün, yoksa en yakın ÖNCEKİ gün), unit bölmesini ve TRY/TL → 1.0 kısayolunu birlikte kilitler. Tarihler sabit olduğu için gün dönmesinden etkilenmez.

    Önem: kritik · Kaynak: backend/app/services/fx_service.py:34
    """
    from datetime import date

    from app.services import fx_service
    _probe_dates = [date(2026, 1, 15), date(2026, 3, 31), date(2026, 5, 4), date(2026, 7, 1)]
    result = {}
    for _d in _probe_dates:
        for _c in ("EUR", "USD", "GBP", "TRY"):
            _r = fx_service.ledger_rate(db, _d, _c)
            result[f"{_c}@{_d.isoformat()}"] = round(_r, 6) if _r is not None else None
    return result


def _inv_hakedis_ozet(db, ref_date=None):
    """Hak ediş / açık alacak yaşlandırması: `compute_receivables(db, today)` GERÇEK servis fonksiyonu çağrılır (finance.hakedis endpoint'inin çekirdeği; FIFO + receivable_terms vadeleri + 120/340 avans netlemesi + kur çevrimi burada birleşir). `today` BİLEREK sabit tarihe (2026-07-25) pinlendi — `date.today()` kullanılsaydı gece yarısı geçen iki ölçüm arasında kovalar kayıp sahte alarm üretirdi. Canlı: acik_tl 74,55 M, vadesi_gecen_tl 17,46 M, 0,46 sn.

    Önem: kritik · Kaynak: app/services/receivable_service.py:194
    """
    from datetime import date

    from app.services.receivable_service import compute_receivables
    from app.services.sales_invoice_service import _invalidate_compute_cache
    _invalidate_compute_cache()
    rec = compute_receivables(db, date(2026, 7, 25))
    s = rec["summary"]
    result = {
        "acik_tl": s["open_tl"],
        "acik_by_currency": s["open_by_currency"],
        "avans_tl": s["advance_tl"],
        "net_acik_tl": s["net_open_tl"],
        "vadesi_gecen_tl": s["overdue_tl"],
        "yedi_gun_tl": s["due_7d_tl"],
        "tahsil_tl": s["collected_tl"],
        "eslenmemis_tahsilat_tl": s["unapplied_tl"],
        "firma_adet": s["firm_count"],
        "gecikmis_firma_adet": s["overdue_firm_count"],
        "kovalar": {k: round(v, 2) for k, v in s["buckets"].items()},
    }
    return result


def _inv_kredi_aktif_kalan_anapara_tip(db, ref_date=None):
    """Aktif kredilerin tip bazlı adet/toplam/kalan anapara özeti + EUR karşılığı. GERÇEK KOD YOLU: `credit_summary()` endpoint fonksiyonu doğrudan çağrılır (`db=db, _=None` — `_` yalnızca izin Depends'i, gövdede kullanılmıyor, bu yüzden None geçilebiliyor). Kredi kalan anaparasının kullanıcıya gösterilen tek kaynağı budur; EUR alanı `max(ExchangeRate.date)` + `forex_buying` üzerinden hesaplanır.

    Önem: kritik · Kaynak: backend/app/routers/finance/krediler/summary.py:23
    """
    from app.routers.finance.krediler.summary import credit_summary
    rows = credit_summary(db=db, _=None)
    result = {}
    for r in rows:
        eur = r.get("remaining_amount_eur")
        result[str(r["type"])] = {
            "adet": int(r["count"]),
            "toplam": round(float(r["total_amount"]), 2),
            "kalan": round(float(r["remaining_amount"]), 2),
            "kalan_eur": (round(float(eur), 2) if eur is not None else None),
        }
    return result


def _inv_kredi_cek_finance_event_izdusumu(db, ref_date=None):
    """Kredi ve çeklerin nakit akımına YANSIYAN hali: `finance_events` tablosunda source_type in ('credit','check') kayıtlarının kaynak × para birimi × is_matched kırılımında adet ve tutar toplamı. `upsert_credit_payment` / `upsert_check` bu satırları üretir; is_matched kırılımı ÇİFT SAYIM sınırıdır (eşleşmiş kayıt frontend'de toplam dışı bırakılır). Kaynak tabloyla (yukarıdaki iki değişmez) nakit akım izdüşümü arasındaki kopukluk buradan yakalanır.

    Önem: kritik · Kaynak: backend/app/services/finance_event_service.py:269
    """
    from sqlalchemy import func

    from app.models.finance_event import FinanceEvent
    rows = (db.query(FinanceEvent.source_type, FinanceEvent.currency, FinanceEvent.is_matched,
                     func.count(FinanceEvent.id),
                     func.coalesce(func.sum(FinanceEvent.amount), 0))
            .filter(FinanceEvent.source_type.in_(("credit", "check")))
            .group_by(FinanceEvent.source_type, FinanceEvent.currency, FinanceEvent.is_matched)
            .order_by(FinanceEvent.source_type, FinanceEvent.currency, FinanceEvent.is_matched)
            .all())
    result = {"%s|%s|%s" % (st, cur, int(bool(m))): {"adet": int(n), "tutar": round(float(a), 2)}
              for st, cur, m, n, a in rows}
    return result


def _inv_kredi_liste_yaniti_imzasi(db, ref_date=None):
    """Kredi listesi ekranının ÜRETTİĞİ yanıtın imzası (ürün adedi, kalan/tutar toplamı, taksit ve ödenen taksit adedi, sonraki ödeme toplamı). GERÇEK KOD YOLU: `list_products()` tüm sayfalar gezilerek çağrılır → `_batch_payment_stats()` (taksit istatistiği, N+1 engelli sorgu) ve `_build_product_response()` (yanıt kurucu) birlikte ölçülür. Kalan/tutar toplamı para birimlerini toplar — rapor değil, DEĞİŞMEZLİK SAĞLAMASI (checksum) amaçlıdır.

    Önem: kritik · Kaynak: backend/app/routers/finance/krediler/products.py:44
    """
    from app.routers.finance.krediler.products import list_products
    kalan = 0.0
    tutar = 0.0
    taksit = 0
    odenen = 0
    sonraki = 0.0
    adet = 0
    sayfa = 1
    while True:
        r = list_products(page=sayfa, page_size=200, type_filter=None, status_filter=None,
                          search=None, db=db, _=None)
        for it in r["items"]:
            adet += 1
            kalan += float(it["remaining_amount"])
            tutar += float(it["total_amount"])
            taksit += int(it["payment_count"] or 0)
            odenen += int(it["paid_count"] or 0)
            sonraki += float(it["next_payment_amount"] or 0)
        if sayfa >= int(r["pages"] or 1):
            break
        sayfa += 1
    result = {"urun_adedi": adet, "kalan_toplam": round(kalan, 2), "tutar_toplam": round(tutar, 2),
              "taksit_adedi": taksit, "odenen_taksit_adedi": odenen,
              "sonraki_odeme_toplami": round(sonraki, 2)}
    return result


def _inv_kredi_odenmemis_taksit_toplami(db, ref_date=None):
    """Aktif kredilerin ödenmemiş (is_paid=False) taksitlerinin para birimi bazlı toplamı: taksit tutarı, anapara bileşeni ve adet. Bu, nakit akımına giren kredi yükümlülüğünün ham çıpasıdır — `credit_summary`/`upcoming_payments` gibi kod yollarından BAĞIMSIZ ölçülür ki iki taraf birlikte kaymasın. Sorgu, `upcoming_payments` filtrelerinin (status='active' + is_paid=False) tarih penceresiz halidir.

    Önem: kritik · Kaynak: backend/app/models/credit_product.py:104
    """
    from sqlalchemy import func

    from app.models.credit_product import CreditPayment, CreditProduct
    rows = (db.query(CreditProduct.currency,
                     func.coalesce(func.sum(CreditPayment.amount), 0),
                     func.coalesce(func.sum(CreditPayment.principal), 0),
                     func.count(CreditPayment.id))
            .join(CreditProduct, CreditPayment.credit_product_id == CreditProduct.id)
            .filter(CreditProduct.status == "active", CreditPayment.is_paid.is_(False))
            .group_by(CreditProduct.currency)
            .order_by(CreditProduct.currency)
            .all())
    result = {str(c): {"taksit_toplami": round(float(a), 2),
                       "anapara_toplami": round(float(p), 2),
                       "adet": int(n)} for c, a, p, n in rows}
    return result


def _inv_odeme_plani_haftalik(db, ref_date=None):
    """Haftalık ödeme planı ucunun GERÇEK kod yolu (payment_schedule.get_payment_schedule) çağrılır: haftalık grup sayısı, toplam tutar, kalem sayısı, ilk/son vade. DİKKAT — denetim API-003: bu uç okuma sırasında sync_vendor_finance_events() + db.commit() ile finance_events YAZAR; ölçümde modül seviyesindeki bu fonksiyon geçici olarak boş bir lambda ile değiştirilip (try/finally ile geri konur) yazma tamamen etkisizleştirilir, salt hesap ölçülür. Not: bu router kopyası vendor_fifo'daki ikizinden FARKLI davranır (ödeme yasaklısı cariler HARİÇ TUTULMAZ + net borç fazlası son faturaya 'leftover' satırı olarak eklenir) → toplamı FIFO toplamından yüksektir. Canlı referans: 43.779.120,55 TL · 41 hafta · 887 kalem · 2026-02-27…2026-12-25.

    Önem: kritik · Kaynak: app/routers/finance/cariler/payment_schedule.py:27
    """
    import app.routers.finance.cariler.payment_schedule as ps
    _orig_sync = ps.sync_vendor_finance_events
    ps.sync_vendor_finance_events = lambda _db: {"created": 0, "updated": 0, "removed": 0, "recurring_synced": 0}
    try:
        groups = ps.get_payment_schedule(from_date=None, to_date=None, db=db, _=None)
    finally:
        ps.sync_vendor_finance_events = _orig_sync
    result = {
        "toplam": round(sum(g["total_amount"] for g in groups), 2),
        "hafta_sayisi": len(groups),
        "kalem_sayisi": sum(len(g["items"]) for g in groups),
        "ilk_vade": str(groups[0]["friday_date"]) if groups else None,
        "son_vade": str(groups[-1]["friday_date"]) if groups else None,
    }
    return result


def _inv_rez_eur_cevrim_katsayilari(db, ref_date=None):
    """Rezervasyon senkronunun kullandığı 'para birimi → EUR' katsayı sözlüğü (`reservation_service._currency_to_eur_factors`). Gerçek fonksiyon çağrılır. TL katsayısının 1/eur_try, USD/GBP'nin çapraz (try_per[c]/eur_try) olduğunu kilitler — bu katsayı bozulursa TL sözleşmeler ciroyu ~50× şişirir. DİKKAT: fonksiyon EN GÜNCEL kur satırını kullanır (tarih bağımlı).

    Önem: kritik · Kaynak: backend/app/services/reservation_service.py:30
    """
    from app.services.reservation_service import _currency_to_eur_factors
    _f = _currency_to_eur_factors(db)
    result = {k: round(float(v), 8) for k, v in sorted(_f.items())} if _f else None
    return result


def _inv_rez_eur_toplam_yil(db, ref_date=None):
    """2026 giriş tarihli rezervasyonların para birimi bazında adet + `eur_total` + ham `net_amount` toplamı ve genel EUR toplamı. Bu, kur çevriminin DB'ye yazılmış sonucudur (FIN-010'un doğrudan hedefi): ham tutar sabit kalırken eur_total oynarsa çevrim mantığı ya da kullanılan kur değişmiştir. Senkron fonksiyonu Sedna tüneli istediğinden çağrılamaz — onun ÜRETTİĞİ değer birebir ölçülür.

    Önem: kritik · Kaynak: backend/app/services/reservation_service.py:100
    """
    from datetime import date

    from sqlalchemy import func

    from app.models.reservation import Reservation
    _rows = (
        db.query(
            Reservation.currency,
            func.count(Reservation.id),
            func.coalesce(func.sum(Reservation.eur_total), 0),
            func.coalesce(func.sum(Reservation.net_amount), 0),
        )
        .filter(Reservation.checkin_date >= date(2026, 1, 1),
                Reservation.checkin_date <= date(2026, 12, 31))
        .group_by(Reservation.currency)
        .order_by(Reservation.currency)
        .all()
    )
    result = {
        (r[0] or "?"): {"adet": int(r[1]), "eur_total": round(float(r[2]), 2), "ham_tutar": round(float(r[3]), 2)}
        for r in _rows
    }
    result["TOPLAM_EUR"] = round(sum(v["eur_total"] for v in result.values()), 2)
    return result


def _inv_runway_banka_nakdi_eur(db, ref_date=None):
    """Saf banka nakdi (EUR): her hesabın (date, id) sırasına göre son bakiyesi eksi bloke tutar, en son TCMB alış kurlarıyla EUR'a çevrilmiş toplam. Panel 'Bankalar' KPI'sı, Nakit Akım sayfa başlığı ve bakiye eğrisinin bugün noktası bu TEK sayıdan beslenir. runway_ozet içinde de yer alır ama ayrı ölçülür: sapma çıkarsa hatanın bakiye/kur tarafında mı yoksa kalem çevriminde mi olduğu tek bakışta ayrılır. Canlı taban: 213.325,00.

    Önem: kritik · Kaynak: backend/app/routers/finance/cash_flow/runway.py:93
    """
    from app.routers.finance.cash_flow.runway import _compute_start_eur
    result = float(_compute_start_eur(db))
    return result


def _inv_runway_ozet(db, ref_date=None):
    """Nakit Koruma (runway) endpoint'inin ürettiği tüm para toplamları: başlangıç banka nakdi (start_eur), bu ay beklenen giriş/çıkış, vadesi geçen gider ve tahsilat, beklemeye alınanlar — her biri kalem sayısı + EUR toplamı olarak. Gerçek endpoint fonksiyonu (runway) çağrılır, sahte current_user yalnız rate-limiter anahtarı içindir. Canlı taban: start_eur 213.325,00 · outs 24 kalem/357.596,65 · overdue 174 kalem/332.012,45.

    Önem: kritik · Kaynak: backend/app/routers/finance/cash_flow/runway.py:244
    """
    import uuid
    from types import SimpleNamespace

    from app.routers.finance.cash_flow.runway import runway
    _r = runway(db=db, current_user=SimpleNamespace(id="fp-" + uuid.uuid4().hex))
    result = {
        "month_start": _r["month_start"], "month_end": _r["month_end"],
        "start_eur": _r["start_eur"],
        "inflows_n": len(_r["inflows"]),
        "inflows_eur": round(sum(i["amount_eur"] for i in _r["inflows"]), 2),
        "outs_n": len(_r["outs"]),
        "outs_eur": round(sum(i["amount_eur"] for i in _r["outs"]), 2),
        "overdue_n": len(_r["overdue"]),
        "overdue_eur": round(sum(i["amount_eur"] for i in _r["overdue"]), 2),
        "overdue_income_n": len(_r["overdue_income"]),
        "overdue_income_eur": round(sum(i["amount_eur"] for i in _r["overdue_income"]), 2),
        "held_n": len(_r["held"]),
        "held_eur": round(sum(i["amount_eur"] for i in _r["held"]), 2),
        "skipped_no_rate": _r["skipped_no_rate"],
    }
    return result


def _inv_si_fifo_cekirdek(db, ref_date=None):
    """FIFO motorunun kendisi: `_compute(db)` DOĞRUDAN çağrılır (30 sn TTL cache'i tamamen atlar — `_compute_cached` DEĞİL). Fatura durum dağılımı (paid/partial/open), toplam tahsil edilen (native + TL karşılığı), fatura anında avansla karşılanan kısım (prepaid) ve müşteri×para birimi bazında artan avans havuzu ölçülür. FIFO sıralaması, aynı-gün fatura-önce-tahsilat kuralı, EUR/TL ayrımı veya _EPS eşiği değişirse bu sayı oynar. Canlı: 3927 fatura, 0,18 sn.

    Önem: kritik · Kaynak: app/services/sales_invoice_service.py:34
    """
    from app.services.sales_invoice_service import _compute
    inv_map, adv_bal = _compute(db)
    status_sayilari = {}
    toplam_tahsil_native = 0.0
    toplam_tahsil_tl = 0.0
    toplam_prepaid_avans = 0.0
    for v in inv_map.values():
        status_sayilari[v["status"]] = status_sayilari.get(v["status"], 0) + 1
        toplam_tahsil_native += v["collected"]
        toplam_tahsil_tl += v["collected_tl"]
        toplam_prepaid_avans += v["advance"]
    havuz_by_cur = {}
    for (code, cur), net in adv_bal.items():
        havuz_by_cur[cur] = round(havuz_by_cur.get(cur, 0.0) + net, 2)
    result = {
        "fatura_adet": len(inv_map),
        "durum_sayilari": status_sayilari,
        "tahsil_native_toplam": round(toplam_tahsil_native, 2),
        "tahsil_tl_toplam": round(toplam_tahsil_tl, 2),
        "prepaid_avans_toplam": round(toplam_prepaid_avans, 2),
        "artan_avans_havuzu_adet": len(adv_bal),
        "artan_avans_havuzu_by_cur": havuz_by_cur,
    }
    return result


def _inv_si_ham_veri_kanari(db, ref_date=None):
    """Karşılaştırmanın GEÇERLİLİK kanarası: satış faturaları / tahsilatlar / 340 avans tablolarının ham adet ve toplamları. Kod yolu ölçmez — bilerek ham SQL. Bu değer iki ölçüm arasında oynadıysa Sedna senkronu (sprenses-sedna-sync.timer, 09-21 arası 2 saatte bir :15) veri yazmış demektir; o durumda diğer tüm değişmezlerdeki fark KOD kaynaklı DEĞİLDİR → ölçüm tekrarlanmalı. Kaynak tablolar: models/sales_invoice.py:27/52/68.

    Önem: kritik · Kaynak: app/models/sales_invoice.py:27
    """
    from sqlalchemy import func

    from app.models.sales_invoice import SalesAdvance, SalesCollection, SalesInvoice
    inv_n, inv_tl, inv_nat = db.query(func.count(SalesInvoice.id),
                                     func.coalesce(func.sum(SalesInvoice.amount), 0),
                                     func.coalesce(func.sum(SalesInvoice.amount_currency), 0)).one()
    col_n, col_tl, col_nat = db.query(func.count(SalesCollection.id),
                                      func.coalesce(func.sum(SalesCollection.amount), 0),
                                      func.coalesce(func.sum(SalesCollection.amount_currency), 0)).one()
    adv_n, adv_rec, adv_con = db.query(func.count(SalesAdvance.id),
                                       func.coalesce(func.sum(SalesAdvance.received), 0),
                                       func.coalesce(func.sum(SalesAdvance.consumed), 0)).one()
    result = {
        "fatura_adet": int(inv_n), "fatura_tl": round(float(inv_tl), 2), "fatura_native": round(float(inv_nat), 2),
        "tahsilat_adet": int(col_n), "tahsilat_tl": round(float(col_tl), 2), "tahsilat_native": round(float(col_nat), 2),
        "avans340_adet": int(adv_n), "avans340_alinan": round(float(adv_rec), 2), "avans340_mahsup": round(float(adv_con), 2),
    }
    return result


def _inv_si_ozet_endpoint(db, ref_date=None):
    """`GET /finance/sales-invoices/summary` endpoint'inin İÇ hesabının birebir taklidi (endpoint Depends(get_db)+require_permission istediği için doğrudan çağrılamaz; router gövdesi sales_invoices.py:377-397 satır satır kopyalandı). Faturalanan / tahsil edilen / AÇIK ALACAK üçlüsünü münferit-acente kırılımıyla ve durum sayaçlarıyla ölçer. Ölçümden önce `_invalidate_compute_cache()` çağrılır → bayat cache riski yok. Canlı: total_acik ≈ 82,17 M TL, 0,41 sn.

    Önem: kritik · Kaynak: app/routers/finance/sales_invoices.py:372
    """
    from app.models.sales_invoice import STATUS_OPEN, STATUS_PAID, STATUS_PARTIAL, SalesInvoice
    from app.services.sales_invoice_service import _compute_cached, _f, _invalidate_compute_cache
    _invalidate_compute_cache()
    smap, _ = _compute_cached(db)
    agg = {"total": {"invoiced": 0.0, "collected": 0.0, "count": 0},
           "munferit": {"invoiced": 0.0, "collected": 0.0, "count": 0},
           "agency": {"invoiced": 0.0, "collected": 0.0, "count": 0}}
    status_counts = {STATUS_PAID: 0, STATUS_PARTIAL: 0, STATUS_OPEN: 0}
    for inv in db.query(SalesInvoice).all():
        entry = smap.get(inv.id, {"collected_tl": 0.0, "status": STATUS_OPEN})
        amt = _f(inv.amount)
        bucket = "munferit" if inv.is_munferit else "agency"
        for key in ("total", bucket):
            agg[key]["invoiced"] += amt
            agg[key]["collected"] += entry.get("collected_tl", 0.0)
            agg[key]["count"] += 1
        status_counts[entry["status"]] += 1
    out = {}
    for key in agg:
        out[key + "_faturalanan"] = round(agg[key]["invoiced"], 2)
        out[key + "_tahsil"] = round(agg[key]["collected"], 2)
        out[key + "_acik"] = round(agg[key]["invoiced"] - agg[key]["collected"], 2)
        out[key + "_adet"] = agg[key]["count"]
    for k, v in status_counts.items():
        out["durum_" + k] = v
    result = out
    return result


def _inv_t_hesap_cari_ay_toplam(db, ref_date=None):
    """Panel T-Hesap Cetveli'nin cari ay (monthly, offset=0) kolon toplamları: giriş/çıkış EUR, net, gerçekleşen giriş/çıkış, faaliyet/finansman neti ve kur bulunamadığı için atlanan kalem sayısı. GERÇEK ENDPOINT FONKSİYONU çağrılır (t_account); FastAPI Depends varsayılanları yerine db ve sahte bir current_user (yalnız .id, rate-limiter anahtarı için) elle geçilir — her ölçümde benzersiz id verildiğinden 429 oluşmaz. Canlı taban: total_in 1.292.325,45 / total_out 1.367.422,01 / net -75.096,56.

    Önem: kritik · Kaynak: backend/app/routers/finance/cash_flow/t_account.py:235
    """
    import uuid
    from types import SimpleNamespace

    from app.routers.finance.cash_flow.t_account import t_account
    _r = t_account(period="monthly", offset=0, db=db,
                   current_user=SimpleNamespace(id="fp-" + uuid.uuid4().hex))
    result = {k: _r[k] for k in ("start_date", "end_date", "total_in_eur", "total_out_eur",
                                 "net_eur", "realized_in_eur", "realized_out_eur",
                                 "faaliyet_net_eur", "finansman_net_eur", "skipped_no_rate")}
    return result


def _inv_t_hesap_grup_kirilimi(db, ref_date=None):
    """Aynı T-Hesap çağrısının GRUP bazında kırılımı: her giriş/çıkış başlığı için (toplam EUR, gerçekleşen EUR, beklemedeki EUR, kalem sayısı). Kolon toplamı aynı kalırken bir kategorinin diğerine kayması (ör. Kredi/Leasing ile Cari, Personel ile Vergi/SGK arası etiket kayması veya bir grubun toplam-dışı sayılması) yalnız burada görünür — FIN-001 sınıfı sessiz kaymanın en hassas dedektörü.

    Önem: kritik · Kaynak: backend/app/routers/finance/cash_flow/t_account.py:300
    """
    import uuid
    from types import SimpleNamespace

    from app.routers.finance.cash_flow.t_account import t_account
    _r = t_account(period="monthly", offset=0, db=db,
                   current_user=SimpleNamespace(id="fp-" + uuid.uuid4().hex))
    _out = {}
    for _side in ("giris", "cikis"):
        for _g in _r[_side]:
            _out["%s|%s" % (_side, _g["label"])] = [round(_g["total_eur"], 2),
                                                    round(_g.get("realized_eur", 0.0), 2),
                                                    round(_g.get("held_eur", 0.0), 2),
                                                    int(_g["item_count"]),
                                                    bool(_g.get("in_total", True)),
                                                    _g.get("section")]
    result = dict(sorted(_out.items()))
    return result


def _inv_acente_mahsup_projeksiyon(db, ref_date=None):
    """Acente Mahsup & Nakit Akım projeksiyonu: `compute_settlement(db, 2026, None, 0.0, today)` GERÇEK servis fonksiyonu çağrılır (router `/sales/acente-mahsup/` bunu 60 sn TTL cache arkasından verir — biz servisi DOĞRUDAN çağırdığımız için o cache devrede değil). Ciro→kickback→avans mahsubu→vadeli tahsilat zincirinin EUR çıktıları ölçülür. Yıl (2026) ve today (2026-07-25) sabit pinlenmiştir. UYARI: içeride `_latest_rates` son TCMB kurunu kullanır → `eur_kuru` alanı da çıktıda; döviz cronu iki ölçüm arasında yeni kur yazarsa TÜM EUR alanları kayar (kod hatası değil, veri değişimi — teşhis için eur_kuru'na bak). Canlı: 0,6-1,4 sn.

    Önem: yuksek · Kaynak: app/services/agency_settlement_service.py:94
    """
    from datetime import date

    from app.services.agency_settlement_service import compute_settlement
    from app.services.sales_invoice_service import _invalidate_compute_cache
    _invalidate_compute_cache()
    st = compute_settlement(db, 2026, None, 0.0, date(2026, 7, 25))
    k = st["kpi"]
    result = {
        "eur_kuru": st["eur_rate"],
        "ciro_toplam_eur": k["grand_total"],
        "gerceklesen_eur": k["realized"],
        "avans_alinan_eur": k["advance_received"],
        "avans_mahsup_eur": k["advance_applied"],
        "avans_kalan_eur": k["advance_remaining"],
        "kickback_eur": k["kickback_total"],
        "huni_mahsup_eur": st["funnel"]["advance_offset"],
        "huni_net_tahsilat_eur": st["funnel"]["net_collection"],
        "nakit_giris_eur": st["cashflow"]["in_total"],
        "nakit_kapanis_eur": st["cashflow"]["closing"],
        "vadesi_gecen_eur": st["overdue"]["total"],
        "acente_satir_adet": len(st["agencies"]),
        "proj_fatura_toplam_eur": st["invoices"]["total_amount"],
        "proj_fatura_net_eur": st["invoices"]["total_net"],
    }
    return result


def _inv_avans_fe_mutabakat(db, ref_date=None):
    """Avans ↔ finance_events tutarlılığı: `source_type='advance'` olayların para birimi ve eşleşme durumu (is_matched) bazında tutar/adedi + advances tablosundaki kayıt sayısıyla karşılaştırması. advance_service'in `finance_event_svc.upsert_advance` / `invalidate` çağrıları bozulursa (nakit akıma yazmama, hayalet kayıt, çift sayım) bu sayılar ayrışır. Canlı: 36 avans ↔ 36 FE, eşleşmiş 29 / açık 7, 0,005 sn.

    Önem: yuksek · Kaynak: app/services/advance_service.py:23
    """
    from sqlalchemy import func

    from app.models.advance import Advance
    from app.models.finance_event import FinanceEvent
    rows = (db.query(FinanceEvent.currency, FinanceEvent.is_matched,
                     func.coalesce(func.sum(FinanceEvent.amount), 0), func.count(FinanceEvent.id))
            .filter(FinanceEvent.source_type == "advance")
            .group_by(FinanceEvent.currency, FinanceEvent.is_matched).all())
    fe = {}
    for cur, matched, tot, cnt in rows:
        slot = fe.setdefault(cur, {"eslesmis_tutar": 0.0, "eslesmis_adet": 0,
                                   "acik_tutar": 0.0, "acik_adet": 0})
        if matched:
            slot["eslesmis_tutar"] = round(float(tot or 0), 2); slot["eslesmis_adet"] = int(cnt)
        else:
            slot["acik_tutar"] = round(float(tot or 0), 2); slot["acik_adet"] = int(cnt)
    adv_n = db.query(func.count(Advance.id)).filter(Advance.status != "cancelled").scalar() or 0
    fe_n = db.query(func.count(FinanceEvent.id)).filter(FinanceEvent.source_type == "advance").scalar() or 0
    result = {"fe_by_currency": fe, "avans_kayit_adet": int(adv_n), "fe_kayit_adet": int(fe_n)}
    return result


def _inv_avans_modul_ozet(db, ref_date=None):
    """finance.avanslar modülünün `GET /finance/avanslar/summary` iç hesabının birebir taklidi (endpoint Depends istediği için router gövdesi advances.py:305-329 kopyalandı): iptal edilmemiş avansların para birimi × durum (pending/received) bazında tutar ve adedi. advance_service'in create/update/delete davranışı ya da durum akışı değişirse bu tablo oynar. Canlı: EUR bekleyen 1.434.000 (7 kayıt) / alınan 7.498.000 (29 kayıt), 0,003 sn.

    Önem: yuksek · Kaynak: app/routers/finance/advances.py:300
    """
    from sqlalchemy import func

    from app.models.advance import Advance
    rows = (db.query(Advance.currency, Advance.status,
                     func.sum(Advance.amount), func.count(Advance.id))
            .filter(Advance.status != "cancelled")
            .group_by(Advance.currency, Advance.status).all())
    out = {}
    for currency, status, total_amount, cnt in rows:
        slot = out.setdefault(currency, {"pending": 0.0, "received": 0.0,
                                         "pending_count": 0, "received_count": 0})
        if status == "pending":
            slot["pending"] = round(float(total_amount or 0), 2)
            slot["pending_count"] = int(cnt)
        elif status == "received":
            slot["received"] = round(float(total_amount or 0), 2)
            slot["received_count"] = int(cnt)
    result = out
    return result


def _inv_cari_detay_ornek(db, ref_date=None):
    """Cari detay ucunun (get_vendor_detay) gerçek fonksiyonu, DETERMİNİSTİK seçilen tek cari için çağrılır: net borcu en yüksek cari (eşitlikte en küçük vendor_id). Ölçülen: bakiye, NET vadesi geçmiş tutar/adet, işlem sayısı, ilk satırın kümülatif bakiyesi (SQL pencere fonksiyonu) ve fifo_remaining çipi. Toplamların gizlediği satır-seviyesi hataları (kümülatif bakiye sıralaması, fatura-başı FIFO kalanı) yakalar. Canlı referans: vendor_id 584 · bakiye −3.100.000,00 · overdue 317.000,00 (1 fatura).

    Önem: yuksek · Kaynak: app/routers/finance/cariler/vendors.py:234
    """
    from app.routers.finance.cariler.vendors import get_vendor_detail
    from app.services.vendor_fifo import _get_vendor_net_debts
    debts = _get_vendor_net_debts(db)
    if not debts:
        result = {"vendor_id": None}
    else:
        vid = sorted(debts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        res = get_vendor_detail(vendor_id=vid, page=1, page_size=5, sort_by=None, sort_dir="desc", db=db, _=None)
        v = res["vendor"]
        items = res["transactions"]["items"]
        first = items[0] if items else {}
        result = {
            "vendor_id": vid,
            "bakiye": round(float(v["bakiye"]), 2),
            "overdue": round(float(v["overdue"]), 2),
            "overdue_count": v["overdue_count"],
            "islem_sayisi": res["transactions"]["total"],
            "ilk_satir_bakiye": round(float(first["bakiye"]), 2) if first.get("bakiye") is not None else None,
            "ilk_satir_fifo_kalan": first.get("fifo_remaining"),
        }
    return result


def _inv_fe_eslesme_bayraklari(db, ref_date=None):
    """Çift sayım kalkanının durumu: kaynak türü × is_matched kırılımında kayıt sayısı, artı iki bütünlük sayacı (is_matched=True olduğu halde matched_event_id boş olanlar; is_matched=False olduğu halde bağı duranlar). Bir eşleştirme yolu bozulup bayrak sessizce sıfırlanırsa (2026-07-19'da upsert_scheduled_entry'de yaşandı — Haziran'da ~94 bin EUR çift sayım) T-Hesap toplamı şişer; bu sayaç o an kırmızıya döner. Canlı taban: check 96 açık/104 eşleşmiş · vendor_payment 868 açık · orphan_matched_no_link 231 (cari kuralı gereği normal).

    Önem: yuksek · Kaynak: backend/app/models/finance_event.py:104
    """
    from sqlalchemy import func

    from app.models.finance_event import FinanceEvent
    _rows = (db.query(FinanceEvent.source_type, FinanceEvent.is_matched,
                      func.count(FinanceEvent.id))
             .group_by(FinanceEvent.source_type, FinanceEvent.is_matched).all())
    _out = {"%s:%s" % (st, "eslesmis" if m else "acik"): int(n) for st, m, n in _rows}
    _out["_orphan_matched_no_link"] = int(db.query(func.count(FinanceEvent.id)).filter(
        FinanceEvent.is_matched == True, FinanceEvent.matched_event_id.is_(None)).scalar() or 0)
    _out["_orphan_link_no_matched"] = int(db.query(func.count(FinanceEvent.id)).filter(
        FinanceEvent.is_matched == False, FinanceEvent.matched_event_id.isnot(None)).scalar() or 0)
    result = dict(sorted(_out.items()))
    return result


def _inv_fe_vendor_payment_toplam(db, ref_date=None):
    """FIFO'nun nakit akıma yansıması: eşleşmemiş vendor_payment finance_events kayıtlarının adedi, amount ve amount_try toplamı (ham okuma, sync_vendor_fifo yazımının SONUCU ölçülür). FIFO toplamı değişmeden bu sayı kayarsa senkron kopmuştur; amount_try kolonu FIN-001 'hayalet para' bulgusunun tam kaynağıdır (canlıda amount 40.349.056,15 iken amount_try yalnız 1.875.144,79 — çoğu satırda NULL). Adet farkı (868 vs FIFO 870) normaldir: aktif düzenli ödeme tanımına bağlı carilere FE üretilmez.

    Önem: yuksek · Kaynak: app/services/sync_vendor_fifo.py:38
    """
    from sqlalchemy import func

    from app.models.finance_event import FinanceEvent
    row = (db.query(func.count(FinanceEvent.id),
                    func.coalesce(func.sum(FinanceEvent.amount), 0),
                    func.coalesce(func.sum(FinanceEvent.amount_try), 0))
           .filter(FinanceEvent.source_type == "vendor_payment",
                   FinanceEvent.is_matched.is_(False)).one())
    result = {"adet": int(row[0]), "amount_toplam": round(float(row[1]), 2), "amount_try_toplam": round(float(row[2]), 2)}
    return result


def _inv_fx_aylik_degerleme_bizim_taraf(db, ref_date=None):
    """Aylık kur değerlemesi `fx_service.compute_monthly_revaluation(db, 2026, 6)` gerçek fonksiyonu çağrılır; Sedna tüneli gerekmesin diye `fetch_valuation` boş sözlük döndüren bir lambda ile enjekte edilir (fonksiyonun desteklediği resmi parametre) — böylece BİZİM taraf (ay sonu ekstre bakiyesi × ay sonu ledger_rate = expected_try) tam ölçülür, Sedna karşılaştırması dışarıda kalır. Kalemler hesap ID'sine göre sıralanır (sorguda order_by yok, sıra garantisiz).

    Önem: yuksek · Kaynak: backend/app/services/fx_service.py:104
    """
    from app.services import fx_service
    _r = fx_service.compute_monthly_revaluation(db, 2026, 6, fetch_valuation=lambda codes, y, m: {})
    result = {
        "hesap_sayisi": len(_r.get("items", [])),
        "ay_sonu": _r.get("month_end"),
        "toplam_beklenen_try": round(sum(i["expected_try"] or 0 for i in _r.get("items", [])), 2),
        "kalemler": sorted(
            [{"hesap": i["account_id"], "pb": i["currency"],
              "bakiye": i["our_fx_balance"],
              "kur": round(i["rate"], 6) if i["rate"] else None,
              "beklenen_try": i["expected_try"]} for i in _r.get("items", [])],
            key=lambda x: x["hesap"]),
    }
    return result


def _inv_fx_kur_tablosu_ozet(db, ref_date=None):
    """Kur tablosunun kendi parmak izi (kontrol ölçümü): satır sayısı, en son tarih ve EUR/USD/GBP için en güncel alış/satış (unit'e bölünmüş). Kod yolu değil VERİ girdisidir — diğer kur değişmezlerinden biri oynadığında 'kod mu bozuldu yoksa TCMB cron'u yeni satır mı ekledi' sorusunu tek başına yanıtlar.

    Önem: yuksek · Kaynak: backend/app/models/exchange_rate.py:22
    """
    from sqlalchemy import func

    from app.models.exchange_rate import ExchangeRate
    result = {"satir_sayisi": int(db.query(func.count(ExchangeRate.id)).scalar() or 0)}
    _maxd = db.query(func.max(ExchangeRate.date)).scalar()
    result["son_tarih"] = _maxd.isoformat() if _maxd else None
    for _c in ("EUR", "USD", "GBP"):
        _row = (
            db.query(ExchangeRate.forex_buying, ExchangeRate.forex_selling, ExchangeRate.unit)
            .filter(ExchangeRate.currency_code == _c, ExchangeRate.forex_buying.isnot(None))
            .order_by(ExchangeRate.date.desc()).first()
        )
        result[f"{_c}_son_alis"] = round(float(_row.forex_buying) / float(_row.unit or 1), 6) if _row else None
        result[f"{_c}_son_satis"] = round(float(_row.forex_selling) / float(_row.unit or 1), 6) if (_row and _row.forex_selling) else None
        result[f"{_c}_satir"] = int(
            db.query(func.count(ExchangeRate.id)).filter(ExchangeRate.currency_code == _c).scalar() or 0
        )
    return result


def _inv_kredi_anapara_tutarlilik_sapmasi(db, ref_date=None):
    """ARCH-001 NÖBETÇİSİ. Her aktif kredi için `remaining_amount` ile `total_amount - (ödenmiş taksitlerin anapara toplamı)` karşılaştırılır; 1 kuruştan büyük farkı olan kredi adedi ve toplam sapma döner. ARCH-001'de manuel kredi eşleştirme `apply_credit_bank_match`'i atlayıp anaparayı düşmüyor, geri alma ise koşulsuz iade ediyordu → her eşleştir/geri-al turunda `remaining_amount` şişiyordu. Bu sayı DB verisinden türetilir (kod yolu çağırmaz) — deploy'un migration'ı ya da eşleştirme mantığı veriyi bozarsa seviye kayar.

    Önem: yuksek · Kaynak: backend/app/services/matching_service.py:950
    """
    from sqlalchemy import func

    from app.models.credit_product import CreditPayment, CreditProduct
    odenen = dict(db.query(CreditPayment.credit_product_id,
                           func.coalesce(func.sum(CreditPayment.principal), 0))
                  .filter(CreditPayment.is_paid.is_(True))
                  .group_by(CreditPayment.credit_product_id).all())
    sapan = 0
    toplam_sapma = 0.0
    for pid, tutar, kalan in (db.query(CreditProduct.id, CreditProduct.total_amount,
                                       CreditProduct.remaining_amount)
                              .filter(CreditProduct.status == "active")
                              .order_by(CreditProduct.id).all()):
        beklenen = float(tutar) - float(odenen.get(pid, 0) or 0)
        if beklenen < 0:
            beklenen = 0.0
        fark = round(float(kalan) - beklenen, 2)
        if abs(fark) >= 0.01:
            sapan += 1
            toplam_sapma += fark
    result = {"sapan_kredi_adedi": sapan, "toplam_sapma": round(toplam_sapma, 2)}
    return result


def _inv_kredi_yaklasan_odemeler_365(db, ref_date=None):
    """Önümüzdeki 365 gün içinde vadesi gelen ödenmemiş kredi taksitlerinin para birimi bazlı adet/tutar/anapara toplamı. GERÇEK KOD YOLU: `upcoming_payments(days=365, include_paid=False, ...)` endpoint fonksiyonu doğrudan çağrılır (Depends parametrelerine db ve None geçilir). DİKKAT: fonksiyon içinde `date.today()` kullanılır → sonuç güne bağlıdır.

    Önem: yuksek · Kaynak: backend/app/routers/finance/krediler/summary.py:95
    """
    from app.routers.finance.krediler.summary import upcoming_payments
    rows = upcoming_payments(days=365, include_paid=False, db=db, _=None)
    per = {}
    for r in rows:
        d = per.setdefault(str(r["currency"]), {"adet": 0, "tutar": 0.0, "anapara": 0.0})
        d["adet"] += 1
        d["tutar"] += float(r["amount"])
        d["anapara"] += float(r["principal"] or 0)
    result = {k: {"adet": v["adet"], "tutar": round(v["tutar"], 2), "anapara": round(v["anapara"], 2)}
              for k, v in sorted(per.items())}
    return result


def _inv_mutabakat_acik_ve_kur_farki(db, ref_date=None):
    """Sedna mutabakatı: açık uyuşmazlıklar gerçek filtre yardımcısı `mutabakat._apply_item_filters` ile (endpoint'in gördüğü kümenin aynısı) çekilir, durum bazında adet + işaretli tutar toplanır; ayrıca `/fx-differences` endpoint'indeki `total_amount_try` toplamı ve kayıt adedi birebir taklit edilir (endpoint Depends istiyor). Uyuşmazlık sınıflandırmasının veya kur farkı (646/656) birikiminin sessizce kaymasını yakalar.

    Önem: yuksek · Kaynak: backend/app/routers/accounting/mutabakat.py:67
    """
    from sqlalchemy import func

    from app.models.event_match import FxDifference
    from app.models.sedna_recon import SednaBankRecon
    from app.routers.accounting.mutabakat import _apply_item_filters
    _q = _apply_item_filters(db.query(SednaBankRecon), None, None, None, False, None)
    _open = _q.all()
    _by_status = {}
    for _r in _open:
        _s = _by_status.setdefault(_r.status, {"adet": 0, "tutar": 0.0})
        _s["adet"] += 1
        _s["tutar"] = round(_s["tutar"] + float(_r.amount or 0), 2)
    result = {"acik_toplam": len(_open), "durum_bazinda": dict(sorted(_by_status.items()))}
    result["kur_farki_toplam_try"] = round(float(
        db.query(func.coalesce(func.sum(FxDifference.amount_try), 0)).scalar() or 0), 2)
    result["kur_farki_adet"] = int(db.query(func.count(FxDifference.id)).scalar() or 0)
    return result


def _inv_yaslananlar_ozeti(db, ref_date=None):
    """Yaşlananlar raporunun (compute_aging, endpoint + cron bildiriminin ORTAK çekirdeği) ürettiği sayılar: 7 günden eski hâlâ eşleşmemiş/gerçekleşmemiş tahminlerin kaynak türü bazında adedi + TL toplamı + en eski tarihi, ayrıca etiketsiz/eşleşmesiz banka hareketlerinin adedi ve mutlak TL toplamı. item_limit=1 verilir (liste değil, toplamlar ölçülür → hızlı). Canlı taban: 148 açık tahmin (çek/temettü/cari) + 316 eşleşmesiz banka hareketi / 74.751.914,82.

    Önem: yuksek · Kaynak: backend/app/routers/finance/cash_flow/aging.py:44
    """
    from app.routers.finance.cash_flow.aging import compute_aging
    _a = compute_aging(db, days=7, item_limit=1)
    result = {
        "cutoff": _a["cutoff"],
        "stale_total_count": _a["stale_forecasts"]["total_count"],
        "by_source": {k: [v["count"], v["total_try"], v["oldest_date"]]
                      for k, v in sorted(_a["stale_forecasts"]["by_source"].items())},
        "unmatched_bank_count": _a["unmatched_bank"]["count"],
        "unmatched_bank_total": _a["unmatched_bank"]["total"],
    }
    return result


def _inv_cari_analitik_toplamlari(db, ref_date=None):
    """Cariler v2 analitik sekmelerinin iki gerçek endpoint fonksiyonu (get_monthly_balances mode=fifo + get_yearly_turnover) çağrılır. Referans yıl/ay TAKVİMDEN DEĞİL veritabanından türetilir (max(vendor_transactions.date)) → gün/ay dönmesi ölçümü kaydırmaz. Ölçülen: aylık faturalanan/kapanan/kalan üçlüsü + satır sayısı, yıllık ciro + fatura adedi. Devir/açılış hariç tutma filtresinin ve ay-sonu kesiminin bozulmasını yakalar. Canlı referans (2026-07): invoiced 123.466.681,86 · closed 81.428.886,90 · remaining 42.037.794,96 (FIFO toplamıyla aynı olmalı) · yıllık ciro 208.068.337,38 / 2.625 fatura.

    Önem: orta · Kaynak: app/routers/finance/cariler/analytics.py:43
    """
    from sqlalchemy import func

    from app.models.vendor_transaction import VendorTransaction
    from app.routers.finance.cariler.analytics import get_monthly_balances, get_yearly_turnover
    mx = db.query(func.max(VendorTransaction.date)).scalar()
    if mx is None:
        result = {"referans_ay": None}
    else:
        mb = get_monthly_balances(year=mx.year, month=mx.month, mode="fifo", hide_zero=True, db=db, _=None)
        yt = get_yearly_turnover(year=mx.year, db=db, _=None)
        result = {
            "referans_ay": "%04d-%02d" % (mx.year, mx.month),
            "aylik_invoiced": mb["totals"]["invoiced"],
            "aylik_closed": mb["totals"]["closed"],
            "aylik_remaining": mb["totals"]["remaining"],
            "aylik_satir": len(mb["items"]),
            "yillik_ciro": yt["total_turnover"],
            "yillik_fatura": yt["total_invoices"],
        }
    return result


def _inv_rez_doluluk_ciro(db, ref_date=None):
    """Doluluk/ciro hesaplayıcısı `occupancy.occupancy_metrics(db, 2026-01-01, 2026-12-31)` birebir çağrılır: oda-gece, geceleme, kapasite, doluluk %, EUR ciro, ADR, RevPAR. Rezervasyon EUR'sunun rapor katmanındaki orantılama (eur_total/nights × generate_series overlap) mantığını kilitler. Sabit tarih aralığı verildiği için `date.today()` etkisi yoktur; ~4 sn sürer (365 günlük generate_series join) — bu yüzden 'orta'.

    Önem: orta · Kaynak: backend/app/services/occupancy.py:55
    """
    from datetime import date

    from app.services.occupancy import occupancy_metrics
    _m = occupancy_metrics(db, date(2026, 1, 1), date(2026, 12, 31))
    result = {
        "room_nights": _m["room_nights"],
        "guest_nights": _m["guest_nights"],
        "capacity": _m["capacity"],
        "occupancy_pct": _m["occupancy_pct"],
        "revenue_eur": _m["revenue_eur"],
        "adr_eur": _m["adr_eur"],
        "revpar_eur": _m["revpar_eur"],
    }
    return result


def _inv_fe_event_eur_tam_tarama(db, ref_date=None):
    """EUR çevrim çekirdeğinin (`t_account._event_eur`) TÜM finance_events üzerinde taranması.

    NEDEN AYRI BİR DEĞİŞMEZ: rapor değişmezleri yalnız kendi PENCERELERİNİ ölçer
    (T-Hesap cari ay, runway bu ay). Bir pencere dışındaki kayda dokunan sessiz hata
    onlara görünmez. 2026-07-25'te kapı doğrulanırken bu somut olarak yaşandı: FIN-001
    kasten geri alındı, `amount_try` tekrar öne çekildi — ama sapan iki TRY kaydı
    Haziran ve Ağustos'ta olduğu için Temmuz penceresindeki hiçbir sayı oynamadı ve
    kapı "temiz" dedi. `fx_event_eur_cevrim` de TRY'yi bilerek dışlıyordu.

    Bu tarama tarih ve para birimi süzmez → FIN-001 sınıfı (TRY dalında amount vs
    amount_try önceliği) doğrudan buradan yakalanır.

    Önem: kritik · Kaynak: backend/app/routers/finance/cash_flow/t_account.py:_event_eur
    """
    from app.models.finance_event import FinanceEvent
    from app.routers.finance.cash_flow.t_account import _event_eur
    _cache = {}
    _rows = db.query(FinanceEvent).order_by(FinanceEvent.id).all()
    _by = {}
    _skipped = 0
    _total = 0.0
    for _fe in _rows:
        _v = _event_eur(db, _fe, _cache)
        if _v is None:
            _skipped += 1
            continue
        _c = (_fe.currency or "TRY").upper()
        _by[_c] = round(_by.get(_c, 0.0) + _v, 2)
        _total += _v
    result = {
        "kalem": len(_rows),
        "cevrilemeyen": _skipped,
        "toplam_eur": round(_total, 2),
        "para_birimi": dict(sorted(_by.items())),
    }
    return result

# ─── Kayıt tablosu ───────────────────────────────────────────
# Sıra: kritik → yüksek → orta. Ölçüm bu sırayla koşar.
INVARIANTS = [
    {"key": "fe_event_eur_tam_tarama", "onem": "kritik", "fn": _inv_fe_event_eur_tam_tarama},
    {"key": 'avans_bakiye_birlesik', "onem": 'kritik', "fn": _inv_avans_bakiye_birlesik},
    {"key": 'cari_net_borc_toplami', "onem": 'kritik', "fn": _inv_cari_net_borc_toplami},
    {"key": 'cari_ozet_kpi', "onem": 'kritik', "fn": _inv_cari_ozet_kpi},
    {"key": 'cek_durum_para_birimi_toplami', "onem": 'kritik', "fn": _inv_cek_durum_para_birimi_toplami},
    {"key": 'cek_ozeti_endpoint', "onem": 'kritik', "fn": _inv_cek_ozeti_endpoint},
    {"key": 'fe_acik_defter_toplami', "onem": 'kritik', "fn": _inv_fe_acik_defter_toplami},
    {"key": 'fe_amount_try_tutarliligi', "onem": 'kritik', "fn": _inv_fe_amount_try_tutarliligi},
    {"key": 'fifo_cari_bazli_parmak_izi', "onem": 'kritik', "fn": _inv_fifo_cari_bazli_parmak_izi},
    {"key": 'fifo_kalan_toplam', "onem": 'kritik', "fn": _inv_fifo_kalan_toplam},
    {"key": 'fx_event_eur_cevrim', "onem": 'kritik', "fn": _inv_fx_event_eur_cevrim},
    {"key": 'fx_ledger_rate_sabit', "onem": 'kritik', "fn": _inv_fx_ledger_rate_sabit},
    {"key": 'hakedis_ozet', "onem": 'kritik', "fn": _inv_hakedis_ozet},
    {"key": 'kredi_aktif_kalan_anapara_tip', "onem": 'kritik', "fn": _inv_kredi_aktif_kalan_anapara_tip},
    {"key": 'kredi_cek_finance_event_izdusumu', "onem": 'kritik', "fn": _inv_kredi_cek_finance_event_izdusumu},
    {"key": 'kredi_liste_yaniti_imzasi', "onem": 'kritik', "fn": _inv_kredi_liste_yaniti_imzasi},
    {"key": 'kredi_odenmemis_taksit_toplami', "onem": 'kritik', "fn": _inv_kredi_odenmemis_taksit_toplami},
    {"key": 'odeme_plani_haftalik', "onem": 'kritik', "fn": _inv_odeme_plani_haftalik},
    {"key": 'rez_eur_cevrim_katsayilari', "onem": 'kritik', "fn": _inv_rez_eur_cevrim_katsayilari},
    {"key": 'rez_eur_toplam_yil', "onem": 'kritik', "fn": _inv_rez_eur_toplam_yil},
    {"key": 'runway_banka_nakdi_eur', "onem": 'kritik', "fn": _inv_runway_banka_nakdi_eur},
    {"key": 'runway_ozet', "onem": 'kritik', "fn": _inv_runway_ozet},
    {"key": 'si_fifo_cekirdek', "onem": 'kritik', "fn": _inv_si_fifo_cekirdek},
    {"key": 'si_ham_veri_kanari', "onem": 'kritik', "fn": _inv_si_ham_veri_kanari},
    {"key": 'si_ozet_endpoint', "onem": 'kritik', "fn": _inv_si_ozet_endpoint},
    {"key": 't_hesap_cari_ay_toplam', "onem": 'kritik', "fn": _inv_t_hesap_cari_ay_toplam},
    {"key": 't_hesap_grup_kirilimi', "onem": 'kritik', "fn": _inv_t_hesap_grup_kirilimi},
    {"key": 'acente_mahsup_projeksiyon', "onem": 'yuksek', "fn": _inv_acente_mahsup_projeksiyon},
    {"key": 'avans_fe_mutabakat', "onem": 'yuksek', "fn": _inv_avans_fe_mutabakat},
    {"key": 'avans_modul_ozet', "onem": 'yuksek', "fn": _inv_avans_modul_ozet},
    {"key": 'cari_detay_ornek', "onem": 'yuksek', "fn": _inv_cari_detay_ornek},
    {"key": 'fe_eslesme_bayraklari', "onem": 'yuksek', "fn": _inv_fe_eslesme_bayraklari},
    {"key": 'fe_vendor_payment_toplam', "onem": 'yuksek', "fn": _inv_fe_vendor_payment_toplam},
    {"key": 'fx_aylik_degerleme_bizim_taraf', "onem": 'yuksek', "fn": _inv_fx_aylik_degerleme_bizim_taraf},
    {"key": 'fx_kur_tablosu_ozet', "onem": 'yuksek', "fn": _inv_fx_kur_tablosu_ozet},
    {"key": 'kredi_anapara_tutarlilik_sapmasi', "onem": 'yuksek', "fn": _inv_kredi_anapara_tutarlilik_sapmasi},
    {"key": 'kredi_yaklasan_odemeler_365', "onem": 'yuksek', "fn": _inv_kredi_yaklasan_odemeler_365},
    {"key": 'mutabakat_acik_ve_kur_farki', "onem": 'yuksek', "fn": _inv_mutabakat_acik_ve_kur_farki},
    {"key": 'yaslananlar_ozeti', "onem": 'yuksek', "fn": _inv_yaslananlar_ozeti},
    {"key": 'cari_analitik_toplamlari', "onem": 'orta', "fn": _inv_cari_analitik_toplamlari},
    {"key": 'rez_doluluk_ciro', "onem": 'orta', "fn": _inv_rez_doluluk_ciro},
]
