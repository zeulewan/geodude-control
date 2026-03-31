#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoOTA.h>
#include <TMCStepper.h>

const char* ssid = "groundstation";
const char* password = "Temp1234";

WebServer server(80);

#define TMC_RX_PIN 16
#define TMC_TX_PIN 17
#define R_SENSE    0.11f

// Driver pin assignments
struct DriverPins {
  int step;
  int dir;
};

DriverPins drvPins[4] = {
  {32, 33},  // Driver 0
  {25, 26},  // Driver 1
  {22, 23},  // Driver 2
  {19, 18},  // Driver 3
};

TMC2209Stepper driver0(&Serial2, R_SENSE, 0x00);
TMC2209Stepper driver1(&Serial2, R_SENSE, 0x01);
TMC2209Stepper driver2(&Serial2, R_SENSE, 0x02);
TMC2209Stepper driver3(&Serial2, R_SENSE, 0x03);
TMC2209Stepper* drivers[] = {&driver0, &driver1, &driver2, &driver3};

int driversFound = 0;
String scanResult;

// Motor state
bool motorRunning[4] = {false, false, false, false};
bool motorDir[4] = {true, true, true, true};
int stepDelay = 2000; // microseconds between steps (lower = faster)
int stepsRemaining[4] = {0, 0, 0, 0};
int currentMA = 400;

String doScan() {
  String r = "";
  driversFound = 0;
  for (int i = 0; i < 4; i++) drivers[i]->begin();
  delay(100);

  for (int i = 0; i < 4; i++) {
    uint8_t ver = drivers[i]->version();
    char buf[256];
    if (ver == 0x21) {
      driversFound++;
      uint32_t ds = drivers[i]->DRV_STATUS();
      snprintf(buf, sizeof(buf),
        "Driver %d (0x%02X): TMC2209\n"
        "  Microsteps:  %d\n"
        "  RMS Current: %d mA\n"
        "  IRUN: %d  IHOLD: %d\n"
        "  GSTAT: 0x%02X\n"
        "  DRV_STATUS: 0x%08X\n"
        "  standstill:%d stealth:%d cs_actual:%d\n"
        "  ot:%d otpw:%d\n\n",
        i, i, drivers[i]->microsteps(), drivers[i]->rms_current(),
        drivers[i]->irun(), drivers[i]->ihold(),
        drivers[i]->GSTAT(), ds,
        (ds >> 31) & 1, (ds >> 30) & 1, (ds >> 16) & 0x1F,
        (ds >> 1) & 1, ds & 1);
    } else {
      snprintf(buf, sizeof(buf), "Driver %d (0x%02X): not found\n", i, i);
    }
    r += buf;
  }
  return r;
}

