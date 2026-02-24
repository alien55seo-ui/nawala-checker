# check_domains.py
# FINAL — trustpositif.cc (Selenium)
# Env:
#   TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DOMAINS_TO_CHECK
# Optional:
#   TARGET_URL (default https://trustpositif.cc/)
#
# DOMAINS_TO_CHECK format: dipisah koma atau enter
# contoh: pk95anomali.space, rtpbetx400.store, boxing55d.pro

import os
import re
import requests
from time import sleep
from typing import Dict, List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

VERSION = "trustpositif-cc-final-v1"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")

TARGET_URL = os.environ.get("TARGET_URL", "https://trustpositif.cc/").strip() or "https://trustpositif.cc/"


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
        r = requests.post(url, json=payload, timeout=25)
        print("Telegram resp:", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("Gagal kirim Telegram:", e, flush=True)


# ================= DOMAIN HELPERS =================
def load_domains() -> List[str]:
    raw = (DOMAINS_ENV or "").strip()
    if not raw:
        return []
    raw = raw.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",") if p.strip()]

    out: List[str] = []
    for d in parts:
        x = d.strip()
        x = x.replace("https://", "").replace("http://", "")
        x = x.strip().strip("/")
        if x:
            out.append(x)
    return out


def chunk(lst: List[str], n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def normalize_status(raw_status: str) -> Tuple[str, str]:
    """
    trustpositif.cc status di tabel: "Aman", "Terblokir", bisa juga "Error"
    """
    t = (raw_status or "").strip().lower()

    if not t:
        return "⚪", "Unknown"

    if "aman" in t or "not blocked" in t:
        return "🟢", "Not Blocked"

    if "terblokir" in t or "blocked" in t or "nawala" in t:
        return "🔴", "Blocked"

    if "error" in t or "gagal" in t:
        return "🟠", "Error"

    return "⚪", raw_status.strip()


# ================= SELENIUM =================
def setup_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--lang=id-ID")

    # UA "normal" biar lebih aman
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
    )

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    return driver


def find_textarea(wait: WebDriverWait):
    # Dari screenshot: textarea besar di tengah (biasanya cuma satu).
    # Kita cari yang paling besar/utama.
    tas = wait.until(lambda d: d.find_elements(By.TAG_NAME, "textarea"))
    if not tas:
        raise RuntimeError("Textarea input domain tidak ditemukan")
    # pilih textarea pertama (umumnya benar)
    return tas[0]


def click_submit(wait: WebDriverWait, driver: webdriver.Chrome):
    # Tombol di UI: "Cek Sekarang - Gratis!" atau sejenis.
    # Kita cari button yang mengandung kata "Cek" atau "Gratis" atau "Sekarang".
    xpaths = [
        "//button[contains(., 'Cek Sekarang')]",
        "//button[contains(., 'Cek')]",
        "//button[contains(., 'Gratis')]",
    ]
    for xp in xpaths:
        try:
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, xp)))
            driver.execute_script("arguments[0].click();", btn)
            return
        except Exception:
            pass
    raise RuntimeError("Tombol submit (Cek Sekarang) tidak ditemukan")


def wait_results_table(wait: WebDriverWait):
    # Setelah submit, akan muncul tabel hasil (kolom: No, Domain, Status, dst)
    # Cari tbody tr minimal 1 row
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "table tbody tr")) > 0)


def parse_table(driver: webdriver.Chrome) -> Dict[str, str]:
    """
    Return: dict domain_lower -> status_raw_text
    """
    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    out: Dict[str, str] = {}

    for row in rows:
        tds = row.find_elements(By.TAG_NAME, "td")
        # biasanya: [No, Domain, Status, Waktu Cek, Kecepatan]
        if len(tds) < 3:
            continue

        domain = tds[1].text.strip().lower()
        status = tds[2].text.strip()

        if domain:
            out[domain] = status

    return out


def check_batch(driver: webdriver.Chrome, domains: List[str]) -> Dict[str, str]:
    wait = WebDriverWait(driver, 45)
    driver.get(TARGET_URL)

    # pastikan body siap
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    textarea = find_textarea(wait)
    textarea.clear()
    textarea.send_keys("\n".join(domains))

    click_submit(wait, driver)

    # tunggu hasil
    wait_results_table(WebDriverWait(driver, 80))

    # parse tabel
    return parse_table(driver)


# ================= MAIN =================
def main():
    send_telegram(f"✅ RUNNING TRUSTPOSITIF.CC VERSION [{VERSION}]")

    domains = load_domains()
    if not domains:
        send_telegram(f"Domain Status Report (trustpositif.cc) [{VERSION}]\nTidak ada domain untuk dicek.")
        return

    # UI menunjukkan max 100 domain
    batches = list(chunk(domains, 100))

    driver = setup_driver()
    all_results: Dict[str, str] = {}

    try:
        for i, batch in enumerate(batches, start=1):
            print(f"Checking batch {i}/{len(batches)}: {len(batch)} domains", flush=True)
            res = check_batch(driver, batch)
            all_results.update(res)

            # jeda kecil biar stabil
            sleep(1.5)

    except TimeoutException:
        msg = (
            f"❌ Timeout (trustpositif.cc) [{VERSION}]\n"
            f"URL: {driver.current_url}\n"
            f"Title: {driver.title}"
        )
        print(msg, flush=True)
        send_telegram(msg)
        return

    except Exception as e:
        msg = (
            f"❌ Error (trustpositif.cc) [{VERSION}]\n"
            f"{type(e).__name__}: {e}\n"
            f"URL: {driver.current_url}\n"
            f"Title: {driver.title}"
        )
        print(msg, flush=True)
        send_telegram(msg)
        return

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # Susun laporan (tanpa “keterangan” tambahan)
    lines = [f"Domain Status Report (trustpositif.cc) [{VERSION}]"]

    for d in domains:
        key = d.lower()
        raw_status = all_results.get(key, "")
        emoji, label = normalize_status(raw_status)
        lines.append(f"{key}: {emoji} {label}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
