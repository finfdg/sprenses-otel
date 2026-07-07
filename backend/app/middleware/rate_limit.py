"""Basit in-memory rate limiting middleware."""

import time
from collections import defaultdict
from typing import Dict, List

from fastapi import HTTPException, Request, status


class RateLimiter:
    """Sliding window rate limiter.

    Bellek sızıntısını önlemek için periyodik olarak eski anahtarları temizler.
    """

    # Her N check'te bir tüm anahtarları tara ve eskilerini sil
    _PURGE_EVERY = 500

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._check_count = 0

    def _cleanup(self, key: str, now: float) -> None:
        """Belirli bir anahtarın eski kayıtlarını temizle."""
        cutoff = now - self.window_seconds
        self._requests[key] = [
            t for t in self._requests[key] if t > cutoff
        ]
        # Boş listeyi sil — bellek sızıntısını önle
        if not self._requests[key]:
            del self._requests[key]

    def _purge_stale(self, now: float) -> None:
        """Tüm anahtarları tara, eski/boş olanları sil."""
        cutoff = now - self.window_seconds
        stale_keys = [
            k for k, timestamps in self._requests.items()
            if not timestamps or timestamps[-1] <= cutoff
        ]
        for k in stale_keys:
            del self._requests[k]

    def check(self, key: str) -> None:
        now = time.time()

        # Periyodik global temizlik
        self._check_count += 1
        if self._check_count >= self._PURGE_EVERY:
            self._purge_stale(now)
            self._check_count = 0

        self._cleanup(key, now)

        if len(self._requests.get(key, [])) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Çok fazla istek gönderdiniz. Lütfen biraz bekleyin.",
            )

        self._requests[key].append(now)


# Login: dakikada en fazla 5 deneme (IP bazlı)
login_limiter = RateLimiter(max_requests=5, window_seconds=60)

# Kayıt: dakikada en fazla 3 deneme (IP bazlı)
register_limiter = RateLimiter(max_requests=3, window_seconds=60)

# Mesaj gönderme: dakikada en fazla 30 mesaj (kullanıcı bazlı)
message_limiter = RateLimiter(max_requests=30, window_seconds=60)

# Dosya yükleme: dakikada en fazla 10 dosya (kullanıcı bazlı)
upload_limiter = RateLimiter(max_requests=10, window_seconds=60)

# Mesaj arama: dakikada en fazla 20 arama (kullanıcı bazlı)
search_limiter = RateLimiter(max_requests=20, window_seconds=60)

# Ağır hesaplama endpoint'leri (EUR bakiye, rapor vb.)
heavy_limiter = RateLimiter(max_requests=10, window_seconds=60)

# Runway (nakit projeksiyon): WS finance_updated + kalem-bazlı Beklet/Geri al akışı
# meşru kullanımda sık tetikler — 10/dk gerçek kullanıcıda 429 üretti (2026-07-07)
runway_limiter = RateLimiter(max_requests=30, window_seconds=60)

# EUR bakiye (RunwayChart/Nakit Akım veri kaynağı): runway ile aynı gerekçe — her Panel/Nakit
# Akım açılışı + finans mutasyonu sonrası tazeleme + Beklet akışı tetikler; heavy_limiter'ın
# 10/dk'sı art arda bekletmede doldu → grafik sessizce bayat kaldı (2026-07-07, nginx: 47×429)
eur_balances_limiter = RateLimiter(max_requests=30, window_seconds=60)


def get_client_ip(request: Request) -> str:
    """İstemci IP adresini al.

    Nginx arkasında çalıştığımız için X-Real-IP başlığını öncelikle kullanırız.
    X-Forwarded-For kullanıcı tarafından sahtelenebilir (spoofing riski),
    bu yüzden yalnızca Nginx'in set ettiği X-Real-IP güvenilirdir.
    """
    # Nginx tarafından set edilen güvenilir başlık
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    # Fallback: doğrudan bağlantı IP'si
    return request.client.host if request.client else "unknown"
