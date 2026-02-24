import os
import requests
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

VERSION = "nawala-asia-final-v3"
TARGET_URL = "https://www.nawala.asia/"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")


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
        r = requests.post(url, json=payload, timeout=20)
        print("Telegram resp:", r.status_code, r.text[:200], flush=True)
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
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver


# ================= DOMAIN =================
def load_domains():
    raw = (DOMAINS_ENV or "").strip()
    if not raw:
        return []
    raw = raw.replace("\n", ",")
    return [x.strip() for x in raw.split(",") if x.strip()]


def normalize_domain(d: str) -> str:
    x = d.strip()
    return x.replace("https://", "").replace("http://", "").strip("/")


# ================= CORE =================
def check_nawala_asia(driver, domains):
    driver.get(TARGET_URL)
    wait = WebDriverWait(driver, 40)
    wait.until(lambda d: d.find_element(By.TAG_NAME, "textarea"))

    textarea = driver.find_element(By.TAG_NAME, "textarea")
    textarea.clear()
    textarea.send_keys("\n".join(normalize_domain(d) for d in domains))

    # klik tombol "Cek Nawala"
    btn = driver.find_element(
        By.XPATH, "//button[contains(., 'Cek')]"
    )
    driver.execute_script("arguments[0].click();", btn)

    # tunggu tabel hasil
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "table tbody tr")) > 0)

    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    results = {}

    for row in rows:
        cols = row.find_elements(By.TAG_NAME, "td")
        if len(cols) < 2:
            continue

        domain = cols[0].text.strip().lower()
        nawala_status = cols[1].text.strip().lower()  # Active / Blocked

        results[domain] = nawala_status

    return results


def status_to_emoji_label(status: str):
    s = status.lower()
    if "active" in s:
        return "🟢", "Not Blocked"
    if "blocked" in s:
        return "🔴", "Blocked"
    return "⚪", "Unknown"


# ================= MAIN =================
def main():
    send_telegram(f"✅ RUNNING NAWALA.ASIA VERSION [{VERSION}]")

    domains = load_domains()
    if not domains:
        send_telegram("Domain Status Report (nawala.asia)\nTidak ada domain.")
        return

    driver = setup_driver()

    try:
        results = check_nawala_asia(driver, domains)
    except TimeoutException:
        send_telegram(f"❌ Timeout (nawala.asia) [{VERSION}]")
        traceback.print_exc()
        return
    except Exception as e:
        send_telegram(f"❌ Error (nawala.asia) [{VERSION}]\n{type(e).__name__}: {e}")
        traceback.print_exc()
        return
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    lines = [f"Domain Status Report (nawala.asia) [{VERSION}]"]
    for d in domains:
        key = normalize_domain(d).lower()
        status = results.get(key, "unknown")
        emoji, label = status_to_emoji_label(status)
        lines.append(f"{key}: {emoji} {label}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
