// =====================================================================
//  SMART ACCESS & IRRIGATION CONTROL — ARDUINO UNO Q SKETCH
//  Compatible with Arduino App Lab Bridge system
// =====================================================================

#include <Arduino_RouterBridge.h>
#include <DHT.h>

// ── Pin Configuration ─────────────────────────────────────────────
#define SOLENOID_PIN  2   // Solenoid / Motor
#define RELAY1_PIN    3   // Aux 1 (Light)
#define RELAY2_PIN    4   // Motor / Aux 2
#define RELAY3_PIN    5   // Aux 3
#define DHT_PIN       6   // DHT11 Sensor
#define IR_PIN        7   // IR Motion Sensor (Digital)
#define PUMP_PIN      8   // Relay 4 (Water Pump)
#define MOTOR1_IN1    9   // DC Motor 1 — IN1 (direction pin A)
#define MOTOR1_IN2    10  // DC Motor 1 — IN2 (direction pin B)
#define MOTOR2_IN1    11  // DC Motor 2 — IN1 (direction pin A)
#define MOTOR2_IN2    12  // DC Motor 2 — IN2 (direction pin B)
#define SOIL_PIN      A0  // Soil Moisture Sensor (Analog)
#define GAS_PIN       A1  // Gas Sensor (Analog)
#define CURRENT_PIN   A2  // Current Sensor ACS712 (Analog)
#define BUZZER_PIN    13  // Gas Alarm Buzzer

// ── Sensors & Objects ────────────────────────────────────────────
#define DHT_TYPE DHT11
DHT dht(DHT_PIN, DHT_TYPE);

// ── Globals ───────────────────────────────────────────────────────
unsigned long lastTelemetryMs = 0;
const unsigned long TELEMETRY_INTERVAL = 500; // every 500ms

// ACS712 zero current offset voltage (auto-calibrated on boot)
float offsetVoltage = 2.50;

// DC Motor 1 — non-blocking timer
unsigned long motor1StopMs = 0;
bool motor1Running = false;

// DC Motor 2 — non-blocking timer
unsigned long motor2StopMs = 0;
bool motor2Running = false;

// ── Motor Helpers ─────────────────────────────────────────────────
// Set H-bridge direction: true=FWD (IN1=H, IN2=L), false=REV (IN1=L, IN2=H)
void setMotorDir(int in1, int in2, bool forward) {
  digitalWrite(in1, forward ? HIGH : LOW);
  digitalWrite(in2, forward ? LOW  : HIGH);
}

// Coast-stop motor (both pins LOW — high-impedance / free spin)
void stopMotor(int in1, int in2) {
  digitalWrite(in1, LOW);
  digitalWrite(in2, LOW);
}

// ── Send Telemetry to Python via Bridge ─────────────────────────
void send_telemetry() {
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  int soil = analogRead(SOIL_PIN);
  int gas  = analogRead(GAS_PIN);
  int ir   = digitalRead(IR_PIN);

  //=========================================================
  // ACS712 20A — AC RMS Current Measurement
  //=========================================================
  const float sensitivity = 0.100; // 20A module: 100 mV/A
  double sum = 0;
  // 500 samples × 200 µs ≈ 100 ms  → covers 5 full 50 Hz cycles
  for (int i = 0; i < 500; i++) {
    float v = analogRead(CURRENT_PIN) * (5.0 / 1023.0);
    float c = (v - offsetVoltage) / sensitivity;
    sum += c * c;
    delayMicroseconds(200);
  }
  float amps = sqrt(sum / 500.0);
  if (amps < 0.05) amps = 0.0; // noise floor

  // Serial log
  Serial.print("[TELEMETRY] T:"); Serial.print(t, 1);
  Serial.print(" H:");    Serial.print(h, 1);
  Serial.print(" Soil:"); Serial.print(soil);
  Serial.print(" Gas:");  Serial.print(gas);
  Serial.print(" IR:");   Serial.print(ir);
  Serial.print(" Amps:"); Serial.print(amps, 2);
  Serial.print(" M1:");   Serial.print(motor1Running ? 1 : 0);
  Serial.print(" M2:");   Serial.println(motor2Running ? 1 : 0);

  // Send to main.py via Bridge
  // Format: T:temp,H:hum,S:soil,G:gas,I:ir,C:amps,M1:running,M2:running
  String msg =
    "T:"  + String(t, 1)   +
    ",H:" + String(h, 1)   +
    ",S:" + String(soil)   +
    ",G:" + String(gas)    +
    ",I:" + String(ir)     +
    ",C:" + String(amps, 2)+
    ",M1:"+ String(motor1Running ? 1 : 0) +
    ",M2:"+ String(motor2Running ? 1 : 0);
  Bridge.call("send_telemetry", msg);
}

