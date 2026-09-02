"""`app/constants.py` tek-kaynak bekçisi — `source_type` değerleri yalnız `models/finance_event.py`'de tanımlıdır.

2026-09-02 yeniden yapılandırmasında bulundu: `SourceType.TAX = "tax"` gibi 9 değer constants.py'de
ikinci kez literal yazılıydı (dosyanın kendi docstring'i "çift tanım yok" derken). Bu test, her
`SourceType` değerinin finance_event kataloğunda olduğunu ve constants.py kaynağında finance
source_type literal'i bulunmadığını doğrular.
"""
import ast
from pathlib import Path

from app import constants
from app.models import finance_event as fe


def test_every_source_type_value_is_in_finance_event_catalogue():
    values = {v for k, v in vars(constants.SourceType).items() if isinstance(v, str) and k.isupper()}
    assert values, "SourceType boş olamaz"
    assert values <= set(fe.ALL_SOURCE_TYPES), f"Katalog dışı source_type: {values - set(fe.ALL_SOURCE_TYPES)}"
    assert constants.SourceType.SCHEDULED <= set(fe.ALL_SOURCE_TYPES)


def test_constants_py_has_no_literal_source_type_strings():
    """`SourceType` sınıf gövdesinde string literal atama YOK — yalnız isimli re-export."""
    src = Path(constants.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SourceType")
    literal_assigns = [
        t.id for n in cls.body if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name)
        and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
    ]
    assert not literal_assigns, f"SourceType içinde literal string tanımı: {literal_assigns} — finance_event'ten re-export et"
