#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <driver/twai.h>
#include "esp_task_wdt.h"

// ===================== CONFIG =====================
// --- CAN bus (TWAI) ---
#define CAN1_RX_PIN GPIO_NUM_6
#define CAN1_TX_PIN GPIO_NUM_7

#define ID_PE1 0x0CFFF048
#define ID_PE2 0x0CFFF148
#define ID_PE4 0x0CFFF348
#define ID_PE6 0x0CFFF548

// --- Telemetria / contrato de datos ---
#define TELEMETRY_PERIOD_MS 50     // 20 Hz de salida hacia el gateway/PC
#define CAN_HEALTH_PERIOD_MS 500   // chequeo de salud del bus CAN
#define STALE_MS 1000              // si un grupo PE no llega en este tiempo -> dato obsoleto

// --- Watchdog (auto-recuperacion) ---
#define WDT_TIMEOUT_MS 4000

// --- Umbrales configurables de variables criticas ---
#define RPM_MAX 9000
#define COOLANT_MAX 110.0          // °C
#define BATTERY_MIN 11.5           // V

// --- LoRa (transmision) ---
// Este nodo es el de ADQUISICION (lee CAN del PE3 y arma el paquete).
// La salida canonica va por Serial como trama enmarcada con CRC.
// Para enviar por LoRa, conecta tu modulo y llama sendOverLoRa(frame).
#define USE_LORA 0
// ==================================================

WebServer server(80);

const char* ssid = "APOLO27GT_TELEMETRY";
const char* password = "apolo27gt";

uint16_t rpm = 0;
float tps = 0, fuelMs = 0, ignitionDeg = 0;
float baro = 0, mapVal = 0, lambda = 0;
float an5 = 0, an6 = 0, an7 = 0, an8 = 0;
float battery = 0, airTemp = 0, coolantTemp = 0;
String pressureType = "-", tempType = "-";

uint32_t msgCount = 0;
uint32_t lastCanMs = 0;

// Frescura por grupo PE (para detectar datos obsoletos por señal)
uint32_t lastPE1Ms = 0, lastPE2Ms = 0, lastPE4Ms = 0, lastPE6Ms = 0;

// Metadatos del contrato de telemetria
uint32_t packetId = 0;     // secuencia de paquete (tambien sirve de heartbeat)
uint32_t busErrCount = 0;  // errores/recuperaciones del bus CAN
uint32_t lastTelemetryMs = 0;
uint32_t lastHealthMs = 0;

uint16_t u16le(uint8_t *d, int i) {
  return d[i] | (d[i + 1] << 8);
}

int16_t s16le(uint8_t *d, int i) {
  return (int16_t)(d[i] | (d[i + 1] << 8));
}

void readCAN() {
  twai_message_t msg;

  while (twai_receive(&msg, 0) == ESP_OK) {
    msgCount++;
    lastCanMs = millis();

    if (!(msg.flags & TWAI_MSG_FLAG_EXTD)) continue;
    if (msg.data_length_code < 8) continue;

    if (msg.identifier == ID_PE1) {
      rpm = u16le(msg.data, 0);
      tps = s16le(msg.data, 2) * 0.1;
      fuelMs = s16le(msg.data, 4) * 0.1;
      ignitionDeg = s16le(msg.data, 6) * 0.1;
      lastPE1Ms = lastCanMs;
    }

    else if (msg.identifier == ID_PE2) {
      baro = s16le(msg.data, 0) * 0.01;
      mapVal = s16le(msg.data, 2) * 0.01;
      lambda = s16le(msg.data, 4) * 0.01;
      pressureType = (msg.data[6] & 0x01) ? "kPa" : "psi";
      lastPE2Ms = lastCanMs;
    }

    else if (msg.identifier == ID_PE4) {
      an5 = s16le(msg.data, 0) * 0.001;
      an6 = s16le(msg.data, 2) * 0.001;
      an7 = s16le(msg.data, 4) * 0.001;
      an8 = s16le(msg.data, 6) * 0.001;
      lastPE4Ms = lastCanMs;
    }

    else if (msg.identifier == ID_PE6) {
      battery = s16le(msg.data, 0) * 0.01;
      airTemp = s16le(msg.data, 2) * 0.1;
      coolantTemp = s16le(msg.data, 4) * 0.1;
      tempType = (msg.data[6] & 0x01) ? "°C" : "°F";
      lastPE6Ms = lastCanMs;
    }
  }
}

