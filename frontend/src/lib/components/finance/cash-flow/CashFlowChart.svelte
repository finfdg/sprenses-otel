<!--
	CashFlowChart.svelte — Nakit Akım grafiği (Finans → Nakit Akım sayfası, 2026-08-19 kullanıcı isteği).

	Dönem serisi (Günlük/Haftalık/Aylık/Yıllık), ORTAK x eksenli İKİ PANEL:
	  ÜST — AKIM (ıraksayan sütun):
	    · sıfırın üstü = TAHSİLATLAR (gerçekleşen koyu yeşil + planlı açık yeşil)
	    · sıfırın altı = ÖDEMELER    (gerçekleşen pirinç + planlı açık pirinç)
	    · yanındaki DAR kesik-çizgili kırmızı sütun = VADESİ GEÇEN (ödenmemiş/tahsil edilmemiş)
	  ALT — BANKA BAKİYESİ: dönem sonu bakiye eğrisi; 0'ın altı kırmızı.

	NEDEN İKİ PANEL (tek grafikte çift eksen DEĞİL): aylık akım ~€1,9M, banka nakdi ~€46K —
	tek ölçekte bakiye düz bir şeride iner. Çift eksen ise sıfırı hizalamak için 0'ın üstünde
	ve altında FARKLI ölçek katsayısı üretiyordu (€497B/yarım ekran ↔ €3,6M/yarım ekran) →
	eğrinin eğimi yanıltıcı okunuyordu. Ayrı panel her iki ölçeği de dürüst tutar.

	VADESİ GEÇEN neden AYRI sütun (üst üste yığılmıyor): tutarı toplama/net'e GİRMEZ —
	"ödenmedi, para hâlâ bankada" kuralı (eur_balances 2026-07-06 notu). Aynı sütuna yığmak
	"toplama dahil" yanılsaması yaratırdı; kesik çizgili ayrı sütun + lejanttaki "toplam dışı"
	ibaresi bunu görsel olarak da söyler. Bakiye eğrisi de vadesi geçeni DÜŞMEZ (aynı kural).

	VERİ: GET /finance/cash-flow/chart (akım + anlık hesap bakiyeleri) — her kova AYNI
	(period, offset) için T-Hesap cetveliyle birebir aynı sayıyı verir (backend "tek sayı
	kuralı", chart.py docstring + tests/test_cash_flow_chart.py).
	BAKİYE EĞRİSİ: `cashFlowCache.eurBalances.daily` — RunwayChart ve PDF raporuyla aynı
	`compute_eur_balances` çekirdeği (sayfa onu WS-geçersizlemeli cache'te tutuyor; dönem
	sekmesi her değiştiğinde ağır tam-taramayı yeniden koşturmamak için buradan okunur).
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import { WS_EVENT } from '$lib/constants/realtime';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import { cashFlowCache, loadCashFlowEurBalances, isEurBalancesStale } from '$lib/stores/cashflow.svelte';
	import { ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Landmark, RotateCcw } from 'lucide-svelte';

	type Bucket = {
		offset: number; key: string; label: string; label_long: string;
		start_date: string; end_date: string; is_current: boolean; is_past: boolean;
		income_realized: number; income_planned: number; income_overdue: number;
		income_held: number; income_info: number;
		expense_realized: number; expense_planned: number; expense_overdue: number;
		expense_held: number; expense_info: number;
		income_count: number; expense_count: number; overdue_count: number;
		income_total: number; expense_total: number; net_eur: number;
	};
	type Account = {
		id: number; bank_name: string; account_no: string | null; iban_tail: string | null;
		currency: string; is_active: boolean; last_balance: number | null;
		blocked_amount: number; effective_balance: number | null; balance_eur: number | null;
		last_movement_date: string | null;
	};
	type ChartData = {
		period: string; offset: number; back: number; forward: number; today: string;
		start_date: string; end_date: string; buckets: Bucket[]; accounts: Account[];
		total_balance_eur: number; eur_rate: number | null;
		overdue_expense_eur: number; overdue_income_eur: number; skipped_no_rate: number;
	};

	const PERIODS = [
		{ value: 'daily', label: 'Günlük' },
		{ value: 'weekly', label: 'Haftalık' },
		{ value: 'monthly', label: 'Aylık' },
		{ value: 'yearly', label: 'Yıllık' },
	];
	const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
	const MONTHS_SHORT = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
	// Gezinme sınırları — backend Query(ge=-120, le=24) ile aynı
	const MIN_OFFSET = -120;
	const MAX_OFFSET = 24;
	// SVG mantıksal kutuları (preserveAspectRatio="none" → x ekseni kaba göre esner; metinler
	// SVG'de DEĞİL HTML katmanında → yazı tipi her ekranda net kalır, RunwayChart deseni.
	// Çizgi kalınlıkları vector-effect="non-scaling-stroke" ile esnemeden sabit kalır.)
	const VW = 1000;
	const FLOW_H = 178, FLOW_TOP = 8, FLOW_BOTTOM = 170;
	const BAL_H = 86, BAL_TOP = 10, BAL_BOTTOM = 76;
	// Palet — app.css @theme token'larıyla aynı değerler (SVG'de literal renk zorunlu)
	const C = {
		incomeRealized: '#047857',  // emerald-700
		incomePlanned: '#6ee7b7',   // emerald-300
		expenseRealized: '#bd9a45', // brass
		expensePlanned: '#e8c979',  // brass-light
		overdue: '#dc2626',         // red-600
		balance: '#1b2b45',         // teal-700 (lacivert primary)
		balanceNeg: '#dc2626',
		today: '#bd9a45',
		zero: '#a09a88',            // gray-400
	};

	// State
	let period = $state<'daily' | 'weekly' | 'monthly' | 'yearly'>('monthly');
	let offsets = $state<Record<string, number>>({ daily: 0, weekly: 0, monthly: 0, yearly: 0 });
	let data = $state<ChartData | null>(null);
	let loading = $state(true);
	let hoverIdx = $state<number | null>(null);
	let showAccounts = $state(false);
	// Çizim alanının ÖLÇÜLEN genişliği — x ekseni etiket sıklığı buradan hesaplanır.
	// Sabit "en çok 13 etiket" kuralı mobilde kırılıyordu: 375px ekranda hücre 8px kalıp
	// "19 Ağu" kırpılıyordu (2026-08-19 mobil kontrolü). Etiket başına ~46px gerekir.
	let plotWidth = $state(0);
	const LABEL_MIN_PX = 46;
	const cache = new Map<string, ChartData>();

	function fmtEur(n: number): string {
		return '€' + new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(Math.round(n));
	}
	function fmtEurSigned(n: number): string {
		return (n < 0 ? '−' : '') + fmtEur(Math.abs(n));
	}
	/** Eksen etiketi — CashFlowSummaryCards konvansiyonu: milyon üstü "M", altı tam sayı. */
	function fmtEurShort(n: number): string {
		const abs = Math.abs(n);
		const sign = n < 0 ? '−' : '';
		if (abs >= 1_000_000) return sign + '€' + (abs / 1_000_000).toFixed(1).replace('.', ',') + 'M';
		return sign + fmtEur(abs);
	}
	const CUR_SYM: Record<string, string> = { TRY: '₺', EUR: '€', USD: '$', GBP: '£' };
	function fmtNative(n: number, currency: string): string {
		const sym = CUR_SYM[currency] || currency + ' ';
		return sym + new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 }).format(Math.round(n));
	}
	function fmtDay(iso: string): string {
		const [y, m, d] = iso.split('-').map(Number);
		return `${d} ${MONTHS_SHORT[m - 1]} ${y}`;
	}

	/** Kova sonundaki (<=) son bilinen banka bakiyesi — eur_balances.daily tek kaynak. */
	function balanceAt(endDate: string): number | null {
		const daily = cashFlowCache.eurBalances?.daily;
		if (!daily) return null;
		let best: string | null = null;
		for (const key in daily) {
			if (key <= endDate && (best === null || key > best)) best = key;
		}
		return best === null ? null : daily[best].balance_eur;
	}

	// Pencere toplamları — grafiğin üstündeki özet satırı
	const totals = $derived.by(() => {
		const buckets = data?.buckets ?? [];
		const sum = (fn: (b: Bucket) => number) => buckets.reduce((s, b) => s + fn(b), 0);
		return {
			income: sum((b) => b.income_total),
			expense: sum((b) => b.expense_total),
			net: sum((b) => b.net_eur),
			overdueExpense: data?.overdue_expense_eur ?? 0,
			overdueIncome: data?.overdue_income_eur ?? 0,
			held: sum((b) => b.expense_held + b.income_held),
		};
	});

	// ── AKIM paneli geometrisi (sütunlar) ──
	const flow = $derived.by(() => {
		const buckets = data?.buckets ?? [];
		if (!buckets.length) return null;

		const n = buckets.length;
		const slot = VW / n;
		const plotH = FLOW_BOTTOM - FLOW_TOP;
		// Vadesi geçen sütunu toplama girmese de kutuya SIĞMALI → tavan hesabına dahil
		const upMax = Math.max(1, ...buckets.map((b) => Math.max(b.income_total, b.income_overdue)));
		const downMax = Math.max(1, ...buckets.map((b) => Math.max(b.expense_total, b.expense_overdue)));
		const zeroY = FLOW_TOP + (upMax / (upMax + downMax)) * plotH;
		const upPx = (v: number) => (v / upMax) * (zeroY - FLOW_TOP);
		const downPx = (v: number) => (v / downMax) * (FLOW_BOTTOM - zeroY);
		// Vadesi geçen sütunu TOPLAMA GÖRE çok küçük kalabilir (€9K ↔ €1,9M tavan → 0,7px):
		// kesik çizgili çerçeve o boyutta okunmaz bir kırmızı lekeye döner. Sıfır olmayan tutar
		// en az OVERDUE_MIN_PX yüksekliğinde çizilir → "burada vadesi geçen VAR" sinyali görünür.
		// Ölçek bozulması bilinçli ve zararsız: bu sütun zaten toplam/net dışıdır, büyüklüğü
		// ipucu balonundan okunur (kullanıcı 2026-08-19 isteğinin özü "görünsün").
		const OVERDUE_MIN_PX = 3;
		const ovdPx = (v: number, px: (n: number) => number) => (v > 0 ? Math.max(OVERDUE_MIN_PX, px(v)) : 0);

		// Sütun yerleşimi: ana sütun + (her zaman ayrılan) dar vadesi-geçen sütunu. Yer HER
		// kovada ayrılır → vadesi geçeni olmayan kovada sütun kaymaz (göz ekseni sabit kalır).
		const mainW = slot * 0.40;
		const ovdW = slot * 0.16;
		const gap = slot * 0.05;
		const groupW = mainW + gap + ovdW;

		const cols = buckets.map((b, i) => {
			const x0 = i * slot + (slot - groupW) / 2;
			const incR = upPx(b.income_realized);
			const incP = upPx(b.income_planned);
			const expR = downPx(b.expense_realized);
			const expP = downPx(b.expense_planned);
			return {
				bucket: b,
				centerPct: (((i + 0.5) * slot) / VW) * 100,
				mainX: x0, mainW, ovdX: x0 + mainW + gap, ovdW,
				// Tahsilat: gerçekleşen sıfırdan yukarı, planlı onun üstüne yığılır
				incRealY: zeroY - incR, incRealH: incR,
				incPlanY: zeroY - incR - incP, incPlanH: incP,
				// Ödeme: gerçekleşen sıfırdan aşağı, planlı onun altına yığılır
				expRealY: zeroY, expRealH: expR,
				expPlanY: zeroY + expR, expPlanH: expP,
				// Vadesi geçen (toplam dışı) — kesik çizgili dar sütun
				ovdUpY: zeroY - ovdPx(b.income_overdue, upPx), ovdUpH: ovdPx(b.income_overdue, upPx),
				ovdDownY: zeroY, ovdDownH: ovdPx(b.expense_overdue, downPx),
				// Kesik çizgi ("toplam dışı" işareti) yalnız okunacak boyutta; minimum yükseklikteki
				// sütunda kesikler noktalara dönüp lekeye benziyordu → orada düz çerçeve
				ovdDash: Math.max(ovdPx(b.income_overdue, upPx), ovdPx(b.expense_overdue, downPx)) >= 8,
			};
		});

		const todayIdx = buckets.findIndex((b) => b.is_current);
		// BUGÜN çizgisi kovanın ORTASINA değil, günün kova içindeki GERÇEK oranına konur
		// (aylık görünümde 19 Ağustos ayın %61'i → çizgi oradan geçer; ortaya koymak
		// "ayın yarısı geçti" gibi yanlış okunuyordu).
		let todayFrac = 0.5;
		if (todayIdx >= 0 && data?.today) {
			const b = buckets[todayIdx];
			const ms = (iso: string) => new Date(iso + 'T00:00:00').getTime();
			const span = ms(b.end_date) + 86400000 - ms(b.start_date);
			todayFrac = span > 0 ? Math.min(1, Math.max(0, (ms(data.today) - ms(b.start_date)) / span)) : 0.5;
		}
		// İlk GELECEK kova — arkasına açık bant çizilir ("buradan sonrası plan")
		const futureIdx = buckets.findIndex((b) => !b.is_past && !b.is_current);
		return {
			n, slot, cols, zeroY, upMax, downMax,
			zeroPct: (zeroY / FLOW_H) * 100,
			todayXPct: todayIdx >= 0 ? (((todayIdx + todayFrac) * slot) / VW) * 100 : null,
			futureXPct: futureIdx >= 0 ? ((futureIdx * slot) / VW) * 100 : null,
			// Etiket sıklığı ÖLÇÜLEN genişlikten (masaüstünde ~13, mobilde ~5 etiket). Adımlar
			// BUGÜNE sabitlenir → bugün her zaman etiketli olur ve komşusuyla çakışmaz (sabit
			// 0'a sabitlenince "19 Ağu" ile "20 Ağu" yan yana basılıyordu).
			labelStep: Math.max(1, Math.ceil(n / Math.max(2, Math.floor((plotWidth || 640) / LABEL_MIN_PX)))),
			labelAnchor: todayIdx >= 0 ? todayIdx : 0,
		};
	});

	// ── BAKİYE paneli geometrisi (ayrı ölçek, ortak x ekseni) ──
	const balance = $derived.by(() => {
		const buckets = data?.buckets ?? [];
		if (!buckets.length || !flow) return null;
		const values = buckets.map((b) => balanceAt(b.end_date));
		const known = values.filter((v): v is number => v !== null);
		if (!known.length) return null;

		const hi = Math.max(0, ...known);
		const lo = Math.min(0, ...known);
		const pad = (hi - lo) * 0.12 || 1;
		const top = hi + pad, bottom = lo - pad;
		const mapY = (v: number) => BAL_BOTTOM - ((v - bottom) / (top - bottom)) * (BAL_BOTTOM - BAL_TOP);
		const zeroY = mapY(0);

		const pts = values.map((v, i) =>
			v === null ? null : { x: i * flow.slot + flow.slot / 2, y: mapY(v), v, idx: i },
		);
		// 0 çizgisinde renk değiştiren ayrı segmentler (RunwayChart deseni — dikey gradyan
		// 0'a yakın seyreden çizgide iki rengi harmanlayıp geçişi bulanıklaştırıyordu)
		const segments: { d: string; color: string }[] = [];
		let run: { x: number; y: number }[] = [];
		let runPos = true;
		const flush = () => {
			if (run.length >= 2) {
				segments.push({
					d: run.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' '),
					color: runPos ? C.balance : C.balanceNeg,
				});
			}
			run = [];
		};
		for (let i = 0; i < pts.length; i++) {
			const p = pts[i];
			if (p === null) { flush(); continue; }
			const pos = p.v >= 0;
			if (run.length && pos !== runPos) {
				const prev = run[run.length - 1];
				const prevV = (pts[i - 1] as { v: number }).v;
				const f = (0 - prevV) / (p.v - prevV);
				const cross = { x: prev.x + f * (p.x - prev.x), y: zeroY };
				run.push(cross);
				flush();
				run = [cross];
			}
			runPos = pos;
			run.push({ x: p.x, y: p.y });
		}
		flush();

		const firstNegIdx = values.findIndex((v) => v !== null && v < 0);
		return {
			points: pts, segments, hi, lo, zeroY,
			zeroPct: (zeroY / BAL_H) * 100,
			firstNegLabel: firstNegIdx >= 0 ? buckets[firstNegIdx].label_long : null,
			values,
		};
	});

	// Anlık banka hesapları — bakiyesi olanlar büyükten küçüğe; sıfır/hareketsizler gizli
	const accountRows = $derived.by(() =>
		(data?.accounts ?? [])
			.filter((a) => a.balance_eur !== null && Math.abs(a.balance_eur) >= 1)
			.sort((a, b) => (b.balance_eur ?? 0) - (a.balance_eur ?? 0)),
	);
	const emptyAccountCount = $derived((data?.accounts?.length ?? 0) - accountRows.length);

	const periodLabel = $derived.by(() => {
		if (!data) return '';
		const [sy, sm, sd] = data.start_date.split('-').map(Number);
		const [ey, em, ed] = data.end_date.split('-').map(Number);
		return `${sd} ${MONTHS[sm - 1]} ${sy} – ${ed} ${MONTHS[em - 1]} ${ey}`;
	});

	async function load() {
		const off = offsets[period];
		const key = `${period}:${off}`;
		const cached = cache.get(key);
		if (cached) { data = cached; loading = false; return; }
		loading = true;
		try {
			const res = await api.get<ChartData>(`/finance/cash-flow/chart?period=${period}&offset=${off}`);
			cache.set(key, res);
			data = res;
		} catch (err) {
			console.error('Nakit akım grafiği yüklenemedi:', err);
			showToast('Nakit akım grafiği yüklenemedi', 'error');
		} finally {
			loading = false;
		}
	}

	// WS yankı koruması + tekil-uçuş (CashFlowTAccount ile aynı desen): her finans mutasyonu
	// hem doğrudan yenileme hem broadcast yankısı üretir; art arda istek 429'a takılıp grafiği
	// sessizce bayat bırakıyordu.
	let refreshInFlight: Promise<void> | null = null;
	let refreshQueued = false;

	async function refresh(): Promise<void> {
		if (refreshInFlight) { refreshQueued = true; return refreshInFlight; }
		refreshInFlight = (async () => {
			try {
				cache.clear();
				await load();
				// Bakiye eğrisi tek kaynağı. force=false BİLEREK: sayfanın WS handler'ı
				// (refreshCashFlowLight/Full) aynı event'te force=true ile zaten tazeliyor →
				// bu çağrı store'un tekil-uçuş guard'ında o isteğe biner, İKİNCİ istek açmaz
				// (eur-balances 30/dk sınırlı ağır tam-tarama). Sayfa tazelemese bile bileşen
				// kendi başına doğru kalır: uçuş yoksa isteği kendisi açar.
				if (isEurBalancesStale()) await loadCashFlowEurBalances();
			} finally {
				refreshInFlight = null;
			}
		})();
		await refreshInFlight;
		if (refreshQueued) { refreshQueued = false; await refresh(); }
	}

	function setPeriod(v: string) {
		period = v as typeof period;
		hoverIdx = null;
		load();
	}
	function nav(delta: number) {
		const next = offsets[period] + delta;
		if (next < MIN_OFFSET || next > MAX_OFFSET) return;
		offsets[period] = next;
		hoverIdx = null;
		load();
	}
	function resetOffset() {
		if (offsets[period] === 0) return;
		offsets[period] = 0;
		hoverIdx = null;
		load();
	}

	function onPlotMove(ev: PointerEvent) {
		if (!flow) return;
		const rect = (ev.currentTarget as HTMLElement).getBoundingClientRect();
		if (!rect.width) return;
		const idx = Math.floor(((ev.clientX - rect.left) / rect.width) * flow.n);
		const clamped = Math.min(flow.n - 1, Math.max(0, idx));
		if (clamped !== hoverIdx) hoverIdx = clamped;
	}
	function onPlotLeave() {
		hoverIdx = null;
	}

	onMount(() => {
		load();
		// Bakiye eğrisi eur_balances'tan gelir — sayfa onu yüklemiş olabilir; bayatsa tazele
		if (isEurBalancesStale()) loadCashFlowEurBalances();
		const unsub = onWsEvent(WS_EVENT.FINANCE_UPDATED, () => refresh());
		return () => unsub();
	});
