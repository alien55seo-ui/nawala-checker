# check_domains.py
# FINAL VERSION — API Check + Cloudflare KV Auto-Update
#
# Env Variables di Railway:
#   TELEGRAM_TOKEN
#   TELEGRAM_CHAT_ID
#   DOMAINS_TO_CHECK   (pisah koma) — daftar domain cadangan
#   CF_API_TOKEN       (Cloudflare API Token)
#   CF_ACCOUNT_ID      (Cloudflare Account ID)
#   CF_KV_NAMESPACE_ID (Cloudflare KV Namespace ID)
#   CF_KV_KEY          (key di KV, contoh: boxing55) — isi sesuai group
#   API_KEY            (optional, API key trustpositif.id)

import os
import requests
from time import sleep
from typing import Dict, List, Tuple

TELEGRAM_TOKEN     = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
DOMAINS_ENV        = os.environ.get("DOMAINS_TO_CHECK", "")
CF_API_TOKEN       = os.environ.get("CF_API_TOKEN", "")
CF_ACCOUNT_ID      = os.environ.get("CF_ACCOUNT_ID", "")
CF_KV_NAMESPACE_ID = os.environ.get("CF_KV_NAMESPACE_ID", "")
CF_KV_KEY          = os.environ.get("CF_KV_KEY", "")
API_KEY            = os.environ.get("API_KEY", "")

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
    """Update KV Cloudflare dengan domain aktif."""
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
    print("=== Nawala Checker + Cloudflare KV START ===", flush=True)
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

    # Update Cloudflare KV
    kv_updated = False
    new_active_domain = ""

    if safe_domains and CF_KV_KEY:
        new_active_domain = safe_domains[0]
        kv_updated = update_cloudflare_kv(CF_KV_KEY, new_active_domain)
    elif not CF_KV_KEY:
        print("[CF] CF_KV_KEY belum diset!", flush=True)

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

    if kv_updated:
        lines.append(f"\n🔗 Redirect aktif: {new_active_domain}")
    elif blocked_domains and not safe_domains:
        lines.append("\n🚨 SEMUA DOMAIN DIBLOKIR! Tambah domain cadangan baru.")
    elif not CF_KV_KEY:
        lines.append("\n⚠️ CF_KV_KEY belum diset di Railway Variables.")

    report = "\n".join(lines)
    print(report, flush=True)
    send_telegram(report)
    print("=== SELESAI ===", flush=True)


if __name__ == "__main__":
    main()
