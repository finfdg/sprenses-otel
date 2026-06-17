---
description: Backend ve/veya frontend'i projenin zorunlu deploy akışıyla canlıya al + sağlık doğrula
argument-hint: "[backend|frontend|all]"
---
Hedef: `$ARGUMENTS` (boşsa **all**).

**Projenin ZORUNLU deploy akışı (CLAUDE.md):**
- **Backend:** sadece servis restart yeter (uvicorn yeni `.py` dosyalarını yükler).
- **Frontend:** SvelteKit production'da (`node build`) çalışır → kaynak değişikliği **build alınmadan yansımaz**. Tek başına restart YETMEZ; `deploy-frontend.sh` build + restart zincirini çalıştırır.

### Backend (hedef `backend` veya `all`)
```bash
sudo systemctl restart sprenses-api.service
sleep 3 && echo "durum: $(systemctl is-active sprenses-api.service)"
curl -s -o /dev/null -w "api health: HTTP %{http_code}\n" http://127.0.0.1:8001/api/health
```
HTTP 200 değilse: `sudo journalctl -u sprenses-api.service -n 30 --no-pager` ile incele.

### Frontend (hedef `frontend` veya `all`)
```bash
/home/ec2-user/otel/scripts/deploy-frontend.sh
sleep 2 && curl -s -o /dev/null -w "frontend: HTTP %{http_code}\n" http://127.0.0.1:3000/
```
(Script `npm run build` + `systemctl restart` + aktiflik kontrolü yapar; build hata verirse durur.)

**Notlar:**
- Ayrı bir commit gerekmiyor — Stop-hook her tur sonunda otomatik commit + GitHub push yapıyor.
- Sonucu net raporla: servis aktif mi, health kodu kaç. Bir şey 200 değilse vurgula, journalctl çıktısını incele.
