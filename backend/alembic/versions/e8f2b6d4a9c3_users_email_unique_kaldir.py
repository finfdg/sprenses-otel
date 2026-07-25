"""users.email UNIQUE kısıtını kaldır — ortak/rol posta kutusuna izin ver

Neden: alarm ve bildirim e-postalarının ortak bir kutuya (ör. finans@…) düşmesi için
aynı adres birden çok hesapta kullanılabilmeli (kullanıcı kararı, 2026-07-25).

Kaldırmak güvenli:
  - Giriş `username` ile yapılır — e-posta ile kimlik doğrulama YOK.
  - E-posta teyit token'ı `user_id`'ye bağlıdır; `auth.verify_email` kullanıcıyı
    `User.id == payload["user_id"]` ile bulur, e-postayla ARAMAZ.
  - E-postayla sorgu yapan tek yer `system_users.py`'deki "zaten kayıtlı" kontrolleridir
    (aynı commit'te gevşetildi).
Index arama/performans için KORUNUR — yalnız benzersizlik düşer.

Revision ID: e8f2b6d4a9c3
Revises: c9e1a3b5d7f2
Create Date: 2026-07-25
"""
from alembic import op

revision = "e8f2b6d4a9c3"
down_revision = "c9e1a3b5d7f2"
branch_labels = None
depends_on = None


def upgrade():
    # UNIQUE index → normal index (aynı ad korunur)
    op.drop_index("ix_users_email", table_name="users")
    op.create_index("ix_users_email", "users", ["email"], unique=False)


def downgrade():
    # DİKKAT: geri alma, mükerrer e-posta varsa BAŞARISIZ olur (beklenen davranış —
    # sessizce veri silmektense migration'ın patlaması doğrudur). Önce mükerrerleri
    # tekilleştirin: SELECT email, count(*) FROM users GROUP BY 1 HAVING count(*) > 1;
    op.drop_index("ix_users_email", table_name="users")
    op.create_index("ix_users_email", "users", ["email"], unique=True)
