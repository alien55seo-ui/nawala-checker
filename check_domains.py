# check_domains.py
# FINAL VERSION — API Check + Cloudflare KV (2 tombol: daftar & login)
#
# Env Variables di Railway:
#   TELEGRAM_TOKEN
#   TELEGRAM_CHAT_ID
#   DOMAINS_TO_CHECK     (pisah koma) — daftar domain cadangan
#   CF_API_TOKEN         (Cloudflare API Token)
#   CF_ACCOUNT_ID        (Cloudflare Account ID)
#   CF_KV_NAMESPACE_ID   (Cloudflare KV Namespace ID)
#   CF_KV_KEY_DAFTAR     (key KV untuk tombol DAFTAR, contoh: boxing55-daftar)
#   CF_KV_KEY_LOGIN      (key KV untuk tombol LOGIN,  contoh: boxing55-login)
#   API_KEY              (optional)

import os
import requests
from time import sleep
from typing import Dict, List, Tuple

TELEGRAM_TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")
DOMAINS_ENV         = os.environ.get("DOMAINS_TO_CHECK", "")
CF_API_TOKEN        = os.environ.get("CF_API_TOKEN", "")
CF_ACCOUNT_ID       = os.environ.get("CF_ACCOUNT_ID", "")
CF_KV_NAMESPACE_ID  = os.environ.get("CF_KV_NAMESPACE_ID", "")
CF_KV_KEY_DAFTAR    = os.environ.get("CF_KV_KEY_DAFTAR", "")
CF_KV_KEY_LOGIN     = os.environ.get("CF_KV_KEY_LOGIN", "")
API_KEY             = os.environ.get("API_KEY", "")

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


# ================= API CHECK =================
def check_batch_api(domains: List[str]) -> Dict[str, bool]:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    payload = {"domains": "\n".join(domains)}
    print(f"[API] Mengecek {len(domains)} domain...", flush=True)

    resp = requests.post(API_URL, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    results = {}
    for item in data.get("results", []):
        domain = item.get("Domain", "").lower().strip()
        blocked = item.get("Blocked", False)
        if domain:
            results[domain] = blocked
            status = "BLOCKED" if blocked else "OK"
            print(f"    {domain}: {status}", flush=True)
    return results


# ================= CLOUDFLARE KV =================
def update_cloudflare_kv(key: str, value: str) -> bool:
    if not CF_API_TOKEN or not CF_ACCOUNT_ID or not CF_KV_NAMESPACE_ID:
        print("[CF] Cloudflare env belum lengkap!", flush=True)
        return False

    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{CF_KV_NAMESPACE_ID}/values/{key}"
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "text/plain",
    }
    try:
        resp = requests.put(url, headers=headers, data=value, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            print(f"[CF] KV updated: {key} = {value}", flush=True)
            return True
        else:
            print(f"[CF] KV update gagal: {data}", flush=True)
            return False
    except Exception as e:
        print(f"[CF] Error: {type(e).__name__} - {e}", flush=True)
        return False


# ================= MAIN =================
def main():
    print("=== Nawala Checker + Cloudflare KV (2 tombol) START ===", flush=True)
    domains = load_domains()
    print(f"Total domain: {len(domains)}", flush=True)

    if not domains:
        send_telegram("Tidak ada domain untuk dicek.")
        return

    # Cek semua domain
    all_results: Dict[str, bool] = {}
    for i, batch in enumerate(chunk(domains, 10)):
        try:
            res = check_batch_api(batch)
            all_results.update(res)
        except Exception as e:
            msg = f"❌ Error cek domain: {type(e).__name__} - {e}"
            print(msg, flush=True)
            send_telegram(msg)
            return
        if i > 0:
            sleep(6)

    safe_domains    = [d for d in domains if not all_results.get(d, False)]
    blocked_domains = [d for d in domains if all_results.get(d, False)]

    print(f"Aman: {len(safe_domains)} | Diblokir: {len(blocked_domains)}", flush=True)

    # Pilih domain untuk tombol DAFTAR (domain aman ke-1)
    # Pilih domain untuk tombol LOGIN  (domain aman ke-2, berbeda dari DAFTAR)
    domain_daftar = safe_domains[0] if len(safe_domains) >= 1 else None
    domain_login  = safe_domains[1] if len(safe_domains) >= 2 else safe_domains[0] if safe_domains else None

    # Update KV
    kv_daftar_ok = False
    kv_login_ok  = False

    if domain_daftar and CF_KV_KEY_DAFTAR:
        kv_daftar_ok = update_cloudflare_kv(CF_KV_KEY_DAFTAR, domain_daftar)

    if domain_login and CF_KV_KEY_LOGIN:
        kv_login_ok = update_cloudflare_kv(CF_KV_KEY_LOGIN, domain_login)

    # Susun laporan
    lines = ["📊 Domain Status Report"]
    for d in domains:
        blocked = all_results.get(d, None)
        if blocked is None:
            lines.append(f"⚪ {d}: Tidak ada data")
        elif blocked:
            lines.append(f"🔴 {d}: Blocked")
        else:
            lines.append(f"🟢 {d}: Aman")

    lines.append("")
    lines.append(f"✅ Aman: {len(safe_domains)} | 🔴 Diblokir: {len(blocked_domains)}")

    if kv_daftar_ok or kv_login_ok:
        lines.append("")
        if kv_daftar_ok:
            lines.append(f"🔵 DAFTAR → {domain_daftar}")
        if kv_login_ok:
            lines.append(f"🟡 LOGIN  → {domain_login}")
    elif blocked_domains and not safe_domains:
        lines.append("\n🚨 SEMUA DOMAIN DIBLOKIR! Tambah domain cadangan baru.")

    report = "\n".join(lines)
    print(report, flush=True)
    send_telegram(report)
    print("=== SELESAI ===", flush=True)


if __name__ == "__main__":
    main()
