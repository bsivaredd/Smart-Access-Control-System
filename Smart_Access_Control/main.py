"""
Smart Access Control & Irrigation — Arduino App Lab (UNO Q)
Advanced Features: Heartbeat, Timers, Alarms, Logging, Sensor Health, Automations, Energy Tracking.
Developed by Bogala Ashok Reddy
"""
import time
import threading
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
from arduino.app_utils import App, Bridge

# Firebase
import firebase_admin
from firebase_admin import credentials, db as firebase_db

CREDENTIALS_FILE = "firebase-credentials.json"
DATABASE_URL = "https://smart-automation-a7f81-default-rtdb.firebaseio.com/"

firebase_ok = False
try:
    cred = credentials.Certificate(CREDENTIALS_FILE)
    firebase_admin.initialize_app(cred, {'databaseURL': DATABASE_URL})
    firebase_ok = True
    print("[FIREBASE] Connected successfully!")
except Exception as e:
    print(f"[FIREBASE ERROR] {e}")

# ── Global State ─────────────────────────────────────────────────────────
state = {
    "solenoid": False,
    "solenoid_open_time": 0,
    "solenoid_duration": 5,
    "relays": {
        1: {"state": False, "schedule": None, "motion_auto": False, "motion_dur": 10, "motion_triggered_time": 0},
        2: {"state": False, "schedule": None},
        3: {"state": False, "schedule": None}
    },
    "pump": {"state": False, "schedule": None, "auto": False, "threshold": 50},
    "motors": {
        1: {"state": False, "schedule": None, "on_dir": "FWD", "on_dur": 3, "off_dir": "REV", "off_dur": 3, "gas_threshold": 500, "auto": False, "running": False},
        2: {"state": False, "schedule": None, "on_dir": "FWD", "on_dur": 3, "off_dir": "REV", "off_dur": 3, "running": False}
    },
    "sensors": {
        "temperature": 0.0, "humidity": 0.0, "soil": 0, "gas": 0, "ir": 1, "current": 0.0
    },
    "power": {
        "today_kwh": 0.0,
        "month_kwh": 0.0,
        "last_date": ""
    },
    "last_telemetry": 0,
    "sensors_healthy": False
}

# ── Helpers ─────────────────────────────────────────────────────────────
def fb_set(path, value):
    if firebase_ok:
        try: firebase_db.reference(path).set(value)
        except Exception as e: print(f"[FB ERROR] {path}: {e}")

def fb_get(path):
    if firebase_ok:
        try: return firebase_db.reference(path).get()
        except: return None
    return None

def push_log(message):
    print(f"[LOG] {message}")
    if firebase_ok:
        try:
            timestamp = int(time.time() * 1000)
            date_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            firebase_db.reference("/logs").child(str(timestamp)).set({"time": date_str, "msg": message})
            # Trim
            logs = firebase_db.reference("/logs").order_by_key().limit_to_last(20).get()
            if logs: firebase_db.reference("/logs").set(logs)
        except: pass

def send_to_mcu(cmd: str):
    try:
        Bridge.call("receive_command", cmd)
        print(f"[MCU] Sent → {cmd}")
    except Exception as e:
        print(f"[MCU ERROR] {e}")

# Load initial power stats
if firebase_ok:
    try:
        p_data = fb_get("/power")
        if p_data:
            state["power"]["today_kwh"] = float(p_data.get("today_kwh", 0.0))
            state["power"]["month_kwh"] = float(p_data.get("month_kwh", 0.0))
            state["power"]["last_date"] = str(p_data.get("last_date", ""))
    except Exception as e:
        print(f"[INIT ERROR] Power data load failed: {e}")

