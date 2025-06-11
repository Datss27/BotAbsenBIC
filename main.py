# ======= [IMPORTS] =======
import os
import logging
import time
import json
import pickle
import requests
import aiohttp
import asyncio
import random
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from bs4 import BeautifulSoup
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.constants import ParseMode
import random

# ======= [CONFIG] =======
ADMIN_ID = 7952198349
BOT_TOKEN = os.getenv("BOT_TOKEN")
PASSWORD_GLOBAL = os.getenv("PASSWORD_GLOBAL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
os.makedirs("cache", exist_ok=True)

# ======= [PENGGUNA] =======
PENGGUNA = {
    7952198349: {"username": "2015276831", "alias": "Venuel Koraag"},
    5018276186: {"username": "2015021438", "alias": "Ghito Palit"},
    5044153907: {"username": "2015285206", "alias": "Erik Kathiandagho"},
    5162021253: {"username": "2015387831", "alias": "Richard Lontoh"},
    5406034801: {"username": "2015014805", "alias": "Sarfan Antu"},
    5627240666: {"username": "2015447883", "alias": "Sukrianto Matui"},
    5512376425: {"username": "2015344315", "alias": "Kevin Makikama"},
    1341142195: {"username": "2015565161", "alias": "Elshadai Tampi"}
}

# ======= [CACHE FUNCTIONS] =======
def user_cache_path(user_id):
    return os.path.join("cache", f"{user_id}.pkl")

def load_user_cache(user_id):
    path = user_cache_path(user_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "rb") as f:
            cache = pickle.load(f)
        now = time.time()
        valid_session = "session" in cache and now - cache.get("session_time", 0) < 3600
        valid_absen = "absen_data" in cache and now - cache.get("absen_time", 0) < 900
        if not valid_session and not valid_absen:
            os.remove(path)
            print(f"🧹 Cache {user_id} dihapus (expired semua)")
            return {}
        return cache
    except Exception as e:
        print(f"⚠️ Gagal baca cache {user_id}: {e}")
        os.remove(path)
        return {}

def save_user_cache(user_id, cache):
    with open(user_cache_path(user_id), "wb") as f:
        pickle.dump(cache, f)

def _status_path(): 
    return os.path.join("cache", "status.json")

def _load_status():
    try:
        with open(_status_path(), "r") as f:
            return json.load(f)
    except:
        return {}

def _save_status(data):
    with open(_status_path(), "w") as f:
        json.dump(data, f)

def get_font(size=16):
    try:
        font_path = os.path.join("fonts", "DejaVuSans.ttf")
        return ImageFont.truetype(font_path, size)
    except:
        return ImageFont.load_default()
        
def load_ucapan():
    try:
        with open("ucapan.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return ["👍 Good day jo, so cukup 😂✌️"]        
        
async def cek_webhook_info():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
    try:
        resp = requests.get(url)
        if resp.ok:
            data = resp.json().get("result", {})
            print("🔍 Webhook Info:")
            print(f"🌐 URL          : {data.get('url')}")
            print(f"📦 Pending Count: {data.get('pending_update_count')}")
            print(f"✅ Last Error   : {data.get('last_error_message')}")
        else:
            print("⚠️ Gagal mengambil info webhook.")
    except Exception as e:
        print(f"❌ Error saat cek webhook: {e}")


# ======= [ABSEN] =======
def ambil_rekapan_absen_awal_bulan(username, user_id):
    login_url = "https://bicmdo.lalskomputer.my.id/idm_v2/req_masuk"
    absen_url = "https://bicmdo.lalskomputer.my.id/idm_v2/Api/get_absen"

    cache = load_user_cache(user_id)
    now = time.time()

    if "absen_data" in cache and now - cache.get("absen_time", 0) < 900:
        print(f"💾 Gunakan absen cache untuk {user_id}")
        return cache["absen_data"]

    # Bangun sesi dari cookie
    session = requests.Session()
    if "cookies" in cache and now - cache.get("session_time", 0) < 3600:
        session.cookies.update(cache["cookies"])
        print(f"🍪 Menggunakan session dari cookie cache untuk {user_id}")
    else:
        print(f"🔐 Login ulang untuk {user_id}")
        res = session.post(login_url, data={"username": username, "password": PASSWORD_GLOBAL, "ipaddr": ""})
        if "login" in res.text.lower():
            raise Exception("⚠️ Gagal login: Periksa username/password")
        cache["cookies"] = session.cookies.get_dict()
        cache["session_time"] = now

    # Ambil halaman absen
    absen_page = session.get(absen_url)
    if "login" in absen_page.text.lower():
        print(f"🔄 Session expired, login ulang untuk {user_id}")
        session = requests.Session()
        res = session.post(login_url, data={"username": username, "password": PASSWORD_GLOBAL, "ipaddr": ""})
        if "login" in res.text.lower():
            raise Exception("⚠️ Session expired dan login ulang gagal")
        cache["cookies"] = session.cookies.get_dict()
        cache["session_time"] = time.time()
        absen_page = session.get(absen_url)

    # Parsing data absensi
    soup = BeautifulSoup(absen_page.text, "html.parser")
    table = soup.find("table", {"id": "detailAbsen"})
    rows = table.find("tbody").find_all("tr") if table else []

    today = datetime.today()
    awal_bulan = today.replace(day=1)
    data_bulan_ini = []

    for row in rows:
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) >= 9:
            try:
                tanggal = datetime.strptime(cols[3], "%d %B %Y")
                if awal_bulan <= tanggal <= today:
                    jam_in = cols[7][:5].replace(":", ".") if cols[7] else "-"
                    jam_out = cols[8][:5].replace(":", ".") if cols[8] else "-"
                    overtime = "-"
                    try:
                        if jam_in != "-" and jam_out != "-":
                            jam_in_float = float(jam_in.replace(",", "."))
                            jam_out_float = float(jam_out.replace(",", "."))
                            durasi = jam_out_float - jam_in_float
                            if durasi > 8:
                                overtime = f"{durasi - 8:.2f} jam"
                    except:
                        overtime = "-"
                    data_bulan_ini.append({
                        "Tanggal": cols[3],
                        "Status": cols[6],
                        "In": jam_in,
                        "Out": jam_out,
                        "Overtime": overtime
                    })
            except:
                continue

    cache["absen_data"] = data_bulan_ini
    cache["absen_time"] = time.time()
    save_user_cache(user_id, cache)

    return data_bulan_ini

# ======= [GAMBAR ABSEN] =======
def buat_gambar_absensi(data, alias):
    width = 1000
    line_height = 35
    header_height = 50
    padding = 20
    font = get_font(size=18)

    total_height = header_height + line_height * (len(data) + 2) + padding * 2
    img = Image.new("RGB", (width, total_height), color="white")
    draw = ImageDraw.Draw(img)

    draw.text((padding, padding), f"📋 Rekapan Absensi: {alias}", fill="black", font=font)

    y = padding + header_height
    header = ["Tanggal", "Status", "IN", "OUT", "Overtime", ""]
    col_widths = [150, 250, 80, 80, 150, 50]

    x = padding
    for i, col in enumerate(header):
        draw.text((x + 5, y + 8), col, fill="black", font=font)
        x += col_widths[i]
    y += line_height

    icon_check = Image.open("icons/centang.png").resize((20, 20))
    icon_x = Image.open("icons/x.png").resize((20, 20))
    total_overtime = 0.0

    for item in data:
        x = padding
        values = [item["Tanggal"], item["Status"], item["In"], item["Out"], item["Overtime"]]
        status = item["Status"].lower()
        bg_color = (220, 255, 220) if status == "hadir" else (255, 220, 220) if "mangkir" in status else (240, 240, 240)
        draw.rectangle([padding, y, width - padding, y + line_height], fill=bg_color)

        for i, val in enumerate(values):
            draw.text((x + 5, y + 8), val, fill="black", font=font)
            x += col_widths[i]
            draw.line([(x, y), (x, y + line_height)], fill="gray", width=1)

        icon = icon_x if status in ["mangkir", "lupa absen waktu pulang"] else icon_check
        img.paste(icon, (x + 10, y + 7), icon if icon.mode == 'RGBA' else None)

        try:
            if item["Overtime"] != "-" and "jam" in item["Overtime"]:
                overtime_value = float(item["Overtime"].split()[0].replace(",", "."))
                total_overtime += overtime_value
        except:
            pass
        y += line_height

    draw.text((padding, y + 10), f"🕒 Total Estimasi Overtime: {total_overtime:.2f} jam", fill="black", font=font)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

#======= [PING] =======
async def ping_bot():
    async with aiohttp.ClientSession() as session:
        try:
            url = WEBHOOK_URL.replace("/webhook", "/ping")
            async with session.get(url) as resp:
                print(f"📡 Ping sukses: {resp.status}")
        except Exception as e:
            print(f"⚠️ Ping gagal: {e}")

# ======= [COMMAND HANDLERS] =======
async def rekap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id not in PENGGUNA:
        await update.message.reply_text("❌ Anda belum terdaftar untuk menggunakan bot ini.")
        return

    akun = PENGGUNA[chat_id]
    username = akun["username"]
    alias = akun["alias"]

    await update.message.reply_text(f"🚀 Menyiapkan rekap {alias}...")
    try:
        data = ambil_rekapan_absen_awal_bulan(username, chat_id)
        if not data:
            await update.message.reply_text("Tidak ada data bulan ini.")
            return
        img_buffer = buat_gambar_absensi(data, alias)
        await update.message.reply_photo(photo=img_buffer, filename=f"Rekap_{alias}.png")
        ucapan_list = load_ucapan()
        await update.message.reply_text(random.choice(ucapan_list))
    except Exception as e:
        await update.message.reply_text(f"Terjadi kesalahan: {str(e)}")

async def semua(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != ADMIN_ID:
        await update.message.reply_text("❌ Anda tidak diizinkan menggunakan perintah ini.")
        return

    await update.message.reply_text("📋 Mengambil semua rekap...")
    for id_pengguna, akun in PENGGUNA.items():
        username = akun["username"]
        alias = akun["alias"]
        try:
            data = ambil_rekapan_absen_awal_bulan(username, id_pengguna)
            if not data:
                await update.message.reply_text(f"{alias}: Tidak ada data bulan ini.")
                continue
            img_buffer = buat_gambar_absensi(data, alias)
            await update.message.reply_photo(photo=img_buffer, filename=f"Rekap_{alias}.png", caption=f"📄 {alias}")
        except Exception as e:
            await update.message.reply_text(f"{alias}: Gagal kirim rekap: {str(e)}")

# ======= [FUNGSI OTOMATIS] =======
async def kirim_rekap_ke_semua():
    print(f"⚡ [Scheduler] Kirim otomatis {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    bot = Bot(token=BOT_TOKEN)
    report_success = []
    report_fail = []

    for chat_id, akun in PENGGUNA.items():
        username = akun["username"]
        alias = akun["alias"]
        try:
            data = ambil_rekapan_absen_awal_bulan(username, chat_id)
            if not data:
                await bot.send_message(chat_id=chat_id, text=f"{alias}: Tidak ada data bulan ini.")
                report_fail.append(f"❌ {alias}: Tidak ada data")
                continue
            img_buffer = buat_gambar_absensi(data, alias)
            await bot.send_photo(chat_id=chat_id, photo=img_buffer, filename=f"Rekap_{alias}.png")
            ucapan_list = load_ucapan()
            await update.message.reply_text(random.choice(ucapan_list))
            report_success.append(f"✅ {alias}")
        except Exception as e:
            await bot.send_message(chat_id=chat_id, text=f"{alias}: Gagal kirim rekap: {str(e)}")
            report_fail.append(f"❌ {alias}: {str(e)}")

    # Kirim ringkasan ke admin
    summary = f"📊 Rekap Otomatis Selesai\n\n"
    summary += f"✅ Berhasil:\n" + ("\n".join(report_success) if report_success else "Tidak ada") + "\n\n"
    summary += f"❌ Gagal:\n" + ("\n".join(report_fail) if report_fail else "Tidak ada")

    await bot.send_message(chat_id=ADMIN_ID, text=summary, parse_mode=ParseMode.HTML)

async def loop_cek_absen_masuk(bot: Bot):
    print("⏳ Mulai loop cek absen masuk (07–11 tiap 5 menit)")
    status = _load_status()
    while datetime.now().hour < 11:
        changed = False
        for cid, acc in PENGGUNA.items():
            if status.get(str(cid), {}).get("masuk"):
                continue
            data = ambil_rekapan_absen_awal_bulan(acc["username"], cid)
            today = datetime.now().strftime("%d %B %Y")
            found = any(item["Tanggal"] == today and item["In"] not in ["-", "00.00"] for item in data)
            if found:
                t = datetime.now().strftime("%H:%M")
                msg = f"✅ Absen masuk tercatat pukul {t}"
                if datetime.now().hour >= 8:
                    msg += " (⏰ Terlambat)"
                await bot.send_message(chat_id=cid, text=msg)
                await bot.send_message(chat_id=ADMIN_ID, text=f"👤 {acc['alias']} sudah absen masuk pukul {t}")
                status.setdefault(str(cid), {})["masuk"] = True
                changed = True
        if changed: _save_status(status)
        if all(status.get(str(cid), {}).get("masuk") for cid in PENGGUNA):
            print("✅ Semua absen masuk selesai, loop berhenti.")
            break
        await asyncio.sleep(300)

    # Setelah loop selesai (jam >= 11 atau semua absen), kirim notifikasi lupa:
    status = _load_status()
    for cid in PENGGUNA:
        if not status.get(str(cid), {}).get("masuk"):
            await bot.send_message(chat_id=cid, text="Ngana lupa absen datang Bro❗❗❗ ")
            status.setdefault(str(cid), {})["masuk"] = False
    _save_status(status)
    print("🛑 Loop cek absen selesai.")
        
async def loop_cek_absen_pulang(bot: Bot):
    print("⏳ Mulai loop cek absen pulang (16:00–20:00)")
    status = _load_status()

    while datetime.now().hour < 20:
        changed = False
        for cid, acc in PENGGUNA.items():
            if status.get(str(cid), {}).get("pulang"):
                continue
            try:
                data = ambil_rekapan_absen_awal_bulan(acc["username"], cid)
                today = datetime.now().strftime("%d %B %Y")
                for item in data:
                    if item["Tanggal"] == today and item["Out"] not in ["-", "00.00"]:
                        jam_out = item["Out"].replace(".", ":")
                        overtime = item["Overtime"] if item["Overtime"] != "-" else "0"
                        await bot.send_message(
                            chat_id=cid,
                            text=f"✅ Absen pulang terdeteksi pukul {jam_out} – Estimasi Overtime: {overtime}"
                        )
                        await bot.send_message(
                            chat_id=ADMIN_ID, 
                            text=f"👤 {acc['alias']} sudah absen pulang pukul {jam_out} – Estimasi Overtime: {overtime}"
                        )
                        status.setdefault(str(cid), {})["pulang"] = True
                        changed = True
                        break
            except Exception as e:
                print(f"⚠️ Gagal cek absen pulang {acc['username']}: {e}")

        if changed:
            _save_status(status)

        if all(status.get(str(cid), {}).get("pulang") for cid in PENGGUNA):
            print("✅ Semua user sudah absen pulang, loop selesai.")
            break

        await asyncio.sleep(300)

    # Jam 20:00 — Kirim notifikasi ke yang belum absen
    for cid in PENGGUNA:
        if not status.get(str(cid), {}).get("pulang"):
            await bot.send_message(chat_id=cid, text="Ngana lupa absen pulang Bro ❗❗❗")
            status.setdefault(str(cid), {})["pulang"] = False

    _save_status(status)
    print("🛑 Loop cek absen pulang selesai.")

# ======= [WEBHOOK CHECK STARTUP] =======
async def cek_webhook_info():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
    try:
        resp = requests.get(url)
        if resp.ok:
            data = resp.json().get("result", {})
            print("🔍 Webhook Info:")
            print(f"🌐 URL          : {data.get('url')}")
            print(f"📦 Pending Count: {data.get('pending_update_count')}")
            print(f"✅ Last Error   : {data.get('last_error_message')}")
    except Exception as e:
        print(f"❌ Error saat cek webhook: {e}")
        

# ======= [STARTUP & MAIN] =======
async def on_startup(app):
    #set time zone
    scheduler = AsyncIOScheduler(timezone="Asia/Jakarta")
    
    # ======= [DAFTAR TUGAS OTOMATIS] =======
    # KIRIM REKAPAN KE SEMUA
    scheduler.add_job(ping_bot, CronTrigger(hour=21, minute=59))
    scheduler.add_job(kirim_rekap_ke_semua, trigger="cron", hour=22, minute=0)
    
    # CEK ABSEN DATANG
    scheduler.add_job(ping_bot, CronTrigger(hour=5, minute=59))
    scheduler.add_job(lambda: asyncio.create_task(loop_cek_absen_masuk(app.bot)), CronTrigger(hour=6, minute=0))
    
    # CEK ABSEN PULANG
    scheduler.add_job(ping_bot, CronTrigger(hour=15, minute=59))
    scheduler.add_job(lambda: asyncio.create_task(loop_cek_absen_pulang(app.bot)), CronTrigger(hour=16, minute=0))
    
    # CEK WEBHOOK
    scheduler.add_job(cek_webhook_info)
    
    scheduler.start()
    
    await app.bot.set_webhook(WEBHOOK_URL)
    print(f"✅ Webhook aktif di: {WEBHOOK_URL}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()
    app.add_handler(CommandHandler("rekap", rekap))
    app.add_handler(CommandHandler("semua", semua))

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8443)),
        webhook_url=WEBHOOK_URL,
        webhook_path="/webhook"
    )
