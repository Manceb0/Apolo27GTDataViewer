"""
Backend Apolo27 GT — pipeline de aseguramiento de telemetria.

Flujo:
    Serial (ESP32)  ->  valida CRC + secuencia  ->  guarda historico (SQLite)
                    ->  diagnostico (actual/tendencia/salud sensor)
                    ->  WebSocket  ->  dashboard Next.js

Uso:
    python server.py            # lee del puerto serie real (config.SERIAL_PORT)
    python server.py --sim      # genera datos simulados (sin ESP32), incl. fallas
    python server.py --port COM7

El dashboard se conecta a  ws://<pc>:8765
"""

import argparse
import asyncio
import json
import threading
import time

import serial  # pyserial
import websockets

import config
from contract import parse_frame
from storage import Storage
from diagnostics import Diagnostics
from simulator import generate_frame


class LinkStats:
    """Salud del enlace: paquetes, perdidas, fallos de CRC, latido."""

    def __init__(self):
        self.last_pkt = None
        self.total = 0
        self.crc_fail = 0
        self.seq_lost = 0
        self.last_recv = 0.0

    def on_valid(self, pkt, recv_at):
        gap = 0
        if self.last_pkt is not None and pkt is not None:
            diff = pkt - self.last_pkt
            if diff > 1:
                gap = diff - 1
                self.seq_lost += gap
        self.last_pkt = pkt
        self.total += 1
        self.last_recv = recv_at
        return gap

    def snapshot(self, now):
        return {
            "total": self.total,
            "crc_fail": self.crc_fail,
            "seq_lost": self.seq_lost,
            "alive": (now - self.last_recv) * 1000 < config.LINK_STALE_MS,
            "loss_pct": round(100 * self.seq_lost / max(1, self.total + self.seq_lost), 2),
        }


class Backend:
    def __init__(self):
        self.storage = Storage()
        self.diag = Diagnostics()
        self.link = LinkStats()
        self.clients = set()
        self.loop = None
        self._last_event_key = {}

    # ---- WebSocket ----------------------------------------------------------
    async def ws_handler(self, websocket):
        self.clients.add(websocket)
        print(f"[ws] cliente conectado ({len(self.clients)} activos)")
        try:
            async for _ in websocket:  # no esperamos mensajes del dashboard
                pass
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            print(f"[ws] cliente desconectado ({len(self.clients)} activos)")

    async def broadcast(self, message: dict):
        if not self.clients:
            return
        payload = json.dumps(message)
        dead = []
        for ws in self.clients:
            try:
                await ws.send(payload)
            except websockets.ConnectionClosed:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    # ---- Procesamiento de una linea cruda -----------------------------------
    def handle_line(self, line: str):
        recv_at = time.time()
        mono = time.monotonic()
        result = parse_frame(line)

        if not result.ok:
            if result.error in ("crc_mismatch", "crc_not_hex"):
                self.link.crc_fail += 1
            return None

        data = result.data
        gap = self.link.on_valid(data.get("pkt"), recv_at)

        # Historico
        self.storage.insert_packet(data, recv_at, gap)

        # Diagnostico
        signals = self.diag.process(data, now=mono)
        self._log_events(recv_at, signals)
        self.storage.commit()

        # Estado general del paquete = peor estado de las señales
        worst = self._worst_status(signals)

        return {
            "type": "telemetry",
            "recv_at": recv_at,
            "pkt": data.get("pkt"),
            "esp_ts": data.get("ts"),
            "raw": data,
            "signals": signals,
            "link": self.link.snapshot(recv_at),
            "overall": worst,
        }

    @staticmethod
    def _worst_status(signals: dict) -> str:
        order = {"ok": 0, "warn": 1, "no_data": 2, "critical": 3, "fault": 4}
        worst = "ok"
        for s in signals.values():
            if order[s["status"]] > order[worst]:
                worst = s["status"]
        return worst

    def _log_events(self, recv_at, signals):
        """Guarda en SQLite solo transiciones (no spamear cada 50 ms)."""
        for name, s in signals.items():
            key = (s["status"], s["reason"])
            if s["status"] != "ok" and self._last_event_key.get(name) != key:
                self.storage.insert_event(recv_at, name, s["status"],
                                          s["reason"], s["value"])
                print(f"[evt] {name}: {s['status'].upper()} - {s['reason']}")
            if s["status"] == "ok":
                self._last_event_key.pop(name, None)
            else:
                self._last_event_key[name] = key

    # ---- Lectores (hilo) ----------------------------------------------------
    def _emit(self, message):
        if message and self.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self.loop)

    def serial_reader(self, port, baud):
        print(f"[serial] abriendo {port} @ {baud}")
        while True:
            try:
                with serial.Serial(port, baud, timeout=1) as ser:
                    print("[serial] conectado")
                    while True:
                        line = ser.readline().decode("utf-8", errors="ignore")
                        if line:
                            self._emit(self.handle_line(line))
            except serial.SerialException as exc:
                print(f"[serial] error: {exc} — reintentando en 2 s")
                time.sleep(2)

    def sim_reader(self, hz=20):
        print(f"[sim] generando telemetria simulada @ {hz} Hz (incl. fallas)")
        period = 1.0 / hz
        while True:
            self._emit(self.handle_line(generate_frame()))
            time.sleep(period)

    # ---- Arranque -----------------------------------------------------------
    async def run(self, args):
        self.loop = asyncio.get_running_loop()

        if args.sim:
            reader = threading.Thread(target=self.sim_reader, daemon=True)
        else:
            port = args.port or config.SERIAL_PORT
            reader = threading.Thread(
                target=self.serial_reader, args=(port, config.SERIAL_BAUD), daemon=True)
        reader.start()

        print(f"[ws] escuchando en ws://{config.WS_HOST}:{config.WS_PORT}")
        async with websockets.serve(self.ws_handler, config.WS_HOST, config.WS_PORT):
            await asyncio.Future()  # corre para siempre


def main():
    ap = argparse.ArgumentParser(description="Backend Apolo27 GT")
    ap.add_argument("--sim", action="store_true", help="datos simulados sin ESP32")
    ap.add_argument("--port", help="puerto serie (sobrescribe config)")
    args = ap.parse_args()

    backend = Backend()
    try:
        asyncio.run(backend.run(args))
    except KeyboardInterrupt:
        print("\n[exit] cerrando…")
        backend.storage.close()


if __name__ == "__main__":
    main()
