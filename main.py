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
import sys
from datetime import datetime
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, CallbackQueryHandler, filters
)
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.constants import ParseMode
from aiohttp import web
from pytz import timezone
from telegram.error import TelegramError, BadRequest
from telegram.request import HTTPXRequest
from telegram.ext import CallbackQueryHandler
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from modul_libur import fetch_libur_nasional, is_libur_nasional
from status_utils import (
    _load_status, _save_status, reset_status_harian,
    load_started_users, save_started_users, sudah_memulai
)

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
sudah_dilaporkan_user_nonaktif = set()

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
# ========= [SEND MESSAGE AMAN] =========
sudah_dilaporkan_user_nonaktif = set()

async def kirim_pesan_aman(chat_id: int, text: str, parse_mode=None):
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
        return True
    except BadRequest as e:
        if "chat not found" in str(e).lower():
            alias = PENGGUNA.get(chat_id, {}).get("alias", str(chat_id))
            if chat_id not in sudah_dilaporkan_user_nonaktif:
                await bot.send_message(ADMIN_ID, f"⚠️ Tidak bisa kirim pesan ke <b>{alias}</b>.\nUser belum /start atau blokir bot.", parse_mode=ParseMode.HTML)
                sudah_dilaporkan_user_nonaktif.add(chat_id)
            #logging.warning(f"[BOT] User {chat_id} belum /start atau blokir bot.")
        else:
            logging.error(f"[BOT] Gagal kirim pesan ke {chat_id}: {e}")
    except Exception as e:
        logging.error(f"[BOT] Error tak terduga saat kirim pesan ke {chat_id}: {e}")
    return False        

# ======= [MAIN FUNCTIONS] =======
async def get_logged_session(username, user_id):
    now = time.time()

    if user_id in SESSION_CACHE:
        session, ts = SESSION_CACHE[user_id]
        if now - ts < SESSION_TTL and not session.closed:
            return session
        else:
            if not session.closed:
                await session.close()
                logging.debug(f"[Session] Menutup sesi lama untuk user {user_id}")

    session = aiohttp.ClientSession()
    try:
        async with session.post(LOGIN_URL, data={
            "username": username,
            "password": PASSWORD,
            "ipaddr": ""
        }) as res:
            html = await res.text()
            if "web report ic" not in html.lower():
                await session.close()
                raise Exception("Login gagal")

        SESSION_CACHE[user_id] = (session, now)

        cj = {c.key: c.value for c in session.cookie_jar}
        all_disk = load_all_cookies()
        all_disk[user_id] = {"cookies": cj, "ts": now}
        save_all_cookies(all_disk)

        return session

    except Exception as e:
        await session.close()
        raise e

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
        status_asli = cols[6].strip()
        jam_masuk_valid = jam_in_raw != "-" and jam_in_raw >= "08:00"

        if status_asli.lower() == "hadir" and jam_masuk_valid:
            status_absen = "Terlambat"
        else:
            status_absen = status_asli
        overtime = "-"
        try:
            if jam_in != "-" and jam_out != "-":
                jam_masuk = float(jam_in)
                jam_pulang = float(jam_out)

                # Cek apakah hari absen adalah Sabtu
                hari_absen = tanggal.strftime("%A")  # e.g., "Saturday"
                jam_kerja = 6 if hari_absen == "Saturday" else 8

                batas_pulang = jam_masuk + jam_kerja
                if jam_pulang > batas_pulang:
                    overtime = f"{jam_pulang - batas_pulang:.2f} jam"
        except Exception as e:
            logging.error(f"Gagal hitung overtime: {e}")
            
        data_bulan_ini.append({
            "Tanggal": tanggal.strftime("%d %B %Y"),
            "Status": status_absen,
            "In": jam_in,
            "Out": jam_out,
            "Overtime": overtime
        })

    return data_bulan_ini
    
