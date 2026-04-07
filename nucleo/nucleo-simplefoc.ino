#include <Wire.h>

// MT6701 encoder (ABZ mode) on Shield encoder header
// SimpleFOC Shield V2 routes A->D2, B->D3
#define ENC_A 2
#define ENC_B 3
#define ENC_PPR 1024
volatile long enc_count = 0;

void encA() {
  if (digitalRead(ENC_B)) enc_count--; else enc_count++;
}
void encB() {
  if (digitalRead(ENC_A)) enc_count++; else enc_count--;
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("HELLO FROM NUCLEO");

  // Encoder pins
  pinMode(ENC_A, INPUT_PULLUP);
  pinMode(ENC_B, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(ENC_A), encA, RISING);
  attachInterrupt(digitalPinToInterrupt(ENC_B), encB, RISING);
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

  // Encoder angle and velocity
  static long prev_count = 0;
  static unsigned long prev_time = 0;
  unsigned long now = millis();
  long cnt = enc_count;
  float enc_angle = (cnt % (4L * ENC_PPR)) * 360.0 / (4.0 * ENC_PPR);
  float enc_vel = 0;
  if (prev_time > 0 && now > prev_time) {
    float dt = (now - prev_time) / 1000.0;
    enc_vel = (cnt - prev_count) * 60.0 / (4.0 * ENC_PPR * dt);  // RPM
  }
  prev_count = cnt;
  prev_time = now;

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
  Serial.print(",\"me\":0,\"en\":0,\"ft\":0,\"sp\":0,\"rt\":0");
  Serial.print(",\"vl\":0,\"sl\":0,\"kp\":0,\"ki\":0,\"kd\":0,\"rmp\":0,\"lpf\":0");
  Serial.print(",\"cm\":0,\"tv\":0");
  Serial.println("}");

  delay(20);  // 50Hz
}
