#!/usr/bin/env bash
# Off-site (S3) yedek yardımcıları — db-backup.sh · db-restore.sh ·
# enable-offsite-backup.sh · provision-offsite-backup.sh ORTAK kullanır.
#
# Neden ayrı dosya: "farklı bölge" kuralı denetim DR-002'nin KAPANIŞ KRİTERİDİR
# ("farklı bölgedeki S3"). Kural üç ayrı script'e kopyalanırsa biri güncellenmeden
# kalır ve sessizce aynı-bölge bucket kabul edilir → bölge-geneli arıza her iki
# kopyayı birden götürür. Tek kaynak + testle sabitlenmiş (test_backup_offsite.py).
#
# Bu dosya doğrudan ÇALIŞTIRILMAZ, `source` edilir.

# ─── s3:// URI ayrıştırma ────────────────────────────────────────────────────

# s3://bucket/prefix/alt  →  bucket
offsite_bucket_of() {
    local uri="${1:?s3 uri gerekli}"
    uri="${uri#s3://}"
    printf '%s' "${uri%%/*}"
}

# s3://bucket/prefix/alt  →  prefix/alt   (prefix yoksa boş)
offsite_prefix_of() {
    local uri="${1:?s3 uri gerekli}"
    uri="${uri#s3://}"
    local rest="${uri#*/}"
    [ "$rest" = "$uri" ] && rest=""      # '/' yoksa prefix yok
    printf '%s' "${rest%/}"
}

# ─── Bölge tespiti ───────────────────────────────────────────────────────────

# Bu makinenin AWS bölgesi. EC2'de IMDSv2'den, dışarıda AWS_REGION/AWS_DEFAULT_REGION'dan.
# Tespit edilemezse BOŞ döner (hata değil — EC2 dışından da çalıştırılabilmeli).
offsite_instance_region() {
    if [ -n "${SPRENSES_INSTANCE_REGION:-}" ]; then      # test/override
        printf '%s' "$SPRENSES_INSTANCE_REGION"; return 0
    fi
    local token region
    token="$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
             -H "X-aws-ec2-metadata-token-ttl-seconds: 60" --max-time 2 2>/dev/null || true)"
    if [ -n "$token" ]; then
        region="$(curl -s --max-time 2 -H "X-aws-ec2-metadata-token: $token" \
                  http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null || true)"
        # IMDS kapalıysa 404 HTML döner — bölge adı asla boşluk/'<' içermez
        case "$region" in *'<'*|*' '*|"") region="" ;; esac
        [ -n "$region" ] && { printf '%s' "$region"; return 0; }
    fi
    printf '%s' "${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
}

# Bucket'ın bölgesi. us-east-1 tarihsel olarak "None"/boş döner → normalize edilir.
offsite_bucket_region() {
    local bucket="${1:?bucket gerekli}" loc
    loc="$(aws s3api get-bucket-location --bucket "$bucket" --output text 2>/dev/null || true)"
    case "$loc" in None|null|"") loc="us-east-1" ;; esac
    printf '%s' "$loc"
}

# ─── Kapanış kriteri bekçisi: FARKLI bölge ───────────────────────────────────
# 0 = kabul edilebilir, 1 = reddet. Reddetme gerekçesi stderr'e yazılır.
#
# Aynı bölgedeki bucket "yerel-only"den iyidir ama denetimin istediği coğrafi
# ayrımı SAĞLAMAZ: eu-north-1 bölgesel arızası hem EC2'yi hem bucket'ı götürür.
# Bilinçli kabul için SPRENSES_ALLOW_SAME_REGION=1 (kayda geçer, sessiz değil).
offsite_assert_cross_region() {
    local uri="${1:?s3 uri gerekli}" bucket inst buck
    bucket="$(offsite_bucket_of "$uri")"
    inst="$(offsite_instance_region)"
    buck="$(offsite_bucket_region "$bucket")"

    if [ -z "$inst" ]; then
        echo "UYARI: bu makinenin bölgesi tespit edilemedi — farklı-bölge kuralı doğrulanamadı (bucket: $buck)" >&2
        return 0
    fi
    if [ "$inst" = "$buck" ]; then
        if [ "${SPRENSES_ALLOW_SAME_REGION:-0}" = "1" ]; then
            echo "UYARI: bucket sunucuyla AYNI bölgede ($buck) — SPRENSES_ALLOW_SAME_REGION=1 ile bilerek kabul edildi" >&2
            return 0
        fi
        echo "HATA: bucket sunucuyla AYNI bölgede ($buck). Denetim DR-002 FARKLI bölge ister —" >&2
        echo "      bölgesel arıza yoksa iki kopya da kaybolur. Farklı bölgede bucket açın" >&2
        echo "      (scripts/provision-offsite-backup.sh) veya bilerek kabul için SPRENSES_ALLOW_SAME_REGION=1." >&2
        return 1
    fi
    echo "farklı-bölge OK: sunucu=$inst bucket=$buck"
    return 0
}

# ─── En son off-site nesnesini bul ───────────────────────────────────────────
# Nesne adları sprenses-YYYYMMDD-HHMMSS.dump → sözlüksel sıralama = zaman sıralaması
# (mtime'a güvenilmez: S3 kopyalama/replikasyon LastModified'ı değiştirir).
offsite_latest_key() {
    local uri="${1:?s3 uri gerekli}" pattern="${2:-sprenses-}"
    aws s3 ls "${uri%/}/" 2>/dev/null \
        | awk '{print $NF}' \
        | grep -E "^${pattern}.*\.dump$" \
        | sort \
        | tail -1
}
