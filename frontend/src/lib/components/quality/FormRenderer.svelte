<script lang="ts">
	import ThresholdIndicator from './ThresholdIndicator.svelte';

	interface Field {
		id: number;
		label: string;
		field_type: string;
		unit: string | null;
		is_required: boolean;
		is_resource: boolean;
		is_guest_count: boolean;
		is_meter: boolean;
		is_month_end_only: boolean;
		options: string | null;
		sort_order: number;
	}

	interface MeterConsumptions {
		current: Record<string, number | null>;
		previous_day?: Record<string, number | null> | null;
		previous_week?: Record<string, number | null> | null;
		previous_month?: Record<string, number | null> | null;
	}

	interface Section {
		id: number;
		name: string;
		sort_order: number;
		fields: Field[];
	}

	interface FieldValue {
		value: string;
		corrective_action: string;
		correction_note: string;
	}

	interface ComparisonPeriod {
		label: string;
		values: Record<number, string>;
	}

	let {
		sections,
		values = $bindable({}),
		previousValues = null,
		comparisons = null,
		meterConsumptions = null,
		increaseThreshold = 10,
		decreaseThreshold = 10,
		isMonthEnd = false,
		readonly = false,
	}: {
		sections: Section[];
		values: Record<number, FieldValue>;
		previousValues: Record<number, string> | null;
		comparisons: ComparisonPeriod[] | null;
		meterConsumptions: MeterConsumptions | null;
		increaseThreshold: number;
		decreaseThreshold: number;
		isMonthEnd: boolean;
		readonly: boolean;
	} = $props();

	// Konaklayan kişi sayısını bul
	let guestCountFieldId = $derived.by(() => {
		for (const sec of sections) {
			for (const f of sec.fields) {
				if (f.is_guest_count) return f.id;
			}
		}
		return null;
	});

	let guestCount = $derived(
		guestCountFieldId && values[guestCountFieldId]
			? parseFloat(values[guestCountFieldId].value) || 0
			: 0
	);

	function getMeterConsumption(fieldId: number): number | null {
		if (!meterConsumptions?.current) return null;
		const val = meterConsumptions.current[String(fieldId)];
		return val ?? null;
	}

	function getMeterPrevReading(fieldId: number): string | null {
		if (!previousValues) return null;
		const val = previousValues[fieldId];
		return val ?? null;
	}

	function getPerCapita(fieldId: number, field?: Field): number | null {
		if (guestCount <= 0) return null;

		// Sayaç alanları: tüketim üzerinden kişi başı
		if (field?.is_meter && meterConsumptions) {
			const consumption = getMeterConsumption(fieldId);
			if (consumption === null) return null;
			return consumption / guestCount;
		}

		const val = parseFloat(values[fieldId]?.value || '0');
		if (isNaN(val)) return null;
		return val / guestCount;
	}

	// Çoklu karşılaştırma dönemlerinden ThresholdIndicator için veri oluştur
	function getComparisonData(fieldId: number, field?: Field): { label: string; perCapita: number | null }[] {
		// Sayaç alanları: tüketim bazlı karşılaştırma
		if (field?.is_meter && meterConsumptions) {
			return _getMeterComparisonData(fieldId);
		}

		if (!comparisons || comparisons.length === 0) {
			// Geriye uyumluluk: eski previousValues kullan
			if (!previousValues) return [];
			const prevGuestCount = guestCountFieldId
				? parseFloat(previousValues[guestCountFieldId] || '0') || 0
				: 0;
			if (prevGuestCount <= 0) return [];
			const prevVal = parseFloat(previousValues[fieldId] || '0');
			if (isNaN(prevVal)) return [];
			return [{ label: 'Ö.Form', perCapita: prevVal / prevGuestCount }];
		}

		const result: { label: string; perCapita: number | null }[] = [];
		for (const comp of comparisons) {
			if (!comp.values) continue;
			const prevGuestCount = guestCountFieldId
				? parseFloat(comp.values[guestCountFieldId] || '0') || 0
				: 0;
			if (prevGuestCount <= 0) {
				result.push({ label: comp.label, perCapita: null });
				continue;
			}
			const prevVal = parseFloat(comp.values[fieldId] || '0');
			if (isNaN(prevVal)) {
				result.push({ label: comp.label, perCapita: null });
				continue;
			}
			result.push({ label: comp.label, perCapita: prevVal / prevGuestCount });
		}
		return result;
	}

	function _getMeterComparisonData(fieldId: number): { label: string; perCapita: number | null }[] {
		if (!comparisons || !meterConsumptions) return [];

		const periodKeyMap: Record<string, string> = {
			'Ö.Gün': 'previous_day',
			'Ö.Hafta': 'previous_week',
			'Ö.Ay': 'previous_month',
		};

		const result: { label: string; perCapita: number | null }[] = [];
		for (const comp of comparisons) {
			if (!comp.values) continue;
			const periodKey = periodKeyMap[comp.label];
			if (!periodKey) continue;

			const prevGuestCount = guestCountFieldId
				? parseFloat(comp.values[guestCountFieldId] || '0') || 0
				: 0;
			if (prevGuestCount <= 0) {
				result.push({ label: comp.label, perCapita: null });
				continue;
			}

			const periodConsumptions = meterConsumptions[periodKey as keyof MeterConsumptions];
			if (!periodConsumptions || typeof periodConsumptions !== 'object') {
				result.push({ label: comp.label, perCapita: null });
				continue;
			}

			const consumption = (periodConsumptions as Record<string, number | null>)[String(fieldId)];
			if (consumption === null || consumption === undefined) {
				result.push({ label: comp.label, perCapita: null });
				continue;
			}

			result.push({ label: comp.label, perCapita: consumption / prevGuestCount });
		}
		return result;
	}

	function ensureValue(fieldId: number): void {
		if (!values[fieldId]) {
			values[fieldId] = { value: '', corrective_action: '', correction_note: '' };
		}
	}

	function handleInput(fieldId: number, val: string): void {
		ensureValue(fieldId);
		values[fieldId] = { ...values[fieldId], value: val };
	}

	function handleCorrective(fieldId: number, val: string): void {
		ensureValue(fieldId);
		values[fieldId] = { ...values[fieldId], corrective_action: val };
	}

	function handleCorrectionNote(fieldId: number, val: string): void {
		ensureValue(fieldId);
		values[fieldId] = { ...values[fieldId], correction_note: val };
	}

	function parseOptions(optionsJson: string | null): string[] {
		if (!optionsJson) return [];
		try { return JSON.parse(optionsJson); } catch (e) { console.error('Seçenek JSON parse edilemedi:', e); return []; }
	}

	function shouldShowField(field: Field): boolean {
		// Ay sonu alanı ve form ay sonu değilse gizle
		if (field.is_month_end_only && !isMonthEnd) return false;
		return true;
	}
