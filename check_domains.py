import os
import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from time import sleep

# ====== ENV VARS ======
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")


# ====== TELEGRAM ======
def send_telegram(text: str):
    """Kirim pesan ke Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram env belum di-set")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        print("Telegram resp:", resp.status_code, resp.text[:200])
    except Exception as e:
        print("Gagal kirim ke Telegram:", e)


# ====== SELENIUM SETUP ======
def setup_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)
    return driver


# ====== DOMAIN INPUT ======
def load_domains():
    """
    Ambil daftar domain dari env DOMAINS_TO_CHECK.
    Bisa dipisah koma atau enter.

    Contoh di Railway Variables:

    DOMAINS_TO_CHECK = alien55.com, alien55.site, alien55.vip
    """
    if not DOMAINS_ENV:
        print("DOMAINS_TO_CHECK kosong, tidak ada domain untuk dicek.", flush=True)
        return []

    # ganti enter dengan koma supaya fleksibel
    raw = DOMAINS_ENV.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",")]
    domains = [p for p in parts if p]

    print("Loaded domains from DOMAINS_TO_CHECK:", domains, flush=True)
    return domains


# ====== STATUS PARSER ======
def classify_status_text(status_text: str):
    """
    Ubah teks dari kolom Status menjadi emoji + label singkat.
    """
    t = (status_text or "").strip().lower()

    if not t:
        return "⚪", "Unknown"

    # penting: cek "not blocked" dulu supaya tidak ketimpa kata "blocked"
    if "not blocked" in t or "tidak diblokir" in t:
        return "🟢", "Not Blocked"

    if "blocked" in t or "diblokir" in t or "blocklist" in t:
        return "🔴", "Blocked"

    if "error" in t:
        return "🟠", "Error"

    return "⚪", status_text.strip() or "Unknown"


# ====== CORE CHECK: CEK BANYAK DOMAIN SEKALIGUS ======
def check_multiple_domains(driver, domains):
    """
    Buka halaman, isi SEMUA domain sekaligus di textarea,
    klik 'Check Domains', lalu baca tabel hasil (per-domain).
    Mengembalikan dict: {domain_lower: status_text}
    """
    driver.get("https://www.ninjamvp.asia/")
    sleep(3)

    # textarea domain
    textarea = driver.find_element(By.TAG_NAME, "textarea")
    textarea.clear()
    textarea.send_keys("\n".join(domains))

    # klik tombol "Check Domains"
    button = driver.find_element(By.XPATH, "//button[contains(., 'Check Domains')]")
    button.click()

    # tunggu sampai tabel hasil muncul
    WebDriverWait(driver, 60).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "#results table tbody tr")
        )
    )

    # ambil seluruh baris tabel
    rows = driver.find_elements(By.CSS_SELECTOR, "#results table tbody tr")
    results = {}

    for row in rows:
        cols = row.find_elements(By.TAG_NAME, "td")
        if len(cols) < 2:
            continue

        domain_cell = cols[0].text.strip().lower()
        status_cell = cols[1].text.strip()

        results[domain_cell] = status_cell

    print("Parsed results from table:", results, flush=True)
    return results


# ====== MAIN ======
def main():
    print("=== DOMAIN CHECKER (ENV ONLY) ===", flush=True)

    domains = load_domains()
    if not domains:
        send_telegram("Domain Status Report\nTidak ada domain untuk dicek.")
        return

    # kalau mau, bisa batasi maksimal 100 domain (sesuai limit website)
    if len(domains) > 100:
        print("Warning: domain > 100, hanya 100 pertama yang dicek.", flush=True)
        domains = domains[:100]

    driver = setup_driver()

    try:
        results = check_multiple_domains(driver, domains)
    except Exception as e:
        driver.quit()
        err_msg = f"Gagal mengambil hasil dari NawalaCheck: {e}"
        print(err_msg, flush=True)
        send_telegram(err_msg)
        return

    lines_console = ["Domain Status Report"]
    lines_tg = ["<b>Domain Status Report</b>"]

    for d in domains:
        key = d.lower()
        status_text = results.get(key, "Unknown")
        emoji, label = classify_status_text(status_text)

        # log ke console
        line_plain = f"{d}: {emoji} {label} ({status_text})"
        print(line_plain, flush=True)
        lines_console.append(line_plain)

        # format link klikable di Telegram
        link = f"<a href=\"http://{d}\">{d}</a>"
        line_tg = f"{link}: {emoji} {label}"
        lines_tg.append(line_tg)

    driver.quit()

    # kirim ke telegram
    message = "\n".join(lines_tg)
    send_telegram(message)


if __name__ == "__main__":
    main()
