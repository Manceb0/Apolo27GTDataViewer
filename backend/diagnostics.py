"""
Motor de diagnostico: actual + tendencia + salud del sensor.

Para cada señal mantiene una ventana movil en memoria (rapida a 20 Hz) y produce
un estado:

    ok        valor normal
    warn      acercandose al umbral de riesgo
    critical  paso el umbral critico
    fault     el sensor parece dañado (riel, flatline, salto imposible, incoherencia)
    no_data   el grupo PE dejo de llegar (flag fresh* en false)

Asi el dashboard puede pintar "Coolant: FAULT - sensor trabado" en vez de mostrar
un numero falso como si fuera real.
"""

import time
from collections import deque

from config import (
    SIGNALS, WINDOW_SECONDS, ENGINE_RUNNING_RPM,
    COLD_ENGINE_RPM, COLD_ENGINE_SECS, COLD_ENGINE_TEMP,
)


class SignalAnalyzer:
    """Ventana movil y reglas de una sola señal."""

    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.cfg = cfg
        self.samples = deque()           # (t, value)
        self.last_status = "ok"

    def add(self, t: float, value: float):
        self.samples.append((t, value))
        cutoff = t - WINDOW_SECONDS
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

    def trend_per_min(self) -> float:
        """Pendiente por minuto via minimos cuadrados sobre la ventana."""
        n = len(self.samples)
        if n < 3:
            return 0.0
        t0 = self.samples[0][0]
        xs = [t - t0 for t, _ in self.samples]
        ys = [v for _, v in self.samples]
        mx = sum(xs) / n
        my = sum(ys) / n
        denom = sum((x - mx) ** 2 for x in xs)
        if denom == 0:
            return 0.0
        slope_per_sec = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
        return slope_per_sec * 60.0

    def _is_stuck(self, rpm: float) -> bool:
        cfg = self.cfg
        if cfg["stuck_secs"] <= 0:
            return False
        if rpm < ENGINE_RUNNING_RPM:        # con motor apagado es normal que no cambie
            return False
        span = self.samples[-1][0] - self.samples[0][0]
        if span < cfg["stuck_secs"]:
            return False
        vals = [v for _, v in self.samples]
        return (max(vals) - min(vals)) <= cfg["stuck_eps"]

    def _rate_spike(self) -> bool:
        if len(self.samples) < 2:
            return False
        (t0, v0), (t1, v1) = self.samples[-2], self.samples[-1]
        dt = t1 - t0
        # Ignora muestras casi simultaneas (rafagas del serial): un dt diminuto
        # dispararia falsos "saltos" por el ruido normal de la señal.
        if dt < 0.01:
            return False
        return abs(v1 - v0) / dt > self.cfg["max_rate"]

    def evaluate(self, value: float, fresh: bool, rpm: float) -> dict:
        cfg = self.cfg
        status = "ok"
        reason = ""

        # 1. Sin datos: el grupo PE no esta llegando (lo dice el .ino)
        if not fresh:
            status, reason = "no_data", "sin datos del bus (fresh=false)"

        # 2. Sensor en riel: abierto o en corto
        elif any(abs(value - fv) < 0.01 for fv in cfg["fault_values"]):
            status, reason = "fault", "valor de riel: sensor abierto/en corto"

        # 3. Fuera de rango fisico: lectura imposible -> sensor/cableado
        elif value < cfg["phys_min"] or value > cfg["phys_max"]:
            status, reason = "fault", f"fuera de rango fisico ({value})"

        # 4. Salto imposible entre muestras: ruido/conector intermitente
        elif self._rate_spike():
            status, reason = "fault", "salto imposible (conector/ruido)"

        # 5. Flatline: no se mueve con el motor girando -> sensor trabado
        elif self._is_stuck(rpm):
            status, reason = "fault", "flatline: sensor trabado/cable suelto"

        # 6. Umbrales de riesgo (solo si la lectura es creible)
        elif cfg["direction"] == "high":
            if value >= cfg["critical"]:
                status, reason = "critical", f">= {cfg['critical']}{cfg['unit']}"
            elif value >= cfg["warn"]:
                status, reason = "warn", f">= {cfg['warn']}{cfg['unit']}"
        elif cfg["direction"] == "low":
            if value <= cfg["critical"]:
                status, reason = "critical", f"<= {cfg['critical']}{cfg['unit']}"
            elif value <= cfg["warn"]:
                status, reason = "warn", f"<= {cfg['warn']}{cfg['unit']}"

        self.last_status = status
        return {
            "value": value,
            "status": status,
            "reason": reason,
            "trend_per_min": round(self.trend_per_min(), 3),
            "unit": cfg["unit"],
            "label": cfg["label"],
        }


class Diagnostics:
    """Orquesta todas las señales + reglas cruzadas."""

    def __init__(self):
        self.analyzers = {name: SignalAnalyzer(name, cfg)
                          for name, cfg in SIGNALS.items()}
        self._warm_since = None   # desde cuando el motor gira pidiendo temperatura

    def process(self, data: dict, now: float = None) -> dict:
        now = time.monotonic() if now is None else now
        rpm = float(data.get("rpm", 0) or 0)

        results = {}
        for name, analyzer in self.analyzers.items():
            if name not in data:
                continue
            value = float(data.get(name, 0) or 0)
            fresh = bool(data.get(analyzer.cfg["fresh_flag"], True))
            analyzer.add(now, value)
            results[name] = analyzer.evaluate(value, fresh, rpm)

        self._cross_check_cold_engine(now, rpm, results)
        return results

    def _cross_check_cold_engine(self, now: float, rpm: float, results: dict):
        """Motor girando un buen rato pero coolant frio -> sensor/termostato."""
        coolant = results.get("coolant")
        if not coolant or coolant["status"] in ("fault", "no_data"):
            self._warm_since = None
            return

        if rpm >= COLD_ENGINE_RPM and coolant["value"] < COLD_ENGINE_TEMP:
            if self._warm_since is None:
                self._warm_since = now
            elif (now - self._warm_since) >= COLD_ENGINE_SECS:
                coolant["status"] = "fault"
                coolant["reason"] = ("motor caliente esperado pero coolant frio: "
                                     "sensor de temperatura o termostato")
        else:
            self._warm_since = None
