# check_domains.py
# UPDATED VERSION — trustpositif.infonawala.com (DEBUG MODE v2)
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
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True}
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
    print(f"[2] Halaman dimuat. Title: {driver.title}", flush=True)

    textareas = driver.find_elements(By.TAG_NAME, "textarea")
    if not textareas:
        raise RuntimeError("Textarea tidak ditemukan")

    print(f"[3] Mengisi {len(domains)} domain...", flush=True)
    textareas[0].clear()
    textareas[0].send_keys("\n".join(domains))

    btn = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(., 'Check') or contains(., 'Cek')]")
        )
    )
    print(f"[4] Klik tombol: '{btn.text.strip()}'", flush=True)
    driver.execute_script("arguments[0].click();", btn)

    # Tunggu 15 detik agar hasil render
    print("[5] Menunggu 15 detik setelah klik...", flush=True)
    sleep(15)

    # Debug: cari semua elemen yang mungkin jadi container hasil
    print("[6] Mencari container hasil...", flush=True)

    # Cek table
    tables = driver.find_elements(By.TAG_NAME, "table")
    print(f"    <table> ditemukan: {len(tables)}", flush=True)

    # Cek div dengan kata kunci hasil
    for kw in ["result", "hasil", "domain", "status", "check"]:
        els = driver.find_elements(By.XPATH, f"//*[contains(@class, '{kw}') or contains(@id, '{kw}')]")
        if els:
            print(f"    Elemen dengan '{kw}': {len(els)} | contoh tag={els[0].tag_name} class='{els[0].get_attribute('class')}'", flush=True)

    # Cek semua <tr>
    trs = driver.find_elements(By.TAG_NAME, "tr")
    print(f"    <tr> ditemukan: {len(trs)}", flush=True)

    # Cek semua <li>
    lis = driver.find_elements(By.TAG_NAME, "li")
    print(f"    <li> ditemukan: {len(lis)}", flush=True)

    # Dump sebagian HTML body (500 char pertama setelah klik)
    body_html = driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
    # Cari bagian yang relevan — cari domain pertama dalam HTML
    first_domain = domains[0] if domains else ""
    idx = body_html.lower().find(first_domain.lower())
    if idx >= 0:
        snippet = body_html[max(0, idx-200):idx+500]
        print(f"[7] HTML di sekitar domain '{first_domain}':\n{snippet}", flush=True)
    else:
        print(f"[7] Domain '{first_domain}' tidak ditemukan dalam HTML!", flush=True)
        # Dump 1000 char pertama body
        print(f"    Body HTML (1000 char pertama):\n{body_html[:1000]}", flush=True)

    return {}


# ================= MAIN =================
def main():
    print("=== Nawala Checker DEBUG v2 START ===", flush=True)
    domains = load_domains()
    print(f"Domain: {domains}", flush=True)

    if not domains:
        send_telegram("Tidak ada domain untuk dicek.")
        return

    driver = setup_driver()
    try:
        for batch in chunk(domains, 5):  # batch kecil untuk debug
            check_batch(driver, batch)
            break  # hanya 1 batch untuk debug
    except Exception as e:
        msg = f"❌ Error: {type(e).__name__} - {e}"
        print(msg, flush=True)
        send_telegram(msg)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    print("=== DEBUG SELESAI — cek Deploy Logs ===", flush=True)
    send_telegram("Debug selesai, cek Railway Deploy Logs untuk lihat struktur HTML hasil.")


if __name__ == "__main__":
    main()
