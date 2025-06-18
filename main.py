# ======= [IMPORTS] =======
import os
import time
import pickle
import aiohttp
import asyncio
import logging
import json
import requests
import random
import datetime
from datetime import datetime
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.constants import ParseMode
from aiohttp import web
from pytz import timezone
from telegram.error import TelegramError, BadRequest
from telegram.request import HTTPXRequest

# ======= [CONFIG] =======
ADMIN_ID = 7952198349
BOT_TOKEN = os.getenv("BOT_TOKEN")
PASSWORD_GLOBAL = os.getenv("PASSWORD_GLOBAL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
# Use port 8080 for webhook
PORT = int(os.getenv("PORT", 8080))
WITA = timezone("Asia/Makassar")

# ── CACHE CONFIG ──
CACHE_DIR   = "cache"
CACHE_FILE  = os.path.join(CACHE_DIR, "sessions_async.pkl")
SESSION_TTL = 3600  # detik

LOGIN_URL  = "https://bicmdo.lalskomputer.my.id/idm_v2/req_masuk"
ABSEN_URL  = "https://bicmdo.lalskomputer.my.id/idm_v2/Api/get_absen"
PASSWORD   = os.getenv("PASSWORD_GLOBAL")

# ======= [BOT GLOBAL INSTANCE] =======
request = HTTPXRequest()
bot = Bot(token=BOT_TOKEN, request=request)

# ── UTILS: disk cache untuk cookies ──
os.makedirs(CACHE_DIR, exist_ok=True)

# ── GLOBAL CACHE (in‑memory) ──
SESSION_CACHE = {}

# ======= [PENGGUNA] =======
PENGGUNA = {
    7952198349: {"username": "2015276831", "alias": "Venuel Koraag", "julukan": "Embo"},
    5018276186: {"username": "2015021438", "alias": "Ghito Palit", "julukan": "Tua Ghito"},
    5044153907: {"username": "2015285206", "alias": "Erik Kathiandagho", "julukan": "Erika"},
    5162021253: {"username": "2015387831", "alias": "Richard Lontoh", "julukan": "Papi"},
    5406034801: {"username": "2015014805", "alias": "Sarfan Antu", "julukan": "Bos Arfan"},
    5627240666: {"username": "2015447883", "alias": "Sukrianto Matui", "julukan": "Pak Haji"},
    5512376425: {"username": "2015344315", "alias": "Kevin Makikama", "julukan": "Kribo"},
    1341142195: {"username": "2015565161", "alias": "Elshadai Tampi", "julukan": "ELL"},
    5665809656: {"username": "2013199951", "alias": "Rio Hasan", "julukan": "Ka Rio"}
}

MONTHS = {
    "Januari": "January", "Februari": "February", "Maret": "March",
    "April": "April",     "Mei": "May",       "Juni": "June",
    "Juli": "July",       "Agustus": "August","September": "September",
    "Oktober": "October", "November": "November", "Desember": "December"
}

# ======= [CACHE FUNCTIONS] =======

def load_all_cookies():
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE, "rb") as f:
        data = pickle.load(f)
    now = time.time()
    return {
        uid: info
        for uid, info in data.items()
        if now - info["ts"] < SESSION_TTL
    }

def save_all_cookies(data):
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(data, f)

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

# ======= [MAIN FUNCTIONS] =======
async def get_logged_session(username, user_id):
    now = time.time()
    if user_id in SESSION_CACHE:
        session, ts = SESSION_CACHE[user_id]
        if now - ts < SESSION_TTL and not session.closed:
            return session

    session = aiohttp.ClientSession()
    async with session.post(LOGIN_URL, data={
        "username": username,
        "password": PASSWORD,
        "ipaddr": ""
    }) as res:
        if "web report ic" not in (await res.text()).lower():
            await session.close()
            raise Exception("Login gagal")

    SESSION_CACHE[user_id] = (session, now)

    cj = {c.key: c.value for c in session.cookie_jar}
    all_disk = load_all_cookies()
    all_disk[user_id] = {"cookies": cj, "ts": now}
    save_all_cookies(all_disk)

    return session

