#!/usr/bin/env bash
# Off-site (S3) yedek altyapısını AWS'de PROVİZYONLA — denetim DR-002.
#
# NEDEN BU SCRIPT VAR: DR-002 iki denetim boyunca (v3 → v4) açık kaldı çünkü kapanışı
# "runbook'taki 12 komutu elle çalıştır" adımına bağlıydı ve o adım hiç yapılmadı.
# Elle uygulanan runbook = yapılmayan runbook. Burada tek komuta indiriliyor ve
# idempotent: yarıda kalırsa yeniden çalıştırılabilir.
#
# KULLANIM (AWS admin kimliğiyle, BİR KEZ):
#     scripts/provision-offsite-backup.sh <benzersiz-bucket-adı> [hedef-bölge] [instance-id]
#
#   ör (sunucuda):  scripts/provision-offsite-backup.sh sprenses-dr-2026 eu-west-1
#   ör (dizüstünde): scripts/provision-offsite-backup.sh sprenses-dr-2026 eu-west-1 i-0cf25a70e992feaa5
#
# İKİ YOL — ikisi de aynı sonucu verir:
#
#   A) SUNUCUDA (aws CLI zaten kurulu):
#        aws configure          # AWS hesabınızdan admin access key
#        scripts/provision-offsite-backup.sh sprenses-dr-2026 eu-west-1
#        rm -rf ~/.aws          # !!! admin anahtarını sunucuda BIRAKMAYIN
#
#   B) KENDİ BİLGİSAYARINIZDA (admin anahtarı üretim sunucusuna hiç girmez — tercih edilir):
#        brew install awscli && aws configure
#        scripts/provision-offsite-backup.sh sprenses-dr-2026 eu-west-1 <instance-id>
#      Instance-id verilirse IAM profili EC2'ye buradan bağlanır; verilmezse ve script
#      EC2 dışındaysa bağlama komutu ekrana yazılır (elle çalıştırılır).
#
# Her iki yolda da sunucu bundan sonra IAM role ile çalışır — anahtar dosyası gerekmez.
#
# NE KURAR (hepsi idempotent):
#   1. S3 bucket — EC2'den FARKLI bölgede (bölgesel arıza iki kopyayı birden götürmesin)
#   2. Versioning         → üzerine yazma/silme geri alınabilir (ransomware ikinci katmanı)
#   3. SSE-AES256         → durağan şifreleme (finans + KVKK verisi)
#   4. Public access block → dört bayrak da true (yanlışlıkla herkese açılamaz)
#   5. Bucket policy      → TLS olmayan istekleri reddet (aws:SecureTransport=false → Deny)
#   6. Lifecycle          → eski sürümler 90 gün sonra silinir (maliyet kontrolü)
#   7. IAM policy + role + instance profile → EC2'ye ekler (MİNİMAL: yalnız bu prefix)
#
# BİLEREK YAPILMAYAN: Object Lock (bucket oluşturulurken açılmalı ve GERİ ALINAMAZ;
#   yanlış kurulmuş bir compliance-mode kilidi faturayı yıllarca kilitler → kullanıcı kararı).
set -euo pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
# shellcheck source=scripts/_offsite-lib.sh
. "$SCRIPT_DIR/_offsite-lib.sh"

BUCKET="${1:?Kullanım: $0 <benzersiz-bucket-adı> [hedef-bölge]}"
PREFIX="${SPRENSES_BACKUP_PREFIX:-sprenses}"
ROLE_NAME="${SPRENSES_IAM_ROLE:-SprensesBackupRole}"
POLICY_NAME="${SPRENSES_IAM_POLICY:-SprensesBackupOffsite}"

INSTANCE_REGION="$(offsite_instance_region)"
[ -n "$INSTANCE_REGION" ] || INSTANCE_REGION="eu-north-1"

# Hedef bölge: verilmediyse sunucu bölgesinden FARKLI bir varsayılan seç.
TARGET_REGION="${2:-}"
if [ -z "$TARGET_REGION" ]; then
    case "$INSTANCE_REGION" in
        eu-west-1) TARGET_REGION="eu-central-1" ;;
        *)         TARGET_REGION="eu-west-1" ;;
    esac
fi
if [ "$TARGET_REGION" = "$INSTANCE_REGION" ] && [ "${SPRENSES_ALLOW_SAME_REGION:-0}" != "1" ]; then
    echo "HATA: hedef bölge sunucuyla aynı ($TARGET_REGION). DR-002 FARKLI bölge ister." >&2
    exit 1
fi

echo "Sunucu bölgesi : $INSTANCE_REGION"
echo "Hedef bölge    : $TARGET_REGION  (farklı ✔)"
echo "Bucket         : $BUCKET"
echo "Prefix         : $PREFIX"
echo ""

