#include "WebInterface.h"

WebInterface::WebInterface(WaveformGenerator& wave, AlarmManager& alarm, 
                           DeviceState& dev, ConfigStorage& stor)
  : server(80), events("/events"), waveform(wave), alarms(alarm), 
    device(dev), storage(stor), currentCO2Value(0), lastDataUpdate(0) {}

bool WebInterface::begin() {
  #if WIFI_AP_MODE
    WiFi.mode(WIFI_AP);
    WiFi.softAP(WIFI_AP_SSID, WIFI_AP_PASSWORD);
    
    CMD_SERIAL.println("\n=== WiFi Access Point Started ===");
    CMD_SERIAL.print("SSID: ");
    CMD_SERIAL.println(WIFI_AP_SSID);
    CMD_SERIAL.print("Password: ");
    CMD_SERIAL.println(WIFI_AP_PASSWORD);
    CMD_SERIAL.print("IP address: ");
    CMD_SERIAL.println(WiFi.softAPIP());
  #else
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_STA_SSID, WIFI_STA_PASSWORD);
    
    CMD_SERIAL.print("Connecting to WiFi");
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
      delay(500);
      CMD_SERIAL.print(".");
      attempts++;
    }
    
    if (WiFi.status() != WL_CONNECTED) {
      CMD_SERIAL.println("\nWiFi connection failed");
      return false;
    }
    
    CMD_SERIAL.println("\nWiFi connected!");
    CMD_SERIAL.print("IP address: ");
    CMD_SERIAL.println(WiFi.localIP());
  #endif
  
  setupRoutes();
  server.begin();
  return true;
}

void WebInterface::setupRoutes() {
  server.on("/", HTTP_GET, [this](AsyncWebServerRequest *request){
    request->send(200, "text/html", getIndexHTML());
  });
  
  server.on("/api/settings", HTTP_GET, [this](AsyncWebServerRequest *request){
    StaticJsonDocument<512> doc;
    doc["amplitude"] = waveform.getAmplitude();
    doc["frequency"] = waveform.getFrequency();
    doc["baseline"] = waveform.getBaseline();
    doc["phase"] = waveform.getPhase() * 180.0 / PI;
    doc["alarmHigh"] = alarms.getHighThreshold();
    doc["alarmLow"] = alarms.getLowThreshold();
    doc["alarmHighEnabled"] = alarms.isHighEnabled();
    doc["alarmLowEnabled"] = alarms.isLowEnabled();
    doc["useI2C"] = waveform.isUsingI2CSensor();
    doc["continuousMode"] = device.isContinuousMode();
    
    String response;
    serializeJson(doc, response);
    request->send(200, "application/json", response);
  });
  
  server.on("/api/settings", HTTP_POST, [](AsyncWebServerRequest *request){}, 
    NULL, [this](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total){
    StaticJsonDocument<512> doc;
    deserializeJson(doc, (const char*)data);
    
    if (doc.containsKey("amplitude")) waveform.setAmplitude(doc["amplitude"]);
    if (doc.containsKey("frequency")) waveform.setFrequency(doc["frequency"]);
    if (doc.containsKey("baseline")) waveform.setBaseline(doc["baseline"]);
    if (doc.containsKey("phase")) waveform.setPhase(doc["phase"].as<float>() * PI / 180.0);
    if (doc.containsKey("alarmHigh")) alarms.setHighThreshold(doc["alarmHigh"]);
    if (doc.containsKey("alarmLow")) alarms.setLowThreshold(doc["alarmLow"]);
    if (doc.containsKey("alarmHighEnabled")) alarms.enableHigh(doc["alarmHighEnabled"]);
    if (doc.containsKey("alarmLowEnabled")) alarms.enableLow(doc["alarmLowEnabled"]);
    if (doc.containsKey("useI2C")) waveform.setUseI2CSensor(doc["useI2C"]);
    
    request->send(200, "application/json", "{\"status\":\"ok\"}");
  });
  
  server.on("/api/save", HTTP_POST, [this](AsyncWebServerRequest *request){
    ConfigStorage::Config cfg;
    cfg.amplitude = waveform.getAmplitude();
    cfg.frequency = waveform.getFrequency();
    cfg.baseline = waveform.getBaseline();
    cfg.phase = waveform.getPhase();
    cfg.alarmHigh = alarms.getHighThreshold();
    cfg.alarmLow = alarms.getLowThreshold();
    cfg.alarmHighEnabled = alarms.isHighEnabled();
    cfg.alarmLowEnabled = alarms.isLowEnabled();
    cfg.useI2CSensor = waveform.isUsingI2CSensor();
    storage.saveConfig(cfg);
    
    request->send(200, "application/json", "{\"status\":\"saved\"}");
  });
  
  server.on("/api/load", HTTP_POST, [this](AsyncWebServerRequest *request){
    ConfigStorage::Config cfg = storage.loadConfig();
    waveform.loadFromConfig(cfg);
    alarms.loadFromConfig(cfg);
    
    request->send(200, "application/json", "{\"status\":\"loaded\"}");
  });
  
  events.onConnect([](AsyncEventSourceClient *client){
    client->send("connected", NULL, millis(), 1000);
  });
  server.addHandler(&events);
}

