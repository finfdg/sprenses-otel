"""D1-4: backend `constants.py` ↔ frontend `realtime.ts` WS sözleşmesi parite testi.

İki taraf elle senkron tutulur (otomatik üretim yok — realtime.ts docstring'i de bunu söyler).
Bir WS event tipi veya broadcast modül adı yalnız BİR tarafta eklenir/yeniden adlandırılırsa
derleme hata vermez ama runtime'da sessizce kopan gerçek-zamanlı akış (event hiç dinlenmez)
oluşur. Bu test o sapmayı CI'da yakalar (mimari denetim D1-4, 2026-06-22).
"""
import re
from pathlib import Path

from app.constants import BroadcastModule, WSEvent

_REALTIME_TS = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "lib" / "constants" / "realtime.ts"
)


def _backend_values(cls) -> set:
    """Bir sabit sınıfının string değerli (dunder olmayan) üyeleri."""
    return {v for k, v in vars(cls).items()
            if not k.startswith("__") and isinstance(v, str)}


def _ts_block_values(text: str, const_name: str) -> set:
    """realtime.ts'teki `export const <NAME> = { ... } as const;` bloğunun string değerleri."""
    m = re.search(const_name + r"\s*=\s*\{(.*?)\}\s*as const", text, re.S)
    assert m, f"{const_name} bloğu realtime.ts'te bulunamadı"
    return set(re.findall(r":\s*'([^']+)'", m.group(1)))


class TestRealtimeConstantsParity:
    def test_realtime_file_exists(self):
        assert _REALTIME_TS.is_file(), f"realtime.ts bulunamadı: {_REALTIME_TS}"

    def test_ws_event_parity(self):
        ts = _REALTIME_TS.read_text(encoding="utf-8")
        backend = _backend_values(WSEvent)
        frontend = _ts_block_values(ts, "WS_EVENT")
        assert backend == frontend, (
            "WS event sözleşmesi sapması (constants.py ↔ realtime.ts):\n"
            f"  yalnız backend (WSEvent): {sorted(backend - frontend)}\n"
            f"  yalnız frontend (WS_EVENT): {sorted(frontend - backend)}"
        )

    def test_broadcast_module_parity(self):
        ts = _REALTIME_TS.read_text(encoding="utf-8")
        backend = _backend_values(BroadcastModule)
        frontend = _ts_block_values(ts, "BROADCAST_MODULE")
        assert backend == frontend, (
            "Broadcast modül sözleşmesi sapması (constants.py ↔ realtime.ts):\n"
            f"  yalnız backend (BroadcastModule): {sorted(backend - frontend)}\n"
            f"  yalnız frontend (BROADCAST_MODULE): {sorted(frontend - backend)}"
        )
