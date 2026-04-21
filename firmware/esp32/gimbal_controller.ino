#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <TMCStepper.h>

const char* ssid = "groundstation";
const char* password = "Temp1234";

WebServer server(80);
Preferences prefs;

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
bool driverFound[4] = {false, false, false, false};  // Cached from last version check

// Per-motor configuration
int motorCurrentMA[4] = {400, 400, 400, 400};
int motorIholdMA[4] = {0, 0, 0, 0};
bool motorStealthChop[4] = {true, true, true, true};
bool motorInterpolation[4] = {true, true, true, true};
bool motorEnabled[4] = {false, false, false, false};

// Gear ratios and angle conversion
const float MICROSTEPS_PER_REV = 3200.0;  // 200 full steps * 16 microsteps
const float gearRatio[4] = {2.0, 3.25, 1.0, 1.0};  // Yaw, Pitch, Roll, Belt
float stepsPerDeg[4];

// Motor state
bool motorRunning[4] = {false, false, false, false};
bool motorDir[4] = {true, true, true, true};
int stepDelay = 2000;
int motorStepDelayUS[4] = {2000, 2000, 2000, 2000};
int motorRampSteps[4] = {0, 0, 0, 0};
int motorMoveTotalSteps[4] = {0, 0, 0, 0};
int stepsRemaining[4] = {0, 0, 0, 0};
bool setupDone = false; // legacy, kept for /status but not required

int clampRunCurrentMA(int ma) {
  if (ma < 50) return 50;
  if (ma > 2000) return 2000;
  return ma;
}

int clampHoldCurrentMA(int ma) {
  if (ma < 0) return 0;
  if (ma > 2000) return 2000;
  return ma;
}

int clampStepDelayUS(int us) {
  if (us < 100) return 100;
  if (us > 50000) return 50000;
  return us;
}

int clampRampSteps(int steps) {
  if (steps < 0) return 0;
  if (steps > 5000) return 5000;
  return steps;
}

void saveMotorConfig(int d) {
  prefs.putInt(("cur" + String(d)).c_str(), motorCurrentMA[d]);
  prefs.putInt(("ih" + String(d)).c_str(), motorIholdMA[d]);
  prefs.putInt(("spd" + String(d)).c_str(), motorStepDelayUS[d]);
  prefs.putInt(("rmp" + String(d)).c_str(), motorRampSteps[d]);
  prefs.putBool(("stl" + String(d)).c_str(), motorStealthChop[d]);
  prefs.putBool(("int" + String(d)).c_str(), motorInterpolation[d]);
}

void loadMotorConfig() {
  for (int i = 0; i < 4; i++) {
    motorCurrentMA[i] = clampRunCurrentMA(prefs.getInt(("cur" + String(i)).c_str(), motorCurrentMA[i]));
    motorIholdMA[i] = clampHoldCurrentMA(prefs.getInt(("ih" + String(i)).c_str(), motorIholdMA[i]));
    motorStepDelayUS[i] = clampStepDelayUS(prefs.getInt(("spd" + String(i)).c_str(), motorStepDelayUS[i]));
    motorRampSteps[i] = clampRampSteps(prefs.getInt(("rmp" + String(i)).c_str(), motorRampSteps[i]));
    motorStealthChop[i] = prefs.getBool(("stl" + String(i)).c_str(), motorStealthChop[i]);
    motorInterpolation[i] = prefs.getBool(("int" + String(i)).c_str(), motorInterpolation[i]);
  }
}

void applyDriverMode(int d) {
  drivers[d]->microsteps(16);
  drivers[d]->intpol(motorInterpolation[d]);
  drivers[d]->en_spreadCycle(!motorStealthChop[d]);
  drivers[d]->pwm_autoscale(true);
}

void initDrivers() {
  for (int i = 0; i < 4; i++) {
    drivers[i]->begin();
    stepsPerDeg[i] = gearRatio[i] * MICROSTEPS_PER_REV / 360.0;
    driverFound[i] = false;
  }
  delay(100);
  // Aggressively disable all drivers with the saved chopper/interpolation mode.
  for (int i = 0; i < 4; i++) {
    applyDriverMode(i);
    drivers[i]->toff(0);
    motorEnabled[i] = false;
  }
}

// --- JSON API ---

void sendJson(String json) {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);
}

bool sendBusyIfStepping(int targetDriver) {
  // Only block if THIS driver is currently running (others are OK).
  if (targetDriver >= 0 && targetDriver < 4 && motorRunning[targetDriver]) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(409, "application/json", "{\"ok\":false,\"error\":\"driver busy stepping\"}");
    return true;
  }
  return false;
}

