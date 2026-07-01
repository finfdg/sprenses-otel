export const meta = {
  name: 'denetle-moduller',
  description: 'Değişen (veya verilen) modülleri modul-denetci ile paralel denetler ve tek rapora birleştirir',
  phases: [
    { title: 'Keşif', detail: 'git diff ile değişen modülleri bul (veya args listesini kullan)' },
    { title: 'Denetim', detail: 'her modül için modul-denetci — paralel' },
    { title: 'Sentez', detail: 'bulguları önem sırasına göre tek rapora birleştir' },
  ],
}

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
let hedefler = Array.isArray(args) && args.length ? args : null
if (!hedefler) {
  const disc = await agent(
    'git status --porcelain ve git diff --name-only HEAD ile değişen dosyaları bul. ' +
    'Her dosyayı modül koduna indirge (ör. backend/app/routers/finance/checks.py → "finance.checks", ' +
    'frontend/src/routes/dashboard/finans/cekler → "finance.checks"). ' +
    'Benzersiz modül kodları listesini döndür. Değişiklik yoksa boş liste döndür.',
    { label: 'kesif', phase: 'Keşif', schema: KESIF_SEMA }
  )
  hedefler = disc?.moduller || []
}

if (!hedefler.length) {
  log('Değişen modül bulunamadı — denetlenecek bir şey yok.')
  return { denetlenen: [], toplam_bulgu: 0, moduller: [] }
}
log(`${hedefler.length} modül denetlenecek: ${hedefler.join(', ')}`)

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
  'Önem sırasına göre grupla (Kritik → Yüksek → Orta → Düşük); her bulguda dosya:satır ve kısa düzeltme öner. ' +
  'Sonda modül-bazlı özet tablo ver.\n\n' +
  JSON.stringify(denetimler),
  { label: 'sentez', phase: 'Sentez' }
)

return { denetlenen: hedefler, toplam_bulgu: toplam, moduller: denetimler, rapor }
