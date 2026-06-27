"""
Almacenamiento local del historico de telemetria (SQLite).

Dos tablas:
  - telemetry: cada paquete validado, con metadatos de calidad de enlace.
  - events:    eventos de diagnostico (fallas de sensor, cruces de umbral).

El historico permite revisar la sesion despues: tendencias, en que momento
fallo un sensor, picos de temperatura, perdida de paquetes, etc.
"""

import json
import sqlite3
import time
from typing import Optional

from config import DB_PATH, DATA_DIR

# Columnas "primarias" que guardamos como campos consultables. El resto del
# paquete se conserva integro en raw_json por si se agregan señales luego.
CORE_FIELDS = [
    "rpm", "tps", "fuel", "ign", "baro", "map", "lambda",
    "battery", "air", "coolant", "an5", "an6", "an7", "an8",
]


class Storage:
    def __init__(self, db_path=DB_PATH):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()
        self.session_id = int(time.time())

    def _init_schema(self):
        cols = ", ".join(f'"{c}" REAL' for c in CORE_FIELDS)
        self.conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS telemetry (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   INTEGER NOT NULL,
                recv_at      REAL    NOT NULL,   -- epoch en la PC
                esp_ts       INTEGER,            -- millis del ESP32
                pkt          INTEGER,            -- secuencia de paquete
                seq_gap      INTEGER,            -- paquetes perdidos antes de este
                crc_ok       INTEGER,            -- 1 siempre (solo guardamos validos)
                valid        INTEGER,            -- flag 'valid' del .ino
                {cols},
                raw_json     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tel_session ON telemetry(session_id, recv_at);

            CREATE TABLE IF NOT EXISTS events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   INTEGER NOT NULL,
                recv_at      REAL    NOT NULL,
                signal       TEXT,
                status       TEXT,               -- warn | critical | fault | no_data
                reason       TEXT,
                value        REAL
            );
            CREATE INDEX IF NOT EXISTS idx_evt_session ON events(session_id, recv_at);
            """
        )
        self.conn.commit()

    def insert_packet(self, data: dict, recv_at: float, seq_gap: int):
        placeholders = ", ".join("?" for _ in CORE_FIELDS)
        cols = ", ".join(f'"{c}"' for c in CORE_FIELDS)
        values = [data.get(c) for c in CORE_FIELDS]
        self.conn.execute(
            f"""INSERT INTO telemetry
                (session_id, recv_at, esp_ts, pkt, seq_gap, crc_ok, valid, {cols}, raw_json)
                VALUES (?, ?, ?, ?, ?, 1, ?, {placeholders}, ?)""",
            [
                self.session_id, recv_at, data.get("ts"), data.get("pkt"),
                seq_gap, 1 if data.get("valid") else 0, *values,
                json.dumps(data, separators=(",", ":")),
            ],
        )

    def insert_event(self, recv_at: float, signal: str, status: str,
                     reason: str, value: Optional[float]):
        self.conn.execute(
            """INSERT INTO events (session_id, recv_at, signal, status, reason, value)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [self.session_id, recv_at, signal, status, reason, value],
        )

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.commit()
        self.conn.close()
