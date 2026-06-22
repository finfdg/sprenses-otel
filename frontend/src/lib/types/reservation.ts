// Otel rezervasyon modülü ortak tipleri (sayfa + modal bileşenleri paylaşır)

export type UploadHistory = {
	id: number;
	file_name: string;
	hotel_name: string | null;
	period_checkin_start: string | null;
	period_checkin_end: string | null;
	total_rows: number;
	new_rows: number;
	updated_rows: number;
	uploader_name: string | null;
	uploaded_at: string;
};

export type RemovalCandidate = {
	id: number;
	rec_id: number;
	agency: string | null;
	room_type: string | null;
	voucher: string | null;
	guests: string | null;
	checkin_date: string;
	checkout_date: string;
	nights: number;
	record_date: string;
	rooms: number;
	nation: string | null;
	eur_total: number;
	rez_status: string | null;
	status: string | null;
};

export type UploadResult = {
	upload_id: number;
	file_name: string;
	hotel_name: string | null;
	period_checkin_start: string | null;
	period_checkin_end: string | null;
	total_rows: number;
	new_rows: number;
	updated_rows: number;
	removal_candidates: RemovalCandidate[];
};

export type ApiGroup = { id: number; name: string; members: string[] };