bool isFresh(uint32_t lastMs) {
  return lastMs != 0 && (millis() - lastMs) < STALE_MS;
}

// Telemetria valida = al menos un grupo de señales del PE3 esta fresco
bool telemetryValid() {
  return isFresh(lastPE1Ms) || isFresh(lastPE2Ms) ||
         isFresh(lastPE4Ms) || isFresh(lastPE6Ms);
}

// CRC16-CCITT (poly 0x1021, init 0xFFFF) para verificar integridad del paquete
uint16_t crc16(const char* data, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; i++) {
    crc ^= (uint16_t)(uint8_t)data[i] << 8;
    for (int b = 0; b < 8; b++) {
      crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : (crc << 1);
    }
  }
  return crc;
}

String jsonData() {
  String s = "{";
  s += "\"rpm\":" + String(rpm) + ",";
  s += "\"tps\":" + String(tps, 1) + ",";
  s += "\"fuel\":" + String(fuelMs, 1) + ",";
  s += "\"ign\":" + String(ignitionDeg, 1) + ",";
  s += "\"baro\":" + String(baro, 2) + ",";
  s += "\"map\":" + String(mapVal, 2) + ",";
  s += "\"lambda\":" + String(lambda, 2) + ",";
  s += "\"pressure\":\"" + pressureType + "\",";
  s += "\"battery\":" + String(battery, 2) + ",";
  s += "\"air\":" + String(airTemp, 1) + ",";
  s += "\"coolant\":" + String(coolantTemp, 1) + ",";
  s += "\"tempType\":\"" + tempType + "\",";
  s += "\"an5\":" + String(an5, 3) + ",";
  s += "\"an6\":" + String(an6, 3) + ",";
  s += "\"an7\":" + String(an7, 3) + ",";
  s += "\"an8\":" + String(an8, 3) + ",";
  s += "\"count\":" + String(msgCount) + ",";
  s += "\"pkt\":" + String(packetId) + ",";
  s += "\"ts\":" + String(millis()) + ",";
  s += "\"fresh1\":" + String(isFresh(lastPE1Ms) ? "true" : "false") + ",";
  s += "\"fresh2\":" + String(isFresh(lastPE2Ms) ? "true" : "false") + ",";
  s += "\"fresh4\":" + String(isFresh(lastPE4Ms) ? "true" : "false") + ",";
  s += "\"fresh6\":" + String(isFresh(lastPE6Ms) ? "true" : "false") + ",";
  s += "\"busErr\":" + String(busErrCount) + ",";
  s += "\"valid\":" + String(telemetryValid() ? "true" : "false") + ",";
  s += "\"alive\":" + String((millis() - lastCanMs < 1000) ? "true" : "false");
  s += "}";
  return s;
}

// Punto de envio por LoRa. Conecta tu modulo y descomenta el bloque de abajo.
void sendOverLoRa(const String& frame) {
#if USE_LORA
  // Ejemplo con la libreria LoRa de Sandeep Mistry (#include <LoRa.h>):
  // LoRa.beginPacket();
  // LoRa.print(frame);
  // LoRa.endPacket();
#endif
}

// Arma la trama del contrato y la emite por Serial (y LoRa si esta activo):
//   $A27,{json}*CRC16HEX
// El backend Python valida el CRC sobre el texto entre "$A27," y "*".
void emitTelemetry() {
  packetId++;                       // secuencia + heartbeat: avanza siempre, haya CAN o no
  String json = jsonData();
  uint16_t crc = crc16(json.c_str(), json.length());

  char crcHex[5];
  sprintf(crcHex, "%04X", crc);

  String frame = "$A27," + json + "*" + crcHex;
  Serial.println(frame);
  sendOverLoRa(frame);
}

