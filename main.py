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
import datetime
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from bs4 import BeautifulSoup
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.constants import ParseMode
from aiohttp import web
from pytz import timezone
from telegram.error import TelegramError, BadRequest


# ======= [CONFIG] =======
ADMIN_ID = 7952198349
BOT_TOKEN = os.getenv("BOT_TOKEN")
PASSWORD_GLOBAL = os.getenv("PASSWORD_GLOBAL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
# Use port 8080 for webhook
PORT = int(os.getenv("PORT", 8080))
CACHE_DIR = "cache"
CACHE_FILE = os.path.join(CACHE_DIR, "sessions.pkl")
os.makedirs(CACHE_DIR, exist_ok=True)
WITA = timezone("Asia/Makassar")
SESSION_TTL = 3600  # seconds

# ======= [PENGGUNA] =======
PENGGUNA = {
    7952198349: {"username": "2015276831", "alias": "Venuel Koraag"},
    #5018276186: {"username": "2015021438", "alias": "Ghito Palit"},
    #5044153907: {"username": "2015285206", "alias": "Erik Kathiandagho"},
    #5162021253: {"username": "2015387831", "alias": "Richard Lontoh"},
    #5406034801: {"username": "2015014805", "alias": "Sarfan Antu"},
    #5627240666: {"username": "2015447883", "alias": "Sukrianto Matui"},
    #5512376425: {"username": "2015344315", "alias": "Kevin Makikama"},
    #1341142195: {"username": "2015565161", "alias": "Elshadai Tampi"}
}

# ======= [CACHE FUNCTIONS] =======
def load_all_sessions():
    """
    Load all user session caches, purge expired entries automatically.
    """
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "rb") as f:
            sessions = pickle.load(f)
    except Exception:
        os.remove(CACHE_FILE)
        return {}

    # Purge expired sessions
    now = time.time()
    expired = [uid for uid, entry in sessions.items() if now - entry.get("session_time", 0) >= SESSION_TTL]
    for uid in expired:
        sessions.pop(uid, None)
        logging.info(f"🗑️ Purged expired session for user {uid}")
    if expired:
        save_all_sessions(sessions)
    return sessions


def save_all_sessions(sessions):
    """
    Save all user session caches to single file.
    """
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(sessions, f)


def load_user_cache(user_id):
    """
    Return cached cookies for user_id if valid.
    """
    sessions = load_all_sessions()
    return sessions.get(user_id, {})


def save_user_cache(user_id, cookies):
    """
    Save cookies for user_id with current timestamp.
    """
    sessions = load_all_sessions()
    sessions[user_id] = {"cookies": cookies, "session_time": time.time()}
    save_all_sessions(sessions)

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

# ======= [ABSEN] =======
def ambil_rekapan_absen_awal_bulan(username, user_id):
    login_url = "https://bicmdo.lalskomputer.my.id/idm_v2/req_masuk"
    absen_url = "https://bicmdo.lalskomputer.my.id/idm_v2/Api/get_absen"

    # load session cache for this user
    cache = load_user_cache(user_id)
    now = time.time()

    session = requests.Session()
    # reuse cookies if exist
    if cache.get("cookies"):
        session.cookies.update(cache["cookies"])
        logging.info(f"🍪 Using cached session for user {user_id}")
    else:
        # perform login
        logging.info(f"🔐 Logging in for user {user_id}")
        res = session.post(login_url, data={"username": username, "password": PASSWORD_GLOBAL, "ipaddr": ""})
        if "web report ic" not in res.text.lower():
            raise Exception("⚠️ Failed login: check username/password")
        save_user_cache(user_id, session.cookies.get_dict())

    # Ambil halaman absen
    res = session.get(absen_url)
    if '<table id="detailAbsen"' not in res.text:
        # session expired server-side, re-login
        logging.info(f"🔄 Session expired, re-login for user {user_id}")
        session = requests.Session()
        res_login = session.post(login_url, data={"username": username, "password": PASSWORD_GLOBAL, "ipaddr": ""})
        if "web report ic" not in res_login.text.lower():
            raise Exception("⚠️ Session expired and re-login failed")
        save_user_cache(user_id, session.cookies.get_dict())
        res = session.get(absen_url)

    # Parsing data absensi
    soup = BeautifulSoup(res.text, "html.parser")
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
                    jam_in_raw = cols[7][:5] if cols[7] else "-"
                    jam_out_raw = cols[8][:5] if cols[8] else "-"
                    jam_in = jam_in_raw.replace(":", ".") if jam_in_raw != "-" else "-"
                    jam_out = jam_out_raw.replace(":", ".") if jam_out_raw != "-" else "-"

                    status_absen = "Terlambat" if jam_in_raw != "-" and jam_in_raw >= "08:00" else cols[6]

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
                        "Status": status_absen,
                        "In": jam_in,
                        "Out": jam_out,
                        "Overtime": overtime
                    })
            except:
                continue


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

