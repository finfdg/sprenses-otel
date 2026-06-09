<script lang="ts">
	interface FieldDraft {
		label: string;
		field_type: string;
		unit: string;
		is_required: boolean;
		is_resource: boolean;
		is_guest_count: boolean;
		is_meter: boolean;
		is_month_end_only: boolean;
		options: string;
		sort_order: number;
	}

	interface SectionDraft {
		name: string;
		sort_order: number;
		fields: FieldDraft[];
	}

	interface AssigneeDraft {
		assignment_type: string;
		user_id: number | null;
		role_id: number | null;
	}

	interface UserBrief { id: number; first_name: string; last_name: string; }
	interface RoleBrief { id: number; name: string; }

	let {
		sections = $bindable([]),
		assignees = $bindable([]),
		users = [],
		roles = [],
	}: {
		sections: SectionDraft[];
		assignees: AssigneeDraft[];
		users: UserBrief[];
		roles: RoleBrief[];
	} = $props();

	const fieldTypes = [
		{ value: 'text', label: 'Metin' },
		{ value: 'number', label: 'Sayı' },
		{ value: 'yes_no', label: 'Evet/Hayır' },
		{ value: 'select', label: 'Seçim Listesi' },
	];

	// ─── Bölüm işlemleri ──────────────────────
	function addSection() {
		sections = [...sections, { name: '', sort_order: sections.length, fields: [] }];
	}

	function removeSection(idx: number) {
		sections = sections.filter((_, i) => i !== idx);
	}

	function moveSection(idx: number, dir: -1 | 1) {
		const newIdx = idx + dir;
		if (newIdx < 0 || newIdx >= sections.length) return;
		const arr = [...sections];
		[arr[idx], arr[newIdx]] = [arr[newIdx], arr[idx]];
		sections = arr;
	}

	// ─── Alan işlemleri ───────────────────────
	function addField(sectionIdx: number) {
		const sec = { ...sections[sectionIdx] };
		sec.fields = [...sec.fields, {
			label: '', field_type: 'text', unit: '', is_required: true,
			is_resource: false, is_guest_count: false, is_meter: false,
			is_month_end_only: false, options: '', sort_order: sec.fields.length,
		}];
		sections = sections.map((s, i) => i === sectionIdx ? sec : s);
	}

	function removeField(sectionIdx: number, fieldIdx: number) {
		const sec = { ...sections[sectionIdx] };
		sec.fields = sec.fields.filter((_, i) => i !== fieldIdx);
		sections = sections.map((s, i) => i === sectionIdx ? sec : s);
	}

	function updateField(sectionIdx: number, fieldIdx: number, key: string, value: any) {
		const sec = { ...sections[sectionIdx] };
		const fld = { ...sec.fields[fieldIdx], [key]: value };

		// is_meter işaretlenince is_resource de otomatik işaretlensin
		if (key === 'is_meter' && value) {
			fld.is_resource = true;
		}

		// is_guest_count sadece bir alan olabilir
		if (key === 'is_guest_count' && value) {
			sec.fields = sec.fields.map((f, i) => ({
				...f,
				is_guest_count: i === fieldIdx,
			}));
		} else {
			sec.fields = sec.fields.map((f, i) => i === fieldIdx ? fld : f);
		}

		sections = sections.map((s, i) => i === sectionIdx ? sec : s);
	}

	// ─── Atama işlemleri ──────────────────────
	function addAssignee(type: 'filler' | 'approver') {
		assignees = [...assignees, { assignment_type: type, user_id: null, role_id: null }];
	}

	function removeAssignee(idx: number) {
		assignees = assignees.filter((_, i) => i !== idx);
	}

	function setAssigneeUser(idx: number, userId: number) {
		assignees = assignees.map((a, i) => i === idx ? { ...a, user_id: userId, role_id: null } : a);
	}

	function setAssigneeRole(idx: number, roleId: number) {
		assignees = assignees.map((a, i) => i === idx ? { ...a, user_id: null, role_id: roleId } : a);
	}

	let fillers = $derived(assignees.filter(a => a.assignment_type === 'filler'));
	let approvers = $derived(assignees.filter(a => a.assignment_type === 'approver'));