</script>

<section class="bg-white border border-gray-200 rounded-2xl shadow-sm p-4 sm:p-5 mb-4">
	<!-- Başlık + dönem sekmeleri + gezinme -->
	<div class="flex flex-wrap items-start justify-between gap-3 mb-3">
		<div>
			<h2 class="text-[17px] text-gray-900">Nakit Akım Grafiği</h2>
			<p class="text-xs text-gray-500 mt-0.5">
				Tahsilat / ödeme kırılımı ve banka bakiyesi · <span class="tabular-nums">{periodLabel}</span>
			</p>
		</div>
		<div class="flex items-center gap-2 flex-wrap">
			<SegmentedControl
				options={PERIODS}
				value={period}
				onchange={setPeriod}
				size="sm"
				ariaLabel="Grafik dönemi"
			/>
			<div class="flex items-center gap-1">
				<button type="button" onclick={() => nav(-1)} disabled={offsets[period] <= MIN_OFFSET}
					aria-label="Önceki dönem"
					class="touch-target flex items-center justify-center rounded-lg border border-gray-200 px-2 py-1.5 text-gray-600 cursor-pointer
						hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed
						focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500">
					<ChevronLeft size={16} aria-hidden="true" />
				</button>
				<button type="button" onclick={resetOffset} disabled={offsets[period] === 0}
					aria-label="Bugüne dön" title="Bugüne dön"
					class="touch-target flex items-center justify-center rounded-lg border border-gray-200 px-2 py-1.5 text-gray-600 cursor-pointer
						hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed
						focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500">
					<RotateCcw size={15} aria-hidden="true" />
				</button>
				<button type="button" onclick={() => nav(1)} disabled={offsets[period] >= MAX_OFFSET}
					aria-label="Sonraki dönem"
					class="touch-target flex items-center justify-center rounded-lg border border-gray-200 px-2 py-1.5 text-gray-600 cursor-pointer
						hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed
						focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500">
					<ChevronRight size={16} aria-hidden="true" />
				</button>
			</div>
		</div>
	</div>

	<!-- Pencere toplamları — kart DEĞİL, panel-içi özet satırı (StatCard sayfa başında) -->
	<div class="flex flex-wrap items-center gap-x-5 gap-y-1.5 mb-3 text-[13px]">
		<span class="text-gray-500">Tahsilat <span class="tabular-nums font-semibold text-emerald-700">{fmtEur(totals.income)}</span></span>
		<span class="text-gray-500">Ödeme <span class="tabular-nums font-semibold text-brass-dark">{fmtEur(totals.expense)}</span></span>
		<span class="text-gray-500">Net <span class="tabular-nums font-semibold {totals.net < 0 ? 'text-red-700' : 'text-teal-700'}">{fmtEurSigned(totals.net)}</span></span>
		{#if totals.overdueExpense > 0}
			<span class="text-gray-500">Vadesi geçen ödeme <span class="tabular-nums font-semibold text-red-700">{fmtEur(totals.overdueExpense)}</span></span>
		{/if}
		{#if totals.overdueIncome > 0}
			<span class="text-gray-500">Vadesi geçen tahsilat <span class="tabular-nums font-semibold text-red-700">{fmtEur(totals.overdueIncome)}</span></span>
		{/if}
		{#if totals.held > 0}
			<span class="text-gray-500">Beklemede <span class="tabular-nums font-semibold text-gray-700">{fmtEur(totals.held)}</span></span>
		{/if}
	</div>

	{#if loading && !data}
		<div class="h-[300px] bg-gray-100 rounded-xl animate-pulse" aria-hidden="true"></div>
	{:else if !flow}
		<div class="h-[300px] flex items-center justify-center text-sm text-gray-500">
			Bu dönemde nakit akım hareketi yok.
		</div>
	{:else}
		<div style="--axis-w:4.25rem">
			<div class="flex items-stretch gap-1">
				<!-- Sol eksen etiketleri (iki panel için ayrı ölçek) -->
				<div class="shrink-0 text-right pr-1" style="width:var(--axis-w)" aria-hidden="true">
					<div class="relative" style="height:{FLOW_H}px">
						<span class="absolute right-0 tabular-nums text-[10px] text-emerald-700" style="top:0;transform:translateY(-2px)">{fmtEurShort(flow.upMax)}</span>
						<span class="absolute right-0 tabular-nums text-[10px] text-gray-500" style="top:{flow.zeroPct}%;transform:translateY(-50%)">€0</span>
						<span class="absolute right-0 tabular-nums text-[10px] text-brass-dark" style="bottom:0;transform:translateY(2px)">{fmtEurShort(flow.downMax)}</span>
					</div>
					{#if balance}
						<div class="relative mt-1.5" style="height:{BAL_H}px">
							<span class="absolute right-0 tabular-nums text-[10px] text-teal-700" style="top:0">{fmtEurShort(balance.hi)}</span>
							{#if balance.lo < 0}
								<span class="absolute right-0 tabular-nums text-[10px] text-red-700" style="bottom:0">{fmtEurShort(balance.lo)}</span>
							{:else}
								<span class="absolute right-0 tabular-nums text-[10px] text-gray-500" style="bottom:0">€0</span>
							{/if}
						</div>
					{/if}
				</div>

				<!-- Çizim alanı: üstte akım sütunları, altta bakiye eğrisi (ORTAK x ekseni) -->
				<div class="relative flex-1 min-w-0" bind:clientWidth={plotWidth} style="touch-action:none" role="img"
					aria-label="Dönem bazlı tahsilat, ödeme ve banka bakiyesi grafiği — üzerinde gezinerek dönem detayını görün"
					onpointermove={onPlotMove} onpointerdown={onPlotMove} onpointerleave={onPlotLeave}>

					<!-- ÜST PANEL — AKIM -->
					<svg viewBox="0 0 {VW} {FLOW_H}" preserveAspectRatio="none" class="w-full block" style="height:{FLOW_H}px" aria-hidden="true">
						{#if flow.futureXPct !== null}
							<!-- Gelecek dönem bandı — "buradan sonrası plan" -->
							<rect x={(flow.futureXPct / 100) * VW} y={FLOW_TOP} width={VW - (flow.futureXPct / 100) * VW}
								height={FLOW_BOTTOM - FLOW_TOP} fill="#f4f0e7" opacity="0.7" />
						{/if}
						<line x1="0" y1={flow.zeroY} x2={VW} y2={flow.zeroY} stroke={C.zero} stroke-width="1" vector-effect="non-scaling-stroke" />

						{#each flow.cols as col (col.bucket.key)}
							<!-- TAHSİLAT (yukarı) -->
							{#if col.incRealH > 0.4}
								<rect x={col.mainX} y={col.incRealY} width={col.mainW} height={col.incRealH} fill={C.incomeRealized} />
							{/if}
							{#if col.incPlanH > 0.4}
								<rect x={col.mainX} y={col.incPlanY} width={col.mainW} height={col.incPlanH} fill={C.incomePlanned} />
							{/if}
							<!-- ÖDEME (aşağı) -->
							{#if col.expRealH > 0.4}
								<rect x={col.mainX} y={col.expRealY} width={col.mainW} height={col.expRealH} fill={C.expenseRealized} />
							{/if}
							{#if col.expPlanH > 0.4}
								<rect x={col.mainX} y={col.expPlanY} width={col.mainW} height={col.expPlanH} fill={C.expensePlanned} />
							{/if}
							<!-- VADESİ GEÇEN — kesik çizgili çerçeve = "toplam dışı" -->
							{#if col.ovdDownH > 0}
								<rect x={col.ovdX} y={col.ovdDownY} width={col.ovdW} height={col.ovdDownH}
									fill={C.overdue} fill-opacity={col.ovdDash ? 0.22 : 0.45} stroke={C.overdue} stroke-width="1.2"
									stroke-dasharray={col.ovdDash ? '3 2' : undefined} vector-effect="non-scaling-stroke" />
							{/if}
							{#if col.ovdUpH > 0}
								<rect x={col.ovdX} y={col.ovdUpY} width={col.ovdW} height={col.ovdUpH}
									fill={C.overdue} fill-opacity={col.ovdDash ? 0.22 : 0.45} stroke={C.overdue} stroke-width="1.2"
									stroke-dasharray={col.ovdDash ? '3 2' : undefined} vector-effect="non-scaling-stroke" />
							{/if}
						{/each}
					</svg>

					<!-- ALT PANEL — BANKA BAKİYESİ -->
					{#if balance}
						<svg viewBox="0 0 {VW} {BAL_H}" preserveAspectRatio="none" class="w-full block mt-1.5" style="height:{BAL_H}px" aria-hidden="true">
							{#if flow.futureXPct !== null}
								<rect x={(flow.futureXPct / 100) * VW} y="0" width={VW - (flow.futureXPct / 100) * VW}
									height={BAL_H} fill="#f4f0e7" opacity="0.7" />
							{/if}
							<line x1="0" y1={balance.zeroY} x2={VW} y2={balance.zeroY} stroke={C.overdue}
								stroke-width="1" stroke-dasharray="4 4" opacity="0.55" vector-effect="non-scaling-stroke" />
							{#each balance.segments as seg}
								<path d={seg.d} fill="none" stroke={seg.color} stroke-width="2" stroke-linecap="round"
									stroke-linejoin="round" vector-effect="non-scaling-stroke" />
							{/each}
							{#each balance.points as p}
								{#if p}
									<circle cx={p.x} cy={p.y} r="2.4" fill="#fffdf7" stroke={p.v >= 0 ? C.balance : C.balanceNeg}
										stroke-width="1.6" vector-effect="non-scaling-stroke" />
								{/if}
							{/each}
						</svg>
					{/if}

					<!-- BUGÜN işareti — iki paneli birden keser -->
					{#if flow.todayXPct !== null}
						<div class="absolute inset-y-0 pointer-events-none border-l-[1.5px] border-dashed"
							style="left:{flow.todayXPct}%;border-color:{C.today}"></div>
						<span class="absolute pointer-events-none rounded px-1 py-px text-[9px] font-semibold uppercase tracking-[0.4px] text-white"
							style="left:{Math.max(4, Math.min(96, flow.todayXPct))}%;top:0;transform:translateX(-50%);background:{C.today}">Bugün</span>
					{/if}

					<!-- Hover: dikey imleç + ipucu balonu -->
					{#if hoverIdx !== null && flow.cols[hoverIdx]}
						{@const col = flow.cols[hoverIdx]}
						{@const b = col.bucket}
						{@const bal = balance?.values[hoverIdx] ?? null}
						{@const tipLeft = Math.max(22, Math.min(78, col.centerPct))}
						<div class="absolute inset-y-0 w-px bg-teal-700/25 pointer-events-none" style="left:{col.centerPct}%"></div>
						<div class="absolute z-10 pointer-events-none rounded-lg border border-gray-200 bg-white shadow-lg px-3 py-2 min-w-[13.5rem]"
							style="left:{tipLeft}%;top:4px;transform:translateX(-50%)">
							<div class="text-[11px] font-semibold text-gray-900 mb-1.5">{b.label_long}</div>
							<div class="space-y-0.5 text-[11.5px]">
								<div class="flex items-center justify-between gap-4">
									<span class="text-gray-600">Tahsilat</span>
									<span class="tabular-nums font-semibold text-emerald-700">{fmtEur(b.income_total)}</span>
								</div>
								{#if b.income_total > 0}
									<div class="text-[10px] text-gray-500 tabular-nums pl-2">
										gerçekleşen {fmtEur(b.income_realized)} · planlı {fmtEur(b.income_planned)} · {b.income_count} kalem
									</div>
								{/if}
								<div class="flex items-center justify-between gap-4">
									<span class="text-gray-600">Ödeme</span>
									<span class="tabular-nums font-semibold text-brass-dark">{fmtEur(b.expense_total)}</span>
								</div>
								{#if b.expense_total > 0}
									<div class="text-[10px] text-gray-500 tabular-nums pl-2">
										gerçekleşen {fmtEur(b.expense_realized)} · planlı {fmtEur(b.expense_planned)} · {b.expense_count} kalem
									</div>
								{/if}
								<div class="flex items-center justify-between gap-4 border-t border-gray-200 pt-0.5 mt-0.5">
									<span class="text-gray-600">Net</span>
									<span class="tabular-nums font-semibold {b.net_eur < 0 ? 'text-red-700' : 'text-teal-700'}">{fmtEurSigned(b.net_eur)}</span>
								</div>
								{#if b.expense_overdue > 0 || b.income_overdue > 0}
									<div class="flex items-center justify-between gap-4">
										<span class="text-red-700">Vadesi geçen&nbsp;<span class="text-gray-500">(toplam dışı)</span></span>
										<span class="tabular-nums font-semibold text-red-700">{fmtEur(b.expense_overdue + b.income_overdue)}</span>
									</div>
									<div class="text-[10px] text-gray-500 tabular-nums pl-2">{b.overdue_count} kalem ödenmemiş / tahsil edilmemiş</div>
								{/if}
								{#if b.expense_held > 0 || b.income_held > 0}
									<div class="flex items-center justify-between gap-4">
										<span class="text-gray-600">Beklemede&nbsp;<span class="text-gray-500">(toplam dışı)</span></span>
										<span class="tabular-nums font-semibold text-gray-700">{fmtEur(b.expense_held + b.income_held)}</span>
									</div>
								{/if}
								{#if bal !== null}
									<div class="flex items-center justify-between gap-4 border-t border-gray-200 pt-0.5 mt-0.5">
										<span class="text-gray-600">Dönem sonu bakiye</span>
										<span class="tabular-nums font-semibold {bal < 0 ? 'text-red-700' : 'text-teal-700'}">{fmtEurSigned(bal)}</span>
									</div>
								{/if}
							</div>
						</div>
					{/if}
				</div>
			</div>

			<!-- X ekseni etiketleri (SVG dışında → her ekranda net yazı). Sabit genişlikli hücre
			     YERİNE mutlak konum: kova genişliği mobilde 8–18px'e inip etiketi kırpıyordu
			     (2026-08-19 mobil kontrolü); ortalanmış etiket boş komşu kovaların üstüne taşar.
			     Kenarlarda %3–%97 arasına clamp'lenir → ilk/son etiket kutunun dışına sarkmaz. -->
			<div class="relative h-4 mt-1" style="margin-left:calc(var(--axis-w) + 0.25rem)">
				{#each flow.cols as col, i (col.bucket.key)}
					{#if (i - flow.labelAnchor) % flow.labelStep === 0}
						<span class="absolute top-0 tabular-nums text-[10px] leading-tight whitespace-nowrap
							{col.bucket.is_current ? 'font-semibold text-brass-dark' : 'text-gray-500'}"
							style="left:{Math.min(97, Math.max(3, col.centerPct))}%;transform:translateX(-50%)">
							{col.bucket.label}
						</span>
					{/if}
				{/each}
			</div>
		</div>

		<!-- Bakiye paneli açıklaması + negatife düşüş uyarısı -->
		{#if balance}
			<p class="mt-1.5 text-[11px] text-gray-500">
				Alt panel: <span class="text-teal-700 font-medium">banka bakiyesi</span> (dönem sonu, gerçek + projeksiyon).
				{#if balance.firstNegLabel}
					<span class="text-red-700 font-medium">Bakiye {balance.firstNegLabel} döneminde negatife düşüyor.</span>
				{/if}
			</p>
		{/if}

		<!-- Lejant -->
		<div class="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-2.5 text-[11px] text-gray-600">
			<span class="inline-flex items-center gap-1.5"><span class="w-3 h-2.5 rounded-[2px]" style="background:{C.incomeRealized}"></span>Tahsilat — gerçekleşen</span>
			<span class="inline-flex items-center gap-1.5"><span class="w-3 h-2.5 rounded-[2px]" style="background:{C.incomePlanned}"></span>Tahsilat — planlı</span>
			<span class="inline-flex items-center gap-1.5"><span class="w-3 h-2.5 rounded-[2px]" style="background:{C.expenseRealized}"></span>Ödeme — gerçekleşen</span>
			<span class="inline-flex items-center gap-1.5"><span class="w-3 h-2.5 rounded-[2px]" style="background:{C.expensePlanned}"></span>Ödeme — planlı</span>
			<span class="inline-flex items-center gap-1.5">
				<span class="w-3 h-2.5 rounded-[2px] border border-dashed" style="background:rgba(220,38,38,.22);border-color:{C.overdue}"></span>
				Vadesi geçen <span class="text-gray-500">(toplam dışı)</span>
			</span>
			<span class="inline-flex items-center gap-1.5"><span class="w-4 h-[2px] rounded-full" style="background:{C.balance}"></span>Banka bakiyesi</span>
		</div>
	{/if}

	<!-- ANLIK BANKA HESAP BAKİYELERİ -->
	{#if data}
		<div class="mt-4 pt-3 border-t border-gray-200">
			<div class="flex flex-wrap items-center justify-between gap-2">
				<div class="flex items-center gap-2 min-w-0">
					<Landmark size={16} class="text-teal-700 shrink-0" aria-hidden="true" />
					<span class="text-[13px] font-medium text-gray-700">Anlık Banka Bakiyeleri</span>
					<span class="tabular-nums text-[15px] font-semibold {data.total_balance_eur < 0 ? 'text-red-700' : 'text-teal-700'}">
						{fmtEurSigned(data.total_balance_eur)}
					</span>
				</div>
				<button type="button" onclick={() => (showAccounts = !showAccounts)} aria-expanded={showAccounts}
					class="touch-target inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-gray-600 cursor-pointer
						hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500">
					{showAccounts ? 'Gizle' : `${accountRows.length} hesap`}
					{#if showAccounts}<ChevronUp size={14} aria-hidden="true" />{:else}<ChevronDown size={14} aria-hidden="true" />{/if}
				</button>
			</div>

			{#if showAccounts}
				<div class="mt-2.5 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
					{#each accountRows as acc (acc.id)}
						<div class="flex items-center justify-between gap-2 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5">
							<div class="min-w-0">
								<div class="truncate text-[12px] font-medium text-gray-800">
									{acc.bank_name}
									<span class="text-gray-500 font-normal">{acc.currency}{acc.iban_tail ? ` ···${acc.iban_tail}` : ''}</span>
								</div>
								<div class="tabular-nums text-[10.5px] text-gray-500">
									{fmtNative(acc.effective_balance ?? 0, acc.currency)}
									{#if acc.blocked_amount > 0}· bloke {fmtNative(acc.blocked_amount, acc.currency)}{/if}
									{#if acc.last_movement_date}· {fmtDay(acc.last_movement_date)}{/if}
								</div>
							</div>
							<span class="tabular-nums text-[13px] font-semibold shrink-0 {(acc.balance_eur ?? 0) < 0 ? 'text-red-700' : 'text-teal-700'}">
								{fmtEurSigned(acc.balance_eur ?? 0)}
							</span>
						</div>
					{/each}
				</div>
				{#if emptyAccountCount > 0}
					<p class="mt-1.5 text-[11px] text-gray-500">
						Bakiyesiz / hareketsiz {emptyAccountCount} hesap gösterilmiyor.
					</p>
				{/if}
			{/if}
		</div>
	{/if}

	{#if data && data.skipped_no_rate > 0}
		<p class="mt-2 text-[11px] text-gray-500">
			{data.skipped_no_rate} kalem, tarihinde TCMB kuru bulunamadığı için grafiğe dahil edilmedi.
		</p>
	{/if}
</section>
