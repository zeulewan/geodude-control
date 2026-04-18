#include <Arduino.h>
#include <SimpleFOC.h>
#include <HardwareTimer.h>

static const uint8_t PWM_A_PIN = 9;
static const uint8_t PWM_B_PIN = 5;
static const uint8_t PWM_C_PIN = 6;
static const uint8_t EN_PIN = 8;
static const int POLE_PAIRS = 11;
static const int ENC_A_PIN = 2;
static const int ENC_B_PIN = 3;
static const int ENC_PPR = 800;

BLDCMotor motor = BLDCMotor(POLE_PAIRS);
BLDCDriver3PWM driver = BLDCDriver3PWM(PWM_A_PIN, PWM_B_PIN, PWM_C_PIN, EN_PIN);
Encoder encoder = Encoder(ENC_A_PIN, ENC_B_PIN, ENC_PPR);
InlineCurrentSense current_sense = InlineCurrentSense(0.01f, 50.0f, A0, A2);

void doA() { encoder.handleA(); }
void doB() { encoder.handleB(); }

float run_voltage = 3.0f;
float run_target = 3.14f;  // ~30 rpm mechanical target in rad/s
float run_ramp = 0.5f;     // rad/s^2
float run_torque = 1.0f;   // direct Uq volts for torque-voltage test
float run_alpha = 0.0f;    // target wheel acceleration in rpm/s for live alpha mode
float current_target = 0.0f;
bool armed = false;
bool foc_ready = false;
bool current_ready = false;
uint8_t profile_phase = 0;
uint8_t live_mode = 0;  // 0=closed-loop wheel velocity, 1=torque, 2=wheel acceleration, 3=open-loop wheel velocity
volatile bool foc_tick_enabled = false;
volatile float foc_target = 0.0f;
unsigned long last_update_us = 0;
unsigned long hold_start_ms = 0;
unsigned long hold_duration_ms = 5000;
unsigned long last_alpha_us = 0;
float alpha_last_rpm = 0.0f;
float alpha_uq = 0.0f;
float alpha_integral = 0.0f;
float alpha_kp = 0.004f;
float alpha_ki = 0.0008f;
float alpha_ff = 0.0030f;  // Uq volts per rpm/s, rough bench estimate
float alpha_limit = 1200.0f;

struct LogSample { uint32_t t_ms; float target; float rpm; float uq; float ia; float ib; float ic_est; float idc; };
static const uint16_t LOG_CAP = 600;
LogSample log_buf[LOG_CAP];
uint16_t log_count = 0;
unsigned long last_log_ms = 0;

HardwareTimer *foc_timer = nullptr;

void foc_timer_callback() {
  if (!foc_tick_enabled) return;
  motor.loopFOC();
  motor.move(foc_target);
}


void reset_log() {
  log_count = 0;
  last_log_ms = 0;
}

void log_sample_no_serial() {
  unsigned long now = millis();
  if (now - last_log_ms < 20) return;
  last_log_ms = now;
  if (log_count >= LOG_CAP) return;
  LogSample &x = log_buf[log_count++];
  x.t_ms = now;
  x.target = current_target;
  x.rpm = encoder.getVelocity() * 60.0f / (2.0f * PI);
  x.uq = motor.voltage.q;
  if (current_ready) {
    PhaseCurrent_s c = current_sense.getPhaseCurrents();
    x.ia = c.a;
    x.ib = c.b;
    x.ic_est = -(c.a + c.b);
    x.idc = current_sense.getDCCurrent(motor.electrical_angle);
  } else {
    x.ia = 0.0f;
    x.ib = 0.0f;
    x.ic_est = 0.0f;
    x.idc = 0.0f;
  }
}

void dump_log() {
  Serial.println("LOG_BEGIN t_ms,target,enc_rpm,uq,ia,ib,ic_est,idc");
  for (uint16_t i = 0; i < log_count; i++) {
    Serial.print(log_buf[i].t_ms); Serial.print(",");
    Serial.print(log_buf[i].target, 5); Serial.print(",");
    Serial.print(log_buf[i].rpm, 3); Serial.print(",");
    Serial.print(log_buf[i].uq, 4); Serial.print(",");
    Serial.print(log_buf[i].ia, 4); Serial.print(",");
    Serial.print(log_buf[i].ib, 4); Serial.print(",");
    Serial.print(log_buf[i].ic_est, 4); Serial.print(",");
    Serial.println(log_buf[i].idc, 4);
  }
  Serial.println("LOG_END");
}

