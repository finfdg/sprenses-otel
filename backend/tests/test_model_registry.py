"""Model kayıt bütünlüğü bekçisi (alembic import yüzeyinde).

Bir model dosyası `app/models/__init__.py` içinde import edilmezse SQLAlchemy o tabloyu
`Base.metadata`'ya eklemez. `alembic/env.py` metadata'yı yalnızca `app.config`,
`app.database` ve `app.models` üzerinden kurar — **router'ları yüklemez**. Kayıtsız tablo
bu yüzden autogenerate'e "veritabanında var ama modelde yok" görünür ve migration'a
**DROP TABLE** olarak yazılır.

2026-07 denetimi bunu canlıda yakaladı: `check.py` (checks, check_uploads), `ai_usage.py`,
`ai_conversation.py` (ai_conversations, ai_messages) kayıt dışıydı — bir sonraki
`alembic revision --autogenerate` çekirdek finans tablosu `checks` için DROP üretecekti.

KRİTİK TASARIM NOTU: Bu kontrol AYRI BİR SÜREÇTE koşmak zorundadır. pytest süreci
`conftest.py` üzerinden FastAPI uygulamasını yükler; router'lar model modüllerini dolaylı
olarak import ettiğinden metadata bu süreçte "yanlışlıkla tam" görünür ve test sessizce
her zaman geçer. Alt süreç, alembic'in gördüğü daraltılmış import yüzeyini taklit eder.
"""

import glob
import json
import os
import re
import subprocess
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BACKEND_DIR, "app", "models")

# alembic/env.py'nin import ettiği yüzeyin birebir aynısı — router YOK.
_PROBE = """
import json
from app.database import Base
import app.models  # noqa: F401
print("___METADATA___" + json.dumps(sorted(Base.metadata.tables.keys())))
"""


def _declared_tables():
    """app/models/*.py içindeki tüm __tablename__ değerlerini {tablo: dosya} olarak döner."""
    found = {}
    for path in glob.glob(os.path.join(MODELS_DIR, "*.py")):
        with open(path, encoding="utf-8") as fh:
            for match in re.finditer(r'__tablename__\s*=\s*["\'](\w+)["\']', fh.read()):
                found[match.group(1)] = os.path.basename(path)
    return found


def _registered_tables_as_alembic_sees_them():
    """Alembic'in daraltılmış import yüzeyinde Base.metadata'ya giren tabloları döner."""
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"Metadata alt süreci başarısız:\n{result.stderr}"
    for line in result.stdout.splitlines():
        if line.startswith("___METADATA___"):
            return set(json.loads(line[len("___METADATA___"):]))
    raise AssertionError(f"Alt süreç metadata döndürmedi:\n{result.stdout}\n{result.stderr}")


def test_all_model_tables_registered_for_alembic():
    """Her __tablename__ alembic'in gördüğü metadata'da olmalı — yoksa autogenerate DROP üretir."""
    declared = _declared_tables()
    registered = _registered_tables_as_alembic_sees_them()

    missing = {table: src for table, src in declared.items() if table not in registered}

    assert not missing, (
        "Şu tablolar alembic'in gördüğü Base.metadata'da YOK — "
        "app/models/__init__.py'ye import ekleyin:\n"
        + "\n".join(f"  - {table}  ({src})" for table, src in sorted(missing.items()))
        + "\n\nUYARI: bu eksiklik `alembic revision --autogenerate` çıktısında "
          "DROP TABLE olarak belirir."
    )


def test_no_orphan_tables_in_metadata():
    """Metadata'da app/models/ dışından gelen tablo olmamalı (çift yönlü kontrol)."""
    declared = _declared_tables()
    registered = _registered_tables_as_alembic_sees_them()

    extra = registered - set(declared)
    assert not extra, (
        "Base.metadata'da app/models/ dışından gelen tablo(lar) var: " + ", ".join(sorted(extra))
    )
