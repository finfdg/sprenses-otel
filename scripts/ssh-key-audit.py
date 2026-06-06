#!/usr/bin/env python3
"""SSH authorized_keys sertlestirme denetimi.

Tunel/forward anahtarlari (options icinde permitlisten / permitopen / port-forwarding
gecen) ZORUNLU olarak hem `command=` hem `permitopen=` tasimalidir. Aksi halde:
  - `command=` yok  -> `restrict` TEK BASINA yetmez (no-pty etkilesimli kabugu kapatir
    ama komut calistirmayi engellemez): `ssh -i key host 'cat .env'` ile sunucudaki TUM
    dosyalar (sirlar dahil) okunabilir.
  - `permitopen=` yok -> `-L`/`-D` ile ic servislere (DB 5432, IMDS 169.254.169.254 ->
    AWS IAM kimlik bilgileri) pivot yapilabilir.

Bu betik forward anahtarlarini denetler; `--fix` ile eksik guvenlik opsiyonlarini
ekler. Anahtar VERISINE asla dokunmaz — yalnizca anahtar tipinden ONCEKI options
on-ekini degistirir; yazma atomiktir ve once yedek alir. Tam-erisimli (opsiyon-suz)
admin anahtarlari otomatik DUZELTILMEZ, yalnizca UYARI olarak raporlanir.

Modlar:
  (varsayilan)  Denetim — ihlalleri raporla; ihlal varsa exit 1
  --fix         Sertlestir — forward anahtarlarina eksik command=/permitopen ekle
  --quiet       Yalniz ozet + ihlal/duzeltme satirlari (cron/systemd icin)

Kullanim:
  python3 ssh-key-audit.py
  python3 ssh-key-audit.py --fix
  python3 ssh-key-audit.py /path/to/authorized_keys --fix --quiet
"""
import os
import re
import sys
import time

# --- Sertlestirme degerleri --------------------------------------------------
FORCED_COMMAND = 'command="echo tunnel-only-no-shell"'   # keyfi komut/kabuk calismaz
DEAD_PORT_PERMITOPEN = 'permitopen="127.0.0.1:1"'        # -L/-D olu porta -> pivot yok

# anahtar tipi + base64 govde (ssh govdesi daima "AAAA" ile baslar -> guvenilir sinir)
KEYTYPE_RE = re.compile(
    r'(?:^|\s)((?:ssh-(?:rsa|dss|ed25519))|(?:ecdsa-sha2-\S+)|(?:sk-[A-Za-z0-9.@_-]+))\s+AAAA'
)


# --- Ayristirma yardimcilari -------------------------------------------------
def split_options(line):
    """Satiri (options, rest) olarak ayir. Anahtar satiri degilse None.

    rest = anahtar tipinden itibaren satirin geri kalani (tip + govde + yorum),
    bayt-bayt korunur. options bos olabilir (opsiyon-suz tam-erisim anahtari).
    """
    m = KEYTYPE_RE.search(line)
    if not m:
        return None
    return line[:m.start(1)].strip(), line[m.start(1):]


def has_flag(opts, name):
    """Bayrak opsiyonu (restrict, port-forwarding) kelime sinirlariyla ara.

    `no-port-forwarding` gibi olumsuzlari ELEMEK icin onunde/ardinda harf/tire olmamali.
    """
    return re.search(r'(?<![\w-])' + re.escape(name) + r'(?![\w-])', opts) is not None


def has_valued(opts, name):
    """Degerli opsiyon: name="..." var mi."""
    return (name + '="') in opts


def is_forwarding_key(opts):
    return (
        has_valued(opts, 'permitlisten')
        or has_valued(opts, 'permitopen')
        or has_flag(opts, 'port-forwarding')
    )


def key_label(rest):
    """rest = 'ssh-ed25519 AAAA... yorum' -> yorum (yoksa anahtar tipi)."""
    toks = rest.split()
    if len(toks) >= 3:
        return " ".join(toks[2:])
    return toks[0] if toks else "?"


def _prune_backups(path, keep=10):
    """En yeni `keep` denetim yedegini birak, gerisini sil (sinirsiz birikme olmasin)."""
    d = os.path.dirname(path) or "."
    base = os.path.basename(path) + ".bak.audit."
    try:
        baks = sorted(n for n in os.listdir(d) if n.startswith(base))
    except OSError:
        return
    for name in baks[:-keep] if len(baks) > keep else []:
        try:
            os.remove(os.path.join(d, name))
        except OSError:
            pass


