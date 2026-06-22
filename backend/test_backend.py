"""
Pruebas rapidas del backend (sin hardware). Ejecutar:
    python test_backend.py
"""

import json

from contract import crc16_ccitt, build_frame, parse_frame
from diagnostics import Diagnostics


def test_crc_matches_ino():
    # CRC16-CCITT (0x1021, init 0xFFFF) de "123456789" es 0x29B1 (vector estandar).
    assert crc16_ccitt(b"123456789") == 0x29B1
    print("ok  crc vector estandar (debe coincidir con el .ino)")


def test_roundtrip_frame():
    payload = json.dumps({"rpm": 3500, "coolant": 92.0, "pkt": 7}, separators=(",", ":"))
    frame = build_frame(payload)
    res = parse_frame(frame)
    assert res.ok and res.data["rpm"] == 3500
    print("ok  trama valida se parsea")


def test_crc_rejects_corruption():
    frame = build_frame('{"rpm":3500}')
    corrupted = frame.replace("3500", "3501")  # cambia el payload, no el CRC
    res = parse_frame(corrupted)
    assert not res.ok and res.error == "crc_mismatch"
    print("ok  trama corrupta se rechaza por CRC")


def test_out_of_range_fault():
    d = Diagnostics()
    out = d.process({"rpm": 3000, "coolant": 215.0, "fresh6": True}, now=0.0)
    assert out["coolant"]["status"] == "fault"
    print(f"ok  riel detectado -> {out['coolant']['reason']}")


def test_flatline_fault():
    d = Diagnostics()
    out = None
    # 88.3 C clavado durante 12 s con el motor girando -> flatline
    for i in range(240):
        out = d.process({"rpm": 3000, "coolant": 88.3, "fresh6": True}, now=i * 0.05)
    assert out["coolant"]["status"] == "fault"
    print(f"ok  flatline detectado -> {out['coolant']['reason']}")


def test_no_data():
    d = Diagnostics()
    out = d.process({"rpm": 3000, "coolant": 90.0, "fresh6": False}, now=0.0)
    assert out["coolant"]["status"] == "no_data"
    print("ok  sin datos (fresh6=false) detectado")


def test_warn_threshold():
    d = Diagnostics()
    out = d.process({"rpm": 3000, "coolant": 105.0, "fresh6": True}, now=0.0)
    assert out["coolant"]["status"] == "warn"
    print("ok  umbral de advertencia")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    print("\nTODO OK")
