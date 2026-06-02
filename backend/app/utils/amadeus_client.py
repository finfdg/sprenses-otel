"""Amadeus Self-Service API istemcisi — uçuş ve havalimanı arama.

Self-Service portal 17.07.2026'da kapanacak — bu süre içinde kullanılır.
Kapanış sonrası alternatif (Skyscanner widget, SerpAPI vb.) entegre edilmeli.

Geliştirici dokümanı: https://developers.amadeus.com/self-service
Test ortamı: ücretsiz 2000 sorgu/ay
Production: sorgu başı ücret (Self-Service kapatma sonrası geçersiz)

Kullanım:
    from app.utils.amadeus_client import amadeus
    flights = amadeus.search_flights("IST", "AYT", "2026-06-15", adults=2)
    airports = amadeus.search_airports("ist")
"""

import logging
import os
import time
from typing import List, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# .env'den okunur (yoksa mock moda düşer)
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY", "").strip()
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET", "").strip()
AMADEUS_BASE = os.getenv("AMADEUS_BASE_URL", "https://test.api.amadeus.com").rstrip("/")

# Mock fallback — gerçek API key yoksa demo veri döner
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


def _mock_flights(origin: str, destination: str, date: str, adults: int) -> dict:
    """Demo uçuş verileri — gerçek API key olmadığında döner."""
    base_price = 1850.0
    return {
        "data": [
            {
                "id": f"mock-{i}",
                "source": "MOCK",
                "numberOfBookableSeats": 9 - i,
                "price": {
                    "currency": "TRY",
                    "total": str(round(base_price + i * 320, 2)),
                    "base": str(round(base_price + i * 280, 2)),
                },
                "itineraries": [
                    {
                        "duration": f"PT{1 + (i % 3)}H{(i * 17) % 60:02d}M",
                        "segments": [
                            {
                                "departure": {
                                    "iataCode": origin,
                                    "at": f"{date}T{6 + i * 2:02d}:30:00",
                                },
                                "arrival": {
                                    "iataCode": destination,
                                    "at": f"{date}T{8 + i * 2:02d}:{(i * 13) % 60:02d}:00",
                                },
                                "carrierCode": ["TK", "PC", "VF", "XQ"][i % 4],
                                "number": str(2100 + i * 7),
                                "aircraft": {"code": ["738", "320", "321"][i % 3]},
                            }
                        ],
                    }
                ],
                "validatingAirlineCodes": [["TK", "PC", "VF", "XQ"][i % 4]],
            }
            for i in range(5)
        ],
        "meta": {"count": 5, "_mock": True},
    }


class AmadeusClient:
    """Token cache'li Amadeus REST istemcisi."""

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_expires: float = 0
        self._client = httpx.Client(timeout=15.0)

    @property
    def has_credentials(self) -> bool:
        return bool(AMADEUS_API_KEY and AMADEUS_API_SECRET)

    def _get_token(self) -> str:
        """OAuth2 access token al (30 dk geçerli, cache'lenir)."""
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        resp = self._client.post(
            f"{AMADEUS_BASE}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": AMADEUS_API_KEY,
                "client_secret": AMADEUS_API_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires = time.time() + int(body.get("expires_in", 1800))
        return self._token

    def _get(self, path: str, params: dict) -> dict:
        token = self._get_token()
        resp = self._client.get(
            f"{AMADEUS_BASE}{path}?{urlencode(params)}",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.json()

    def search_airports(self, keyword: str) -> List[dict]:
        """Havalimanı/şehir arama (autocomplete için).

        Mock fallback: gerçek API key yoksa MOCK_AIRPORTS'tan filtreli liste.
        """
        keyword = (keyword or "").strip()
        if not keyword or len(keyword) < 2:
            return []

        if not self.has_credentials:
            kw = keyword.lower()
            return [
                a for a in MOCK_AIRPORTS
                if kw in a["iataCode"].lower()
                or kw in a["name"].lower()
                or kw in a["city"].lower()
            ][:10]

        try:
            data = self._get("/v1/reference-data/locations", {
                "subType": "AIRPORT,CITY",
                "keyword": keyword,
                "page[limit]": 10,
            })
            return [
                {
                    "iataCode": item["iataCode"],
                    "name": item.get("name", ""),
                    "city": item.get("address", {}).get("cityName", ""),
                    "country": item.get("address", {}).get("countryCode", ""),
                }
                for item in data.get("data", [])
                if item.get("iataCode")
            ]
        except Exception as e:
            logger.warning("Amadeus airport search failed: %s — fallback to mock", e)
            return [a for a in MOCK_AIRPORTS if keyword.lower() in a["city"].lower()][:5]

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
        max_results: int = 20,
    ) -> dict:
        """Uçuş arama. Mock fallback: gerçek API key yoksa demo veri."""
        if not self.has_credentials:
            logger.info("Amadeus credentials yok — mock veri dönüyor")
            return _mock_flights(origin, destination, departure_date, adults)

        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": departure_date,
            "adults": adults,
            "currencyCode": currency,
            "max": max_results,
        }
        if return_date:
            params["returnDate"] = return_date
        if children > 0:
            params["children"] = children
        if infants > 0:
            params["infants"] = infants
        if travel_class:
            params["travelClass"] = travel_class.upper()

        try:
            return self._get("/v2/shopping/flight-offers", params)
        except httpx.HTTPStatusError as e:
            logger.error("Amadeus flight search HTTP error %s: %s", e.response.status_code, e.response.text[:300])
            raise
        except Exception as e:
            logger.error("Amadeus flight search error: %s", e)
            raise


amadeus = AmadeusClient()
