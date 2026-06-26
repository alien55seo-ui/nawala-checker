# check_domains.py
# UPDATED VERSION — trustpositif.infonawala.com
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
    driver.set_page_load_timeout(90)  # naik dari 60
    return driver


def find_textarea(wait):
    tas = wait.until(lambda d: d.find_elements(By.TAG_NAME, "textarea"))
    if not tas:
        raise RuntimeError("Textarea tidak ditemukan")
    return tas[0]


def click_submit(wait, driver):
    # website baru tombolnya "Check Domains"
    btn = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(., 'Check') or contains(., 'Cek')]")
        )
    )
    driver.execute_script("arguments[0].click();", btn)


def wait_results(wait):
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "table tbody tr")) > 0)


def parse_table(driver) -> Dict[str, str]:
    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    out = {}

    for row in rows:
        tds = row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 3:
            domain = tds[1].text.strip().lower()
            status = tds[2].text.strip()
            if domain:
                out[domain] = status

    return out


def check_batch(driver, domains: List[str]) -> Dict[str, str]:
    wait = WebDriverWait(driver, 60)  # naik dari 45

    driver.get(TARGET_URL)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    # pastikan checkbox Kominfo/Status Nawala aktif
    try:
        checkboxes = driver.find_elements(By.XPATH, "//input[@type='checkbox']")
        if checkboxes and not checkboxes[0].is_selected():
            driver.execute_script("arguments[0].click();", checkboxes[0])
            sleep(0.5)
    except Exception:
        pass

    textarea = find_textarea(wait)
    textarea.clear()
    textarea.send_keys("\n".join(domains))

    click_submit(wait, driver)
    wait_results(WebDriverWait(driver, 120))  # naik dari 80

    return parse_table(driver)


# ================= MAIN =================
def main():
    domains = load_domains()
    if not domains:
        send_telegram("Tidak ada domain untuk dicek.")
        return

    driver = setup_driver()
    results = {}

    try:
        for batch in chunk(domains, 100):
            res = check_batch(driver, batch)
            results.update(res)
            sleep(1.2)

    except TimeoutException:
        send_telegram("❌ Timeout saat cek trustpositif.infonawala.com")
        return
    except Exception as e:
        send_telegram(f"❌ Error: {type(e).__name__} - {e}")
        return
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # Susun laporan final
    lines = ["Domain Status Report (trustpositif.infonawala.com)"]

    for d in domains:
        raw = results.get(d, "")
        emoji, label = normalize_status(raw)
        lines.append(f"{d}: {emoji} {label}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