async def rekap_spl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cid = query.message.chat_id

    if cid not in PENGGUNA:
        await context.bot.send_message(chat_id=cid, text="❌ Anda belum terdaftar.")
        return

    akun = PENGGUNA[cid]
    username = akun["username"]
    alias = akun["alias"]
    julukan = akun["julukan"]

    now = datetime.now(WITA)
    awal_bulan = now.replace(day=1)
    tanggal_awal = awal_bulan.strftime("%d %B %Y")
    tanggal_akhir = now.strftime("%d %B %Y")

    await query.edit_message_text("📊 Sedang menghitung SPL Anda...")
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"👤 {julukan} meminta rekapan SPL")

    try:
        data = await ambil_rekapan_absen_awal_bulan_async(username, cid)
        total_overtime = 0.0
        rincian = ""

        for item in data:
            overtime = item.get("Overtime", "-")
            if overtime != "-" and "jam" in overtime:
                try:
                    jam = float(overtime.split()[0].replace(",", "."))
                    if jam > 0:
                        total_overtime += jam
                        rincian += f"• {item['Tanggal']}: {jam:.2f} jam\n"
                except:
                    pass

        if total_overtime > 0:
            pesan = (
                f"<b>Rekapan SPL {alias}</b>\n"
                f"📆 Periode: <b>{tanggal_awal}</b> s.d. <b>{tanggal_akhir}</b>\n"
                f"{rincian}"
                f"🕒 Total Overtime: <b>{total_overtime:.2f} jam</b>\n\n"
            )
        else:
            pesan = (
                f"👋 Hai <b>{alias}</b>,\n\n"
                f"Belum ada overtime dari awal bulan sampai hari ini. 💤"
            )

        await context.bot.send_message(cid, pesan, parse_mode=ParseMode.HTML)

    except Exception as e:
        logging.warning(f"[SPL Manual] Gagal ambil SPL untuk {alias}: {e}")
        await context.bot.send_message(cid, "❌ Gagal mengambil data SPL.")

# ======= [GAMBAR ABSEN] =======
def buat_gambar_absensi(data, alias):
    width = 1000
    line_height = 38
    header_height = 60
    padding = 25
    font = get_font(size=18)
    font_bold = get_font(size=20)

    total_height = header_height + line_height * (len(data) + 2) + padding * 2
    img = Image.new("RGB", (width, total_height), color="white")
    draw = ImageDraw.Draw(img)

    # Judul
    icon_judul = Image.open("icons/user.png").resize((32, 32))
    img.paste(icon_judul, (padding, padding), icon_judul)
    draw.text((padding + 40, padding + 4), f"Rekapan Absensi: {alias}", fill="black", font=font_bold)

    y = padding + header_height
    header = ["Tanggal", "Status", "IN", "OUT", "Overtime", ""]
    col_widths = [150, 300, 80, 80, 150, 50]

    # Header bar latar biru muda
    x = padding
    for i, col in enumerate(header):
        draw.rectangle([x, y, x + col_widths[i], y + line_height], fill=(200, 220, 255))
        draw.text((x + 5, y + 8), col, fill="black", font=font_bold)
        x += col_widths[i]
    y += line_height

    icon_check = Image.open("icons/centang.png").resize((20, 20))
    icon_x = Image.open("icons/x.png").resize((20, 20))
    icon_late = Image.open("icons/terlambat.png").resize((20, 20))
    icon_holiday = Image.open("icons/libur.png").resize((20, 20))
    icon_ijin = Image.open("icons/ijin.png").resize((20, 20))
    icon_lupa = Image.open("icons/lupa.png").resize((20, 20))
    total_overtime = 0.0

    for item in data:
        x = padding
        values = [item["Tanggal"], item["Status"], item["In"], item["Out"], item["Overtime"]]
        status = item["Status"].lower()

        if status in ["hadir", "ijin datang terlambat", "ijin pulang"]:
            bg_color = (220, 255, 220)  # Hijau muda
        elif status in ["mangkir", "terlambat", "lupa absen waktu pulang"]:
            bg_color = (255, 220, 220)  # Merah muda
        elif status in ["libur", "hari libur nasional"]:
            bg_color = (210, 230, 255)  # Biru muda
        else:
            bg_color = (240, 240, 240)  # Netral

        draw.rectangle([padding, y, width - padding, y + line_height], fill=bg_color)

        for i, val in enumerate(values):
            draw.text((x + 5, y + 8), val, fill="black", font=font)
            x += col_widths[i]

        # Simbol centang / silang
        if status == "hadir":
            icon = icon_check
        elif status == "mangkir":
            icon = icon_x
        elif status == "terlambat":
            icon = icon_late
        elif status == "lupa absen waktu pulang":
            icon = icon_lupa
        elif status in ["libur", "hari libur nasional"]:
            icon = icon_holiday
        elif status in ["ijin datang terlambat", "ijin pulang"]:
            icon = icon_ijin
        else:
            icon = icon_check  # fallback default
        
        img.paste(icon, (x + 10, y + 9), icon if icon.mode == 'RGBA' else None)

        try:
            if item["Overtime"] != "-" and "jam" in item["Overtime"]:
                overtime_value = float(item["Overtime"].split()[0].replace(",", "."))
                total_overtime += overtime_value
        except:
            pass
        y += line_height

    # Total overtime
    overtime_text = f"Total Estimasi Overtime: {total_overtime:.2f} jam"
    icon_jam = Image.open("icons/overtime.png").resize((24, 24))
    
    try:
        tw, _ = font_bold.getsize(overtime_text)
    except AttributeError:
        bbox = font_bold.getbbox(overtime_text)
        tw = bbox[2] - bbox[0]
    
    ox = (width - tw) // 2
    
    # Tempel ikon sebelum teks
    img.paste(icon_jam, (ox - 30, y + 12), icon_jam)
    draw.text((ox, y + 10), overtime_text, fill="black", font=font_bold)

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
    