# ── Telemetry Receiver (From C++) ────────────────────────────────────────
def on_telemetry(data: str):
    try:
        # Expected: T:25.0,H:60.0,S:500,G:300,I:0,C:1.50
        parts = data.split(",")
        temp = float(parts[0].split(":")[1])
        hum  = float(parts[1].split(":")[1])
        soil = int(parts[2].split(":")[1])
        gas  = int(parts[3].split(":")[1])
        ir   = int(parts[4].split(":")[1])
        curr = float(parts[5].split(":")[1])
        
        # Parse motor running states from telemetry (M1/M2)
        m1_run = int(parts[6].split(":")[1]) if len(parts) > 6 else 0
        m2_run = int(parts[7].split(":")[1]) if len(parts) > 7 else 0
        
        state["motors"][1]["running"] = bool(m1_run)
        state["motors"][2]["running"] = bool(m2_run)
        
        state["sensors"]["temperature"] = temp
        state["sensors"]["humidity"] = hum
        state["sensors"]["soil"] = soil
        state["sensors"]["gas"] = gas
        state["sensors"]["ir"] = ir
        state["sensors"]["current"] = curr
        state["last_telemetry"] = time.time()
        
        if not state["sensors_healthy"]:
            state["sensors_healthy"] = True
            fb_set("/sensors_status", "DETECTED")
            push_log("Sensors reconnected and detected.")

        # Update Firebase
        fb_set("/telemetry/temperature", temp)
        fb_set("/telemetry/humidity", hum)
        
        # Convert Soil ADC (0-1023) to Percentage (0-100%)
        soil_pct = max(0, min(100, 100 - (soil / 1023.0 * 100)))
        fb_set("/sensors/soil", int(soil_pct))
        fb_set("/sensors/soil_raw", soil)
        
        # Convert Gas ADC (0-1023) to Percentage
        gas_pct = max(0, min(100, (gas / 1023.0 * 100)))
        fb_set("/sensors/gas", int(gas_pct))
        fb_set("/sensors/gas_raw", gas)
        
        fb_set("/sensors/ir", ir)
        fb_set("/sensors/current", curr)
        
        # Push live motor running status from MCU
        fb_set("/motors/motor1/running", bool(m1_run))
        fb_set("/motors/motor2/running", bool(m2_run))

        # ── AUTOMATIONS ──
        
        # 1. Soil -> Pump (uses raw ADC value 0-1023)
        # Note: Higher raw value = DRIER soil (sensor resistance increases when dry)
        if state["pump"]["auto"]:
            thr = state["pump"]["threshold"]
            pname = state["pump"].get("name", "Water Pump")
            # Pump ON when soil is DRY (raw > threshold means dry)
            if soil > thr and not state["pump"]["state"]:
                fb_set("/pump/state", True)
                push_log(f"Auto Watering ON: Soil raw ({soil}) > Dry threshold ({thr})")
            # Pump OFF when soil is WET enough (raw <= threshold means wet)
            elif soil <= thr and state["pump"]["state"]:
                fb_set("/pump/state", False)
                push_log(f"Auto Watering OFF: Soil raw ({soil}) <= Target ({thr})")

        # 2. IR Motion -> Relay 1 (0 = Detected, 1 = Clear)
        if state["relays"][1]["motion_auto"]:
            if ir == 0: # Motion detected
                state["relays"][1]["motion_triggered_time"] = time.time()
                if not state["relays"][1]["state"]:
                    fb_set("/relays/relay1/state", True)
                    rname = state["relays"][1].get("name", "Relay 1")
                    push_log(f"Motion Detected: Turned on {rname}")

        # 3. Gas raw -> Motor 1 (gas_threshold is raw ADC 0-1023)
        if state["motors"][1]["auto"]:
            thr = state["motors"][1].get("gas_threshold", 500)
            m1name = state["motors"][1].get("name", "Motor 1")
            on_dir  = state["motors"][1].get("on_dir", "FWD")
            off_dir = state["motors"][1].get("off_dir", "REV")
            on_dur  = state["motors"][1].get("on_dur", 3)
            off_dur = state["motors"][1].get("off_dur", 3)
            if gas >= thr:
                if not state["motors"][1].get("buzzing", False):
                    state["motors"][1]["buzzing"] = True
                    send_to_mcu("BUZ:1")
                    push_log("Gas threshold exceeded! Buzzer ON.")
                if state["motors"][1]["state"]:
                    state["motors"][1]["state"] = False
                    fb_set("/motors/motor1/state", False)
                    send_to_mcu(f"M1:{off_dir}:{off_dur * 1000}")
                    push_log(f"GAS ALERT (raw {gas} >= {thr}): {m1name} turned OFF ({off_dir}).")
            else:
                if state["motors"][1].get("buzzing", False):
                    state["motors"][1]["buzzing"] = False
                    send_to_mcu("BUZ:0")
                    push_log("Gas level safe. Buzzer OFF.")

    except Exception as e:
        pass # Ignore malformed packets

Bridge.provide("send_telemetry", on_telemetry)

