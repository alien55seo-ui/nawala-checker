import os
import re
import requests
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

VERSION = "trustpositif-app-v1"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")

TARGET_URL = "https://trustpositif.app/"


# ================= TELEGRAM =================
def send_telegram(text: str):
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
        resp = requests.post(url, json=payload, timeout=20)
        print("Telegram resp:", resp.status_code, resp.text[:200], flush=True)
    except Exception as e:
        print("Gagal kirim Telegram:", e, flush=True)


# ================= SELENIUM =================
def setup_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,720")

    # sedikit lebih “normal” agar tidak mudah ditolak
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    )

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver


# ================= DOMAIN =================
def load_domains():
    if not DOMAINS_ENV.strip():
        print("DOMAINS_TO_CHECK kosong.", flush=True)
        return []

    raw = DOMAINS_ENV.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",")]
    domains = [p for p in parts if p]
    print("Loaded domains:", domains, flush=True)
    return domains


def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def normalize_domain(d: str) -> str:
    # trustpositif.app minta domain/IP per line, tanpa perlu http(s)
    x = d.strip()
    x = x.replace("https://", "").replace("http://", "")
    x = x.strip().strip("/")
    return x


# ================= TRUSTPOSITIF.APP =================
def click_scan_button(driver):
    """
    Cari tombol yang mengandung teks 'SCAN' (case-insensitive).
    Karena UI bisa pakai button/div role=button, kita buat fleksibel.
    """
    candidates = driver.find_elements(
        By.XPATH,
        "//*[self::button or self::a or self::div or self::span]"
        "[contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SCAN')]"
    )
    for el in candidates:
        try:
            if el.is_displayed() and el.is_enabled():
                driver.execute_script("arguments[0].click();", el)
                return
        except Exception:
            pass

    raise RuntimeError("Tombol 'SCAN' tidak ditemukan")


def parse_results_from_text(page_text: str, domains: list[str]) -> dict:
    """
    Parse hasil dari text halaman.
    Kita cari pola:
      domain ... Allowed/Blocked/Error
    Output: dict domain_lower -> status ('Allowed'/'Blocked'/'Error'/'Unknown')
    """
    text = (page_text or "")
    results = {}

    # normalisasi agar pencarian stabil
    lower_text = text.lower()

    for d in domains:
        key = normalize_domain(d).lower()

        # regex yang toleran spasi/kolom
        # contoh: "alien55.com  Allowed"
        # contoh: "alien55.com   Blocked"
        m = re.search(rf"(?<!\w){re.escape(key)}(?!\w).*?\b(allowed|blocked|error)\b", lower_text, re.IGNORECASE)
        if m:
            status = m.group(1).capitalize()
            results[key] = status
        else:
            results[key] = "Unknown"

    return results


def check_batch_trustpositif(driver, domains_batch: list[str]) -> dict:
    driver.get(TARGET_URL)
    wait = WebDriverWait(driver, 40)
    wait.until(lambda d: d.find_element(By.TAG_NAME, "body"))

    # textarea pertama (paling aman)
    textarea = wait.until(lambda d: d.find_element(By.TAG_NAME, "textarea"))
    textarea.clear()
    textarea.send_keys("\n".join(normalize_domain(x) for x in domains_batch))

    click_scan_button(driver)

    # tunggu hasil: minimal ada kata Allowed/Blocked/Error atau total berubah
    def done(d):
        body_text = d.find_element(By.TAG_NAME, "body").text.lower()
        if "allowed" in body_text or "blocked" in body_text or "error" in body_text:
            return True
        return False

    wait2 = WebDriverWait(driver, 80)
    wait2.until(done)

    body_text = driver.find_element(By.TAG_NAME, "body").text
    return parse_results_from_text(body_text, domains_batch)


def to_emoji_label(status: str):
    s = (status or "").strip().lower()
    if s == "allowed":
        return "🟢", "Not Blocked"
    if s == "blocked":
        return "🔴", "Blocked"
    if s == "error":
        return "🟠", "Error"
    return "⚪", "Unknown"


# ================= MAIN =================
def main():
    print(f"=== DOMAIN CHECKER (trustpositif.app) | {VERSION} ===", flush=True)

    domains = load_domains()
    if not domains:
        send_telegram(f"Domain Status Report (trustpositif.app) [{VERSION}]\nTidak ada domain untuk dicek.")
        return

    # trustpositif.app max 100 / scan (dari UI)
    # jadi kita batch 100 agar aman
    driver = setup_driver()
    final = {}

    try:
        for batch in chunk(domains, 100):
            res = check_batch_trustpositif(driver, batch)
            final.update(res)

    except TimeoutException:
        msg = (
            f"❌ Timeout (trustpositif.app) [{VERSION}]\n"
            f"URL: {driver.current_url}\n"
            f"Title: {driver.title}"
        )
        print(msg, flush=True)
        traceback.print_exc()
        send_telegram(msg)

    except Exception as e:
        msg = (
            f"❌ Error (trustpositif.app) [{VERSION}]\n"
            f"{type(e).__name__}: {e}\n"
            f"URL: {driver.current_url}\n"
            f"Title: {driver.title}"
        )
        print(msg, flush=True)
        traceback.print_exc()
        send_telegram(msg)

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    if not final:
        return

    lines = [f"Domain Status Report (trustpositif.app) [{VERSION}]"]
    for d in domains:
        key = normalize_domain(d).lower()
        status = final.get(key, "Unknown")
        emoji, label = to_emoji_label(status)
        lines.append(f"{key}: {emoji} {label}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