void handleRoot() {
  String statusColor = driversFound > 0 ? "#0f0" : "#f00";
  String statusText = driversFound > 0
    ? String(driversFound) + " driver(s) connected"
    : "No drivers found - check wiring / 24V power";

  String motorStatus = "";
  for (int i = 0; i < 4; i++) {
    String state = motorRunning[i] ? "RUNNING" : "stopped";
    String dir = motorDir[i] ? "CW" : "CCW";
    motorStatus += "<tr><td>Driver " + String(i) + "</td>"
      "<td>" + state + " (" + dir + ")</td>"
      "<td>"
      "<a class='btn' href='/move?d=" + String(i) + "&steps=200'>200 steps</a> "
      "<a class='btn' href='/move?d=" + String(i) + "&steps=1000'>1000</a> "
      "<a class='btn' href='/move?d=" + String(i) + "&steps=-200'>-200</a> "
      "<a class='btn' href='/move?d=" + String(i) + "&steps=-1000'>-1000</a> "
      "<a class='btn stop' href='/stop?d=" + String(i) + "'>STOP</a>"
      "</td></tr>";
  }

  String html = "<html><head><title>ESP32-TMC</title>"
    "<meta name='viewport' content='width=device-width'>"
    "<style>body{font-family:monospace;background:#111;color:#eee;padding:20px;}"
    "pre{background:#000;padding:15px;border:1px solid #333;margin-top:15px;}"
    ".status{padding:12px;border-radius:6px;font-size:1.2em;margin:15px 0;}"
    ".btn{display:inline-block;padding:6px 12px;background:#333;color:#0ff;"
    "text-decoration:none;border:1px solid #0ff;border-radius:4px;margin:2px;font-size:0.9em;}"
    ".btn:hover{background:#0ff;color:#000;}"
    ".btn.stop{border-color:#f00;color:#f00;}.btn.stop:hover{background:#f00;color:#000;}"
    "table{border-collapse:collapse;width:100%;margin:15px 0;}"
    "td,th{padding:8px;border:1px solid #333;text-align:left;}"
    "h3{color:#0ff;margin-top:25px;}"
    ".controls{margin:15px 0;}"
    "</style></head><body>"
    "<h2>ESP32-TMC Controller</h2>"
    "<div class='status' style='border:2px solid " + statusColor + ";color:" + statusColor + ";'>"
    + statusText + "</div>"
    "<p>WiFi: " + WiFi.localIP().toString() + " | Uptime: " + String(millis()/1000) + "s"
    " | Step delay: " + String(stepDelay) + "us</p>"
    "<div class='controls'>"
    "<a class='btn' href='/scan'>Scan Drivers</a> "
    "<a class='btn' href='/speed?us=5000'>Slow</a> "
    "<a class='btn' href='/speed?us=2000'>Medium</a> "
    "<a class='btn' href='/speed?us=500'>Fast</a> "
    "<a class='btn' href='/setup'>Setup Drivers</a>"
    "</div>"
    "<h3>Current Setting</h3>"
    "<form action='/current' method='get' style='margin:10px 0;'>"
    "<input type='number' name='ma' min='50' max='2000' value='" + String(currentMA) + "' "
    "style='background:#000;color:#0ff;border:1px solid #0ff;padding:6px;width:80px;font-family:monospace;'>"
    " mA <input type='submit' value='Set' class='btn' style='border:none;cursor:pointer;'>"
    "</form>"
    "<p style='color:#666;'>Range: 50-2000 mA. Motor rated current recommended.</p>"
    "<h3>Motor Control</h3>"
    "<table><tr><th>Driver</th><th>Status</th><th>Actions</th></tr>"
    + motorStatus + "</table>"
    "<h3>Driver Info</h3>"
    "<pre>" + scanResult + "</pre>"
    "</body></html>";
  server.send(200, "text/html", html);
}

void handleScan() {
  scanResult = doScan();
  server.sendHeader("Location", "/");
  server.send(302);
}

void handleSetup() {
  String r = "Setting up drivers...\n";
  for (int i = 0; i < 4; i++) {
    if (drivers[i]->version() == 0x21) {
      drivers[i]->toff(4);
      drivers[i]->rms_current(currentMA);
      drivers[i]->microsteps(16);
      drivers[i]->en_spreadCycle(false); // StealthChop
      drivers[i]->pwm_autoscale(true);
      drivers[i]->GSTAT(0x07); // Clear flags
      // Force IHOLD=0 after all other config (rms_current sets IHOLD internally)
      uint32_t reg = drivers[i]->IHOLD_IRUN();
      reg &= ~(0x1F);       // clear IHOLD bits [4:0]
      reg &= ~(0xF << 16);  // clear IHOLDDELAY bits [19:16]
      reg |= (1 << 16);     // IHOLDDELAY=1 (fast transition to IHOLD)
      drivers[i]->IHOLD_IRUN(reg);
      r += "Driver " + String(i) + ": configured (" + String(currentMA) + "mA, IHOLD=0, 16 microsteps, StealthChop)\n";
    }
  }
  scanResult = doScan();
  server.sendHeader("Location", "/");
  server.send(302);
}

void handleMove() {
  int d = server.arg("d").toInt();
  int steps = server.arg("steps").toInt();
  if (d >= 0 && d < 4) {
    motorDir[d] = steps > 0;
    digitalWrite(drvPins[d].dir, motorDir[d] ? HIGH : LOW);
    stepsRemaining[d] = abs(steps);
    motorRunning[d] = true;
  }
  server.sendHeader("Location", "/");
  server.send(302);
}

