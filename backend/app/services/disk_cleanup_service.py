"""Disk kullanım analizi + düzenli temizlik (system.server modülü servis katmanı).

Neden servis: temizlik iki yerden tetiklenir — (a) UI'daki Disk kartı → `POST /server/disk/cleanup`,
(b) günlük `sprenses-disk-cleanup.timer` → `cron_disk_cleanup.py`. İkisi de BU dosyadaki
`scan_disk()` / `run_cleanup()` fonksiyonlarını çağırır, böylece "elle temizlik" ile
"otomatik temizlik" arasında davranış sapması olamaz (CLAUDE.md ortak-service deseni).

Kategori tasarımı:
- `cleanable=True`  → yeniden üretilebilen önbellek/log; otomatik silinebilir.
- `cleanable=False` → bilgi amaçlı (müşteri dosyaları, yedekler, bağımlılıklar) — ASLA otomatik silinmez.

Tüm yollar sabittir; kullanıcı girdisi yol üretmez. Temizlik seçimi yalnız whitelist'li `key` ile yapılır.
"""

import glob
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Yol sabitleri ────────────────────────────────────────────────────────────

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REPO_DIR = os.path.dirname(_BACKEND_DIR)
_HOME = os.path.expanduser("~")

APP_LOG_DIR = os.path.join(_BACKEND_DIR, "logs")
UPLOADS_DIR = os.path.join(_BACKEND_DIR, "uploads")
VENV_DIR = os.path.join(_BACKEND_DIR, "venv")
NODE_MODULES_DIR = os.path.join(_REPO_DIR, "frontend", "node_modules")
WORKTREES_DIR = os.path.join(_REPO_DIR, ".claude", "worktrees")

JOURNAL_DIR = "/var/log/journal"
DNF_CACHE_DIR = "/var/cache/dnf"
DNF_TMP_GLOB = "/var/tmp/dnf-*"
BACKUP_DIR = "/var/backups"
NPM_CACHE_DIRS = [os.path.join(_HOME, ".npm", "_cacache"), os.path.join(_HOME, ".npm", "_npx")]
ROOT_NPM_DIR = "/root/.npm"
PIP_CACHE_DIR = os.path.join(_HOME, ".cache", "pip")
PLAYWRIGHT_DIR = os.path.join(_HOME, ".cache", "ms-playwright")
CLAUDE_CLI_DIR = os.path.join(_HOME, ".claude", "remote", "ccd-cli")
CLAUDE_PROJECTS_DIR = os.path.join(_HOME, ".claude", "projects")

# ─── Temizlik politikası ──────────────────────────────────────────────────────

JOURNAL_KEEP_MB = 200          # journald'den sonra kalacak tavan (vacuum hedefi)
APP_LOG_KEEP_DAYS = 14         # döndürülmüş uygulama logları bu yaştan sonra silinir
CLAUDE_CLI_KEEP_VERSIONS = 2   # Claude CLI'ın en yeni N sürümü tutulur (geri dönüş payı)

DU_TIMEOUT = 30
CMD_TIMEOUT = 120

# ─── Kategori tanımları ───────────────────────────────────────────────────────
# key → UI'da gösterilecek etiket + hangi yolları kapsadığı + temizlenebilir mi.

