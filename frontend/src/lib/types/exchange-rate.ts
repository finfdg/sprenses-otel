export interface ExchangeRate {
	id: number;
	date: string;
	currency_code: 'USD' | 'EUR' | 'GBP';
	currency_name: string | null;
	unit: number;
	forex_buying: number | null;
	forex_selling: number | null;
	banknote_buying: number | null;
	banknote_selling: number | null;
	source: 'tcmb' | 'carried';
}

export interface LatestRates {
	date: string | null;
	rates: ExchangeRate[];
	eur_usd_parity: number | null;
}

export interface ChartDataPoint {
	date: string;
	forex_buying: number | null;
	forex_selling: number | null;
}

export interface ParityDataPoint {
	date: string;
	parity: number | null;
}

export type CurrencyCode = 'USD' | 'EUR' | 'GBP';