void handleStop() {
  int d = server.arg("d").toInt();
  if (d >= 0 && d < 4) {
    motorRunning[d] = false;
    stepsRemaining[d] = 0;
  }
  server.sendHeader("Location", "/");
  server.send(302);
}

void handleSpeed() {
  stepDelay = server.arg("us").toInt();
  if (stepDelay < 100) stepDelay = 100;
  if (stepDelay > 50000) stepDelay = 50000;
  server.sendHeader("Location", "/");
  server.send(302);
}

void handleCurrent() {
  int ma = server.arg("ma").toInt();
  if (ma >= 50 && ma <= 2000) {
    currentMA = ma;
    for (int i = 0; i < 4; i++) {
      if (drivers[i]->version() == 0x21) {
        drivers[i]->rms_current(currentMA);
        // Re-apply IHOLD=0 since rms_current overwrites it
        uint32_t reg = drivers[i]->IHOLD_IRUN();
        reg &= ~(0x1F);       // clear IHOLD bits [4:0]
        reg &= ~(0xF << 16);  // clear IHOLDDELAY bits [19:16]
        reg |= (1 << 16);     // IHOLDDELAY=1
        drivers[i]->IHOLD_IRUN(reg);
      }
    }
    scanResult = doScan();
  }
  server.sendHeader("Location", "/");
  server.send(302);
}

void handleDebug() {
  String r = "UART Debug\n";
  r += "GPIO 16: " + String(digitalRead(16)) + "\n";
  r += "GPIO 17: " + String(digitalRead(17)) + "\n";
  while (Serial2.available()) Serial2.read();
  uint8_t test[] = {0x05, 0x00, 0x00, 0x48};
  Serial2.write(test, 4);
  Serial2.flush();
  delay(100);
  int avail = Serial2.available();
  r += "Sent 4 bytes, got back: " + String(avail) + "\n";
  if (avail > 0) {
    r += "Received: ";
    while (Serial2.available()) {
      char buf[8];
      snprintf(buf, sizeof(buf), "0x%02X ", Serial2.read());
      r += buf;
    }
    r += "\n";
  }
  server.send(200, "text/plain", r);
}

void setup() {
  Serial.begin(115200);
  delay(500);

  // Setup step/dir pins
  for (int i = 0; i < 4; i++) {
    pinMode(drvPins[i].step, OUTPUT);
    pinMode(drvPins[i].dir, OUTPUT);
    digitalWrite(drvPins[i].step, LOW);
    digitalWrite(drvPins[i].dir, LOW);
  }

  Serial.printf("Connecting to: '%s'\n", ssid);
  WiFi.begin(ssid, password);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.printf("WiFi status: %d\n", WiFi.status());
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("WiFi: %s\n", WiFi.localIP().toString().c_str());
    ArduinoOTA.setHostname("esp32-tmc");
    ArduinoOTA.begin();
  } else {
    Serial.printf("WiFi FAILED. Status: %d\n", WiFi.status());
  }

  Serial2.begin(115200, SERIAL_8N1, TMC_RX_PIN, TMC_TX_PIN);
  delay(200);

  scanResult = doScan();

  server.on("/", handleRoot);
  server.on("/scan", handleScan);
  server.on("/setup", handleSetup);
  server.on("/move", handleMove);
  server.on("/stop", handleStop);
  server.on("/speed", handleSpeed);
  server.on("/current", handleCurrent);
  server.on("/debug", handleDebug);
  server.begin();
  Serial.println("Web server: http://" + WiFi.localIP().toString());
}

void loop() {
  ArduinoOTA.handle();
  server.handleClient();

  // Step motors
  for (int i = 0; i < 4; i++) {
    if (motorRunning[i] && stepsRemaining[i] > 0) {
      digitalWrite(drvPins[i].step, HIGH);
      delayMicroseconds(10);
      digitalWrite(drvPins[i].step, LOW);
      delayMicroseconds(stepDelay);
      stepsRemaining[i]--;
      if (stepsRemaining[i] <= 0) {
        motorRunning[i] = false;
      }
    }
  }
}