# --- Sertlestirme ------------------------------------------------------------
def harden_options(opts):
    """Forward anahtari icin eksik guvenlik opsiyonlarini ekle; mevcutlari koru.

    Donus: (yeni_opts, eklenenler[]). Anahtar tipi/govdesi cagiran tarafta korunur.
    """
    added = []
    if not has_flag(opts, 'restrict'):
        opts = ('restrict,' + opts) if opts else 'restrict'
        added.append('restrict')
        # restrict forwarding'i kapatir -> -R/-L icin geri ac
        if not has_flag(opts, 'port-forwarding'):
            opts = opts + ',port-forwarding'
            added.append('port-forwarding')
    if not has_valued(opts, 'command'):
        opts = opts + ',' + FORCED_COMMAND
        added.append('command=')
    if not has_valued(opts, 'permitopen'):
        opts = opts + ',' + DEAD_PORT_PERMITOPEN
        added.append('permitopen=')
    return opts, added


# --- Ana akis ----------------------------------------------------------------
def main():
    argv = sys.argv[1:]
    fix = '--fix' in argv
    quiet = '--quiet' in argv
    positional = [a for a in argv if not a.startswith('--')]
    path = positional[0] if positional else os.path.expanduser('~/.ssh/authorized_keys')

    if not os.path.isfile(path):
        print(f"[HATA] Dosya yok: {path}", file=sys.stderr)
        return 2

    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        original_lines = f.read().splitlines()

    out_lines = []
    violations = []   # (label, eksikler)
    warnings = []     # (label, sebep)
    fixed = []        # (label, eklenenler)
    ok_count = 0

    for line in original_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        parsed = split_options(line)
        if parsed is None:
            out_lines.append(line)            # anahtar degil -> dokunma
            continue
        opts, rest = parsed
        label = key_label(rest)

        if not opts:
            # opsiyon-suz = tam-erisimli kabuk anahtari (admin). Otomatik duzeltme YOK.
            warnings.append((label, "opsiyon-suz tam-erisim anahtari (kabuk acik) — gozden gecir"))
            out_lines.append(line)
            continue

        if not is_forwarding_key(opts):
            # forward degil. restrict var ama command yoksa komut calistirilabilir -> uyar.
            if (has_flag(opts, 'restrict') or has_flag(opts, 'no-pty')) and not has_valued(opts, 'command'):
                warnings.append((label, "restrict var ama command= yok — komut calistirilabilir"))
            else:
                ok_count += 1
            out_lines.append(line)
            continue

        # --- forward anahtari: command= VE permitopen= zorunlu ---
        missing = []
        if not has_valued(opts, 'command'):
            missing.append('command=')
        if not has_valued(opts, 'permitopen'):
            missing.append('permitopen=')

        if not missing:
            ok_count += 1
            out_lines.append(line)
            continue

        # ihlal
        if fix:
            new_opts, added = harden_options(opts)
            new_line = new_opts + " " + rest
            # guvenlik: yeni satir hala gecerli bir anahtar satiri mi + govde ayni mi
            check = split_options(new_line)
            if check is None or check[1] != rest:
                violations.append((label, missing))      # duzeltilemedi -> ihlal kalir
                warnings.append((label, "otomatik sertlestirme dogrulamasi basarisiz — elle duzelt"))
                out_lines.append(line)
            else:
                fixed.append((label, added))
                out_lines.append(new_line)
        else:
            violations.append((label, missing))
            out_lines.append(line)

    # --- yazma (yalniz fix modunda ve degisiklik varsa) ---
    changed = fixed and (out_lines != original_lines)
    if fix and changed:
        ts = int(time.time())
        backup = f"{path}.bak.audit.{ts}"
        try:
            with open(backup, "w", encoding="utf-8", errors="surrogateescape") as f:
                f.write("\n".join(original_lines) + "\n")
            os.chmod(backup, 0o600)
            tmp = f"{path}.tmp.{ts}"
            with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as f:
                f.write("\n".join(out_lines) + "\n")
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)             # atomik
            _prune_backups(path, keep=10)
        except OSError as e:
            print(f"[HATA] Yazma basarisiz: {e}", file=sys.stderr)
            return 2

    # --- rapor ---
    def emit(msg):
        print(msg)

    if not quiet:
        emit(f"== SSH anahtar denetimi: {path} ==")
    for label, added in fixed:
        emit(f"[DUZELTILDI] {label}  +{','.join(added)}")
    for label, missing in violations:
        emit(f"[IHLAL] {label}  eksik: {','.join(missing)}")
    if not quiet:
        for label, reason in warnings:
            emit(f"[UYARI] {label}  {reason}")
    elif warnings and not (fixed or violations):
        pass  # quiet + sorun yok + sadece uyari -> sessiz kal (heartbeat gurultusu yok)

    total_keys = ok_count + len(violations) + len(fixed) + len(warnings)
    summary = (f"ozet: {total_keys} anahtar | OK={ok_count} "
               f"duzeltildi={len(fixed)} ihlal={len(violations)} uyari={len(warnings)}")
    if not quiet or fixed or violations:
        emit(summary)

    # exit kodu: cozulmemis ihlal varsa 1
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
