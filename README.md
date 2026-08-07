# Smart Access Control 

<div align="center">

![Arduino](https://img.shields.io/badge/Arduino-UNO%20Q-00979D?style=for-the-badge&logo=arduino&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Firebase](https://img.shields.io/badge/Firebase-Realtime%20DB-FFCA28?style=for-the-badge&logo=firebase&logoColor=black)
![JavaScript](https://img.shields.io/badge/JavaScript-face--api.js-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black)

**Built for Arduino Physical AI Challenge India 2026 — Robu.in × Arduino**

🌐 **Live Demo:** https://smart-automation-a7f81.web.app/

</div>

---

## 📌 What This Project Does

A single, unified IoT platform that handles **home security**, **appliance automation**, **smart irrigation**, and **gas safety** — all controlled from one beautiful web dashboard on your phone or laptop, powered by the **Arduino UNO Q**.

---

## ✨ Features

### 🔐 AI Face Recognition Door Lock
- Detects and recognises faces in real-time using `face-api.js` (SSD MobileNet V1 + FaceNet 128D) running fully in the browser
- Automatically unlocks the solenoid door lock when an authorised face is detected
- Auto-relocks after a configurable duration (default: 5 seconds)
- Registered faces are stored in Firebase — persists across sessions

### 🎙️ Voice Control & Macros
- Control any device by voice using the Web Speech API
- Create custom macro phrases (e.g., say *"turn off"* → Light OFF + Fan OFF + TV OFF + Pump OFF simultaneously)
- Loop Mode for hands-free continuous listening

### 📊 Live Environment Monitoring
- **Temperature & Humidity** (DHT11)
- **Soil Moisture** — raw ADC value (0–1023)
- **Gas Level** — raw ADC value (0–1023)
- **IR Motion Status** — DETECTED / CLEAR
- **AC Current** (ACS712 20A, True RMS) and **Power in Watts**
- **Daily & Monthly Energy Consumption** in kWh (saved to Firebase on rollover)

### 💡 Smart Device Control (Light, Fan, TV, Water Pump)
Each device supports:
- **Manual toggle** from the dashboard
- **Custom device name**
- **Custom voice keywords** (ON and OFF phrases)
- **Countdown Timer** — e.g., "Turn ON for 2 hours 30 minutes then auto-OFF"
- **Time-of-Day Alarm** — e.g., "Turn OFF at 11:00 PM, run for 30 minutes"
- **Auto Restart** — when device turns OFF via alarm, it automatically turns back ON after the set duration

### 💧 Smart Irrigation (Water Pump)
- **Soil Auto-Watering**: reads raw soil ADC; if soil is dry (raw > threshold), pump turns ON automatically; turns OFF when soil is wet enough
- Configurable raw ADC threshold
- Fully overridable manually at any time

### ☁️ Gas Safety System (DC Motor Gas Valve)
- Reads MQ-2/MQ-5 gas sensor raw value continuously
- If gas exceeds set threshold → **Buzzer rings** + **Gas valve motor closes** immediately
- When gas returns to safe level → Buzzer silences automatically
- Works only when **Auto Gas Safety** is enabled (can be toggled off when not needed)

### 🔄 DC Motor Valve Control (Gas Valve & Water Valve)
- Two independent DC motors (H-Bridge L298N) on pins 9/10 and 11/12
- Configurable **ON Direction** (FWD/REV) and **ON Duration** (seconds)
- Configurable **OFF Direction** (FWD/REV) and **OFF Duration** (seconds)
- Non-blocking auto-stop on the Arduino — motor stops exactly after the set time

### 🚨 IR Motion Auto-Lighting
- IR sensor triggers Relay 1 (light) when motion is detected
- Configurable auto-OFF duration after motion clears

### 📅 Scheduler & Logs
- All schedule events fire based on **Indian Standard Time (IST)**
- Stale schedules (missed by > 60 seconds) are automatically discarded
- Live scrolling system log with IST timestamps

---

## 🔌 Pin Mapping

| Pin | Component | Logic |
|---|---|---|
| D2 | Solenoid Lock | Active-HIGH |
| D3 | Relay 1 — Light | Active-LOW |
| D4 | Relay 2 — Fan/TV | Active-LOW |
| D5 | Relay 3 — Aux | Active-LOW |
| D6 | DHT11 Sensor | Data |
| D7 | IR Motion Sensor | Digital IN |
| D8 | Water Pump Relay | Active-HIGH |
| D9, D10 | DC Motor 1 (Gas Valve) IN1/IN2 | H-Bridge |
| D11, D12 | DC Motor 2 (Water Valve) IN1/IN2 | H-Bridge |
| D13 | Buzzer | Active-HIGH |
| A0 | Soil Moisture Sensor | Analog IN (0–1023) |
| A1 | Gas Sensor (MQ-2) | Analog IN (0–1023) |
| A2 | ACS712 20A Current Sensor | Analog IN (AC RMS) |

---

## 🏗️ System Architecture

```
SENSORS (DHT11, Soil, Gas, IR, ACS712)
    ↓  every 500ms
ARDUINO UNO Q  ←→  App Lab Bridge (USB/Serial)
    ↓
PYTHON BACKEND (main.py)
  → Runs automations
  → Syncs to Firebase
    ↓
FIREBASE REALTIME DATABASE
    ↓  real-time WebSocket
WEB DASHBOARD (WebUI.html / Chrome)
  → User controls devices
  → face-api.js runs AI face recognition
  → Web Speech API handles voice commands
```

---

## 📁 File Structure

```
├── sketch.ino      # Arduino UNO Q firmware (sensors, relays, motors, buzzer)
├── main.py         # Python App Lab backend (automations, Firebase sync, scheduling)
├── WebUI.html      # Web dashboard (face recognition, voice, timers, alarms, energy)
└── index.html      # Firebase Hosting entry point
```

---

## 🚀 How to Run

### 1. Arduino
1. Open `sketch.ino` in the Arduino IDE
2. Select board: **Arduino UNO Q**
3. Upload the sketch

### 2. Python Backend
```bash
# Install dependencies
pip install firebase-admin

# Add your Firebase credentials file as:
# firebase-credentials.json

# Run via Arduino App Lab
# (main.py is loaded automatically by the App Lab Bridge)
```

### 3. Web Dashboard
- Open `https://smart-automation-a7f81.web.app/` in Chrome, OR
- Open `WebUI.html` directly in Chrome


---

## 🧠 AI Model Details

| Field | Detail |
|---|---|
| Library | face-api.js (`@vladmandic/face-api` v1.7.12) |
| Detection Model | SSD MobileNet V1 |
| Landmark Model | 68-Point Facial Landmark |
| Recognition Model | FaceNet 128-D Descriptor |
| Runtime | Browser (TensorFlow.js) — no server needed |
| Match Threshold | Euclidean distance < 0.5 |
| Accuracy | ~95%+ (frontal face, good lighting) |

---

## 🔧 Key Technical Highlights

- **True AC RMS current measurement** — 500 samples × 200µs = 100ms window, covering 5 full 50Hz cycles. Auto zero-calibration on boot.
- **Non-blocking motor control** — Arduino uses `millis()` timers, not `delay()`, so motors stop precisely without blocking sensor reads.
- **Race condition fix** — Firebase stale schedules (>60s overdue) are automatically cleared to prevent phantom device triggers on reconnect.
- **Active-LOW relay handling** — First 3 relays are correctly driven LOW=ON / HIGH=OFF in both firmware and Python.
- **Energy history** — Daily kWh saved to `/power/history/YYYY-MM-DD`, monthly to `/power/monthly_history/YYYY-MM` at rollover.

---

## 📦 Bill of Materials

| Component | Qty |
|---|---|
| Arduino UNO Q (ABX00162) | 1 |
| DHT11 Temperature & Humidity Sensor | 1 |
| Soil Moisture Sensor | 1 |
| MQ-2 Gas Sensor | 1 |
| IR Motion Sensor | 1 |
| ACS712 20A Current Sensor | 1 |
| 5V Solenoid Lock | 1 |
| 4-Channel Relay Module (Active-LOW) | 1 |
| L298N DC Motor Driver | 2 |
| DC Motor | 2 |
| Active Buzzer (5V) | 1 |
| Submersible Water Pump | 1 |
| USB Webcam | 1 |
| Jumper Wires, Breadboard | As required |

---

## 👤 Author

**Bogala Ashok Reddy**
Arduino Physical AI Challenge India 2026

---

## 📄 License

This project is submitted for the Arduino Physical AI Challenge India 2026 (Robu.in × Arduino).
