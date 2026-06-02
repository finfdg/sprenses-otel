<script lang="ts">
	let { onSelect, onClose }: { onSelect: (emoji: string) => void; onClose: () => void } = $props();

	let searchQuery = $state('');
	let activeCategory = $state('smileys');

	const categories = [
		{ id: 'smileys', icon: '😀', label: 'Yüzler' },
		{ id: 'hands', icon: '👋', label: 'El/Beden' },
		{ id: 'hearts', icon: '❤️', label: 'Kalpler' },
		{ id: 'animals', icon: '🐱', label: 'Hayvanlar' },
		{ id: 'food', icon: '🍎', label: 'Yiyecek' },
		{ id: 'activity', icon: '⚽', label: 'Aktivite' },
		{ id: 'travel', icon: '🚗', label: 'Seyahat' },
		{ id: 'objects', icon: '💡', label: 'Nesneler' },
		{ id: 'symbols', icon: '❗', label: 'Semboller' },
	];

	const emojiData: Record<string, Array<{ emoji: string; keywords: string }>> = {
		smileys: [
			{ emoji: '😀', keywords: 'gülen yüz mutlu' },
			{ emoji: '😃', keywords: 'gülen gözler mutlu' },
			{ emoji: '😄', keywords: 'gülen gülen mutlu' },
			{ emoji: '😁', keywords: 'sırıtan yüz' },
			{ emoji: '😆', keywords: 'kahkaha gülen' },
			{ emoji: '😅', keywords: 'ter gülen' },
			{ emoji: '🤣', keywords: 'yerde yuvarlanan gülen' },
			{ emoji: '😂', keywords: 'sevinç gözyaşı gülen' },
			{ emoji: '🙂', keywords: 'hafif gülümseyen' },
			{ emoji: '😊', keywords: 'kızaran gülen' },
			{ emoji: '😇', keywords: 'melek halo' },
			{ emoji: '🥰', keywords: 'aşk kalp yüz' },
			{ emoji: '😍', keywords: 'kalp gözler aşk' },
			{ emoji: '🤩', keywords: 'yıldız gözler hayranlık' },
			{ emoji: '😘', keywords: 'öpücük gönderen' },
			{ emoji: '😗', keywords: 'öpen yüz' },
			{ emoji: '😚', keywords: 'öpen kapalı gözler' },
			{ emoji: '😙', keywords: 'öpen gülen gözler' },
			{ emoji: '🥲', keywords: 'gülen gözyaşı hüzün' },
			{ emoji: '😋', keywords: 'lezzetli dil' },
			{ emoji: '😛', keywords: 'dil çıkaran' },
			{ emoji: '😜', keywords: 'göz kırpan dil' },
			{ emoji: '🤪', keywords: 'çılgın yüz' },
			{ emoji: '😝', keywords: 'sıkı gözler dil' },
			{ emoji: '🤑', keywords: 'para ağız' },
			{ emoji: '🤗', keywords: 'sarılan kucak' },
			{ emoji: '🤭', keywords: 'ağzını kapatan' },
			{ emoji: '🤫', keywords: 'sus sessiz' },
			{ emoji: '🤔', keywords: 'düşünen merak' },
			{ emoji: '🤐', keywords: 'fermuar ağız' },
			{ emoji: '🤨', keywords: 'kaş kaldıran' },
			{ emoji: '😐', keywords: 'nötr yüz' },
			{ emoji: '😑', keywords: 'ifadesiz' },
			{ emoji: '😶', keywords: 'ağızsız sessiz' },
			{ emoji: '😏', keywords: 'sırıtan kurnaz' },
			{ emoji: '😒', keywords: 'can sıkılmış' },
			{ emoji: '🙄', keywords: 'gözlerini deviren' },
			{ emoji: '😬', keywords: 'yüz buruşturan' },
			{ emoji: '😮‍💨', keywords: 'nefes veren' },
			{ emoji: '🤥', keywords: 'yalancı burun' },
			{ emoji: '😌', keywords: 'rahatlamış' },
			{ emoji: '😔', keywords: 'üzgün düşünceli' },
			{ emoji: '😪', keywords: 'uykulu' },
			{ emoji: '🤤', keywords: 'salya akan' },
			{ emoji: '😴', keywords: 'uyuyan' },
			{ emoji: '😷', keywords: 'maske tıbbi' },
			{ emoji: '🤒', keywords: 'hasta termometre' },
			{ emoji: '🤕', keywords: 'bandajlı yaralı' },
			{ emoji: '🤢', keywords: 'bulantı mide' },
			{ emoji: '🤮', keywords: 'kusan' },
			{ emoji: '😵', keywords: 'baş dönen' },
			{ emoji: '🥴', keywords: 'sarhoş sersem' },
			{ emoji: '😎', keywords: 'güneş gözlüğü havalı' },
			{ emoji: '🤓', keywords: 'inek gözlük' },
			{ emoji: '🧐', keywords: 'monoküllü' },
			{ emoji: '😕', keywords: 'kafası karışık' },
			{ emoji: '😟', keywords: 'endişeli' },
			{ emoji: '🙁', keywords: 'üzgün' },
			{ emoji: '😮', keywords: 'şaşkın açık ağız' },
			{ emoji: '😯', keywords: 'şaşkın sessiz' },
			{ emoji: '😲', keywords: 'çok şaşırmış' },
			{ emoji: '😳', keywords: 'kızarmış yüz' },
			{ emoji: '🥺', keywords: 'yalvaran gözler' },
			{ emoji: '😦', keywords: 'kaygılı' },
			{ emoji: '😧', keywords: 'ıstıraplı' },
			{ emoji: '😨', keywords: 'korkmuş' },
			{ emoji: '😰', keywords: 'endişeli terli' },
			{ emoji: '😥', keywords: 'üzgün rahatlamış' },
			{ emoji: '😢', keywords: 'ağlayan' },
			{ emoji: '😭', keywords: 'hüngür ağlayan' },
			{ emoji: '😱', keywords: 'çığlık korkmuş' },
			{ emoji: '😖', keywords: 'sinirli' },
			{ emoji: '😣', keywords: 'çaresiz' },
			{ emoji: '😞', keywords: 'hayal kırıklığı' },
			{ emoji: '😓', keywords: 'soğuk ter' },
			{ emoji: '😩', keywords: 'yorgun bıkkın' },
			{ emoji: '😫', keywords: 'bitkin' },
			{ emoji: '🥱', keywords: 'esneme sıkılmış' },
			{ emoji: '😤', keywords: 'sinirli burun' },
			{ emoji: '😡', keywords: 'öfkeli kızgın' },
			{ emoji: '😠', keywords: 'kızgın' },
			{ emoji: '🤬', keywords: 'küfür sansür' },
			{ emoji: '👿', keywords: 'kızgın şeytan' },
			{ emoji: '💀', keywords: 'kafatası ölüm' },
			{ emoji: '💩', keywords: 'kaka gülen' },
			{ emoji: '🤡', keywords: 'palyaço' },
			{ emoji: '👻', keywords: 'hayalet' },
			{ emoji: '👽', keywords: 'uzaylı' },
			{ emoji: '🤖', keywords: 'robot' },
			{ emoji: '🎃', keywords: 'balkabağı cadılar' },
		],
		hands: [
			{ emoji: '👋', keywords: 'el sallayan selam' },
			{ emoji: '🤚', keywords: 'el arkası' },
			{ emoji: '🖐️', keywords: 'açık el' },
			{ emoji: '✋', keywords: 'dur el' },
			{ emoji: '🖖', keywords: 'vulkan selam' },
			{ emoji: '👌', keywords: 'tamam ok' },
			{ emoji: '🤌', keywords: 'parmaklarla ne' },
			{ emoji: '🤏', keywords: 'azıcık' },
			{ emoji: '✌️', keywords: 'zafer barış' },
			{ emoji: '🤞', keywords: 'parmaklar çapraz şans' },
			{ emoji: '🤟', keywords: 'seviyorum el' },
			{ emoji: '🤘', keywords: 'rock metal' },
			{ emoji: '🤙', keywords: 'ara beni el' },
			{ emoji: '👈', keywords: 'sol işaret' },
			{ emoji: '👉', keywords: 'sağ işaret' },
			{ emoji: '👆', keywords: 'yukarı işaret' },
			{ emoji: '👇', keywords: 'aşağı işaret' },
			{ emoji: '☝️', keywords: 'yukarı bir parmak' },
			{ emoji: '👍', keywords: 'beğen iyi başparmak yukarı' },
			{ emoji: '👎', keywords: 'beğenme kötü başparmak aşağı' },
			{ emoji: '✊', keywords: 'yumruk güç' },
			{ emoji: '👊', keywords: 'yumruk vuruş' },
			{ emoji: '🤛', keywords: 'sol yumruk' },
			{ emoji: '🤜', keywords: 'sağ yumruk' },
			{ emoji: '👏', keywords: 'alkış bravo' },
			{ emoji: '🙌', keywords: 'kutlama eller' },
			{ emoji: '👐', keywords: 'açık eller' },
			{ emoji: '🤲', keywords: 'avuçlar yukarı' },
			{ emoji: '🤝', keywords: 'el sıkışma anlaşma' },
			{ emoji: '🙏', keywords: 'dua lütfen teşekkür' },
			{ emoji: '💪', keywords: 'kas güçlü kol' },
			{ emoji: '🦾', keywords: 'mekanik kol' },
			{ emoji: '👀', keywords: 'gözler bakma' },
			{ emoji: '👁️', keywords: 'göz' },
			{ emoji: '👅', keywords: 'dil' },
			{ emoji: '👄', keywords: 'dudak ağız' },
		],
		hearts: [
			{ emoji: '❤️', keywords: 'kırmızı kalp aşk' },
			{ emoji: '🧡', keywords: 'turuncu kalp' },
			{ emoji: '💛', keywords: 'sarı kalp' },
			{ emoji: '💚', keywords: 'yeşil kalp' },
			{ emoji: '💙', keywords: 'mavi kalp' },
			{ emoji: '💜', keywords: 'mor kalp' },
			{ emoji: '🖤', keywords: 'siyah kalp' },
			{ emoji: '🤍', keywords: 'beyaz kalp' },
			{ emoji: '🤎', keywords: 'kahverengi kalp' },
			{ emoji: '💔', keywords: 'kırık kalp' },
			{ emoji: '❤️‍🔥', keywords: 'yanan kalp ateş' },
			{ emoji: '💕', keywords: 'iki kalp' },
			{ emoji: '💞', keywords: 'dönen kalpler' },
			{ emoji: '💓', keywords: 'atan kalp' },
			{ emoji: '💗', keywords: 'büyüyen kalp' },
			{ emoji: '💖', keywords: 'parlayan kalp' },
			{ emoji: '💘', keywords: 'ok ile kalp aşk' },
			{ emoji: '💝', keywords: 'kurdeleli kalp hediye' },
			{ emoji: '💟', keywords: 'kalp süsü' },
			{ emoji: '💋', keywords: 'öpücük izi' },
			{ emoji: '💐', keywords: 'çiçek buket' },
			{ emoji: '🌹', keywords: 'gül kırmızı' },
			{ emoji: '🌺', keywords: 'çiçek hibiskus' },
			{ emoji: '🌸', keywords: 'kiraz çiçeği' },
			{ emoji: '🌷', keywords: 'lale' },
			{ emoji: '🌻', keywords: 'ayçiçeği' },
		],
		animals: [
			{ emoji: '🐱', keywords: 'kedi yüz' },
			{ emoji: '🐶', keywords: 'köpek yüz' },
			{ emoji: '🐭', keywords: 'fare yüz' },
			{ emoji: '🐹', keywords: 'hamster' },
			{ emoji: '🐰', keywords: 'tavşan' },
			{ emoji: '🦊', keywords: 'tilki' },
			{ emoji: '🐻', keywords: 'ayı' },
			{ emoji: '🐼', keywords: 'panda' },
			{ emoji: '🐨', keywords: 'koala' },
			{ emoji: '🐯', keywords: 'kaplan' },
			{ emoji: '🦁', keywords: 'aslan' },
			{ emoji: '🐮', keywords: 'inek' },
			{ emoji: '🐷', keywords: 'domuz' },
			{ emoji: '🐸', keywords: 'kurbağa' },
			{ emoji: '🐵', keywords: 'maymun' },
			{ emoji: '🐔', keywords: 'tavuk' },
			{ emoji: '🐧', keywords: 'penguen' },
			{ emoji: '🐦', keywords: 'kuş' },
			{ emoji: '🦅', keywords: 'kartal' },
			{ emoji: '🦋', keywords: 'kelebek' },
			{ emoji: '🐛', keywords: 'böcek' },
			{ emoji: '🐝', keywords: 'arı bal' },
			{ emoji: '🐢', keywords: 'kaplumbağa' },
			{ emoji: '🐍', keywords: 'yılan' },
			{ emoji: '🐠', keywords: 'balık' },
			{ emoji: '🐬', keywords: 'yunus' },
			{ emoji: '🐳', keywords: 'balina' },
			{ emoji: '🦈', keywords: 'köpekbalığı' },
			{ emoji: '🐙', keywords: 'ahtapot' },
			{ emoji: '🦄', keywords: 'unicorn tek boynuzlu' },
		],
		food: [
			{ emoji: '🍎', keywords: 'elma kırmızı meyve' },
			{ emoji: '🍐', keywords: 'armut' },
			{ emoji: '🍊', keywords: 'portakal mandalina' },
			{ emoji: '🍋', keywords: 'limon' },
			{ emoji: '🍌', keywords: 'muz' },
			{ emoji: '🍉', keywords: 'karpuz' },
			{ emoji: '🍇', keywords: 'üzüm' },
			{ emoji: '🍓', keywords: 'çilek' },
			{ emoji: '🍒', keywords: 'kiraz' },
			{ emoji: '🍑', keywords: 'şeftali' },
			{ emoji: '🥑', keywords: 'avokado' },
			{ emoji: '🍕', keywords: 'pizza' },
			{ emoji: '🍔', keywords: 'hamburger' },
			{ emoji: '🍟', keywords: 'patates kızartma' },
			{ emoji: '🌭', keywords: 'sosisli hot dog' },
			{ emoji: '🍿', keywords: 'popcorn mısır' },
			{ emoji: '🧀', keywords: 'peynir' },
			{ emoji: '🥐', keywords: 'kruvasan' },
			{ emoji: '🍞', keywords: 'ekmek' },
			{ emoji: '🥩', keywords: 'et biftek' },
			{ emoji: '🍗', keywords: 'tavuk baget' },
			{ emoji: '🍰', keywords: 'pasta kek' },
			{ emoji: '🎂', keywords: 'doğum günü pastası' },
			{ emoji: '🍩', keywords: 'donut' },
			{ emoji: '🍫', keywords: 'çikolata' },
			{ emoji: '🍦', keywords: 'dondurma' },
			{ emoji: '☕', keywords: 'kahve çay sıcak' },
			{ emoji: '🍵', keywords: 'çay' },
			{ emoji: '🥤', keywords: 'içecek bardak' },
			{ emoji: '🍺', keywords: 'bira' },
			{ emoji: '🍷', keywords: 'şarap' },
			{ emoji: '🥂', keywords: 'kadeh tokuşturma' },
		],
		activity: [
			{ emoji: '⚽', keywords: 'futbol top' },
			{ emoji: '🏀', keywords: 'basketbol' },
			{ emoji: '🏈', keywords: 'amerikan futbol' },
			{ emoji: '⚾', keywords: 'beyzbol' },
			{ emoji: '🎾', keywords: 'tenis' },
			{ emoji: '🏐', keywords: 'voleybol' },
			{ emoji: '🎯', keywords: 'hedef dart' },
			{ emoji: '🏆', keywords: 'kupa ödül şampiyon' },
			{ emoji: '🥇', keywords: 'altın madalya birinci' },
			{ emoji: '🥈', keywords: 'gümüş madalya ikinci' },
			{ emoji: '🥉', keywords: 'bronz madalya üçüncü' },
			{ emoji: '🎮', keywords: 'oyun kontrolcü' },
			{ emoji: '🎲', keywords: 'zar şans' },
			{ emoji: '🎭', keywords: 'tiyatro maske' },
			{ emoji: '🎨', keywords: 'sanat palet boya' },
			{ emoji: '🎬', keywords: 'film sinema' },
			{ emoji: '🎤', keywords: 'mikrofon şarkı' },
			{ emoji: '🎧', keywords: 'kulaklık müzik' },
			{ emoji: '🎵', keywords: 'nota müzik' },
			{ emoji: '🎶', keywords: 'notalar müzik' },
			{ emoji: '🎸', keywords: 'gitar' },
			{ emoji: '🎹', keywords: 'piyano' },
			{ emoji: '🎻', keywords: 'keman' },
			{ emoji: '🏊', keywords: 'yüzme' },
			{ emoji: '🚴', keywords: 'bisiklet' },
			{ emoji: '🧘', keywords: 'yoga meditasyon' },
		],
		travel: [
			{ emoji: '🚗', keywords: 'araba otomobil' },
			{ emoji: '🚕', keywords: 'taksi' },
			{ emoji: '🚌', keywords: 'otobüs' },
			{ emoji: '🚑', keywords: 'ambulans' },
			{ emoji: '🚒', keywords: 'itfaiye' },
			{ emoji: '🚓', keywords: 'polis arabası' },
			{ emoji: '✈️', keywords: 'uçak seyahat' },
			{ emoji: '🚀', keywords: 'roket uzay' },
			{ emoji: '🚢', keywords: 'gemi deniz' },
			{ emoji: '🏠', keywords: 'ev' },
			{ emoji: '🏨', keywords: 'otel' },
			{ emoji: '🏖️', keywords: 'plaj kumsal' },
			{ emoji: '🗻', keywords: 'dağ' },
			{ emoji: '🌍', keywords: 'dünya harita' },
			{ emoji: '🌅', keywords: 'gün batımı' },
			{ emoji: '🌄', keywords: 'gün doğumu' },
			{ emoji: '🌈', keywords: 'gökkuşağı' },
			{ emoji: '⭐', keywords: 'yıldız' },
			{ emoji: '🌙', keywords: 'ay gece' },
			{ emoji: '☀️', keywords: 'güneş' },
			{ emoji: '⛅', keywords: 'bulutlu güneş' },
			{ emoji: '🌧️', keywords: 'yağmur' },
			{ emoji: '⛈️', keywords: 'fırtına' },
			{ emoji: '❄️', keywords: 'kar kış' },
			{ emoji: '🔥', keywords: 'ateş alev' },
			{ emoji: '💧', keywords: 'su damla' },
		],
		objects: [
			{ emoji: '💡', keywords: 'ampul fikir' },
			{ emoji: '📱', keywords: 'telefon mobil' },
			{ emoji: '💻', keywords: 'bilgisayar laptop' },
			{ emoji: '⌨️', keywords: 'klavye' },
			{ emoji: '🖥️', keywords: 'masaüstü bilgisayar' },
			{ emoji: '📷', keywords: 'kamera fotoğraf' },
			{ emoji: '📹', keywords: 'video kamera' },
			{ emoji: '🔑', keywords: 'anahtar' },
			{ emoji: '🔒', keywords: 'kilit' },
			{ emoji: '📌', keywords: 'raptiye pin' },
			{ emoji: '📎', keywords: 'ataç' },
			{ emoji: '✏️', keywords: 'kalem' },
			{ emoji: '📝', keywords: 'not yazma' },
			{ emoji: '📚', keywords: 'kitaplar' },
			{ emoji: '📅', keywords: 'takvim tarih' },
			{ emoji: '⏰', keywords: 'çalar saat' },
			{ emoji: '🔔', keywords: 'zil bildirim' },
			{ emoji: '📧', keywords: 'eposta mail' },
			{ emoji: '💰', keywords: 'para çanta' },
			{ emoji: '💳', keywords: 'kredi kart' },
			{ emoji: '🎁', keywords: 'hediye kutu' },
			{ emoji: '🎈', keywords: 'balon' },
			{ emoji: '🎉', keywords: 'kutlama parti' },
			{ emoji: '🎊', keywords: 'konfeti kutlama' },
			{ emoji: '🏷️', keywords: 'etiket' },
			{ emoji: '🛒', keywords: 'alışveriş sepeti' },
		],
		symbols: [
			{ emoji: '❗', keywords: 'ünlem dikkat' },
			{ emoji: '❓', keywords: 'soru işareti' },
			{ emoji: '‼️', keywords: 'çift ünlem' },
			{ emoji: '⁉️', keywords: 'ünlem soru' },
			{ emoji: '✅', keywords: 'onay yeşil tik' },
			{ emoji: '❌', keywords: 'çarpı hayır' },
			{ emoji: '⭕', keywords: 'kırmızı daire' },
			{ emoji: '🔴', keywords: 'kırmızı nokta' },
			{ emoji: '🟢', keywords: 'yeşil nokta' },
			{ emoji: '🔵', keywords: 'mavi nokta' },
			{ emoji: '⚠️', keywords: 'uyarı dikkat' },
			{ emoji: '🚫', keywords: 'yasak' },
			{ emoji: '♻️', keywords: 'geri dönüşüm' },
			{ emoji: '💯', keywords: 'yüz puan mükemmel' },
			{ emoji: '🆗', keywords: 'ok tamam' },
			{ emoji: '🆕', keywords: 'yeni' },
			{ emoji: '🔜', keywords: 'yakında' },
			{ emoji: '➡️', keywords: 'sağ ok' },
			{ emoji: '⬅️', keywords: 'sol ok' },
			{ emoji: '⬆️', keywords: 'yukarı ok' },
			{ emoji: '⬇️', keywords: 'aşağı ok' },
			{ emoji: '🔄', keywords: 'tekrar döngü' },
			{ emoji: '✨', keywords: 'parıltı yıldız' },
			{ emoji: '💫', keywords: 'baş dönmesi yıldız' },
			{ emoji: '🌟', keywords: 'parlayan yıldız' },
			{ emoji: '⚡', keywords: 'şimşek enerji' },
			{ emoji: '🎵', keywords: 'müzik nota' },
			{ emoji: '♥️', keywords: 'kalp kırmızı' },
			{ emoji: '♦️', keywords: 'karo' },
			{ emoji: '♠️', keywords: 'maça' },
			{ emoji: '♣️', keywords: 'sinek' },
		],
	};

	function getFilteredEmojis(): Array<{ emoji: string; keywords: string }> {
		if (searchQuery.trim()) {
			const q = searchQuery.toLowerCase();
			const all: Array<{ emoji: string; keywords: string }> = [];
			for (const cat of Object.values(emojiData)) {
				for (const e of cat) {
					if (e.keywords.includes(q) || e.emoji.includes(q)) {
						all.push(e);
					}
				}
			}
			return all;
		}
		return emojiData[activeCategory] || [];
	}

	function handleSelect(emoji: string) {
		onSelect(emoji);
	}

	function handleBackdropClick(e: MouseEvent) {
		if ((e.target as HTMLElement).classList.contains('emoji-backdrop')) {
			onClose();
		}
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="emoji-backdrop fixed inset-0 z-40"
	onclick={handleBackdropClick}
	onkeydown={(e) => { if (e.key === 'Escape') onClose(); }}
>
	<div class="absolute bottom-16 left-2 right-2 md:left-auto md:right-auto md:w-80 bg-white rounded-xl shadow-xl border border-gray-200 overflow-hidden z-50">
		<!-- Arama -->
		<div class="p-2 border-b border-gray-100">
			<input
				type="text"
				bind:value={searchQuery}
				placeholder="Emoji ara..."
				class="w-full px-3 py-1.5 bg-gray-100 rounded-lg text-sm text-gray-900 placeholder-gray-400 outline-none focus:ring-2 focus:ring-teal-100 transition-all"
			/>
		</div>

		<!-- Kategoriler -->
		{#if !searchQuery.trim()}
			<div class="flex items-center gap-0.5 px-2 py-1 border-b border-gray-100 overflow-x-auto">
				{#each categories as cat}
					<button
						onclick={() => activeCategory = cat.id}
						class="w-8 h-8 flex items-center justify-center rounded-lg text-lg transition-colors cursor-pointer shrink-0 {activeCategory === cat.id ? 'bg-teal-100' : 'hover:bg-gray-100'}"
						title={cat.label}
					>
						{cat.icon}
					</button>
				{/each}
			</div>
		{/if}

		<!-- Emojiler -->
		<div class="grid grid-cols-8 gap-0.5 p-2 max-h-48 overflow-y-auto">
			{#each getFilteredEmojis() as item}
				<button
					onclick={() => handleSelect(item.emoji)}
					class="w-9 h-9 flex items-center justify-center rounded-lg text-xl hover:bg-gray-100 transition-colors cursor-pointer"
					title={item.keywords}
				>
					{item.emoji}
				</button>
			{/each}
			{#if getFilteredEmojis().length === 0}
				<div class="col-span-8 text-center text-gray-500 text-sm py-4">
					Emoji bulunamadı
				</div>
			{/if}
		</div>
	</div>
</div>
