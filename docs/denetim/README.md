# Denetim Raporları — Dondurulmuş Kayıtlar

Bu klasördeki raporlar **tarihli anlık görüntülerdir**: içerikleri ve atıf yaptıkları dosya yolları,
raporun yazıldığı günkü kod düzenini yansıtır ve **sonradan yeniden yazılmaz** (kanıt zinciri ve
`audit_reports.doc_path` DB kaydı bu dosyalara bağlıdır; klasör taşınmaz, dosyalar yeniden adlandırılmaz).

**2026-09-02 yeniden yapılandırması** kod tabanının fiziksel düzenini değiştirdi. Bu raporlarda geçen
eski yollar için dönüşüm haritası: [`docs/proje-yapisi.md`](../proje-yapisi.md) (güncel ağaç) ve
[`docs/denetim/2026-09-02-yeniden-yapilandirma.md`](2026-09-02-yeniden-yapilandirma.md) (eski → yeni yol tablosu).
Sık karşılaşılanlar:

| Raporlardaki eski yol | Güncel yol |
|---|---|
| `backend/app/utils/{matching_service,finance_event_service,auto_tagger,vendor_fifo,sync_vendor_fifo,recurring_vendor_sync,entry_generator,kmh_calculator,occupancy,fx_rates}.py` | `backend/app/services/<aynı ad>.py` |
| `backend/app/utils/approval_{check,service,executor}.py` | `backend/app/approval/<aynı ad>.py` |
| `backend/app/utils/{sedna_client,tcmb,garanti_api,qnb_api,yapikredi_api,vakifbank_client,mail,amadeus_client}.py` | `backend/app/integrations/<aynı ad>.py` |
| `backend/app/utils/{bank_parser,bank_parse_helpers,cc_statement_parser,check_parser,reservation_parser,vendor_parser}.py` | `backend/app/parsers/<aynı ad>.py` |
| `backend/app/utils/{finance_broadcast,sales_broadcast,notification,push}.py` | `backend/app/realtime/<aynı ad>.py` |
| `backend/app/routers/{system_users,system_roles,system_modules,system_server,system_backup,system_docs,system_denetim,audit,error_logs}.py` | `backend/app/routers/system/{users,roles,modules,server,backup,docs,denetim,audit_logs,error_logs}.py` |
| `backend/app/routers/{auth,health,ws,push,notifications,files,internal}.py` | `backend/app/routers/core/<aynı ad>.py` |
| `backend/app/routers/ai_assistant.py` · `scheduled_base.py` · `shifts.py` · `shift_schedule.py` | `routers/ai/assistant.py` · `routers/common/scheduled_factory.py` · `routers/hr/{shifts,shift_schedule}.py` |
| `backend/app/routers/finance/{bank_statement_import,check_import}.py` | `backend/app/services/{bank_statement_import_service,check_import_service}.py` |
| `frontend/src/lib/components/<Primitive>.svelte` (Button, Modal, …) | `frontend/src/lib/components/ui/<Primitive>.svelte` |
| `frontend/src/lib/components/{Sidebar,Topbar,NotificationBell,ToastContainer}.svelte` | `frontend/src/lib/components/layout/…` |
| `frontend/src/lib/components/{CashFlowTAccount,RunwayChart,OverdueList,HeldList,AiDigestCard}.svelte` | `frontend/src/lib/components/dashboard/…` |
| `frontend/src/lib/stores/{cashflow,runway}.svelte.ts` · `lib/utils/messaging-*.svelte.ts` | `lib/stores/cashflow/{cache,runway}.svelte.ts` · `lib/stores/messaging/*.ts` |
