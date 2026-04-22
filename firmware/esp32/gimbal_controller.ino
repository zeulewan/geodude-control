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
bool motorMultistepFilt[4] = {true, true, true, true};
float motorSoftLimitMin[4] = {-360.0f, -360.0f, -360.0f, -50000.0f};
float motorSoftLimitMax[4] = {360.0f, 360.0f, 360.0f, 50000.0f};
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
uint32_t motorNextStepAtUS[4] = {0, 0, 0, 0};
uint32_t motorLastStepAtUS[4] = {0, 0, 0, 0};
uint32_t motorLastStepIntervalUS[4] = {0, 0, 0, 0};
uint32_t motorLastStepLagUS[4] = {0, 0, 0, 0};
int32_t motorPositionSteps[4] = {0, 0, 0, 0};
bool motorPositionTrusted[4] = {false, false, false, false};
uint8_t motorPositionReason[4] = {0, 0, 0, 0};
bool setupDone = false; // legacy, kept for /status but not required

enum PositionReason : uint8_t {
  POSITION_REASON_BOOT = 0,
  POSITION_REASON_SET_ZERO = 1,
  POSITION_REASON_CLEAR = 2,
  POSITION_REASON_DISABLE = 3,
  POSITION_REASON_ESTOP = 4,
  POSITION_REASON_POWER_LOSS = 5
};

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

float smootherStep01(float t) {
  if (t <= 0.0f) return 0.0f;
  if (t >= 1.0f) return 1.0f;
  return t * t * t * (t * (t * 6.0f - 15.0f) + 10.0f);
}

float driverHardLimitMin(int d) {
  switch (d) {
    case 0: return -360.0f;     // Yaw
    case 1: return -360.0f;     // Pitch
    case 2: return -360.0f;     // Roll
    case 3: return -50000.0f;   // Belt steps
    default: return -50000.0f;
  }
}

float driverHardLimitMax(int d) {
  switch (d) {
    case 0: return 360.0f;      // Yaw
    case 1: return 360.0f;      // Pitch
    case 2: return 360.0f;      // Roll
    case 3: return 50000.0f;    // Belt steps
    default: return 50000.0f;
  }
}

float clampSoftLimitValue(int d, float value) {
  float lo = driverHardLimitMin(d);
  float hi = driverHardLimitMax(d);
  if (value < lo) return lo;
  if (value > hi) return hi;
  return value;
}

void saveMotorConfig(int d) {
  prefs.putInt(("cur" + String(d)).c_str(), motorCurrentMA[d]);
  prefs.putInt(("ih" + String(d)).c_str(), motorIholdMA[d]);
  prefs.putInt(("spd" + String(d)).c_str(), motorStepDelayUS[d]);
  prefs.putInt(("rmp" + String(d)).c_str(), motorRampSteps[d]);
  prefs.putBool(("stl" + String(d)).c_str(), motorStealthChop[d]);
  prefs.putBool(("int" + String(d)).c_str(), motorInterpolation[d]);
  prefs.putBool(("msf" + String(d)).c_str(), motorMultistepFilt[d]);
  prefs.putFloat(("lmn" + String(d)).c_str(), motorSoftLimitMin[d]);
  prefs.putFloat(("lmx" + String(d)).c_str(), motorSoftLimitMax[d]);
}

void loadMotorConfig() {
  for (int i = 0; i < 4; i++) {
    motorCurrentMA[i] = clampRunCurrentMA(prefs.getInt(("cur" + String(i)).c_str(), motorCurrentMA[i]));
    motorIholdMA[i] = clampHoldCurrentMA(prefs.getInt(("ih" + String(i)).c_str(), motorIholdMA[i]));
    motorStepDelayUS[i] = clampStepDelayUS(prefs.getInt(("spd" + String(i)).c_str(), motorStepDelayUS[i]));
    motorRampSteps[i] = clampRampSteps(prefs.getInt(("rmp" + String(i)).c_str(), motorRampSteps[i]));
    motorStealthChop[i] = prefs.getBool(("stl" + String(i)).c_str(), motorStealthChop[i]);
    motorInterpolation[i] = prefs.getBool(("int" + String(i)).c_str(), motorInterpolation[i]);
    motorMultistepFilt[i] = prefs.getBool(("msf" + String(i)).c_str(), motorMultistepFilt[i]);
    motorSoftLimitMin[i] = clampSoftLimitValue(i, prefs.getFloat(("lmn" + String(i)).c_str(), motorSoftLimitMin[i]));
    motorSoftLimitMax[i] = clampSoftLimitValue(i, prefs.getFloat(("lmx" + String(i)).c_str(), motorSoftLimitMax[i]));
    if (motorSoftLimitMin[i] > 0.0f) motorSoftLimitMin[i] = 0.0f;
    if (motorSoftLimitMax[i] < 0.0f) motorSoftLimitMax[i] = 0.0f;
    if (motorSoftLimitMin[i] > motorSoftLimitMax[i]) {
      motorSoftLimitMin[i] = driverHardLimitMin(i);
      motorSoftLimitMax[i] = driverHardLimitMax(i);
    }
  }
}

