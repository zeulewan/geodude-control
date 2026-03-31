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

// Per-motor configuration
int motorCurrentMA[4] = {400, 400, 400, 400};
int motorIholdMA[4] = {0, 0, 0, 0};
bool motorEnabled[4] = {false, false, false, false};
int jerkLevel = 5;

// Gear ratios and angle conversion
const float MICROSTEPS_PER_REV = 3200.0;  // 200 full steps * 16 microsteps
const float gearRatio[4] = {2.0, 3.25, 1.0, 1.0};  // Yaw, Pitch, Roll, Belt
float stepsPerDeg[4];

// Motor state
bool motorRunning[4] = {false, false, false, false};
bool motorDir[4] = {true, true, true, true};
int stepDelay = 2000;
int stepsRemaining[4] = {0, 0, 0, 0};
int totalSteps[4] = {0, 0, 0, 0};
bool setupDone = false;
const int RAMP_START_DELAY = 8000;

void initDrivers() {
  for (int i = 0; i < 4; i++) {
    drivers[i]->begin();
    stepsPerDeg[i] = gearRatio[i] * MICROSTEPS_PER_REV / 360.0;
  }
  delay(100);
  // Aggressively disable all drivers: SpreadCycle + toff(0)
  for (int i = 0; i < 4; i++) {
    drivers[i]->en_spreadCycle(true);
    drivers[i]->pwm_autoscale(false);
    drivers[i]->toff(0);
    motorEnabled[i] = false;
  }
}

// --- S-curve ramping ---

float smoothstep(float t) {
  t = constrain(t, 0.0f, 1.0f);
  return t * t * (3.0f - 2.0f * t);
}

int computeDelay(int stepNum, int totalSteps, int targetDelay, int startDelay, int jerk) {
  if (totalSteps <= 1) return targetDelay;
  float progress = (float)stepNum / (float)totalSteps;
  float blend = jerk / 10.0f;
  float accelFrac = 0.25f;
  float vel;
  if (progress < accelFrac) {
    float t = progress / accelFrac;
    vel = (1.0f - blend) * t + blend * smoothstep(t);
  } else if (progress > (1.0f - accelFrac)) {
    float t = (1.0f - progress) / accelFrac;
    vel = (1.0f - blend) * t + blend * smoothstep(t);
  } else {
    vel = 1.0f;
  }
  if (vel < 0.05f) vel = 0.05f;
  return (int)(targetDelay + (startDelay - targetDelay) * (1.0f - vel));
}

// --- JSON API ---

void sendJson(String json) {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);
}

void handleStatus() {
  String r = "{\"drivers_found\":" + String(driversFound) +
    ",\"step_delay\":" + String(stepDelay) +
    ",\"jerk_level\":" + String(jerkLevel) +
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
      ",\"enabled\":" + String(motorEnabled[i] ? "true" : "false") +
      ",\"dir\":\"" + String(motorDir[i] ? "CW" : "CCW") + "\"" +
      ",\"steps_remaining\":" + String(stepsRemaining[i]) +
      ",\"current_ma\":" + String(motorCurrentMA[i]) +
      ",\"ihold_ma\":" + String(motorIholdMA[i]) +
      ",\"gear_ratio\":" + String(gearRatio[i], 2) +
      ",\"steps_per_deg\":" + String(stepsPerDeg[i], 4);
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
      drivers[i]->rms_current(motorCurrentMA[i], 0.0f);
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
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  if (!setupDone) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"run setup first\"}");
    return;
  }
  if (!motorEnabled[d]) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"motor not enabled\"}");
    return;
  }
  motorDir[d] = steps > 0;
  digitalWrite(drvPins[d].dir, motorDir[d] ? HIGH : LOW);
  stepsRemaining[d] = abs(steps);
  totalSteps[d] = abs(steps);
  motorRunning[d] = true;
  drivers[d]->toff(4);
  drivers[d]->rms_current(motorCurrentMA[d], 0.0f);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"steps\":" + String(steps) + "}");
}

