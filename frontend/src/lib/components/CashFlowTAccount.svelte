<!--
	CashFlowTAccount.svelte — Nakit Akım T Hesap Cetveli (Panel yeniden tasarımı, 2026-07-04;
	etkileşim yenilemesi 2026-07-06 — tasarım: "Nakit Akım T-Hesap.dc.html").

	Muhasebedeki T hesap cetveli: solda Nakit Giriş (yeşil), sağda Nakit Çıkış (altın); mobilde
	dikey istif. Dönem sekmeleri (Günlük/Haftalık/Aylık/Yıllık) + tarih gezgini.

	İki bağımsız SÜTUN-İÇİ kontrol (tasarım kararı):
	  1) SEGMENT (Bekleyen | ✓ Gerçekleşen) — aynı liste YERİNDE değişir (ayrı panel açılmaz).
	     Varsayılan "Bekleyen"; dönem/gezinme değişince sıfırlanır. Bölme grup sayaçlarından
	     (realized_eur/realized_count) yapılır — items MAX_ITEMS_PER_GROUP=100 ile kırpık olabilir.
	  2) TARİH GÖRÜNÜMÜ — sütun başlığındaki takvim ikonuna basınca kategori-gruplama ↔ gün-gruplama
	     arası geçiş. Tarih görünümünde tüm kalemler kronolojik gün başlıkları altında (kategori etiketiyle).

	Veri: GET /finance/cash-flow/t-account?period=&offset= (EUR, gerçek finance_events).
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { WS_EVENT } from '$lib/constants/realtime';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import RunwayChart from '$lib/components/RunwayChart.svelte';
	import OverdueList from '$lib/components/OverdueList.svelte';
	import HeldList from '$lib/components/HeldList.svelte';
	import { cashFlowCache, loadCashFlowEurBalances, isEurBalancesStale } from '$lib/stores/cashflow.svelte';
	import { runwayStore, setHoldMode, holdBatch, type SourceRef } from '$lib/stores/runway.svelte';
	import { aggregateRows, AGGREGATE_LABELS, daySourceRank, firstTippingRow, type CashRow } from '$lib/utils/cashflow';
	import { bankBadge } from '$lib/utils/bankBadge';
	import { HOLDABLE_SOURCE_TYPES } from '$lib/constants/finance';
	import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, PauseCircle } from 'lucide-svelte';

	type TItem = { name: string; date: string; amount_eur: number; amount_native: number; currency: string; is_realized?: boolean; is_held?: boolean; source_type?: string | null; source_id?: number | null; bank_name?: string | null };
	// in_total=false → toplam-dışı bilgi grubu (ör. "Pos Bloke Çözme" — hesaplar arası
	// virman): listede görünür, kolon toplamı/net/gün toplamına GİRMEZ (backend INFO_CATEGORIES)
	type TGroup = { label: string; total_eur: number; item_count: number; section?: string; items: TItem[]; realized_eur?: number; realized_count?: number; held_eur?: number; held_count?: number; in_total?: boolean };
	type TData = {
		period: string; offset: number; start_date: string; end_date: string;
		giris: TGroup[]; cikis: TGroup[];
		total_in_eur: number; total_out_eur: number; net_eur: number;
		realized_in_eur?: number; realized_out_eur?: number;
		faaliyet_net_eur?: number; finansman_net_eur?: number; skipped_no_rate: number;
	};
	type SideKey = 'giris' | 'cikis';
	type DayBucket = { date: string; label: string; items: TItem[]; totalEur: number };
	// Tarih görünümü: gün → kategori alt-grubu → satır (cari toplu, diğerleri ayrı)
	// Held (beklemeye alınmış) satırlar sarı gösterilir, toplama katılmaz → ayrı `heldRows`.
	type DateRow = { name: string; amountLabel: string; amount_eur: number; members: SourceRef[]; bank_name: string | null };
	type DateCat = { label: string; rank: number; totalEur: number; inTotal: boolean; rows: DateRow[]; heldRows: DateRow[] };
	type DateDay = { date: string; label: string; totalEur: number; cats: DateCat[] };

	// İleri (gelecek dönem) navigasyon üst sınırı — backend le=24 ile aynı
	const MAX_FUTURE_OFFSET = 24;
	// Tarih görünümünde gösterilecek en fazla gün başlığı (fazlası "+N gün daha" ile özetlenir)
	const MAX_DATE_DAYS = 40;

	const PERIODS = [
		{ value: 'daily', label: 'Günlük' },
		{ value: 'weekly', label: 'Haftalık' },
		{ value: 'monthly', label: 'Aylık' },
		{ value: 'yearly', label: 'Yıllık' },
	];
	const PERIOD_TYPE_LABEL: Record<string, string> = {
		daily: 'GÜNLÜK', weekly: 'HAFTALIK', monthly: 'AYLIK', yearly: 'YILLIK',
	};
	const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
	const MONTHS_SHORT = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
	const WEEKDAYS = ['Pazar', 'Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi'];
	// Sütun görsel kimliği: gelir=yeşil (emerald), gider=altın (brass); net bandı lacivert (teal-700 token)
	const COLS: { side: SideKey; title: string; accent: string; totalCls: string }[] = [
		{ side: 'giris', title: 'Nakit Giriş', accent: 'bg-emerald-600', totalCls: 'text-emerald-700' },
		{ side: 'cikis', title: 'Nakit Çıkış', accent: 'bg-brass', totalCls: 'text-brass-dark' },
	];

	// State
	let period = $state<'daily' | 'weekly' | 'monthly' | 'yearly'>('monthly');
	let offsets = $state<Record<string, number>>({ daily: 0, weekly: 0, monthly: 0, yearly: 0 });
	let data = $state<TData | null>(null);
	let loading = $state(false);
	let open = $state<Record<string, boolean>>({});
	// Segment: her sütun bağımsız (bekleyen/gerceklesen); varsayılan bekleyen
	let sideView = $state<Record<SideKey, 'bekleyen' | 'gerceklesen'>>({ giris: 'bekleyen', cikis: 'bekleyen' });
	// Tarih görünümü toggle (kategori↔gün); her sütun bağımsız
	let dateView = $state<Record<SideKey, boolean>>({ giris: false, cikis: false });
	// Mobil (README): kapalıyken "Bugün" özet kartı, dokununca tam T hesap açılır
	let expanded = $state(false);
	let todaySummary = $state<TData | null>(null);
	const cache = new Map<string, TData>();

	// Beklet (hold) modu — yalnız finance.cash_flow KULLANIM yetkisi olanlar görür/kullanır.
	// Mod AÇIKKEN bekleyen satırlar tıklanınca beklemeye alınır (akım-dışı, Bekleme Listesi'ne).
	const canHold = hasPermission('finance.cash_flow', 'use');
	const holdMode = $derived(runwayStore.holdMode);
	let holdMutating = $state(false);

	function fmtEur(n: number): string {
		return '€' + new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(Math.round(n));
	}
	// Kalem kendi para biriminde (detay satırı) — grup/kolon toplamı EUR kalır
	const CUR_SYM: Record<string, string> = { TRY: '₺', EUR: '€', USD: '$', GBP: '£' };
	function fmtNative(n: number, currency: string): string {
		const sym = CUR_SYM[currency] || (currency + ' ');
		return sym + new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(Math.round(n));
	}
	// Toplu/tekil satır tutarı: tek para birimi → native (₺/€…); karışık (currency=null) → EUR toplam
	function rowAmountLabel(row: CashRow): string {
		return row.currency ? fmtNative(row.amount_native, row.currency) : fmtEur(row.amount_eur);
	}
	// Kalem adı başındaki "[Avans]"/"[Maaş]"/"[Alınan Kira]" gibi tür ön ekini kaldır — grup/kategori
	// başlığı zaten türü gösteriyor (kullanıcı isteği 2026-07-07); OverdueList'teki cleanName ile aynı.
	function cleanName(name: string): string {
		return name.replace(/^\[[^\]]*\]\s*/, '');
	}

	// ── Segment bölme (kategori görünümü) — sayaç-bazlı (items kırpık olabilir) ──
	function catGroups(groups: TGroup[], realized: boolean): TGroup[] {
		return groups
			.map((g) => {
				const rEur = g.realized_eur ?? 0;
				const rCount = g.realized_count ?? 0;
				return {
					...g,
					items: g.items.filter((it) => !!it.is_realized === realized),
					total_eur: realized ? rEur : g.total_eur - rEur,
					item_count: realized ? rCount : g.item_count - rCount,
				};
			})
			.filter((g) => g.item_count > 0)
			.sort((a, b) => b.total_eur - a.total_eur);
	}

	// Açık kategori grubunun kalemlerini gün başlıkları altında grupla (Map-bazlı → mükerrer
	// anahtar/donma yok; backend items'ı tarih sıralı gönderir). Günlük toplam EUR HELD'İ HARİÇ tutar
	// (beklemeye alınan kalem sarı gösterilir ama toplama katılmaz); held kalem items'ta KALIR.
	function groupItemsByDate(items: TItem[]): DayBucket[] {
		const byDate = new Map<string, DayBucket>();
		const out: DayBucket[] = [];
		for (const it of items) {
			let cur = byDate.get(it.date);
			if (!cur) {
				const [y, m, d] = it.date.split('-').map(Number);
				cur = { date: it.date, label: `${d} ${MONTHS[m - 1]} ${y}`, items: [], totalEur: 0 };
				byDate.set(it.date, cur);
				out.push(cur);
			}
			cur.items.push(it);
			if (!it.is_held) cur.totalEur += it.amount_eur; // held toplama katılmaz
		}
		return out;
	}

	// ── Tarih görünümü — segment'e göre kalemleri düzleştir; GÜN → KATEGORİ alt-grubu → satır.
	// Kategori "Cari Ödemeleri" ise satırlar firma bazında TOPLU (aggregateRows), diğerlerinde her kalem AYRI.
	function dateBuckets(groups: TGroup[], realized: boolean): { days: DateDay[]; hasMore: boolean; moreText: string } {
		const flat: (TItem & { cat: string; inTotal: boolean })[] = [];
		for (const g of groups) for (const it of g.items) if (!!it.is_realized === realized) flat.push({ ...it, cat: g.label, inTotal: g.in_total !== false });
		flat.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));

		const byDate = new Map<string, { date: string; label: string; totalEur: number; catMap: Map<string, (TItem & { cat: string; inTotal: boolean })[]> }>();
		const dayOrder: string[] = [];
		for (const it of flat) {
			let day = byDate.get(it.date);
			if (!day) {
				const [y, m, d] = it.date.split('-').map(Number);
				day = { date: it.date, label: `${d} ${MONTHS[m - 1]} ${y}`, totalEur: 0, catMap: new Map() };
				byDate.set(it.date, day);
				dayOrder.push(it.date);
			}
			// held + toplam-dışı bilgi kategorisi (Pos Bloke Çözme) gün toplamına katılmaz
			if (!it.is_held && it.inTotal) day.totalEur += it.amount_eur;
			let catItems = day.catMap.get(it.cat);
			if (!catItems) { catItems = []; day.catMap.set(it.cat, catItems); }
			catItems.push(it);
		}

		const toRow = (r: CashRow): DateRow => ({ name: r.name, amountLabel: rowAmountLabel(r), amount_eur: r.amount_eur, members: r.members, bank_name: r.bank_name });
		const days: DateDay[] = dayOrder.map((d) => {
			const day = byDate.get(d)!;
			const cats: DateCat[] = [...day.catMap.entries()]
				.map(([label, items]) => {
					const agg = AGGREGATE_LABELS.has(label);
					// Held (beklemeye alınmış) kalemler ayrı toplanır → sarı gösterilir, toplama girmez
					const counted = items.filter((it) => !it.is_held);
					const heldItems = items.filter((it) => it.is_held);
					return {
						label,
						// Grup tek kaynak türünden oluşur (backend etiket=kaynak) → ilk kalem yeterli
						rank: daySourceRank(items[0]?.source_type),
						totalEur: counted.reduce((s, it) => s + it.amount_eur, 0),
						inTotal: items[0]?.inTotal !== false,
						rows: aggregateRows(counted, agg).map(toRow),
						heldRows: aggregateRows(heldItems, agg).map(toRow),
					};
				})
				// Gün içi ödeme önceliği: çek → kredi → KK → vergi → SGK → diğer → fatura → cari
				// (daySourceRank — kullanıcı kararı 2026-07-07); eşit öncelikte tutar azalan.
				.sort((a, b) => a.rank - b.rank || b.totalEur - a.totalEur);
			return { date: day.date, label: day.label, totalEur: day.totalEur, cats };
		});

		if (days.length > MAX_DATE_DAYS) {
			const extra = days.length - MAX_DATE_DAYS;
			return { days: days.slice(0, MAX_DATE_DAYS), hasMore: true, moreText: `+${extra} gün daha (Nakit Akım sayfasında tümü)` };
		}
		return { days, hasMore: false, moreText: '' };
	}

	function segTotals(side: SideKey) {
		if (!data) return { realized: 0, pending: 0, hasData: false };
		const total = side === 'giris' ? data.total_in_eur : data.total_out_eur;
		const realized = (side === 'giris' ? data.realized_in_eur : data.realized_out_eur) ?? 0;
		const raw = side === 'giris' ? data.giris : data.cikis;
		return { realized, pending: total - realized, hasData: raw.length > 0 };
	}

	// Bugünkü SAF banka nakdi — runway `start_eur` (= backend `_compute_start_eur`; Bankalar KPI +
	// RunwayChart başlığıyla TEK kaynak, C2). ilk-açık yürüyüşünün başlangıcı. **`eur_balances.
	// total_balance_eur` KULLANILMAZ** — o değer bugün son banka ekstresinden sonraysa bugünün
	// ödenmemiş ödemesini zaten düşüyor → tipping yürüyüşü aynı ödemeyi tekrar düşünce ÇİFT sayım
	// ("para hâlâ bankada" 2026-07-06 ilkesi + kullanıcı bulgusu 2026-07-16). Saf nakit → tek düşüm.
	const startCash = $derived(runwayStore.data?.start_eur ?? null);

	// İLK AÇIK: bugünkü saf nakitten başlayıp BEKLEYEN çıkışları kronolojik yürüt; bakiyeyi ilk kez
	// negatife düşüren ödeme = "nakit buraya yetmiyor" (kullanıcı isteği 2026-07-07 — yalnız o TEK
	// satır kırmızı). Yalnız ÇIKIŞ + bekleyen segment + tarih görünümünde anlamlı (kronolojik).
	// Aynı `dateBuckets(data.cikis, false)` render'da kullanılır → (date, catLabel, rowIdx) birebir eşleşir.
	// Yürüyüş mantığı saf `firstTippingRow`'da (test: cashflow.test.ts — çift-sayım regresyonu).
	const tippingCikis = $derived.by(() => {
		if (!data || startCash == null || sideView.cikis !== 'bekleyen' || !dateView.cikis) return null;
		// Bekleyen giriş: gün başına EUR (o günün ödemelerinden ÖNCE nakde eklenir);
		// held + toplam-dışı bilgi grupları (in_total=false) HARİÇ (akım-dışı)
		const inflowByDate = new Map<string, number>();
		for (const g of data.giris) {
			if (g.in_total === false) continue;
			for (const it of g.items) if (!it.is_realized && !it.is_held) inflowByDate.set(it.date, (inflowByDate.get(it.date) ?? 0) + it.amount_eur);
		}
		return firstTippingRow(startCash, inflowByDate, dateBuckets(data.cikis, false).days);
	});

	// Dönem etiketi — start/end_date'ten (README biçimleri)
	const periodLabel = $derived.by(() => {
		if (!data) return '';
		const s = new Date(data.start_date + 'T00:00:00');
		if (period === 'daily') return `${WEEKDAYS[s.getDay()]}, ${s.getDate()} ${MONTHS[s.getMonth()]} ${s.getFullYear()}`;
		if (period === 'weekly') {
			const e = new Date(data.end_date + 'T00:00:00');
			return `${s.getDate()} ${MONTHS_SHORT[s.getMonth()]} – ${e.getDate()} ${MONTHS_SHORT[e.getMonth()]} ${e.getFullYear()}`;
		}
		if (period === 'monthly') return `${MONTHS[s.getMonth()]} ${s.getFullYear()}`;
		return String(s.getFullYear());
	});

	async function load() {
		const off = offsets[period];
		const key = `${period}:${off}`;
		const cached = cache.get(key);
		if (cached) { data = cached; return; }
		loading = true;
		try {
			const r = await api.get<TData>(`/finance/cash-flow/t-account?period=${period}&offset=${off}`);
			cache.set(key, r);
			data = r;
		} catch (err) {
			console.error('T hesap verisi yüklenemedi:', err);
			showToast('Nakit akım T hesap verisi yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	// T-Hesap verisini tazele (bekletme/ödeme sonrası) — cache bayat olduğundan temizle + yeniden yükle.
	// Tekil-uçuş koruması (runway.svelte.ts ile aynı desen, 2026-07-07): her Beklet tıklaması hem
	// doğrudan refreshData hem WS finance_updated yankısı tetikler; t-account (30/dk) ve özellikle
	// eur-balances art arda bekletmede rate limit'e takılıp grafiği sessizce bayat bırakıyordu
	// (nginx: 47×429). Uçuş sürerken gelen çağrılar TEK trailing yenilemeye kuyruklanır.
	let refreshInFlight: Promise<void> | null = null;
	let refreshQueued = false;
	let lastRefreshAt = 0;
	const WS_ECHO_MS = 1500; // sunucu broadcast debounce (500ms) + iletim gecikmesi payı

	async function refreshData(): Promise<void> {
		if (refreshInFlight) {
			// Uçuştaki yanıt bu çağrıdan önceki durumu taşıyabilir → uçuş bitince BİR kez daha yükle
			refreshQueued = true;
			return refreshInFlight;
		}
		refreshInFlight = (async () => {
			try {
				cache.clear();
				await load();
				if (cashFlowCache.eurBalances) await loadCashFlowEurBalances(); // RunwayChart eğrisi (başlık+tipping runway start_eur'den)
			} finally {
				lastRefreshAt = Date.now();
				refreshInFlight = null;
			}
		})();
		await refreshInFlight;
		if (refreshQueued) {
			refreshQueued = false;
			await refreshData();
		}
	}

	function toggleHoldMode() {
		if (!canHold) return;
		setHoldMode(!runwayStore.holdMode);
		expanded = true; // mobilde beklet moduna geçince tam görünüm açılsın (listeler görünür)
	}

	// Bekletilebilir üye filtresi — backend bekletilemez türleri (bank/check) sessizce atlar;
	// UI da bunlara affordance göstermez (çek satırında yalancı "Beklemeye alındı" olmasın).
	function holdableMembers(members: SourceRef[]): SourceRef[] {
		return members.filter((m) => HOLDABLE_SOURCE_TYPES.has(m.source_type));
	}

	// Bir bekleyen satırı (aggregate → members) beklemeye al (held=true) / kaldır (false).
	async function holdRow(members: SourceRef[], held: boolean) {
		if (!canHold || !runwayStore.holdMode || holdMutating || members.length === 0) return;
		holdMutating = true;
		try {
			await holdBatch(members, held); // POST hold-batch + runway tazele
			await refreshData(); // T-Hesap'ta kalem bekleyen'den düşsün / geri gelsin
			showToast(held ? 'Beklemeye alındı' : 'Bekletme kaldırıldı', 'success');
		} catch (err: any) {
			console.error('Bekletme işlemi başarısız:', err);
			showToast(err?.message || 'Bekletme işlemi başarısız', 'error');
		} finally {
			holdMutating = false;
		}
	}

	// Dönem/gezinme değişince segment + tarih görünümü + açık gruplar sıfırlanır (tasarım kararı)
	function resetViews() {
		open = {};
		sideView = { giris: 'bekleyen', cikis: 'bekleyen' };
		dateView = { giris: false, cikis: false };
	}
	function setPeriod(v: string) {
		period = v as typeof period;
		resetViews();
		load();
	}
	function nav(delta: number) {
		if (delta > 0 && offsets[period] >= MAX_FUTURE_OFFSET) return; // ileri üst sınır (gelecek dönem)
		if (delta < 0 && offsets[period] <= -120) return; // backend alt sınırı (ge=-120)
		offsets[period] += delta;
		resetViews();
		load();
	}
	function setSegment(side: SideKey, v: 'bekleyen' | 'gerceklesen') {
		sideView[side] = v;
		open = {}; // segment değişince açık gruplar kapanır (yerinde swap)
	}
	function toggleDateView(side: SideKey) {
		dateView[side] = !dateView[side];
		open = {};
	}
	function toggle(key: string) {
		open[key] = !open[key];
	}

	onMount(() => {
		load();
		// Runway grafiği için gerçek günlük banka bakiyeleri (eur_balances — Nakit Akım sayfasıyla ortak
		// kaynak). Boş VEYA bayat ise çek — "yalnız boşsa" guard'ı, başka sayfadayken gelen finance_updated
		// sonrası dolu-ama-eski cache'i kullanıp grafiği güncel tutamıyordu (store WS'te damgayı sıfırlar).
		if (isEurBalancesStale()) loadCashFlowEurBalances();
		// Mobil özet kartı için bugünün Giriş/Çıkış/Net değerleri
		api.get<TData>('/finance/cash-flow/t-account?period=daily&offset=0')
			.then((r) => { cache.set('daily:0', r); todaySummary = r; })
			.catch((err) => console.error('Günlük özet yüklenemedi:', err));
		// Finans değişince (bekletme/ödeme/etiketleme/Sedna vb.) T-Hesap'ı WS ile canlı tazele (polling yok).
		// Son yüklemenin hemen ardından gelen event, bizim mutasyonumuzun broadcast YANKISIDIR —
		// doğrudan refreshData güncel veriyi zaten aldı, isteği atla (uçuş sürüyorsa kuyruklanır).
		const unsub = onWsEvent(WS_EVENT.FINANCE_UPDATED, () => {
			if (!refreshInFlight && Date.now() - lastRefreshAt < WS_ECHO_MS) return;
			refreshData();
		});
		return () => { unsub(); setHoldMode(false); }; // ayrılırken beklet modu pasife dön (salt gösterim)
	});
</script>

<div class="bg-white border border-gray-200 rounded-2xl shadow-sm p-4 sm:p-6">
	<!-- Başlık -->
	<div class="mb-4 flex items-start justify-between gap-3">
		<div>
			<h3 class="text-[17px] text-gray-900">Nakit Akım</h3>
			<!-- Masaüstü alt-başlık kaldırıldı; yerine aşağıya nakit projeksiyon grafiği (RunwayChart) geldi.
			     Mobil kapalı görünümde "Bugün" etiketi mini özet kartını niteler. -->
			<p class="text-xs text-gray-500 mt-0.5 sm:hidden {expanded ? 'hidden' : ''}">Bugün</p>
		</div>
		<div class="flex items-center gap-2 shrink-0">
			<!-- Beklet (option) butonu — yalnız finance.cash_flow USE yetkisi. Açıkken bekleyen satırlar
			     tıklanınca beklemeye alınır (akım-dışı). Pasifken bekletmeler korunur, düzenlenemez. -->
			{#if canHold}
				<button type="button" onclick={toggleHoldMode} aria-pressed={holdMode}
					title={holdMode ? 'Beklet modu açık — kapatmak için tıkla' : 'Beklet modunu aç (kalem beklemeye al)'}
					class="touch-target flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium cursor-pointer transition-colors
						{holdMode ? 'border-amber-300 bg-amber-100 text-amber-800' : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'}">
					<PauseCircle size={15} /> Beklet{#if holdMode} · Açık{/if}
				</button>
			{/if}
			<!-- Mobil: kapalıyken "detay için dokun" ipucu (sağ üst köşe) -->
			<button type="button" onclick={() => (expanded = true)} aria-label="Detayı aç"
				class="sm:hidden {expanded ? 'hidden' : ''} -mt-0.5 flex items-center gap-1 text-xs text-teal-700 font-medium cursor-pointer">
				detay için dokun <ChevronRight size={14} />
			</button>
			<!-- Mobil: tam görünümü kapat (yukarı ok) -->
			<button type="button" onclick={() => (expanded = false)} aria-label="Özete dön"
				class="sm:hidden {expanded ? '' : 'hidden'} touch-target w-9 h-9 -mt-1 -mr-1 flex items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 cursor-pointer">
				<ChevronUp size={18} />
			</button>
		</div>
	</div>

	<!-- Bankadaki nakit runway grafiği — başlık SAF banka nakdi (runway start_eur; Bankalar KPI ile aynı),
	     eğri gerçek günlük bakiye projeksiyonu (eur_balances), dönem aralığına göre dilimlenir -->
	<RunwayChart balances={cashFlowCache.eurBalances} startEur={runwayStore.data?.start_eur} startDate={data?.start_date} endDate={data?.end_date} />

	<!-- MOBİL ÖZET KARTI (kapalıyken) — Bugün için Giriş/Çıkış/Net mini kutuları -->
	<button type="button" onclick={() => (expanded = true)}
		class="sm:hidden {expanded ? 'hidden' : ''} w-full text-left cursor-pointer">
		<div class="grid grid-cols-3 gap-2">
			<div class="rounded-xl bg-emerald-50 border border-emerald-100 px-3 py-2.5">
				<div class="text-[10px] uppercase tracking-[0.5px] text-emerald-700">Giriş</div>
				<div class="tabular-nums text-sm font-semibold text-emerald-700 mt-0.5">{todaySummary ? fmtEur(todaySummary.total_in_eur) : '…'}</div>
			</div>
			<div class="rounded-xl bg-brass-soft border border-brass/30 px-3 py-2.5">
				<div class="text-[10px] uppercase tracking-[0.5px] text-brass-dark">Çıkış</div>
				<div class="tabular-nums text-sm font-semibold text-brass-dark mt-0.5">{todaySummary ? fmtEur(todaySummary.total_out_eur) : '…'}</div>
			</div>
			<div class="rounded-xl bg-teal-700 px-3 py-2.5">
				<div class="text-[10px] uppercase tracking-[0.5px] text-teal-200">Net</div>
				<div class="tabular-nums text-sm font-semibold mt-0.5 {(todaySummary?.net_eur ?? 0) >= 0 ? 'text-emerald-300' : 'text-red-300'}">
					{todaySummary ? (todaySummary.net_eur >= 0 ? '+' : '−') + fmtEur(Math.abs(todaySummary.net_eur)) : '…'}
				</div>
			</div>
		</div>
	</button>

	<!-- TAM GÖRÜNÜM (mobilde açıkken / masaüstünde her zaman) -->
	<div class="{expanded ? '' : 'hidden'} sm:block">
	<!-- Sekmeler -->
	<SegmentedControl options={PERIODS} value={period} onchange={setPeriod} fullWidth ariaLabel="Dönem seçimi" class="mb-3" />

	<!-- Tarih gezgini -->
	<div class="flex items-center justify-center gap-3 mb-4">
		<button type="button" onclick={() => nav(-1)} aria-label="Önceki dönem"
			class="touch-target w-9 h-9 flex items-center justify-center rounded-full border border-gray-200 text-gray-600 hover:bg-gray-100 cursor-pointer">
			<ChevronLeft size={16} />
		</button>
		<div class="text-center min-w-[190px]">
			<div class="tabular-nums text-sm font-semibold text-gray-900">{periodLabel || '…'}</div>
			<div class="text-[10px] tracking-[1.5px] text-gray-500">{PERIOD_TYPE_LABEL[period]}</div>
		</div>
		<button type="button" onclick={() => nav(1)} aria-label="Sonraki dönem" disabled={offsets[period] >= MAX_FUTURE_OFFSET}
			class="touch-target w-9 h-9 flex items-center justify-center rounded-full border border-gray-200 text-gray-600 hover:bg-gray-100 cursor-pointer disabled:opacity-40 disabled:cursor-default disabled:hover:bg-transparent">
			<ChevronRight size={16} />
		</button>
	</div>

	{#if canHold && holdMode}
		<div class="mb-3 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
			<PauseCircle size={15} class="shrink-0 text-amber-600" />
			<span><strong>Beklet modu açık.</strong> Bekleyen bir satıra dokununca beklemeye alınır (sarı olur; toplam/net/projeksiyona girmez, listede kalır). Sarı satıra tekrar dokununca geri alınır. Bitince butonu kapatın.</span>
		</div>
	{/if}

	{#if loading && !data}
		<div class="space-y-2 animate-pulse" aria-hidden="true">
			{#each Array(4) as _}
				<div class="h-8 bg-gray-100 rounded"></div>
			{/each}
		</div>
	{:else if data}
		<!-- Tek kalem/toplu satır — üç durum: normal · held (sarı, toplam-dışı) · tipping (kırmızı,
		     nakit yetmeyen ilk ödeme). Beklet modu + yetki varsa TIKLANABİLİR (tipping satırı DA
		     beklemeye alınabilir → nakit açığını kapatmak için); tıklanınca held→çıkar / normal→al. -->
		{#snippet bankMark(bank: string | null | undefined)}
			{@const bb = bankBadge(bank)}
			{#if bb}
				<span class="shrink-0 inline-flex items-center justify-center w-[18px] h-[18px] rounded-full text-[8px] font-bold leading-none select-none"
					style="background:{bb.bg};color:{bb.fg}" title={bank}>{bb.code}</span>
			{/if}
		{/snippet}

		{#snippet flowRow(name: string, amountLabel: string, members: SourceRef[], held: boolean, isTip: boolean, holdable: boolean, dense: boolean, bank: string | null)}
			{@const hm = holdableMembers(members)}
			{@const clickable = holdable && hm.length > 0}
			{@const divPad = dense ? 'pl-7' : 'pl-10'}
			{@const btnPad = dense ? 'pl-5' : 'pl-8'}
			{@const txt = held ? 'text-amber-800' : isTip ? 'text-red-700 font-semibold' : 'text-gray-700'}
			{@const bg = held ? 'bg-amber-50' : isTip ? 'bg-red-50' : ''}
			{@const icon = held ? 'text-amber-600' : isTip ? 'text-red-500' : 'text-amber-500'}
			{#if clickable}
				<button type="button" onclick={() => holdRow(hm, !held)} disabled={holdMutating}
					title={held ? 'Bekletmeyi kaldır' : 'Beklemeye al (nakit akıma dahil edilmez)'}
					aria-label="{cleanName(name)} {held ? 'bekletmeyi kaldır' : 'beklemeye al'}"
					class="w-full flex items-center gap-2 {btnPad} pr-2 py-1 rounded-md cursor-pointer text-left disabled:opacity-50 {held ? 'bg-amber-50 hover:bg-amber-100' : isTip ? 'bg-red-50 hover:bg-red-100' : 'hover:bg-amber-50'}">
					<PauseCircle size={14} class="shrink-0 {icon}" />
					{@render bankMark(bank)}
					<span class="text-[12px] truncate {txt}">{cleanName(name)}</span>
					{#if held}<span class="shrink-0 text-[9px] font-semibold uppercase tracking-wide text-amber-700 bg-amber-100 border border-amber-200 rounded px-1 py-0.5">beklemede</span>{/if}
					{#if isTip}<span class="shrink-0 text-[9px] font-semibold uppercase tracking-wide text-red-700 bg-red-100 border border-red-200 rounded px-1 py-0.5">⚠ nakit yetmiyor</span>{/if}
					<span class="ml-auto tabular-nums text-[12px] shrink-0 {txt}">{amountLabel}</span>
				</button>
			{:else}
				<div class="flex items-center gap-2 {divPad} pr-2 py-1 {bg} {bg ? 'rounded-md' : ''} {isTip ? '-mx-0.5 px-2.5' : ''}">
					{@render bankMark(bank)}
					<span class="text-[12px] truncate {txt}">{cleanName(name)}</span>
					{#if held}<span class="shrink-0 text-[9px] font-semibold uppercase tracking-wide text-amber-700 bg-amber-100 border border-amber-200 rounded px-1 py-0.5">beklemede</span>{/if}
					{#if isTip}<span class="shrink-0 text-[9px] font-semibold uppercase tracking-wide text-red-700 bg-red-100 border border-red-200 rounded px-1 py-0.5">⚠ nakit buraya yetmiyor</span>{/if}
					<span class="ml-auto tabular-nums text-[12px] shrink-0 {txt}">{amountLabel}</span>
				</div>
			{/if}
		{/snippet}

		<!-- Bir kategori grubunun accordion satırı + gün detayı (kategori görünümü) -->
		{#snippet catRows(side: SideKey, realized: boolean, groups: TGroup[])}
			{#each groups as g (g.label)}
				{@const k = `${side}:${realized ? 'g' : 'b'}:${g.label}`}
				<button type="button" onclick={() => toggle(k)} aria-expanded={!!open[k]}
					class="w-full flex items-center gap-2 px-2 py-2 border-t border-gray-100 hover:bg-gray-50 cursor-pointer text-left touch-target">
					<ChevronDown size={13} class="shrink-0 text-gray-500 transition-transform {open[k] ? '' : '-rotate-90'}" />
					<span class="text-[13px] font-semibold text-gray-900 truncate">{g.label}</span>
					<span class="text-[11px] text-gray-500 shrink-0">{g.item_count} işlem</span>
					{#if g.in_total === false}
						<span class="shrink-0 text-[9px] font-semibold uppercase tracking-wide text-gray-500 bg-gray-100 border border-gray-200 rounded px-1 py-0.5"
							title="Hesaplar arası virman — kolon toplamına ve net'e dahil değildir">toplam dışı</span>
					{/if}
					{#if !realized && (g.held_eur ?? 0) > 0}
						<span class="text-[10px] text-amber-600 shrink-0" title="Beklemeye alınan (toplama dahil değil)">+{fmtEur(g.held_eur ?? 0)} beklemede</span>
					{/if}
					<span class="ml-auto tabular-nums text-[13px] {g.in_total === false ? 'text-gray-500' : 'text-gray-800'} shrink-0">{fmtEur(g.total_eur)}</span>
				</button>
				{#if open[k]}
					<div class="pb-1">
						{#each groupItemsByDate(g.items) as day (day.date)}
							<div class="flex items-center justify-between gap-2 pl-8 pr-2 pt-2 pb-1 border-t border-gray-100">
								<span class="text-[10px] font-semibold uppercase tracking-wide text-gray-500">{day.label}</span>
								<span class="tabular-nums text-[10.5px] font-semibold text-gray-500 shrink-0">{fmtEur(day.totalEur)}</span>
							</div>
							<!-- Cari grubunda aynı firma birden çok ödeme → tek toplu satır; diğerlerinde her kalem ayrı.
							     Held (beklemeye alınmış) kalemler ayrı toplanır → sarı, gün toplamına katılmaz. -->
							{@const agg = AGGREGATE_LABELS.has(g.label)}
							{@const holdable = !realized && canHold && holdMode}
							{#each aggregateRows(day.items.filter((it) => !it.is_held), agg) as row, i (i)}
								{@render flowRow(row.name, rowAmountLabel(row), row.members, false, false, holdable, false, row.bank_name)}
							{/each}
							{#each aggregateRows(day.items.filter((it) => it.is_held), agg) as row, i (`h${i}`)}
								{@render flowRow(row.name, rowAmountLabel(row), row.members, true, false, holdable, false, row.bank_name)}
							{/each}
						{/each}
						{#if g.item_count > g.items.length}
							<p class="pl-8 pr-2 py-1 text-[11px] text-gray-500">+{g.item_count - g.items.length} kalem daha (Nakit Akım sayfasında tümü)</p>
						{/if}
					</div>
				{/if}
			{/each}
		{/snippet}

		<!-- Tarih görünümü: GÜN başlığı → KATEGORİ alt-başlığı (etiket + işlem sayısı + alt toplam) → satırlar
		     (cari: firma bazında toplu "N ödeme" rozetli; kredi/çek: her kalem ayrı) -->
		{#snippet dateRows(dv: { days: DateDay[]; hasMore: boolean; moreText: string }, tipping: { date: string; catLabel: string; rowIdx: number } | null, holdable: boolean)}
			{#each dv.days as day (day.date)}
				<div class="flex items-center justify-between gap-2 px-2 py-2 border-t border-gray-100 bg-gray-50">
					<span class="text-[11px] font-bold uppercase tracking-wide text-gray-700">{day.label}</span>
					<span class="tabular-nums text-[11px] font-semibold text-gray-600 shrink-0">{fmtEur(day.totalEur)}</span>
				</div>
				{#each day.cats as cat (cat.label)}
					<!-- Kategori başlığı — beklet modunda yanında TOPLU beklet düğmesi (kullanıcı isteği
					     2026-07-07): tıklanınca başlık altındaki TÜM bekletilebilir ödemeler beklemeye
					     alınır; hepsi zaten beklemedeyse tümünün bekletmesi kaldırılır (toggle). -->
					{@const catPending = holdableMembers(cat.rows.flatMap((r) => r.members))}
					{@const catHeld = holdableMembers(cat.heldRows.flatMap((r) => r.members))}
					{@const allHeld = catPending.length === 0 && catHeld.length > 0}
					<div class="flex items-center gap-2 pl-4 pr-2 pt-2 pb-0.5">
						{#if holdable && (catPending.length > 0 || catHeld.length > 0)}
							<button type="button" onclick={() => holdRow(allHeld ? catHeld : catPending, !allHeld)}
								disabled={holdMutating}
								title={allHeld ? 'Tümünün bekletmesini kaldır' : 'Tümünü beklemeye al (nakit akıma dahil edilmez)'}
								aria-label="{cat.label} — {allHeld ? 'tümünün bekletmesini kaldır' : 'tümünü beklemeye al'}"
								class="flex items-center gap-1.5 min-w-0 -ml-1 pl-1 pr-1.5 py-0.5 rounded-md cursor-pointer disabled:opacity-50 {allHeld ? 'bg-amber-50 hover:bg-amber-100' : 'hover:bg-amber-50'}">
								<PauseCircle size={13} class="shrink-0 {allHeld ? 'text-amber-600' : 'text-amber-500'}" />
								<span class="text-[11px] font-semibold truncate {allHeld ? 'text-amber-800' : 'text-gray-700'}">{cat.label}</span>
							</button>
						{:else}
							<span class="text-[11px] font-semibold text-gray-700 truncate">{cat.label}</span>
						{/if}
						{#if !cat.inTotal}
							<span class="shrink-0 text-[9px] font-semibold uppercase tracking-wide text-gray-500 bg-gray-100 border border-gray-200 rounded px-1 py-0.5"
								title="Hesaplar arası virman — gün toplamına ve net'e dahil değildir">toplam dışı</span>
						{/if}
						<span class="ml-auto tabular-nums text-[10.5px] font-semibold text-gray-500 shrink-0">{fmtEur(cat.totalEur)}</span>
					</div>
					{#each cat.rows as row, i (i)}
						{@const isTip = !!tipping && day.date === tipping.date && cat.label === tipping.catLabel && i === tipping.rowIdx}
						{@render flowRow(row.name, row.amountLabel, row.members, false, isTip, holdable, true, row.bank_name)}
					{/each}
					<!-- Held (beklemeye alınmış) satırlar — sarı, kategori toplamına katılmaz -->
					{#each cat.heldRows as row, i (`h${i}`)}
						{@render flowRow(row.name, row.amountLabel, row.members, true, false, holdable, true, row.bank_name)}
					{/each}
				{/each}
			{/each}
			{#if dv.hasMore}
				<p class="px-4 py-1.5 text-[11px] text-gray-500">{dv.moreText}</p>
			{/if}
		{/snippet}

		<!-- T-account gövdesi: üst 2px lacivert çizgi; ortada dikey ayraç (masaüstü) -->
		<div class="border-t-2 border-teal-700 grid grid-cols-1 sm:grid-cols-2 {loading ? 'opacity-60' : ''}">
			{#each COLS as col (col.side)}
				{@const st = segTotals(col.side)}
				{@const realized = sideView[col.side] === 'gerceklesen'}
				{@const groups = col.side === 'giris' ? data.giris : data.cikis}
				{@const filtered = catGroups(groups, realized)}
				{@const dv = dateView[col.side] ? dateBuckets(groups, realized) : null}
				<div class="{col.side === 'cikis' ? 'sm:border-l-2 sm:border-teal-700 border-t-2 border-teal-700 sm:border-t-0' : ''} px-0 sm:px-3 py-2 {col.side === 'giris' ? 'sm:pr-3 sm:pl-0' : ''}">
					<!-- Sütun başlığı = tarih görünümü toggle'ı (takvim ikonu) -->
					<button type="button" onclick={() => toggleDateView(col.side)}
						aria-pressed={dateView[col.side]}
						title={dateView[col.side] ? 'Kategoriye göre sırala' : 'Tarihe göre sırala'}
						class="touch-target w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-50 cursor-pointer text-left">
						<span class="flex items-center gap-2 text-base sm:text-lg font-semibold tracking-wide uppercase text-gray-800">
							<span class="w-3.5 h-3.5 rounded-sm {col.accent}"></span>{col.title}
							<CalendarDays size={15} class="{dateView[col.side] ? col.totalCls : 'text-gray-400'} transition-colors" />
						</span>
						<span class="tabular-nums text-lg sm:text-xl font-semibold {col.totalCls}">{fmtEur(col.side === 'giris' ? data.total_in_eur : data.total_out_eur)}</span>
					</button>

					<!-- SEGMENT: ✓ Gerçekleşen | Bekleyen (yerinde swap; ayrı panel yok) -->
					{#if st.hasData}
						<div role="tablist" aria-label="{col.title} durum" class="flex gap-1 bg-gray-100 rounded-lg p-1 mx-2 mt-1 mb-2">
							<button type="button" role="tab" aria-selected={realized} onclick={() => setSegment(col.side, 'gerceklesen')}
								class="touch-target flex-1 flex flex-col items-start gap-0 px-2.5 py-1 rounded-md cursor-pointer transition-colors {realized ? 'bg-white shadow-sm' : 'hover:bg-white/50'}">
								<span class="text-[9.5px] uppercase tracking-wide text-emerald-700">✓ Gerçekleşen</span>
								<span class="tabular-nums text-[12.5px] font-semibold text-emerald-700">{fmtEur(st.realized)}</span>
							</button>
							<button type="button" role="tab" aria-selected={!realized} onclick={() => setSegment(col.side, 'bekleyen')}
								class="touch-target flex-1 flex flex-col items-start gap-0 px-2.5 py-1 rounded-md cursor-pointer transition-colors {!realized ? 'bg-white shadow-sm' : 'hover:bg-white/50'}">
								<span class="text-[9.5px] uppercase tracking-wide {!realized ? 'text-gray-700' : 'text-gray-500'}">Bekleyen</span>
								<span class="tabular-nums text-[12.5px] font-semibold {!realized ? 'text-gray-900' : 'text-gray-500'}">{fmtEur(st.pending)}</span>
							</button>
						</div>
					{/if}

					<!-- İçerik: boş / tarih görünümü / kategori görünümü -->
					{#if filtered.length === 0}
						<p class="px-2 py-3 text-xs text-gray-500">
							{!st.hasData ? 'Bu dönemde kayıt yok.' : realized ? 'Gerçekleşen işlem yok.' : 'Bekleyen işlem yok.'}
						</p>
					{:else if dv}
						{@render dateRows(dv, col.side === 'cikis' ? tippingCikis : null, !realized && canHold && holdMode)}
					{:else}
						{@render catRows(col.side, realized, filtered)}
					{/if}
				</div>
			{/each}
		</div>

		<!-- Net bant -->
		<div class="mt-3 rounded-xl bg-teal-700 text-white flex items-center justify-between gap-3 px-4 py-3">
			<span class="text-xs sm:text-sm text-gray-200">Net Nakit Akım · {periodLabel}</span>
			<span class="tabular-nums text-lg font-semibold {data.net_eur >= 0 ? 'text-emerald-300' : 'text-red-300'}">
				{data.net_eur >= 0 ? '+' : '−'}{fmtEur(Math.abs(data.net_eur))}
			</span>
		</div>
		{#if data.skipped_no_rate > 0}
			<p class="mt-2 text-[11px] text-amber-700">{data.skipped_no_rate} kalem kur bilgisi olmadığından hesaba katılamadı.</p>
		{/if}
	{/if}

	</div>

	<!-- Bekleme Listesi (beklemeye alınmış kalemler) — Vadesi Geçenler'in üstünde -->
	<HeldList />

	<!-- Vadesi Geçenler — Nakit Akım kartının EN ALTINDA (kullanıcı isteği 2026-07-06) -->
	<OverdueList />
</div>
