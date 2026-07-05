/**
 * Kenar menü (Sidebar) ve route guard için TEK kaynak navigasyon konfigürasyonu.
 *
 * Daha önce Sidebar.svelte içinde ~40 link bloğu elle yazılıydı; her modül için
 * href/izin-kodu/etiket/ikon tekrar tekrar kopyalanıyordu. Artık menü yapısı burada
 * veri olarak tanımlıdır:
 *   - Sidebar.svelte bu konfigi loop ile render eder (hasPerm geçidiyle).
 *   - +layout.svelte route guard'ı `requiredModuleForPath()` ile mevcut rotanın
 *     gerektirdiği modül iznini bulup yetkisiz erişimi engeller.
 *
 * Yeni modül/sayfa eklemek için: ilgili gruba bir NavItem ekle — sidebar linki ve
 * route koruması otomatik gelir. (Backend izin/onay tarafı ayrıca yapılır.)
 *
 * `icon`: Heroicons (outline) `<path>` `d` değer(ler)i. Çoğu ikon tek path; bazıları
 * (ör. Sistem dişli) iki path içerir — bu yüzden string[].
 */

export interface NavItem {
	/** Modül izin kodu — hasPerm(code) ve route guard için */
	code: string;
	label: string;
	href: string;
	/** SVG <path d="..."> değer(ler)i */
	icon: string[];
	/** true → pathname href ile BAŞLIYORSA aktif (alt rotalı sayfalar: formlar/[id]).
	 *  false/undefined → tam eşleşme (pathname === href). */
	prefixActive?: boolean;
}

export interface NavGroup {
	/** Açıl/kapan durum anahtarı */
	key: string;
	label: string;
	/** Grup rota öneki — grup-aktif vurgusu ve otomatik açılma için */
	prefix: string;
	icon: string[];
	items: NavItem[];
}

