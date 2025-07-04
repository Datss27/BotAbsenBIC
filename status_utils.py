import os
import json
import logging
from datetime import datetime
from pytz import timezone

WITA = timezone("Asia/Makassar")
STATUS_FILE = os.path.join("cache", "status.json")

def _status_path():
    return STATUS_FILE

def _load_status():
    try:
        with open(_status_path(), "r") as f:
            return json.load(f)
    except Exception as e:
        logging.warning(f"⚠️ Gagal load status: {e}")
        return {}

def _save_status(data):
    try:
        _backup_status()
        os.makedirs(os.path.dirname(_status_path()), exist_ok=True)
        with open(_status_path(), "w") as f:
            json.dump(data, f, indent=2)
        logging.info("✅ Status berhasil disimpan.")
    except Exception as e:
        logging.error(f"❌ Gagal simpan status: {e}")

def _backup_status():
    try:
        path = _status_path()
        if os.path.exists(path):
            with open(path, "r") as src:
                content = src.read()
            with open(path + ".bak", "w") as dst:
                dst.write(content)
    except Exception as e:
        logging.warning(f"⚠️ Backup status.json gagal: {e}")

def reset_status_harian():
    now = datetime.now(WITA)
    today_str = now.strftime("%d %B %Y")
    status = _load_status()
    if status.get("_last_date") != today_str:
        logging.info("🔁 Reset status harian (masuk/pulang)")
        new_status = {"_last_date": today_str}
        _save_status(new_status)
        return new_status
    return status
    
USER_STARTED_FILE = "user_started.json"

def load_started_users():
    try:
        with open(USER_STARTED_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_started_users(users):
    with open(USER_STARTED_FILE, "w") as f:
        json.dump(list(users), f)

def sudah_memulai(chat_id: int) -> bool:
    return chat_id in load_started_users()