const char* positionReasonName(uint8_t reason) {
  switch (reason) {
    case POSITION_REASON_SET_ZERO: return "set_zero";
    case POSITION_REASON_CLEAR: return "cleared";
    case POSITION_REASON_DISABLE: return "disabled";
    case POSITION_REASON_ESTOP: return "estop";
    case POSITION_REASON_POWER_LOSS: return "power_loss";
    case POSITION_REASON_BOOT:
    default:
      return "boot";
  }
}

void markPositionTrusted(int d, bool trusted, uint8_t reason) {
  motorPositionTrusted[d] = trusted;
  motorPositionReason[d] = reason;
}

bool driverDisplaysWrappedDegrees(int d) {
  return d == 2;  // Roll only
}

bool driverGoZeroUsesShortestPath(int d) {
  return d == 2;  // Roll only
}

bool driverSupportsSoftLimits(int d) {
  return d != 2;  // No software limits on Roll
}

bool driverUsesDegreeUnits(int d) {
  return d >= 0 && d < 3;
}

const char* driverLimitUnits(int d) {
  return driverUsesDegreeUnits(d) ? "deg" : "steps";
}

float driverPositionDisplayValue(int d, int32_t positionSteps) {
  if (driverUsesDegreeUnits(d)) {
    return positionSteps / stepsPerDeg[d];
  }
  return (float)positionSteps;
}

int32_t driverDisplayValueToSteps(int d, float value) {
  if (driverUsesDegreeUnits(d)) {
    return (int32_t)lroundf(value * stepsPerDeg[d]);
  }
  return (int32_t)lroundf(value);
}

int32_t stepsPerRevForDriver(int d) {
  return (int32_t)lroundf(stepsPerDeg[d] * 360.0f);
}

int32_t shortestWrappedDeltaToZero(int d, int32_t positionSteps) {
  int32_t stepsPerRev = stepsPerRevForDriver(d);
  if (stepsPerRev <= 0) return -positionSteps;
  int32_t wrapped = positionSteps % stepsPerRev;
  int32_t halfRev = stepsPerRev / 2;
  if (wrapped > halfRev) wrapped -= stepsPerRev;
  if (wrapped < -halfRev) wrapped += stepsPerRev;
  return -wrapped;
}

bool driverMoveRespectsSoftLimits(int d, int32_t deltaSteps, String &error, int32_t *clampedTargetSteps = nullptr) {
  int32_t targetSteps = motorPositionSteps[d] + deltaSteps;
  if (!driverSupportsSoftLimits(d) || !motorPositionTrusted[d]) {
    return true;  // limits are only meaningful once zero is trusted
  }
  int32_t minSteps = driverDisplayValueToSteps(d, motorSoftLimitMin[d]);
  int32_t maxSteps = driverDisplayValueToSteps(d, motorSoftLimitMax[d]);
  if (targetSteps < minSteps) {
    error = "soft min limit";
    if (clampedTargetSteps) *clampedTargetSteps = minSteps;
    return false;
  }
  if (targetSteps > maxSteps) {
    error = "soft max limit";
    if (clampedTargetSteps) *clampedTargetSteps = maxSteps;
    return false;
  }
  return true;
}

String formatLimitValueForDriver(int d, float value) {
  return driverUsesDegreeUnits(d) ? String(value, 1) : String((int32_t)lroundf(value));
}

String jsonLimitValueForDriver(int d, float value) {
  if (!driverSupportsSoftLimits(d)) return "null";
  return formatLimitValueForDriver(d, value);
}

void applyDriverMode(int d) {
  drivers[d]->microsteps(16);
  drivers[d]->intpol(motorInterpolation[d]);
  drivers[d]->multistep_filt(motorMultistepFilt[d]);
  drivers[d]->en_spreadCycle(!motorStealthChop[d]);
  drivers[d]->pwm_autoscale(true);
}

