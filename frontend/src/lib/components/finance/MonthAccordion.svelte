<script lang="ts">
	import { tick } from 'svelte';
	import type { MonthGroup, TransactionCategory } from '$lib/types/finance';
	import { formatCompact } from '$lib/utils/finance';
	import { lazyMount } from '$lib/utils/lazy-mount';
	import CashFlowItem from './CashFlowItem.svelte';

	let {
		monthGroups,
		currentMonthKey,
		currentDayKey,
		categories,
		onTagAssign,
		onCreateCategory,
		matchMode = false,
		matchDate = null,
		onMatchSelect,
		onCCMatchStart,
		eurBalances = null,
	}: {
		monthGroups: MonthGroup[];
		currentMonthKey: string;
		currentDayKey: string;
		categories: TransactionCategory[];
		onTagAssign: (txId: number, categoryId: number | null, note: string | null, vendorId?: number | null) => void;
		onCreateCategory: (name: string, color: string) => Promise<TransactionCategory | null>;
		matchMode?: boolean;
		matchDate?: string | null;
		onMatchSelect?: (txId: number) => void;
		onCCMatchStart?: (statementId: number, type: 'cc' | 'credit', description: string, amount: number) => void;
		eurBalances?: any;
	} = $props();

	function fmtEur(val: number): string {
		return val.toLocaleString('tr-TR', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
	}

	function getMonthEur(monthKey: string): { income: number; expense: number; balance: number } | null {
		if (!eurBalances?.monthly) return null;
		const m = eurBalances.monthly[monthKey];
		if (!m) return null;
		return { income: m.income_eur, expense: m.expense_eur, balance: m.balance_eur };
	}

	// EUR bakiyelerinin işlem olmayan günler için önceki bakiyesini O(log n) bulabilmek üzere
	// günler tek seferde sıralanır — eskiden her gün için Object.keys(...).sort() çağrılıyordu
	// (toplamda O(n²·log n)) ve 200+ gün listelendiğinde scroll donmasına yol açıyordu.
	const sortedBalanceDays = $derived.by(() => {
		if (!eurBalances?.daily) return null;
		return Object.keys(eurBalances.daily).sort();
	});

	function getDayEur(dayDate: string): { income: number; expense: number; balance: number } | null {
		if (!eurBalances?.daily) return null;
		const d = eurBalances.daily[dayDate];
		if (d) return { income: d.income_eur, expense: d.expense_eur, balance: d.balance_eur };
		// İşlem olmayan gün — önceki günün bakiyesini önceden sıralanmış listeden binary search ile al
		if (!sortedBalanceDays) return null;
		let lo = 0, hi = sortedBalanceDays.length;
		while (lo < hi) {
			const mid = (lo + hi) >>> 1;
			if (sortedBalanceDays[mid] < dayDate) lo = mid + 1;
			else hi = mid;
		}
		// lo, dayDate'ten büyük veya eşit olan ilk konum; bir önceki son <dayDate
		const prevKey = lo > 0 ? sortedBalanceDays[lo - 1] : null;
		const prevBalance = prevKey ? eurBalances.daily[prevKey].balance_eur : 0;
		if (prevBalance !== 0) return { income: 0, expense: 0, balance: prevBalance };
		return null;
	}

	// Yıl bazlı gruplama
	interface YearGroup {
		year: string;
		months: MonthGroup[];
		total_income: number;
		total_expense: number;
	}

	const yearGroups: YearGroup[] = $derived.by(() => {
		const map: Record<string, YearGroup> = {};
		for (const m of monthGroups) {
			const year = m.key.substring(0, 4);
			if (!map[year]) {
				map[year] = { year, months: [], total_income: 0, total_expense: 0 };
			}
			map[year].months.push(m);
			map[year].total_income += m.total_income;
			map[year].total_expense += m.total_expense;
		}
		return Object.values(map).sort((a, b) => a.year.localeCompare(b.year));
	});

	const currentYear = currentMonthKey.substring(0, 4);

	// Akordiyon state
	let expandedYears = $state<Record<string, boolean>>({});
	let expandedMonths = $state<Record<string, boolean>>({});
	let expandedDays = $state<Record<string, boolean>>({});
	// Görünür olmuş (viewport'a girmiş) günler — IntersectionObserver ile işaretlenir.
	// Açık ama kaydırılarak ekran dışında kalan günlerin item'ları boş bırakılır;
	// uzun listelerde scroll donmasını ve initial paint'i hafifletir.
	let visibleDays = $state<Record<string, boolean>>({});
	let initializedAccordion = false;

	// T yapısı odak modu (sadece masaüstü)
	let focusMode = $state<'balanced' | 'expense' | 'income'>('balanced');

	const isExpenseNarrow = $derived(focusMode === 'income');
	const isIncomeNarrow = $derived(focusMode === 'expense');
	const gridCols = $derived(
		focusMode === 'expense' ? '5fr 2fr' :
		focusMode === 'income' ? '2fr 5fr' :
		'1fr 1fr'
	);

	$effect(() => {
		if (monthGroups.length > 0 && !initializedAccordion) {
			// Eşleştirme modunda: matchDate'in gününü aç
			const focusDay = matchMode && matchDate ? matchDate : currentDayKey;
			const focusMonthKey = focusDay ? focusDay.substring(0, 7) : currentMonthKey;
			const focusYear = focusMonthKey.substring(0, 4);

			// İçinde bulunulan yılı aç
			expandedYears[focusYear] = true;

			// Hedef ayı bul
			const targetMonth = monthGroups.find(m => m.key === focusMonthKey) || monthGroups.find(m => m.key === currentMonthKey) || monthGroups[0];
			expandedMonths[targetMonth.key] = true;

			// Sadece hedef günü aç; yoksa en yakın sonraki günü aç
			let targetDayKey: string | null = null;

			// 1. Hedef gün var mı?
			const todayDay = targetMonth.days.find(d => d.date === focusDay);
			if (todayDay) {
				targetDayKey = todayDay.date;
			} else {
				// 2. Bugünden sonraki en yakın günü bul (tüm aylarda)
				for (const month of monthGroups) {
					for (const day of month.days) {
						if (day.date >= currentDayKey) {
							// Bu ay henüz açılmamışsa aç
							if (month.key !== targetMonth.key) {
								expandedMonths[month.key] = true;
							}
							targetDayKey = day.date;
							break;
						}
					}
					if (targetDayKey) break;
				}
				// 3. Gelecekte gün yoksa bugünden önceki en yakın günü aç
				if (!targetDayKey) {
					for (let i = monthGroups.length - 1; i >= 0; i--) {
						const month = monthGroups[i];
						for (let j = month.days.length - 1; j >= 0; j--) {
							if (month.days[j].date <= currentDayKey) {
								if (month.key !== targetMonth.key) {
									expandedMonths[month.key] = true;
								}
								targetDayKey = month.days[j].date;
								break;
							}
						}
						if (targetDayKey) break;
					}
				}
			}

			// Sadece hedef günü aç, diğerleri kapalı kalsın
			if (targetDayKey) {
				expandedDays[targetDayKey] = true;
				// Açılan hedef günü hemen görünür işaretle ki içeriği IO beklemeden render edilsin
				visibleDays[targetDayKey] = true;
			}

			initializedAccordion = true;

			tick().then(() => {
				const scrollTarget = targetDayKey
					? document.getElementById(`day-${targetDayKey}`)
					: document.getElementById(`month-${targetMonth.key}`);
				if (scrollTarget) {
					scrollTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });
				}
			});
		}
	});

	function toggleMonth(key: string) {
		expandedMonths[key] = !expandedMonths[key];
	}

	function toggleDay(date: string) {
		expandedDays[date] = !expandedDays[date];
		// Kullanıcı bir günü AÇIYORSA içeriği hemen mount et (kullanıcı doğrudan istedi)
		if (expandedDays[date]) {
			visibleDays[date] = true;
		}
	}

	function toggleFocus(side: 'expense' | 'income') {
		focusMode = focusMode === side ? 'balanced' : side;
	}

	function toggleYear(year: string) {
		expandedYears[year] = !expandedYears[year];
	}

	/** Filtre değiştiğinde dışarıdan akordiyonu sıfırla */
	export function resetAccordion() {
		initializedAccordion = false;
		expandedYears = {};
		expandedMonths = {};
		expandedDays = {};
		visibleDays = {};
	}

	/** Otomatik açılan günü hemen "görünür" işaretle —
	 *  scrollIntoView animasyonu sonrası IO geç tetiklenebilir, kullanıcı bekletilmesin. */
	function markVisible(date: string) {
		visibleDays[date] = true;
	}
