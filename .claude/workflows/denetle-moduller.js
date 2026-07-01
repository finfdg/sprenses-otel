export const meta = {
  name: 'denetle-moduller',
  description: 'Modülleri modul-denetci ile paralel denetler (hedef yoksa TÜM modüller) ve tek rapora birleştirir',
  phases: [
    { title: 'Keşif', detail: 'hedef modülleri belirle: args listesi / "degisen" (git) / boşsa tüm modüller' },
    { title: 'Denetim', detail: 'her modül için modul-denetci — paralel' },
    { title: 'Sentez', detail: 'bulguları önem sırasına göre tek rapora birleştir' },
  ],
}

// ── Tüm leaf (CRUD'lu) modüller — DB `modules` tablosu anlık görüntüsü (2026-07-01, 45 modül).
// Leaf = alt-modülü olmayan modüller. Yenilemek için: alt-modülü olmayan modules.code listesi.
const TUM_MODULLER = [
  'accounting.dividend', 'accounting.fis_icmali', 'accounting.mizan', 'accounting.recurring',
  'accounting.rent_expense', 'accounting.rent_income', 'accounting.taxes', 'dashboard',
  'finance.avanslar', 'finance.banks', 'finance.butce', 'finance.cariler', 'finance.cash_flow',
  'finance.checks', 'finance.doviz', 'finance.krediler', 'finance.onay', 'finance.sales_invoices',
  'hr.attendance', 'hr.salary', 'hr.sgk', 'hr.shift_schedule', 'hr.shifts', 'hr.withholding',
  'messaging', 'quality.forms', 'quality.templates', 'sales.daily_reservations', 'sales.flight',
  'sales.hotel_reservation', 'sales.room_types', 'stok.depolar', 'stok.hareketler', 'stok.maliyet',
  'stok.urunler', 'system.approval', 'system.audit_logs', 'system.backup', 'system.docs',
  'system.error_logs', 'system.modules', 'system.roles', 'system.server', 'system.users',
  'yonetim.panel',
]

// ── Şemalar ───────────────────────────────────────────────────
const KESIF_SEMA = {
  type: 'object',
  additionalProperties: false,
  properties: { moduller: { type: 'array', items: { type: 'string' } } },
  required: ['moduller'],
}

const DENETIM_SEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    modul: { type: 'string' },
    bulgular: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          kural: { type: 'string' },
          onem: { type: 'string', enum: ['kritik', 'yuksek', 'orta', 'dusuk'] },
          dosya_satir: { type: 'string' },
          aciklama: { type: 'string' },
        },
        required: ['kural', 'onem', 'dosya_satir', 'aciklama'],
      },
    },
  },
  required: ['modul', 'bulgular'],
}

// ── 1) Hedef modülleri belirle ────────────────────────────────
phase('Keşif')
// args normalizasyonu — dizi, JSON-string veya virgüllü string olarak gelebilir
let girdi = args
if (typeof girdi === 'string') {
  const s = girdi.trim()
  try {
    girdi = JSON.parse(s)
  } catch (e) {
    girdi = s ? s.split(',').map((x) => x.trim()).filter(Boolean) : []
  }
}
const verilen = Array.isArray(girdi) ? girdi.filter(Boolean) : []
const ilk = verilen.length === 1 ? String(verilen[0]).toLowerCase() : null

let hedefler
if (ilk === 'degisen' || ilk === 'changed') {
  // "degisen" anahtarı → git ile değişen modülleri keşfet
  const disc = await agent(
    'git status --porcelain ve git diff --name-only HEAD ile değişen dosyaları bul. ' +
    'Her dosyayı modül koduna indirge (ör. backend/app/routers/finance/checks.py → "finance.checks", ' +
    'frontend/src/routes/dashboard/finans/cekler → "finance.checks"). ' +
    'Benzersiz modül kodları listesini döndür. Değişiklik yoksa boş liste döndür.',
    { label: 'kesif', phase: 'Keşif', schema: KESIF_SEMA }
  )
  hedefler = disc?.moduller || []
  log(`git keşfi: ${hedefler.length} değişen modül.`)
} else if (verilen.length) {
  // Açık modül listesi verildi
  hedefler = verilen
  log(`Verilen ${hedefler.length} modül denetlenecek.`)
} else {
  // Hedef yok → TÜM modülleri tara
  hedefler = TUM_MODULLER
  log(`Hedef verilmedi → TÜM ${TUM_MODULLER.length} modül taranacak.`)
}

if (!hedefler.length) {
  log('Denetlenecek modül yok.')
  return { denetlenen: [], toplam_bulgu: 0, moduller: [] }
}
log(`Denetim başlıyor (${hedefler.length}): ${hedefler.join(', ')}`)

// ── 2) Her modülü paralel denetle (modul-denetci) ─────────────
const denetimler = (await parallel(hedefler.map((m) => () =>
  agent(
    `"${m}" modülünü /home/ec2-user/otel/CLAUDE.md kurallarına göre SALT-OKUNUR denetle. ` +
    'Router/model/schema/frontend dosyalarını bul; izin sistemi, onay akışı + executor handler, ' +
    'audit log, Türkçe karakter, Python 3.9, merkezi sabitler, finance_events, UI tasarım sistemi, ' +
    'doküman ve test kapsamını kontrol et. Bulguları şemaya göre döndür; bulgu yoksa boş bulgular[].',
    { label: `denetim:${m}`, phase: 'Denetim', agentType: 'modul-denetci', schema: DENETIM_SEMA }
  )
))).filter(Boolean)

// ── 3) Sentez ─────────────────────────────────────────────────
phase('Sentez')
const toplam = denetimler.reduce((n, d) => n + (d.bulgular ? d.bulgular.length : 0), 0)

// 0 bulgu → pahalı sentez ajanını atla (early-exit)
if (toplam === 0) {
  log('Tüm modüller temiz — kural ihlali bulunamadı.')
  return { denetlenen: hedefler, toplam_bulgu: 0, moduller: denetimler }
}

const rapor = await agent(
  'Aşağıdaki modül denetim bulgularını tek bir Türkçe markdown rapora birleştir. ' +
  'Kritik ve Yüksek bulguları tek tek yaz (dosya:satır + kısa düzeltme). ' +
  'Orta ve Düşük bulguları kesişen temalara göre grupla ve özetle (her temada birkaç örnek dosya:satır ver). ' +
  'Modüller-arası tekrarlayan desenleri (ör. eksik RBAC 403 testi, doküman/kod sapması) ayrı bir ' +
  '"Kesişen Temalar" bölümünde vurgula. Sonda önem kırılımını gösteren modül-bazlı özet tablo ver.\n\n' +
  JSON.stringify(denetimler),
  { label: 'sentez', phase: 'Sentez' }
)

return { denetlenen: hedefler, toplam_bulgu: toplam, moduller: denetimler, rapor }