// Monitorea el bus CAN y lo recupera automaticamente si entra en bus-off
void canHealthCheck() {
  twai_status_info_t st;
  if (twai_get_status_info(&st) != ESP_OK) return;

  if (st.state == TWAI_STATE_BUS_OFF) {
    twai_initiate_recovery();
    busErrCount++;
  } else if (st.state == TWAI_STATE_STOPPED) {
    twai_start();
    busErrCount++;
  }
}

const char page[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Apolo27 GT Telemetry</title>
<style>
:root{
  --bg:#05070a;
  --panel:#0c1118;
  --panel2:#111824;
  --line:#1f2b3b;
  --text:#f4f7fb;
  --muted:#7f8ea3;
  --blue:#00a3ff;
  --red:#ff2738;
  --green:#21e685;
  --yellow:#ffd166;
}
*{box-sizing:border-box}
body{
  margin:0;
  background:
    radial-gradient(circle at top left, rgba(0,163,255,.22), transparent 35%),
    radial-gradient(circle at bottom right, rgba(255,39,56,.18), transparent 35%),
    var(--bg);
  color:var(--text);
  font-family:Inter,Arial,Helvetica,sans-serif;
}
.top{
  padding:22px 28px;
  border-bottom:1px solid var(--line);
  background:rgba(5,7,10,.82);
  backdrop-filter:blur(14px);
  display:flex;
  justify-content:space-between;
  align-items:center;
}
.brand{
  display:flex;
  flex-direction:column;
}
.logo{
  font-size:31px;
  font-weight:900;
  letter-spacing:.08em;
}
.logo span{color:var(--blue)}
.sub{
  color:var(--muted);
  font-size:13px;
  margin-top:4px;
  letter-spacing:.15em;
}
.statusBox{
  text-align:right;
  font-size:13px;
  color:var(--muted);
}
.status{
  display:inline-block;
  padding:8px 12px;
  border-radius:999px;
  background:#1a222e;
  margin-bottom:6px;
  font-weight:800;
}
.online{color:var(--green)}
.offline{color:var(--red)}
.wrap{
  padding:22px;
  display:grid;
  grid-template-columns:1.4fr .8fr;
  gap:18px;
}
.card{
  background:linear-gradient(180deg,rgba(17,24,36,.96),rgba(9,13,19,.96));
  border:1px solid var(--line);
  border-radius:24px;
  padding:20px;
  box-shadow:0 18px 40px rgba(0,0,0,.32);
}
.rpmCard{
  min-height:330px;
}
.label{
  font-size:12px;
  color:var(--muted);
  text-transform:uppercase;
  letter-spacing:.16em;
  font-weight:800;
}
.rpmValue{
  font-size:112px;
  line-height:1;
  font-weight:950;
  margin-top:28px;
  letter-spacing:-.06em;
}
.unit{
  color:var(--muted);
  font-weight:700;
}
.barOuter{
  margin-top:30px;
  width:100%;
  height:22px;
  border-radius:999px;
  background:#151d29;
  overflow:hidden;
  border:1px solid #263449;
}
.barInner{
  height:100%;
  width:0%;
  background:linear-gradient(90deg,var(--green),var(--yellow),var(--red));
  border-radius:999px;
  transition:.18s;
}
.shift{
  display:grid;
  grid-template-columns:repeat(8,1fr);
  gap:8px;
  margin-top:18px;
}
.light{
  height:22px;
  border-radius:8px;
  background:#182130;
  border:1px solid #263449;
}
.light.on:nth-child(-n+4){background:var(--green)}
.light.on:nth-child(n+5):nth-child(-n+6){background:var(--yellow)}
.light.on:nth-child(n+7){background:var(--red)}
.sideGrid{
  display:grid;
  grid-template-columns:1fr;
  gap:18px;
}
.metricGrid{
  grid-column:1 / 3;
  display:grid;
  grid-template-columns:repeat(4,1fr);
  gap:18px;
}
.metric{
  min-height:135px;
}
.value{
  font-size:38px;
  font-weight:900;
  margin-top:18px;
}
.smallValue{
  font-size:30px;
}
.footer{
  padding:0 22px 22px;
  color:var(--muted);
  font-size:12px;
  letter-spacing:.08em;
}
.danger{color:var(--red)}
.good{color:var(--green)}
.warn{color:var(--yellow)}
@media(max-width:900px){
  .wrap{grid-template-columns:1fr}
  .metricGrid{grid-column:auto;grid-template-columns:repeat(2,1fr)}
  .rpmValue{font-size:82px}
  .top{align-items:flex-start;gap:12px;flex-direction:column}
  .statusBox{text-align:left}
}
</style>
</head>
<body>
<div class="top">
  <div class="brand">
    <div class="logo">APOLO<span>27</span> GT</div>
    <div class="sub">PE3 LIVE TELEMETRY DASHBOARD</div>
  </div>
  <div class="statusBox">
    <div id="alive" class="status offline">CAN OFFLINE</div><br>
    Messages: <span id="count">0</span>
  </div>
</div>

<div class="wrap">
  <div class="card rpmCard">
    <div class="label">Engine Speed</div>
    <div class="rpmValue"><span id="rpm">0</span></div>
    <div class="unit">RPM</div>
    <div class="barOuter"><div id="rpmBar" class="barInner"></div></div>
    <div class="shift">
      <div class="light" id="l1"></div><div class="light" id="l2"></div>
      <div class="light" id="l3"></div><div class="light" id="l4"></div>
      <div class="light" id="l5"></div><div class="light" id="l6"></div>
      <div class="light" id="l7"></div><div class="light" id="l8"></div>
    </div>
  </div>

  <div class="sideGrid">
    <div class="card">
      <div class="label">Throttle Position</div>
      <div class="value"><span id="tps">0.0</span><span class="unit"> %</span></div>
    </div>
    <div class="card">
      <div class="label">Battery Voltage</div>
      <div class="value"><span id="battery">0.00</span><span class="unit"> V</span></div>
    </div>
  </div>

  <div class="metricGrid">
    <div class="card metric">
      <div class="label">MAP</div>
      <div class="value smallValue"><span id="map">0.00</span></div>
      <div class="unit" id="pressure">kPa / psi</div>
    </div>

    <div class="card metric">
      <div class="label">Lambda</div>
      <div class="value smallValue"><span id="lambda">0.00</span></div>
      <div class="unit">λ</div>
    </div>

    <div class="card metric">
      <div class="label">Coolant</div>
      <div class="value smallValue"><span id="coolant">0.0</span></div>
      <div class="unit" id="tempType">°C / °F</div>
    </div>

    <div class="card metric">
      <div class="label">Air Temp</div>
      <div class="value smallValue"><span id="air">0.0</span></div>
      <div class="unit">Temp</div>
    </div>

    <div class="card metric">
      <div class="label">Fuel Open Time</div>
      <div class="value smallValue"><span id="fuel">0.0</span></div>
      <div class="unit">ms</div>
    </div>

    <div class="card metric">
      <div class="label">Ignition Angle</div>
      <div class="value smallValue"><span id="ign">0.0</span></div>
      <div class="unit">deg</div>
    </div>

    <div class="card metric">
      <div class="label">Barometer</div>
      <div class="value smallValue"><span id="baro">0.00</span></div>
      <div class="unit">Pressure</div>
    </div>

    <div class="card metric">
      <div class="label">Analog Inputs</div>
      <div class="value smallValue"><span id="analogs">0.000</span></div>
      <div class="unit">AN5 / AN6 / AN7 / AN8</div>
    </div>
  </div>
</div>

<div class="footer">APOLO27 GT | ESP32-CAN-X2 | PE3 ECU | LIVE CAN BUS</div>

<script>
function setText(id,v){document.getElementById(id).innerText=v;}

async function update(){
  try{
    const r = await fetch('/data');
    const d = await r.json();

    setText('rpm', d.rpm);
    setText('tps', d.tps.toFixed(1));
    setText('battery', d.battery.toFixed(2));
    setText('map', d.map.toFixed(2));
    setText('lambda', d.lambda.toFixed(2));
    setText('coolant', d.coolant.toFixed(1));
    setText('air', d.air.toFixed(1));
    setText('fuel', d.fuel.toFixed(1));
    setText('ign', d.ign.toFixed(1));
    setText('baro', d.baro.toFixed(2));
    setText('pressure', d.pressure);
    setText('tempType', d.tempType);
    setText('count', d.count);
    setText('analogs', d.an5.toFixed(3) + " / " + d.an6.toFixed(3) + " / " + d.an7.toFixed(3) + " / " + d.an8.toFixed(3));

    let pct = Math.min(d.rpm / 9000 * 100, 100);
    document.getElementById('rpmBar').style.width = pct + "%";

    let lights = Math.floor(d.rpm / 9000 * 8);
    for(let i=1;i<=8;i++){
      document.getElementById('l'+i).className = i <= lights ? "light on" : "light";
    }

    const alive = document.getElementById('alive');
    if(d.alive){
      alive.innerText="CAN ONLINE";
      alive.className="status online";
    }else{
      alive.innerText="CAN OFFLINE";
      alive.className="status offline";
    }

  }catch(e){}
}

setInterval(update,150);
update();
</script>
</body>
</html>
)rawliteral";