# ── Background Worker ───────────────────────────────────────────────────
def background_worker_thread():
    power_sync_counter = 0
    
    while True:
        now = time.time()
        
        # 1. Heartbeat
        fb_set("/uno_status/last_heartbeat", int(now))

        # 2. Sensor Health
        if state["sensors_healthy"] and (now - state["last_telemetry"] > 10):
            state["sensors_healthy"] = False
            fb_set("/sensors_status", "NOT DETECTED")
            push_log("WARNING: Sensor connection lost.")

        # 3. Solenoid Auto-Close
        if state["solenoid"] and state["solenoid_open_time"] > 0:
            if now - state["solenoid_open_time"] >= state["solenoid_duration"]:
                push_log(f"Solenoid auto-closed after {state['solenoid_duration']}s.")
                fb_set("/solenoid/state", False)

        # 4. Motion Auto-Close for Relay 1
        r1 = state["relays"][1]
        # Only auto-close if motion sensor is clear (ir == 1)
        if r1["motion_auto"] and r1["state"] and r1["motion_triggered_time"] > 0 and state["sensors"]["ir"] == 1:
            if now - r1["motion_triggered_time"] >= r1["motion_dur"]:
                rname = r1.get("name", "Relay 1")
                push_log(f"{rname} auto-closed after {r1['motion_dur']}s of no motion.")
                fb_set("/relays/relay1/state", False)
                r1["motion_triggered_time"] = 0

        # 5. Schedules (Relays + Pump + Motors)
        devices = [("relay1", state["relays"][1]), 
                   ("relay2", state["relays"][2]), 
                   ("relay3", state["relays"][3]),
                   ("pump",   state["pump"]),
                   ("motor1", state["motors"][1]),
                   ("motor2", state["motors"][2])]
                   
        for dev_path, dev_state in devices:
            sched = dev_state.get("schedule")
            if sched:
                exec_time = sched.get("execute_at", 0)
                if exec_time > 0 and now >= exec_time and (now - exec_time) < 60:
                    target = bool(sched.get("target_state", False))
                    sched_type = sched.get("type", "Schedule")
                    duration = sched.get("duration_mins", 0)
                    dname = dev_state.get("name", dev_path.capitalize())
                    push_log(f"{sched_type} triggered: {dname} turning {'ON' if target else 'OFF'}.")
                    
                    if 'relay' in dev_path:
                        fb_path = f"/relays/{dev_path}/state"
                    elif 'motor' in dev_path:
                        fb_path = f"/motors/{dev_path}/state"
                    else:
                        fb_path = f"/{dev_path}/state"
                    fb_set(fb_path, target)
                    
                    if target and duration > 0:
                        off_time = exec_time + (duration * 60)
                        new_sched = {"type": "TIMER", "execute_at": off_time, "target_state": False}
                        fb_set(fb_path.replace('/state', '/schedule'), new_sched)
                        dev_state["schedule"] = new_sched
                        push_log(f"Scheduled {dname} to turn OFF in {duration} minutes.")
                    else:
                        fb_set(fb_path.replace('/state', '/schedule'), None)
                        dev_state["schedule"] = None

        # 6. Energy Tracking (Every 1 second)
        current = state["sensors"].get("current", 0.0)
        if current > 0.05: # ignore noise under 50mA
            watts = current * 230.0 # Standard India Voltage
            kwh_per_sec = watts / (3600.0 * 1000.0)
            state["power"]["today_kwh"] += kwh_per_sec
            state["power"]["month_kwh"] += kwh_per_sec
            
        current_date = datetime.now(IST).strftime("%Y-%m-%d")
        if state["power"]["last_date"] != current_date:
            if state["power"]["last_date"] != "":
                # Save daily value to history
                last_date = state["power"]["last_date"]
                day_total = state["power"]["today_kwh"]
                fb_set(f"/power/history/{last_date}", day_total)
                push_log(f"Saved daily energy: {day_total:.4f} kWh for {last_date}")
                
                # Date rolled over
                state["power"]["today_kwh"] = 0.0
                if state["power"]["last_date"][:7] != current_date[:7]:
                    # Save monthly value to history
                    last_month = state["power"]["last_date"][:7]
                    month_total = state["power"]["month_kwh"]
                    fb_set(f"/power/monthly_history/{last_month}", month_total)
                    push_log(f"Saved monthly energy: {month_total:.4f} kWh for {last_month}")
                    
                    # Month rolled over
                    state["power"]["month_kwh"] = 0.0
            state["power"]["last_date"] = current_date
            
        power_sync_counter += 1
        if power_sync_counter >= 5: # Sync to Firebase every 5 seconds
            fb_set("/power", state["power"])
            power_sync_counter = 0

        time.sleep(1)