async def ambil_rekapan_absen_awal_bulan_async(username, user_id):
    session = await get_logged_session(username, user_id)
    async with session.get(ABSEN_URL) as res:
        html = await res.text()

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "detailAbsen"})
    rows = table.find("tbody").find_all("tr") if table else []

    today = datetime.today()
    awal_bulan = today.replace(day=1)
    data_bulan_ini = []

    for row in rows:
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) < 9:
            continue
        tgl = cols[3]
        for id_bln, en_bln in MONTHS.items():
            tgl = tgl.replace(id_bln, en_bln)
        try:
            tanggal = datetime.strptime(tgl, "%d %B %Y")
        except:
            continue
        if not (awal_bulan <= tanggal <= today):
            continue
        jam_in_raw = cols[7][:5] if cols[7] else "-"
        jam_out_raw = cols[8][:5] if cols[8] else "-"
        jam_in = jam_in_raw.replace(":", ".") if jam_in_raw != "-" else "-"
        jam_out = jam_out_raw.replace(":", ".") if jam_out_raw != "-" else "-"
        status_absen = "Terlambat" if jam_in_raw != "-" and jam_in_raw >= "08:00" else cols[6]
        overtime = "-"
        try:
            if jam_in != "-" and jam_out != "-":
                durasi = float(jam_out) - float(jam_in)
                if durasi > 8:
                    overtime = f"{durasi - 8:.2f} jam"
        except:
            pass

        data_bulan_ini.append({
            "Tanggal": tanggal.strftime("%d %B %Y"),
            "Status": status_absen,
            "In": jam_in,
            "Out": jam_out,
            "Overtime": overtime
        })

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
    url = WEBHOOK_URL.replace("/webhook", "/ping")
    logging.info(f"[Ping] Memulai ping ke: {url}")

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    logging.info(f"📡 Ping sukses ke {url} (status: 200 OK)")
                else:
                    logging.warning(f"⚠️ Ping ke {url} gagal (status: {resp.status})")
    except asyncio.TimeoutError:
        logging.error(f"⏱️ Ping timeout ke {url}")
    except aiohttp.ClientConnectionError as e:
        logging.error(f"🌐 Koneksi gagal saat ping ke {url}: {e}")
    except Exception as e:
        logging.error(f"🚨 Ping error tidak terduga: {e}")

# ======= [COMMAND HANDLERS] =======
async def rekap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id not in PENGGUNA:
        await update.message.reply_text("❌ Anda belum terdaftar untuk menggunakan bot ini.")
        return

    akun = PENGGUNA[chat_id]
    username = akun["username"]
    alias = akun["alias"]
    julukan = akun["julukan"]

    await update.message.reply_text(f"🚀 Menyiapkan rekap {alias}...")
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"👤 {julukan} meminta rekap absensi")
    logging.info(f"[Rekap] {alias} meminta rekap absensi")
    try:
        data = await ambil_rekapan_absen_awal_bulan_async(username, chat_id)
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
            data = await ambil_rekapan_absen_awal_bulan_async(username, id_pengguna)
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

    for chat_id, akun in PENGGUNA.items():
        username = akun["username"]
        alias = akun["alias"]

        try:
            data = await ambil_rekapan_absen_awal_bulan_async(username, chat_id)
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

    # Kumpulkan coroutine per user
    tasks = []
    for cid, acc in PENGGUNA.items():
        key = str(cid)
        if status.get(key, {}).get("masuk"):
            continue

        async def _cek_user_masuk(cid=cid, acc=acc, key=key):
            logging.info(f"mengecek absen masuk {acc['julukan']} ({cid})")
            try:
                data = await ambil_rekapan_absen_awal_bulan_async(acc["username"], cid)
                if any(item["Tanggal"] == today_str for item in data):
                    try:
                        await bot.send_message(cid, f"✅ Absen masuk berhasil, ba scan jo bro")
                    except TelegramError as e:
                        logging.warning(f"Gagal kirim ke {acc['alias']}: {e}")
                    finally:
                        status.setdefault(key, {})["masuk"] = True
                        logging.info(f"[STATUS] {acc['julukan']} ({cid}) ✅ sudah absen datang.")
            except Exception as e:
                logging.warning(f"Gagal cek absen masuk {acc['username']}: {e}")

        tasks.append(_cek_user_masuk())

    if tasks:
        # Jalankan semua task secara paralel
        start = time.time()
        await asyncio.gather(*tasks)
        logging.info(f"[Loop] cek_absen_masuk selesai dalam {time.time() - start:.2f}s")
        _save_status(status)

async def _cek_user_lupa(cid, acc, status):
    key = str(cid)
    if status.get(key, {}).get("masuk"):
        return

    logging.info(f"[_cek_user_lupa] {acc['julukan']} ({cid})")
    try:
        await bot.send_message(chat_id=cid, text="ngana lupa absen maso bro❗❗❗")
        await bot.send_message(chat_id=ADMIN_ID, text=f"👤 {acc['julukan']} lupa absen maso😂")
    except Exception as e:
        logging.warning(f"Gagal notifikasi lupa masuk ke {acc['alias']}: {e}")
    finally:
        status.setdefault(key, {})["masuk"] = False
        logging.info(f"[STATUS] {acc['alias']} ({cid}) ❌ belum absen masuk.")


async def cek_lupa_masuk():
    logging.info("[cek_lupa_masuk] Mengecek lupa absen masuk...")
    status = _load_status()
    tasks = [_cek_user_lupa(cid, acc, status) for cid, acc in PENGGUNA.items()]
    await asyncio.gather(*tasks)
    _save_status(status)
        
        
    
