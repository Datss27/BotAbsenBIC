import aiohttp
from datetime import datetime
import logging

# Cache global untuk menyimpan tanggal libur
LIBUR_CACHE = set()

async def fetch_libur_nasional():
    """
    Mengambil data libur nasional dari API gratis
    dan menyimpannya di LIBUR_CACHE (format: YYYY-MM-DD).
    """
    url = "https://api-harilibur.vercel.app/api"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    LIBUR_CACHE.clear()
                    for item in data:
                        tanggal = item.get("holiday_date")
                        if tanggal:
                            LIBUR_CACHE.add(tanggal)
                    logging.info(f"[LIBUR] {len(LIBUR_CACHE)} tanggal libur dimuat.")
                else:
                    logging.warning(f"[LIBUR] Gagal ambil data, status {resp.status}")
    except Exception as e:
        logging.error(f"[LIBUR] Exception saat fetch: {e}")

def is_libur_nasional(hari_ini=None):
    """
    Mengecek apakah hari_ini adalah hari libur nasional berdasarkan LIBUR_CACHE.
    """
    if not hari_ini:
        hari_ini = datetime.now()
    return hari_ini.strftime("%Y-%m-%d") in LIBUR_CACHE