void handleMoveDeg() {
  int d = server.arg("d").toInt();
  float deg = server.arg("deg").toFloat();
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  if (!setupDone) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"run setup first\"}");
    return;
  }
  if (!motorEnabled[d]) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"motor not enabled\"}");
    return;
  }
  int steps = (int)round(deg * stepsPerDeg[d]);
  motorDir[d] = steps > 0;
  digitalWrite(drvPins[d].dir, motorDir[d] ? HIGH : LOW);
  stepsRemaining[d] = abs(steps);
  totalSteps[d] = abs(steps);
  motorRunning[d] = true;
  drivers[d]->toff(4);
  drivers[d]->rms_current(motorCurrentMA[d], 0.0f);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"deg\":" + String(deg, 2) + ",\"steps\":" + String(steps) + "}");
}

void handleEnable() {
  int d = server.arg("d").toInt();
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  motorEnabled[d] = true;
  drivers[d]->toff(4);
  drivers[d]->rms_current(motorCurrentMA[d], 0.0f);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"enabled\":true}");
}

void handleDisable() {
  int d = server.arg("d").toInt();
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  motorEnabled[d] = false;
  drivers[d]->toff(0);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"enabled\":false}");
}

void handleMotorCurrent() {
  int d = server.arg("d").toInt();
  int ma = server.arg("ma").toInt();
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  if (ma < 50 || ma > 2000) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"range 50-2000\"}");
    return;
  }
  motorCurrentMA[d] = ma;
  drivers[d]->rms_current(ma, 0.0f);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"current_ma\":" + String(ma) + "}");
}

void handleMotorIhold() {
  int d = server.arg("d").toInt();
  int ma = server.arg("ma").toInt();
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  if (ma < 0 || ma > 2000) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"range 0-2000\"}");
    return;
  }
  motorIholdMA[d] = ma;
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"ihold_ma\":" + String(ma) + "}");
}

void handleJerk() {
  int level = server.arg("level").toInt();
  if (level < 0) level = 0;
  if (level > 10) level = 10;
  jerkLevel = level;
  sendJson("{\"ok\":true,\"jerk_level\":" + String(jerkLevel) + "}");
}

void handleEstop() {
  for (int i = 0; i < 4; i++) {
    motorRunning[i] = false;
    stepsRemaining[i] = 0;
    motorEnabled[i] = false;
    drivers[i]->toff(0);
  }
  sendJson("{\"ok\":true,\"estop\":true}");
}

void handleStop() {
  int d = server.arg("d").toInt();
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  motorRunning[d] = false;
  stepsRemaining[d] = 0;
  if (motorIholdMA[d] == 0) {
    drivers[d]->toff(0);
  }
  sendJson("{\"ok\":true,\"driver\":" + String(d) + "}");
}

void handleStopAll() {
  for (int i = 0; i < 4; i++) {
    motorRunning[i] = false;
    stepsRemaining[i] = 0;
    if (motorIholdMA[i] == 0) {
      drivers[i]->toff(0);
    }
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
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"range 50-2000\"}");
    return;
  }
  for (int i = 0; i < 4; i++) {
    motorCurrentMA[i] = ma;
    if (drivers[i]->version() == 0x21) {
      drivers[i]->rms_current(ma, 0.0f);
    }
  }
  sendJson("{\"ok\":true,\"current_ma\":" + String(ma) + "}");
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
  server.on("/move_deg", handleMoveDeg);
  server.on("/enable", handleEnable);
  server.on("/disable", handleDisable);
  server.on("/motor_current", handleMotorCurrent);
  server.on("/motor_ihold", handleMotorIhold);
  server.on("/jerk", handleJerk);
  server.on("/estop", handleEstop);
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

      int d = computeDelay(totalSteps[i] - stepsRemaining[i], totalSteps[i], stepDelay, RAMP_START_DELAY, jerkLevel);
      delayMicroseconds(d);

      stepsRemaining[i]--;
      if (stepsRemaining[i] <= 0) {
        motorRunning[i] = false;
        if (motorIholdMA[i] > 0) {
          // Hold position with reduced current
          drivers[i]->rms_current(motorIholdMA[i], 1.0f);
        } else {
          drivers[i]->toff(0); // fully disable — zero current
        }
      }
    }
  }
}
