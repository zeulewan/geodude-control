#include <SimpleFOC.h>
#include <Wire.h>

BLDCMotor motor = BLDCMotor(7);
BLDCDriver3PWM driver = BLDCDriver3PWM(10, 11, 12, 14);
MagneticSensorI2C sensor = MagneticSensorI2C(AS5600_I2C);

float target_velocity = 0;

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

  // AS5600 encoder
  Wire1.beginTransmission(0x36);
  Wire1.write(0x0C);
  i2c_err_enc = Wire1.endTransmission(false);
  if (i2c_err_enc == 0) {
    Wire1.requestFrom(0x36, 2);
    if (Wire1.available() >= 2) {
      int h = Wire1.read();
      int l = Wire1.read();
      enc_angle = ((h & 0x0F) << 8 | l) / 4096.0 * 360.0;
    }
  }

  // ICM20948 accel + gyro
  Wire1.beginTransmission(0x69);
  Wire1.write(0x2D);
  i2c_err_imu = Wire1.endTransmission(false);
  if (i2c_err_imu == 0) {
    Wire1.requestFrom(0x69, 12);
    if (Wire1.available() >= 12) {
      int16_t ax = (Wire1.read() << 8) | Wire1.read();
      int16_t ay = (Wire1.read() << 8) | Wire1.read();
      int16_t az = (Wire1.read() << 8) | Wire1.read();
      int16_t gx = (Wire1.read() << 8) | Wire1.read();
      int16_t gy = (Wire1.read() << 8) | Wire1.read();
      int16_t gz = (Wire1.read() << 8) | Wire1.read();
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
  Wire1.setClock(100000);

  // Wake ICM20948
  Wire1.beginTransmission(0x69);
  Wire1.write(0x06);
  Wire1.write(0x01);
  Wire1.endTransmission();
  delay(50);
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

  // AS5600 encoder on I2C1
  sensor.init(&Wire1);
  motor.linkSensor(&sensor);

  SimpleFOCDebug::enable(&Serial);

  // Motor driver
  driver.voltage_power_supply = 12;
  driver.voltage_limit = 12;
  driver.init();
  motor.linkDriver(&driver);
  motor.voltage_limit = 1.5;
  motor.velocity_limit = 20;
  motor.controller = MotionControlType::velocity;

  // Velocity PID
  motor.PID_velocity.P = 0.2;
  motor.PID_velocity.I = 10;
  motor.PID_velocity.D = 0;
  motor.PID_velocity.output_ramp = 1000;
  motor.LPF_velocity.Tf = 0.01;

  motor.init();
  motor.initFOC();  // calibrate at startup - motor must be connected
}

void loop() {
  // Motor control
  motor.loopFOC();
  motor.move(target_velocity);

  // Read sensors at 50Hz
  unsigned long now = millis();
  if (now - last_sensor_read >= 20) {
    last_sensor_read = now;
    readSensors();

    // Read VSYS voltage (ADC3/GPIO29, 200K/100K divider = /3)
    analogReadResolution(12);
    int raw = analogRead(A3);
    float vsys = raw * 3.0 * 3.3 / 4095.0;

    // Stream JSON status line
    Serial.print("{\"t\":");
    Serial.print(target_velocity, 2);
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
    } else if (cmd == "D") {
      // Disable motor
      target_velocity = 0;
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
      motor.voltage_limit = cmd.substring(1).toFloat();
    } else if (cmd.startsWith("L")) {
      motor.velocity_limit = cmd.substring(1).toFloat();
    } else if (cmd.startsWith("A")) {
      motor.PID_velocity.output_ramp = cmd.substring(1).toFloat();
    } else if (cmd.startsWith("F")) {
      motor.LPF_velocity.Tf = cmd.substring(1).toFloat();
    }
  }
}
