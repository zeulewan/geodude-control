#include <SimpleFOC.h>
#include <Wire.h>

BLDCMotor motor = BLDCMotor(7);
BLDCDriver3PWM driver = BLDCDriver3PWM(10, 11, 12, 14);
MagneticSensorI2C sensor = MagneticSensorI2C(AS5600_I2C);  // 0x36 on Wire1 (GP2/GP3)

float target_velocity = 0;
float target_voltage = 0;
int control_mode = 0;  // 0=velocity (MACE manual), 1=torque (attitude control)

// DRV8313 control pins
#define PIN_NRT 19  // nRESET (active low, output)
#define PIN_NSP 20  // nSLEEP (active low, output)
#define PIN_NFT 21  // nFAULT (active low, input)

// Sensor cache
float enc_angle = 0;
float imu_ax = 0, imu_ay = 0, imu_az = 0;
float imu_gx = 0, imu_gy = 0, imu_gz = 0;
bool i2c_ok = false;
unsigned long last_sensor_read = 0;
int i2c_err_enc = -1;
int i2c_err_imu = -1;

void initI2C() {
  // Already initialized in setup()
}

void readSensors() {
  if (!i2c_ok) initI2C();

  // AS5600 encoder - read from motor sensor (I2C)
  sensor.update();
  enc_angle = fmod(sensor.getAngle() * 180.0 / PI, 360.0);
  if (enc_angle < 0) enc_angle += 360.0;
  i2c_err_enc = 0;

  // ICM20948 accel + gyro on Wire/I2C0 (GP4/GP5)
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
  // Init I2C FIRST before USB serial
  Wire1.setSDA(2);
  Wire1.setSCL(3);
  Wire1.begin();
  Wire1.setClock(400000);  // 400kHz - testing higher speed for RPM cap

  // IMU on Wire/I2C0 (GP4/GP5)
  Wire.setSDA(4);
  Wire.setSCL(5);
  Wire.begin();
  Wire.setClock(200000);

  // Wake ICM20948 (if connected)
  Wire.beginTransmission(0x69);
  Wire.write(0x06);
  Wire.write(0x01);
  if (Wire.endTransmission() == 0) {
    delay(50);
  }
  i2c_ok = true;

  // DRV8313 control pins
  pinMode(PIN_NFT, INPUT_PULLUP);

  // Wake driver from sleep first
  pinMode(PIN_NSP, OUTPUT);
  digitalWrite(PIN_NSP, HIGH);
  delay(10);

  // Release from reset
  pinMode(PIN_NRT, OUTPUT);
  digitalWrite(PIN_NRT, HIGH);
  delay(50);

  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(115200);
  while (!Serial && millis() < 5000) {
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
    delay(100);
  }
  digitalWrite(LED_BUILTIN, HIGH);

  SimpleFOCDebug::enable(&Serial);
  Serial.println("BOOT: waiting for AS5600...");

  // Wait for AS5600 to be ready on I2C1 before init
  analogReadResolution(12);  // for VSYS ADC
  for (int attempt = 0; attempt < 20; attempt++) {
    Wire1.beginTransmission(0x36);
    int err = Wire1.endTransmission();
    if (err == 0) {
      Serial.print("BOOT: AS5600 found after ");
      Serial.print(attempt);
      Serial.println(" attempts");
      break;
    }
    delay(100);
  }

  // AS5600 encoder on I2C1 (GP2/GP3)
  sensor.init(&Wire1);
  Serial.println("BOOT: sensor init done");
  motor.linkSensor(&sensor);

  // Motor driver
  driver.voltage_power_supply = 12;
  driver.voltage_limit = 12;
  driver.init();
  motor.linkDriver(&driver);
  motor.voltage_limit = 2;
  motor.velocity_limit = 300;
  motor.controller = MotionControlType::velocity;

  // Velocity PID (tuned for I2C encoder - clean signal)
  motor.PID_velocity.P = 0.2;
  motor.PID_velocity.I = 2;
  motor.PID_velocity.D = 0;
  motor.PID_velocity.output_ramp = 1000;
  motor.LPF_velocity.Tf = 0.05;  // heavier filtering for analog encoder noise

  Serial.println("BOOT: motor.init()...");
  motor.init();
  Serial.println("BOOT: motor.initFOC()...");
  motor.initFOC();  // calibrate at startup - motor must be connected
  Serial.println("BOOT: initFOC done");
  motor.PID_velocity.limit = motor.voltage_limit;  // sync PID limit with voltage limit
  motor.disable();  // start disabled - user must explicitly enable
  Serial.println("BOOT: motor disabled (waiting for enable command)");
}