void print_status(const char* event) {
  encoder.update();
  float rpm = encoder.getVelocity() * 60.0f / (2.0f * PI);
  Serial.print("{\"event\":\""); Serial.print(event);
  Serial.print("\",\"armed\":"); Serial.print(armed ? 1 : 0);
  Serial.print(",\"foc_ready\":"); Serial.print(foc_ready ? 1 : 0);
  Serial.print(",\"phase\":"); Serial.print(profile_phase);
  Serial.print(",\"live_mode\":"); Serial.print(live_mode == 3 ? "\"open_velocity\"" : (live_mode == 2 ? "\"alpha\"" : (live_mode == 1 ? "\"torque\"" : "\"rate\"")));
  Serial.print(",\"target\":"); Serial.print(current_target, 4);
  Serial.print(",\"run_target\":"); Serial.print(run_target, 4);
  Serial.print(",\"run_ramp\":"); Serial.print(run_ramp, 4);
  Serial.print(",\"run_voltage\":"); Serial.print(run_voltage, 3);
  Serial.print(",\"run_torque\":"); Serial.print(run_torque, 3);
  Serial.print(",\"run_alpha\":"); Serial.print(run_alpha, 3);
  Serial.print(",\"enc_deg\":"); Serial.print(encoder.getAngle() * 180.0f / PI, 2);
  Serial.print(",\"enc_rpm\":"); Serial.print(rpm, 2);
  Serial.print(",\"zero_electric_angle\":"); Serial.print(motor.zero_electric_angle, 6);
  Serial.print(",\"sensor_direction\":"); Serial.print(motor.sensor_direction == Direction::CW ? "\"CW\"" : (motor.sensor_direction == Direction::CCW ? "\"CCW\"" : "\"UNKNOWN\""));
  Serial.print(",\"uq\":"); Serial.print(motor.voltage.q, 3);
  Serial.print(",\"alpha_uq\":"); Serial.print(alpha_uq, 3);
  Serial.print(",\"current_ready\":"); Serial.print(current_ready ? 1 : 0);
  Serial.print(",\"pid_p\":"); Serial.print(motor.PID_velocity.P, 5);
  Serial.print(",\"pid_i\":"); Serial.print(motor.PID_velocity.I, 5);
  Serial.print(",\"lpf_tf\":"); Serial.print(motor.LPF_velocity.Tf, 5);
  Serial.println("}");
}

void disable_motor() {
  foc_tick_enabled = false;
  current_target = 0.0f;
  foc_target = 0.0f;
  profile_phase = 0;
  motor.move(0.0f);
  motor.disable();
  armed = false;
}

float ramp_target(float target) {
  unsigned long now_us = micros();
  float dt = (now_us - last_update_us) * 1e-6f;
  last_update_us = now_us;
  if (dt <= 0.0f || dt > 0.1f) dt = 0.001f;
  float step = run_ramp * dt;
  if (current_target < target) {
    current_target += step;
    if (current_target > target) current_target = target;
  } else if (current_target > target) {
    current_target -= step;
    if (current_target < target) current_target = target;
  }
  return step;
}

void update_profile_no_serial() {
  unsigned long now_us = micros();
  float dt = (now_us - last_update_us) * 1e-6f;
  last_update_us = now_us;
  if (dt <= 0.0f || dt > 0.1f) dt = 0.001f;
  float step = run_ramp * dt;
  if (profile_phase == 1) {
    current_target += step;
    if (current_target >= run_target) {
      current_target = run_target;
      hold_start_ms = millis();
      profile_phase = 2;
    }
  } else if (profile_phase == 2) {
    if (millis() - hold_start_ms >= hold_duration_ms) profile_phase = 3;
  } else if (profile_phase == 3) {
    current_target -= step;
    if (current_target <= 0.0f) {
      current_target = 0.0f;
      motor.move(0.0f);
      motor.disable();
      armed = false;
      profile_phase = 4;
      Serial.println("RUN_DONE");
      print_status("done");
    }
  }
}

void run_calibration() {
  current_target = 0.0f;
  profile_phase = 0;
  driver.voltage_limit = run_voltage;
  motor.voltage_limit = run_voltage;
  motor.PID_velocity.limit = run_voltage;
  motor.enable();
  int ok = motor.initFOC();
  motor.disable();
  foc_ready = ok == 1;
  print_status(foc_ready ? "initFOC_ok" : "initFOC_failed");
}

void start_torque_test() {
  if (!foc_ready) {
    Serial.println("ERR run G first");
    return;
  }
  driver.voltage_limit = run_voltage;
  motor.voltage_limit = run_voltage;
  motor.PID_velocity.limit = run_voltage;
  current_target = run_torque;
  reset_log();
  hold_start_ms = millis();
  profile_phase = 5;
  motor.controller = MotionControlType::torque;
  motor.torque_controller = TorqueControlType::voltage;
  foc_target = current_target;
  motor.enable();
  armed = true;
  foc_tick_enabled = true;
}

