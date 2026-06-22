"""
Validador de enlace ESP32 <-> backend (sin WebSocket ni base de datos).

Usalo para comprobar el cable/puerto antes de levantar server.py:

    python check_link.py                 # lista los puertos COM disponibles
    python check_link.py COM5            # escucha COM5 y valida las tramas
    python check_link.py COM5 --baud 115200

Muestra, en vivo, cuantas tramas llegan validas, cuantas fallan el CRC, y un
resumen de cada paquete (rpm/coolant) para confirmar que los datos son reales.
"""

import argparse
import sys
import time

import serial
from serial.tools import list_ports

from contract import parse_frame
from config import SERIAL_BAUD


def cmd_list():
    ports = list(list_ports.comports())
    if not ports:
        print("No se detecto ningun puerto COM. ¿Esta conectado el ESP32 por USB?")
        return
    print("Puertos disponibles:")
    for p in ports:
        print(f"  {p.device:8}  {p.description}")
    print("\nUsa:  python check_link.py <PUERTO>")


def cmd_listen(port: str, baud: int):
    print(f"Escuchando {port} @ {baud}  (Ctrl+C para salir)\n")
    valid = bad_prefix = crc_fail = other = 0
    last_pkt = None
    seq_lost = 0
    t_start = time.time()

    try:
        ser = serial.Serial(port, baud, timeout=1)
    except serial.SerialException as exc:
        print(f"No se pudo abrir {port}: {exc}")
        print("Pista: cierra el Monitor Serie del Arduino IDE (ocupa el puerto).")
        sys.exit(1)

    try:
        with ser:
            while True:
                line = ser.readline().decode("utf-8", errors="ignore")
                if not line.strip():
                    continue
                res = parse_frame(line)
                if res.ok:
                    valid += 1
                    pkt = res.data.get("pkt")
                    if last_pkt is not None and pkt is not None and pkt - last_pkt > 1:
                        seq_lost += (pkt - last_pkt - 1)
                    last_pkt = pkt
                    if valid % 10 == 0:   # no spamear: 1 de cada 10
                        d = res.data
                        rate = valid / max(0.001, time.time() - t_start)
                        print(f"OK  pkt={pkt:<6} rpm={d.get('rpm'):<5} "
                              f"coolant={d.get('coolant')}C  "
                              f"valid={valid} crc_fail={crc_fail} perdidos={seq_lost} "
                              f"~{rate:.0f}Hz")
                elif res.error in ("crc_mismatch", "crc_not_hex"):
                    crc_fail += 1
                elif res.error == "bad_prefix":
                    bad_prefix += 1   # lineas de arranque del .ino: normal
                else:
                    other += 1
    except KeyboardInterrupt:
        dur = time.time() - t_start
        print(f"\n--- Resumen ({dur:.1f}s) ---")
        print(f"  validas    : {valid}")
        print(f"  crc_fail   : {crc_fail}")
        print(f"  perdidas   : {seq_lost}")
        print(f"  otras lineas: {bad_prefix} (texto de arranque) / {other} (raras)")
        if valid == 0:
            print("\n  No llego ninguna trama valida. Revisa baud, puerto y que el")
            print("  .ino este emitiendo (busca lineas que empiecen con $A27,).")
        else:
            print("\n  Enlace OK: el backend ve los datos del ESP32 correctamente.")


def main():
    ap = argparse.ArgumentParser(description="Validador de enlace ESP32<->backend")
    ap.add_argument("port", nargs="?", help="puerto COM (omitir para listarlos)")
    ap.add_argument("--baud", type=int, default=SERIAL_BAUD)
    args = ap.parse_args()

    if not args.port:
        cmd_list()
    else:
        cmd_listen(args.port, args.baud)


if __name__ == "__main__":
    main()