void loop() {
  // Motor control
  motor.loopFOC();
  if (control_mode == 1) {
    motor.move(target_voltage);   // torque mode: voltage applied directly via FOC
  } else {
    motor.move(target_velocity);  // velocity mode: SimpleFOC PID controls
  }

  // Read sensors at 50Hz
  unsigned long now = millis();
  if (now - last_sensor_read >= 20) {
    last_sensor_read = now;
    readSensors();

    // Read VSYS voltage (ADC3/GPIO29, 200K/100K divider = /3)
    int raw = analogRead(A3);
    float vsys = raw * 3.0 * 3.3 / 4095.0;

    // Stream JSON status line
    float shaft_vel = motor.shaft_velocity;  // rad/s (filtered by SimpleFOC)
    float shaft_rpm = shaft_vel * 60.0 / (2.0 * PI);

    Serial.print("{\"t\":");
    Serial.print(target_velocity, 2);
    Serial.print(",\"vel\":");
    Serial.print(shaft_vel, 2);
    Serial.print(",\"rpm\":");
    Serial.print(shaft_rpm, 1);
    Serial.print(",\"vsys\":");
    Serial.print(vsys, 2);
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
    Serial.print(",\"ft\":");
    Serial.print(digitalRead(PIN_NFT));
    Serial.print(",\"sp\":");
    Serial.print(digitalRead(PIN_NSP));
    Serial.print(",\"rt\":");
    Serial.print(digitalRead(PIN_NRT));
    Serial.print(",\"ie\":");
    Serial.print(i2c_err_enc);
    Serial.print(",\"ii\":");
    Serial.print(i2c_err_imu);
    Serial.print(",\"en\":");
    Serial.print(digitalRead(14));
    Serial.print(",\"me\":");
    Serial.print(motor.enabled);
    Serial.print(",\"va\":");
    Serial.print(motor.Ua, 3);
    Serial.print(",\"vb\":");
    Serial.print(motor.Ub, 3);
    Serial.print(",\"vc\":");
    Serial.print(motor.Uc, 3);
    Serial.print(",\"da\":");
    Serial.print(driver.dc_a, 3);
    Serial.print(",\"db\":");
    Serial.print(driver.dc_b, 3);
    Serial.print(",\"dc\":");
    Serial.print(driver.dc_c, 3);
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

  // Read incoming commands (non-blocking)
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.startsWith("T")) {
      if (cmd.length() > 1) {
        target_velocity = cmd.substring(1).toFloat();
      }
    } else if (cmd == "R") {
      // Reset DRV8313 fault
      digitalWrite(PIN_NRT, LOW);
      delay(10);
      digitalWrite(PIN_NRT, HIGH);
      delay(50);
    } else if (cmd == "C") {
      // Calibrate: run initFOC and enable motor
      motor.initFOC();
      motor.enable();
    } else if (cmd == "M0") {
      // Switch to velocity mode (MACE manual)
      control_mode = 0;
      target_voltage = 0;
      motor.controller = MotionControlType::velocity;
    } else if (cmd == "M1") {
      // Switch to torque mode (attitude control)
      control_mode = 1;
      target_velocity = 0;
      motor.controller = MotionControlType::torque;
    } else if (cmd.startsWith("U")) {
      // Direct voltage command (torque mode)
      float v = cmd.substring(1).toFloat();
      target_voltage = constrain(v, -12.0, 12.0);
    } else if (cmd == "D") {
      // Disable motor
      target_velocity = 0;
      target_voltage = 0;
      motor.disable();
    } else if (cmd == "E") {
      // Enable motor (only after calibration)
      motor.enable();
    } else if (cmd.startsWith("P")) {
      motor.PID_velocity.P = cmd.substring(1).toFloat();
    } else if (cmd.startsWith("I")) {
      motor.PID_velocity.I = cmd.substring(1).toFloat();
    } else if (cmd.startsWith("W")) {  // D taken by disable
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
