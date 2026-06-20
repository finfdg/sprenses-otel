<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { hasPermission } from '$lib/stores/auth.svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onWsEvent } from '$lib/stores/websocket.svelte';
	import FormRenderer from '$lib/components/quality/FormRenderer.svelte';
	import Breadcrumb from '$lib/components/Breadcrumb.svelte';
	import FormSkeleton from '$lib/components/FormSkeleton.svelte';
	import Button from '$lib/components/Button.svelte';
	import Textarea from '$lib/components/Textarea.svelte';
	import { FileText } from 'lucide-svelte';

	const canUse = hasPermission('quality.forms', 'use');

	let formData = $state<any>(null);
	let loading = $state(true);
	let saving = $state(false);
	let submitting = $state(false);
	let reviewing = $state(false);
	let reopening = $state(false);
	let reviewComment = $state('');

	// Form değerleri: { [fieldId]: { value, corrective_action, correction_note } }
	let fieldValues = $state<Record<number, { value: string; corrective_action: string; correction_note: string }>>({});
	let previousValuesMap = $state<Record<number, string>>({});
	let comparisonPeriods = $state<{ label: string; values: Record<number, string> }[]>([]);
	let meterConsumptionsData = $state<any>(null);
	let notes = $state('');

	let formId = $derived(Number($page.params.id));

	const statusLabels: Record<string, string> = {
		draft: 'Taslak',
		submitted: 'Gönderildi',
		approved: 'Onaylandı',
		rejected: 'Reddedildi',
	};

	const statusStyles: Record<string, string> = {
		draft: 'bg-gray-100 text-gray-600 border-gray-200',
		submitted: 'bg-blue-50 text-blue-600 border-blue-200',
		approved: 'bg-green-50 text-green-600 border-green-200',
		rejected: 'bg-red-50 text-red-600 border-red-200',
	};

	let isReadonly = $derived(
		!canUse || (formData?.status !== 'draft' && formData?.status !== 'rejected')
	);

	let canSubmit = $derived(
		canUse && (formData?.status === 'draft' || formData?.status === 'rejected')
	);

	let canReview = $derived(
		canUse && formData?.status === 'submitted'
	);

	let canReopen = $derived(
		canUse && formData?.status === 'rejected'
	);

	let unsubWs: (() => void) | null = null;

	onMount(async () => {
		await loadForm();

		// WS: Bu form güncellendiğinde yenile
		unsubWs = onWsEvent('quality_form_update', (data: any) => {
			if (data.form_id === formId) {
				const eventLabels: Record<string, string> = {
					submitted: 'gönderildi',
					approved: 'onaylandı',
					rejected: 'reddedildi',
					reopened: 'yeniden açıldı',
				};
				const label = eventLabels[data.event] || 'güncellendi';
				showToast(`Form ${label} (${data.actor_name})`, 'info');
				loadForm();
			}
		});
	});

	onDestroy(() => {
		unsubWs?.();
	});

	async function loadForm() {
		loading = true;
		try {
			const data = await api.get<any>(`/quality/forms/${formId}`);
			formData = data;
			notes = data.notes || '';

			// Değerleri map'e dönüştür
			const valMap: Record<number, { value: string; corrective_action: string; correction_note: string }> = {};
			for (const v of (data.values || [])) {
				valMap[v.field_id] = {
					value: v.value || '',
					corrective_action: v.corrective_action || '',
					correction_note: v.correction_note || '',
				};
			}
			fieldValues = valMap;

			// Önceki değerleri map'e dönüştür
			// Sayaç alanları için önceki gün (previous_day) değerlerini kullan
			const prevMap: Record<number, string> = {};
			const prevDayVals = data.comparisons?.previous_day;
			if (prevDayVals && Array.isArray(prevDayVals)) {
				for (const pv of prevDayVals) {
					prevMap[pv.field_id] = pv.value || '';
				}
			} else if (data.previous_values) {
				for (const pv of data.previous_values) {
					prevMap[pv.field_id] = pv.value || '';
				}
			}
			previousValuesMap = prevMap;

			// Sayaç tüketim verileri
			meterConsumptionsData = data.meter_consumptions || null;

			// Çoklu karşılaştırma dönemlerini oluştur
			const periodLabels: Record<string, string> = {
				previous_day: 'Ö.Gün',
				previous_week: 'Ö.Hafta',
				previous_month: 'Ö.Ay',
			};
			const periods: { label: string; values: Record<number, string> }[] = [];
			if (data.comparisons) {
				for (const [key, label] of Object.entries(periodLabels)) {
					const periodVals = data.comparisons[key];
					if (periodVals && Array.isArray(periodVals)) {
						const pMap: Record<number, string> = {};
						for (const pv of periodVals) {
							pMap[pv.field_id] = pv.value || '';
						}
						periods.push({ label: label as string, values: pMap });
					}
				}
			}
			comparisonPeriods = periods;
		} catch (err) {
			console.error('Form yüklenemedi:', err);
			showToast('Form yüklenemedi', 'error');
		}
		loading = false;
	}

	async function handleSave() {
		saving = true;
		try {
			const values = Object.entries(fieldValues).map(([fieldId, v]) => ({
				field_id: Number(fieldId),
				value: v.value || null,
				corrective_action: v.corrective_action || null,
				correction_note: v.correction_note || null,
			}));

			await api.patch(`/quality/forms/${formId}/fill`, {
				values,
				notes: notes.trim() || null,
			});
			showToast('Form kaydedildi', 'success');
		} catch (err: any) {
			console.error('Kayıt hatası:', err);
			showToast(err.message || 'Kaydedilemedi', 'error');
		}
		saving = false;
	}

	async function handleSubmit() {
		// Önce kaydet
		await handleSave();

		submitting = true;
		try {
			await api.post(`/quality/forms/${formId}/submit`, {});
			showToast('Form gönderildi', 'success');
			await loadForm();
		} catch (err: any) {
			console.error('Gönderme hatası:', err);
			showToast(err.message || 'Gönderilemedi', 'error');
		}
		submitting = false;
	}

	async function handleReview(action: 'approve' | 'reject') {
		reviewing = true;
		try {
			await api.post(`/quality/forms/${formId}/review`, {
				action,
				comment: reviewComment.trim() || null,
			});
			showToast(action === 'approve' ? 'Form onaylandı' : 'Form reddedildi', 'success');
			await loadForm();
		} catch (err: any) {
			console.error('İnceleme hatası:', err);
			showToast(err.message || 'İşlem başarısız', 'error');
		}
		reviewing = false;
	}

	async function handleReopen() {
		reopening = true;
		try {
			await api.post(`/quality/forms/${formId}/reopen`, {});
			showToast('Form yeniden açıldı', 'success');
			await loadForm();
		} catch (err: any) {
			console.error('Yeniden açma hatası:', err);
			showToast(err.message || 'Yeniden açılamadı', 'error');
		}
		reopening = false;
	}

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleDateString('tr-TR', {
			day: '2-digit',
			month: '2-digit',
			year: 'numeric',
		});
	}

	function formatDateTime(dateStr: string): string {
		return new Date(dateStr).toLocaleString('tr-TR', {
			day: '2-digit',
			month: '2-digit',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit',
		});
	}

	async function openPdf() {
		// Popup engelini önlemek için pencereyi fetch'ten ÖNCE aç (kullanıcı tıklamasıyla senkron)
		const pdfWindow = window.open('', '_blank');
		if (!pdfWindow) {
			showToast('Popup engellendi, lütfen tarayıcı ayarlarından izin verin', 'error');
			return;
		}

		// Yükleniyor mesajı göster
		pdfWindow.document.write(`
			<html><head><title>PDF Yükleniyor...</title></head>
			<body style="display:flex;align-items:center;justify-content:center;height:100vh;margin:0;font-family:system-ui,sans-serif;background:#f9fafb;">
				<div style="text-align:center;color:#6b7280;">
					<div style="width:40px;height:40px;border:3px solid #e5e7eb;border-top-color:#0d9488;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 16px;"></div>
					<p style="font-size:16px;">PDF yükleniyor...</p>
				</div>
				<style>@keyframes spin{to{transform:rotate(360deg)}}</style>
			</body></html>
		`);

		try {
			// Cookie üzerinden kimlik doğrulama — token URL'de gösterilmez
			const res = await fetch(`/api/quality/forms/${formId}/pdf`, {
				credentials: 'include',
			});
			if (!res.ok) {
				pdfWindow.close();
				showToast('PDF oluşturulamadı', 'error');
				return;
			}
			const blob = await res.blob();
			const url = URL.createObjectURL(blob);

			// Tarayıcının PDF görüntüleyicisinde aç (indirme butonu zaten mevcut)
			pdfWindow.location.href = url;

			setTimeout(() => URL.revokeObjectURL(url), 120000);
		} catch (err) {
			pdfWindow.close();
			console.error('PDF açma hatası:', err);
			showToast('PDF açılamadı', 'error');
		}
	}
