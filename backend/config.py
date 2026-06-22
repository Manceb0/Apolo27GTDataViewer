"""
Configuracion central del backend Apolo27 GT.

Aqui viven los umbrales de riesgo y los parametros de diagnostico de sensores.
Ajustalos a tu motor/ECU sin tocar el resto del codigo.
"""

from pathlib import Path

# ----------------------------------------------------------------------------
# Conexion con el ESP32 (nodo de adquisicion)
# ----------------------------------------------------------------------------
SERIAL_PORT = "COM5"          # Windows: COMx | Linux: /dev/ttyUSB0
SERIAL_BAUD = 115200
FRAME_PREFIX = "$A27,"        # debe coincidir con el .ino (emitTelemetry)

# ----------------------------------------------------------------------------
# Salida WebSocket hacia el dashboard Next.js
# ----------------------------------------------------------------------------
WS_HOST = "0.0.0.0"
WS_PORT = 8765

# ----------------------------------------------------------------------------
# Almacenamiento local (historico)
# ----------------------------------------------------------------------------
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "telemetry.db"

# ----------------------------------------------------------------------------
# Ventana de analisis para tendencia y diagnostico
# ----------------------------------------------------------------------------
WINDOW_SECONDS = 12.0         # cuanto historial reciente se usa para tendencia/flatline
LINK_STALE_MS = 1000          # si no llega trama en este tiempo -> enlace caido

# ----------------------------------------------------------------------------
# Definicion de señales monitoreadas
# ----------------------------------------------------------------------------
# direction:
#   "high" -> el riesgo crece cuando el valor sube (temperatura, rpm)
#   "low"  -> el riesgo crece cuando el valor baja (voltaje de bateria)
#   None   -> sin umbral de riesgo, solo deteccion de falla de sensor
#
# fault_values: valores "riel" tipicos cuando el sensor esta abierto o en corto
#               (el PE3 reporta el extremo de la escala). Igualarlos = sensor dañado.
#
# stuck_eps / stuck_secs: si la señal no se mueve mas que eps durante stuck_secs
#                         con el motor girando -> sensor trabado / cable suelto.
#
# max_rate: cambio por segundo fisicamente plausible. Saltos mayores = ruido/conector.
#
# fresh_flag: nombre del flag de frescura que ya manda el .ino para ese grupo PE.
# ----------------------------------------------------------------------------
SIGNALS = {
    "coolant": {
        "label": "Coolant Temp", "unit": "C", "fresh_flag": "fresh6",
        "phys_min": -30.0, "phys_max": 160.0,
        "fault_values": [-40.0, 215.0],
        "direction": "high", "warn": 100.0, "critical": 110.0,
        "stuck_eps": 0.05, "stuck_secs": 8.0, "max_rate": 40.0,
    },
    "air": {
        "label": "Air Temp", "unit": "C", "fresh_flag": "fresh6",
        "phys_min": -40.0, "phys_max": 130.0,
        "fault_values": [-40.0, 215.0],
        "direction": "high", "warn": 70.0, "critical": 90.0,
        "stuck_eps": 0.05, "stuck_secs": 15.0, "max_rate": 40.0,
    },
    "battery": {
        "label": "Battery", "unit": "V", "fresh_flag": "fresh6",
        "phys_min": 5.0, "phys_max": 18.0,
        "fault_values": [0.0],
        "direction": "low", "warn": 12.0, "critical": 11.5,
        "stuck_eps": 0.01, "stuck_secs": 30.0, "max_rate": 5.0,
    },
    "rpm": {
        "label": "Engine Speed", "unit": "rpm", "fresh_flag": "fresh1",
        "phys_min": 0.0, "phys_max": 20000.0,
        "fault_values": [],
        "direction": "high", "warn": 8000.0, "critical": 9000.0,
        "stuck_eps": 0.0, "stuck_secs": 0.0, "max_rate": 1e9,  # rpm cambia muy rapido: no flatline/rate
    },
    "lambda": {
        "label": "Lambda", "unit": "l", "fresh_flag": "fresh2",
        "phys_min": 0.5, "phys_max": 1.6,
        "fault_values": [0.0],
        "direction": None,
        "stuck_eps": 0.0, "stuck_secs": 0.0, "max_rate": 1e9,
    },
    "map": {
        "label": "MAP", "unit": "kPa", "fresh_flag": "fresh2",
        "phys_min": 0.0, "phys_max": 400.0,
        "fault_values": [],
        "direction": None,
        "stuck_eps": 0.0, "stuck_secs": 0.0, "max_rate": 1e9,
    },
    "tps": {
        "label": "Throttle", "unit": "%", "fresh_flag": "fresh1",
        "phys_min": -5.0, "phys_max": 105.0,
        "fault_values": [],
        "direction": None,
        "stuck_eps": 0.0, "stuck_secs": 0.0, "max_rate": 1e9,
    },
}

# Motor "girando" si las RPM superan esto (usado por la deteccion de flatline)
ENGINE_RUNNING_RPM = 500.0

# Regla cruzada: motor girando sostenidamente pero el coolant sigue frio
# -> sensor de temperatura o termostato sospechoso.
COLD_ENGINE_RPM = 2000.0      # rpm sostenidas
COLD_ENGINE_SECS = 120.0      # durante este tiempo
COLD_ENGINE_TEMP = 40.0       # y coolant aun por debajo de esto (C)
