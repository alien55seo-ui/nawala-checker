import os
import json
import requests
from typing import Any, Dict, List, Tuple

VERSION = "nawala-asia-api-final-v2"

API_URL = "https://ukvsutaqqtjsebnkdmmt.supabase.co/functions/v1/check-domains"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")

# Optional: kalau suatu saat endpoint butuh key, isi env ini
NAWALA_API_KEY = os.environ.get("NAWALA_API_KEY", "").strip()


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


def load_domains() -> List[str]:
    raw = (DOMAINS_ENV or "").strip()
    if not raw:
        return []

    raw = raw.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",") if p.strip()]

    # normalisasi domain (hapus http/https dan slash)
    out: List[str] = []
    for d in parts:
        x = d.replace("https://", "").replace("http://", "").strip().strip("/")
        if x:
            out.append(x)
    return out


def build_headers() -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.nawala.asia",
        "Referer": "https://www.nawala.asia/",
        "User-Agent": "Mozilla/5.0",
    }
    if NAWALA_API_KEY:
        headers["Authorization"] = f"Bearer {NAWALA_API_KEY}"
        headers["apikey"] = NAWALA_API_KEY
    return headers


def call_api(domains: List[str]) -> Tuple[bool, str, Any]:
    """
    ✅ FORMAT WAJIB dari API ini:
    {
      "data": "domain1.com\ndomain2.com\n..."
    }
    """
    headers = build_headers()
    payload = {"data": "\n".join(domains)}

    try:
        r = requests.post(API_URL, headers=headers, json=payload, timeout=45)
    except Exception as e:
        return False, f"Request error: {type(e).__name__}: {e}", None

    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:500]}", None

    ct = (r.headers.get("content-type") or "").lower()
    if "application/json" not in ct:
        return False, f"Non-JSON response: {r.text[:500]}", None

    try:
        return True, "OK", r.json()
    except Exception as e:
        return False, f"JSON parse error: {type(e).__name__}: {e} | body={r.text[:500]}", None


def extract_results(data: Any) -> Dict[str, str]:
    """
    Coba parse berbagai bentuk response yang umum:
    - {"success":true,"results":[{"domain":"x","nawala":"Active"}...]}
    - {"results":[...]}
    - [{"domain":"x","nawala":"Active"}...]
    """
    results: Dict[str, str] = {}

    def norm(s: str) -> str:
        t = (s or "").strip().lower()
        if "blocked" in t or "terblok" in t or "nawala" in t and "active" not in t:
            return "blocked"
        if "active" in t or "aman" in t or "not blocked" in t or "tidak terblok" in t:
            return "active"
        return t or "unknown"

    def get_domain(it: Dict[str, Any]) -> str:
        return (it.get("domain") or it.get("host") or it.get("url") or "").strip().lower()

    def get_status(it: Dict[str, Any]) -> str:
        # prioritas field yang biasanya ada
        for k in ["nawala", "nawala_status", "status_nawala", "status", "result"]:
            if k in it and isinstance(it[k], (str, int, float)):
                return norm(str(it[k]))

        # nested object
        for k in ["nawala", "network"]:
            if k in it and isinstance(it[k], dict):
                for kk in ["status", "result", "state"]:
                    if kk in it[k]:
                        return norm(str(it[k][kk]))

        return "unknown"

    # list
    if isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                dom = get_domain(it)
                if dom:
                    results[dom] = get_status(it)
        return results

    # dict
    if isinstance(data, dict):
        items = None
        if isinstance(data.get("results"), list):
            items = data["results"]
        elif isinstance(data.get("data"), list):
            items = data["data"]

        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    dom = get_domain(it)
                    if dom:
                        results[dom] = get_status(it)
            return results

        # fallback: dict keyed by domain
        for k, v in data.items():
            if isinstance(k, str) and "." in k:
                dom = k.strip().lower()
                if isinstance(v, str):
                    results[dom] = norm(v)
                elif isinstance(v, dict):
                    results[dom] = get_status(v)
        return results

    return results


def status_to_emoji_label(status: str) -> Tuple[str, str]:
    s = (status or "").lower()
    if "blocked" in s:
        return "🔴", "Blocked"
    if "active" in s:
        return "🟢", "Not Blocked"
    return "⚪", "Unknown"


def main():
    send_telegram(f"✅ RUNNING NAWALA.ASIA API VERSION [{VERSION}]")

    domains = load_domains()
    if not domains:
        send_telegram(f"Domain Status Report (nawala.asia API) [{VERSION}]\nTidak ada domain untuk dicek.")
        return

    ok, info, data = call_api(domains)
    if not ok:
        send_telegram(
            f"❌ Gagal call API [{VERSION}]\n"
            f"Endpoint: {API_URL}\n"
            f"Info: {info}\n"
            f"Hint: Jika butuh key, set NAWALA_API_KEY."
        )
        return

    results = extract_results(data)
    if not results:
        preview = ""
        try:
            preview = json.dumps(data, ensure_ascii=False)[:900]
        except Exception:
            preview = str(data)[:900]

        send_telegram(
            f"⚠️ API OK tapi hasil tidak bisa diparse [{VERSION}]\n"
            f"{info}\n"
            f"Response preview:\n{preview}"
        )
        return

    lines = [f"Domain Status Report (nawala.asia API) [{VERSION}]"]
    for d in domains:
        key = d.lower()
        st = results.get(key, "unknown")
        emoji, label = status_to_emoji_label(st)
        lines.append(f"{key}: {emoji} {label}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