void WebInterface::update() {
  if (millis() - lastDataUpdate >= 100) {
    lastDataUpdate = millis();
    currentCO2Value = waveform.getSample();
    
    StaticJsonDocument<256> doc;
    doc["co2"] = currentCO2Value;
    doc["rate"] = waveform.getRespiratoryRate();
    doc["mode"] = device.isContinuousMode() ? "CONTINUOUS" : "IDLE";
    
    uint8_t status = 0;
    doc["alarm"] = alarms.checkAlarms(currentCO2Value, status);
    
    String data;
    serializeJson(doc, data);
    events.send(data.c_str(), "data", millis());
  }
}

// Continued in Part 2 with HTML...
// Add this method to WebInterface.cpp after the update() method

String WebInterface::getIndexHTML() {
  return R"rawliteral(<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>CO2 Emulator</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}body{font-family:Arial,sans-serif;background:#f0f2f5;padding:20px}
.container{max-width:1000px;margin:0 auto}.card{background:#fff;padding:20px;margin:10px 0;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1)}
h1{color:#1a73e8;margin-bottom:10px}h2{color:#5f6368;font-size:18px;margin-bottom:15px;border-bottom:2px solid #e8eaed;padding-bottom:8px}
.control-group{margin:15px 0;display:flex;align-items:center;flex-wrap:wrap}
label{display:inline-block;min-width:150px;font-weight:500;color:#3c4043}
input[type="number"],input[type="range"]{padding:8px;border:1px solid #dadce0;border-radius:4px;font-size:14px}
input[type="number"]{width:100px}input[type="range"]{width:200px;margin:0 10px}
input[type="checkbox"]{width:20px;height:20px;cursor:pointer}
button{padding:10px 24px;margin:5px;background:#1a73e8;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:14px;font-weight:500}
button:hover{background:#1765cc}button:active{background:#185abc}
button.secondary{background:#5f6368}button.secondary:hover{background:#4d5156}
#waveform{width:100%;height:300px;border:1px solid #dadce0;border-radius:4px;background:#fafafa}
.value-display{display:inline-block;min-width:60px;text-align:right;font-weight:600;color:#1a73e8}
.status-badge{display:inline-block;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}
.status-badge.active{background:#e6f4ea;color:#137333}.status-badge.inactive{background:#fce8e6;color:#c5221f}
.alarm{background:#fef7e0;padding:15px;margin:10px 0;border-left:4px solid #f9ab00;border-radius:4px;display:none}
.alarm.show{display:block}.alarm-icon{font-size:20px;margin-right:8px}
.info-row{display:flex;gap:20px;margin-top:10px;flex-wrap:wrap}.info-item{flex:1;min-width:150px}
.info-label{font-size:12px;color:#5f6368;margin-bottom:4px}.info-value{font-size:24px;font-weight:600;color:#1a73e8}
@media(max-width:768px){.container{padding:10px}.card{padding:15px}input[type="range"]{width:150px}label{min-width:120px}}
</style></head><body>
<div class="container">
<h1>🫁 CO2 Sensor Emulator</h1>
<div class="card"><h2>Live Data</h2><canvas id="waveform"></canvas>
<div class="info-row">
<div class="info-item"><div class="info-label">Current CO2</div><div class="info-value"><span id="currentCO2">--</span> <span style="font-size:14px">mmHg</span></div></div>
<div class="info-item"><div class="info-label">Respiratory Rate</div><div class="info-value"><span id="respRate">--</span> <span style="font-size:14px">br/min</span></div></div>
<div class="info-item"><div class="info-label">Mode</div><div class="info-value" style="font-size:18px"><span class="status-badge" id="modeBadge">IDLE</span></div></div>
</div><div id="alarmStatus" class="alarm"><span class="alarm-icon">⚠️</span><strong>ALARM:</strong> CO2 out of range!</div></div>
<div class="card"><h2>Waveform Control</h2>
<div class="control-group"><label>Amplitude (mmHg):</label>
<input type="range" id="amp" min="0" max="100" step="1" value="38"><span class="value-display" id="ampVal">38</span></div>
<div class="control-group"><label>Frequency (Hz):</label>
<input type="range" id="freq" min="0.1" max="1.0" step="0.05" value="0.25"><span class="value-display" id="freqVal">0.25</span></div>
<div class="control-group"><label>Baseline (mmHg):</label>
<input type="range" id="base" min="-10" max="50" step="1" value="0"><span class="value-display" id="baseVal">0</span></div>
<div class="control-group"><label>Phase (degrees):</label>
<input type="range" id="phase" min="0" max="360" step="10" value="0"><span class="value-display" id="phaseVal">0</span></div>
<div class="control-group"><label>Use I2C Sensor:</label><input type="checkbox" id="useI2C"></div>
<button onclick="updateSettings()">Apply Changes</button></div>
<div class="card"><h2>Alarm Settings</h2>
<div class="control-group"><label>High Alarm (mmHg):</label>
<input type="number" id="alarmHigh" value="50" step="1" style="width:100px"><input type="checkbox" id="alarmHighEn" style="margin-left:10px"> Enable</div>
<div class="control-group"><label>Low Alarm (mmHg):</label>
<input type="number" id="alarmLow" value="30" step="1" style="width:100px"><input type="checkbox" id="alarmLowEn" style="margin-left:10px"> Enable</div>
<button onclick="updateSettings()">Apply Changes</button></div>
<div class="card"><h2>Configuration</h2>
<button onclick="saveConfig()">💾 Save to EEPROM</button>
<button onclick="loadConfig()" class="secondary">📂 Load from EEPROM</button></div></div>
<script>
let canvas=document.getElementById('waveform');let ctx=canvas.getContext('2d');
canvas.width=canvas.offsetWidth;canvas.height=300;let waveformData=[];let maxPoints=canvas.width;
let eventSource=new EventSource('/events');
eventSource.addEventListener('data',function(e){let data=JSON.parse(e.data);updateDisplay(data);});
function updateDisplay(data){document.getElementById('currentCO2').textContent=data.co2.toFixed(2);
document.getElementById('respRate').textContent=data.rate;
let badge=document.getElementById('modeBadge');badge.textContent=data.mode;
badge.className='status-badge '+(data.mode==='CONTINUOUS'?'active':'inactive');
waveformData.push(data.co2);if(waveformData.length>maxPoints)waveformData.shift();drawWaveform();
let alarmDiv=document.getElementById('alarmStatus');
if(data.alarm){alarmDiv.classList.add('show');}else{alarmDiv.classList.remove('show');}}
function drawWaveform(){ctx.fillStyle='#fafafa';ctx.fillRect(0,0,canvas.width,canvas.height);
ctx.strokeStyle='#e0e0e0';ctx.lineWidth=1;
for(let i=0;i<=4;i++){let y=i*canvas.height/4;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(canvas.width,y);ctx.stroke();}
ctx.strokeStyle='#1a73e8';ctx.lineWidth=2;ctx.beginPath();let minVal=0;let maxVal=100;
for(let i=0;i<waveformData.length;i++){let x=i;
let y=canvas.height-(waveformData[i]-minVal)/(maxVal-minVal)*canvas.height;
if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.stroke();}
['amp','freq','base','phase'].forEach(id=>{document.getElementById(id).addEventListener('input',function(){
document.getElementById(id+'Val').textContent=this.value;});});
function updateSettings(){let settings={amplitude:parseFloat(document.getElementById('amp').value),
frequency:parseFloat(document.getElementById('freq').value),baseline:parseFloat(document.getElementById('base').value),
phase:parseFloat(document.getElementById('phase').value),alarmHigh:parseFloat(document.getElementById('alarmHigh').value),
alarmLow:parseFloat(document.getElementById('alarmLow').value),
alarmHighEnabled:document.getElementById('alarmHighEn').checked,
alarmLowEnabled:document.getElementById('alarmLowEn').checked,useI2C:document.getElementById('useI2C').checked};
fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)})
.then(r=>r.json()).then(data=>console.log('Settings updated'));}
function saveConfig(){fetch('/api/save',{method:'POST'}).then(r=>r.json()).then(data=>alert('Configuration saved!'));}
function loadConfig(){fetch('/api/load',{method:'POST'}).then(r=>r.json()).then(data=>location.reload());}
fetch('/api/settings').then(r=>r.json()).then(data=>{document.getElementById('amp').value=data.amplitude;
document.getElementById('ampVal').textContent=data.amplitude;document.getElementById('freq').value=data.frequency;
document.getElementById('freqVal').textContent=data.frequency;document.getElementById('base').value=data.baseline;
document.getElementById('baseVal').textContent=data.baseline;document.getElementById('phase').value=data.phase;
document.getElementById('phaseVal').textContent=data.phase;document.getElementById('alarmHigh').value=data.alarmHigh;
document.getElementById('alarmLow').value=data.alarmLow;document.getElementById('alarmHighEn').checked=data.alarmHighEnabled;
document.getElementById('alarmLowEn').checked=data.alarmLowEnabled;document.getElementById('useI2C').checked=data.useI2C;});
</script></body></html>)rawliteral";
}