# ─── 0) Kimlik ───────────────────────────────────────────────────────────────
echo "0) AWS kimliği doğrulanıyor..."
IDENTITY="$(aws sts get-caller-identity --output text --query 'Arn' 2>/dev/null || true)"
if [ -z "$IDENTITY" ]; then
    echo "HATA: AWS kimliği yok. 'aws configure' ile admin anahtarı girin (sonra 'rm -rf ~/.aws')." >&2
    exit 1
fi
ACCOUNT_ID="$(aws sts get-caller-identity --output text --query 'Account')"
echo "   $IDENTITY (hesap $ACCOUNT_ID)"

# ─── 1) Bucket ───────────────────────────────────────────────────────────────
echo "1) S3 bucket..."
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
    EXISTING_REGION="$(offsite_bucket_region "$BUCKET")"
    echo "   zaten var ($EXISTING_REGION)"
    if [ "$EXISTING_REGION" != "$TARGET_REGION" ]; then
        echo "   UYARI: mevcut bucket bölgesi ($EXISTING_REGION) istenen hedeften ($TARGET_REGION) farklı" >&2
        TARGET_REGION="$EXISTING_REGION"
    fi
else
    # us-east-1 LocationConstraint KABUL ETMEZ (API'nin tarihsel tuhaflığı) — ayrı çağrı
    if [ "$TARGET_REGION" = "us-east-1" ]; then
        aws s3api create-bucket --bucket "$BUCKET" --region us-east-1 >/dev/null
    else
        aws s3api create-bucket --bucket "$BUCKET" --region "$TARGET_REGION" \
            --create-bucket-configuration "LocationConstraint=$TARGET_REGION" >/dev/null
    fi
    echo "   oluşturuldu: $BUCKET ($TARGET_REGION)"
fi

# Farklı-bölge kuralını bucket GERÇEKTEN oluştuktan sonra bir kez daha doğrula
if [ "$(offsite_bucket_region "$BUCKET")" = "$INSTANCE_REGION" ] \
   && [ "${SPRENSES_ALLOW_SAME_REGION:-0}" != "1" ]; then
    echo "HATA: bucket sunucuyla aynı bölgede — DR-002 kapanmaz." >&2
    exit 1
fi

# ─── 2-6) Bucket sertleştirme ────────────────────────────────────────────────
echo "2) Versioning (silme/üzerine yazma geri alınabilir)..."
aws s3api put-bucket-versioning --bucket "$BUCKET" \
    --versioning-configuration Status=Enabled

echo "3) Şifreleme (SSE-AES256)..."
aws s3api put-bucket-encryption --bucket "$BUCKET" \
    --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'

echo "4) Public access block (dört bayrak)..."
aws s3api put-public-access-block --bucket "$BUCKET" \
    --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

echo "5) Bucket policy — TLS zorunlu..."
aws s3api put-bucket-policy --bucket "$BUCKET" --policy "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DenyInsecureTransport",
    "Effect": "Deny",
    "Principal": "*",
    "Action": "s3:*",
    "Resource": ["arn:aws:s3:::$BUCKET", "arn:aws:s3:::$BUCKET/*"],
    "Condition": {"Bool": {"aws:SecureTransport": "false"}}
  }]
}
EOF
)"

echo "6) Lifecycle — eski sürümler 90 gün sonra silinir..."
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" \
    --lifecycle-configuration "$(cat <<EOF
{
  "Rules": [{
    "ID": "sprenses-eski-surumleri-temizle",
    "Status": "Enabled",
    "Filter": {"Prefix": "$PREFIX/"},
    "NoncurrentVersionExpiration": {"NoncurrentDays": 90},
    "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
  }]
}
EOF
)"

# ─── 7) IAM: policy + role + instance profile ────────────────────────────────
# MİNİMAL yetki: yalnız bu bucket'ın bu prefix'i. Get+List RESTORE için ŞART —
# yalnız Put verilirse yükleme her gün yeşil görünür ama felaket anında geri
# dönülemez (db-restore.sh --offsite bunu tatbikatla yakalar).
#
# s3:GetBucketLocation NEDEN AYRI İFADEDE (2026-07-25 canlıda yakalandı): bu eylem
# `s3:prefix` bağlam anahtarını DESTEKLEMEZ. ListBucket ile aynı koşullu ifadeye
# konursa koşul asla sağlanmaz → AccessDenied → farklı-bölge bekçisi bucket bölgesini
# okuyamaz. İlk kurulumda tam bu oldu ve bekçi sessizce "us-east-1" varsayıp geçirdi.
echo "7) IAM policy + role..."
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"
POLICY_DOC="$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "Yaz", "Effect": "Allow", "Action": ["s3:PutObject"],
     "Resource": "arn:aws:s3:::$BUCKET/$PREFIX/*"},
    {"Sid": "OkuGeriYukle", "Effect": "Allow", "Action": ["s3:GetObject"],
     "Resource": "arn:aws:s3:::$BUCKET/$PREFIX/*"},
    {"Sid": "Listele", "Effect": "Allow", "Action": ["s3:ListBucket"],
     "Resource": "arn:aws:s3:::$BUCKET",
     "Condition": {"StringLike": {"s3:prefix": ["$PREFIX/*", "$PREFIX"]}}},
    {"Sid": "BolgeOku", "Effect": "Allow", "Action": ["s3:GetBucketLocation"],
     "Resource": "arn:aws:s3:::$BUCKET"}
  ]
}
EOF
)"

