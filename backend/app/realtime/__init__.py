"""Gerçek-zaman yayılımı — WebSocket broadcast (finans/satış, debounce'lu), bildirim, web-push.

`app.websocket.manager` üzerinden yayın yapar; servisler after_commit sigortasıyla buradan çağırır
(`finance_event_service` → `finance_broadcast.notify_finance_update_sync`). Router import ETMEZ.
2026-09-02 yeniden yapılandırmasında `app/utils/` altından buraya taşındı.
"""
