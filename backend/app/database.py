from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=25,        # 25 eş zamanlı kullanıcı için yeterli
    max_overflow=10,     # Ani yük artışlarında +10 ek bağlantı
    pool_recycle=900,    # 15 dk sonra eski bağlantıları yenile (eski: 30 dk)
    pool_timeout=10,     # 10 sn sonra kuyrukta bekleyeni hata döndür
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def set_timezone(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("SET timezone = 'Europe/Istanbul'")
    cursor.close()


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
