"""Banka ekstre ayrıştırıcı — saf yardımcı fonksiyon birim testleri.

Denetim D10-1 (2026-06-21): `bank_parser.py` (1044 satır, finansal verinin giriş kapısı)
ayrıştırma mantığı hiç test edilmiyordu (~%9 kapsam = sadece import). TR/EN sayı formatı
yanlış tespiti veya bakiye-zinciri hatası sessizce yanlış tutar/işaret üretip finance_events'e
yayılır. Bu dosya fixture gerektirmeyen saf yardımcıları kapsar (PDF/Excel fixture'ları ayrı).
"""
from datetime import date

import pytest

from app.utils.bank_parser import (
    ParsedTransaction,
    _balance_chain_score,
    _detect_number_format,
    _ensure_chronological_order,
    _extract_trailing_numbers,
    _repair_balance_gaps,
    _smart_parse_number,
    _strip_currency_suffix,
    compute_tx_hash,
    parse_date_tr,
    parse_english_number,
    parse_turkish_number,
)


def _tx(d, amount, balance, **kw):
    return ParsedTransaction(date=d, receipt_no=kw.get("receipt_no"), description=kw.get("description", ""),
                             amount=amount, balance=balance, type=kw.get("type", "income"),
                             tx_hash=kw.get("tx_hash", ""), time=kw.get("time"))


class TestParseTurkishNumber:
    @pytest.mark.parametrize("text,expected", [
        ("3.765.000,00", 3765000.00),
        ("2.785,37", 2785.37),
        ("0,00", 0.0),
        ("1.234.567,89", 1234567.89),
        ("100", 100.0),                  # binlik/ondalık yok
        ("2.785,37 TL", 2785.37),        # döviz son eki
        ("1.500,00 TRY", 1500.0),
        ("-1.234,56", -1234.56),         # negatif
        ("+250,00", 250.0),              # pozitif işaret atılır
        ("(500,00)", -500.0),            # parantez = negatif
        ("", None),
        ("abc", None),
    ])
    def test_parse(self, text, expected):
        assert parse_turkish_number(text) == expected


class TestParseEnglishNumber:
    @pytest.mark.parametrize("text,expected", [
        ("600,000.00", 600000.00),       # QNB Finansbank formatı
        ("1,234.56", 1234.56),
        ("1,234.56 USD", 1234.56),
        ("-50.00", -50.0),
        ("(99.99)", -99.99),
        ("100", 100.0),
        ("", None),
        ("abc", None),
    ])
    def test_parse(self, text, expected):
        assert parse_english_number(text) == expected


class TestStripCurrencySuffix:
    @pytest.mark.parametrize("text,expected", [
        ("2.785,37 TL", "2.785,37"),
        ("100 EUR", "100"),
        ("100 euro", "100"),             # case-insensitive
        ("50,00 USD", "50,00"),
        ("1.000,00", "1.000,00"),        # son ek yoksa değişmez
    ])
    def test_strip(self, text, expected):
        assert _strip_currency_suffix(text) == expected


class TestDetectNumberFormat:
    def test_english(self):
        rows = [["x", "600,000.00", "1,200,000.00"], ["x", "1,234.56", "2,468.00"]]
        assert _detect_number_format(rows, amount_idx=1, balance_idx=2) == "english"

    def test_turkish(self):
        rows = [["x", "600.000,00", "1.200.000,00"], ["x", "1.234,56", "2.468,00"]]
        assert _detect_number_format(rows, amount_idx=1, balance_idx=2) == "turkish"

    def test_empty_defaults_turkish(self):
        # Belirsiz/boş → varsayılan turkish (TR bankalarının çoğunluğu)
        assert _detect_number_format([["", ""]], amount_idx=0, balance_idx=1) == "turkish"

    def test_idx_out_of_range_safe(self):
        assert _detect_number_format([["a"]], amount_idx=5, balance_idx=9) == "turkish"


class TestParseDateTr:
    @pytest.mark.parametrize("text,expected", [
        ("15.06.2026", date(2026, 6, 15)),
        ("15/06/2026", date(2026, 6, 15)),
        ("15-06-2026", date(2026, 6, 15)),
        ("01.01.2025", date(2025, 1, 1)),
        ("2026-06-15", None),            # ISO formatı desteklenmez
        ("32.13.2026", None),            # geçersiz gün/ay
        ("", None),
    ])
    def test_parse(self, text, expected):
        assert parse_date_tr(text) == expected


