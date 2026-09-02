"""Paketler-arası paylaşılan HTTP fabrikaları (services DEĞİL: APIRouter/Depends kullanır).

`scheduled_factory.create_scheduled_router(...)` — accounting/ ve hr/ paketlerinin 7 planlı
gelir/gider modülünü üretir. Router paketleri buradan import edebilir; bu paket router paketlerinden
import ETMEZ.
"""