#======= [UCAPAN] =======
async def kirim_ucapan(update: Update):
    ucapan_list = load_ucapan()
    ucapan = random.choice(ucapan_list)

    pesan = f"""
*{ucapan}*

📅 {datetime.now().strftime('%A, %d %B %Y')}
"""
    await update.message.reply_text(pesan, parse_mode=ParseMode.MARKDOWN)

async def kirim_ucapan_ke(bot: Bot, chat_id: int):
    ucapan_list = load_ucapan()
    ucapan = random.choice(ucapan_list)

    pesan = f"""
🌟 *Ucapan Spesial Hari Ini* 🌟

*{ucapan}*

📅 {datetime.now().strftime('%A, %d %B %Y')}
"""
    await bot.send_message(chat_id=chat_id, text=pesan, parse_mode=ParseMode.MARKDOWN)
    
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
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"👤 {alias} meminta rekap absensi")
    logging.info(f"[Rekap] {alias} meminta rekap absensi")
    try:
        data = ambil_rekapan_absen_awal_bulan(username, chat_id)
        if not data:
            await update.message.reply_text("Tidak ada data bulan ini.")
            return
        img_buffer = buat_gambar_absensi(data, alias)
        await update.message.reply_photo(photo=img_buffer, filename=f"Rekap_{alias}.png")
        ucapan_list = load_ucapan()
        await kirim_ucapan(update)
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
    logging.info(f"[kirim_rekap_ke_semua] mengirim rekap absensi ke semua")
    waktu_skrg = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"⚡ [Scheduler] Kirim otomatis {waktu_skrg}")

    report_success = []
    report_fail = []

    async with Bot(token=BOT_TOKEN) as bot:
        for chat_id, akun in PENGGUNA.items():
            username = akun["username"]
            alias = akun["alias"]

            try:
                data = ambil_rekapan_absen_awal_bulan(username, chat_id)
                if not data:
                    await bot.send_message(chat_id=chat_id, text=f"📭 {alias}: Tidak ada data bulan ini.")
                    report_fail.append(f"❌ {alias}: Data kosong")
                    continue

                img_buffer = buat_gambar_absensi(data, alias)
                await bot.send_photo(chat_id=chat_id, photo=img_buffer, filename=f"Rekap_{alias}.png")

                await kirim_ucapan_ke(bot, chat_id)
                report_success.append(f"✅ {alias}")

            except BadRequest as e:
                if "chat not found" in str(e).lower():
                    report_fail.append(f"❌ {alias}: Chat ID tidak ditemukan (mungkin belum /start)")
                else:
                    report_fail.append(f"❌ {alias}: BadRequest - {str(e)}")
            except TelegramError as e:
                report_fail.append(f"❌ {alias}: Telegram error - {str(e)}")
            except Exception as e:
                report_fail.append(f"❌ {alias}: {str(e)}")

        # Kirim ringkasan ke admin
        summary = f"<b>📊 Rekap Otomatis Selesai</b>\n🕒"
        summary += f"<b>✅ Berhasil:</b>\n" + ("\n".join(report_success) if report_success else "Tidak ada") + "\n\n"
        summary += f"<b>❌ Gagal:</b>\n" + ("\n".join(report_fail) if report_fail else "Tidak ada")

        try:
            await bot.send_message(chat_id=ADMIN_ID, text=summary, parse_mode=ParseMode.HTML)
        except Exception as e:
            print(f"⚠️ Gagal kirim rekap ke admin: {e}")

