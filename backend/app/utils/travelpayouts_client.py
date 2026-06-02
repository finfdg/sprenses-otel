"""Travelpayouts (Aviasales) API istemcisi — uçuş ve havalimanı arama.

Travelpayouts affiliate programı: https://www.travelpayouts.com
Affiliate olunca ücretsiz API token alınır + tıklama başına komisyon kazanılır.

Endpoint'ler:
  - autocomplete.travelpayouts.com/places2  (PUBLIC, token gerekmez)
  - api.travelpayouts.com/aviasales/v3/prices_for_dates  (token gerekir)

Mock fallback: TRAVELPAYOUTS_TOKEN yoksa demo veri döner — UI test için.

Response formatı **Amadeus benzeri** ortak yapıya çevrilir, böylece frontend
hiç değişiklik gerektirmez (sadece backend'in çevirisi yeterli).
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# .env
TRAVELPAYOUTS_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN", "").strip()
TRAVELPAYOUTS_MARKER = os.getenv("TRAVELPAYOUTS_MARKER", "").strip()  # Affiliate partner ID
TRAVELPAYOUTS_API_BASE = "https://api.travelpayouts.com"
TRAVELPAYOUTS_AUTOCOMPLETE_BASE = "https://autocomplete.travelpayouts.com"
AVIASALES_DEEPLINK_BASE = "https://www.aviasales.com"

CARRIER_NAMES = {
    "TK": "Türk Hava Yolları",
    "PC": "Pegasus",
    "VF": "AnadoluJet",
    "XQ": "SunExpress",
    "LH": "Lufthansa",
    "BA": "British Airways",
    "AF": "Air France",
    "KL": "KLM",
    "EK": "Emirates",
    "QR": "Qatar Airways",
    "FZ": "flydubai",
    "SU": "Aeroflot",
}

# Mock fallback (token yoksa)
MOCK_AIRPORTS = [
    {"iataCode": "IST", "name": "Istanbul Airport", "city": "Istanbul", "country": "TR"},
    {"iataCode": "SAW", "name": "Sabiha Gökçen", "city": "Istanbul", "country": "TR"},
    {"iataCode": "AYT", "name": "Antalya Airport", "city": "Antalya", "country": "TR"},
    {"iataCode": "ESB", "name": "Esenboğa", "city": "Ankara", "country": "TR"},
    {"iataCode": "ADB", "name": "Adnan Menderes", "city": "Izmir", "country": "TR"},
    {"iataCode": "DLM", "name": "Dalaman", "city": "Muğla", "country": "TR"},
    {"iataCode": "BJV", "name": "Milas-Bodrum", "city": "Muğla", "country": "TR"},
    {"iataCode": "FRA", "name": "Frankfurt am Main", "city": "Frankfurt", "country": "DE"},
    {"iataCode": "LHR", "name": "Heathrow", "city": "London", "country": "GB"},
    {"iataCode": "CDG", "name": "Charles de Gaulle", "city": "Paris", "country": "FR"},
]


def _mock_flights(origin: str, destination: str, date: str, adults: int, return_date: Optional[str] = None) -> dict:
    base_price = 3400.0 if return_date else 1850.0  # Round-trip ~2x
    flights = []
    for i in range(5):
        airline = ["TK", "PC", "VF", "XQ"][i % 4]
        flight_no = str(2100 + i * 7)
        aircraft = ["738", "320", "321"][i % 3]
        out_dep = f"{date}T{6 + i * 2:02d}:30:00"
        out_arr = f"{date}T{8 + i * 2:02d}:{(i * 13) % 60:02d}:00"

        itineraries = [{
            "duration": f"PT{1 + (i % 3)}H{(i * 17) % 60:02d}M",
            "segments": [{
                "departure": {"iataCode": origin, "at": out_dep},
                "arrival": {"iataCode": destination, "at": out_arr},
                "carrierCode": airline,
                "number": flight_no,
                "aircraft": {"code": aircraft},
            }],
            "stops": 0,
        }]

        if return_date:
            ret_dep = f"{return_date}T{14 + i * 2:02d}:00:00"
            ret_arr = f"{return_date}T{16 + i * 2:02d}:{(i * 11) % 60:02d}:00"
            itineraries.append({
                "duration": f"PT{1 + (i % 3)}H{(i * 19) % 60:02d}M",
                "segments": [{
                    "departure": {"iataCode": destination, "at": ret_dep},
                    "arrival": {"iataCode": origin, "at": ret_arr},
                    "carrierCode": airline,
                    "number": "",
                    "aircraft": {"code": aircraft},
                }],
                "stops": 0,
            })

        flights.append({
            "id": f"mock-{i}",
            "source": "MOCK",
            "numberOfBookableSeats": 9 - i,
            "price": {
                "currency": "TRY",
                "total": str(round(base_price + i * 320, 2)),
                "base": str(round(base_price + i * 280, 2)),
            },
            "itineraries": itineraries,
            "validatingAirlineCodes": [airline],
            "deepLink": None,
        })

    return {
        "data": flights,
        "meta": {"count": len(flights), "_mock": True, "source": "travelpayouts"},
    }


def _duration_minutes_to_iso(minutes: int) -> str:
    """120 → 'PT2H00M'."""
    h = minutes // 60
    m = minutes % 60
    return f"PT{h}H{m:02d}M"


def _add_minutes(iso: str, minutes: int) -> str:
    """ISO datetime + minutes → ISO datetime."""
    try:
        # Travelpayouts formatı: 2024-12-30T10:55:00+03:00
        dt = datetime.fromisoformat(iso)
        return (dt + timedelta(minutes=minutes)).isoformat()
    except Exception:
        return iso


class TravelpayoutsClient:
    """Travelpayouts (Aviasales) REST istemcisi — autocomplete public, search token'lı."""

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=15.0)

    @property
    def has_credentials(self) -> bool:
        return bool(TRAVELPAYOUTS_TOKEN)

    def search_airports(self, keyword: str) -> List[dict]:
        """Havalimanı/şehir arama — autocomplete.travelpayouts.com (token gerekmez)."""
        keyword = (keyword or "").strip()
        if not keyword or len(keyword) < 2:
            return []

        try:
            # Locale 'en' Türkçe için de iyi çalışıyor; types filtresi koymuyoruz
            # (filtre boş sonuç döndürüyor — şehir+havalimanı karışık geliyor)
            url = f"{TRAVELPAYOUTS_AUTOCOMPLETE_BASE}/places2"
            resp = self._client.get(url, params={
                "term": keyword,
                "locale": "en",
            })
            resp.raise_for_status()
            data = resp.json()
            results = []
            seen_codes = set()
            for item in data:
                code = item.get("code")
                # Sadece havalimanı (airport) veya şehir (city) tip — country atla
                t = item.get("type", "")
                if t not in ("airport", "city"):
                    continue
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                results.append({
                    "iataCode": code,
                    "name": item.get("name", ""),
                    "city": item.get("city_name") or item.get("name", ""),
                    "country": item.get("country_code", ""),
                    "type": t,
                })
            return results[:15]
        except Exception as e:
            logger.warning("Travelpayouts autocomplete failed: %s — fallback to mock", e)
            kw = keyword.lower()
            return [
                a for a in MOCK_AIRPORTS
                if kw in a["iataCode"].lower()
                or kw in a["name"].lower()
                or kw in a["city"].lower()
            ][:10]

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
        children: int = 0,
        infants: int = 0,
        travel_class: Optional[str] = None,
        currency: str = "TRY",
        max_results: int = 30,
    ) -> dict:
        """Uçuş arama — aviasales/v3/prices_for_dates üzerinden.

        Travelpayouts response'u Amadeus benzeri ortak formata çevrilir.
        """
        if not self.has_credentials:
            logger.info("Travelpayouts token yok — mock veri dönüyor")
            return _mock_flights(origin, destination, departure_date, adults, return_date)

        params = {
            "origin": origin,
            "destination": destination,
            "departure_at": departure_date,
            "currency": currency.lower(),
            "limit": max_results,
            "sorting": "price",
            "unique": "false",
            "direct": "false",
            "page": 1,
            "one_way": "true" if not return_date else "false",
        }
        if return_date:
            params["return_at"] = return_date
        if travel_class:
            tc_map = {"ECONOMY": "0", "BUSINESS": "2", "FIRST": "3"}
            tc = tc_map.get(travel_class.upper())
            if tc:
                params["trip_class"] = tc
        if TRAVELPAYOUTS_MARKER:
            params["marker"] = TRAVELPAYOUTS_MARKER

        url = f"{TRAVELPAYOUTS_API_BASE}/aviasales/v3/prices_for_dates"
        try:
            resp = self._client.get(
                url,
                params=params,
                headers={"X-Access-Token": TRAVELPAYOUTS_TOKEN},
            )
            resp.raise_for_status()
            body = resp.json()
            return self._transform_to_amadeus_format(body, currency, adults, departure_date)
        except httpx.HTTPStatusError as e:
            logger.error("Travelpayouts HTTP %s: %s", e.response.status_code, e.response.text[:300])
            raise
        except Exception as e:
            logger.error("Travelpayouts search error: %s", e)
            raise

    def _transform_to_amadeus_format(self, body: dict, currency: str, adults: int, dep_date: str) -> dict:
        """Travelpayouts response → Amadeus benzeri ortak format.

        Frontend bu formatı kullandığı için backend'in transformasyon yapması yeterli.
        Round-trip aramalarda response'da `return_at` + `duration_back` alanları gelir
        — bu durumda itineraries[1] olarak dönüş bacağı eklenir (free tier segment
        detayı vermediği için tek özet segment, detay aviasales linkinde).
        """
        items = body.get("data", []) if body.get("success", True) else []
        offers = []
        for i, f in enumerate(items):
            airline = f.get("airline", "")
            flight_no = f.get("flight_number", "")
            origin_code = f.get("origin_airport") or f.get("origin", "")
            dest_code = f.get("destination_airport") or f.get("destination", "")
            departure_at = f.get("departure_at", f"{dep_date}T00:00:00")
            # duration_to: gidiş bacağı süresi · duration: toplam (round-trip'te gidiş+dönüş)
            duration_to = int(f.get("duration_to", 0) or 0)
            duration_total = int(f.get("duration", 0) or 0)
            out_duration = duration_to or duration_total
            arrival_at = _add_minutes(departure_at, out_duration) if out_duration else departure_at
            transfers = int(f.get("transfers", 0) or 0)
            price = float(f.get("price", 0) or 0)
            link = f.get("link", "")
            deep_link = f"{AVIASALES_DEEPLINK_BASE}{link}" if link else None

            # Gidiş bacağı — tek özet segment (Travelpayouts free tier aktarma detayı vermiyor)
            out_segments = [{
                "departure": {"iataCode": origin_code, "at": departure_at},
                "arrival": {"iataCode": dest_code, "at": arrival_at},
                "carrierCode": airline,
                "number": str(flight_no),
                "aircraft": {"code": ""},
            }]
            if transfers > 0:
                out_segments[0]["_transfers_note"] = f"{transfers} aktarmalı"

            itineraries = [{
                "duration": _duration_minutes_to_iso(out_duration),
                "segments": out_segments,
                "stops": transfers,
            }]

            # Dönüş bacağı (sadece round-trip'te response'a girer)
            return_at = f.get("return_at")
            if return_at:
                ret_duration = int(f.get("duration_back", 0) or 0)
                ret_arrival_at = _add_minutes(return_at, ret_duration) if ret_duration else return_at
                ret_transfers = int(f.get("return_transfers", 0) or 0)
                ret_segments = [{
                    "departure": {"iataCode": dest_code, "at": return_at},
                    "arrival": {"iataCode": origin_code, "at": ret_arrival_at},
                    "carrierCode": airline,  # Free tier dönüş havayolunu ayrı vermiyor
                    "number": "",  # Dönüş uçuş no free tier'da yok — boş bırakıyoruz
                    "aircraft": {"code": ""},
                }]
                if ret_transfers > 0:
                    ret_segments[0]["_transfers_note"] = f"{ret_transfers} aktarmalı"
                itineraries.append({
                    "duration": _duration_minutes_to_iso(ret_duration),
                    "segments": ret_segments,
                    "stops": ret_transfers,
                })

            offers.append({
                "id": f"tp-{i}-{airline}{flight_no}",
                "source": "TRAVELPAYOUTS",
                "numberOfBookableSeats": None,  # Travelpayouts bu bilgiyi free tier'da vermez
                "price": {
                    "currency": currency.upper(),
                    "total": f"{price:.2f}",
                    "base": f"{price:.2f}",
                },
                "itineraries": itineraries,
                "validatingAirlineCodes": [airline],
                "deepLink": deep_link,
            })

        return {
            "data": offers,
            "meta": {
                "count": len(offers),
                "_mock": False,
                "source": "travelpayouts",
            },
        }


travelpayouts = TravelpayoutsClient()