bool parseEnabledArg(const String& value) {
  return value.equalsIgnoreCase("1") || value.equalsIgnoreCase("true") || value.equalsIgnoreCase("on");
}

void applyIdleDriverCurrent(int d) {
  if (!motorEnabled[d]) {
    drivers[d]->toff(0);
    return;
  }
  if (motorIholdMA[d] > 0) {
    drivers[d]->toff(4);
    drivers[d]->rms_current(motorIholdMA[d], 1.0f);
  } else {
    drivers[d]->toff(0);
  }
}

void applyRunDriverCurrent(int d) {
  if (!motorEnabled[d]) {
    drivers[d]->toff(0);
    return;
  }
  drivers[d]->toff(4);
  drivers[d]->rms_current(motorCurrentMA[d], 0.0f);
}

int currentStepDelayForDriver(int d) {
  int target = motorStepDelayUS[d];
  int rampSteps = motorRampSteps[d];
  int totalSteps = motorMoveTotalSteps[d];
  if (rampSteps <= 0 || totalSteps <= 0) {
    return target;
  }
  int stepsDone = totalSteps - stepsRemaining[d];
  if (stepsDone <= 0) {
    stepsDone = 0;
  }
  int stepsLeftAfterThis = stepsRemaining[d] - 1;
  if (stepsLeftAfterThis < 0) {
    stepsLeftAfterThis = 0;
  }
  int rampProgress = stepsDone;
  if (stepsLeftAfterThis < rampProgress) {
    rampProgress = stepsLeftAfterThis;
  }
  if (rampProgress >= rampSteps) {
    return target;
  }
  int startDelay = target * 4;
  if (startDelay < target) startDelay = target;
  if (startDelay > 50000) startDelay = 50000;
  long span = (long)startDelay - (long)target;
  long delayNow = startDelay - (span * rampProgress) / rampSteps;
  if (delayNow < target) delayNow = target;
  return (int)delayNow;
}

void handleStatus() {
  bool stepping = anyMotorRunning();
  String r = "{\"drivers_found\":" + String(driversFound) +
    ",\"step_delay\":" + String(stepDelay) +
    ",\"setup_done\":" + String(setupDone ? "true" : "false") +
    ",\"uptime\":" + String(millis() / 1000) +
    ",\"ip\":\"" + WiFi.localIP().toString() + "\"" +
    ",\"drivers\":[";
  for (int i = 0; i < 4; i++) {
    if (i > 0) r += ",";
    // Skip slow UART reads while motors are stepping to avoid pauses
    bool found = driverFound[i];
    uint32_t ds = 0;
    if (!stepping) {
      uint8_t ver = drivers[i]->version();
      found = (ver == 0x21);
      driverFound[i] = found;
      ds = found ? drivers[i]->DRV_STATUS() : 0;
    }
    r += "{\"index\":" + String(i) +
      ",\"name\":\"" + String(drvNames[i]) + "\"" +
      ",\"found\":" + String(found ? "true" : "false") +
      ",\"running\":" + String(motorRunning[i] ? "true" : "false") +
      ",\"enabled\":" + String(motorEnabled[i] ? "true" : "false") +
      ",\"stealthchop\":" + String(motorStealthChop[i] ? "true" : "false") +
      ",\"interpolation\":" + String(motorInterpolation[i] ? "true" : "false") +
      ",\"dir\":\"" + String(motorDir[i] ? "CW" : "CCW") + "\"" +
      ",\"steps_remaining\":" + String(stepsRemaining[i]) +
      ",\"step_delay_us\":" + String(motorStepDelayUS[i]) +
      ",\"ramp_steps\":" + String(motorRampSteps[i]) +
      ",\"current_step_delay_us\":" + String(motorRunning[i] ? currentStepDelayForDriver(i) : motorStepDelayUS[i]) +
      ",\"current_ma\":" + String(motorCurrentMA[i]) +
      ",\"ihold_ma\":" + String(motorIholdMA[i]) +
      ",\"gear_ratio\":" + String(gearRatio[i], 2) +
      ",\"steps_per_deg\":" + String(stepsPerDeg[i], 4);
    if (found && !stepping) {
      r += ",\"microsteps\":" + String(drivers[i]->microsteps()) +
        ",\"actual_stealthchop\":" + String(drivers[i]->en_spreadCycle() ? "false" : "true") +
        ",\"actual_interpolation\":" + String(drivers[i]->intpol() ? "true" : "false") +
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
    bool found = (drivers[i]->version() == 0x21);
    driverFound[i] = found;
    if (found) driversFound++;
  }
  sendJson("{\"ok\":true,\"drivers_found\":" + String(driversFound) + "}");
}

void handleSetup() {
  int configured = 0;
  for (int i = 0; i < 4; i++) {
    if (drivers[i]->version() == 0x21) {
      drivers[i]->toff(4);
      drivers[i]->rms_current(motorCurrentMA[i], 0.0f);
      applyDriverMode(i);
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
  if (!motorEnabled[d]) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"motor not enabled\"}");
    return;
  }
  motorDir[d] = steps > 0;
  digitalWrite(drvPins[d].dir, motorDir[d] ? HIGH : LOW);
  stepsRemaining[d] = abs(steps);
  motorMoveTotalSteps[d] = stepsRemaining[d];

  motorRunning[d] = true;
  applyRunDriverCurrent(d);
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
  if (!motorEnabled[d]) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"motor not enabled\"}");
    return;
  }
  int steps = (int)round(deg * stepsPerDeg[d]);
  motorDir[d] = steps > 0;
  digitalWrite(drvPins[d].dir, motorDir[d] ? HIGH : LOW);
  stepsRemaining[d] = abs(steps);
  motorMoveTotalSteps[d] = stepsRemaining[d];

  motorRunning[d] = true;
  applyRunDriverCurrent(d);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"deg\":" + String(deg, 2) + ",\"steps\":" + String(steps) + "}");
}

