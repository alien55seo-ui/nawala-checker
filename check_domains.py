import os
import re
import requests
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException


VERSION = "nawala-asia-final-v1"
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
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True}
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
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1280,720")

    # lebih “normal”
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver


# ================= DOMAIN =================
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


def body_snippet(driver, limit=400):
    try:
        t = driver.find_element(By.TAG_NAME, "body").text.strip()
        if not t:
            return "(body kosong)"
        return t[:limit] + ("..." if len(t) > limit else "")
    except Exception:
        return "(gagal ambil body)"


# ================= FIND ELEMENTS (ROBUST) =================
def find_best_textarea_or_input(driver):
    """
    Cari textarea dulu. Jika tidak ada, cari input yang bisa diisi (type=text/search/url).
    """
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
    """
    Cari tombol dengan teks: check/cek/scan/submit.
    """
    keywords = ["check", "cek", "scan", "submit", "proses", "process"]
    # button/a/input
    candidates = driver.find_elements(
        By.XPATH,
        "//*[self::button or self::a or self::input]"
    )

    def score(el_text: str) -> int:
        s = (el_text or "").strip().lower()
        sc = 0
        for k in keywords:
            if k in s:
                sc += 2
        if sc == 0 and s:
            # teks ada tapi tidak match keyword
            sc += 0
        return sc

    best = None
    best_score = 0

    for el in candidates:
        try:
            if not el.is_displayed() or not el.is_enabled():
                continue

            txt = el.text.strip()
            if not txt:
                # untuk input button, teks bisa di value
                txt = (el.get_attribute("value") or "").strip()

            sc = score(txt)
            if sc > best_score:
                best_score = sc
                best = el
        except Exception:
            pass

    if not best:
        raise RuntimeError("Tidak menemukan tombol aksi (Check/Scan/Cek/Submit).")

    return best


# ================= PARSE RESULTS =================
def parse_table_results(driver):
    """
    Jika ada table, coba parse:
    - kolom 1 = domain
    - kolom status ada di kolom lain (cari kata blocked/terblokir/aman/not blocked)
    Return dict domain_lower -> status_text (raw)
    """
    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    if not rows:
        return {}

    out = {}
    for row in rows:
        tds = row.find_elements(By.TAG_NAME, "td")
        if len(tds) < 2:
            continue
        dom = normalize_domain(tds[0].text).lower()
        # gabungkan semua kolom selain domain jadi status raw
        status_raw = " | ".join(td.text.strip() for td in tds[1:] if td.text.strip())
        if dom:
            out[dom] = status_raw
    return out


def classify_status(status_raw: str):
    s = (status_raw or "").lower()
    # urutan penting: not blocked dulu supaya tidak ketimpa kata blocked
    if "not blocked" in s or "tidak diblokir" in s or "aman" in s or "allowed" in s or "clean" in s:
        return "🟢", "Not Blocked"
    if "blocked" in s or "terblokir" in s or "nawala" in s or "ipos" in s:
        return "🔴", "Blocked"
    if "error" in s or "gagal" in s:
        return "🟠", "Error"
    return "⚪", "Unknown"


def parse_from_body_text(body_text: str, domains: list[str]):
    """
    Fallback: cari per domain di body text.
    """
    lower = (body_text or "").lower()
    out = {}
    for d in domains:
        key = normalize_domain(d).lower()
        if not key:
            continue
        m = re.search(
            rf"(?<!\w){re.escape(key)}(?!\w).*?\b(not blocked|tidak diblokir|aman|allowed|blocked|terblokir|error)\b",
            lower,
            re.IGNORECASE
        )
        out[key] = m.group(1) if m else "Unknown"
    return out


# ================= CORE CHECK =================
def check_batch(driver, batch_domains):
    driver.get(TARGET_URL)
    wait = WebDriverWait(driver, 40)
    wait.until(lambda d: d.find_element(By.TAG_NAME, "body"))

    # Deteksi cloudflare "Just a moment..."
    title = (driver.title or "").lower()
    body_now = driver.find_element(By.TAG_NAME, "body").text.lower()
    if "just a moment" in title or "cloudflare" in body_now or "security verification" in body_now:
        raise RuntimeError("Terkena proteksi Cloudflare/anti-bot (Just a moment / security verification).")

    input_el = find_best_textarea_or_input(driver)
    input_el.clear()

    # format satu domain per baris
    input_el.send_keys("\n".join(normalize_domain(x) for x in batch_domains))

    btn = find_action_button(driver)
    driver.execute_script("arguments[0].click();", btn)

    # tunggu: table row muncul ATAU kata kunci status muncul
    def done(d):
        t = d.find_element(By.TAG_NAME, "body").text.lower()
        if len(d.find_elements(By.CSS_SELECTOR, "table tbody tr")) > 0:
            return True
        if any(k in t for k in ["blocked", "terblokir", "not blocked", "tidak diblokir", "aman", "allowed", "error"]):
            return True
        return False

    wait2 = WebDriverWait(driver, 90)
    wait2.until(done)

    # coba parse table dulu
    table_results = parse_table_results(driver)
    if table_results:
        return table_results

    # fallback parse body
    body_text = driver.find_element(By.TAG_NAME, "body").text
    return parse_from_body_text(body_text, batch_domains)


# ================= MAIN =================
def main():
    # signature
    send_telegram(f"✅ RUNNING NAWALA.ASIA VERSION [{VERSION}]")

    domains = load_domains()
    if not domains:
        send_telegram(f"Domain Status Report (nawala.asia) [{VERSION}]\nTidak ada domain.")
        return

    # kalau situs punya limit, kamu bisa ubah batch size di sini
    BATCH_SIZE = 50

    driver = setup_driver()
    merged = {}

    try:
        for batch in chunk(domains, BATCH_SIZE):
            res = check_batch(driver, batch)
            merged.update(res)

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

    # build report
    lines = [f"Domain Status Report (nawala.asia) [{VERSION}]"]
    for d in domains:
        key = normalize_domain(d).lower()
        raw = merged.get(key, "Unknown")
        emoji, label = classify_status(raw)
        lines.append(f"{key}: {emoji} {label}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
