"""`utils/fx_rates.RateBook` — tarih bazlı TCMB kur defteri (bisect, birim, çapraz, kur-yok → None)."""
from datetime import date

from app.models.exchange_rate import ExchangeRate
from app.utils.fx_rates import CROSS_EUR_CURRENCIES, RateBook


def _seed(db, rows):
    db.query(ExchangeRate).filter(
        ExchangeRate.currency_code.in_(("EUR", "USD", "GBP"))
    ).delete(synchronize_session=False)
    for code, dt, buying, unit in rows:
        db.add(ExchangeRate(date=dt, currency_code=code, unit=unit,
                            forex_buying=buying, forex_selling=buying))
    db.flush()


def test_cross_set_is_usd_gbp():
    assert CROSS_EUR_CURRENCIES == ("USD", "GBP")


def test_rate_lookup_uses_last_publication_on_or_before_date(db):
    _seed(db, [("EUR", date(2026, 1, 1), 40, 1), ("EUR", date(2026, 1, 5), 42, 1)])
    book = RateBook.load(db)
    assert book.eur(date(2026, 1, 1)) == 40
    assert book.eur(date(2026, 1, 3)) == 40      # 3 Oca: son yayın 1 Oca
    assert book.eur(date(2026, 1, 5)) == 42
    assert book.eur(date(2026, 1, 9)) == 42      # hafta sonu/tatil → önceki yayın
    assert book.eur(date(2025, 12, 31)) is None  # ilk yayından önce → kur yok


def test_unit_division_and_cross_conversion(db):
    _seed(db, [
        ("EUR", date(2026, 1, 1), 40, 1),
        ("USD", date(2026, 1, 1), 30, 1),
        ("GBP", date(2026, 1, 1), 4500, 100),  # 100 birim → 45,00 TL/GBP
    ])
    book = RateBook.load(db)
    d = date(2026, 1, 3)
    assert book.rate("GBP", d) == 45.0
    assert book.to_eur(100, "USD", d) == 75.0    # 100 × 30 / 40
    assert book.to_eur(10, "GBP", d) == 11.25    # 10 × 45 / 40
    assert book.to_eur(400, "TL", d) == 10.0     # 400 / 40
    assert book.to_eur(400, "TRY", d) == 10.0
    assert book.to_eur(50, "EUR", d) == 50.0
    assert book.to_eur(1, "CHF", d) is None      # yüklenmemiş döviz → 1:1 varsayımı yok


def test_missing_eur_rate_returns_none_even_for_tl(db):
    _seed(db, [("USD", date(2026, 1, 1), 30, 1)])
    book = RateBook.load(db)
    assert book.to_eur(400, "TL", date(2026, 1, 3)) is None
    assert book.to_eur(100, "USD", date(2026, 1, 3)) is None
