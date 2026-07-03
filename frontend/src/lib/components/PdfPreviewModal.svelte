<!--
	PdfPreviewModal.svelte — iOS Safari uyumlu PDF önizleme modalı (tasarım sistemi primitive'i).

	Neden: iOS Safari, yeni sekmede açılan veya `<a download>` + click() ile indirilen
	blob URL'lerine erişemiyor ("WebKitBlobResource hatası 1"). Bu bileşen PDF'i aynı
	sayfada iframe içinde gösterir; Yazdır / İndir / Kapat aksiyonları modal başlığındadır.
	Aynı-origin blob'lar iframe'de tüm platformlarda sorunsuz çalışır.
	Blob URL yaşam döngüsü (create/revoke) bileşenin içindedir — çağıran sayfa yalnızca
	blob'u verir. İlk uygulama: bankalar/talimatlar (2026-04-20); ortak bileşene
	çıkarılma: 2026-07-03 (nakit-akim PDF raporu iPad'de aynı hatayı verince).

	Kullanım:
		import PdfPreviewModal from '$lib/components/PdfPreviewModal.svelte';
		let pdfModal: PdfPreviewModal | undefined = $state();
		...
		const blob = await res.blob();
		pdfModal?.open(blob, 'rapor.pdf');
		...
		<PdfPreviewModal bind:this={pdfModal} />
-->
<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Printer, Download, X } from 'lucide-svelte';
	import Button from './Button.svelte';
	import { showToast } from '$lib/stores/toast.svelte';

	let preview = $state<{ url: string; filename: string } | null>(null);
	let iframeEl: HTMLIFrameElement | undefined = $state();

	/** PDF blob'unu modalda göster (önceki önizlemenin URL'i serbest bırakılır) */
	export function open(blob: Blob, filename: string) {
		if (preview) URL.revokeObjectURL(preview.url);
		preview = { url: URL.createObjectURL(blob), filename };
	}

	/** Modalı kapat ve blob URL'ini serbest bırak */
	export function close() {
		if (preview) {
			URL.revokeObjectURL(preview.url);
			preview = null;
		}
	}

	/**
	 * PDF'i yazdır. Masaüstünde iframe.contentWindow.print() çalışır.
	 * iOS Safari iframe print sinyalini çoğu zaman yoksaydığı için fallback
	 * olarak blob gizli bir iframe'e yüklenip print tetiklenir; o da olmazsa
	 * kullanıcıya Paylaş → Yazdır önerilir.
	 */
	function printPdf() {
		if (!preview) return;
		try {
			if (iframeEl?.contentWindow) {
				iframeEl.contentWindow.focus();
				iframeEl.contentWindow.print();
				return;
			}
		} catch (err) {
			console.error('iframe print hatası:', err);
		}
		// Fallback — blob'u gizli iframe'e yükleyip print
		const hidden = document.createElement('iframe');
		hidden.style.position = 'fixed';
		hidden.style.right = '0';
		hidden.style.bottom = '0';
		hidden.style.width = '0';
		hidden.style.height = '0';
		hidden.style.border = '0';
		hidden.src = preview.url;
		hidden.onload = () => {
			try {
				hidden.contentWindow?.focus();
				hidden.contentWindow?.print();
			} catch (err) {
				console.error('Fallback print hatası:', err);
				showToast("Yazdırma başlatılamadı — Paylaş menüsünden Yazdır'ı kullanın", 'error');
			}
			setTimeout(() => hidden.remove(), 60000);
		};
		document.body.appendChild(hidden);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && preview) close();
	}

	onDestroy(() => {
		if (preview) URL.revokeObjectURL(preview.url);
	});
</script>

<svelte:window onkeydown={handleKeydown} />

{#if preview}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-[60] bg-black/70 flex items-center justify-center p-2 sm:p-4"
		onclick={(e) => { if (e.target === e.currentTarget) close(); }}
	>
		<div class="bg-white rounded-xl w-full max-w-5xl h-[95vh] sm:h-[90vh] flex flex-col overflow-hidden shadow-2xl">
			<div class="flex items-center justify-between gap-2 px-3 sm:px-4 py-2.5 border-b border-gray-200 bg-gray-50">
				<h3 class="text-sm font-semibold text-gray-800 truncate">{preview.filename}</h3>
				<div class="flex gap-1.5 sm:gap-2 shrink-0">
					<Button variant="secondary" size="sm" onclick={printPdf} ariaLabel="Yazdır" title="Yazdır">
						<Printer size={14} />
						<span class="hidden sm:inline">Yazdır</span>
					</Button>
					<!-- İndir: Button href dalı `download` özniteliğini iletmediğinden ham <a> (teal-700 AA) -->
					<a
						href={preview.url}
						download={preview.filename}
						class="touch-target inline-flex items-center justify-center gap-1.5 px-3 py-1.5 bg-teal-700 text-white text-xs font-medium rounded-lg hover:bg-teal-800 cursor-pointer shadow-sm"
						aria-label="İndir"
						title="İndir"
					>
						<Download size={14} />
						<span class="hidden sm:inline">İndir</span>
					</a>
					<Button variant="ghost" size="sm" onclick={close} ariaLabel="Kapat" title="Kapat">
						<X size={14} />
						<span class="hidden sm:inline">Kapat</span>
					</Button>
				</div>
			</div>
			<iframe
				bind:this={iframeEl}
				src={preview.url}
				class="flex-1 border-0 w-full"
				title={preview.filename}
			></iframe>
		</div>
	</div>
{/if}