# ── Firebase Listener Thread ─────────────────────────────────────────────
def firebase_listener_thread():
    if not firebase_ok: return

    def on_solenoid(event):
        try:
            d = fb_get("/solenoid")
            if not d: return
            val, duration = bool(d.get("state", False)), int(d.get("duration", 5))
            state["solenoid_duration"] = duration
            if val != state["solenoid"]:
                state["solenoid"] = val
                send_to_mcu(f"SOL:{1 if val else 0}")
                if val:
                    state["solenoid_open_time"] = time.time()
                    push_log(f"Solenoid UNLOCKED (Auto-close in {duration}s)")
                else:
                    state["solenoid_open_time"] = 0
                    push_log("Solenoid manually LOCKED.")
        except: pass

    def on_relays(event):
        try:
            # Use event data to avoid a secondary fb_get race condition
            ref = fb_get("/relays")
            if not ref: return
            for i in [1, 2, 3]:
                r = ref.get(f"relay{i}")
                if r is None: continue
                val = bool(r.get("state", False))
                name = r.get("name", f"Device {i}")
                state["relays"][i]["name"] = name
                
                prev_state = state["relays"][i]["state"]
                if val != prev_state:
                    if state["relays"][i].get("motion_auto") and not val:
                        state["relays"][i]["motion_triggered_time"] = 0
                    state["relays"][i]["state"] = val
                    send_to_mcu(f"R{i}:{1 if val else 0}")
                    push_log(f"{name} switched {'ON' if val else 'OFF'}")
                
                # Only load schedule if it exists and is in the future
                raw_sched = r.get("schedule", None)
                if raw_sched:
                    exec_time = raw_sched.get("execute_at", 0)
                    now_ts = time.time()
                    # Discard stale schedules (more than 60s in the past)
                    if exec_time > 0 and (now_ts - exec_time) > 60:
                        fb_set(f"/relays/relay{i}/schedule", None)
                        state["relays"][i]["schedule"] = None
                        push_log(f"Cleared stale schedule for {name}.")
                    else:
                        state["relays"][i]["schedule"] = raw_sched
                else:
                    state["relays"][i]["schedule"] = None
                
                if i == 1:
                    state["relays"][1]["motion_auto"] = bool(r.get("motion_auto", False))
                    state["relays"][1]["motion_dur"] = int(r.get("motion_dur", 10))
        except Exception as e:
            print(f"[on_relays ERROR] {e}")

    def on_pump(event):
        try:
            p = fb_get("/pump")
            if not p: return
            val = bool(p.get("state", False))
            state["pump"]["name"] = p.get("name", "Water Pump")
            if val != state["pump"]["state"]:
                state["pump"]["state"] = val
                send_to_mcu(f"PUMP:{1 if val else 0}")
                push_log(f"{state['pump']['name']} switched {'ON' if val else 'OFF'}")
            
            state["pump"]["schedule"] = p.get("schedule", None)
            state["pump"]["auto"] = bool(p.get("auto", False))
            state["pump"]["threshold"] = int(p.get("threshold", 50))
        except: pass

    def on_motors(event):
        try:
            ref = fb_get("/motors")
            if not ref: return
            for i in [1, 2]:
                m = ref.get(f"motor{i}")
                if m is None: continue
                val  = bool(m.get("state", False))
                name = m.get("name", f"Motor {i}")
                state["motors"][i]["name"] = name
                
                if val != state["motors"][i]["state"]:
                    state["motors"][i]["state"] = val
                    on_dir  = m.get("on_dir",  "FWD")
                    off_dir = m.get("off_dir", "REV")
                    on_dur  = int(m.get("on_dur",  3))
                    off_dur = int(m.get("off_dur", 3))
                    if val:
                        send_to_mcu(f"M{i}:{on_dir}:{on_dur * 1000}")
                        push_log(f"{name} ON → {on_dir} for {on_dur}s")
                    else:
                        send_to_mcu(f"M{i}:{off_dir}:{off_dur * 1000}")
                        push_log(f"{name} OFF → {off_dir} for {off_dur}s")
                
                # Persist motor config
                state["motors"][i]["on_dir"]  = m.get("on_dir",  "FWD")
                state["motors"][i]["off_dir"] = m.get("off_dir", "REV")
                state["motors"][i]["on_dur"]  = int(m.get("on_dur",  3))
                state["motors"][i]["off_dur"] = int(m.get("off_dur", 3))
                
                # Stale schedule cleanup
                raw_sched = m.get("schedule", None)
                if raw_sched:
                    et = raw_sched.get("execute_at", 0)
                    if et > 0 and (time.time() - et) > 60:
                        fb_set(f"/motors/motor{i}/schedule", None)
                        state["motors"][i]["schedule"] = None
                    else:
                        state["motors"][i]["schedule"] = raw_sched
                else:
                    state["motors"][i]["schedule"] = None
                
                if i == 1:
                    state["motors"][1]["auto"]          = bool(m.get("gas_auto", False))
                    state["motors"][1]["gas_threshold"] = int(m.get("gas_threshold", 500))
        except Exception as e:
            print(f"[on_motors ERROR] {e}")

    firebase_db.reference("/solenoid").listen(on_solenoid)
    firebase_db.reference("/relays").listen(on_relays)
    firebase_db.reference("/pump").listen(on_pump)
    firebase_db.reference("/motors").listen(on_motors)


threading.Thread(target=firebase_listener_thread, daemon=True).start()
threading.Thread(target=background_worker_thread, daemon=True).start()

push_log("System Rebooted - UNO Q Python Backend Started")
print("[SMART ACCESS] App Lab Backend Started!")

App.run()
