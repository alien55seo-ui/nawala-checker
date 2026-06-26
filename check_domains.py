# check_domains.py
# UPDATED VERSION — trustpositif.infonawala.com (DEBUG MODE)
# Env:
#   TELEGRAM_TOKEN
#   TELEGRAM_CHAT_ID
#   DOMAINS_TO_CHECK   (pisah koma atau enter)
# Optional:
#   TARGET_URL (default https://trustpositif.infonawala.com/)

import os
import requests
from time import sleep
from typing import Dict, List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")
TARGET_URL = os.environ.get("TARGET_URL", "https://trustpositif.infonawala.com/")


# ================= TELEGRAM =================
def send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram env belum di-set", flush=True)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }

    try:
        requests.post(url, json=payload, timeout=25)
    except Exception as e:
        print("Gagal kirim Telegram:", e, flush=True)


# ================= DOMAIN =================
def load_domains() -> List[str]:
    raw = (DOMAINS_ENV or "").strip()
    if not raw:
        return []

    raw = raw.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",") if p.strip()]

    out = []
    for d in parts:
        x = d.replace("https://", "").replace("http://", "").strip().strip("/")
        if x:
            out.append(x.lower())
    return out


def chunk(lst: List[str], n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def normalize_status(raw: str) -> Tuple[str, str]:
    t = (raw or "").lower()

    if "aman" in t or "not blocked" in t or "clean" in t:
        return "🟢", "Not Blocked"
    if "terblokir" in t or "blocked" in t or "blokir" in t:
        return "🔴", "Blocked"
    if "error" in t:
        return "🟠", "Error"

    return "⚪", "Unknown"


# ================= SELENIUM =================
def setup_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--lang=id-ID")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
    )

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(90)
    return driver


def check_batch(driver, domains: List[str]) -> Dict[str, str]:
    wait = WebDriverWait(driver, 60)

    print(f"[1] Membuka URL: {TARGET_URL}", flush=True)
    driver.get(TARGET_URL)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    print(f"[2] Halaman berhasil dimuat. Title: {driver.title}", flush=True)

    # Debug: cetak semua tombol yang ada
    buttons = driver.find_elements(By.TAG_NAME, "button")
    print(f"[3] Jumlah tombol ditemukan: {len(buttons)}", flush=True)
    for i, b in enumerate(buttons):
        print(f"    Tombol[{i}]: '{b.text.strip()}' | class='{b.get_attribute('class')}'", flush=True)

    # Debug: cetak semua textarea
    textareas = driver.find_elements(By.TAG_NAME, "textarea")
    print(f"[4] Jumlah textarea ditemukan: {len(textareas)}", flush=True)
    for i, t in enumerate(textareas):
        print(f"    Textarea[{i}]: placeholder='{t.get_attribute('placeholder')}'", flush=True)

    # Debug: cetak semua checkbox
    checkboxes = driver.find_elements(By.XPATH, "//input[@type='checkbox']")
    print(f"[5] Jumlah checkbox ditemukan: {len(checkboxes)}", flush=True)

    if not textareas:
        raise RuntimeError("Textarea tidak ditemukan di halaman")

    # Aktifkan checkbox pertama (Kominfo) jika belum aktif
    if checkboxes and not checkboxes[0].is_selected():
        print("[6] Klik checkbox Kominfo...", flush=True)
        driver.execute_script("arguments[0].click();", checkboxes[0])
        sleep(0.5)

    # Isi textarea
    print(f"[7] Mengisi {len(domains)} domain ke textarea...", flush=True)
    textareas[0].clear()
    textareas[0].send_keys("\n".join(domains))

    # Klik tombol submit
    print("[8] Mencari tombol submit...", flush=True)
    btn = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(., 'Check') or contains(., 'Cek')]")
        )
    )
    print(f"[9] Klik tombol: '{btn.text.strip()}'", flush=True)
    driver.execute_script("arguments[0].click();", btn)

    # Tunggu hasil tabel
    print("[10] Menunggu tabel hasil...", flush=True)
    WebDriverWait(driver, 120).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, "table tbody tr")) > 0
    )

    # Parse tabel
    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    print(f"[11] Tabel ditemukan: {len(rows)} baris", flush=True)

    # Debug: cetak isi baris pertama
    if rows:
        tds = rows[0].find_elements(By.TAG_NAME, "td")
        print(f"[12] Kolom di baris pertama: {len(tds)}", flush=True)
        for i, td in enumerate(tds):
            print(f"     td[{i}]: '{td.text.strip()}'", flush=True)

    out = {}
    for row in rows:
        tds = row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 3:
            domain = tds[1].text.strip().lower()
            status = tds[2].text.strip()
            if domain:
                out[domain] = status

    return out


# ================= MAIN =================
def main():
    print("=== Nawala Checker START ===", flush=True)

    domains = load_domains()
    print(f"Domain dimuat: {len(domains)}", flush=True)

    if not domains:
        send_telegram("Tidak ada domain untuk dicek.")
        return

    driver = setup_driver()
    print("Driver Selenium siap.", flush=True)
    results = {}

    try:
        for batch in chunk(domains, 100):
            res = check_batch(driver, batch)
            results.update(res)
            sleep(1.2)

    except TimeoutException as e:
        msg = f"❌ Timeout saat cek trustpositif.infonawala.com\n{e}"
        print(msg, flush=True)
        send_telegram(msg)
        return
    except Exception as e:
        msg = f"❌ Error: {type(e).__name__} - {e}"
        print(msg, flush=True)
        send_telegram(msg)
        return
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    lines = ["Domain Status Report (trustpositif.infonawala.com)"]
    for d in domains:
        raw = results.get(d, "")
        emoji, label = normalize_status(raw)
        lines.append(f"{d}: {emoji} {label}")

    send_telegram("\n".join(lines))
    print("=== Nawala Checker DONE ===", flush=True)


if __name__ == "__main__":
    main()