async def cek_absen_pulang():
    status = _load_status()
    now = datetime.now(WITA)
    today_str = now.strftime("%d %B %Y")

    tasks = []
    for cid, acc in PENGGUNA.items():
        key = str(cid)
        if status.get(key, {}).get("pulang"):
            continue

        async def _cek_user_pulang(cid=cid, acc=acc, key=key):
            logging.info(f"[_cek_user_pulang] mengecek absen pulang {acc['julukan']} ({cid})")
            try:
                data = await ambil_rekapan_absen_awal_bulan_async(acc["username"], cid)
                for item in data:
                    if item["Tanggal"] == today_str and item["Out"] not in ["-", "00.00"]:
                        jam_out = item["Out"].replace(".", ":")
                        overtime = item.get("Overtime", "-")
                        try:
                            await bot.send_message(cid, f"✅ Absen pulang pukul {jam_out} – Overtime: {overtime}")
                            await bot.send_message(ADMIN_ID, f"👤 {acc['julukan']} pulang pukul {jam_out}")
                        except Exception as e:
                            logging.warning(f"Gagal kirim pesan absen pulang ke {acc['alias']}: {e}")
                        finally:
                            status.setdefault(key, {})["pulang"] = True
                            logging.info(f"[STATUS] {acc['julukan']} ({cid}) ✅ sudah absen pulang.")
                        break
            except Exception as e:
                logging.warning(f"Gagal cek absen pulang {acc['alias']}: {e}")

        tasks.append(_cek_user_pulang())

    if tasks:
        start = time.time()
        await asyncio.gather(*tasks)
        logging.info(f"[Loop] cek_absen_pulang selesai dalam {time.time() - start:.2f}s")
        _save_status(status)

async def _cek_user_lupa_pulang(cid, acc, status):
    key = str(cid)
    masuk = status.get(key, {}).get("masuk")
    pulang = status.get(key, {}).get("pulang")

    if pulang:
        return

    logging.info(f"[_cek_user_lupa_pulang] {acc['julukan']} ({cid})")

    try:
        await bot.send_message(chat_id=cid, text="ngana lupa absen pulang bro❗❗❗")
        await bot.send_message(chat_id=ADMIN_ID, text=f"👤 {acc['julukan']} lupa absen pulang😂")
    except Exception as e:
        logging.warning(f"Gagal kirim pesan lupa pulang ke {cid}: {e}")
    finally:
        status.setdefault(key, {})["pulang"] = False
        logging.info(f"[STATUS] {acc['alias']} ({cid}) ❌ belum absen pulang.")

    if not masuk:
        try:
            await bot.send_message(chat_id=cid, text="⚠️ ngana mangkir atau SKD ini bro 😂")
            await bot.send_message(chat_id=ADMIN_ID, text=f"👤 {acc['julukan']} lupa ba absen 😂")
        except Exception as e:
            logging.warning(f"Gagal kirim pesan mangkir ke {cid}: {e}")


async def cek_lupa_pulang():
    logging.info("[cek_lupa_pulang] Mengecek lupa absen pulang...")
    status = _load_status()
    tasks = [_cek_user_lupa_pulang(cid, acc, status) for cid, acc in PENGGUNA.items()]
    await asyncio.gather(*tasks)
    _save_status(status)

async def on_startup(app):
    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(timezone=WITA)
    logging.info("[Scheduler] Menjadwalkan tugas-tugas cek absen dan notifikasi...")
    
    # Tugas kirim rekap otomatis
    scheduler.add_job(ping_bot, CronTrigger(hour=5, minute=59, timezone=WITA))
    scheduler.add_job(kirim_rekap_ke_semua, CronTrigger(hour=6, minute=0, timezone=WITA))

    # Tugas cek absensi
    scheduler.add_job(ping_bot, CronTrigger(hour=6, minute=59, timezone=WITA))
    # Loop cek masuk
    scheduler.add_job(
        cek_absen_masuk,
        CronTrigger(minute='*/5', hour='7-9', timezone=WITA)
    )
    # Notifikasi lupa masuk
    scheduler.add_job(
        cek_lupa_masuk,
        CronTrigger(hour=10, minute=0, timezone=WITA)
    )
    # Loop cek pulang
    scheduler.add_job(ping_bot, CronTrigger(hour=16, minute=59, timezone=WITA))
    scheduler.add_job(
        cek_absen_pulang,
        CronTrigger(minute='*/5', hour='17-19', timezone=WITA)
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("log_absen.log"),
            logging.StreamHandler()
        ]
    )

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
        web_app.router.add_post("/webhook/{token}", telegram_webhook)

        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()

        print(f"🌐 Server running on port {PORT}")

        # Keep the service alive
        while True:
            await asyncio.sleep(3600)

    asyncio.run(startup_and_run())
