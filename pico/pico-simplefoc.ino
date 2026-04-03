#include <SimpleFOC.h>
#include <Wire.h>

BLDCMotor motor = BLDCMotor(7);
BLDCDriver3PWM driver = BLDCDriver3PWM(10, 11, 12, 14);

float target_velocity = 0;

// Sensor cache
float enc_angle = 0;
float imu_ax = 0, imu_ay = 0, imu_az = 0;
float imu_gx = 0, imu_gy = 0, imu_gz = 0;
bool i2c_ok = false;
unsigned long last_sensor_read = 0;

void initI2C() {
  if (!i2c_ok) {
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
  }
}

void readSensors() {
  if (!i2c_ok) initI2C();

  // AS5600 encoder
  Wire1.beginTransmission(0x36);
  Wire1.write(0x0C);
  if (Wire1.endTransmission(false) == 0) {
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
  if (Wire1.endTransmission(false) == 0) {
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
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(115200);
  while (!Serial && millis() < 5000) {
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
    delay(100);
  }
  digitalWrite(LED_BUILTIN, HIGH);

  // Motor driver
  driver.voltage_power_supply = 12;
  driver.voltage_limit = 6;
  driver.init();

  motor.linkDriver(&driver);
  motor.voltage_limit = 6;
  motor.velocity_limit = 20;
  motor.controller = MotionControlType::velocity_openloop;
  motor.init();
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

    // Stream JSON status line
    Serial.print("{\"t\":");
    Serial.print(target_velocity, 2);
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
    }
  }
}