class TestComputeTxHash:
    def test_deterministic(self):
        a = compute_tx_hash(date(2026, 6, 1), "R1", -100.0, "EFT")
        b = compute_tx_hash(date(2026, 6, 1), "R1", -100.0, "EFT")
        assert a == b and len(a) == 64

    def test_seq_changes_hash(self):
        base = compute_tx_hash(date(2026, 6, 1), None, -100.0, "EFT")
        seqd = compute_tx_hash(date(2026, 6, 1), None, -100.0, "EFT", seq=1)
        assert base != seqd

    def test_amount_changes_hash(self):
        a = compute_tx_hash(date(2026, 6, 1), None, -100.0, "EFT")
        b = compute_tx_hash(date(2026, 6, 1), None, -100.01, "EFT")
        assert a != b


class TestBalanceChainScore:
    def test_consistent_chain_high_score(self):
        # her bakiye = önceki + tutar → her adım +1
        txs = [_tx(date(2026, 6, 1), 0, 1000), _tx(date(2026, 6, 2), -200, 800),
               _tx(date(2026, 6, 3), 500, 1300)]
        assert _balance_chain_score(txs) == 2  # 2 geçiş tutarlı

    def test_broken_chain_zero(self):
        txs = [_tx(date(2026, 6, 1), 0, 1000), _tx(date(2026, 6, 2), -200, 999)]
        assert _balance_chain_score(txs) == 0

    def test_none_balance_skipped(self):
        txs = [_tx(date(2026, 6, 1), 0, None), _tx(date(2026, 6, 2), -200, 800)]
        assert _balance_chain_score(txs) == 0


class TestSmartParseNumber:
    @pytest.mark.parametrize("text,expected", [
        ("1.234,56", 1234.56),           # standart TR
        ("1.234.567,89", 1234567.89),
        ("1.234", 1234.0),               # virgülsüz, son nokta-parça 3 hane = binlik
        ("1.50", 1.5),                   # virgülsüz, son nokta-parça 2 hane = ondalık (OCR)
        ("123", 123.0),
        ("-1.234,56", -1234.56),
        ("", None),
        ("abc", None),
    ])
    def test_parse(self, text, expected):
        assert _smart_parse_number(text) == expected


class TestExtractTrailingNumbers:
    def test_two_trailing(self):
        nums, rem = _extract_trailing_numbers("EFT GIDEN 2.785,37 1.273.709,37")
        assert nums == ["2.785,37", "1.273.709,37"]
        assert rem == "EFT GIDEN"

    def test_inner_currency_labels_stripped(self):
        # Yapı Kredi: "... 2.785,37 TL 1.273.709,37 TL"
        nums, rem = _extract_trailing_numbers("ACIKLAMA 2.785,37 TL 1.273.709,37 TL")
        assert nums == ["2.785,37", "1.273.709,37"]
        assert rem == "ACIKLAMA"

    def test_no_numbers(self):
        nums, rem = _extract_trailing_numbers("SADECE METIN")
        assert nums == []


class TestRepairBalanceGaps:
    def test_inserts_missing_tx(self):
        # prev.balance=1000; cur amount=-200 ama cur.balance=500 → 300'lük eksik gider var
        txs = [_tx(date(2026, 6, 1), 0, 1000), _tx(date(2026, 6, 2), -200, 500)]
        repaired = _repair_balance_gaps(txs)
        assert len(repaired) == 3
        recovered = repaired[1]  # araya eklenen
        assert abs(recovered.amount - (-300.0)) < 0.01   # 500 - (-200) - 1000 = -300
        assert recovered.type == "expense"
        assert abs(recovered.balance - 700.0) < 0.01     # 1000 + (-300)

    def test_consistent_chain_unchanged(self):
        txs = [_tx(date(2026, 6, 1), 0, 1000), _tx(date(2026, 6, 2), -200, 800)]
        assert len(_repair_balance_gaps(txs)) == 2

    def test_short_list_noop(self):
        txs = [_tx(date(2026, 6, 1), 0, 1000)]
        assert _repair_balance_gaps(txs) == txs


class TestEnsureChronologicalOrder:
    def test_reverses_reverse_chronological(self):
        # ilk tarih > son tarih → ters kronolojik → çevrilmeli
        txs = [_tx(date(2026, 6, 10), -100, 900), _tx(date(2026, 6, 1), 0, 1000)]
        _ensure_chronological_order(txs)
        assert txs[0].date == date(2026, 6, 1) and txs[-1].date == date(2026, 6, 10)

    def test_keeps_chronological(self):
        txs = [_tx(date(2026, 6, 1), 0, 1000), _tx(date(2026, 6, 10), -100, 900)]
        _ensure_chronological_order(txs)
        assert txs[0].date == date(2026, 6, 1)

    def test_same_day_uses_balance_chain(self):
        # Aynı gün; ters sıra bakiye zinciriyle tutarlı → çevrilmeli
        # Doğru sıra: 1000 → (+500) 1500. Listeyi ters ver: [1500(amt+500), 1000(amt 0)]
        txs = [_tx(date(2026, 6, 1), 500, 1500), _tx(date(2026, 6, 1), 0, 1000)]
        _ensure_chronological_order(txs)
        assert txs[0].balance == 1000 and txs[1].balance == 1500