async def cek_absen_masuk():
    status = _load_status()
    now = datetime.now(WITA)
    today_str = now.strftime("%d %B %Y")
    bot = Bot(token=BOT_TOKEN)

    # Kumpulkan coroutine per user
    tasks = []
    for cid, acc in PENGGUNA.items():
        key = str(cid)
        if status.get(key, {}).get("masuk"):
            continue

        async def _cek_user_masuk(cid=cid, acc=acc, key=key):
            try:
                data = ambil_rekapan_absen_awal_bulan(acc["username"], cid)
                if any(item["Tanggal"] == today_str for item in data):
                    t = now.strftime("%H:%M")
                    label = " (Terlambat trusss😂)" if now.hour >= 8 else ""
                    await bot.send_message(cid, f"✅ Absen masuk tercatat pukul {t}{label}")
                    await bot.send_message(ADMIN_ID, f"👤 {acc['alias']} absen masuk pukul {t}")
                    status.setdefault(key, {})["masuk"] = True
            except Exception as e:
                logging.warning(f"Gagal cek absen masuk {acc['username']}: {e}")

        tasks.append(_cek_user_masuk())

    if tasks:
        # Jalankan semua task secara paralel
        start = time.time()
        await asyncio.gather(*tasks)
        logging.info(f"[Loop] cek_absen_masuk selesai dalam {time.time() - start:.2f}s")
        _save_status(status)

async def cek_lupa_masuk():
    logging.info("[Loop] Mengecek lupa absen masuk...")
    """
    Notifikasi lupa absen datang pada pukul 11:00 WITA
    """
    status = _load_status()
    bot = Bot(token=BOT_TOKEN)
    now = datetime.now(WITA)
    today_str = now.strftime("%d %B %Y")

    tasks = []
    for cid, acc in PENGGUNA.items():
        key = str(cid)
        # hanya yang belum absen masuk
        if status.get(key, {}).get("masuk"):
            continue
        async def _cek_user_lupa(cid=cid, acc=acc, key=key):
            try:
                await bot.send_message(chat_id=cid, text="ngana lupa absen maso bro❗❗❗")
                await bot.send_message(chat_id=ADMIN_ID, text=f"👤 {acc['alias']} lupa absen maso😂")
                status.setdefault(key, {})["masuk"] = False
            except Exception as e:
                logging.warning(f"Gagal notifikasi lupa absen masuk {acc['username']}: {e}")

        tasks.append(_cek_user_lupa())

    if tasks:
        start = time.time()
        await asyncio.gather(*tasks)
        logging.info(f"[Loop] cek_absen_masuk selesai dalam {time.time() - start:.2f}s")
        _save_status(status)
    
async def cek_absen_pulang():
    status = _load_status()
    now = datetime.now(WITA)
    today_str = now.strftime("%d %B %Y")
    bot = Bot(token=BOT_TOKEN)

    tasks = []
    for cid, acc in PENGGUNA.items():
        key = str(cid)
        if status.get(key, {}).get("pulang"):
            continue

        async def _cek_user_pulang(cid=cid, acc=acc, key=key):
            try:
                data = ambil_rekapan_absen_awal_bulan(acc["username"], cid)
                for item in data:
                    if item["Tanggal"] == today_str and item["Out"] not in ["-", "00.00"]:
                        jam_out = item["Out"].replace(".", ":")
                        overtime = item.get("Overtime", "-")
                        await bot.send_message(cid, f"✅ Absen pulang pukul {jam_out} – Overtime: {overtime}")
                        await bot.send_message(ADMIN_ID, f"👤 {acc['alias']} pulang pukul {jam_out}")
                        status.setdefault(key, {})["pulang"] = True
                        break
            except Exception as e:
                logging.warning(f"Gagal cek absen pulang {acc['username']}: {e}")

        tasks.append(_cek_user_pulang())

    if tasks:
        start = time.time()
        await asyncio.gather(*tasks)
        logging.info(f"[Loop] cek_absen_masuk selesai dalam {time.time() - start:.2f}s")
        _save_status(status)