void startMoveSteps(int d, int32_t steps) {
  motorDir[d] = steps > 0;
  digitalWrite(drvPins[d].dir, motorDir[d] ? HIGH : LOW);
  stepsRemaining[d] = abs((int)steps);
  motorMoveTotalSteps[d] = stepsRemaining[d];
  motorNextStepAtUS[d] = micros();
  clearStepDebug(d);
  motorRunning[d] = stepsRemaining[d] > 0;
  if (motorRunning[d]) {
    applyRunDriverCurrent(d);
  } else {
    applyIdleDriverCurrent(d);
  }
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
  float startHz = 1000000.0f / (float)startDelay;
  float targetHz = 1000000.0f / (float)target;
  float t = (float)rampProgress / (float)rampSteps;
  float eased = smootherStep01(t);
  float hzNow = startHz + (targetHz - startHz) * eased;
  if (hzNow <= 0.0f) return startDelay;
  int delayNow = (int)lroundf(1000000.0f / hzNow);
  if (delayNow < target) delayNow = target;
  if (delayNow > startDelay) delayNow = startDelay;
  return delayNow;
}

void clearStepDebug(int d) {
  motorLastStepAtUS[d] = 0;
  motorLastStepIntervalUS[d] = 0;
  motorLastStepLagUS[d] = 0;
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
      ",\"multistep_filt\":" + String(motorMultistepFilt[i] ? "true" : "false") +
      ",\"dir\":\"" + String(motorDir[i] ? "CW" : "CCW") + "\"" +
      ",\"steps_remaining\":" + String(stepsRemaining[i]) +
      ",\"display_wrap\":" + String(driverDisplaysWrappedDegrees(i) ? "true" : "false") +
      ",\"go_zero_mode\":\"" + String(driverGoZeroUsesShortestPath(i) ? "shortest_path" : "absolute") + "\"" +
      ",\"position_steps\":" + String(motorPositionSteps[i]) +
      ",\"position_deg\":" + String(motorPositionSteps[i] / stepsPerDeg[i], 2) +
      ",\"position_trusted\":" + String(motorPositionTrusted[i] ? "true" : "false") +
      ",\"position_reason\":\"" + String(positionReasonName(motorPositionReason[i])) + "\"" +
      ",\"soft_limit_min\":" + jsonLimitValueForDriver(i, motorSoftLimitMin[i]) +
      ",\"soft_limit_max\":" + jsonLimitValueForDriver(i, motorSoftLimitMax[i]) +
      ",\"hard_limit_min\":" + jsonLimitValueForDriver(i, driverHardLimitMin(i)) +
      ",\"hard_limit_max\":" + jsonLimitValueForDriver(i, driverHardLimitMax(i)) +
      ",\"limit_units\":\"" + String(driverLimitUnits(i)) + "\"" +
      ",\"limits_supported\":" + String(driverSupportsSoftLimits(i) ? "true" : "false") +
      ",\"limits_enforced\":" + String((driverSupportsSoftLimits(i) && motorPositionTrusted[i]) ? "true" : "false") +
      ",\"step_delay_us\":" + String(motorStepDelayUS[i]) +
      ",\"ramp_steps\":" + String(motorRampSteps[i]) +
      ",\"current_step_delay_us\":" + String(motorRunning[i] ? currentStepDelayForDriver(i) : motorStepDelayUS[i]) +
      ",\"target_step_hz\":" + String((motorRunning[i] ? (1000000.0f / currentStepDelayForDriver(i)) : (1000000.0f / motorStepDelayUS[i])), 1) +
      ",\"actual_step_hz\":" + String(motorLastStepIntervalUS[i] > 0 ? (1000000.0f / motorLastStepIntervalUS[i]) : 0.0f, 1) +
      ",\"last_step_interval_us\":" + String(motorLastStepIntervalUS[i]) +
      ",\"last_step_lag_us\":" + String(motorLastStepLagUS[i]) +
      ",\"current_ma\":" + String(motorCurrentMA[i]) +
      ",\"ihold_ma\":" + String(motorIholdMA[i]) +
      ",\"gear_ratio\":" + String(gearRatio[i], 2) +
      ",\"steps_per_deg\":" + String(stepsPerDeg[i], 4);
    if (found && !stepping) {
      r += ",\"microsteps\":" + String(drivers[i]->microsteps()) +
        ",\"actual_stealthchop\":" + String(drivers[i]->en_spreadCycle() ? "false" : "true") +
        ",\"actual_interpolation\":" + String(drivers[i]->intpol() ? "true" : "false") +
        ",\"actual_multistep_filt\":" + String(drivers[i]->multistep_filt() ? "true" : "false") +
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
  int32_t steps = server.arg("steps").toInt();
  String limitError;
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
  if (!driverMoveRespectsSoftLimits(d, steps, limitError)) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(409, "application/json", "{\"ok\":false,\"error\":\"" + limitError + "\"}");
    return;
  }
  startMoveSteps(d, steps);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"steps\":" + String(steps) + "}");
}