void setupCAN() {
  twai_general_config_t g_config =
    TWAI_GENERAL_CONFIG_DEFAULT(CAN1_TX_PIN, CAN1_RX_PIN, TWAI_MODE_NORMAL);

  twai_timing_config_t t_config = TWAI_TIMING_CONFIG_250KBITS();
  twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

  twai_driver_install(&g_config, &t_config, &f_config);
  twai_start();
}

void setup() {
  Serial.begin(115200);
  delay(2000);

  setupCAN();

  // Watchdog: reinicia el ESP32 si el loop se cuelga (auto-recuperacion)
#if ESP_IDF_VERSION_MAJOR >= 5
  esp_task_wdt_config_t twdt = {
    .timeout_ms = WDT_TIMEOUT_MS,
    .idle_core_mask = 0,
    .trigger_panic = true
  };
  esp_task_wdt_reconfigure(&twdt);
#else
  esp_task_wdt_init(WDT_TIMEOUT_MS / 1000, true);
#endif
  esp_task_wdt_add(NULL);

  WiFi.softAP(ssid, password);

  server.on("/", []() {
    server.send_P(200, "text/html", page);
  });

  server.on("/data", []() {
    server.send(200, "application/json", jsonData());
  });

  server.begin();

  Serial.println("APOLO27 GT Dashboard listo");
  Serial.print("WiFi: ");
  Serial.println(ssid);
  Serial.print("Password: ");
  Serial.println(password);
  Serial.print("IP: ");
  Serial.println(WiFi.softAPIP());
}

void loop() {
  readCAN();
  server.handleClient();

  uint32_t now = millis();

  // Emite la trama del contrato a ritmo fijo (heartbeat + secuencia siempre avanza)
  if (now - lastTelemetryMs >= TELEMETRY_PERIOD_MS) {
    lastTelemetryMs = now;
    emitTelemetry();
  }

  // Vigila y recupera el bus CAN
  if (now - lastHealthMs >= CAN_HEALTH_PERIOD_MS) {
    lastHealthMs = now;
    canHealthCheck();
  }

  esp_task_wdt_reset();
}