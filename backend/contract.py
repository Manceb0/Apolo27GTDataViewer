"""
Contrato de datos entre el ESP32 y el backend.

El .ino emite una trama por linea:
    $A27,{...json...}*CRC16HEX

El CRC16-CCITT (poly 0x1021, init 0xFFFF, sin reflexion) se calcula sobre el
texto del JSON que va entre "$A27," y "*". Aqui se valida la integridad y se
parsea el JSON. Si el CRC no cuadra, la trama se descarta.
"""

import json
from dataclasses import dataclass, field
from typing import Optional

from config import FRAME_PREFIX


def crc16_ccitt(data: bytes) -> int:
    """Mismo algoritmo que crc16() en el .ino. Debe dar identico resultado."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


@dataclass
class ParseResult:
    ok: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    raw: str = ""


def parse_frame(line: str) -> ParseResult:
    """Valida y parsea una linea cruda del puerto serie."""
    line = line.strip()
    if not line:
        return ParseResult(False, error="empty")
    if not line.startswith(FRAME_PREFIX):
        return ParseResult(False, error="bad_prefix", raw=line)
    if "*" not in line:
        return ParseResult(False, error="no_crc", raw=line)

    body = line[len(FRAME_PREFIX):]
    payload, _, crc_hex = body.rpartition("*")

    try:
        crc_recv = int(crc_hex, 16)
    except ValueError:
        return ParseResult(False, error="crc_not_hex", raw=line)

    if crc16_ccitt(payload.encode("utf-8")) != crc_recv:
        return ParseResult(False, error="crc_mismatch", raw=line)

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return ParseResult(False, error=f"json:{exc}", raw=line)

    return ParseResult(True, data=data, raw=line)


def build_frame(payload_json: str) -> str:
    """Construye una trama valida (usado por el simulador y los tests)."""
    crc = crc16_ccitt(payload_json.encode("utf-8"))
    return f"{FRAME_PREFIX}{payload_json}*{crc:04X}"
