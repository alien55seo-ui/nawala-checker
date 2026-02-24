import os
import json
import requests
from typing import Any, Dict, List, Optional, Tuple

VERSION = "nawala-asia-api-final-v3"

API_URL = "https://ukvsutaqqtjsebnkdmmt.supabase.co/functions/v1/check-domains"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")

# WAJIB: isi dengan key dari header apikey/authorization (sama persis)
NAWALA_API_KEY = os.environ.get("NAWALA_API_KEY", "").strip()


# ----------------- TELEGRAM -----------------
def send_telegram(text: str) -> None:
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


# ----------------- DOMAINS -----------------
def load_domains() -> List[str]:
    raw = (DOMAINS_ENV or "").strip()
    if not raw:
        return []

    raw = raw.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",") if p.strip()]

    out: List[str] = []
    for d in parts:
        x = d.replace("https://", "").replace("http://", "").strip().strip("/")
        if x:
            out.append(x)
    return out


# ----------------- API CALL -----------------
def build_headers() -> Dict[str, str]:
    # Header minimal yang penting + key supabase
    return {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://www.nawala.asia",
        "referer": "https://www.nawala.asia/",
        "user-agent": "Mozilla/5.0",
        "apikey": NAWALA_API_KEY,
        "authorization": f"Bearer {NAWALA_API_KEY}",
    }


def post_json(payload: Dict[str, Any]) -> Tuple[int, str, Optional[Any]]:
    headers = build_headers()
    try:
        r = requests.post(API_URL, headers=headers, json=payload, timeout=45)
    except Exception as e:
        return 0, f"Request error: {type(e).__name__}: {e}", None

    txt = r.text or ""
    if r.status_code != 200:
        return r.status_code, txt[:600], None

    # try json
    try:
        return r.status_code, txt[:600], r.json()
    except Exception:
        return r.status_code, txt[:600], None


def call_api(domains: List[str]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Karena payload request asli belum kelihatan (yang kamu kirim body-nya seperti response),
    kita coba beberapa format input yang umum untuk edge function ini.

    API harus balas JSON dengan {"success": true, "data": [...]}
    """
    candidates = [
        {"domains": domains},
        {"data": domains},
        {"domains": "\n".join(domains)},
        {"data": "\n".join(domains)},
        {"items": domains},
        {"list": domains},
    ]

    last_info = ""
    for i, payload in enumerate(candidates, start=1):
        code, preview, data = post_json(payload)
        last_info = f"try#{i} HTTP {code} preview={preview}"

        if isinstance(data, dict) and data.get("success") is True and isinstance(data.get("data"), list):
            return True, f"OK (payload try#{i})", data

        # beberapa server tidak pakai "success", tapi langsung "data"
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return True, f"OK (payload try#{i}, no success flag)", data

    return False, last_info, None


# ----------------- PARSE RESULT -----------------
def status_to_emoji_label(blocked: Optional[bool]) -> Tuple[str, str]:
    if blocked is True:
        return "🔴", "Blocked"
    if blocked is False:
        return "🟢", "Not Blocked"
    return "⚪", "Unknown"


def parse_results(api_json: Dict[str, Any]) -> Dict[str, Dict[str, Optional[bool]]]:
    """
    Expected response (dari cURL kamu):
      {"success":true,"data":[{"domain":"x","nawala":{"blocked":false},"network":{"blocked":false}}]}
    Return:
      { "x": {"nawala": False, "network": False}, ... }
    """
    out: Dict[str, Dict[str, Optional[bool]]] = {}
    items = api_json.get("data", [])
    if not isinstance(items, list):
        return out

    for it in items:
        if not isinstance(it, dict):
            continue
        dom = (it.get("domain") or "").strip().lower()
        if not dom:
            continue

        nawala_blocked = None
        network_blocked = None

        n = it.get("nawala")
        if isinstance(n, dict):
            if "blocked" in n:
                nawala_blocked = bool(n["blocked"])

        nw = it.get("network")
        if isinstance(nw, dict):
            if "blocked" in nw:
                network_blocked = bool(nw["blocked"])

        out[dom] = {"nawala": nawala_blocked, "network": network_blocked}

    return out


# ----------------- MAIN -----------------
def main() -> None:
    send_telegram(f"✅ RUNNING NAWALA.ASIA API VERSION [{VERSION}]")

    if not NAWALA_API_KEY:
        send_telegram(
            f"❌ NAWALA_API_KEY belum di-set [{VERSION}]\n"
            f"Set env NAWALA_API_KEY = apikey/authorization dari Network."
        )
        return

    domains = load_domains()
    if not domains:
        send_telegram(f"Domain Status Report (nawala.asia API) [{VERSION}]\nTidak ada domain untuk dicek.")
        return

    ok, info, data = call_api(domains)
    if not ok or not data:
        send_telegram(
            f"❌ Gagal call API [{VERSION}]\n"
            f"Endpoint: {API_URL}\n"
            f"Info: {info}\n"
            f"Catatan: Pastikan NAWALA_API_KEY benar, dan payload cocok."
        )
        return

    results = parse_results(data)
    if not results:
        preview = json.dumps(data, ensure_ascii=False)[:900]
        send_telegram(
            f"⚠️ API OK tapi hasil kosong/tidak ter-parse [{VERSION}]\n"
            f"{info}\n"
            f"Response preview:\n{preview}"
        )
        return

    lines = [f"Domain Status Report (nawala.asia API) [{VERSION}]"]

    for d in domains:
        key = d.lower()
        item = results.get(key, {"nawala": None, "network": None})

        e1, l1 = status_to_emoji_label(item.get("nawala"))
        e2, l2 = status_to_emoji_label(item.get("network"))

        # kamu bisa pilih tampilkan hanya Nawala atau dua-duanya.
        # Di sini saya tampilkan dua status biar jelas:
        lines.append(f"{key}: Nawala {e1} {l1} | Network {e2} {l2}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