</script>

<div class="max-w-4xl mx-auto">
	{#if loading}
		<FormSkeleton fields={5} />
	{:else if formData}
		<!-- Başlık + Breadcrumb -->
		<div class="mb-4 sm:mb-6">
			<Breadcrumb items={[
				{ label: 'Kalite', href: '/dashboard/kalite/formlar' },
				{ label: 'Formlar', href: '/dashboard/kalite/formlar' },
				{ label: formData.template_name }
			]} />
			<div class="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
				<div>
					<h1 class="text-2xl font-semibold text-gray-900">{formData.template_name}</h1>
					<div class="flex flex-wrap items-center gap-2 sm:gap-3 mt-1">
						<span class="text-sm text-gray-500">{formatDate(formData.period_date)}</span>
						<span class="text-xs px-2 py-0.5 rounded-full border {statusStyles[formData.status] || ''}">
							{statusLabels[formData.status] || formData.status}
						</span>
					</div>
				</div>
				{#if formData.status === 'approved'}
					<Button variant="secondary" class="shrink-0" onclick={openPdf}>
						<FileText size={16} />
						PDF
					</Button>
				{/if}
			</div>

			<!-- Durum bilgileri -->
			{#if formData.filled_by_name || formData.reviewed_by_name}
				<div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
					{#if formData.filled_by_name}
						<span>Dolduran: <strong class="text-gray-700">{formData.filled_by_name}</strong></span>
					{/if}
					{#if formData.submitted_at}
						<span>Gönderilme: <strong class="text-gray-700">{formatDateTime(formData.submitted_at)}</strong></span>
					{/if}
					{#if formData.reviewed_by_name}
						<span>
							{formData.status === 'approved' ? 'Onaylayan' : 'Reddeden'}:
							<strong class="text-gray-700">{formData.reviewed_by_name}</strong>
						</span>
					{/if}
					{#if formData.reviewed_at}
						<span>Tarih: <strong class="text-gray-700">{formatDateTime(formData.reviewed_at)}</strong></span>
					{/if}
				</div>
			{/if}

			<!-- Red yorumu -->
			{#if formData.status === 'rejected' && formData.review_comment}
				<div class="mt-3 bg-red-50 border border-red-200 rounded-lg p-3">
					<p class="text-xs font-medium text-red-700 mb-1">Red Yorumu:</p>
					<p class="text-sm text-red-900">{formData.review_comment}</p>
				</div>
			{/if}
		</div>

		<!-- Form Alanları -->
		<FormRenderer
			sections={formData.sections || []}
			bind:values={fieldValues}
			previousValues={Object.keys(previousValuesMap).length > 0 ? previousValuesMap : null}
			comparisons={comparisonPeriods.length > 0 ? comparisonPeriods : null}
			meterConsumptions={meterConsumptionsData}
			increaseThreshold={formData.increase_threshold ?? 10}
			decreaseThreshold={formData.decrease_threshold ?? 10}
			isMonthEnd={formData.is_month_end ?? false}
			readonly={isReadonly}
		/>

		<!-- Açıklama Alanı -->
		<div class="mt-4 sm:mt-6 bg-white border border-gray-200 rounded-xl p-3 sm:p-4">
			<label for="qfd-notes" class="block text-sm font-semibold text-gray-700 mb-2">Açıklama</label>
			<p class="text-xs text-gray-500 mb-2">Sorularda olmayan veya o gün için gelişen özel olayları buraya yazınız.</p>
			{#if isReadonly}
				<p class="text-sm text-gray-900">{notes || '—'}</p>
			{:else}
				<Textarea
					id="qfd-notes"
					bind:value={notes}
					placeholder="Günlük açıklama / özel durumlar..."
					rows={3}
				/>
			{/if}
		</div>

		<!-- İşlem Butonları -->
		<div class="mt-4 sm:mt-6 space-y-3">
			{#if canSubmit}
				<div class="flex flex-col sm:flex-row gap-2 sm:gap-3">
					<Button variant="secondary" class="w-full sm:w-auto" onclick={handleSave} loading={saving}>Kaydet (Taslak)</Button>
					<Button class="w-full sm:w-auto" onclick={handleSubmit} loading={submitting} disabled={saving}>Gönder</Button>
				</div>
			{/if}

			{#if canReview}
				<div class="bg-white border border-gray-200 rounded-xl p-3 sm:p-4 space-y-3">
					<label for="qfd-review" class="block text-sm font-medium text-gray-700">İnceleme</label>
					<Textarea
						id="qfd-review"
						bind:value={reviewComment}
						placeholder="Yorum (opsiyonel)..."
						rows={2}
					/>
					<div class="flex flex-col sm:flex-row gap-2">
						<Button class="w-full sm:w-auto flex-1 sm:flex-none" loading={reviewing} onclick={() => handleReview('approve')}>Onayla</Button>
						<Button variant="danger" class="w-full sm:w-auto flex-1 sm:flex-none" loading={reviewing} onclick={() => handleReview('reject')}>Reddet</Button>
					</div>
				</div>
			{/if}

			{#if canReopen}
				<Button variant="secondary" class="w-full sm:w-auto" loading={reopening} onclick={handleReopen}>Yeniden Aç</Button>
			{/if}
		</div>
	{/if}
</div>