# ─── parse_excel entegrasyon testleri (sentetik .xlsx — gerçek dosya ayrıştırma) ───

from datetime import datetime  # noqa: E402

from app.utils.bank_parser import parse_excel  # noqa: E402


def _write_xlsx(path, meta_rows, header, data_rows):
    """Sentetik banka ekstresi .xlsx üret: meta satırları + tablo başlığı + veri."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for r in meta_rows:
        ws.append(r)
    ws.append(header)
    for r in data_rows:
        ws.append(r)
    wb.save(str(path))
    return str(path)


class TestParseExcelIntegration:
    def test_signed_amount_with_balance(self, tmp_path):
        """Tarih(datetime)+Açıklama+Tutar(işaretli sayı)+Bakiye — IBAN/döviz/işlemler doğru çıkmalı."""
        p = _write_xlsx(
            tmp_path / "halk.xlsx",
            meta_rows=[
                ["Hesap Ekstresi"],
                ["IBAN: TR33 0006 1005 1978 6457 8413 26", "Para Birimi: TRY"],
                ["Şube: Merkez"],
            ],
            header=["Tarih", "Açıklama", "Tutar", "Bakiye"],
            data_rows=[
                [datetime(2026, 6, 1), "ACILIS", 1000.00, 1000.00],
                [datetime(2026, 6, 2), "EFT GIDEN", -250.50, 749.50],
                [datetime(2026, 6, 3), "HAVALE GELEN", 500.00, 1249.50],
            ],
        )
        res = parse_excel(p)
        assert res.header.iban == "TR330006100519786457841326"
        assert res.header.currency == "TRY"
        assert res.header.branch_name == "Merkez"
        assert len(res.transactions) == 3
        # kronolojik (eskiden yeniye)
        assert res.transactions[0].date == date(2026, 6, 1)
        assert res.transactions[0].type == "income" and res.transactions[0].amount == 1000.00
        assert res.transactions[1].type == "expense" and res.transactions[1].amount == -250.50
        assert res.transactions[1].balance == 749.50
        assert res.transactions[2].amount == 500.00

    def test_debit_credit_columns(self, tmp_path):
        """Ayrı Borç/Alacak kolonları → işaretli amount'a dönüşmeli (borç negatif, alacak pozitif)."""
        p = _write_xlsx(
            tmp_path / "ziraat.xlsx",
            meta_rows=[["IBAN: TR10 0001 0000 0000 0000 0000 01", "TRY"]],
            header=["Tarih", "Açıklama", "Borç", "Alacak", "Bakiye"],
            data_rows=[
                [datetime(2026, 6, 1), "MAAS", None, 5000.00, 5000.00],
                [datetime(2026, 6, 2), "KIRA", 2000.00, None, 3000.00],
            ],
        )
        res = parse_excel(p)
        assert len(res.transactions) == 2
        maas = next(t for t in res.transactions if t.description == "MAAS")
        kira = next(t for t in res.transactions if t.description == "KIRA")
        assert maas.amount == 5000.00 and maas.type == "income"
        assert kira.amount == -2000.00 and kira.type == "expense"   # borç → negatif

    def test_string_date_and_tr_number(self, tmp_path):
        """String tarih (DD.MM.YYYY) + TR-format string tutar/bakiye → doğru parse edilmeli."""
        p = _write_xlsx(
            tmp_path / "teb.xlsx",
            meta_rows=[["IBAN: TR20 0003 2000 0000 0000 0000 02", "TRY"]],
            header=["Tarih", "Açıklama", "Tutar", "Bakiye"],
            data_rows=[
                ["01.06.2026", "ACILIS", "1.000,00", "1.000,00"],
                ["02.06.2026", "POS", "-1.234,56", "-234,56"],
            ],
        )
        res = parse_excel(p)
        assert len(res.transactions) == 2
        assert res.transactions[0].amount == 1000.00
        assert res.transactions[1].amount == -1234.56
        assert res.transactions[1].balance == -234.56

    def test_no_header_row_returns_empty(self, tmp_path):
        """Tablo başlığı (Tarih+tutar/bakiye) yoksa boş sonuç — çökmemeli."""
        p = _write_xlsx(tmp_path / "bos.xlsx", meta_rows=[["Rastgele"]],
                        header=["Kolon1", "Kolon2"], data_rows=[["a", "b"]])
        res = parse_excel(p)
        assert res.transactions == []