// Heroicons path'leri (Sidebar'dan birebir taşındı)
const I = {
	chevronDown: 'M19 9l-7 7-7-7',
	doc: 'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z',
	checkDoc: 'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m3.75 9v6m3-3H9m1.5-12H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z',
	home: 'M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25',
	check: 'M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z',
	money: 'M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z',
	currency: 'M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
	users: 'M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z',
	userSingle: 'M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z',
	docCheck: 'M10.125 2.25h-4.5c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125v-9M10.125 2.25h.375a9 9 0 019 9v.375M10.125 2.25A3.375 3.375 0 0113.5 5.625v1.5c0 .621.504 1.125 1.125 1.125h1.5a3.375 3.375 0 013.375 3.375M9 15l2.25 2.25L15 12',
	trendUp: 'M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941',
	bank: 'M12 21v-8.25M15.75 21v-8.25M8.25 21v-8.25M3 9l9-6 9 6m-1.5 12V10.332A48.36 48.36 0 0012 9.75c-2.551 0-5.056.2-7.5.582V21M3 21h18M12 6.75h.008v.008H12V6.75z',
	creditCard: 'M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 002.25-2.25V6.75A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25v10.5A2.25 2.25 0 004.5 19.5z',
	chart: 'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z',
	scale: 'M12 3v17.25m0 0c-1.472 0-2.882.265-4.185.75M12 20.25c1.472 0 2.882.265 4.185.75M18.75 4.97A48.416 48.416 0 0012 4.5c-2.291 0-4.545.16-6.75.47m13.5 0c1.01.143 2.01.317 3 .52m-3-.52l2.62 10.726c.122.499-.106 1.028-.589 1.202a5.988 5.988 0 01-2.031.352 5.988 5.988 0 01-2.031-.352c-.483-.174-.711-.703-.59-1.202L18.75 4.971zm-16.5.52c.99-.203 1.99-.377 3-.52m0 0l2.62 10.726c.122.499-.106 1.028-.589 1.202a5.989 5.989 0 01-2.031.352 5.989 5.989 0 01-2.031-.352c-.483-.174-.711-.703-.59-1.202L5.25 4.971z',
	checkCircle: 'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
	building: 'M15.75 15.75V18m-7.5-6.75h.008v.008H8.25v-.008zm0 2.25h.008v.008H8.25V13.5zm0 2.25h.008v.008H8.25v-.008zm0 2.25h.008v.008H8.25V18zm2.498-6.75h.007v.008h-.007v-.008zm0 2.25h.007v.008h-.007V13.5zm0 2.25h.007v.008h-.007v-.008zm0 2.25h.007v.008h-.007V18zm2.504-6.75h.008v.008h-.008v-.008zm0 2.25h.008v.008h-.008V13.5zm0 2.25h.008v.008h-.008v-.008zm0 2.25h.008v.008h-.008V18zm2.498-6.75h.008v.008h-.008v-.008zm0 2.25h.008v.008h-.008V13.5zM8.25 6h7.5v2.25h-7.5V6zM12 2.25c-1.892 0-3.758.11-5.593.322C5.307 2.7 4.5 3.65 4.5 4.757V19.5a2.25 2.25 0 002.25 2.25h10.5a2.25 2.25 0 002.25-2.25V4.757c0-1.108-.806-2.057-1.907-2.185A48.507 48.507 0 0012 2.25z',
	receipt: 'M9 14.25l6-6m4.5-3.493V21.75l-3.75-1.5-3.75 1.5-3.75-1.5-3.75 1.5V4.757c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0c1.1.128 1.907 1.077 1.907 2.185zM9.75 9h.008v.008H9.75V9zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm4.125 4.5h.008v.008h-.008V13.5zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z',
	refresh: 'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99',
	homeModern: 'M8.25 21v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21m0 0h4.5V3.545M12.75 21h7.5V10.75M2.25 21h1.5m18 0h-18M2.25 9l4.5-1.636M18.75 3l-1.5.545m0 6.205l3 1m1.5.5l-1.5-.5M6.75 7.364V3h-3v18m3-13.636l10.5-3.819',
	team: 'M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z',
	cart: 'M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 00-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 00-16.536-1.84M7.5 14.25L5.106 5.272M6 20.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm12.75 0a.75.75 0 11-1.5 0 .75.75 0 011.5 0z',
	bed: 'M3 12a2.25 2.25 0 002.25 2.25h13.5A2.25 2.25 0 0021 12M3 12V8.25A2.25 2.25 0 015.25 6h13.5A2.25 2.25 0 0121 8.25V12M3 12v6a.75.75 0 00.75.75h.75a.75.75 0 00.75-.75v-.75a.75.75 0 01.75-.75h12a.75.75 0 01.75.75v.75a.75.75 0 00.75.75h.75a.75.75 0 00.75-.75v-6m-15-3v.75c0 .414.336.75.75.75h.75a.75.75 0 00.75-.75V9m6.75 0v.75c0 .414.336.75.75.75h.75a.75.75 0 00.75-.75V9',
	plane: 'M6 12L3.269 3.125A59.769 59.769 0 0121.485 12 59.768 59.768 0 013.27 20.875L5.999 12zm0 0h7.5',
	gear1: 'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z',
	gear2: 'M15 12a3 3 0 11-6 0 3 3 0 016 0z',
	cube: 'M21 7.5l-9-5.25L3 7.5m18 0l-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9',
	clipboard: 'M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z',
	warning: 'M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z',
	badgeCheck: 'M9 12.75L11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 01-1.043 3.296 3.745 3.745 0 01-3.296 1.043A3.745 3.745 0 0112 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 01-3.296-1.043 3.745 3.745 0 01-1.043-3.296A3.745 3.745 0 013 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 011.043-3.296 3.746 3.746 0 013.296-1.043A3.746 3.746 0 0112 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 013.296 1.043 3.746 3.746 0 011.043 3.296A3.745 3.745 0 0121 12z',
	server: 'M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z',
	cloudUp: 'M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z',
	fingerprint: 'M7.864 4.243A7.5 7.5 0 0119.5 10.5c0 2.92-.556 5.709-1.568 8.268M5.742 6.364A7.465 7.465 0 004.5 10.5a7.464 7.464 0 01-1.15 3.993m1.989 3.559A11.209 11.209 0 008.25 10.5a3.75 3.75 0 117.5 0c0 .527-.021 1.049-.064 1.565M12 10.5a14.94 14.94 0 01-3.6 9.75m6.633-4.596a18.666 18.666 0 01-2.485 5.33',
	clock: 'M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z',
	calendarDays: 'M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5m-9-6h.008v.008H12v-.008zM12 15h.008v.008H12V15zm0 2.25h.008v.008H12v-.008zM9.75 15h.008v.008H9.75V15zm0 2.25h.008v.008H9.75v-.008zM7.5 15h.008v.008H7.5V15zm0 2.25h.008v.008H7.5v-.008zm6.75-4.5h.008v.008h-.008v-.008zm0 2.25h.008v.008h-.008V15zm0 2.25h.008v.008h-.008v-.008zm2.25-4.5h.008v.008H16.5v-.008zm0 2.25h.008v.008H16.5V15z',
};