void handleEnable() {
  int d = server.arg("d").toInt();
  if (sendBusyIfStepping(d)) return;
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  // Full driver configuration on enable
  motorEnabled[d] = true;
  drivers[d]->toff(4);
  applyDriverMode(d);
  drivers[d]->GSTAT(0x07);
  applyIdleDriverCurrent(d);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"enabled\":true}");
}

void handleDisable() {
  int d = server.arg("d").toInt();
  if (sendBusyIfStepping(d)) return;
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
  if (sendBusyIfStepping(d)) return;
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
  saveMotorConfig(d);
  if (motorEnabled[d]) {
    applyIdleDriverCurrent(d);
  }
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
  saveMotorConfig(d);
  if (motorEnabled[d] && !motorRunning[d]) {
    applyIdleDriverCurrent(d);
  }
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"ihold_ma\":" + String(ma) + "}");
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
  motorMoveTotalSteps[d] = 0;
  applyIdleDriverCurrent(d);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + "}");
}

void handleStopAll() {
  for (int i = 0; i < 4; i++) {
    motorRunning[i] = false;
    stepsRemaining[i] = 0;
    motorMoveTotalSteps[i] = 0;
    applyIdleDriverCurrent(i);
  }
  sendJson("{\"ok\":true}");
}

void handleSpeed() {
  int us = server.arg("us").toInt();
  if (us < 100) us = 100;
  if (us > 50000) us = 50000;
  stepDelay = us;
  for (int i = 0; i < 4; i++) {
    motorStepDelayUS[i] = us;
    saveMotorConfig(i);
  }
  sendJson("{\"ok\":true,\"step_delay\":" + String(stepDelay) + "}");
}

void handleMotorSpeed() {
  int d = server.arg("d").toInt();
  if (sendBusyIfStepping(d)) return;
  int us = server.arg("us").toInt();
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  if (us < 100 || us > 50000) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"range 100-50000\"}");
    return;
  }
  motorStepDelayUS[d] = us;
  saveMotorConfig(d);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"step_delay_us\":" + String(us) + "}");
}

void handleMotorRamp() {
  int d = server.arg("d").toInt();
  if (sendBusyIfStepping(d)) return;
  int steps = server.arg("steps").toInt();
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  if (steps < 0 || steps > 5000) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"range 0-5000\"}");
    return;
  }
  motorRampSteps[d] = steps;
  saveMotorConfig(d);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"ramp_steps\":" + String(steps) + "}");
}

void handleMotorStealthChop() {
  int d = server.arg("d").toInt();
  if (sendBusyIfStepping(d)) return;
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  bool enabled = parseEnabledArg(server.arg("enabled"));
  motorStealthChop[d] = enabled;
  saveMotorConfig(d);
  applyDriverMode(d);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"stealthchop\":" + String(enabled ? "true" : "false") + "}");
}