async def cek_lupa_pulang():
    logging.info("[Loop] Mengecek lupa absen pulang...")
    """
    Notifikasi lupa absen pulang pada akhir hari
    """
    status = _load_status()
    bot = Bot(token=BOT_TOKEN)

    tasks = []
    for cid, acc in PENGGUNA.items():
        key = str(cid)
        masuk = status.get(key, {}).get("masuk")
        pulang = status.get(key, {}).get("pulang")

        async def _cek_user_lupa_pulang(cid=cid, acc=acc, key=key, masuk=masuk, pulang=pulang):
            try:
                if not pulang:
                    await bot.send_message(chat_id=cid, text="ngana lupa absen pulang bro❗❗❗")
                    await bot.send_message(chat_id=ADMIN_ID, text=f"👤 {acc['alias']} lupa absen pulang😂")
                    status.setdefault(key, {})["pulang"] = False
                if not masuk and not pulang:
                    await bot.send_message(chat_id=cid, text="⚠️ ngana mangkir atau SKD ini bro 😂")
                    await bot.send_message(chat_id=ADMIN_ID, text=f"👤 {acc['alias']} lupa ba absen 😂")
            except Exception as e:
                logging.warning(f"Gagal notifikasi lupa absen pulang {acc['username']}: {e}")

        tasks.append(_cek_user_lupa_pulang())

    if tasks:
        start = time.time()
        await asyncio.gather(*tasks)
        logging.info(f"[Loop] cek_absen_masuk selesai dalam {time.time() - start:.2f}s")
        _save_status(status)

async def on_startup(app):
    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(timezone=WITA)
    logging.info("[Scheduler] Menjadwalkan tugas-tugas cek absen dan notifikasi...")
    
    # Tugas kirim rekap otomatis
    #scheduler.add_job(ping_bot, CronTrigger(hour=21, minute=59, timezone=WITA))
    #scheduler.add_job(kirim_rekap_ke_semua, CronTrigger(hour=22, minute=0, timezone=WITA))

    # Tugas cek absensi
    #scheduler.add_job(ping_bot, CronTrigger(hour=6, minute=59, timezone=WITA))
    # Loop cek masuk
    scheduler.add_job(
        cek_absen_masuk,
        CronTrigger(minute='*/1', hour='22-23', timezone=WITA)
    )
    # Notifikasi lupa masuk
    scheduler.add_job(
        cek_lupa_masuk,
        CronTrigger(hour=10, minute=0, timezone=WITA)
    )
    # Loop cek pulang
    scheduler.add_job(ping_bot, CronTrigger(hour=15, minute=59, timezone=WITA))
    scheduler.add_job(
        cek_absen_pulang,
        CronTrigger(minute='*/1', hour='17-19', timezone=WITA)
    )
    # Notifikasi lupa pulang
    scheduler.add_job(
    cek_lupa_pulang,
    CronTrigger(hour=20, minute=0, timezone=WITA)
    )

    scheduler.start()
    logging.info("[Scheduler] Semua tugas dijalankan.")

# ======= [WEBHOOK CHECK STARTUP] =======
async def telegram_webhook(request):
    # Verify token in URL
    token = request.match_info.get('token')
    if token != BOT_TOKEN:
        return web.Response(status=403)

    data = await request.json()
    update = Update.de_json(data, request.app['bot_app'].bot)
    # Put incoming update into the application's queue
    await request.app['bot_app'].update_queue.put(update)
    return web.Response(text="OK")
    
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def startup_and_run():
        # Build the bot application
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        # Register command handlers
        app.add_handler(CommandHandler("rekap", rekap))
        app.add_handler(CommandHandler("semua", semua))

        # Initialize & start the application (dispatcher, job queue, etc)
        await app.initialize()
        await app.start()

        # **Pasang webhook** (sekali saja)
        webhook_endpoint = f"/webhook/{BOT_TOKEN}"
        full_webhook_url = f"{WEBHOOK_URL}{webhook_endpoint}"
        await app.bot.set_webhook(full_webhook_url)
        logging.info(f"✅ Webhook active at: {full_webhook_url}")
        
        # Run startup tasks (scheduler + webhook)
        await on_startup(app)

        # Create aiohttp web server for webhook
        web_app = web.Application()
        web_app['bot_app'] = app
        # Route webhook requests
        web_app.router.add_post(webhook_endpoint, telegram_webhook)
        # Health check endpoint
        web_app.router.add_get('/ping', lambda r: web.Response(text='pong'))

        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()

        print(f"🌐 Server running on port {PORT}")

        # Keep the service alive
        while True:
            await asyncio.sleep(3600)

    asyncio.run(startup_and_run())
