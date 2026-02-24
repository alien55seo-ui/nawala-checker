import os
import requests
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

VERSION = "nawala-asia-final-v4"
TARGET_URL = "https://www.nawala.asia/"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")


def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram env belum di-set", flush=True)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=20)
        print("Telegram resp:", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("Gagal kirim Telegram:", e, flush=True)


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


def load_domains():
    raw = (DOMAINS_ENV or "").strip()
    if not raw:
        return []
    raw = raw.replace("\n", ",")
    return [x.strip() for x in raw.split(",") if x.strip()]


def normalize_domain(d: str) -> str:
    x = (d or "").strip()
    return x.replace("https://", "").replace("http://", "").strip("/")


def body_snippet(driver, limit=500):
    try:
        t = driver.find_element(By.TAG_NAME, "body").text.strip()
        if not t:
            return "(body kosong)"
        return t[:limit] + ("..." if len(t) > limit else "")
    except Exception:
        return "(gagal ambil body)"


def click_cek_nawala(driver):
    """
    Klik tombol/elemen yang mengandung teks 'Cek Nawala' atau minimal 'Cek'.
    Fleksibel: button/a/div/span.
    """
    # prioritas: "Cek Nawala"
    xpath1 = (
        "//*[self::button or self::a or self::div or self::span]"
        "[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'cek nawala')]"
    )
    els = driver.find_elements(By.XPATH, xpath1)
    for el in els:
        try:
            if el.is_displayed() and el.is_enabled():
                driver.execute_script("arguments[0].click();", el)
                return
        except Exception:
            pass

    # fallback: "Cek"
    xpath2 = (
        "//*[self::button or self::a or self::div or self::span]"
        "[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'cek')]"
    )
    els = driver.find_elements(By.XPATH, xpath2)
    for el in els:
        try:
            if el.is_displayed() and el.is_enabled():
                driver.execute_script("arguments[0].click();", el)
                return
        except Exception:
            pass

    raise RuntimeError("Tombol 'Cek Nawala' tidak ditemukan / tidak bisa diklik.")


def wait_results(driver):
    """
    Tunggu sampai hasil muncul.
    Tidak bergantung table saja:
    - table row muncul ATAU
    - teks 'Active' / 'Blocked' muncul di halaman
    """
    def done(d):
        # ada row tabel?
        if len(d.find_elements(By.CSS_SELECTOR, "table tbody tr")) > 0:
            return True

        # atau minimal ada table
        if len(d.find_elements(By.TAG_NAME, "table")) > 0:
            return True

        # atau ada kata status
        txt = d.find_element(By.TAG_NAME, "body").text.lower()
        if "active" in txt or "blocked" in txt:
            return True

        return False

    WebDriverWait(driver, 120).until(done)  # naikin timeout jadi 120 detik


def parse_table(driver):
    """
    Parse tabel hasil:
    kolom 1=domain, kolom 2=Nawala, kolom 3=Network
    Ambil kolom 2 sebagai status utama.
    """
    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    if not rows:
        # fallback: table ada tapi belum ada tbody
        rows = driver.find_elements(By.CSS_SELECTOR, "table tr")

    results = {}
    for row in rows:
        cols = row.find_elements(By.TAG_NAME, "td")
        if len(cols) < 2:
            continue
        domain = cols[0].text.strip().lower()
        nawala_status = cols[1].text.strip().lower()  # Active/Blocked (badge)
        if domain:
            results[domain] = nawala_status

    return results


def status_to_emoji_label(status: str):
    s = (status or "").lower()
    if "active" in s:
        return "🟢", "Not Blocked"
    if "blocked" in s:
        return "🔴", "Blocked"
    return "⚪", "Unknown"


def main():
    send_telegram(f"✅ RUNNING NAWALA.ASIA VERSION [{VERSION}]")

    domains = load_domains()
    if not domains:
        send_telegram(f"Domain Status Report (nawala.asia) [{VERSION}]\nTidak ada domain.")
        return

    driver = setup_driver()

    try:
        driver.get(TARGET_URL)

        wait = WebDriverWait(driver, 60)
        textarea = wait.until(lambda d: d.find_element(By.TAG_NAME, "textarea"))
        textarea.clear()
        textarea.send_keys("\n".join(normalize_domain(d) for d in domains))

        click_cek_nawala(driver)
        wait_results(driver)

        results = parse_table(driver)

        # kalau parsing tabel gagal, kirim debug supaya kita tahu struktur aslinya
        if not results:
            msg = (
                f"❌ Hasil muncul tapi gagal parse tabel [{VERSION}]\n"
                f"URL: {driver.current_url}\n"
                f"Title: {driver.title}\n"
                f"BODY:\n{body_snippet(driver)}"
            )
            send_telegram(msg)
            return

    except TimeoutException:
        msg = (
            f"❌ Timeout (nawala.asia) [{VERSION}]\n"
            f"URL: {driver.current_url}\n"
            f"Title: {driver.title}\n"
            f"BODY:\n{body_snippet(driver)}"
        )
        send_telegram(msg)
        traceback.print_exc()
        return

    except Exception as e:
        msg = (
            f"❌ Error (nawala.asia) [{VERSION}]\n"
            f"{type(e).__name__}: {e}\n"
            f"URL: {driver.current_url}\n"
            f"Title: {driver.title}\n"
            f"BODY:\n{body_snippet(driver)}"
        )
        send_telegram(msg)
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
        raw = results.get(key, "unknown")
        emoji, label = status_to_emoji_label(raw)
        lines.append(f"{key}: {emoji} {label}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
