#include <SimpleFOC.h>
#include <Wire.h>

// Motor: TBD pole pairs - using 7 as placeholder
// SimpleFOC Shield V2.0.4 default pins for Nucleo-64:
//   INH_A = D9 (PA8/TIM1_CH1), INH_B = D5 (PB4/TIM3_CH1), INH_C = D6 (PB10?)
//   EN = D8
// These are the SimpleFOC Shield V2 defaults for Arduino UNO layout
BLDCMotor motor = BLDCMotor(7);
BLDCDriver3PWM driver = BLDCDriver3PWM(9, 5, 6, 8);  // INH_A, INH_B, INH_C, EN

// MT6701 encoder in ABZ mode
// A and B need to be on interrupt-capable pins
// On Nucleo F446RE Arduino headers: D2 (PA10), D3 (PB3) have interrupts
Encoder encoder = Encoder(2, 3, 1024);  // A=D2, B=D3, 1024 PPR
void doA() { encoder.handleA(); }
void doB() { encoder.handleB(); }

// IMU (ICM20948) on I2C
float imu_ax = 0, imu_ay = 0, imu_az = 0;
float imu_gx = 0, imu_gy = 0, imu_gz = 0;
int i2c_err_imu = -1;

// Control
float target_velocity = 0;
float target_voltage = 0;
int control_mode = 0;  // 0=velocity, 1=torque
unsigned long last_telemetry = 0;

void readIMU() {
  Wire.beginTransmission(0x69);
  Wire.write(0x2D);
  i2c_err_imu = Wire.endTransmission(false);
  if (i2c_err_imu == 0) {
    Wire.requestFrom(0x69, 12);
    if (Wire.available() >= 12) {
      int16_t ax = (Wire.read() << 8) | Wire.read();
      int16_t ay = (Wire.read() << 8) | Wire.read();
      int16_t az = (Wire.read() << 8) | Wire.read();
      int16_t gx = (Wire.read() << 8) | Wire.read();
      int16_t gy = (Wire.read() << 8) | Wire.read();
      int16_t gz = (Wire.read() << 8) | Wire.read();
      imu_ax = ax / 16384.0;
      imu_ay = ay / 16384.0;
      imu_az = az / 16384.0;
      imu_gx = gx / 131.0;
      imu_gy = gy / 131.0;
      imu_gz = gz / 131.0;
    }
  }
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000);
  delay(500);

  Serial.println("BOOT: Nucleo F446RE + SimpleFOC Shield V2");

  // I2C for IMU
  Wire.begin();
  Wire.setClock(400000);

  // Wake ICM20948
  Wire.beginTransmission(0x69);
  Wire.write(0x06);
  Wire.write(0x01);
  if (Wire.endTransmission() == 0) {
    Serial.println("BOOT: ICM20948 found");
    delay(50);
  } else {
    Serial.println("BOOT: ICM20948 not found");
  }

  // Encoder (ABZ mode)
  encoder.init();
  encoder.enableInterrupts(doA, doB);
  Serial.println("BOOT: Encoder initialized (ABZ mode, 1024 PPR)");

  // Motor driver
  driver.voltage_power_supply = 24;
  driver.voltage_limit = 24;
  driver.init();
  Serial.println("BOOT: Driver initialized");

  motor.linkSensor(&encoder);
  motor.linkDriver(&driver);
  motor.voltage_limit = 2;  // start conservative
  motor.velocity_limit = 100;
  motor.controller = MotionControlType::velocity;

  // Velocity PID defaults
  motor.PID_velocity.P = 0.2;
  motor.PID_velocity.I = 2;
  motor.PID_velocity.D = 0;
  motor.PID_velocity.output_ramp = 1000;
  motor.LPF_velocity.Tf = 0.02;

  motor.init();
  Serial.println("BOOT: Motor initialized");

  // Skip initFOC if no motor connected - just report sensor data
  // motor.initFOC();
  Serial.println("BOOT: initFOC SKIPPED (no motor connected)");
  Serial.println("BOOT: Send 'G' to run initFOC when motor is connected");

  motor.disable();
  Serial.println("BOOT: Motor disabled. Ready.");
}

