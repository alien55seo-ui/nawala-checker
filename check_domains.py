import os
import requests

from time import sleep
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")

TARGET_URL = "https://www.ninjamvp.asia/"


def send_telegram(text: str):
    """Kirim pesan ke Telegram (plain text)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram env belum di-set")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        print("Telegram resp:", resp.status_code, resp.text[:200])
    except Exception as e:
        print("Gagal kirim ke Telegram:", e)


def setup_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,720")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver


def load_domains():
    if not DOMAINS_ENV:
        print("DOMAINS_TO_CHECK kosong.", flush=True)
        return []

    raw = DOMAINS_ENV.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",")]
    domains = [p for p in parts if p]
    print("Loaded domains:", domains, flush=True)
    return domains


def normalize_status(status_text: str):
    t = (status_text or "").strip().lower()

    if not t:
        return "⚪", "Unknown"

    if "aman" in t or "tidak terblokir" in t or "not blocked" in t:
        return "🟢", "Not Blocked"

    if "nawala" in t or "terblokir" in t or "blocked" in t:
        return "🔴", "Blocked"

    return "⚪", (status_text or "").strip() or "Unknown"


def check_domains_ninjamvp(driver, domains):
    """
    Return: dict domain_lower -> status_text
    (kolom keterangan sengaja diabaikan)
    """
    driver.get(TARGET_URL)

    WebDriverWait(driver, 30).until(
        lambda d: d.find_element(By.TAG_NAME, "body")
    )

    textarea = driver.find_element(By.CSS_SELECTOR, "textarea#domainsInput")
    textarea.clear()
    textarea.send_keys("\n".join(domains))

    btn = driver.find_element(By.CSS_SELECTOR, "button#scanBtn")
    btn.click()

    # tunggu sampai tabel hasil muncul (minimal 1 row)
    WebDriverWait(driver, 60).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, "div.table-card table tbody tr")) > 0
    )

    rows = driver.find_elements(By.CSS_SELECTOR, "div.table-card table tbody tr")
    results = {}

    for row in rows:
        tds = row.find_elements(By.TAG_NAME, "td")
        if len(tds) < 2:
            continue

        domain_cell = tds[0].text.strip().lower()
        status_cell = tds[1].text.strip()

        results[domain_cell] = status_cell

    return results


def main():
    print("=== DOMAIN CHECKER (ninjamvp.asia) ===", flush=True)

    domains = load_domains()
    if not domains:
        send_telegram("Domain Status Report (ninjamvp.asia)\nTidak ada domain untuk dicek.")
        return

    # UI ninjamvp biasanya max 50 domain per scan
    if len(domains) > 50:
        domains = domains[:50]
        print("Info: domain > 50, hanya 50 pertama yang dicek.", flush=True)

    driver = setup_driver()
    try:
        results = check_domains_ninjamvp(driver, domains)
    except Exception as e:
        try:
            driver.quit()
        except Exception:
            pass
        err_msg = f"❌ Gagal cek domain (ninjamvp.asia): {e}"
        print(err_msg, flush=True)
        send_telegram(err_msg)
        return

    try:
        driver.quit()
    except Exception:
        pass

    lines = ["Domain Status Report (ninjamvp.asia)"]

    for d in domains:
        status_text = results.get(d.lower(), "Unknown")
        emoji, label = normalize_status(status_text)
        lines.append(f"{d}: {emoji} {label}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
