# check_domains.py
# UPDATED VERSION — trustpositif.infonawala.com (DEBUG MODE v3)
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

    # Klik SEMUA tombol metrics/checkbox yang ada (Kominfo, SSL, DNS, WHOIS, dll)
    print("[3] Mengklik semua tombol metrics...", flush=True)
    metric_buttons = driver.find_elements(
        By.XPATH, "//div[contains(@class,'grid')]//button"
    )
    print(f"    Tombol metrics ditemukan: {len(metric_buttons)}", flush=True)
    for i, mb in enumerate(metric_buttons):
        try:
            label = mb.text.strip()
            print(f"    Klik metrics[{i}]: '{label}'", flush=True)
            driver.execute_script("arguments[0].click();", mb)
            sleep(0.3)
        except Exception as e:
            print(f"    Gagal klik metrics[{i}]: {e}", flush=True)

    sleep(1)

    # Isi textarea domain
    textareas = driver.find_elements(By.TAG_NAME, "textarea")
    if not textareas:
        raise RuntimeError("Textarea tidak ditemukan")
    print(f"[4] Mengisi {len(domains)} domain...", flush=True)
    textareas[0].clear()
    textareas[0].send_keys("\n".join(domains))
    sleep(0.5)

    # Klik tombol Check Domains
    btn = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(., 'Check') or contains(., 'Cek')]")
        )
    )
    print(f"[5] Klik tombol: '{btn.text.strip()}'", flush=True)
    driver.execute_script("arguments[0].click();", btn)

    # Tunggu hasil muncul — cari div/element yang mengandung nama domain
    print("[6] Menunggu hasil muncul (max 60 detik)...", flush=True)
    first_domain = domains[0].lower()

    def result_appeared(d):
        body = d.find_element(By.TAG_NAME, "body").get_attribute("innerHTML").lower()
        # Cari indikator hasil: domain muncul di luar textarea + ada kata status
        count = body.count(first_domain)
        return count >= 2  # muncul minimal 2x (textarea + hasil)

    try:
        WebDriverWait(driver, 60).until(result_appeared)
        print("[7] Hasil terdeteksi!", flush=True)
    except TimeoutException:
        print("[7] Timeout menunggu hasil, lanjut dump HTML...", flush=True)

    # Dump HTML untuk analisis
    body_html = driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
    idx = body_html.lower().find(first_domain)
    # Cari kemunculan ke-2
    idx2 = body_html.lower().find(first_domain, idx + 1) if idx >= 0 else -1

    if idx2 >= 0:
        snippet = body_html[max(0, idx2-300):idx2+600]
        print(f"[8] HTML hasil di sekitar domain '{first_domain}':\n{snippet}", flush=True)
    else:
        print(f"[8] Hasil tidak ditemukan. Body HTML (2000 char terakhir):\n{body_html[-2000:]}", flush=True)

    return {}


# ================= MAIN =================
def main():
    print("=== Nawala Checker DEBUG v3 START ===", flush=True)
    domains = load_domains()
    print(f"Domain: {domains}", flush=True)

    if not domains:
        send_telegram("Tidak ada domain untuk dicek.")
        return

    driver = setup_driver()
    try:
        for batch in chunk(domains, 3):
            check_batch(driver, batch)
            break
    except Exception as e:
        msg = f"❌ Error: {type(e).__name__} - {e}"
        print(msg, flush=True)
        send_telegram(msg)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    print("=== DEBUG v3 SELESAI ===", flush=True)
    send_telegram("Debug v3 selesai, cek Railway Deploy Logs.")


if __name__ == "__main__":
    main()