// ── Receive Commands from Python via Bridge ──────────────────────
// Relay commands (unchanged):  SOL:1  R1:1  R2:0  R3:1  PUMP:1
// Motor commands:
//   M1:FWD:3000  → Motor1 forward  for 3000 ms then auto-stop
//   M1:REV:5000  → Motor1 reverse  for 5000 ms then auto-stop
//   M1:STOP      → Motor1 stop immediately
//   M2:FWD:2000  → Motor2 forward  for 2000 ms then auto-stop
//   M2:REV:4000  → Motor2 reverse  for 4000 ms then auto-stop
//   M2:STOP      → Motor2 stop immediately
void receive_command(String cmd) {
  cmd.trim();
  Serial.print("[COMMAND] Received: ");
  Serial.println(cmd);

  if (cmd.startsWith("SOL:")) {
    digitalWrite(SOLENOID_PIN, cmd.substring(4).toInt() ? HIGH : LOW);
  }
  else if (cmd.startsWith("R1:")) {
    // Active-LOW relay: ON=LOW, OFF=HIGH
    digitalWrite(RELAY1_PIN, cmd.substring(3).toInt() ? LOW : HIGH);
  }
  else if (cmd.startsWith("R2:")) {
    digitalWrite(RELAY2_PIN, cmd.substring(3).toInt() ? LOW : HIGH);
  }
  else if (cmd.startsWith("R3:")) {
    digitalWrite(RELAY3_PIN, cmd.substring(3).toInt() ? LOW : HIGH);
  }
  else if (cmd.startsWith("PUMP:")) {
    digitalWrite(PUMP_PIN, cmd.substring(5).toInt() ? HIGH : LOW);
  }
  else if (cmd.startsWith("BUZ:")) {
    digitalWrite(BUZZER_PIN, cmd.substring(4).toInt() ? HIGH : LOW);
  }
  // ── DC Motor 1 ──────────────────────────────────────────────────
  else if (cmd.startsWith("M1:")) {
    String sub = cmd.substring(3); // e.g. "FWD:3000" or "STOP"
    if (sub == "STOP") {
      stopMotor(MOTOR1_IN1, MOTOR1_IN2);
      motor1Running = false;
      motor1StopMs  = 0;
      Serial.println("[MOTOR1] Stopped.");
    } else {
      int col = sub.indexOf(':');
      if (col > 0) {
        bool fwd = (sub.substring(0, col) == "FWD");
        unsigned long dur = sub.substring(col + 1).toInt();
        setMotorDir(MOTOR1_IN1, MOTOR1_IN2, fwd);
        motor1StopMs  = millis() + dur;
        motor1Running = true;
        Serial.print("[MOTOR1] "); Serial.print(fwd ? "FWD" : "REV");
        Serial.print(" for "); Serial.print(dur); Serial.println(" ms");
      }
    }
  }
  // ── DC Motor 2 ──────────────────────────────────────────────────
  else if (cmd.startsWith("M2:")) {
    String sub = cmd.substring(3);
    if (sub == "STOP") {
      stopMotor(MOTOR2_IN1, MOTOR2_IN2);
      motor2Running = false;
      motor2StopMs  = 0;
      Serial.println("[MOTOR2] Stopped.");
    } else {
      int col = sub.indexOf(':');
      if (col > 0) {
        bool fwd = (sub.substring(0, col) == "FWD");
        unsigned long dur = sub.substring(col + 1).toInt();
        setMotorDir(MOTOR2_IN1, MOTOR2_IN2, fwd);
        motor2StopMs  = millis() + dur;
        motor2Running = true;
        Serial.print("[MOTOR2] "); Serial.print(fwd ? "FWD" : "REV");
        Serial.print(" for "); Serial.print(dur); Serial.println(" ms");
      }
    }
  }
}

