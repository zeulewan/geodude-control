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
  {32, 33},  // Driver 0 (Yaw)
  {25, 26},  // Driver 1 (Pitch)
  {22, 23},  // Driver 2 (Roll)
  {19, 18},  // Driver 3 (Belt)
};

const char* drvNames[] = {"Yaw", "Pitch", "Roll", "Belt"};

TMC2209Stepper driver0(&Serial2, R_SENSE, 0x00);
TMC2209Stepper driver1(&Serial2, R_SENSE, 0x01);
TMC2209Stepper driver2(&Serial2, R_SENSE, 0x02);
TMC2209Stepper driver3(&Serial2, R_SENSE, 0x03);
TMC2209Stepper* drivers[] = {&driver0, &driver1, &driver2, &driver3};

int driversFound = 0;

// Motor state
bool motorRunning[4] = {false, false, false, false};
bool motorDir[4] = {true, true, true, true};
int stepDelay = 2000;
int stepsRemaining[4] = {0, 0, 0, 0};
int totalSteps[4] = {0, 0, 0, 0};
int currentDelay[4] = {0, 0, 0, 0};
int accelSteps[4] = {0, 0, 0, 0};
int currentMA = 400;
bool setupDone = false;
const int RAMP_START_DELAY = 8000;
const int RAMP_ACCEL = 50;

void initDrivers() {
  for (int i = 0; i < 4; i++) drivers[i]->begin();
  delay(100);
  for (int i = 0; i < 4; i++) drivers[i]->toff(0);
}

// --- JSON API ---

void sendJson(String json) {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);
}

void handleStatus() {
  String r = "{\"drivers_found\":" + String(driversFound) +
    ",\"step_delay\":" + String(stepDelay) +
    ",\"current_ma\":" + String(currentMA) +
    ",\"setup_done\":" + String(setupDone ? "true" : "false") +
    ",\"uptime\":" + String(millis() / 1000) +
    ",\"ip\":\"" + WiFi.localIP().toString() + "\"" +
    ",\"drivers\":[";
  for (int i = 0; i < 4; i++) {
    if (i > 0) r += ",";
    uint8_t ver = drivers[i]->version();
    bool found = (ver == 0x21);
    uint32_t ds = found ? drivers[i]->DRV_STATUS() : 0;
    r += "{\"index\":" + String(i) +
      ",\"name\":\"" + String(drvNames[i]) + "\"" +
      ",\"found\":" + String(found ? "true" : "false") +
      ",\"running\":" + String(motorRunning[i] ? "true" : "false") +
      ",\"dir\":\"" + String(motorDir[i] ? "CW" : "CCW") + "\"" +
      ",\"steps_remaining\":" + String(stepsRemaining[i]);
    if (found) {
      r += ",\"microsteps\":" + String(drivers[i]->microsteps()) +
        ",\"rms_current\":" + String(drivers[i]->rms_current()) +
        ",\"irun\":" + String(drivers[i]->irun()) +
        ",\"ihold\":" + String(drivers[i]->ihold()) +
        ",\"cs_actual\":" + String((ds >> 16) & 0x1F) +
        ",\"standstill\":" + String((ds >> 31) & 1 ? "true" : "false") +
        ",\"ot\":" + String((ds >> 1) & 1 ? "true" : "false") +
        ",\"otpw\":" + String(ds & 1 ? "true" : "false");
    }
    r += "}";
  }
  r += "]}";
  sendJson(r);
}

void handleScan() {
  driversFound = 0;
  for (int i = 0; i < 4; i++) {
    if (drivers[i]->version() == 0x21) driversFound++;
  }
  sendJson("{\"ok\":true,\"drivers_found\":" + String(driversFound) + "}");
}

void handleSetup() {
  int configured = 0;
  for (int i = 0; i < 4; i++) {
    if (drivers[i]->version() == 0x21) {
      drivers[i]->toff(4);
      drivers[i]->rms_current(currentMA, 0.0f);
      drivers[i]->microsteps(16);
      drivers[i]->en_spreadCycle(true);
      drivers[i]->pwm_autoscale(false);
      drivers[i]->GSTAT(0x07);
      drivers[i]->toff(0);
      configured++;
    }
  }
  setupDone = true;
  driversFound = configured;
  sendJson("{\"ok\":true,\"configured\":" + String(configured) + "}");
}

