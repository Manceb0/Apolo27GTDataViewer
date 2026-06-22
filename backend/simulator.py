"""
Simulador del nodo de adquisicion (ESP32 + PE3), para probar el backend sin
hardware. Genera tramas validas con el mismo formato y CRC del .ino.

Guion de la sesion simulada:
  0-15 s   arranque: motor sube de ralenti, coolant calienta normal
  15-30 s  operacion normal a media carga
  30 s en  FALLA INYECTADA: el sensor de coolant se "traba" (flatline) y luego
           se va al riel (215 C) -> el backend debe marcarlo como FAULT
           aunque el numero "parezca" una temperatura real.
"""

import json
import math
import random
import time

from contract import build_frame

_t0 = time.monotonic()
_pkt = 0
_coolant_last = 25.0


def _scripted_state(elapsed: float) -> dict:
    global _coolant_last

    # RPM: ralenti + ondas de aceleracion
    rpm = 1100 + 2600 * (0.5 + 0.5 * math.sin(elapsed * 0.6)) + random.uniform(-60, 60)
    rpm = max(0, rpm)
    tps = min(100, max(0, (rpm - 1100) / 38 + random.uniform(-2, 2)))

    # Coolant: calienta hacia ~92 C de forma realista
    target = min(92.0, 25.0 + elapsed * 2.2)
    coolant = target + random.uniform(-0.4, 0.4)

    fresh6 = True

    # ---- FALLA INYECTADA a partir de los 30 s ----
    if elapsed >= 30.0:
        if elapsed < 45.0:
            coolant = 88.3            # flatline: clavado, no se mueve con el motor girando
        else:
            coolant = 215.0           # riel: sensor abierto/en corto

    _coolant_last = coolant

    return {
        "rpm": int(rpm),
        "tps": round(tps, 1),
        "fuel": round(2.5 + tps * 0.05, 1),
        "ign": round(15 + tps * 0.2, 1),
        "baro": 101.0,
        "map": round(30 + tps * 1.5, 2),
        "lambda": round(0.95 + random.uniform(-0.03, 0.03), 2),
        "pressure": "kPa",
        "battery": round(13.8 + random.uniform(-0.1, 0.1), 2),
        "air": round(28 + random.uniform(-0.5, 0.5), 1),
        "coolant": round(coolant, 1),
        "tempType": "C",
        "an5": 0.0, "an6": 0.0, "an7": 0.0, "an8": 0.0,
        "fresh1": True, "fresh2": True, "fresh4": True, "fresh6": fresh6,
    }


def generate_frame() -> str:
    """Devuelve una linea de trama valida ($A27,{json}*CRC)."""
    global _pkt
    elapsed = time.monotonic() - _t0
    _pkt += 1

    state = _scripted_state(elapsed)
    state["count"] = _pkt
    state["pkt"] = _pkt
    state["ts"] = int(elapsed * 1000)
    state["busErr"] = 0
    state["valid"] = True
    state["alive"] = True

    payload = json.dumps(state, separators=(",", ":"))
    return build_frame(payload)