void loop() {
  // Motor FOC loop (safe even when disabled)
  motor.loopFOC();
  if (control_mode == 1) {
    motor.move(target_voltage);
  } else {
    motor.move(target_velocity);
  }

  // Telemetry at 50Hz
  unsigned long now = millis();
  if (now - last_telemetry >= 20) {
    last_telemetry = now;

    readIMU();
    encoder.update();
    float enc_angle = encoder.getAngle() * 180.0 / PI;
    float shaft_vel = encoder.getVelocity();
    float shaft_rpm = shaft_vel * 60.0 / (2.0 * PI);

    Serial.print("{\"t\":");
    Serial.print(target_velocity, 2);
    Serial.print(",\"vel\":");
    Serial.print(shaft_vel, 2);
    Serial.print(",\"rpm\":");
    Serial.print(shaft_rpm, 1);
    Serial.print(",\"enc\":");
    Serial.print(enc_angle, 1);
    Serial.print(",\"ax\":");
    Serial.print(imu_ax, 2);
    Serial.print(",\"ay\":");
    Serial.print(imu_ay, 2);
    Serial.print(",\"az\":");
    Serial.print(imu_az, 2);
    Serial.print(",\"gx\":");
    Serial.print(imu_gx, 1);
    Serial.print(",\"gy\":");
    Serial.print(imu_gy, 1);
    Serial.print(",\"gz\":");
    Serial.print(imu_gz, 1);
    Serial.print(",\"ii\":");
    Serial.print(i2c_err_imu);
    Serial.print(",\"me\":");
    Serial.print(motor.enabled);
    Serial.print(",\"vl\":");
    Serial.print(motor.voltage_limit, 2);
    Serial.print(",\"sl\":");
    Serial.print(motor.velocity_limit, 1);
    Serial.print(",\"kp\":");
    Serial.print(motor.PID_velocity.P, 3);
    Serial.print(",\"ki\":");
    Serial.print(motor.PID_velocity.I, 2);
    Serial.print(",\"kd\":");
    Serial.print(motor.PID_velocity.D, 3);
    Serial.print(",\"rmp\":");
    Serial.print(motor.PID_velocity.output_ramp, 0);
    Serial.print(",\"lpf\":");
    Serial.print(motor.LPF_velocity.Tf, 3);
    Serial.print(",\"cm\":");
    Serial.print(control_mode);
    Serial.print(",\"tv\":");
    Serial.print(target_voltage, 3);
    Serial.println("}");
  }

  // Serial commands
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.startsWith("T")) {
      target_velocity = cmd.substring(1).toFloat();
    } else if (cmd.startsWith("U")) {
      target_voltage = constrain(cmd.substring(1).toFloat(), -24.0, 24.0);
    } else if (cmd == "M0") {
      control_mode = 0; target_voltage = 0;
      motor.controller = MotionControlType::velocity;
    } else if (cmd == "M1") {
      control_mode = 1; target_velocity = 0;
      motor.controller = MotionControlType::torque;
    } else if (cmd == "G") {
      Serial.println("Running initFOC...");
      motor.initFOC();
      Serial.println("initFOC done");
    } else if (cmd == "D") {
      target_velocity = 0; target_voltage = 0;
      motor.disable();
    } else if (cmd == "E") {
      motor.enable();
    } else if (cmd == "C") {
      motor.initFOC();
      motor.enable();
    } else if (cmd == "R") {
      // Reset - re-init
      motor.init();
    } else if (cmd.startsWith("P")) {
      motor.PID_velocity.P = cmd.substring(1).toFloat();
    } else if (cmd.startsWith("I")) {
      motor.PID_velocity.I = cmd.substring(1).toFloat();
    } else if (cmd.startsWith("W")) {
      motor.PID_velocity.D = cmd.substring(1).toFloat();
    } else if (cmd.startsWith("V")) {
      float v = cmd.substring(1).toFloat();
      motor.voltage_limit = v;
      motor.PID_velocity.limit = v;
    } else if (cmd.startsWith("L")) {
      motor.velocity_limit = cmd.substring(1).toFloat();
    } else if (cmd.startsWith("A")) {
      motor.PID_velocity.output_ramp = cmd.substring(1).toFloat();
    } else if (cmd.startsWith("F")) {
      motor.LPF_velocity.Tf = cmd.substring(1).toFloat();
    }
  }
}