void handleMove() {
  int d = server.arg("d").toInt();
  int steps = server.arg("steps").toInt();
  if (d < 0 || d >= 4) {
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  if (!setupDone) {
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"run setup first\"}");
    return;
  }
  motorDir[d] = steps > 0;
  digitalWrite(drvPins[d].dir, motorDir[d] ? HIGH : LOW);
  stepsRemaining[d] = abs(steps);
  totalSteps[d] = abs(steps);
  motorRunning[d] = true;
  currentDelay[d] = RAMP_START_DELAY;
  accelSteps[d] = 0;
  drivers[d]->toff(4);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"steps\":" + String(steps) + "}");
}

void handleStop() {
  int d = server.arg("d").toInt();
  if (d < 0 || d >= 4) {
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  motorRunning[d] = false;
  stepsRemaining[d] = 0;
  drivers[d]->toff(0);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + "}");
}

void handleStopAll() {
  for (int i = 0; i < 4; i++) {
    motorRunning[i] = false;
    stepsRemaining[i] = 0;
    drivers[i]->toff(0);
  }
  sendJson("{\"ok\":true}");
}

void handleSpeed() {
  int us = server.arg("us").toInt();
  if (us < 100) us = 100;
  if (us > 50000) us = 50000;
  stepDelay = us;
  sendJson("{\"ok\":true,\"step_delay\":" + String(stepDelay) + "}");
}

void handleCurrent() {
  int ma = server.arg("ma").toInt();
  if (ma < 50 || ma > 2000) {
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"range 50-2000\"}");
    return;
  }
  currentMA = ma;
  for (int i = 0; i < 4; i++) {
    if (drivers[i]->version() == 0x21) {
      drivers[i]->rms_current(currentMA, 0.0f);
    }
  }
  sendJson("{\"ok\":true,\"current_ma\":" + String(currentMA) + "}");
}

void setup() {
  Serial.begin(115200);
  delay(500);

  for (int i = 0; i < 4; i++) {
    pinMode(drvPins[i].step, OUTPUT);
    pinMode(drvPins[i].dir, OUTPUT);
    digitalWrite(drvPins[i].step, LOW);
    digitalWrite(drvPins[i].dir, LOW);
  }

  WiFi.begin(ssid, password);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    ArduinoOTA.setHostname("esp32-tmc");
    ArduinoOTA.begin();
  }

  Serial2.begin(115200, SERIAL_8N1, TMC_RX_PIN, TMC_TX_PIN);
  delay(200);

  initDrivers();

  server.on("/status", handleStatus);
  server.on("/scan", handleScan);
  server.on("/setup", handleSetup);
  server.on("/move", handleMove);
  server.on("/stop", handleStop);
  server.on("/stop_all", handleStopAll);
  server.on("/speed", handleSpeed);
  server.on("/current", handleCurrent);
  server.begin();
}

void loop() {
  ArduinoOTA.handle();
  server.handleClient();

  for (int i = 0; i < 4; i++) {
    if (motorRunning[i] && stepsRemaining[i] > 0) {
      digitalWrite(drvPins[i].step, HIGH);
      delayMicroseconds(10);
      digitalWrite(drvPins[i].step, LOW);
      delayMicroseconds(currentDelay[i]);
      if (stepsRemaining[i] <= accelSteps[i]) {
        currentDelay[i] += RAMP_ACCEL;
        if (currentDelay[i] > RAMP_START_DELAY) currentDelay[i] = RAMP_START_DELAY;
      } else if (currentDelay[i] > stepDelay) {
        currentDelay[i] -= RAMP_ACCEL;
        if (currentDelay[i] < stepDelay) currentDelay[i] = stepDelay;
        accelSteps[i]++;
      }
      stepsRemaining[i]--;
      if (stepsRemaining[i] <= 0) {
        motorRunning[i] = false;
        drivers[i]->toff(0);
      }
    }
  }
}
