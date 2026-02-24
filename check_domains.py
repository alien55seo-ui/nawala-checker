import os
import re
import requests
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

VERSION = "nawala-asia-final-v2"
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
    if not DOMAINS_ENV.strip():
        return []
    raw = DOMAINS_ENV.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


def normalize_domain(d: str) -> str:
    x = (d or "").strip()
    x = x.replace("https://", "").replace("http://", "").strip().strip("/")
    return x


def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def body_snippet(driver, limit=450):
    try:
        t = driver.find_element(By.TAG_NAME, "body").text.strip()
        if not t:
            return "(body kosong)"
        return t[:limit] + ("..." if len(t) > limit else "")
    except Exception:
        return "(gagal ambil body)"


def find_best_textarea_or_input(driver):
    textareas = driver.find_elements(By.TAG_NAME, "textarea")
    for ta in textareas:
        try:
            if ta.is_displayed() and ta.is_enabled():
                return ta
        except Exception:
            pass

    inputs = driver.find_elements(By.TAG_NAME, "input")
    for inp in inputs:
        try:
            if not (inp.is_displayed() and inp.is_enabled()):
                continue
            t = (inp.get_attribute("type") or "").lower()
            if t in ("text", "search", "url", ""):
                return inp
        except Exception:
            pass

    raise RuntimeError("Tidak menemukan textarea/input untuk memasukkan domain.")


def find_action_button(driver):
    keywords = ["check", "cek", "scan", "submit", "proses", "process", "search", "cari"]
    candidates = driver.find_elements(By.XPATH, "//*[self::button or self::a or self::input]")

    best = None
    best_score = 0

    for el in candidates:
        try:
            if not el.is_displayed() or not el.is_enabled():
                continue

            txt = el.text.strip()
            if not txt:
                txt = (el.get_attribute("value") or "").strip()
            low = txt.lower()

            score = 0
            for k in keywords:
                if k in low:
                    score += 2

            if score > best_score:
                best_score = score
                best = el
        except Exception:
            pass

    if not best:
        raise RuntimeError("Tidak menemukan tombol aksi (Check/Scan/Cek/Submit).")

    return best


def classify_from_line(line: str):
    """
    Klasifikasi fleksibel dari 1 baris yang mengandung domain.
    Kita tidak paksa hanya blocked/not blocked, tapi baca kata-kata umum.
    """
    t = (line or "").lower()

    # aman / tidak diblokir
    if any(k in t for k in ["not blocked", "tidak diblokir", "aman", "allowed", "clean", "safe", "negatif"]):
        return "🟢", "Not Blocked"

    # terblokir / nawala / ipos
    if any(k in t for k in ["blocked", "terblokir", "nawala", "ipos", "positif", "internet positif"]):
        return "🔴", "Blocked"

    if "error" in t or "gagal" in t:
        return "🟠", "Error"

    # fallback: tampilkan ringkasan textnya
    return "⚪", "Unknown"


def extract_line_for_domain(body_text: str, domain: str) -> str:
    """
    Ambil baris di body_text yang mengandung domain.
    Kalau tidak ada baris yang jelas, ambil potongan sekitar domain.
    """
    key = normalize_domain(domain)
    if not key:
        return ""

    lines = (body_text or "").splitlines()
    for ln in lines:
        if key.lower() in ln.lower():
            return ln.strip()

    # fallback: ambil potongan sekitar domain (kalau HTML tidak pakai newline)
    lower = (body_text or "").lower()
    idx = lower.find(key.lower())
    if idx == -1:
        return ""
    start = max(0, idx - 80)
    end = min(len(body_text), idx + len(key) + 120)
    return body_text[start:end].replace("\n", " ").strip()


def check_batch(driver, batch_domains):
    driver.get(TARGET_URL)
    wait = WebDriverWait(driver, 40)
    wait.until(lambda d: d.find_element(By.TAG_NAME, "body"))

    input_el = find_best_textarea_or_input(driver)
    input_el.clear()
    input_el.send_keys("\n".join(normalize_domain(x) for x in batch_domains))

    btn = find_action_button(driver)
    driver.execute_script("arguments[0].click();", btn)

    # tunggu minimal ada perubahan teks atau muncul domain di body
    def done(d):
        txt = d.find_element(By.TAG_NAME, "body").text
        # selesai kalau minimal ada salah satu domain muncul di body
        for dom in batch_domains[: min(5, len(batch_domains))]:
            if normalize_domain(dom).lower() in txt.lower():
                return True
        # atau ada kata-kata status umum
        low = txt.lower()
        if any(k in low for k in ["blocked", "terblokir", "nawala", "ipos", "aman", "tidak diblokir", "allowed"]):
            return True
        return False

    WebDriverWait(driver, 90).until(done)

    body_text = driver.find_element(By.TAG_NAME, "body").text
    results = {}

    for d in batch_domains:
        key = normalize_domain(d).lower()
        line = extract_line_for_domain(body_text, d)
        results[key] = line if line else "Unknown"

    return results


def main():
    send_telegram(f"✅ RUNNING NAWALA.ASIA VERSION [{VERSION}]")

    domains = load_domains()
    if not domains:
        send_telegram(f"Domain Status Report (nawala.asia) [{VERSION}]\nTidak ada domain.")
        return

    driver = setup_driver()
    merged = {}

    try:
        for batch in chunk(domains, 50):
            merged.update(check_batch(driver, batch))

    except TimeoutException:
        msg = (
            f"❌ Timeout (nawala.asia) [{VERSION}]\n"
            f"URL: {driver.current_url}\n"
            f"Title: {driver.title}\n"
            f"Body: {body_snippet(driver)}"
        )
        send_telegram(msg)
        print(msg, flush=True)
        traceback.print_exc()
        return

    except Exception as e:
        msg = (
            f"❌ Error (nawala.asia) [{VERSION}]\n"
            f"{type(e).__name__}: {e}\n"
            f"URL: {driver.current_url}\n"
            f"Title: {driver.title}\n"
            f"Body: {body_snippet(driver)}"
        )
        send_telegram(msg)
        print(msg, flush=True)
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
        raw_line = merged.get(key, "Unknown")
        emoji, label = classify_from_line(raw_line)

        # tampilkan status ringkas + (opsional) potongan line biar kamu bisa lihat kata apa yang dipakai situs
        # Kalau kamu mau super bersih, hapus " — {raw_line}" di bawah.
        lines.append(f"{key}: {emoji} {label} — {raw_line}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