state_broadcast = set()

def format_broadcast_message(pesan: str) -> str:
    tanggal = datetime.now(WITA).strftime('%A, %d %B %Y')
    return (
        f"<b>📢 Info-Info</b>\n"
        f"🗓️ {tanggal}\n\n"
        f"{pesan}\n\n"
        f"<b>📢 Brando</b>"
    )

#======= [UCAPAN] =======

async def kirim_ucapan(update: Update):
    ucapan_list = load_ucapan()
    ucapan = random.choice(ucapan_list)

    tanggal = datetime.now(WITA).strftime('%A, %d %B %Y')
    pesan = (
        f"<b>{ucapan}</b>\n\n"
        f"<b>{tanggal}</b>"
    )
    await update.message.reply_text(pesan, parse_mode=ParseMode.HTML)

async def kirim_ucapan_ke(bot: Bot, chat_id: int):
    ucapan_list = load_ucapan()
    ucapan = random.choice(ucapan_list)

    tanggal = datetime.now(WITA).strftime('%A, %d %B %Y')
    pesan = (
        f"<b>{ucapan}</b>\n\n"
        f"<b>{tanggal}</b>"
    )
    await bot.send_message(chat_id=chat_id, text=pesan, parse_mode=ParseMode.HTML)
    
#======= [PING] =======
async def ping_bot():
    url = WEBHOOK_URL.replace("/webhook", "/ping")  # pastikan ada endpoint /ping di web Anda
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    logging.debug(f"✅ Ping OK {url}")
    except:
        pass  # Jangan log error agar log tidak penuh

async def ping_handler(request):
    return web.Response(text="pong")
    
async def conditional_ping():
    now = datetime.now(WITA)
    jam = now.hour

    # Zona idle siang: 11.00 - 16.59 | malam: 21.01 - 05.59
    if (11 <= jam < 17) or (21 <= jam or jam < 6):
        logging.debug("[Ping] Zona idle, mengirim ping...")
        await ping_bot()
    else:
        logging.debug("[Ping] Zona aktif, skip ping.")

# ======= [COMMAND HANDLERS] =======
async def rekap_absen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if chat_id not in PENGGUNA:
        await query.edit_message_text("❌ Anda belum terdaftar.")
        return

    akun = PENGGUNA[chat_id]
    username = akun["username"]
    alias = akun["alias"]
    julukan = akun["julukan"]

    await query.edit_message_text(f"🚀 Menyiapkan rekapan absen {alias}...")
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"👤 {julukan} meminta rekapan absen")

    try:
        data = await ambil_rekapan_absen_awal_bulan_async(username, chat_id)
        if not data:
            await context.bot.send_message(chat_id, "Tidak ada data bulan ini.")
            return

        img_buffer = buat_gambar_absensi(data, alias)
        await context.bot.send_photo(chat_id=chat_id, photo=img_buffer, filename=f"Rekap_{alias}.png")
        await kirim_ucapan_ke(context.bot, chat_id)
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Terjadi kesalahan: {str(e)}")

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

