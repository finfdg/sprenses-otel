"""Onay akışı motoru — router'lar ile domain servisleri ARASINDA duran orkestrasyon katmanı.

- `approval_check.check_approval()`  : mutasyon endpoint'lerinin onay kapısı (202 + payload saklama)
- `approval_service`                 : workflow eşleme + talep durum makinesi
- `approval_executor`                : onaylanan payload'ı ilgili domain servisiyle UYGULAYAN handler kaydı

Katman yönü: routers → approval → services → models. Bu paket router import ETMEZ.
2026-09-02 yeniden yapılandırmasında `app/utils/` altından buraya taşındı (utils = teknik yardımcı).
"""
