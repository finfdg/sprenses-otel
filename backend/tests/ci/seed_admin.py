"""CI/test veritabanı için admin kullanıcısı seed script'i.

Şema (01_schema.sql) ve referans veri (02_seed.sql) yüklendikten sonra çalıştırılır.
Migration'lar admin KULLANICISINI oluşturmaz (prod'da manuel kayıtlıdır), bu yüzden
test/CI ortamında admin'i deterministik biçimde burada üretiyoruz.

Idempotent: admin zaten varsa hiçbir şey yapmaz.

Kullanım:
    DATABASE_URL=postgresql://...sprenses_test python tests/ci/seed_admin.py

Şifre TEST_ADMIN_PASSWORD ortam değişkeninden okunur (varsayılan: admin123).
"""

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.role import Role
from app.models.user import User
from app.utils.security import hash_password

ADMIN_USERNAME = "admin"
ADMIN_EMAIL = "admin@sprenses.com"


def seed_admin() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        sys.exit("[seed_admin] DATABASE_URL gerekli")
    if "_test" not in db_url and not os.environ.get("ALLOW_PROD_DB_TESTS"):
        sys.exit(
            "[seed_admin] DATABASE_URL test DB'sine işaret etmeli (adı '_test' içermeli). "
            "Prod DB'ye admin seed edilmesini önlemek için durduruldu."
        )

    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        existing = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if existing:
            print(f"[seed_admin] '{ADMIN_USERNAME}' zaten var (id={existing.id}) — atlanıyor.")
            return

        admin_role = db.query(Role).filter(Role.name == "Admin").first()
        if not admin_role:
            admin_role = db.query(Role).order_by(Role.id).first()
        if not admin_role:
            sys.exit("[seed_admin] Admin rolü bulunamadı — önce 02_seed.sql yüklenmeli.")

        password = os.environ.get("TEST_ADMIN_PASSWORD", "admin123")
        admin = User(
            username=ADMIN_USERNAME,
            email=ADMIN_EMAIL,
            hashed_password=hash_password(password),
            first_name="Sistem",
            last_name="Yönetici",
            role_id=admin_role.id,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        print(f"[seed_admin] admin oluşturuldu (id={admin.id}, role_id={admin_role.id}).")
    finally:
        db.close()


if __name__ == "__main__":
    seed_admin()