async def rekap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📋 Absen", callback_data="rekap_absen")],
        [InlineKeyboardButton("🕒 SPL", callback_data="rekap_spl")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("mo minta rekapan apa bro?", reply_markup=reply_markup)
    
async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("❌ Hanya admin yang bisa pakai perintah ini.")
        return

    if not context.args:
        await update.message.reply_text("Gunakan format: /broadcast <isi pesan>")
        return

    pesan_raw = " ".join(context.args)
    pesan = format_broadcast_message(pesan_raw)

    keyboard = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton("📝 Balas Pesan Ini", callback_data="reply_broadcast")
    )

    semua_user = list(PENGGUNA.keys())
    sukses, gagal = [], []

    await update.message.reply_text(f"📡 Mengirim broadcast ke {len(semua_user)} pengguna...")

    for uid in semua_user:
        try:
            await bot.send_message(
                chat_id=uid,
                text=pesan,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            sukses.append(uid)
        except Exception as e:
            logging.warning(f"[Broadcast] Gagal kirim ke {uid}: {e}")
            gagal.append(uid)

    ringkasan = (
        f"<b>📢 Broadcast Selesai</b>\n\n"
        f"✅ Terkirim: {len(sukses)}\n"
        f"❌ Gagal: {len(gagal)}"
    )
    await bot.send_message(chat_id=ADMIN_ID, text=ringkasan, parse_mode=ParseMode.HTML)
    
async def reply_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    alias = PENGGUNA.get(user_id, {}).get("alias", str(user_id))

    await query.answer()
    await query.message.reply_text("📝 Silakan kirim balasan Anda sekarang.")
    
    state_broadcast.add(user_id)
    await bot.send_message(ADMIN_ID, f"📨 {alias} menekan tombol Balas Broadcast.")
    
async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    if user_id not in state_broadcast:
        return

    alias = PENGGUNA.get(user_id, {}).get("alias", str(user_id))

    try:
        if update.message.text:
            await bot.send_message(
                ADMIN_ID,
                f"📨 <b>{alias}</b> membalas broadcast:\n\n{update.message.text}",
                parse_mode=ParseMode.HTML
            )
        else:
            await bot.forward_message(ADMIN_ID, user_id, update.message.message_id)

        await update.message.reply_text("✅ Terima kasih atas balasannya!")
    except Exception as e:
        logging.error(f"[REPLY] Gagal forward dari {user_id}: {e}")

    state_broadcast.discard(user_id)

async def tanya_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    if user_id not in PENGGUNA:
        await update.message.reply_text("❌ Anda belum terdaftar.")
        return

    if not context.args:
        await update.message.reply_text("Gunakan format: /tanya_admin <pertanyaan Anda>")
        return

    alias = PENGGUNA[user_id]["alias"]
    pertanyaan = " ".join(context.args)

    await update.message.reply_text("✅ Pertanyaan Anda sudah dikirim ke admin.")

    pesan_admin = (
        f"🆘 <b>Pesan dari {alias}</b>\n"
        f"<b>Chat ID:</b> <code>{user_id}</code>\n\n"
        f"{pertanyaan}"
    )
    await bot.send_message(chat_id=ADMIN_ID, text=pesan_admin, parse_mode=ParseMode.HTML)


# ======= [FUNGSI OTOMATIS] =======
async def kirim_rekap_ke_semua():
    if not sudah_memulai(chat_id):
        return
    logging.debug(f"[kirim_rekap_ke_semua] mengirim rekap absensi ke semua")
    waktu_skrg = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
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
        logging.warning(f"⚠️ Gagal kirim rekap ke admin: {e}")

# 1. CEK ABSEN MASUK
async def cek_absen_masuk():
    if not sudah_memulai(chat_id):
        return
    now = datetime.now(WITA)
    if now.weekday() == 6 or is_libur_nasional(now): 
        return
    status = reset_status_harian()
    today = now.strftime("%d %B %Y")
    tasks = []

    for cid, acc in PENGGUNA.items():
        key = str(cid)
        if status.get(key, {}).get("masuk"): 
            continue

        async def _task(cid=cid, acc=acc, key=key):
            try:
                data = await ambil_rekapan_absen_awal_bulan_async(acc["username"], cid)
                for item in data:
                    if item["Tanggal"] == today and item["In"] not in ["-", "00.00"]:
                        jam_in = item["In"].replace(".", ":")
                        await kirim_pesan_aman(cid, f"✅ Masuk terdeteksi (In: {jam_in})")
                        await kirim_pesan_aman(ADMIN_ID, f"👤 {acc['julukan']} ✅ Masuk: {jam_in}")
                        status.setdefault(key, {})["masuk"] = True
                        break
            except Exception as e:
                logging.warning(f"[Masuk] {acc['alias']}: {e}")

        tasks.append(_task())

    if tasks:
        await asyncio.gather(*tasks)
        _save_status(status)

# 2. CEK LUPA MASUK
async def cek_lupa_masuk():
    if not sudah_memulai(chat_id):
        return
    if datetime.now(WITA).weekday() == 6 or is_libur_nasional(datetime.now(WITA)): 
        return
    status = _load_status()
    sudah, belum = [], []

    async def _task(cid, acc):
        key = str(cid)
        if status.get(key, {}).get("masuk"): sudah.append(acc["alias"])
        else:
            belum.append(acc["alias"])
            await kirim_pesan_aman(cid, "ngana lupa absen maso bro❗❗❗")

    await asyncio.gather(*[_task(cid, acc) for cid, acc in PENGGUNA.items()])
    await tutup_semua_session_otomatis()
    _save_status(status)

    summary = (
        "📋 <b>Ringkasan Lupa Absen Masuk:</b>\n\n"
        f"✅ <b>Sudah:</b>\n{chr(10).join(sudah) or 'Tidak ada'}\n\n"
        f"❌ <b>Belum:</b>\n{chr(10).join(belum) or 'Tidak ada'}"
    )
    await bot.send_message(chat_id=ADMIN_ID, text=summary, parse_mode=ParseMode.HTML)

# 3. CEK ABSEN PULANG
async def cek_absen_pulang():
    if not sudah_memulai(chat_id):
        return
    if datetime.now(WITA).weekday() == 6 or is_libur_nasional(datetime.now(WITA)): 
        return
    status = _load_status()
    today = datetime.now(WITA).strftime("%d %B %Y")
    tasks = []

    for cid, acc in PENGGUNA.items():
        key = str(cid)
        if status.get(key, {}).get("pulang"): 
            continue

        async def _task(cid=cid, acc=acc, key=key):
            try:
                data = await ambil_rekapan_absen_awal_bulan_async(acc["username"], cid)
                for item in data:
                    if item["Tanggal"] == today and item["Out"] not in ["-", "00.00"]:
                        jam_out = item["Out"].replace(".", ":")
                        await kirim_pesan_aman(cid, f"✅ Pulang terdeteksi (Out: {jam_out})")
                        await kirim_pesan_aman(ADMIN_ID, f"👤 {acc['julukan']} ✅ Pulang: {jam_out}")
                        status.setdefault(key, {})["pulang"] = True
                        break
            except Exception as e:
                logging.warning(f"[Pulang] {acc['alias']}: {e}")

        tasks.append(_task())

    if tasks:
        await asyncio.gather(*tasks)
        _save_status(status)

# 4. CEK LUPA PULANG
async def cek_lupa_pulang():
    if not sudah_memulai(chat_id):
        return
    if datetime.now(WITA).weekday() == 6 or is_libur_nasional(datetime.now(WITA)): 
        return
    status = _load_status()
    sudah, belum, mangkir = [], [], []

    async def _task(cid, acc):
        key = str(cid)
        masuk = status.get(key, {}).get("masuk", False)
        pulang = status.get(key, {}).get("pulang", False)
        alias = acc["alias"]
        julukan = acc["julukan"]

        if pulang:
            sudah.append(alias)
        elif not masuk:
            mangkir.append(alias)
            await kirim_pesan_aman(cid, "⚠️ Ngana mangkir atau SKD ini bro 😂")
            await bot.send_message(ADMIN_ID, f"👤 {julukan} mangkir bro. Nda absen masuk & pulang")
        else:
            belum.append(alias)
            await kirim_pesan_aman(cid, "❗Ngana lupa absen pulang bro❗")

    await asyncio.gather(*[_task(cid, acc) for cid, acc in PENGGUNA.items()])
    _save_status(status)

    summary = (
        "📋 <b>Ringkasan Lupa Absen Pulang:</b>\n\n"
        f"✅ <b>Sudah:</b>\n{chr(10).join(sudah) or 'Tidak ada'}\n\n"
        f"❌ <b>Belum:</b>\n{chr(10).join(belum) or 'Tidak ada'}\n\n"
        f"⚠️ <b>Mangkir:</b>\n{chr(10).join(mangkir) or 'Tidak ada'}"
    )
    await bot.send_message(chat_id=ADMIN_ID, text=summary, parse_mode=ParseMode.HTML)

# 5. PENGINGAT ESS
async def pengingat():
    if not sudah_memulai(chat_id):
        return
    if datetime.now(WITA).weekday() == 6 or is_libur_nasional(datetime.now(WITA)): 
        return
    today = datetime.now(WITA).strftime("%d %B %Y")
    tasks = []

    async def _task(cid, acc):
        try:
            data = await ambil_rekapan_absen_awal_bulan_async(acc["username"], cid)
            for item in data:
                if item["Tanggal"] == today:
                    if item["Status"].lower() in ["mangkir", "terlambat", "lupa absen waktu pulang"]:
                        await kirim_pesan_aman(
                            cid,
                            f"<b>{item['Tanggal']} - {item['Status']}</b>\nJangan lupa input ESS Bro ❗❗❗\n<a href='https://portal.hrindomaret.com/'>🔗 Klik ke ESS</a>",
                            parse_mode=ParseMode.HTML
                        )
                    break
        except Exception as e:
            logging.warning(f"[ESS Reminder] {acc['alias']}: {e}")

    for cid, acc in PENGGUNA.items():
        tasks.append(_task(cid, acc))
    await asyncio.gather(*tasks)
    
async def tutup_semua_session_otomatis():
    closed = 0
    for uid, (session, _) in SESSION_CACHE.items():
        if not session.closed:
            await session.close()
            closed += 1
    SESSION_CACHE.clear()
    
    logging.warning(f"[Auto Close] Ditutup otomatis {closed} session.")
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=f"🧹 Otomatis ditutup {closed} session.")
    except:
        pass