void start_profile() {
  if (!foc_ready) {
    Serial.println("ERR run G first");
    return;
  }
  driver.voltage_limit = run_voltage;
  motor.voltage_limit = run_voltage;
  motor.PID_velocity.limit = run_voltage;
  current_target = 0.0f;
  reset_log();
  last_update_us = micros();
  hold_start_ms = 0;
  profile_phase = 1;
  foc_target = current_target;
  motor.enable();
  armed = true;
  foc_tick_enabled = true;
}

void start_live_control() {
  if (!foc_ready) {
    Serial.println("ERR run G first");
    return;
  }
  driver.voltage_limit = run_voltage;
  motor.voltage_limit = run_voltage;
  motor.PID_velocity.limit = run_voltage;
  reset_log();
  last_update_us = micros();
  motor.controller = live_mode == 3 ? MotionControlType::velocity_openloop : (live_mode == 0 ? MotionControlType::velocity : MotionControlType::torque);
  motor.torque_controller = TorqueControlType::voltage;
  profile_phase = live_mode == 2 ? 8 : (live_mode == 1 ? 7 : 6);
  alpha_integral = 0.0f;
  alpha_uq = 0.0f;
  alpha_last_rpm = encoder.getVelocity() * 60.0f / (2.0f * PI);
  last_alpha_us = micros();
  foc_target = current_target;
  motor.enable();
  armed = true;
  foc_tick_enabled = true;
}

void setup() {
  pinMode(EN_PIN, OUTPUT);
  digitalWrite(EN_PIN, LOW);
  Serial.begin(115200);
  Serial.setTimeout(5);
  delay(1000);
  Serial.println("BOOT_MIN_CLOSEDLOOP");

  encoder.init();
  encoder.enableInterrupts(doA, doB);

  driver.voltage_power_supply = 24.0f;
  driver.voltage_limit = run_voltage;
  if (!driver.init()) {
    Serial.println("ERR driver.init");
    while (1) delay(1000);
  }

  motor.linkDriver(&driver);
  motor.linkSensor(&encoder);
  current_sense.linkDriver(&driver);
  motor.voltage_limit = run_voltage;
  motor.velocity_limit = 250.0f;
  motor.controller = MotionControlType::velocity;
  motor.torque_controller = TorqueControlType::voltage;
  motor.foc_modulation = FOCModulationType::SinePWM;
  motor.modulation_centered = 1;
  motor.PID_velocity.P = 0.02f;
  motor.PID_velocity.I = 0.10f;
  motor.PID_velocity.D = 0.0f;
  motor.PID_velocity.limit = run_voltage;
  motor.LPF_velocity.Tf = 0.08f;

  motor.init();
  current_ready = current_sense.init() == 1;
  if (current_ready) motor.linkCurrentSense(&current_sense);
  motor.disable();

  foc_timer = new HardwareTimer(TIM7);
  foc_timer->setOverflow(4000, HERTZ_FORMAT);
  foc_timer->attachInterrupt(foc_timer_callback);
  foc_timer->resume();
  print_status("ready_disabled");
}

