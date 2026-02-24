import os
import json
import requests
from typing import Any, Dict, List, Tuple

VERSION = "nawala-asia-api-final-v1"

API_URL = "https://ukvsutaqqtjsebnkdmmt.supabase.co/functions/v1/check-domains"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")

# Opsional: kalau endpoint ini butuh API key / anon key
# isi di Railway/GitHub Secrets: NAWALA_API_KEY (atau SUPABASE_ANON_KEY)
NAWALA_API_KEY = os.environ.get("NAWALA_API_KEY", "")  # optional


def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram env belum di-set")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=20)
        print("Telegram resp:", r.status_code, r.text[:200])
    except Exception as e:
        print("Gagal kirim Telegram:", e)


def load_domains() -> List[str]:
    raw = (DOMAINS_ENV or "").strip()
    if not raw:
        return []
    raw = raw.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    # normalisasi: hilangkan http(s):// dan slash
    out = []
    for d in parts:
        x = d.replace("https://", "").replace("http://", "").strip().strip("/")
        if x:
            out.append(x)
    return out


def build_headers() -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://www.nawala.asia",
        "Referer": "https://www.nawala.asia/",
    }
    # Beberapa Supabase Edge Functions butuh Authorization / apikey
    if NAWALA_API_KEY:
        # coba dua header umum supabase
        headers["Authorization"] = f"Bearer {NAWALA_API_KEY}"
        headers["apikey"] = NAWALA_API_KEY
    return headers


def try_call_api(domains: List[str]) -> Tuple[bool, str, Any]:
    """
    Coba beberapa bentuk payload umum:
    1) {"domains": [...]}
    2) {"domainList": [...]}
    3) {"input": "... newline ..."}
    Return: (ok, info, data_or_text)
    """
    headers = build_headers()

    payloads = [
        {"domains": domains},
        {"domainList": domains},
        {"input": "\n".join(domains)},
        {"text": "\n".join(domains)},
    ]

    last_err = None
    for idx, payload in enumerate(payloads, start=1):
        try:
            r = requests.post(API_URL, headers=headers, json=payload, timeout=45)
            ct = (r.headers.get("content-type") or "").lower()
            if r.status_code >= 400:
                last_err = f"HTTP {r.status_code} payload#{idx}: {r.text[:300]}"
                continue

            if "application/json" in ct:
                data = r.json()
                return True, f"OK payload#{idx}", data
            else:
                # kadang edge function return text
                return True, f"OK payload#{idx} (non-json)", r.text

        except Exception as e:
            last_err = f"EXC payload#{idx}: {type(e).__name__}: {e}"

    return False, last_err or "Unknown error", None


def extract_results(data: Any, domains: List[str]) -> Dict[str, str]:
    """
    Usaha parse berbagai bentuk response:
    - list of objects: [{"domain":"x","nawala":"Active",...}]
    - dict with "results": [...]
    - dict keyed by domain: {"x":"Active"} or {"x":{"nawala":"Active"}}
    """
    results: Dict[str, str] = {}

    def norm_status(s: str) -> str:
        t = (s or "").strip().lower()
        if "block" in t or "nawala" in t and "active" not in t:
            return "blocked"
        if "active" in t or "aman" in t or "not blocked" in t:
            return "active"
        return t or "unknown"

    # helper: ambil status nawala dari item dict
    def status_from_item(it: Dict[str, Any]) -> str:
        # kandidat field
        for k in ["nawala", "nawala_status", "status_nawala", "status", "result"]:
            if k in it and isinstance(it[k], (str, int, float)):
                return norm_status(str(it[k]))
        # nested
        for k in ["nawala", "network"]:
            if k in it and isinstance(it[k], dict):
                for kk in ["status", "result", "state"]:
                    if kk in it[k]:
                        return norm_status(str(it[k][kk]))
        return "unknown"

    # case 1: list
    if isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                dom = (it.get("domain") or it.get("host") or it.get("url") or "").strip().lower()
                if dom:
                    results[dom] = status_from_item(it)
        return results

    # case 2: dict
    if isinstance(data, dict):
        # dict results
        if "results" in data and isinstance(data["results"], list):
            for it in data["results"]:
                if isinstance(it, dict):
                    dom = (it.get("domain") or it.get("host") or it.get("url") or "").strip().lower()
                    if dom:
                        results[dom] = status_from_item(it)
            return results

        # dict keyed by domain
        # contoh: {"a.com":"Active"} atau {"a.com":{"nawala":"Active"}}
        for k, v in data.items():
            if isinstance(k, str) and "." in k:
                dom = k.strip().lower()
                if isinstance(v, str):
                    results[dom] = norm_status(v)
                elif isinstance(v, dict):
                    results[dom] = status_from_item(v)

        return results

    return results


def status_to_emoji_label(status: str) -> Tuple[str, str]:
    s = (status or "").lower()
    if "blocked" in s or s == "block":
        return "🔴", "Blocked"
    if "active" in s or "not blocked" in s or "aman" in s:
        return "🟢", "Not Blocked"
    return "⚪", "Unknown"


def main():
    send_telegram(f"✅ RUNNING NAWALA.ASIA API VERSION [{VERSION}]")

    domains = load_domains()
    if not domains:
        send_telegram(f"Domain Status Report (nawala.asia API) [{VERSION}]\nTidak ada domain untuk dicek.")
        return

    ok, info, data = try_call_api(domains)
    if not ok:
        send_telegram(
            f"❌ Gagal call API [{VERSION}]\n"
            f"Endpoint: {API_URL}\n"
            f"Info: {info}\n"
            f"Hint: Jika butuh key, set NAWALA_API_KEY."
        )
        return

    # parse results
    results = extract_results(data, domains)

    # kalau kosong, kirim debug supaya kita lihat struktur response
    if not results:
        preview = ""
        try:
            preview = json.dumps(data, ensure_ascii=False)[:800]
        except Exception:
            preview = str(data)[:800]

        send_telegram(
            f"⚠️ API terpanggil tapi hasil tidak bisa diparse [{VERSION}]\n"
            f"{info}\n"
            f"Endpoint: {API_URL}\n"
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
