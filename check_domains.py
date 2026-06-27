# check_domains.py
# FINAL VERSION — trustpositif.id REST API (tanpa Selenium!)
# Gratis 100 domain/hari per IP, tanpa perlu API key
#
# Env:
#   TELEGRAM_TOKEN
#   TELEGRAM_CHAT_ID
#   DOMAINS_TO_CHECK   (pisah koma atau enter)
# Optional:
#   API_KEY  (isi jika punya, untuk limit lebih tinggi)

import os
import requests
from time import sleep
from typing import Dict, List, Tuple

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DOMAINS_ENV     = os.environ.get("DOMAINS_TO_CHECK", "")
API_KEY         = os.environ.get("API_KEY", "")  # optional

API_URL = "https://trustpositif.id/api/v1/check"


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


def normalize_status(blocked: bool) -> Tuple[str, str]:
    if blocked:
        return "🔴", "Blocked"
    return "🟢", "Not Blocked"


# ================= API CHECK =================
def check_batch_api(domains: List[str]) -> Dict[str, bool]:
    """
    Cek batch domain via REST API trustpositif.id
    Return dict: {domain: blocked (True/False)}
    """
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    payload = {"domains": "\n".join(domains)}

    print(f"[API] Mengecek {len(domains)} domain...", flush=True)
    try:
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        print(f"[API] Response: success={data.get('success')}, count={data.get('count')}", flush=True)

        results = {}
        for item in data.get("results", []):
            domain = item.get("Domain", "").lower().strip()
            blocked = item.get("Blocked", False)
            if domain:
                results[domain] = blocked
                status = "BLOCKED" if blocked else "OK"
                print(f"    {domain}: {status}", flush=True)
        return results

    except requests.HTTPError as e:
        print(f"[API] HTTP Error: {e.response.status_code} - {e.response.text}", flush=True)
        raise
    except Exception as e:
        print(f"[API] Error: {type(e).__name__} - {e}", flush=True)
        raise


# ================= MAIN =================
def main():
    print("=== Nawala Checker START (API Mode) ===", flush=True)
    domains = load_domains()
    print(f"Total domain: {len(domains)}", flush=True)

    if not domains:
        send_telegram("Tidak ada domain untuk dicek.")
        return

    all_results: Dict[str, bool] = {}

    # API gratis limit 10 call/menit, batch max ~10 domain per call agar aman
    for i, batch in enumerate(chunk(domains, 10)):
        try:
            res = check_batch_api(batch)
            all_results.update(res)
        except Exception as e:
            msg = f"❌ Error batch {i+1}: {type(e).__name__} - {e}"
            print(msg, flush=True)
            send_telegram(msg)
            return
        if i > 0:
            sleep(6)  # jaga rate limit 10 call/menit

    # Susun laporan
    lines = ["📊 Domain Status Report (trustpositif.id)"]
    blocked_list = []
    ok_list = []

    for d in domains:
        blocked = all_results.get(d, None)
        if blocked is None:
            lines.append(f"{d}: ⚪ Tidak ada data")
        elif blocked:
            emoji, label = normalize_status(True)
            lines.append(f"{d}: {emoji} {label}")
            blocked_list.append(d)
        else:
            emoji, label = normalize_status(False)
            lines.append(f"{d}: {emoji} {label}")
            ok_list.append(d)

    lines.append(f"\n✅ Aman: {len(ok_list)} | 🔴 Diblokir: {len(blocked_list)}")

    report = "\n".join(lines)
    print(report, flush=True)
    send_telegram(report)
    print("=== SELESAI ===", flush=True)


if __name__ == "__main__":
    main()
