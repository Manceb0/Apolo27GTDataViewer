"""
Auto-deteccion del puerto COM del ESP32.

Escanea TODOS los puertos serie disponibles, abre cada uno y escucha unos
segundos. Si un puerto emite una trama valida del contrato ($A27,...*CRC),
ese es el ESP32. Asi no hay que fijar el COM a mano: se conecta solo.
"""

import time
import serial
from serial.tools import list_ports

from contract import parse_frame
from config import SERIAL_BAUD


def list_com_ports():
    """Lista los puertos COM presentes (device + descripcion)."""
    return list(list_ports.comports())


def probe_port(device, baud=SERIAL_BAUD, probe_seconds=2.0):
    """Abre un puerto y devuelve True si recibe una trama $A27, valida."""
    try:
        with serial.Serial(device, baud, timeout=0.4) as ser:
            t0 = time.time()
            while time.time() - t0 < probe_seconds:
                line = ser.readline().decode("utf-8", errors="ignore")
                if line and parse_frame(line).ok:
                    return True
    except (serial.SerialException, OSError):
        return False
    return False


def find_esp32_port(baud=SERIAL_BAUD, probe_seconds=2.0, verbose=True):
    """Recorre todos los COM y devuelve el primero que emite telemetria valida."""
    ports = list_com_ports()
    if not ports:
        if verbose:
            print("[scan] no hay puertos COM (revisa el cable/USB del ESP32 o del gateway)")
        return None

    if verbose:
        print(f"[scan] {len(ports)} puerto(s): " + ", ".join(p.device for p in ports))

    for p in ports:
        if verbose:
            print(f"[scan] probando {p.device} ({p.description}) ...")
        if probe_port(p.device, baud, probe_seconds):
            if verbose:
                print(f"[scan] OK -> ESP32 detectado en {p.device}")
            return p.device

    if verbose:
        print("[scan] ningun puerto emitio tramas $A27, validas")
    return None


if __name__ == "__main__":
    # Uso directo: python ports.py  -> escanea y reporta
    print("Escaneando todos los COM en busca del ESP32...\n")
    dev = find_esp32_port()
    print("\nResultado:", dev if dev else "no encontrado")