/** Üst menü: Panel (her zaman görünür, izin gerekmez) ikon path'i */
export const PANEL_ICON = [I.home];
/** Mesajlaşma ikon path'i (özel: okunmamış badge'i ile Sidebar'da elle render edilir) */
export const MESSAGING_ICON = ['M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z'];

export const NAV_GROUPS: NavGroup[] = [
	{
		key: 'quality', label: 'Kalite', prefix: '/dashboard/kalite', icon: [I.clipboard],
		items: [
			{ code: 'quality.templates', label: 'Şablonlar', href: '/dashboard/kalite/sablonlar', icon: [I.doc] },
			{ code: 'quality.forms', label: 'Formlar', href: '/dashboard/kalite/formlar', icon: [I.docCheck], prefixActive: true },
		],
	},
	{
		key: 'finance', label: 'Finans', prefix: '/dashboard/finans', icon: [I.money],
		items: [
			{ code: 'finance.cash_flow', label: 'Nakit Akım', href: '/dashboard/finans/nakit-akim', icon: [I.trendUp] },
			{ code: 'finance.banks', label: 'Bankalar', href: '/dashboard/finans/bankalar', icon: [I.bank] },
			{ code: 'finance.banks', label: 'Talimatlar', href: '/dashboard/finans/bankalar/talimatlar', icon: [I.doc] },
			{ code: 'finance.doviz', label: 'Döviz', href: '/dashboard/finans/doviz', icon: [I.currency] },
			{ code: 'finance.cariler', label: 'Cariler', href: '/dashboard/finans/cariler', icon: [I.users] },
			{ code: 'finance.sales_invoices', label: 'Satış Faturaları', href: '/dashboard/finans/satis-faturalari', icon: [I.receipt] },
			{ code: 'finance.hakedis', label: 'Hak Ediş Takibi', href: '/dashboard/finans/hakedis', icon: [I.receipt] },
			{ code: 'finance.checks', label: 'Verilen Çekler', href: '/dashboard/finans/cekler', icon: [I.checkDoc] },
			{ code: 'finance.krediler', label: 'Krediler', href: '/dashboard/finans/krediler', icon: [I.creditCard] },
			{ code: 'finance.avanslar', label: 'Alınan Avanslar', href: '/dashboard/finans/avanslar', icon: [I.money] },
			{ code: 'finance.butce', label: 'Bütçe', href: '/dashboard/finans/butce', icon: [I.chart] },
			{ code: 'finance.onay', label: 'Onay Kutusu', href: '/dashboard/finans/onay', icon: [I.checkCircle] },
		],
	},
	{
		key: 'accounting', label: 'Muhasebe', prefix: '/dashboard/muhasebe', icon: [I.building],
		items: [
			{ code: 'accounting.taxes', label: 'Vergiler', href: '/dashboard/muhasebe/vergiler', icon: [I.receipt] },
			{ code: 'accounting.recurring', label: 'Düzenli Ödemeler', href: '/dashboard/muhasebe/duzenli-odemeler', icon: [I.refresh] },
			{ code: 'accounting.rent_income', label: 'Alınan Kiralar', href: '/dashboard/muhasebe/alinan-kiralar', icon: [I.home] },
			{ code: 'accounting.rent_expense', label: 'Verilen Kiralar', href: '/dashboard/muhasebe/verilen-kiralar', icon: [I.homeModern] },
			{ code: 'accounting.dividend', label: 'Temettü', href: '/dashboard/muhasebe/temettu', icon: [I.currency] },
			{ code: 'accounting.fis_icmali', label: 'Kullanıcı Fiş İcmali', href: '/dashboard/muhasebe/fis-icmali', icon: [I.chart] },
			{ code: 'accounting.mizan', label: 'Mizan', href: '/dashboard/muhasebe/mizan', icon: [I.scale] },
		],
	},
	{
		key: 'hr', label: 'İnsan Kaynakları', prefix: '/dashboard/ik', icon: [I.team],
		items: [
			{ code: 'hr.salary', label: 'Maaş', href: '/dashboard/ik/maas', icon: [I.money] },
			{ code: 'hr.withholding', label: 'Stopaj', href: '/dashboard/ik/stopaj', icon: [I.doc] },
			{ code: 'hr.sgk', label: 'SGK', href: '/dashboard/ik/sgk', icon: [I.check] },
			{ code: 'hr.attendance', label: 'Devam Takip', href: '/dashboard/ik/devam-takip', icon: [I.fingerprint] },
			{ code: 'hr.shifts', label: 'Vardiyalar', href: '/dashboard/ik/vardiyalar', icon: [I.clock] },
			{ code: 'hr.shift_schedule', label: 'Vardiya Çizelgesi', href: '/dashboard/ik/vardiya-cizelgesi', icon: [I.calendarDays] },
		],
	},
	{
		key: 'sales', label: 'Satış', prefix: '/dashboard/satis', icon: [I.cart],
		items: [
			{ code: 'sales.hotel_reservation', label: 'Otel Rezervasyon', href: '/dashboard/satis/otel-rezervasyon', icon: [I.home] },
			{ code: 'sales.daily_reservations', label: 'Günlük Hareketler', href: '/dashboard/satis/gunluk-hareketler', icon: [I.calendarDays] },
			{ code: 'sales.acente_mahsup', label: 'Acente Mahsup & Nakit Akım', href: '/dashboard/satis/acente-mahsup', icon: [I.scale] },
			{ code: 'sales.room_types', label: 'Oda Tipleri', href: '/dashboard/satis/oda-tipleri', icon: [I.bed] },
			{ code: 'sales.flight', label: 'Uçak Rezervasyon', href: '/dashboard/satis/ucak-rezervasyon', icon: [I.plane] },
		],
	},
	{
		key: 'stock', label: 'Stok', prefix: '/dashboard/stok', icon: [I.cube],
		items: [
			{ code: 'stok.maliyet', label: 'Maliyet Analizi', href: '/dashboard/stok/maliyet', icon: [I.chart] },
			{ code: 'stok.urunler', label: 'Ürünler & Stok', href: '/dashboard/stok/urunler', icon: [I.cube] },
			{ code: 'stok.hareketler', label: 'Hareketler', href: '/dashboard/stok/hareketler', icon: [I.refresh] },
			{ code: 'stok.depolar', label: 'Depolar', href: '/dashboard/stok/depolar', icon: [I.building] },
		],
	},
	{
		key: 'system', label: 'Sistem', prefix: '/dashboard/sistem', icon: [I.gear1, I.gear2],
		items: [
			{ code: 'system.users', label: 'Kullanıcılar', href: '/dashboard/sistem/kullanicilar', icon: [I.userSingle] },
			{ code: 'system.roles', label: 'Roller', href: '/dashboard/sistem/roller', icon: [I.check] },
			{ code: 'system.modules', label: 'Modüller', href: '/dashboard/sistem/moduller', icon: [I.cube] },
			{ code: 'system.audit_logs', label: 'Audit Logları', href: '/dashboard/sistem/audit-loglar', icon: [I.clipboard] },
			{ code: 'system.error_logs', label: 'Hata Logları', href: '/dashboard/sistem/hata-loglar', icon: [I.warning] },
			{ code: 'system.approval', label: 'Onay Akışı', href: '/dashboard/sistem/onay-akisi', icon: [I.badgeCheck] },
			{ code: 'system.server', label: 'Sunucu', href: '/dashboard/sistem/sunucu', icon: [I.server] },
			{ code: 'system.backup', label: 'Yedekleme', href: '/dashboard/sistem/yedekleme', icon: [I.cloudUp] },
			{ code: 'system.docs', label: 'Dokümanlar', href: '/dashboard/sistem/dokumanlar', icon: [I.doc] },
		],
	},
];

/**
 * Verilen pathname için gerekli modül iznini döndürür (route guard).
 * En uzun eşleşen href kazanır (iç içe rotalar: bankalar/talimatlar, formlar/[id]).
 * Eşleşme yoksa null (ör. /dashboard panel — izin gerekmez).
 */
export function requiredModuleForPath(pathname: string): string | null {
	const routes: Array<{ href: string; code: string }> = [
		{ href: '/dashboard/mesajlasma', code: 'messaging' },
		{ href: '/dashboard/yonetim', code: 'yonetim.panel' },
	];
	for (const g of NAV_GROUPS) {
		for (const it of g.items) routes.push({ href: it.href, code: it.code });
	}
	// En spesifik (uzun) href önce
	routes.sort((a, b) => b.href.length - a.href.length);
	for (const r of routes) {
		if (pathname === r.href || pathname.startsWith(r.href + '/')) {
			return r.code;
		}
	}
	return null;
}