void handleMoveDeg() {
  int d = server.arg("d").toInt();
  float deg = server.arg("deg").toFloat();
  String limitError;
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
  int32_t steps = (int32_t)round(deg * stepsPerDeg[d]);
  if (!driverMoveRespectsSoftLimits(d, steps, limitError)) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(409, "application/json", "{\"ok\":false,\"error\":\"" + limitError + "\"}");
    return;
  }
  startMoveSteps(d, steps);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"deg\":" + String(deg, 2) + ",\"steps\":" + String(steps) + "}");
}

void handleSetZero() {
  int d = server.arg("d").toInt();
  if (sendBusyIfStepping(d)) return;
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  motorPositionSteps[d] = 0;
  markPositionTrusted(d, true, POSITION_REASON_SET_ZERO);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"position_steps\":0,\"position_deg\":0.00,\"position_trusted\":true}");
}

void handleClearZero() {
  int d = server.arg("d").toInt();
  if (sendBusyIfStepping(d)) return;
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  markPositionTrusted(d, false, POSITION_REASON_CLEAR);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"position_trusted\":false}");
}

void handleGoZero() {
  int d = server.arg("d").toInt();
  String limitError;
  if (sendBusyIfStepping(d)) return;
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
  if (!motorPositionTrusted[d]) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(409, "application/json", "{\"ok\":false,\"error\":\"position untrusted\"}");
    return;
  }
  int32_t steps = driverGoZeroUsesShortestPath(d) ? shortestWrappedDeltaToZero(d, motorPositionSteps[d]) : -motorPositionSteps[d];
  if (!driverMoveRespectsSoftLimits(d, steps, limitError)) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(409, "application/json", "{\"ok\":false,\"error\":\"" + limitError + "\"}");
    return;
  }
  startMoveSteps(d, steps);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"steps\":" + String(steps) + ",\"target\":\"zero\",\"mode\":\"" + String(driverGoZeroUsesShortestPath(d) ? "shortest_path" : "absolute") + "\"}");
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
  motorRunning[d] = false;
  stepsRemaining[d] = 0;
  motorMoveTotalSteps[d] = 0;
  motorNextStepAtUS[d] = 0;
  clearStepDebug(d);
  markPositionTrusted(d, false, POSITION_REASON_DISABLE);
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

void handleMotorLimits() {
  int d = server.arg("d").toInt();
  if (sendBusyIfStepping(d)) return;
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  if (!driverSupportsSoftLimits(d)) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"limits unsupported for this axis\"}");
    return;
  }
  if (!server.hasArg("min") || !server.hasArg("max") || server.arg("min").length() == 0 || server.arg("max").length() == 0) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"min and max required\"}");
    return;
  }

  float minValue = server.arg("min").toFloat();
  float maxValue = server.arg("max").toFloat();
  float hardMin = driverHardLimitMin(d);
  float hardMax = driverHardLimitMax(d);

  if (!driverUsesDegreeUnits(d)) {
    minValue = lroundf(minValue);
    maxValue = lroundf(maxValue);
  }
  if (minValue < hardMin || minValue > hardMax || maxValue < hardMin || maxValue > hardMax) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"outside hard range\"}");
    return;
  }
  if (minValue > 0.0f || maxValue < 0.0f || minValue > maxValue) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"require min <= 0 <= max\"}");
    return;
  }

  motorSoftLimitMin[d] = minValue;
  motorSoftLimitMax[d] = maxValue;
  saveMotorConfig(d);
  sendJson(
    "{\"ok\":true,\"driver\":" + String(d) +
    ",\"soft_limit_min\":" + formatLimitValueForDriver(d, motorSoftLimitMin[d]) +
    ",\"soft_limit_max\":" + formatLimitValueForDriver(d, motorSoftLimitMax[d]) +
    ",\"hard_limit_min\":" + formatLimitValueForDriver(d, hardMin) +
    ",\"hard_limit_max\":" + formatLimitValueForDriver(d, hardMax) +
    ",\"limit_units\":\"" + String(driverLimitUnits(d)) + "\"}"
  );
}


void handleEstop() {
  for (int i = 0; i < 4; i++) {
    motorRunning[i] = false;
    stepsRemaining[i] = 0;
    motorEnabled[i] = false;
    motorMoveTotalSteps[i] = 0;
    motorNextStepAtUS[i] = 0;
    clearStepDebug(i);
    markPositionTrusted(i, false, POSITION_REASON_ESTOP);
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
  motorNextStepAtUS[d] = 0;
  clearStepDebug(d);
  applyIdleDriverCurrent(d);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + "}");
}