CATEGORIES: List[Dict[str, Any]] = [
    {
        "key": "journal",
        "label": "Systemd Journal Logları",
        "path": JOURNAL_DIR,
        "cleanable": True,
        "description": "Servis logları (journalctl). Son {} MB tutulur, eskisi silinir.".format(JOURNAL_KEEP_MB),
    },
    {
        "key": "npm_cache",
        "label": "npm Önbelleği",
        "path": "~/.npm · /root/.npm",
        "cleanable": True,
        "description": "Paket indirme önbelleği. Silinince ilk kurulumda yeniden indirilir.",
    },
    {
        "key": "pip_cache",
        "label": "pip Önbelleği",
        "path": "~/.cache/pip",
        "cleanable": True,
        "description": "Python paket önbelleği. Silinmesi güvenli.",
    },
    {
        "key": "dnf_cache",
        "label": "Sistem Paket Önbelleği (dnf)",
        "path": "/var/cache/dnf · /var/tmp/dnf-*",
        "cleanable": True,
        "description": "İşletim sistemi paket önbelleği ve artık geçici dizinler.",
    },
    {
        "key": "app_logs",
        "label": "Uygulama Logları (döndürülmüş)",
        "path": APP_LOG_DIR,
        "cleanable": True,
        "description": "{} günden eski `*.log.N` arşiv dosyaları. Güncel log dosyası korunur.".format(APP_LOG_KEEP_DAYS),
    },
    {
        "key": "claude_cli",
        "label": "Claude CLI Eski Sürümleri",
        "path": CLAUDE_CLI_DIR,
        "cleanable": True,
        "description": "En yeni {} sürüm tutulur, eskileri silinir (her biri ~250 MB).".format(CLAUDE_CLI_KEEP_VERSIONS),
    },
    # ─── Bilgi amaçlı — otomatik silinmez ───
    {
        "key": "uploads",
        "label": "Yüklenen Dosyalar",
        "path": UPLOADS_DIR,
        "cleanable": False,
        "description": "Müşteri belgeleri (dekont, ekstre, kontrat). Silinmez.",
    },
    {
        "key": "backups",
        "label": "Yedekler",
        "path": BACKUP_DIR,
        "cleanable": False,
        "description": "Veritabanı + dosya yedekleri. Kendi rotasyonu var (30 yedek).",
    },
    {
        "key": "deps",
        "label": "Bağımlılıklar (venv + node_modules)",
        "path": "backend/venv · frontend/node_modules",
        "cleanable": False,
        "description": "Uygulamanın çalışması için gerekli. Silinirse yeniden kurulum şart.",
    },
    {
        "key": "worktrees",
        "label": "Git Worktree'leri (Claude oturumları)",
        "path": WORKTREES_DIR,
        "cleanable": False,
        "description": "Bitmiş oturumların çalışma kopyaları — elle: `git worktree remove <yol>`.",
    },
    {
        "key": "playwright",
        "label": "Playwright Tarayıcıları",
        "path": PLAYWRIGHT_DIR,
        "cleanable": False,
        "description": "Tarayıcı otomasyonu için indirilen tarayıcılar.",
    },
    {
        "key": "claude_sessions",
        "label": "Claude Oturum Geçmişi",
        "path": CLAUDE_PROJECTS_DIR,
        "cleanable": False,
        "description": "Oturum kayıtları ve bellek dosyaları. Silinmesi geçmişi kaybettirir.",
    },
]

CLEANABLE_KEYS = [c["key"] for c in CATEGORIES if c["cleanable"]]


# ─── Ölçüm yardımcıları ───────────────────────────────────────────────────────


def _dir_bytes(path: str, use_sudo: bool = False) -> int:
    """Bir dizinin GERÇEK disk kullanımı (ayrılmış blok, apparent size değil).

    `du` bazı alt dizinleri okuyamazsa 1 ile çıkar ama toplamı yine yazar → stdout
    ayrıştırılabiliyorsa returncode'a bakmadan kabul edilir.

    `use_sudo` yolunda `os.path.exists()` ile ÖN KONTROL YAPILMAZ: /root gibi dizinler
    ec2-user'a kapalıdır → `exists()` False döner ve boyut sessizce 0 görünürdü.
    """
    if not use_sudo and not os.path.exists(path):
        return 0
    cmd = ["du", "-s", "-x", "--block-size=1", path]
    if use_sudo:
        cmd = ["sudo", "-n"] + cmd
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=DU_TIMEOUT)
        return int(result.stdout.split()[0])
    except (subprocess.TimeoutExpired, ValueError, IndexError, OSError):
        logger.debug("Boyut ölçülemedi: %s", path, exc_info=True)
        return 0