void handleMotorInterpolation() {
  int d = server.arg("d").toInt();
  if (sendBusyIfStepping(d)) return;
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  bool enabled = parseEnabledArg(server.arg("enabled"));
  motorInterpolation[d] = enabled;
  saveMotorConfig(d);
  applyDriverMode(d);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"interpolation\":" + String(enabled ? "true" : "false") + "}");
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
    saveMotorConfig(i);
    if (drivers[i]->version() == 0x21) {
      drivers[i]->rms_current(ma, 0.0f);
    }
  }
  sendJson("{\"ok\":true,\"current_ma\":" + String(ma) + "}");
}



void onWiFiEvent(WiFiEvent_t event) {
  if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP) {
    // Re-init OTA after (re)connect. ArduinoOTA.begin() is idempotent.
    ArduinoOTA.setHostname("esp32-tmc");
    ArduinoOTA.begin();
  }
}

void handleReboot() {
  sendJson("{\"ok\":true,\"msg\":\"rebooting\"}");
  delay(100);
  ESP.restart();
}

void setup() {
  Serial.begin(115200);
  delay(500);
  prefs.begin("gimbalcfg", false);
  loadMotorConfig();

  for (int i = 0; i < 4; i++) {
    pinMode(drvPins[i].step, OUTPUT);
    pinMode(drvPins[i].dir, OUTPUT);
    digitalWrite(drvPins[i].step, LOW);
    digitalWrite(drvPins[i].dir, LOW);
  }

  WiFi.onEvent(onWiFiEvent);
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

  server.on("/reboot", HTTP_POST, handleReboot);
  server.on("/status", handleStatus);
  server.on("/scan", handleScan);
  server.on("/setup", handleSetup);
  server.on("/move", handleMove);
  server.on("/move_deg", handleMoveDeg);
  server.on("/enable", handleEnable);
  server.on("/disable", handleDisable);
  server.on("/motor_current", handleMotorCurrent);
  server.on("/motor_ihold", handleMotorIhold);
  server.on("/motor_speed", handleMotorSpeed);
  server.on("/motor_ramp", handleMotorRamp);
  server.on("/motor_stealthchop", handleMotorStealthChop);
  server.on("/motor_interpolation", handleMotorInterpolation);
  server.on("/estop", handleEstop);
  server.on("/stop", handleStop);
  server.on("/stop_all", handleStopAll);
  server.on("/speed", handleSpeed);
  server.on("/current", handleCurrent);
  server.begin();
}

// Auto-disable drivers when 24V appears
bool driversInitialized = false;
unsigned long lastDriverCheck = 0;

void checkDriverPower() {
  // Check every 500ms if drivers just appeared (24V turned on)
  if (millis() - lastDriverCheck < 500) return;
  lastDriverCheck = millis();

  bool anyFound = false;
  for (int i = 0; i < 4; i++) {
    if (drivers[i]->version() == 0x21) { anyFound = true; break; }
  }

  if (anyFound && !driversInitialized) {
    // 24V just came on — immediately disable all drivers
    for (int i = 0; i < 4; i++) {
      applyDriverMode(i);
      drivers[i]->toff(0);
      motorEnabled[i] = false;
    }
    driversInitialized = true;
  } else if (!anyFound) {
    driversInitialized = false; // 24V is off, reset for next power-on
  }
}

bool anyMotorRunning() {
  for (int i = 0; i < 4; i++) {
    if (motorRunning[i] && stepsRemaining[i] > 0) return true;
  }
  return false;
}

void loop() {
  // Only handle WiFi/OTA when no motors are stepping — prevents timing jitter
  if (!anyMotorRunning()) {
    ArduinoOTA.handle();
    server.handleClient();
    checkDriverPower();
    return;
  }

  // Step all active motors (one step per motor per loop iteration)
  for (int i = 0; i < 4; i++) {
    if (motorRunning[i] && stepsRemaining[i] > 0) {
      digitalWrite(drvPins[i].step, HIGH);
      delayMicroseconds(10);
      digitalWrite(drvPins[i].step, LOW);
      delayMicroseconds(currentStepDelayForDriver(i));

      stepsRemaining[i]--;
      if (stepsRemaining[i] <= 0) {
        motorRunning[i] = false;
        motorMoveTotalSteps[i] = 0;
        applyIdleDriverCurrent(i);
      }
    }
  }

  // Briefly yield to WiFi every 100 steps so estop can get through
  static int stepCounter = 0;
  if (++stepCounter >= 100) {
    stepCounter = 0;
    server.handleClient();
  }
}