void handleStopAll() {
  for (int i = 0; i < 4; i++) {
    motorRunning[i] = false;
    stepsRemaining[i] = 0;
    motorMoveTotalSteps[i] = 0;
    motorNextStepAtUS[i] = 0;
    clearStepDebug(i);
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

void handleMotorMultistepFilt() {
  int d = server.arg("d").toInt();
  if (sendBusyIfStepping(d)) return;
  if (d < 0 || d >= 4) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid driver\"}");
    return;
  }
  bool enabled = parseEnabledArg(server.arg("enabled"));
  motorMultistepFilt[d] = enabled;
  saveMotorConfig(d);
  applyDriverMode(d);
  sendJson("{\"ok\":true,\"driver\":" + String(d) + ",\"multistep_filt\":" + String(enabled ? "true" : "false") + "}");
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
  server.on("/set_zero", handleSetZero);
  server.on("/clear_zero", handleClearZero);
  server.on("/go_zero", handleGoZero);
  server.on("/enable", handleEnable);
  server.on("/disable", handleDisable);
  server.on("/motor_current", handleMotorCurrent);
  server.on("/motor_ihold", handleMotorIhold);
  server.on("/motor_limits", handleMotorLimits);
  server.on("/motor_speed", handleMotorSpeed);
  server.on("/motor_ramp", handleMotorRamp);
  server.on("/motor_stealthchop", handleMotorStealthChop);
  server.on("/motor_interpolation", handleMotorInterpolation);
  server.on("/motor_multistep_filt", handleMotorMultistepFilt);
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
    for (int i = 0; i < 4; i++) {
      motorEnabled[i] = false;
      markPositionTrusted(i, false, POSITION_REASON_POWER_LOSS);
    }
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
  if (!anyMotorRunning()) {
    ArduinoOTA.handle();
    server.handleClient();
    checkDriverPower();
    return;
  }

  uint32_t now = micros();
  bool stepped = false;
  uint32_t nextDue = now + 1000000UL;
  static uint32_t steppedSinceService = 0;

  // Step any motor whose own schedule says it's due. Each axis keeps its own cadence.
  for (int i = 0; i < 4; i++) {
    if (!motorRunning[i] || stepsRemaining[i] <= 0) continue;

    uint32_t dueAt = motorNextStepAtUS[i];
    if ((int32_t)(now - dueAt) >= 0) {
      int intervalUS = currentStepDelayForDriver(i);
      uint32_t lagUS = (uint32_t)((int32_t)(now - dueAt) > 0 ? (now - dueAt) : 0);
      digitalWrite(drvPins[i].step, HIGH);
      delayMicroseconds(10);
      digitalWrite(drvPins[i].step, LOW);
      uint32_t pulseDone = micros();
      if (motorLastStepAtUS[i] != 0) {
        motorLastStepIntervalUS[i] = pulseDone - motorLastStepAtUS[i];
      }
      motorLastStepAtUS[i] = pulseDone;
      motorLastStepLagUS[i] = lagUS;
      uint32_t scheduledNext = dueAt + (uint32_t)intervalUS;
      uint32_t minNext = pulseDone + 4;
      if ((int32_t)(scheduledNext - minNext) < 0) {
        scheduledNext = minNext;
      }
      motorNextStepAtUS[i] = scheduledNext;
      motorPositionSteps[i] += motorDir[i] ? 1 : -1;
      stepsRemaining[i]--;
      stepped = true;
      steppedSinceService++;
      if (stepsRemaining[i] <= 0) {
        motorRunning[i] = false;
        motorMoveTotalSteps[i] = 0;
        motorNextStepAtUS[i] = 0;
        applyIdleDriverCurrent(i);
      }
    }

    if (motorRunning[i] && stepsRemaining[i] > 0) {
      if ((int32_t)(motorNextStepAtUS[i] - nextDue) < 0) {
        nextDue = motorNextStepAtUS[i];
      }
    }
  }

  // Keep control responsive, but don't inject a 500 Hz wobble into the step train.
  if (steppedSinceService >= 100) {
    steppedSinceService = 0;
    server.handleClient();
  }

  if (!stepped) {
    uint32_t waitUS = 0;
    uint32_t afterLoop = micros();
    if ((int32_t)(nextDue - afterLoop) > 0) {
      waitUS = nextDue - afterLoop;
    }
    if (waitUS > 10) {
      delayMicroseconds(waitUS - 5);
    }
  }
}
