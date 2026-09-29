"""
Smart Access Control & Irrigation — Arduino App Lab (UNO Q)
Advanced Features: Heartbeat, Timers, Alarms, Logging, Sensor Health, Automations, Energy Tracking.
Pure-Python Lightweight REST + SSE Client (Zero-C++ Dependencies, No grpcio, Instant Boot).
Developed by Bogala Ashok Reddy
"""
import time
import json
import threading
import urllib.request
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
from arduino.app_utils import App, Bridge

# ── Firebase REST Configuration ──────────────────────────────────────────
DATABASE_URL = "https://smart-automation-a7f81-default-rtdb.firebaseio.com"

# ── Global State ─────────────────────────────────────────────────────────
state = {
    "solenoid": False,
    "solenoid_open_time": 0,
    "solenoid_duration": 5,
    "relays": {
        1: {"state": False, "schedule": None, "motion_auto": False, "motion_dur": 10, "motion_triggered_time": 0, "name": "Relay 1"},
        2: {"state": False, "schedule": None, "name": "Relay 2"},
        3: {"state": False, "schedule": None, "name": "Relay 3"}
    },
    "pump": {"state": False, "schedule": None, "auto": False, "threshold": 50, "name": "Water Pump"},
    "motors": {
        1: {"state": False, "schedule": None, "on_dir": "FWD", "on_dur": 3, "off_dir": "REV", "off_dur": 3, "gas_threshold": 500, "auto": False, "running": False, "name": "Motor 1", "buzzing": False, "buz_dur": 0, "buzzer_started_at": 0},
        2: {"state": False, "schedule": None, "on_dir": "FWD", "on_dur": 3, "off_dir": "REV", "off_dur": 3, "running": False, "name": "Motor 2"}
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

# ── Firebase REST Helpers (Lightweight & Reliable) ───────────────────────
def fb_set(path: str, value):
    clean = path.strip("/")
    url = f"{DATABASE_URL}/{clean}.json"
    try:
        data = json.dumps(value).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="PUT")
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status
    except Exception as e:
        print(f"[FB SET ERROR] {path}: {e}")
        return None

def fb_get(path: str):
    clean = path.strip("/")
    url = f"{DATABASE_URL}/{clean}.json"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        return None

def push_log(message: str):
    print(f"[LOG] {message}")
    try:
        timestamp = int(time.time() * 1000)
        date_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        fb_set(f"logs/{timestamp}", {"time": date_str, "msg": message})
    except:
        pass

def send_to_mcu(cmd: str):
    try:
        Bridge.call("receive_command", cmd)
        print(f"[MCU] Sent → {cmd}")
    except Exception as e:
        print(f"[MCU ERROR] {e}")

# Load initial power stats
try:
    p_data = fb_get("power")
    if p_data:
        state["power"]["today_kwh"] = float(p_data.get("today_kwh", 0.0))
        state["power"]["month_kwh"] = float(p_data.get("month_kwh", 0.0))
        state["power"]["last_date"] = str(p_data.get("last_date", ""))
        print(f"[POWER] Loaded stats: Today={state['power']['today_kwh']:.3f} kWh, Month={state['power']['month_kwh']:.2f} kWh")
except Exception as e:
    print(f"[INIT ERROR] Power data load failed: {e}")

# ── Telemetry Receiver (From C++) ────────────────────────────────────────
def on_telemetry(data: str):
    try:
        state["last_telemetry"] = time.time()
        if not state["sensors_healthy"]:
            state["sensors_healthy"] = True
            fb_set("sensors_status", "DETECTED")
            push_log("Sensors reconnected and detected.")

        # Expected format: "T:25.0,H:60.0,S:450,G:120,I:1,C:0.12,M1:0,M2:0"
        parts = data.strip().split(',')
        parsed = {}
        for p in parts:
            if ':' in p:
                k, v = p.split(':', 1)
                parsed[k] = v

        temp = float(parsed.get('T', 0.0))
        hum = float(parsed.get('H', 0.0))
        soil = int(parsed.get('S', 0))
        gas = int(parsed.get('G', 0))
        ir = int(parsed.get('I', 1))
        curr = float(parsed.get('C', 0.0))
        m1_run = bool(int(parsed.get('M1', 0)))
        m2_run = bool(int(parsed.get('M2', 0)))

        # Update global state
        state["sensors"]["temperature"] = temp
        state["sensors"]["humidity"]    = hum
        state["sensors"]["soil"]        = soil
        state["sensors"]["gas"]         = gas
        state["sensors"]["ir"]          = ir
        state["sensors"]["current"]     = curr
        state["motors"][1]["running"]   = m1_run
        state["motors"][2]["running"]   = m2_run

        # Sync to Firebase
        fb_set("sensors", {
            "temperature": temp, "humidity": hum,
            "soil_raw": soil, "gas_raw": gas,
            "ir": ir, "current": curr
        })
        fb_set("motors/motor1/running", m1_run)
        fb_set("motors/motor2/running", m2_run)

        # ── Automations ──────────────────────────────────────────────────
        # 1. Soil Moisture -> Water Pump (threshold is raw ADC 0-1023)
        if state["pump"]["auto"]:
            thresh = state["pump"].get("threshold", 500)
            if soil > thresh and not state["pump"]["state"]:
                state["pump"]["state"] = True
                fb_set("pump/state", True)
                send_to_mcu("PUMP:1")
                push_log(f"Auto-Watering: Soil is dry (raw {soil} > {thresh}) -> Pump ON")
            elif soil <= thresh and state["pump"]["state"]:
                state["pump"]["state"] = False
                fb_set("pump/state", False)
                send_to_mcu("PUMP:0")
                push_log(f"Auto-Watering: Soil moisture normal (raw {soil} <= {thresh}) -> Pump OFF")

        # 2. IR Motion -> Relay 1
        if state["relays"][1]["motion_auto"]:
            if ir == 0: # Motion detected
                state["relays"][1]["motion_triggered_time"] = time.time()
                if not state["relays"][1]["state"]:
                    fb_set("relays/relay1/state", True)
                    rname = state["relays"][1].get("name", "Relay 1")
                    push_log(f"Motion Detected: Turned on {rname}")

        # 3. Gas Safety -> Motor 1 + Buzzer Alarm
        if state["motors"][1]["auto"]:
            thr = state["motors"][1].get("gas_threshold", 500)
            m1name = state["motors"][1].get("name", "Motor 1")
            on_dir  = state["motors"][1].get("on_dir", "FWD")
            off_dir = state["motors"][1].get("off_dir", "REV")
            on_dur  = state["motors"][1].get("on_dur", 3)
            off_dur = state["motors"][1].get("off_dur", 3)
            buz_dur = state["motors"][1].get("buz_dur", 0)

            if gas >= thr:
                # Trigger buzzer
                if not state["motors"][1].get("buzzing", False):
                    state["motors"][1]["buzzing"] = True
                    state["motors"][1]["buzzer_started_at"] = time.time()
                    send_to_mcu("BUZ:1")
                    fb_set("motors/motor1/buzzing", True)
                    push_log(f"GAS ALERT! Raw level {gas} >= {thr} threshold. Buzzer ON.")
                else:
                    # Auto-silence after buz_dur seconds if configured
                    started = state["motors"][1].get("buzzer_started_at", 0)
                    if buz_dur > 0 and started > 0 and (time.time() - started) >= buz_dur:
                        state["motors"][1]["buzzing"] = False
                        state["motors"][1]["buzzer_started_at"] = 0
                        send_to_mcu("BUZ:0")
                        fb_set("motors/motor1/buzzing", False)
                        push_log(f"Buzzer auto-silenced after {buz_dur}s. Gas still elevated — stay alert!")

                # Emergency shutoff: Turn Motor 1 OFF (close valve)
                if state["motors"][1]["state"]:
                    state["motors"][1]["state"] = False
                    fb_set("motors/motor1/state", False)
                    send_to_mcu(f"M1:{off_dir}:{off_dur * 1000}")
                    push_log(f"GAS ALERT: {m1name} valve turned OFF ({off_dir}).")
            else:
                # Gas is safe
                if state["motors"][1].get("buzzing", False):
                    state["motors"][1]["buzzing"] = False
                    state["motors"][1]["buzzer_started_at"] = 0
                    send_to_mcu("BUZ:0")
                    fb_set("motors/motor1/buzzing", False)
                    push_log("Gas level returned to normal safe level. Buzzer OFF.")

    except Exception as e:
        pass # Ignore malformed packets

Bridge.provide("send_telemetry", on_telemetry)

# ── Background Worker (1Hz Execution) ────────────────────────────────────
def background_worker_thread():
    power_sync_counter = 0
    
    while True:
        try:
            now = time.time()
            
            # 1. Heartbeat
            fb_set("uno_status/last_heartbeat", int(now))

            # 2. Sensor Health
            if state["sensors_healthy"] and (now - state["last_telemetry"] > 10):
                state["sensors_healthy"] = False
                fb_set("sensors_status", "NOT DETECTED")
                push_log("WARNING: Sensor connection lost.")

            # 3. Solenoid Auto-Close
            if state["solenoid"] and state["solenoid_open_time"] > 0:
                if now - state["solenoid_open_time"] >= state["solenoid_duration"]:
                    push_log(f"Solenoid auto-closed after {state['solenoid_duration']}s.")
                    fb_set("solenoid/state", False)

            # 4. Motion Auto-Close for Relay 1
            r1 = state["relays"][1]
            if r1["motion_auto"] and r1["state"] and r1["motion_triggered_time"] > 0 and state["sensors"]["ir"] == 1:
                if now - r1["motion_triggered_time"] >= r1["motion_dur"]:
                    rname = r1.get("name", "Relay 1")
                    push_log(f"{rname} auto-closed after {r1['motion_dur']}s of no motion.")
                    fb_set("relays/relay1/state", False)
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
                            fb_path = f"relays/{dev_path}/state"
                        elif 'motor' in dev_path:
                            fb_path = f"motors/{dev_path}/state"
                        else:
                            fb_path = f"{dev_path}/state"
                        fb_set(fb_path, target)
                        
                        if target and duration > 0:
                            off_time = exec_time + (duration * 60)
                            new_sched = {"type": "TIMER", "execute_at": off_time, "target_state": False}
                            fb_set(fb_path.replace('/state', '/schedule'), new_sched)
                            dev_state["schedule"] = new_sched
                            push_log(f"Scheduled {dname} to turn OFF in {duration} minutes.")
                        elif not target and sched.get("restart_after", False) and duration > 0:
                            on_time = exec_time + (duration * 60)
                            new_sched = {"type": "RESTART", "execute_at": on_time, "target_state": True, "duration_mins": 0}
                            fb_set(fb_path.replace('/state', '/schedule'), new_sched)
                            dev_state["schedule"] = new_sched
                            push_log(f"Auto-Restart: {dname} will turn ON again in {duration} minutes.")
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
                    fb_set(f"power/history/{last_date}", day_total)
                    push_log(f"Saved daily energy: {day_total:.4f} kWh for {last_date}")
                    
                    # Date rolled over
                    state["power"]["today_kwh"] = 0.0
                    if state["power"]["last_date"][:7] != current_date[:7]:
                        last_month = state["power"]["last_date"][:7]
                        month_total = state["power"]["month_kwh"]
                        fb_set(f"power/monthly_history/{last_month}", month_total)
                        push_log(f"Saved monthly energy: {month_total:.4f} kWh for {last_month}")
                        state["power"]["month_kwh"] = 0.0
                state["power"]["last_date"] = current_date
                
            power_sync_counter += 1
            if power_sync_counter >= 5: # Sync to Firebase every 5 seconds
                fb_set("power", state["power"])
                power_sync_counter = 0

        except Exception as e:
            print(f"[WORKER ERROR] {e}")

        time.sleep(1)

# ── Check Device State Updates from Firebase ─────────────────────────────
def check_device_updates():
    try:
        # 1. Solenoid
        sol = fb_get("solenoid")
        if sol:
            val = bool(sol.get("state", False))
            dur = int(sol.get("duration", 5))
            state["solenoid_duration"] = dur
            if val != state["solenoid"]:
                state["solenoid"] = val
                send_to_mcu(f"SOL:{1 if val else 0}")
                if val:
                    state["solenoid_open_time"] = time.time()
                    push_log(f"Solenoid Unlocked (Open for {dur}s)")
                else:
                    push_log("Solenoid Locked")

        # 2. Relays
        relays = fb_get("relays")
        if relays:
            for i in [1, 2, 3]:
                r = relays.get(f"relay{i}")
                if r is None: continue
                val = bool(r.get("state", False))
                name = r.get("name", f"Relay {i}")
                state["relays"][i]["name"] = name
                if val != state["relays"][i]["state"]:
                    state["relays"][i]["state"] = val
                    send_to_mcu(f"R{i}:{1 if val else 0}")
                    push_log(f"{name} turned {'ON' if val else 'OFF'}")
                if i == 1:
                    state["relays"][1]["motion_auto"] = bool(r.get("motion_auto", False))
                    state["relays"][1]["motion_dur"]  = int(r.get("motion_dur", 10))
                raw_sched = r.get("schedule", None)
                if raw_sched:
                    et = raw_sched.get("execute_at", 0)
                    if et > 0 and (time.time() - et) > 60:
                        fb_set(f"relays/relay{i}/schedule", None)
                        state["relays"][i]["schedule"] = None
                    else:
                        state["relays"][i]["schedule"] = raw_sched
                else:
                    state["relays"][i]["schedule"] = None

        # 3. Water Pump
        p = fb_get("pump")
        if p:
            val = bool(p.get("state", False))
            name = p.get("name", "Water Pump")
            state["pump"]["name"] = name
            if val != state["pump"]["state"]:
                state["pump"]["state"] = val
                send_to_mcu(f"PUMP:{1 if val else 0}")
                push_log(f"{name} turned {'ON' if val else 'OFF'}")
            state["pump"]["auto"] = bool(p.get("auto", False))
            state["pump"]["threshold"] = int(p.get("threshold", 50))
            raw_sched = p.get("schedule", None)
            if raw_sched:
                et = raw_sched.get("execute_at", 0)
                if et > 0 and (time.time() - et) > 60:
                    fb_set("pump/schedule", None)
                    state["pump"]["schedule"] = None
                else:
                    state["pump"]["schedule"] = raw_sched
            else:
                state["pump"]["schedule"] = None

        # 4. DC Motors
        motors = fb_get("motors")
        if motors:
            for i in [1, 2]:
                m = motors.get(f"motor{i}")
                if m is None: continue
                val = bool(m.get("state", False))
                name = m.get("name", f"Motor {i}")
                state["motors"][i]["name"] = name
                on_dir  = m.get("on_dir",  "FWD")
                off_dir = m.get("off_dir", "REV")
                on_dur  = int(m.get("on_dur",  3))
                off_dur = int(m.get("off_dur", 3))
                if val != state["motors"][i]["state"]:
                    state["motors"][i]["state"] = val
                    if val:
                        send_to_mcu(f"M{i}:{on_dir}:{on_dur * 1000}")
                        push_log(f"{name} ON → {on_dir} for {on_dur}s")
                    else:
                        send_to_mcu(f"M{i}:{off_dir}:{off_dur * 1000}")
                        push_log(f"{name} OFF → {off_dir} for {off_dur}s")
                state["motors"][i]["on_dir"]  = on_dir
                state["motors"][i]["off_dir"] = off_dir
                state["motors"][i]["on_dur"]  = on_dur
                state["motors"][i]["off_dur"] = off_dur
                raw_sched = m.get("schedule", None)
                if raw_sched:
                    et = raw_sched.get("execute_at", 0)
                    if et > 0 and (time.time() - et) > 60:
                        fb_set(f"motors/motor{i}/schedule", None)
                        state["motors"][i]["schedule"] = None
                    else:
                        state["motors"][i]["schedule"] = raw_sched
                else:
                    state["motors"][i]["schedule"] = None
                if i == 1:
                    state["motors"][1]["auto"]          = bool(m.get("gas_auto", False))
                    state["motors"][1]["gas_threshold"] = int(m.get("gas_threshold", 500))
                    state["motors"][1]["buz_dur"]       = int(m.get("buz_dur", 0))
                    # Handle manual "Silence Buzzer" button from dashboard
                    if m.get("buzzer_off", False):
                        if state["motors"][1].get("buzzing", False):
                            state["motors"][1]["buzzing"] = False
                            state["motors"][1]["buzzer_started_at"] = 0
                            send_to_mcu("BUZ:0")
                            fb_set("motors/motor1/buzzing", False)
                            push_log("Buzzer manually silenced from dashboard.")
                        fb_set("motors/motor1/buzzer_off", None)
    except Exception as e:
        print(f"[CHECK_UPDATES ERROR] {e}")

# ── Firebase Real-Time Listener (SSE Stream + Fallback Polling) ──────────
def firebase_sse_listener_thread():
    """Streams changes from Firebase in real-time using Server-Sent Events."""
    while True:
        try:
            req = urllib.request.Request(f"{DATABASE_URL}/.json", headers={"Accept": "text/event-stream"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                event = None
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:") and event in ("put", "patch"):
                        data_str = line[5:].strip()
                        if data_str and data_str != "null":
                            check_device_updates()
                        event = None
        except Exception as e:
            # Reconnect after brief pause if stream disconnects
            time.sleep(2)

def firebase_polling_fallback_thread():
    """Backup poll loop every 1 second to ensure 100% reliability."""
    while True:
        try:
            check_device_updates()
        except:
            pass
        time.sleep(1)

# Start background worker and listeners
threading.Thread(target=background_worker_thread, daemon=True).start()
threading.Thread(target=firebase_sse_listener_thread, daemon=True).start()
threading.Thread(target=firebase_polling_fallback_thread, daemon=True).start()

push_log("System Rebooted - UNO Q Python Backend Started (Lightweight REST Engine)")
print("[SMART ACCESS] App Lab Backend Started successfully!")

try:
    App.run()
except Exception as e:
    print(f"[APP RUN ERROR] {e}")

# Keep main thread alive permanently so container never terminates
while True:
    time.sleep(10)