void process_command(String cmd, bool allow_status) {
  cmd.trim();
  if (!cmd.length()) return;

  if (cmd == "G") {
    run_calibration();
  } else if (cmd == "RUN") {
    motor.controller = MotionControlType::velocity;
    start_profile();
  } else if (cmd == "TU") {
    start_torque_test();
  } else if (cmd == "E") {
    start_live_control();
    if (allow_status) print_status("enabled");
  } else if (cmd == "MR") {
    live_mode = 0;
    motor.controller = MotionControlType::velocity;
    if (allow_status) print_status("rate_mode");
  } else if (cmd == "MA") {
    live_mode = 1;
    motor.controller = MotionControlType::torque;
    motor.torque_controller = TorqueControlType::voltage;
    if (allow_status) print_status("torque_mode");
  } else if (cmd == "MX") {
    live_mode = 2;
    motor.controller = MotionControlType::torque;
    motor.torque_controller = TorqueControlType::voltage;
    if (allow_status) print_status("alpha_mode");
  } else if (cmd == "MO") {
    live_mode = 3;
    motor.controller = MotionControlType::velocity_openloop;
    motor.torque_controller = TorqueControlType::voltage;
    if (allow_status) print_status("open_velocity_mode");
  } else if (cmd == "D") {
    disable_motor();
    if (allow_status) print_status("disabled");
  } else if (cmd.startsWith("V")) {
    run_voltage = constrain(cmd.substring(1).toFloat(), 0.0f, 24.0f);
    driver.voltage_limit = run_voltage;
    motor.voltage_limit = run_voltage;
    motor.PID_velocity.limit = run_voltage;
    if (allow_status) print_status("voltage_set");
  } else if (cmd.startsWith("T")) {
    run_target = constrain(cmd.substring(1).toFloat(), -250.0f, 250.0f);
    if (allow_status) print_status("target_set");
  } else if (cmd.startsWith("R")) {
    run_ramp = constrain(cmd.substring(1).toFloat(), 0.01f, 50.0f);
    if (allow_status) print_status("ramp_set");
  } else if (cmd.startsWith("A")) {
    run_alpha = constrain(cmd.substring(1).toFloat(), -alpha_limit, alpha_limit);
    if (allow_status) print_status("alpha_set");
  } else if (cmd.startsWith("U")) {
    run_torque = constrain(cmd.substring(1).toFloat(), -24.0f, 24.0f);
    if (live_mode == 1 && armed && profile_phase == 7) current_target = run_torque;
    if (allow_status) print_status("torque_set");
  } else if (cmd.startsWith("P")) {
    motor.PID_velocity.P = constrain(cmd.substring(1).toFloat(), 0.0f, 5.0f);
    if (allow_status) print_status("pid_p_set");
  } else if (cmd.startsWith("I")) {
    motor.PID_velocity.I = constrain(cmd.substring(1).toFloat(), 0.0f, 20.0f);
    if (allow_status) print_status("pid_i_set");
  } else if (cmd.startsWith("L")) {
    motor.LPF_velocity.Tf = constrain(cmd.substring(1).toFloat(), 0.001f, 1.0f);
    if (allow_status) print_status("lpf_set");
  } else if (cmd == "DUMP") {
    dump_log();
  } else if (cmd.startsWith("H")) {
    hold_duration_ms = (unsigned long)constrain(cmd.substring(1).toFloat(), 0.5f, 30.0f) * 1000UL;
    if (allow_status) print_status("hold_set");
  } else if (cmd == "S") {
    print_status("status");
  }
}

void loop() {
  if (armed) {
    if (Serial.available()) {
      process_command(Serial.readStringUntil('\n'), false);
    }
    if (profile_phase >= 1 && profile_phase <= 3) update_profile_no_serial();
    log_sample_no_serial();
    if (profile_phase == 5) {
      if (millis() - hold_start_ms >= hold_duration_ms) {
        foc_tick_enabled = false;
        foc_target = 0.0f;
        motor.move(0.0f);
        motor.disable();
        armed = false;
        profile_phase = 4;
        motor.controller = MotionControlType::velocity;
        Serial.println("TORQUE_DONE");
        print_status("torque_done");
      } else {
        foc_target = current_target;
      }
    } else if (profile_phase == 6) {
      ramp_target(run_target);
      foc_target = current_target;
    } else if (profile_phase == 7) {
      current_target = run_torque;
      foc_target = current_target;
    } else if (profile_phase == 8) {
      unsigned long now_us = micros();
      float dt = (now_us - last_alpha_us) * 1e-6f;
      if (dt <= 0.0f || dt > 0.1f) dt = 0.001f;
      last_alpha_us = now_us;
      float rpm = encoder.getVelocity() * 60.0f / (2.0f * PI);
      float alpha = (rpm - alpha_last_rpm) / dt;
      alpha_last_rpm = rpm;
      float err = run_alpha - alpha;
      // Integrate only when the loop is not pinned hard in the same direction.
      if (fabsf(alpha_uq) < run_voltage * 0.98f || alpha_uq * err < 0.0f) {
        alpha_integral += err * dt;
        alpha_integral = constrain(alpha_integral, -5000.0f, 5000.0f);
      }
      float target_uq = alpha_ff * run_alpha + alpha_kp * err + alpha_ki * alpha_integral;
      target_uq = constrain(target_uq, -run_voltage, run_voltage);
      float max_step = 30.0f * dt;
      if (target_uq > alpha_uq + max_step) alpha_uq += max_step;
      else if (target_uq < alpha_uq - max_step) alpha_uq -= max_step;
      else alpha_uq = target_uq;
      current_target = alpha_uq;
      foc_target = current_target;
    } else {
      foc_target = current_target;
    }
    return;
  }

  encoder.update();
  if (!Serial.available()) return;
  process_command(Serial.readStringUntil('\n'), true);
}