if aws iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
    # Yeni sürüm oluştur ve varsayılan yap (idempotent güncelleme)
    aws iam create-policy-version --policy-arn "$POLICY_ARN" \
        --policy-document "$POLICY_DOC" --set-as-default >/dev/null 2>&1 \
        || echo "   (policy sürümü güncellenemedi — 5 sürüm sınırı olabilir, mevcut korunuyor)"
    echo "   policy güncel: $POLICY_ARN"
else
    aws iam create-policy --policy-name "$POLICY_NAME" --policy-document "$POLICY_DOC" >/dev/null
    echo "   policy oluşturuldu: $POLICY_ARN"
fi

if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]
    }' >/dev/null
    echo "   role oluşturuldu: $ROLE_NAME"
else
    echo "   role zaten var: $ROLE_NAME"
fi
aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN"

if ! aws iam get-instance-profile --instance-profile-name "$ROLE_NAME" >/dev/null 2>&1; then
    aws iam create-instance-profile --instance-profile-name "$ROLE_NAME" >/dev/null
    aws iam add-role-to-instance-profile --instance-profile-name "$ROLE_NAME" --role-name "$ROLE_NAME"
    echo "   instance profile oluşturuldu — IAM yayılması için 10 sn bekleniyor..."
    sleep 10
fi

# ─── 8) Instance'a ekle ──────────────────────────────────────────────────────
# Instance-id: 3. argümandan (dizüstünden koşarken) ya da IMDS'ten (sunucuda koşarken).
INSTANCE_ID="${3:-${SPRENSES_EC2_INSTANCE_ID:-}}"
if [ -z "$INSTANCE_ID" ]; then
    TOKEN="$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
             -H "X-aws-ec2-metadata-token-ttl-seconds: 60" --max-time 2 2>/dev/null || true)"
    if [ -n "$TOKEN" ]; then
        INSTANCE_ID="$(curl -s --max-time 2 -H "X-aws-ec2-metadata-token: $TOKEN" \
                       http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || true)"
        case "$INSTANCE_ID" in *'<'*|*' '*) INSTANCE_ID="" ;; esac
    fi
fi

if [ -n "$INSTANCE_ID" ]; then
    echo "8) Instance profile EC2'ye ekleniyor ($INSTANCE_ID)..."
    if aws ec2 describe-iam-instance-profile-associations \
         --filters "Name=instance-id,Values=$INSTANCE_ID" \
         --query 'IamInstanceProfileAssociations[?State!=`disassociated`]' --output text \
         --region "$INSTANCE_REGION" | grep -q .; then
        echo "   instance'ta zaten bir IAM profile var — elle kontrol edin (üzerine yazılmadı)"
    else
        aws ec2 associate-iam-instance-profile --instance-id "$INSTANCE_ID" \
            --iam-instance-profile "Name=$ROLE_NAME" --region "$INSTANCE_REGION" >/dev/null
        echo "   eklendi. Kimliğin metadata'ya yayılması ~30 sn sürebilir."
    fi
else
    echo "8) EC2 dışında çalışıyor — instance profile'ı elle ekleyin:"
    echo "   aws ec2 associate-iam-instance-profile --instance-id <id> \\"
    echo "       --iam-instance-profile Name=$ROLE_NAME --region $INSTANCE_REGION"
fi

echo ""
echo "✅ Provizyon tamam. Şimdi SUNUCUDA (ec2-user, /home/ec2-user/otel):"
if [ -n "$INSTANCE_ID" ]; then
    echo "   # IAM kimliğinin metadata'ya yayılması için ~30 sn bekleyin"
fi
echo "   rm -rf ~/.aws                                   # bu makinede admin anahtarı bırakmayın"
echo "   scripts/enable-offsite-backup.sh s3://$BUCKET/$PREFIX"
echo "   scripts/db-restore.sh --offsite                 # DR tatbikatı (kapanış kanıtı)"