async def kirim_overtime_ke_semua():
    if not sudah_memulai(chat_id):
        return
    logging.debug("[SPL] Mengirimkan rekap overtime ke semua pengguna...")
    now = datetime.now(WITA)
    pengguna_dengan_spl = []

    for cid, akun in PENGGUNA.items():
        username = akun["username"]
        alias = akun["alias"]
        try:
            data = await ambil_rekapan_absen_awal_bulan_async(username, cid)
            total = 0.0
            overtime_data = []

            for item in data:
                overtime = item.get("Overtime", "-")
                if overtime != "-" and "jam" in overtime:
                    try:
                        jam = float(overtime.split()[0].replace(",", "."))
                        if jam > 0:
                            total += jam
                            overtime_data.append(f"📅 {item['Tanggal']} — {jam:.2f} jam")
                    except:
                        continue

            if overtime_data:
                # ===== HEADER =====
                overtime_title = "selamat hari minggu bro 😊"
                word_title = "kira-kira bagini ente pe SPL"
                name_line = f"👨‍💼 {alias}"
                width = max(len(overtime_title), len(word_title), len(name_line))
                pad = " " * max((40 - width) // 2, 0)

                header = (
                    f"<pre>{pad}{overtime_title}\n"
                    f"{pad}{word_title}\n"
                    f"{pad}{name_line}</pre>\n\n"
                )
                isi = "\n".join(overtime_data)
                footer = f"\n\n<b>📊 Total Overtime:</b> {total:.2f} jam"

                pesan = header + isi + footer
                
                pengguna_dengan_spl.append(f"{alias}: {total:.2f} jam")

                # kirim ke user
                await kirim_pesan_aman(chat_id=cid, text=pesan, parse_mode=ParseMode.HTML)
            else:
                pesan = (
                    f"👋 <b>Selamat hari Minggu, {alias}</b>\n\n"
                    f"Belum ada data SPL bulan ini. 💤"
                )
                await kirim_pesan_aman(chat_id=cid, text=pesan, parse_mode=ParseMode.HTML)

        except Exception as e:
            logging.warning(f"[SPL] Gagal kirim ke {alias}: {e}")
    
    if pengguna_dengan_spl:
        pengguna_dengan_spl.sort()
        ringkasan = "📋 <b>Ringkasan SPL:</b>\n\n"
        ringkasan += "\n".join(pengguna_dengan_spl)

        try:
            await bot.send_message(chat_id=ADMIN_ID, text=ringkasan, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.warning(f"[SPL] Gagal kirim ringkasan ke admin: {e}")
      
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    started = load_started_users()
    if chat_id in started:
        return

    alias = PENGGUNA.get(chat_id, {}).get("alias", "Pengguna")
    started.add(chat_id)
    save_started_users(started)

    await update.message.reply_text(
        f"👋 Selamat datang, {alias}!\nBot sudah aktif untuk kamu.\nGunakan /rekap untuk melihat absensi."
    )
    await bot.send_message(ADMIN_ID, f"🆕 Pengguna baru /start: {chat_id} - {alias}")
            
async def on_startup(app):
    await fetch_libur_nasional()
    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(timezone=WITA)
    logging.debug("[Scheduler] Menjadwalkan tugas-tugas cek absen dan notifikasi...")
    
    # Tugas ping
    scheduler.add_job(
        conditional_ping,
        CronTrigger(minute='*/30', timezone=WITA)
    )
    # Tugas kirim rekap otomatis
    scheduler.add_job(kirim_rekap_ke_semua, CronTrigger(hour=6, minute=0, timezone=WITA))
    scheduler.add_job(
        kirim_overtime_ke_semua,
        CronTrigger(day_of_week="sun", hour=7, minute=0, timezone=WITA)
    )
    # Tugas cek absensi
    # Loop cek masuk
    scheduler.add_job(
        cek_absen_masuk,
        CronTrigger(minute='*/1', hour='7-9', timezone=WITA)
    )
    # Notifikasi lupa masuk
    scheduler.add_job(
        cek_lupa_masuk,
        CronTrigger(hour=10, minute=0, timezone=WITA)
    )
    # Loop cek pulang
    scheduler.add_job(
        cek_absen_pulang,
        CronTrigger(minute='*/1', hour='17-19', timezone=WITA)
    )
    # Notifikasi lupa pulang
    scheduler.add_job(
        cek_lupa_pulang,
        CronTrigger(hour=20, minute=0, timezone=WITA)
    )
    # Notifikasi Pengingat
    scheduler.add_job(
        pengingat,
        CronTrigger(hour=21, minute=0, timezone=WITA) 
    )
    # Membersihkan session
    scheduler.add_job(
        tutup_semua_session_otomatis,
        CronTrigger(hour=22, minute=0, timezone=WITA)
    )
    
    scheduler.add_job(
        fetch_libur_nasional,
        CronTrigger(day_of_week="sun", hour=6, minute=30, timezone=WITA)
    )

    scheduler.start()
    logging.debug("[Scheduler] Semua tugas dijalankan.")

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
        level=logging.WARNING,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("log_absen.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    async def startup_and_run():
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("rekap", rekap))
        app.add_handler(CallbackQueryHandler(rekap_absen, pattern="^rekap_absen$"))
        app.add_handler(CallbackQueryHandler(rekap_spl, pattern="^rekap_spl$"))
        app.add_handler(CommandHandler("semua", semua))
        app.add_handler(CommandHandler("broadcast", broadcast_handler))
        app.add_handler(CallbackQueryHandler(reply_broadcast_handler, pattern="^reply_broadcast$"))
        app.add_handler(MessageHandler(filters.TEXT, handle_reply))
        app.add_handler(CommandHandler("tanya_admin", tanya_admin))

        await app.initialize()
        await app.start()

        webhook_endpoint = f"/webhook/{BOT_TOKEN}"
        full_webhook_url = f"{WEBHOOK_URL}{webhook_endpoint}"
        await app.bot.set_webhook(full_webhook_url)
        logging.debug(f"✅ Webhook active at: {full_webhook_url}")
        
        await on_startup(app)

        web_app = web.Application()
        web_app['bot_app'] = app
        web_app.router.add_post("/webhook/{token}", telegram_webhook)
        web_app.router.add_get("/ping", ping_handler)

        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()

        print(f"🌐 Server running on port {PORT}")

        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await tutup_semua_session_otomatis()
            await app.shutdown()
            await app.stop()

    asyncio.run(startup_and_run())