</script>

<div class="space-y-6">
	{#each yearGroups as yg (yg.year)}
		{@const isCurrentYearGroup = yg.year === currentYear}
		{@const yEur = (() => {
			if (!eurBalances?.monthly) return null;
			let inc = 0, exp = 0, bal = 0;
			for (const m of yg.months) {
				const me = eurBalances.monthly[m.key];
				if (me) { inc += me.income_eur; exp += me.expense_eur; }
			}
			// Yılın son ayının bakiyesini al
			const lastMonth = yg.months[yg.months.length - 1];
			const lastMe = eurBalances.monthly[lastMonth.key];
			if (lastMe) bal = lastMe.balance_eur;
			return { income: inc, expense: exp, balance: bal };
		})()}
		<div class="bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
			<!-- Yıl Başlık -->
			<button
				onclick={() => toggleYear(yg.year)}
				class="w-full flex items-center gap-2 sm:gap-3 px-4 sm:px-6 py-3.5 sm:py-4 transition-colors cursor-pointer {isCurrentYearGroup ? 'bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700' : 'bg-gray-100 hover:bg-gray-200'}"
			>
				<svg class="w-5 h-5 shrink-0 transition-transform duration-200 {expandedYears[yg.year] ? 'rotate-90' : ''} {isCurrentYearGroup ? 'text-indigo-200' : 'text-gray-500'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
					<path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
				</svg>
				<span class="text-base sm:text-lg font-bold {isCurrentYearGroup ? 'text-white' : 'text-gray-800'}">{yg.year}</span>
				<span class="text-xs font-medium {isCurrentYearGroup ? 'text-indigo-200' : 'text-gray-500'}">{yg.months.length} ay</span>
				<div class="ml-auto flex items-center">
					{#if yEur}
						<span class="w-[85px] sm:w-[120px] text-right inline-block text-[10px] sm:text-xs font-semibold px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-lg {isCurrentYearGroup ? 'text-rose-100 bg-rose-500/30' : 'text-rose-600 bg-rose-50'}">
							-€{fmtEur(yEur.expense)}
						</span>
						<span class="w-[85px] sm:w-[120px] text-right inline-block text-[10px] sm:text-xs font-semibold px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-lg ml-1 {isCurrentYearGroup ? 'text-emerald-100 bg-emerald-500/30' : 'text-emerald-600 bg-emerald-50'}">
							+€{fmtEur(yEur.income)}
						</span>
						<span class="w-[75px] sm:w-[110px] text-right inline-block text-[10px] sm:text-xs font-semibold px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-lg ml-1 {isCurrentYearGroup ? 'text-amber-100 bg-amber-500/30' : yEur.balance >= 0 ? 'text-amber-700 bg-amber-50 border border-amber-200' : 'text-red-600 bg-red-50 border border-red-200'}">
							€{fmtEur(yEur.balance)}
						</span>
					{/if}
				</div>
			</button>

			{#if expandedYears[yg.year]}
				<div class="space-y-3 p-3 sm:p-4">
					{#each yg.months as month (month.key)}
						{@const isCurrentMonth = month.key === currentMonthKey}
						{@const mEur = getMonthEur(month.key)}
						<div id="month-{month.key}" class="bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
							<!-- Ay Başlık -->
							<button
								onclick={() => toggleMonth(month.key)}
								class="w-full flex items-center gap-2 sm:gap-3 px-3 sm:px-6 py-3 sm:py-3.5 transition-colors cursor-pointer {isCurrentMonth ? 'bg-blue-600 hover:bg-blue-700 active:bg-blue-800' : 'hover:bg-gray-50/50 active:bg-gray-100/50'}"
							>
				<svg class="w-4 h-4 shrink-0 transition-transform duration-200 {expandedMonths[month.key] ? 'rotate-90' : ''} {isCurrentMonth ? 'text-blue-200' : 'text-gray-500'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
					<path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
				</svg>
				<span class="text-sm sm:text-base font-bold {isCurrentMonth ? 'text-white' : 'text-gray-800'}">{month.label}</span>
				<div class="ml-auto flex items-center">
					{#if mEur}
						<span class="w-[85px] sm:w-[110px] text-right inline-block text-[10px] sm:text-xs font-semibold px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-lg {isCurrentMonth ? 'text-rose-100 bg-rose-500/30' : 'text-rose-600 bg-rose-50'}">
							-€{fmtEur(mEur.expense)}
						</span>
						<span class="w-[85px] sm:w-[110px] text-right inline-block text-[10px] sm:text-xs font-semibold px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-lg ml-1 {isCurrentMonth ? 'text-emerald-100 bg-emerald-500/30' : 'text-emerald-600 bg-emerald-50'}">
							+€{fmtEur(mEur.income)}
						</span>
						<span class="w-[75px] sm:w-[100px] text-right inline-block text-[10px] sm:text-xs font-semibold px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-lg ml-1 {isCurrentMonth ? 'text-amber-100 bg-amber-500/30' : mEur.balance >= 0 ? 'text-amber-700 bg-amber-50 border border-amber-200' : 'text-red-600 bg-red-50 border border-red-200'}">
							€{fmtEur(mEur.balance)}
						</span>
					{:else}
						<span class="w-[85px] sm:w-[110px] text-right inline-block text-[10px] sm:text-xs font-semibold px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-lg {isCurrentMonth ? 'text-rose-100 bg-rose-500/30' : 'text-rose-600 bg-rose-50'}">
							-{formatCompact(month.total_expense)}
						</span>
						<span class="w-[85px] sm:w-[110px] text-right inline-block text-[10px] sm:text-xs font-semibold px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-lg ml-1 {isCurrentMonth ? 'text-emerald-100 bg-emerald-500/30' : 'text-emerald-600 bg-emerald-50'}">
							+{formatCompact(month.total_income)}
						</span>
						<span class="w-[75px] sm:w-[100px] text-right inline-block text-[10px] sm:text-xs font-semibold px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-lg ml-1 {isCurrentMonth ? (month.balance >= 0 ? 'text-blue-100 bg-white/20' : 'text-red-200 bg-red-500/30') : (month.balance >= 0 ? 'text-blue-600 bg-blue-50' : 'text-red-600 bg-red-50')}">
							{formatCompact(month.balance)}
						</span>
					{/if}
				</div>
			</button>

			{#if expandedMonths[month.key]}
				<!-- T'nin üst yatay çubuğu -->
				<div class="bg-gradient-to-r from-blue-500 via-blue-600 to-blue-500 h-1"></div>

				<!-- Sütun başlıkları — mobilde sabit 1fr 1fr -->
				<div class="grid grid-cols-2 md:hidden">
					<div class="px-2 py-1.5 border-b border-gray-100">
						<h3 class="text-[10px] font-bold text-rose-600 flex items-center gap-1">
							<svg class="w-3 h-3 shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 6L9 12.75l4.286-4.286a11.948 11.948 0 014.306 6.43l.776 2.898m0 0l3.182-5.511m-3.182 5.51l-5.511-3.181" />
							</svg>
							Giderler
						</h3>
					</div>
					<div class="px-2 py-1.5 border-b border-gray-100 border-l-[3px] border-l-blue-500">
						<h3 class="text-[10px] font-bold text-emerald-600 flex items-center gap-1">
							<svg class="w-3 h-3 shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" />
							</svg>
							Gelirler
						</h3>
					</div>
				</div>

				<!-- Masaüstü sütun başlıkları (md+) — focusMode destekli -->
				<div class="hidden md:grid" style="grid-template-columns: {gridCols}; transition: grid-template-columns 300ms ease-in-out">
					<button
						onclick={() => toggleFocus('expense')}
						class="text-left px-6 py-2 border-b border-gray-100 hover:bg-rose-50/40 active:bg-rose-50/60 transition-colors cursor-pointer"
					>
						<h3 class="text-sm font-bold text-rose-600 flex items-center gap-1.5">
							<svg class="w-4 h-4 shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 6L9 12.75l4.286-4.286a11.948 11.948 0 014.306 6.43l.776 2.898m0 0l3.182-5.511m-3.182 5.51l-5.511-3.181" />
							</svg>
							{#if !isExpenseNarrow}<span class="truncate">Giderler</span>{/if}
							<svg class="w-2.5 h-2.5 shrink-0 text-gray-500 transition-transform {focusMode === 'expense' ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
							</svg>
						</h3>
					</button>
					<button
						onclick={() => toggleFocus('income')}
						class="text-left px-6 py-2 border-b border-gray-100 border-l-[3px] border-l-blue-500 hover:bg-emerald-50/40 active:bg-emerald-50/60 transition-colors cursor-pointer"
					>
						<h3 class="text-sm font-bold text-emerald-600 flex items-center gap-1.5">
							<svg class="w-4 h-4 shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" />
							</svg>
							{#if !isIncomeNarrow}<span class="truncate">Gelirler</span>{/if}
							<svg class="w-2.5 h-2.5 shrink-0 text-gray-500 transition-transform {focusMode === 'income' ? 'rotate-180' : ''}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
							</svg>
						</h3>
					</button>
				</div>

				<!-- Gün bazlı akordiyon -->
				{#each month.days as day (day.date)}
					{@const isToday = day.date === currentDayKey}
					{@const dEur = getDayEur(day.date)}
					<button
						id="day-{day.date}"
						onclick={() => toggleDay(day.date)}
						class="w-full flex items-center gap-1.5 sm:gap-2 px-3 sm:px-6 py-1.5 sm:py-2 border-t transition-colors cursor-pointer {isToday ? 'bg-blue-100 border-blue-300 hover:bg-blue-200/80 active:bg-blue-200' : 'bg-gray-50 border-gray-200 hover:bg-gray-100/80 active:bg-gray-100'}"
					>
						<svg class="w-3 h-3 shrink-0 transition-transform duration-200 {expandedDays[day.date] ? 'rotate-90' : ''} {isToday ? 'text-blue-500' : 'text-gray-500'}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
							<path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
						</svg>
						<span class="text-[11px] sm:text-xs font-semibold truncate {isToday ? 'text-blue-700' : 'text-gray-600'}">{day.label}</span>
						<div class="ml-auto flex items-center">
							<span class="w-[75px] sm:w-[100px] text-right inline-block text-[10px] sm:text-xs font-semibold text-rose-500">
								{#if dEur}{#if dEur.expense > 0}-€{fmtEur(dEur.expense)}{/if}{:else if day.total_expense > 0}-{formatCompact(day.total_expense)}{/if}
							</span>
							<span class="w-[75px] sm:w-[100px] text-right inline-block text-[10px] sm:text-xs font-semibold text-emerald-500 ml-1">
								{#if dEur}{#if dEur.income > 0}+€{fmtEur(dEur.income)}{/if}{:else if day.total_income > 0}+{formatCompact(day.total_income)}{/if}
							</span>
							<span class="w-[65px] sm:w-[90px] text-right inline-block text-[10px] sm:text-[10px] font-medium px-1.5 py-0.5 rounded ml-1 {dEur && dEur.balance < 0 ? 'text-red-600 bg-red-50 border border-red-200' : 'text-amber-700 bg-amber-50 border border-amber-200'}">
								{#if dEur}€{fmtEur(dEur.balance)}{/if}
							</span>
						</div>
					</button>

					{#if expandedDays[day.date]}
						{@const isDayVisible = visibleDays[day.date]}
						{@const dayItemCount = day.expenseItems.length + day.incomeItems.length}
						<!-- Lazy mount sentinel — viewport'a yaklaştığında içerik render edilir.
						     Placeholder, item başına ~32px yer ayırır → scroll yüksekliği yaklaşık tutulur. -->
						<div
							use:lazyMount={{ onEnter: () => markVisible(day.date), rootMargin: '300px' }}
						>
							{#if !isDayVisible}
								<div
									class="border-t border-gray-100 bg-gray-50/40 flex items-center justify-center text-[10px] text-gray-500"
									style="min-height: {Math.min(Math.max(dayItemCount * 32, 40), 400)}px"
								>
									{dayItemCount} kayıt yükleniyor…
								</div>
							{:else}
								<!-- MOBİL: sabit grid -->
								<div class="grid grid-cols-2 md:hidden border-t border-gray-100">
									<div class="p-1 space-y-1 overflow-hidden">
										{#each day.expenseItems as item (item.id)}
											<CashFlowItem {item} variant="mobile" {categories} {onTagAssign} {matchMode} {onMatchSelect} {onCCMatchStart} onCreateCategory={onCreateCategory} />
										{/each}
										{#if day.expenseItems.length === 0}
											<div class="min-h-[1px]"></div>
										{/if}
									</div>
									<div class="p-1 space-y-1 overflow-hidden border-l-[2px] border-blue-500">
										{#each day.incomeItems as item (item.id)}
											<CashFlowItem {item} variant="mobile" {categories} {onTagAssign} {matchMode} {onMatchSelect} {onCCMatchStart} onCreateCategory={onCreateCategory} />
										{/each}
										{#if day.incomeItems.length === 0}
											<div class="min-h-[1px]"></div>
										{/if}
									</div>
								</div>

								<!-- MASAÜSTÜ: focusMode destekli grid -->
								<div class="hidden md:grid border-t border-gray-100" style="grid-template-columns: {gridCols}; transition: grid-template-columns 300ms ease-in-out">
									<div class="p-3 space-y-1.5 overflow-hidden">
										{#each day.expenseItems as item (item.id)}
											<CashFlowItem {item} narrow={isExpenseNarrow} {categories} {onTagAssign} {matchMode} {onMatchSelect} {onCCMatchStart} onCreateCategory={onCreateCategory} />
										{/each}
										{#if day.expenseItems.length === 0}
											<div class="min-h-[1px]"></div>
										{/if}
									</div>
									<div class="p-3 space-y-1.5 overflow-hidden border-l-[3px] border-blue-500">
										{#each day.incomeItems as item (item.id)}
											<CashFlowItem {item} narrow={isIncomeNarrow} {categories} {onTagAssign} {matchMode} {onMatchSelect} {onCCMatchStart} onCreateCategory={onCreateCategory} />
										{/each}
										{#if day.incomeItems.length === 0}
											<div class="min-h-[1px]"></div>
										{/if}
									</div>
								</div>
							{/if}
						</div>
					{/if}
				{/each}
			{/if}
					</div>
				{/each}
				</div>
			{/if}
		</div>
	{/each}
</div>