def _paths_bytes(paths: List[str], use_sudo: bool = False) -> int:
    return sum(_dir_bytes(p, use_sudo=use_sudo) for p in paths)


def _file_bytes(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _old_rotated_logs() -> List[str]:
    """`*.log.N` biçimli, APP_LOG_KEEP_DAYS'ten eski arşiv logları (güncel log hariç)."""
    cutoff = time.time() - APP_LOG_KEEP_DAYS * 86400
    out = []
    for path in glob.glob(os.path.join(APP_LOG_DIR, "*.log.*")):
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                out.append(path)
        except OSError:
            continue
    return sorted(out)


def _stale_cli_versions() -> List[str]:
    """Claude CLI dizinindeki, en yeni CLAUDE_CLI_KEEP_VERSIONS dışında kalan sürüm dosyaları."""
    if not os.path.isdir(CLAUDE_CLI_DIR):
        return []
    entries = []
    for name in os.listdir(CLAUDE_CLI_DIR):
        path = os.path.join(CLAUDE_CLI_DIR, name)
        try:
            if os.path.isfile(path):
                entries.append((os.path.getmtime(path), path))
        except OSError:
            continue
    entries.sort(reverse=True)  # en yeni önce
    return [p for _, p in entries[CLAUDE_CLI_KEEP_VERSIONS:]]


# ─── Kategori bazlı boyut + temizlenebilir hesabı ─────────────────────────────


def _measure(key: str) -> Dict[str, int]:
    """Bir kategori için (toplam boyut, temizlenebilir boyut) döner."""
    if key == "journal":
        size = _dir_bytes(JOURNAL_DIR)
        return {"size": size, "cleanable": max(0, size - JOURNAL_KEEP_MB * 1024 * 1024)}

    if key == "npm_cache":
        size = _paths_bytes(NPM_CACHE_DIRS) + _dir_bytes(ROOT_NPM_DIR, use_sudo=True)
        return {"size": size, "cleanable": size}

    if key == "pip_cache":
        size = _dir_bytes(PIP_CACHE_DIR)
        return {"size": size, "cleanable": size}

    if key == "dnf_cache":
        size = _dir_bytes(DNF_CACHE_DIR) + _paths_bytes(sorted(glob.glob(DNF_TMP_GLOB)))
        return {"size": size, "cleanable": size}

    if key == "app_logs":
        size = _dir_bytes(APP_LOG_DIR)
        return {"size": size, "cleanable": sum(_file_bytes(p) for p in _old_rotated_logs())}

    if key == "claude_cli":
        size = _dir_bytes(CLAUDE_CLI_DIR)
        return {"size": size, "cleanable": sum(_file_bytes(p) for p in _stale_cli_versions())}

    if key == "uploads":
        return {"size": _dir_bytes(UPLOADS_DIR), "cleanable": 0}

    if key == "backups":
        return {"size": _dir_bytes(BACKUP_DIR), "cleanable": 0}

    if key == "deps":
        return {"size": _paths_bytes([VENV_DIR, NODE_MODULES_DIR]), "cleanable": 0}

    if key == "worktrees":
        return {"size": _dir_bytes(WORKTREES_DIR), "cleanable": 0}

    if key == "playwright":
        return {"size": _dir_bytes(PLAYWRIGHT_DIR), "cleanable": 0}

    if key == "claude_sessions":
        return {"size": _dir_bytes(CLAUDE_PROJECTS_DIR), "cleanable": 0}

    return {"size": 0, "cleanable": 0}


# ─── Temizlik işlemleri ───────────────────────────────────────────────────────


def _run(cmd: List[str]) -> bool:
    """Sabit komutu çalıştır; başarı durumunu döner (hata loglanır, istisna fırlatmaz)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=CMD_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        logger.warning("Temizlik komutu çalıştırılamadı: %s", " ".join(cmd), exc_info=True)
        return False
    if result.returncode != 0:
        logger.warning("Temizlik komutu hata verdi (%s): %s", " ".join(cmd), result.stderr.strip()[:300])
        return False
    return True


def _rmtree(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def _clean(key: str) -> None:
    """Bir kategoriyi temizler. Yollar sabittir — dışarıdan yol gelmez."""
    if key == "journal":
        _run(["sudo", "-n", "journalctl", "--vacuum-size={}M".format(JOURNAL_KEEP_MB)])

    elif key == "npm_cache":
        for path in NPM_CACHE_DIRS:
            _rmtree(path)
        # /root ec2-user'a kapalı → isdir() ön kontrolü yapılmaz; `rm -rf` yoksa da 0 döner.
        _run(["sudo", "-n", "rm", "-rf", ROOT_NPM_DIR])

    elif key == "pip_cache":
        _rmtree(PIP_CACHE_DIR)

    elif key == "dnf_cache":
        _run(["sudo", "-n", "dnf", "clean", "all"])
        for path in sorted(glob.glob(DNF_TMP_GLOB)):
            _rmtree(path)

    elif key == "app_logs":
        for path in _old_rotated_logs():
            try:
                os.remove(path)
            except OSError:
                logger.warning("Log dosyası silinemedi: %s", path, exc_info=True)

    elif key == "claude_cli":
        for path in _stale_cli_versions():
            try:
                os.remove(path)
            except OSError:
                logger.warning("Eski CLI sürümü silinemedi: %s", path, exc_info=True)


# ─── Genel API ────────────────────────────────────────────────────────────────


def _filesystem() -> Dict[str, Any]:
    usage = shutil.disk_usage("/")
    return {
        "mount": "/",
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "percent": round((usage.used / usage.total) * 100, 1) if usage.total else 0.0,
    }


def scan_disk() -> Dict[str, Any]:
    """Disk kullanımının kategori bazlı dökümü + temizlenebilir alan."""
    categories = []
    for spec in CATEGORIES:
        measured = _measure(spec["key"])
        categories.append({
            "key": spec["key"],
            "label": spec["label"],
            "path": spec["path"],
            "description": spec["description"],
            "cleanable": spec["cleanable"],
            "size_bytes": measured["size"],
            "cleanable_bytes": measured["cleanable"] if spec["cleanable"] else 0,
        })

    fs = _filesystem()
    measured_total = sum(c["size_bytes"] for c in categories)
    # Ölçülen kategoriler diskin tamamını kapsamaz (işletim sistemi, paketler…) →
    # kullanıcı "toplam neden tutmuyor" diye sormasın diye kalanı açıkça gösteriyoruz.
    other_bytes = max(0, fs["used_bytes"] - measured_total)

    return {
        "filesystem": fs,
        "categories": categories,
        "other_bytes": other_bytes,
        "total_cleanable_bytes": sum(c["cleanable_bytes"] for c in categories),
        "cleanable_keys": list(CLEANABLE_KEYS),
        "scanned_at": datetime.now().isoformat(),
    }


def run_cleanup(keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """Seçilen kategorileri temizler (varsayılan: tüm temizlenebilir kategoriler).

    Her kategori için önce/sonra ölçüm yapılır → raporlanan `freed_bytes` gerçek kazançtır.
    Whitelist dışı key sessizce atlanmaz — çağıran doğrulamalıdır (router 400 döner).
    """
    selected = [k for k in (keys or CLEANABLE_KEYS) if k in CLEANABLE_KEYS]

    free_before = shutil.disk_usage("/").free
    results = []
    for key in selected:
        before = _measure(key)["size"]
        _clean(key)
        after = _measure(key)["size"]
        freed = max(0, before - after)
        results.append({"key": key, "freed_bytes": freed, "size_after_bytes": after})
        logger.info("Disk temizliği — %s: %.1f MB serbest kaldı", key, freed / 1024 / 1024)

    free_after = shutil.disk_usage("/").free
    return {
        "cleaned_keys": selected,
        "results": results,
        "freed_bytes": sum(r["freed_bytes"] for r in results),
        "disk_free_before_bytes": free_before,
        "disk_free_after_bytes": free_after,
        "filesystem": _filesystem(),
    }