// ── Setup ─────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("[SYSTEM] Uno Q MCU booting up...");

  Bridge.begin();
  Serial.println("[SYSTEM] Communication Bridge initialized.");

  // ── Auto-calibrate ACS712 zero-current offset ──────────────────
  Serial.println("[SYSTEM] Calibrating ACS712 (ensure NO load is running)...");
  long offsetSum = 0;
  for (int i = 0; i < 1000; i++) {
    offsetSum += analogRead(CURRENT_PIN);
    delayMicroseconds(500); // total ~0.5 s
  }
  offsetVoltage = (offsetSum / 1000.0) * (5.0 / 1023.0);
  Serial.print("[SYSTEM] ACS712 Offset = ");
  Serial.print(offsetVoltage, 3); Serial.println(" V");

  // ── Output pins ────────────────────────────────────────────────
  pinMode(SOLENOID_PIN, OUTPUT);
  pinMode(RELAY1_PIN,   OUTPUT);
  pinMode(RELAY2_PIN,   OUTPUT);
  pinMode(RELAY3_PIN,   OUTPUT);
  pinMode(PUMP_PIN,     OUTPUT);
  pinMode(MOTOR1_IN1,   OUTPUT);
  pinMode(MOTOR1_IN2,   OUTPUT);
  pinMode(MOTOR2_IN1,   OUTPUT);
  pinMode(MOTOR2_IN2,   OUTPUT);
  pinMode(BUZZER_PIN,   OUTPUT);

  // ── Input pins ─────────────────────────────────────────────────
  pinMode(IR_PIN, INPUT);

  // ── Initial states ─────────────────────────────────────────────
  digitalWrite(SOLENOID_PIN, LOW);  // Active-HIGH solenoid: OFF
  digitalWrite(RELAY1_PIN,  HIGH);  // Active-LOW relay:    OFF
  digitalWrite(RELAY2_PIN,  HIGH);  // Active-LOW relay:    OFF
  digitalWrite(RELAY3_PIN,  HIGH);  // Active-LOW relay:    OFF
  digitalWrite(PUMP_PIN,    LOW);   // Active-HIGH pump:    OFF
  stopMotor(MOTOR1_IN1, MOTOR1_IN2); // DC Motor 1: stopped
  stopMotor(MOTOR2_IN1, MOTOR2_IN2); // DC Motor 2: stopped
  digitalWrite(BUZZER_PIN, LOW);    // Buzzer: OFF

  Serial.println("[SYSTEM] All outputs initialized.");
  dht.begin();
  Serial.println("[SYSTEM] DHT Sensor initialized.");

  Bridge.provide("receive_command", receive_command);
  Serial.println("[SYSTEM] Bridge RPC registered. Ready.");
}

// ── Loop ──────────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // ── Non-blocking motor auto-stop ───────────────────────────────
  if (motor1Running && motor1StopMs > 0 && now >= motor1StopMs) {
    stopMotor(MOTOR1_IN1, MOTOR1_IN2);
    motor1Running = false;
    motor1StopMs  = 0;
    Serial.println("[MOTOR1] Auto-stopped after duration.");
  }
  if (motor2Running && motor2StopMs > 0 && now >= motor2StopMs) {
    stopMotor(MOTOR2_IN1, MOTOR2_IN2);
    motor2Running = false;
    motor2StopMs  = 0;
    Serial.println("[MOTOR2] Auto-stopped after duration.");
  }

  // ── Telemetry ─────────────────────────────────────────────────
  if (now - lastTelemetryMs >= TELEMETRY_INTERVAL) {
    lastTelemetryMs = now;
    send_telemetry();
  }

  delay(10);
}
