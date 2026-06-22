# ERP / Otel Otomasyonu Teknik Denetim Soru Seti — v2

> **v1 → v2 değişikliği:** 2026-06-21 denetiminin sonuçlarına göre güncellendi. Kanıtlanmış 15 başlık korundu, **ayırt edici** (gerçek bulgu yakalayan) alt-sorularla güçlendirildi, denetimde açık kalan **5 yeni başlık** (16-20) eklendi, ek çıktılar genişletildi. `🆕` = v2'de eklenen/ayırt edici bulunan sorular.

---

## Yöntem (her denetimde uygula)

Her başlık için şu altı bölüm hazırlanır: **Mevcut Durum · Güçlü Yönler · Tespit Edilen Sorunlar · Risk Seviyesi · Çözüm Önerileri · Öncelik Sırası.** Ek olarak her başlık **0-10 olgunluk skoru** alır.

**Kalite kuralları (bulguların güvenilir olması için):**
- **Kanıt zorunlu:** Her sorun somut `dosya:satır` referansı taşımalı; tahmin değil, koddan doğrulama.
- **Risk kalibrasyonu:** `Kritik` (veri kaybı / güvenlik ihlali / üretim çöküşü) · `Yüksek` (ciddi, sınırlı) · `Orta` (kalite/sürdürülebilirlik) · `Düşük` (kozmetik).
- **🆕 Çekişmeli doğrulama:** Her Kritik/Yüksek bulgu **bağımsız ikinci bir gözle** koddan teyit edilmeli — abartılmışsa risk düşürülür, kanıt tutmuyorsa reddedilir. (v1 denetiminde çoğu "Yüksek" doğrulamada "Orta"ya indi; bu adım false-positive'i ayıklar.)
- **🆕 Çözülmüşü tekrar yazma:** Önceki denetimde kapatılmış maddeler "sorun" sayılmaz — önce koddan doğrula (örn. v1'de `/docs prod'da açık` iddiası doğrulamada "public 404" çıktı).
- Çözüm önerileri uygulanabilir olmalı (hangi dosya, ne değişmeli).

---

## 1. Mimari ve Modülerlik

- Sistem modüler mi? Modüller birbirinden ne kadar bağımsız (coupling)?
- Katmanlı mimari uygulanmış mı? 🆕 **Resmi bir service katmanı var mı (router → service → model), yoksa iş mantığı router'larda mı gömülü?**
- 🆕 **Bir router başka bir router'dan import ediyor mu (paketler-arası coupling)?**
- SOLID prensipleri uygulanmış mı? Circular dependency mevcut mu (import grafiği)?
- 🆕 **Aynı iş mantığı birden çok yerde elle tekrar yazılıyor mu (örn. onay/dual-write yolu router davranışını birebir yansıtmak zorunda mı)?**
- Teknik borç oluşturan mimari kararlar var mı? Yeni modül eklemek ne kadar kolay (fabrika deseni / iskelet otomasyonu var mı)?

## 2. Kod Kalitesi

- Kod tekrarları mevcut mu? 🆕 **Ortak yardımcılar (tarih/para formatı vb.) merkezi mi, yoksa sayfalara kopyalanıp tutarsızlaşmış mı?**
- Çok büyük dosya/fonksiyonlar var mı? (Eşik öner: dosya > ~600 satır incele.)
- Refactor edilmesi gereken alanlar? Naming convention tutarlı mı?
- Türkçe/İngilizce karışıklıkları var mı (tanımlayıcı İngilizce / kullanıcı metni Türkçe kuralı)? ASCII-Türkçe ihlali?
- 🆕 **Tip güvenliği: yaygın `any`/untyped kullanımı var mı? Boş `catch`/sessiz hata yutma var mı?**
- Kod okunabilirliği ve sürdürülebilirliği ne seviyede (TODO/FIXME borcu)?

## 3. Güvenlik (OWASP Top 10)

- OWASP Top 10'un **her** maddesini tek tek değerlendir (A01…A10).
- Yetkilendirme (RBAC) eksikleri? **IDOR / yatay yetki** kontrolü var mı?
- Authentication güvenli mi? JWT/Cookie kullanımı doğru mu (HttpOnly/secure/samesite, localStorage'da token var mı)?
- Path Traversal, XSS, CSRF, SSRF, Injection (ham SQL girdileri doğrulanıyor mu)?
- 🆕 **WebSocket handshake'inde Origin kontrolü var mı (CSWSH riski)?**
- 🆕 **Bağımlılık CVE'leri (kripto/parse kütüphaneleri — jose/passlib/lxml vb.) — sürümler güncel mi?**
- 🆕 **Başarısız giriş denemeleri kalıcı denetim izine (audit) yazılıyor mu?**
- API güvenliği yeterli mi? Secrets/env doğru yönetiliyor mu (kodda default yok)? Dosya yükleme magic-byte ile doğrulanıyor mu?

## 4. Performans

- En yavaş modüller? N+1 sorgu problemleri? Cache stratejileri yeterli mi?
- 🆕 **GET endpoint'leri gerçekten salt-okunur mu (GET içinde yazma/commit var mı)?**
- 🆕 **Bloklayıcı I/O (DB/dış servis/parse) event-loop'u kilitliyor mu, yoksa threadpool/`to_thread`'e mi alınmış?**
- 🆕 **Sayfalama gerçek SQL seviyesinde mi (count + offset/limit), yoksa Python'da slice mı?**
- Büyük veri setlerinde darboğaz? Sedna/harici entegrasyon yüksek yük altında nasıl?
- Bellek/CPU riskli noktalar (tüm sonucu belleğe alma, büyük parse)?

## 5. Stabilite ve Dayanıklılık

- Harici servis kesintilerinde davranış (graceful degradation mı, çöküş mü)?
- 🆕 **Timeout VE retry birlikte var mı (timeout tek başına dayanıklılık değildir)?** (Detaylı: Başlık 19)
- Hata yönetimi standart mı (global exception handler)?
- Kritik iş akışlarında veri kaybı oluşabilir mi? Transaction yönetimi doğru mu (commit/rollback, SAVEPOINT, kısmi başarı, idempotency)?
- 🆕 **Sessiz hata yutan (return 0/None ile devam eden) kritik yol var mı?**

## 6. Veritabanı Tasarımı

- Şema sağlıklı mı? Veri bütünlüğü kuralları yeterli mi?
- 🆕 **Index eksikleri — sık filtrelenen/JOIN'lenen/cascade FK kolonları indeksli mi?**
- 🆕 **Dedup/benzersizlik DB-seviyesi UNIQUE ile mi korunuyor, yoksa yalnız uygulama katmanında mı (yarış durumunda çift kayıt riski)?**
- 🆕 **Domain invariant'ları (durum enum'ları, işaret/pozitiflik) DB-seviyesi CHECK ile mi, yoksa tamamen uygulamaya mı bağlı?**
- Performans problemi oluşturabilecek büyüyen tablolar? Migration süreçleri güvenli mi (downgrade var mı, autogenerate yanlış DROP riski)?

## 7. API Kalitesi

- Endpoint isimlendirmeleri tutarlı mı (REST, çoğul kaynak, kebab-case, ASCII path)? HTTP metod/status semantiği doğru mu?
- Versiyonlama stratejisi var mı (`/api/v1`)?
- 🆕 **`response_model` kapsamı ne (OpenAPI sözleşmesi güvenilir mi, codegen mümkün mü)?**
- Hata cevapları standart mı? 🆕 **422/validasyon hataları dil ve şekil olarak tutarlı mı (kullanıcı-metni dil kuralıyla uyumlu mu)?**
- Swagger/OpenAPI dokümantasyonu güncel mi (ve prod'da açık olması bir ifşa riski mi)?

## 8. Frontend ve Mobil Denetimi

- Mobil kullanım kalitesi (tablo→kart dönüşümü, touch-target ≥44px, safe-area)?
- Responsive kurallar tutarlı mı? PWA desteği yeterli mi (manifest + SW + offline + install)?
- 🆕 **Gerçek cihaz / e2e (Playwright) testi yapılmış/otomatik mı, yoksa yalnız manuel mı?**
- Büyük veri tablolarında kullanıcı deneyimi (sanallaştırma/lazy-mount, truncation uyarısı)?

## 9. Test Altyapısı (Kapsam)

- Unit + integration kapsamı? E2E test mevcut mu? Coverage oranı yeterli mi?
- 🆕 **En riskli/en büyük modüller (dosya parser'ları, finans hesaplayıcılar) DOĞRUDAN test ediliyor mu, yoksa yalnız dolaylı mı (kod-değeri × test-kapsamı kesişimine bak)?**
- Kritik iş akışlarının testleri var mı? Eksik test senaryoları neler?

## 10. Test Süreçleri

- Test kullanıcıları/rolleri (izin-matrisi fixture'ları) tanımlı mı? Test veri setleri var mı?
- 🆕 **Mock servisler doğru kurulmuş mu? Harici HTTP için açık ağ-engeli (network guard) var mı, yoksa izolasyon "çağrılmadığı için" mi çalışıyor (kırılgan garanti)?**
- 🆕 **Sessizce atlanan test var mı (`skipif` ile yerel-dosyaya bağlı, CI'da hiç çalışmayan)?**
- Regression testleri var mı? Testler otomatik çalışıyor mu?

## 11. CI/CD ve DevOps

- CI/CD pipeline mevcut mu? PR'da hangi kontroller çalışıyor (test + type-check + lint + güvenlik)?
- 🆕 **CI merge'i GATE ediyor mu (branch protection / required checks), yoksa yalnız bilgilendirici mi?**
- Test başarısız olursa deploy engelleniyor mu? Coverage raporları üretiliyor/PR'a yansıyor mu?
- Güvenlik taramaları (SAST/dependency/Dependabot) yapılıyor mu?
- 🆕 **Deploy akışında migration adımı (`alembic upgrade head`) var mı? Rollback mekanizması (release tag / atomik build-swap) var mı?**

## 12. Loglama ve İzleme

- Audit log sistemi yeterli mi (tüm CRUD + login/logout, IP/user/entity)?
- Error tracking mevcut mu (DB tablosu / merkezi araç)?
- Loglama stratejisi kurumsal seviyede mi (structured/JSON, log rotation)?
- 🆕 **Korelasyon/request ID ile frontend→backend→DB akışı ilişkilendirilebiliyor mu?**
- *(APM / alerting / metrik → ayrı başlıkta: 17)*

## 13. Dokümantasyon

- CLAUDE.md / api-haritasi.md / ui-kurallari.md güncel mi? Kod ile arasında drift var mı (nicel/envanter bölümlerini özellikle kontrol et)?
- 🆕 **Drift OTOMATİK tespit ediliyor mu (CI'da kod-doküman tutarlılık testi var mı)?**
- 🆕 **Her aktif modülün dedicated modül dokümanı var mı (yeni modül = doküman kuralı uygulanmış mı)?**

## 14. Ölçeklenebilirlik

- Kullanıcı sayısı 10 kat artarsa? Modül sayısı 2 katına çıkarsa mimari yeterli mi?
- Veritabanı büyümesine hazır mı (partition/arşiv/retention)?
- 🆕 **In-memory durum (WebSocket registry, cache, rate-limit, oturum) yatay ölçekte (çok-worker/çok-instance) bölünür mü? Oturum/durum dışsallaştırılmış mı (Redis/DB)?**
- 🆕 **Dosya yüklemeleri yerel diske mi (çok-instance'ta paylaşılır mı)?** Yatay ölçekleme yapılabilir mi?

## 15. Teknik Borç ve Yol Haritası

- Kritik teknik borçlar? İlk 30 / 90 günde yapılacaklar?
- Enterprise seviyesine ulaşmak için eksik parçalar (observability, e2e, API versiyon, secret manager, IaC, HA, SAST, staging, blue-green, DR tatbikatı)?
- En büyük tek risk nedir?

---

# 🆕 Yeni Başlıklar (v2)

> Bu beş başlık v1'de ya hiç yoktu ya da bir alt-soruya sıkışmıştı. 2026-06-21 denetimi bunların en ayırt edici alan olduğunu gösterdi (tek **Kritik** bulgu — otomatik DB yedeği yokluğu — buradan çıktı).

## 16. Yedekleme, Felaket Kurtarma (DR) ve İş Sürekliliği

- **Otomatik veritabanı yedeği var mı?** (Kod yedeği ≠ DB yedeği — ikisini ayır.) Sıklık, formatı (`pg_dump -Fc` / fiziksel), **off-site kopya** (S3/başka makine, şifreli)?
- **RPO/RTO tanımlı mı** (kabul edilebilir veri kaybı / kurtarma süresi)?
- **Restore tatbikatı yapılıyor mu** (yedek geri yüklenip satır sayısı doğrulanıyor mu — "yedek var" ≠ "yedek çalışıyor")?
- PITR / WAL arşivleme var mı? EBS snapshot / RDS otomatik yedek?
- SPOF (tek sunucu/tek disk/tek DB)? Ransomware / yanlış DROP / disk arızası senaryosunda kurtarma yolu?
- "Yedekleme" adlı bir modül/özellik gerçekten DB'yi mi koruyor, yoksa yanlış güven mi veriyor?

## 17. Gözlemlenebilirlik (Observability) ve Alerting

- **APM / distributed tracing** var mı (Sentry / OpenTelemetry / Datadog)?
- **Metrikler toplanıyor mu** (p50/p95/p99 gecikme, hata oranı, slow query, request-timing)?
- **Alerting:** Bir şey patladığında **kim, nasıl, ne kadar sürede** haber alıyor (yoksa kullanıcı şikayetiyle mi fark ediliyor)?
- **Readiness/liveness probe** gerçek mi (health endpoint DB/bağımlılık kontrol ediyor mu, yoksa sabit `ok` mu)?
- Hata gruplama/deduplication, release ilişkilendirme, etkilenen kullanıcı sayısı görünür mü?
- Frontend istemci-hata yakalama (window.onerror → backend / Sentry) var mı?
- Dashboard / kapasite planlama verisi var mı?

## 18. Veri Gizliliği ve KVKK Uyumu

- **Kişisel veri envanteri** çıkarılmış mı (misafir, personel, cari — hangi tabloda hangi PII)?
- **Saklama süreleri** tanımlı ve uygulanıyor mu (audit/log/finansal kayıt retention)?
- Veri **anonimleştirme/maskeleme** (özellikle loglarda, yedeklerde, test ortamında PII)?
- **Veri ihlali bildirim** süreci var mı (KVKK 72 saat)? İlgili kişi **erişim/silme/düzeltme** talepleri karşılanabilir mi?
- Hassas verilere erişim **denetlenebilir** mi (audit izi)? Üçüncü taraflara (Sedna/Travelpayouts) veri aktarımı sözleşmesel/teknik olarak yönetiliyor mu?
- Şifre/secret saklama (hash, secret manager) ve aktarımda (TLS) koruma?

## 19. Üçüncü-Parti Entegrasyon Dayanıklılığı

- Her harici bağımlılık (Sedna SQL Server, TCMB, Travelpayouts, push, e-posta vb.) için:
  - **Timeout + retry + circuit-breaker** var mı? (timeout tek başına yetmez)
  - Servis düşünce **graceful degradation** mı, yoksa zincirleme arıza mı?
  - Çağrılar **idempotent** mi (retry güvenli mi, çift-işlem riski var mı)?
  - **Kontrat değişikliği** (XML şeması, API alanı) tespit ediliyor mu, yoksa sessizce mi bozuluyor?
  - Uzun/ağır senkronlar arka plana alınmış mı (HTTP timeout / 504 riski)?
- Entegrasyon ana uygulamanın çalışmasına bağlı mı, yoksa gevşek-bağlı (loose coupled) mı?

## 20. Finansal Doğruluk ve Mutabakat Bütünlüğü

> ERP'nin kalbi para — bu, "stabilite"den ayrı bir **doğruluk** denetimidir.

- **Çift-sayım engeli** yapısal mı (idempotent upsert + DB UNIQUE), yoksa yalnız uygulama mantığına mı bağlı?
- **FIFO / ödeme kırpma / tahsilat eşleştirme** mantığı test edilmiş ve doğru mu (para birimi bazında ayrı havuz, kalan-tutar sıralaması)?
- **Onay → uygula (dual-write) tutarlılığı:** onay handler'ı router'ın TÜM yan etkilerini (finance_events, plan üretimi, recalc) birebir yansıtıyor mu (sessiz sapma riski)?
- **Kur dönüşümü / yuvarlama:** çok-para-birimli tutarlar (amount_try) doğru ve güncel mi? Yuvarlama tutarlı mı?
- **Mutabakat:** yerel kayıtlar ↔ kaynak sistem (Sedna muhasebe) periyodik mutabık ediliyor mu?
- **Denetlenebilir para izi:** her finansal mutasyon geriye izlenebilir ve değiştirilemez (immutable) mi?

---

# Ek Çıktılar (v2)

v1'in 10 çıktısı + 3 yeni:

1. **Risk Matrisi** (olasılık × etki)
2. **Eksik Test Senaryoları Listesi**
3. **Eksik Test Kullanıcıları ve Roller**
4. **Eksik Mock Veri Setleri**
5. **Dokümantasyon Drift Raporu**
6. **Güvenlik Açıkları Listesi**
7. **Performans İyileştirme Listesi**
8. **Önceliklendirilmiş Teknik Borç Listesi**
9. **30-60-90 Günlük İyileştirme Planı**
10. **Genel Proje Notu (100 üzerinden)** + bağımlılık-azaltıldığında hedef not
11. 🆕 **KVKK / Kişisel Veri Envanteri ve Uyum Boşlukları**
12. 🆕 **Felaket Kurtarma (DR) / Restore Tatbikat Raporu** (yedek var mı · RPO/RTO · restore test edildi mi)
13. 🆕 **Üçüncü-Parti Entegrasyon Dayanıklılık Matrisi** (her servis: timeout / retry / circuit-breaker / fallback / idempotency durumu)

---

*v1: kullanıcının orijinal 15-başlık + 10-çıktı seti. v2: 2026-06-21 çok-ajanlı denetimin bulgularıyla güncellendi (`docs/denetim/2026-06-21-teknik-denetim-raporu.md`).*
