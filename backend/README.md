# Backend Apolo27 GT

Pipeline de aseguramiento de telemetria: lee las tramas del ESP32 por Serial,
valida integridad y secuencia, **guarda el historico en SQLite**, calcula
**tendencia** y **diagnostico de salud de sensores**, y emite por **WebSocket**
hacia el dashboard Next.js.

```
Serial (ESP32/PE3)  ->  CRC + secuencia  ->  SQLite (historico)
                    ->  diagnostico (actual/tendencia/sensor)
                    ->  WebSocket :8765  ->  dashboard Next.js
```

## Instalar

```bash
pip install -r requirements.txt
```

## Correr

```bash
# Con el ESP32 conectado (ajusta el puerto en config.py o pásalo por flag):
python server.py --port COM5

# Sin hardware, datos simulados (inyecta una falla de sensor a los 30 s):
python server.py --sim
```

El dashboard se conecta a `ws://<ip-de-la-pc>:8765` y recibe un mensaje JSON por
paquete:

```jsonc
{
  "type": "telemetry",
  "pkt": 1820,
  "overall": "fault",                 // peor estado de todas las señales
  "raw": { "rpm": 3500, "coolant": 215.0, ... },
  "signals": {
    "coolant": {
      "value": 215.0,
      "status": "fault",              // ok | warn | critical | fault | no_data
      "reason": "valor de riel: sensor abierto/en corto",
      "trend_per_min": 0.0,
      "unit": "C", "label": "Coolant Temp"
    },
    "rpm": { "value": 3500, "status": "ok", "trend_per_min": 120.0, ... }
  },
  "link": { "total": 1820, "crc_fail": 0, "seq_lost": 3, "loss_pct": 0.16, "alive": true }
}
```

## Diagnostico de sensores

Para cada señal (ver `config.py`) se detecta no solo el rango, sino **fallas por patron**:

| Estado     | Como se detecta |
|------------|-----------------|
| `fault`    | valor de riel (sensor abierto/corto), fuera de rango fisico, salto imposible, flatline (trabado), o incoherencia cruzada |
| `no_data`  | el grupo PE dejo de llegar (`fresh*` = false del .ino) |
| `critical` | paso el umbral critico configurado |
| `warn`     | acercandose al umbral |
| `ok`       | normal |

Los umbrales y parametros de cada sensor se ajustan en `config.py` sin tocar codigo.

## Historico (SQLite)

Se guarda en `data/telemetry.db`:

- Tabla `telemetry`: cada paquete validado (valores + `pkt`, `seq_gap`, `valid`).
- Tabla `events`: transiciones de diagnostico (cuando un sensor entra en falla/umbral).

Sirve para revisar la sesion despues: tendencias, en que vuelta se calento el
motor, cuando se daño un sensor, perdida de paquetes, etc.

## Pruebas

```bash
python test_backend.py
```

Valida que el CRC coincide con el del `.ino`, que las tramas corruptas se
rechazan, y que la deteccion de fallas (riel, flatline, sin datos, umbrales) funciona.
