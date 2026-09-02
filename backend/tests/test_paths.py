"""`app/paths.py` — merkezi yol sabitleri kilidi (2026-09-02 yeniden yapılandırma bekçisi).

Yeniden yapılandırmadan önce 15 modül `__file__` derinliğinden dizin türetiyordu; bir dosya
taşınınca yol sessizce kayabiliyordu. Artık hepsi `app.paths`'ten okur. Bu test hem sabitlerin
gerçek diskteki kökü gösterdiğini hem de tüketici modüllerin AYNI değeri gördüğünü doğrular.
"""
import os
from pathlib import Path

from app import paths


def test_repo_and_backend_roots_resolve_to_real_project():
    assert (paths.REPO_ROOT / "CLAUDE.md").is_file()
    assert (paths.BACKEND_DIR / "alembic.ini").is_file()
    assert (paths.APP_DIR / "main.py").is_file()
    assert paths.UPLOADS_DIR == paths.BACKEND_DIR / "uploads"
    assert paths.LOGS_DIR.name == "logs" and paths.LOGS_DIR.parent == paths.BACKEND_DIR
    assert paths.TESSDATA_DIR == paths.BACKEND_DIR / "tessdata"
    assert paths.CRON_DENETIM_SCRIPT.is_file()
    assert paths.QNB_REFRESH_TOKEN_FILE.parent == paths.REPO_ROOT
    assert paths.uploads_subdir("x", "y") == os.path.join(str(paths.UPLOADS_DIR), "x", "y")


def test_consumers_share_the_central_paths():
    """Yol tüketen her modül merkezi sabitle birebir aynı değeri görmeli (derinlikten bağımsız)."""
    from app import main
    from app.integrations import qnb_api
    from app.parsers import bank_parser
    from app.routers import files, system_denetim, system_docs
    from app.routers.finance import bank_statement_import, cc_statements, checks
    from app.routers.finance.cariler import _helpers as cariler_helpers
    from app.routers.sales import contracts
    from app.routers.sales.reservations import _helpers as reservation_helpers
    from app.services import disk_cleanup_service
    from app.utils import file_upload, pdf_bank_instruction

    up = str(paths.UPLOADS_DIR)
    assert Path(main.LOG_DIR) == paths.LOGS_DIR
    assert main._uploads_dir == paths.UPLOADS_DIR
    assert files._uploads_dir == paths.UPLOADS_DIR
    assert file_upload.UPLOAD_DIR == paths.UPLOADS_DIR
    assert system_docs.ROOT == paths.REPO_ROOT
    assert system_denetim._BACKEND_DIR == str(paths.BACKEND_DIR)
    assert system_denetim._CRON_SCRIPT == str(paths.CRON_DENETIM_SCRIPT)
    assert cc_statements.UPLOAD_DIR == os.path.join(up, "cc_statements")
    assert checks.UPLOAD_DIR == os.path.join(up, "check_files")
    assert bank_statement_import.UPLOAD_DIR == os.path.join(up, "bank_statements")
    assert cariler_helpers.UPLOAD_DIR == os.path.join(up, "vendor_statements")
    assert contracts.UPLOAD_DIR == os.path.join(up, "contract_files")
    assert reservation_helpers.UPLOAD_DIR == os.path.join(up, "reservation_files")
    assert bank_parser.TESSDATA_DIR == str(paths.TESSDATA_DIR)
    assert pdf_bank_instruction._BACKEND_DIR == str(paths.BACKEND_DIR)
    assert disk_cleanup_service._BACKEND_DIR == str(paths.BACKEND_DIR)
    assert disk_cleanup_service._REPO_DIR == str(paths.REPO_ROOT)
    assert disk_cleanup_service.VENV_DIR == str(paths.VENV_DIR)
    assert qnb_api._REFRESH_FILE == str(paths.QNB_REFRESH_TOKEN_FILE)


def test_no_new_file_depth_path_computation_in_app():
    """`app/` altında `__file__` tabanlı proje-dizini hesabı yalnız paths.py ve config.py'de kalabilir."""
    offenders = []
    for py in paths.APP_DIR.rglob("*.py"):
        rel = py.relative_to(paths.APP_DIR).as_posix()
        if rel in ("paths.py", "config.py"):
            continue
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if "__file__" in line and "reportlab.__file__" not in line:
                offenders.append(f"{rel}:{i}")
    assert not offenders, f"__file__ tabanlı yol hesabı yeni kodda yasak — app.paths kullan: {offenders}"
