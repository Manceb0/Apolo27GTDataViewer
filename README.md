# Apolo27 GT Data Viewer

Sistema local de telemetria para Apolo27 GT. El ESP32 lee CAN por TWAI, emite
tramas seriales con CRC, el backend Python valida/diagnostica/guarda historico
en SQLite y el dashboard HTML visualiza en vivo por WebSocket.

## Arquitectura

```text
ESP32 CAN/TWAI -> Serial $A27,{json}*CRC -> Backend Python -> SQLite
                                                   |
                                                   v
                                           WebSocket :8765
                                                   |
                                                   v
                                           Dashboard :8000
```

## Pines CAN del ESP32

El firmware actual usa pines seguros para ESP32 clasico:

| Senal | Pin ESP32 |
| --- | --- |
| CAN TX | GPIO21 |
| CAN RX | GPIO22 |
| GND | Comun con el transceiver |

> Nota: no usar GPIO6/GPIO7 en ESP32 clasico. Esos pines pertenecen al flash
> interno y pueden provocar reinicios por watchdog.

## Requisitos

- Python 3.12+
- Dependencias del backend:

```bash
pip install -r backend/requirements.txt
```

- Para compilar/subir el firmware: Arduino CLI con core `esp32:esp32`.

## Subir firmware al ESP32

Con el ESP32 conectado por USB, identifica el puerto COM. En nuestra prueba fue
`COM5`.

```bash
arduino-cli core install esp32:esp32
arduino-cli compile --fqbn esp32:esp32:esp32 CAN_BUS_READING_INTERFACE_WORKING/CAN_BUS_READING_INTERFACE_WORKING.ino
arduino-cli upload -p COM5 --fqbn esp32:esp32:esp32 CAN_BUS_READING_INTERFACE_WORKING/CAN_BUS_READING_INTERFACE_WORKING.ino
```

El firmware tambien levanta un punto de acceso WiFi:

- SSID: `APOLO27GT_TELEMETRY`
- Password: `apolo27gt`
- IP: `192.168.4.1`

## Ejecutar backend

Modo hardware, indicando el COM:

```bash
cd backend
python server.py --port COM5
```

Modo hardware con autodeteccion de puerto:

```bash
cd backend
python server.py
```

Modo simulado desde backend:

```bash
cd backend
python server.py --sim
```

El backend publica WebSocket en:

```text
ws://localhost:8765
```

## Abrir dashboard

En otra terminal:

```bash
cd dashboard
python -m http.server 8000
```

Luego abrir:

```text
http://localhost:8000
```

## Switch Live / Simulado

El dashboard tiene un unico selector:

- `LIVE`: lee datos reales desde `ws://localhost:8765`.
- `SIMULADO`: genera telemetria local de prueba sin depender del backend.

Cada cambio de modo reinicia el historico visual, la grafica, los eventos de
diagnostico y los contadores para que cada prueba empiece limpia.

## Pruebas

```bash
cd backend
python test_backend.py
```

Las pruebas validan CRC, rechazo de tramas corruptas y diagnosticos principales
como no-data, riel de sensor, flatline y umbrales.