</script>

<div class="space-y-4 sm:space-y-6">
	{#each sections as section (section.id)}
		{@const visibleFields = section.fields.filter(shouldShowField)}
		{#if visibleFields.length > 0}
			<div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
				<div class="bg-gray-50 px-3 sm:px-4 py-2.5 sm:py-3 border-b border-gray-200">
					<h3 class="text-sm font-semibold text-gray-700">{section.name}</h3>
				</div>

				<div class="divide-y divide-gray-100">
					{#each visibleFields as field (field.id)}
						{@const fieldVal = values[field.id]}
						{@const currentVal = fieldVal?.value || ''}
						{@const isNo = field.field_type === 'yes_no' && (currentVal === 'Hayır' || currentVal === 'Uygun Değil')}
						{@const perCapita = field.is_resource ? getPerCapita(field.id, field) : null}
						{@const compData = field.is_resource ? getComparisonData(field.id, field) : []}
						{@const meterConsumption = field.is_meter ? getMeterConsumption(field.id) : null}
						{@const meterPrevReading = field.is_meter ? getMeterPrevReading(field.id) : null}

						<div class="px-3 sm:px-4 py-3">
							<!-- Mobil: yığılmış, Masaüstü: yan yana -->
							<div class="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-2">
								<!-- Etiket -->
								<label for="fr-field-{field.id}" class="text-sm text-gray-700 sm:w-1/2 flex items-center gap-1">
									{field.label}
									{#if field.is_required}
										<span class="text-red-400">*</span>
									{/if}
									{#if field.unit}
										<span class="text-gray-500 text-xs">({field.unit})</span>
									{/if}
									{#if field.is_month_end_only}
										<span class="text-purple-500 text-xs">(Ay Sonu)</span>
									{/if}
								</label>

								<!-- Giriş Alanı -->
								<div class="flex-1">
									{#if field.field_type === 'text'}
										{#if readonly}
											<span class="text-sm text-gray-900">{currentVal || '—'}</span>
										{:else}
											<input
												type="text"
												value={currentVal}
												oninput={(e) => handleInput(field.id, e.currentTarget.value)}
												class="w-full px-3 py-2.5 sm:py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 transition-all"
											/>
										{/if}

									{:else if field.field_type === 'number'}
										<div class="space-y-1.5">
											<div class="flex items-center gap-2">
												{#if readonly}
													<span class="text-sm text-gray-900">{currentVal || '—'}</span>
												{:else}
													<input
														type="number"
														step="any"
														inputmode="decimal"
														value={currentVal}
														oninput={(e) => handleInput(field.id, e.currentTarget.value)}
														class="w-full sm:max-w-[180px] px-3 py-2.5 sm:py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 transition-all"
													/>
												{/if}

												{#if field.is_guest_count && guestCount > 0}
													<span class="text-xs text-teal-600 font-medium whitespace-nowrap shrink-0">
														{guestCount} kişi
													</span>
												{/if}
											</div>

											<!-- Sayaç tüketim bilgisi -->
											{#if field.is_meter}
												<div class="flex flex-wrap items-center gap-3 text-xs">
													{#if meterPrevReading !== null}
														<span class="text-gray-500">
															Önceki sayaç: <span class="font-medium text-gray-500">{meterPrevReading}</span>
														</span>
													{/if}
													{#if meterConsumption !== null}
														<span class="text-cyan-600">
															Tüketim: <span class="font-semibold">{meterConsumption.toFixed(1)}</span>
															{#if field.unit}<span class="text-cyan-500">{field.unit}</span>{/if}
														</span>
													{:else if currentVal && meterPrevReading === null}
														<span class="text-gray-500 italic">Önceki gün verisi yok</span>
													{/if}
												</div>
											{/if}

											<!-- Kişi başı gösterge — mobilde alt satıra -->
											{#if field.is_resource && perCapita !== null}
												<div class="flex flex-wrap items-center gap-2 text-xs">
													<span class="text-gray-500">
														Kişi başı: <span class="font-medium text-gray-700">{perCapita.toFixed(2)}</span>
														{#if field.unit}<span class="text-gray-500">{field.unit}</span>{/if}
													</span>
													<ThresholdIndicator
														currentPerCapita={perCapita}
														comparisons={compData}
														{increaseThreshold}
														{decreaseThreshold}
													/>
												</div>
											{/if}
										</div>

									{:else if field.field_type === 'yes_no'}
										{#if readonly}
											<span class="text-sm {(currentVal === 'Evet' || currentVal === 'Uygun') ? 'text-green-600' : (currentVal === 'Hayır' || currentVal === 'Uygun Değil') ? 'text-red-600' : 'text-gray-500'}">
												{currentVal === 'Evet' ? 'Uygun' : currentVal === 'Hayır' ? 'Uygun Değil' : currentVal || '—'}
											</span>
										{:else}
											<div class="flex gap-4">
												<label class="flex items-center gap-1.5 cursor-pointer py-1">
													<input
														type="radio"
														name="field_{field.id}"
														value="Uygun"
														checked={currentVal === 'Uygun' || currentVal === 'Evet'}
														onchange={() => handleInput(field.id, 'Uygun')}
														class="accent-teal-600 w-4 h-4"
													/>
													<span class="text-sm text-green-700">Uygun</span>
												</label>
												<label class="flex items-center gap-1.5 cursor-pointer py-1">
													<input
														type="radio"
														name="field_{field.id}"
														value="Uygun Değil"
														checked={currentVal === 'Uygun Değil' || currentVal === 'Hayır'}
														onchange={() => handleInput(field.id, 'Uygun Değil')}
														class="accent-red-600 w-4 h-4"
													/>
													<span class="text-sm text-red-700">Uygun Değil</span>
												</label>
											</div>
										{/if}

									{:else if field.field_type === 'select'}
										{#if readonly}
											<span class="text-sm text-gray-900">{currentVal || '—'}</span>
										{:else}
											<select
												value={currentVal}
												onchange={(e) => handleInput(field.id, e.currentTarget.value)}
												class="w-full sm:max-w-[250px] px-3 py-2.5 sm:py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100 transition-all"
											>
												<option value="">Seçiniz</option>
												{#each parseOptions(field.options) as opt}
													<option value={opt}>{opt}</option>
												{/each}
											</select>
										{/if}
									{/if}
								</div>
							</div>

							<!-- Uygunsuzluk alanları (Uygun Değil seçildiğinde) -->
							{#if isNo}
								<div class="mt-2 sm:ml-[50%] sm:pl-2 space-y-2">
									<!-- Açıklama -->
									<div class="bg-red-50 border border-red-200 rounded-lg p-3">
										<label for="fr-corrective-{field.id}" class="block text-xs font-medium text-red-700 mb-1">
											Uygunsuzluk Açıklaması
										</label>
										{#if readonly}
											<p class="text-sm text-red-900">{fieldVal?.corrective_action || '—'}</p>
										{:else}
											<textarea
												id="fr-corrective-{field.id}"
												value={fieldVal?.corrective_action || ''}
												oninput={(e) => handleCorrective(field.id, e.currentTarget.value)}
												placeholder="Uygunsuzluğun açıklamasını yazınız..."
												rows="2"
												class="w-full px-3 py-2 bg-white border border-red-200 rounded-lg text-sm outline-none focus:border-red-400 focus:ring-2 focus:ring-red-100 transition-all resize-none"
											></textarea>
										{/if}
									</div>
									<!-- Yapılan Düzeltme -->
									<div class="bg-amber-50 border border-amber-200 rounded-lg p-3">
										<label for="fr-correction-{field.id}" class="block text-xs font-medium text-amber-700 mb-1">
											Yapılan Düzeltme
										</label>
										{#if readonly}
											<p class="text-sm text-amber-900">{fieldVal?.correction_note || '—'}</p>
										{:else}
											<textarea
												id="fr-correction-{field.id}"
												value={fieldVal?.correction_note || ''}
												oninput={(e) => handleCorrectionNote(field.id, e.currentTarget.value)}
												placeholder="Yapılan düzeltme işlemini yazınız..."
												rows="2"
												class="w-full px-3 py-2 bg-white border border-amber-200 rounded-lg text-sm outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100 transition-all resize-none"
											></textarea>
										{/if}
									</div>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{/if}
	{/each}
</div>
