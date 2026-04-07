#include <SimpleFOC.h>
#include <Wire.h>

// SimpleFOC Shield V2 pins for UNO layout
BLDCMotor motor = BLDCMotor(7);  // pole pairs TBD
BLDCDriver3PWM driver = BLDCDriver3PWM(9, 5, 6, 8);
bool mtr_ready = false;

// MT6701 encoder (ABZ mode) on Shield encoder header
#define ENC_A 2
#define ENC_B 3
#define ENC_PPR 400
volatile long enc_count = 0;
Encoder foc_encoder = Encoder(ENC_A, ENC_B, ENC_PPR);

void encA() { foc_encoder.handleA(); }
void encB() { foc_encoder.handleB(); }

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("HELLO FROM NUCLEO");

  // Encoder
  foc_encoder.init();
  foc_encoder.enableInterrupts(encA, encB);
  Serial.println("ENCODER INIT DONE (D2/D3 ABZ)");

  Wire.begin();
  Wire.setClock(400000);

  // Wake ICM20948
  Wire.beginTransmission(0x69);
  Wire.write(0x06);
  Wire.write(0x01);
  Wire.endTransmission();
  delay(50);
  Wire.beginTransmission(0x69);
  Wire.write(0x07);
  Wire.write(0x00);
  Wire.endTransmission();
  delay(10);

  Serial.println("IMU INIT DONE");

  // Motor init - each step with debug
  Serial.println("MOTOR: driver.voltage_power_supply...");
  Serial.flush();
  driver.voltage_power_supply = 24;
  driver.voltage_limit = 24;
  Serial.println("MOTOR: driver.init()...");
  Serial.flush();
  driver.init();
  Serial.println("MOTOR: driver.init() DONE");
  Serial.flush();

  Serial.println("MOTOR: linking sensor and driver...");
  Serial.flush();
  motor.linkSensor(&foc_encoder);
  motor.linkDriver(&driver);
  motor.voltage_limit = 2;
  motor.velocity_limit = 100;
  motor.controller = MotionControlType::torque;
  Serial.println("MOTOR: motor.init()...");
  Serial.flush();
  motor.init();
  Serial.println("MOTOR: motor.init() DONE");
  Serial.flush();

  motor.disable();
  mtr_ready = true;
  Serial.println("MOTOR: ready (disabled). Send E to enable, G for initFOC.");
}

void loop() {
  // Read IMU
  Wire.beginTransmission(0x69);
  Wire.write(0x2D);
  int err = Wire.endTransmission(false);

  float ax=0,ay=0,az=0,gx=0,gy=0,gz=0;
  if (err == 0) {
    Wire.requestFrom(0x69, 12);
    if (Wire.available() >= 12) {
      int16_t rax = (Wire.read()<<8)|Wire.read();
      int16_t ray = (Wire.read()<<8)|Wire.read();
      int16_t raz = (Wire.read()<<8)|Wire.read();
      int16_t rgx = (Wire.read()<<8)|Wire.read();
      int16_t rgy = (Wire.read()<<8)|Wire.read();
      int16_t rgz = (Wire.read()<<8)|Wire.read();
      ax=rax/16384.0; ay=ray/16384.0; az=raz/16384.0;
      gx=rgx/131.0; gy=rgy/131.0; gz=rgz/131.0;
    }
  }

  // Encoder angle and velocity via SimpleFOC
  foc_encoder.update();
  float enc_angle = foc_encoder.getAngle() * 180.0 / PI;
  float enc_vel = foc_encoder.getVelocity() * 60.0 / (2.0 * PI);  // RPM

  // Full JSON telemetry
  Serial.print("{\"t\":0,\"vel\":0,\"rpm\":");
  Serial.print(enc_vel, 1);
  Serial.print(",\"enc\":");
  Serial.print(enc_angle, 1);
  Serial.print(",\"ax\":");
  Serial.print(ax, 3);
  Serial.print(",\"ay\":");
  Serial.print(ay, 3);
  Serial.print(",\"az\":");
  Serial.print(az, 3);
  Serial.print(",\"gx\":");
  Serial.print(gx, 1);
  Serial.print(",\"gy\":");
  Serial.print(gy, 1);
  Serial.print(",\"gz\":");
  Serial.print(gz, 1);
  Serial.print(",\"ii\":");
  Serial.print(err);
  Serial.print(",\"me\":");
  Serial.print(mtr_ready ? motor.enabled : 0);
  Serial.print(",\"en\":0,\"ft\":0,\"sp\":0,\"rt\":0");
  Serial.print(",\"vl\":");
  Serial.print(mtr_ready ? motor.voltage_limit : 0, 1);
  Serial.print(",\"sl\":0,\"kp\":0,\"ki\":0,\"kd\":0,\"rmp\":0,\"lpf\":0");
  Serial.print(",\"cm\":0,\"tv\":0");
  Serial.println("}");

  // Serial commands
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "E" && mtr_ready) {
      motor.enable();
      Serial.println("Motor enabled");
    } else if (cmd == "D" && mtr_ready) {
      motor.disable();
      Serial.println("Motor disabled");
    } else if (cmd == "G" && mtr_ready) {
      // initFOC needs encoder linked
      Serial.println("Running initFOC...");
      motor.initFOC();
      motor.disable();
      Serial.println("initFOC done. Motor disabled.");
    } else if (cmd.startsWith("U") && mtr_ready) {
      float v = cmd.substring(1).toFloat();
      v = constrain(v, -24.0, 24.0);
      motor.move(v);
      Serial.print("Voltage: "); Serial.println(v);
    } else if (cmd.startsWith("V") && mtr_ready) {
      motor.voltage_limit = cmd.substring(1).toFloat();
      Serial.print("VL: "); Serial.println(motor.voltage_limit);
    }
  }

  // Run FOC if motor enabled
  if (mtr_ready && motor.enabled) {
    motor.loopFOC();
  }

  delay(20);  // 50Hz
}
