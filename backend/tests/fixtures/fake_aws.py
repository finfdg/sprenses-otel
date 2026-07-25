#!/usr/bin/env python3
"""Sahte `aws` CLI — off-site (S3) yedek yolunu GERÇEK AWS olmadan uçtan uca koşturur.

NEDEN: denetim DR-002'nin kapanış kriteri "S3'e yükleniyor + S3'ten geri yüklendi".
Gerçek AWS kimliği CI'da ve geliştirme makinesinde yok; olmadığı için de bu kod yolu
bugüne dek HİÇ test edilmedi — `enable-offsite-backup.sh` yalnız elle, bir kez
çalıştırılacak varsayımıyla yazılmıştı. Bu stub `s3://` URI'lerini yerel bir dizine
eşleyerek db-backup.sh / db-restore.sh'ın off-site dallarını gerçek dosya trafiğiyle
sınar: yükleme, aynalama, listeleme, indirme ve İÇERİK EŞİTLİĞİ.

Desteklenen alt komutlar (script'lerin kullandıkları kadarı):
    aws s3 cp <kaynak> <hedef> [--sse ...]
    aws s3 sync <dizin> <hedef> [--sse ...] [--only-show-errors]
    aws s3 ls <s3-uri> [--recursive]
    aws s3 rm <s3-uri>
    aws sts get-caller-identity
    aws s3api get-bucket-location --bucket <b> --output text

Ortam:
    FAKE_S3_ROOT      — s3:// içeriğinin tutulacağı yerel kök dizin (zorunlu)
    FAKE_S3_REGION    — get-bucket-location yanıtı (varsayılan eu-west-1)
    FAKE_S3_FAIL      — bu alt dize hedef URI'de geçerse komut BAŞARISIZ olur
                        (sessiz-hata regresyonu için: yükleme çökünce iş de çökmeli)
    FAKE_S3_LOCATION_DENIED=1 — get-bucket-location AccessDenied verir. Canlıda
                        yaşanan IAM hatasını taklit eder: bölge okunamayınca
                        farklı-bölge bekçisi SESSİZCE geçmemeli, REDDETMELİ.
"""

import os
import shutil
import sys

ROOT = os.environ.get("FAKE_S3_ROOT")
REGION = os.environ.get("FAKE_S3_REGION", "eu-west-1")
FAIL_ON = os.environ.get("FAKE_S3_FAIL", "")


def local_path(uri):
    """s3://bucket/key → <ROOT>/bucket/key"""
    return os.path.join(ROOT, uri[len("s3://"):])


def is_s3(arg):
    return arg.startswith("s3://")


def fail_if_marked(*uris):
    if FAIL_ON and any(FAIL_ON in u for u in uris):
        sys.stderr.write("fake-aws: yükleme bilerek başarısız (FAKE_S3_FAIL)\n")
        sys.exit(1)


def positionals(args):
    """Bayrakları ve bayrak değerlerini ele — geriye yalnız kaynak/hedef kalsın."""
    VALUED = {"--sse", "--storage-class", "--acl"}   # değer alan bayraklar
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a.startswith("--"):
            skip = a in VALUED
            continue
        out.append(a)
    return out


def cmd_cp(args):
    args = positionals(args)
    src, dst = args[0], args[1]
    fail_if_marked(src, dst)
    if is_s3(dst):
        target = local_path(dst)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(src, target)
    else:
        source = local_path(src)
        if not os.path.isfile(source):
            sys.stderr.write("fake-aws: nesne yok: %s\n" % src)
            return 1
        shutil.copy2(source, dst)
    return 0


def cmd_sync(args):
    args = positionals(args)
    src, dst = args[0], args[1]
    fail_if_marked(src, dst)
    # Yalnız yerel dizin → s3 yönü kullanılıyor (yedek akışında tersi yok)
    target = local_path(dst)
    for dirpath, _dirs, files in os.walk(src):
        for name in files:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, src)
            out = os.path.join(target, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            # `aws s3 sync` değişmeyeni atlar — boyut+mtime karşılaştırması yeterli taklit
            if os.path.exists(out) and os.path.getsize(out) == os.path.getsize(full):
                continue
            shutil.copy2(full, out)
    return 0


def cmd_ls(args):
    recursive = "--recursive" in args
    uri = [a for a in args if is_s3(a)][0]
    base = local_path(uri)
    if recursive:
        prefix = uri[len("s3://"):]
        for dirpath, _dirs, files in os.walk(base):
            for name in sorted(files):
                rel = os.path.relpath(os.path.join(dirpath, name), base)
                print("2026-07-25 00:00:00       1024 %s/%s" % (prefix.rstrip("/"), rel))
        return 0
    if not os.path.isdir(base):
        return 1
    for name in sorted(os.listdir(base)):
        full = os.path.join(base, name)
        if os.path.isdir(full):
            print("                           PRE %s/" % name)
        else:
            print("2026-07-25 00:00:00 %10d %s" % (os.path.getsize(full), name))
    return 0


def cmd_rm(args):
    target = local_path([a for a in positionals(args) if is_s3(a)][0])
    if os.path.isfile(target):
        os.remove(target)
    return 0


def main():
    argv = sys.argv[1:]
    if not argv:
        return 1
    if argv[0] == "sts":
        print("arn:aws:iam::000000000000:role/FakeTestRole")
        return 0
    if argv[0] == "s3api":
        if "get-bucket-location" in argv:
            if os.environ.get("FAKE_S3_LOCATION_DENIED") == "1":
                sys.stderr.write(
                    "An error occurred (AccessDenied) when calling the "
                    "GetBucketLocation operation\n")
                return 254
            print(REGION)
            return 0
        return 0
    if argv[0] == "s3":
        if not ROOT:
            sys.stderr.write("fake-aws: FAKE_S3_ROOT ayarlanmamış\n")
            return 2
        sub = argv[1]
        # Handler'lara HAM argümanlar verilir: `ls` bayrakları da görmeli
        # (--recursive burada elenirse özyinelemeli listeleme sessizce düz listelemeye
        # düşer ve "hiç dosya yok" gibi görünür — bu tuzağa bir kez düşüldü).
        return {"cp": cmd_cp, "sync": cmd_sync, "ls": cmd_ls, "rm": cmd_rm}[sub](argv[2:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