</script>

<div class="space-y-6">
	<!-- ─── Bölümler ──────────────────────────── -->
	<div>
		<div class="flex items-center justify-between mb-3">
			<h3 class="text-sm font-semibold text-gray-700 uppercase tracking-wider">Bölümler & Alanlar</h3>
			<button
				type="button"
				onclick={addSection}
				class="text-xs px-3 py-1.5 bg-teal-700 text-white rounded-lg hover:bg-teal-800 transition-colors cursor-pointer"
			>
				+ Bölüm Ekle
			</button>
		</div>

		{#if sections.length === 0}
			<p class="text-sm text-gray-500 text-center py-8">Henüz bölüm eklenmedi. "Bölüm Ekle" ile başlayın.</p>
		{/if}

		<div class="space-y-4">
			{#each sections as section, sIdx (sIdx)}
				<div class="border border-gray-200 rounded-xl overflow-hidden">
					<!-- Bölüm başlığı -->
					<div class="bg-gray-50 px-3 sm:px-4 py-2.5 flex items-center gap-2">
						<div class="flex gap-1 shrink-0">
							<button type="button" onclick={() => moveSection(sIdx, -1)} class="text-gray-500 hover:text-gray-600 text-xs cursor-pointer p-1" title="Yukarı">▲</button>
							<button type="button" onclick={() => moveSection(sIdx, 1)} class="text-gray-500 hover:text-gray-600 text-xs cursor-pointer p-1" title="Aşağı">▼</button>
						</div>
						<input
							type="text"
							bind:value={section.name}
							placeholder="Bölüm adı..."
							class="flex-1 min-w-0 px-2 py-1.5 bg-white border border-gray-200 rounded text-sm outline-none focus:border-teal-400"
						/>
						<button
							type="button"
							onclick={() => addField(sIdx)}
							class="text-xs px-2 py-1.5 bg-blue-50 text-blue-600 rounded hover:bg-blue-100 transition-colors cursor-pointer shrink-0"
						>
							+ Alan
						</button>
						<button
							type="button"
							onclick={() => removeSection(sIdx)}
							class="text-xs px-2 py-1.5 text-red-600 hover:bg-red-50 rounded transition-colors cursor-pointer shrink-0"
							title="Bölümü sil"
						>
							✕
						</button>
					</div>

					<!-- Alanlar -->
					{#if section.fields.length > 0}
						<div class="divide-y divide-gray-100 bg-white">
							{#each section.fields as field, fIdx (fIdx)}
								<div class="px-3 sm:px-4 py-3 space-y-2">
									<!-- Mobil: Yığılmış düzen, Masaüstü: Grid düzeni -->
									<div class="flex flex-col gap-2 sm:grid sm:grid-cols-12 sm:items-start">
										<!-- Etiket -->
										<div class="sm:col-span-4">
											<span class="block text-xs text-gray-500 mb-1 sm:hidden">Etiket</span>
											<input
												type="text"
												value={field.label}
												oninput={(e) => updateField(sIdx, fIdx, 'label', e.currentTarget.value)}
												placeholder="Alan etiketi..."
												class="w-full px-2 py-2 sm:py-1.5 bg-gray-50 border border-gray-200 rounded text-sm outline-none focus:border-teal-400"
											/>
										</div>

										<!-- Tip + Birim — mobilde yan yana -->
										<div class="flex gap-2 sm:contents">
											<div class="flex-1 sm:col-span-2">
												<span class="block text-xs text-gray-500 mb-1 sm:hidden">Tip</span>
												<select
													value={field.field_type}
													onchange={(e) => updateField(sIdx, fIdx, 'field_type', e.currentTarget.value)}
													class="w-full px-2 py-2 sm:py-1.5 bg-gray-50 border border-gray-200 rounded text-sm outline-none focus:border-teal-400"
												>
													{#each fieldTypes as ft}
														<option value={ft.value}>{ft.label}</option>
													{/each}
												</select>
											</div>

											<div class="flex-1 sm:col-span-2">
												{#if field.field_type === 'number'}
													<span class="block text-xs text-gray-500 mb-1 sm:hidden">Birim</span>
													<input
														type="text"
														value={field.unit}
														oninput={(e) => updateField(sIdx, fIdx, 'unit', e.currentTarget.value)}
														placeholder="kWh, m³..."
														class="w-full px-2 py-2 sm:py-1.5 bg-gray-50 border border-gray-200 rounded text-xs outline-none focus:border-teal-400"
													/>
												{/if}
											</div>
										</div>

										<!-- Togglelar + Sil — mobilde satır -->
										<div class="flex items-center justify-between sm:col-span-4">
											<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
												<label class="flex items-center gap-1.5 text-xs cursor-pointer">
													<input type="checkbox" checked={field.is_required} onchange={(e) => updateField(sIdx, fIdx, 'is_required', e.currentTarget.checked)} class="accent-teal-700 w-4 h-4" />
													<span>Zorunlu</span>
												</label>
												{#if field.field_type === 'number'}
													<label class="flex items-center gap-1.5 text-xs cursor-pointer">
														<input type="checkbox" checked={field.is_resource} onchange={(e) => updateField(sIdx, fIdx, 'is_resource', e.currentTarget.checked)} class="accent-blue-600 w-4 h-4" />
														<span>Kaynak</span>
													</label>
													<label class="flex items-center gap-1.5 text-xs cursor-pointer">
														<input type="checkbox" checked={field.is_meter} onchange={(e) => updateField(sIdx, fIdx, 'is_meter', e.currentTarget.checked)} class="accent-cyan-600 w-4 h-4" />
														<span>Sayaç</span>
													</label>
													<label class="flex items-center gap-1.5 text-xs cursor-pointer">
														<input type="checkbox" checked={field.is_guest_count} onchange={(e) => updateField(sIdx, fIdx, 'is_guest_count', e.currentTarget.checked)} class="accent-amber-600 w-4 h-4" />
														<span>Kişi Sayısı</span>
													</label>
												{/if}
												<label class="flex items-center gap-1.5 text-xs cursor-pointer">
													<input type="checkbox" checked={field.is_month_end_only} onchange={(e) => updateField(sIdx, fIdx, 'is_month_end_only', e.currentTarget.checked)} class="accent-purple-600 w-4 h-4" />
													<span>Ay Sonu</span>
												</label>
											</div>

											<button
												type="button"
												onclick={() => removeField(sIdx, fIdx)}
												class="text-red-400 hover:text-red-600 text-sm cursor-pointer p-1.5 -mr-1"
												title="Alanı sil"
											>
												✕
											</button>
										</div>
									</div>

									<!-- Select seçenekleri -->
									{#if field.field_type === 'select'}
										<div>
											<input
												type="text"
												value={field.options}
												oninput={(e) => updateField(sIdx, fIdx, 'options', e.currentTarget.value)}
												placeholder='Seçenekler: ["Seçenek A","Seçenek B","Seçenek C"]'
												class="w-full px-2 py-2 sm:py-1.5 bg-gray-50 border border-gray-200 rounded text-xs outline-none focus:border-teal-400"
											/>
											<p class="text-xs text-gray-500 mt-0.5">JSON formatında: ["A","B","C"]</p>
										</div>
									{/if}
								</div>
							{/each}
						</div>
					{:else}
						<p class="text-sm text-gray-500 text-center py-4">Bu bölümde henüz alan yok.</p>
					{/if}
				</div>
			{/each}
		</div>
	</div>

	<!-- ─── Atamalar ──────────────────────────── -->
	<div class="grid grid-cols-1 gap-4">
		<!-- Dolduranlar -->
		<div class="border border-gray-200 rounded-xl overflow-hidden">
			<div class="bg-gray-50 px-3 sm:px-4 py-2.5 flex items-center justify-between border-b border-gray-200">
				<h4 class="text-sm font-semibold text-gray-700">Dolduranlar</h4>
				<button
					type="button"
					onclick={() => addAssignee('filler')}
					class="text-xs px-2 py-1.5 bg-teal-50 text-teal-600 rounded hover:bg-teal-100 transition-colors cursor-pointer"
				>
					+ Ekle
				</button>
			</div>
			<div class="p-3 space-y-2">
				{#if fillers.length === 0}
					<p class="text-xs text-gray-500 text-center py-2">Atama yok — herkes doldurabilir</p>
				{/if}
				{#each assignees as a, idx}
					{#if a.assignment_type === 'filler'}
						<div class="flex items-center gap-2">
							<select
								value={a.user_id ? `u-${a.user_id}` : a.role_id ? `r-${a.role_id}` : ''}
								onchange={(e) => {
									const v = e.currentTarget.value;
									if (v.startsWith('u-')) setAssigneeUser(idx, parseInt(v.slice(2)));
									else if (v.startsWith('r-')) setAssigneeRole(idx, parseInt(v.slice(2)));
								}}
								class="flex-1 min-w-0 px-2 py-2 sm:py-1.5 bg-gray-50 border border-gray-200 rounded text-sm outline-none focus:border-teal-400"
							>
								<option value="">Seçiniz</option>
								<optgroup label="Kullanıcılar">
									{#each users as u}
										<option value="u-{u.id}">{u.first_name} {u.last_name}</option>
									{/each}
								</optgroup>
								<optgroup label="Roller">
									{#each roles as r}
										<option value="r-{r.id}">{r.name}</option>
									{/each}
								</optgroup>
							</select>
							<button type="button" onclick={() => removeAssignee(idx)} class="text-red-400 hover:text-red-600 text-sm cursor-pointer p-1.5">✕</button>
						</div>
					{/if}
				{/each}
			</div>
		</div>

		<!-- Onaylayanlar -->
		<div class="border border-gray-200 rounded-xl overflow-hidden">
			<div class="bg-gray-50 px-3 sm:px-4 py-2.5 flex items-center justify-between border-b border-gray-200">
				<h4 class="text-sm font-semibold text-gray-700">Onaylayanlar</h4>
				<button
					type="button"
					onclick={() => addAssignee('approver')}
					class="text-xs px-2 py-1.5 bg-teal-50 text-teal-600 rounded hover:bg-teal-100 transition-colors cursor-pointer"
				>
					+ Ekle
				</button>
			</div>
			<div class="p-3 space-y-2">
				{#if approvers.length === 0}
					<p class="text-xs text-gray-500 text-center py-2">Atama yok — herkes onaylayabilir</p>
				{/if}
				{#each assignees as a, idx}
					{#if a.assignment_type === 'approver'}
						<div class="flex items-center gap-2">
							<select
								value={a.user_id ? `u-${a.user_id}` : a.role_id ? `r-${a.role_id}` : ''}
								onchange={(e) => {
									const v = e.currentTarget.value;
									if (v.startsWith('u-')) setAssigneeUser(idx, parseInt(v.slice(2)));
									else if (v.startsWith('r-')) setAssigneeRole(idx, parseInt(v.slice(2)));
								}}
								class="flex-1 min-w-0 px-2 py-2 sm:py-1.5 bg-gray-50 border border-gray-200 rounded text-sm outline-none focus:border-teal-400"
							>
								<option value="">Seçiniz</option>
								<optgroup label="Kullanıcılar">
									{#each users as u}
										<option value="u-{u.id}">{u.first_name} {u.last_name}</option>
									{/each}
								</optgroup>
								<optgroup label="Roller">
									{#each roles as r}
										<option value="r-{r.id}">{r.name}</option>
									{/each}
								</optgroup>
							</select>
							<button type="button" onclick={() => removeAssignee(idx)} class="text-red-400 hover:text-red-600 text-sm cursor-pointer p-1.5">✕</button>
						</div>
					{/if}
				{/each}
			</div>
		</div>
	</div>
</div>
