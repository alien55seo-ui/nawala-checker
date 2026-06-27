# check_domains.py
# FINAL VERSION — API Check + Bitly Auto-Update (2 links)
#
# Env Variables di Railway:
#   TELEGRAM_TOKEN
#   TELEGRAM_CHAT_ID
#   DOMAINS_TO_CHECK   (pisah koma) — daftar domain cadangan
#   BITLY_TOKEN        (API token Bitly)
#   BITLY_LINK_ID_1    (ID link bitly pertama,  contoh: boxing-55)
#   BITLY_LINK_ID_2    (ID link bitly kedua,    contoh: boxing55amp)
#   BITLY_LINK_ID_3    (ID link bitly ketiga,   contoh: box55amp)
#   API_KEY            (optional)

import os
import requests
from time import sleep
from typing import Dict, List, Tuple

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DOMAINS_ENV      = os.environ.get("DOMAINS_TO_CHECK", "")
BITLY_TOKEN      = os.environ.get("BITLY_TOKEN", "")
BITLY_LINK_ID_1  = os.environ.get("BITLY_LINK_ID_1", "")
BITLY_LINK_ID_2  = os.environ.get("BITLY_LINK_ID_2", "")
BITLY_LINK_ID_3  = os.environ.get("BITLY_LINK_ID_3", "")
API_KEY          = os.environ.get("API_KEY", "")

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


# ================= BITLY =================
def update_bitly(link_id: str, new_url: str) -> bool:
    """Update destination URL bitly ke domain baru."""
    if not link_id:
        return False
    url = f"https://api-ssl.bitly.com/v4/bitlinks/bit.ly/{link_id}"
    headers = {
        "Authorization": f"Bearer {BITLY_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"long_url": f"https://{new_url}"}
    try:
        resp = requests.patch(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        print(f"[Bitly] bit.ly/{link_id} → https://{new_url}", flush=True)
        return True
    except Exception as e:
        print(f"[Bitly] Gagal update bit.ly/{link_id}: {e}", flush=True)
        return False


def update_all_bitly_links(active_domain: str) -> List[str]:
    """Update semua bitly links ke domain aktif. Return list link yang berhasil."""
    updated = []
    for link_id in [BITLY_LINK_ID_1, BITLY_LINK_ID_2, BITLY_LINK_ID_3]:
        if link_id:
            ok = update_bitly(link_id, active_domain)
            if ok:
                updated.append(f"bit.ly/{link_id}")
            sleep(1)  # jaga rate limit Bitly
    return updated


# ================= MAIN =================
def main():
    print("=== Nawala Checker + Bitly Auto-Update START ===", flush=True)
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

    # Pisahkan domain aman vs diblokir
    safe_domains    = [d for d in domains if not all_results.get(d, False)]
    blocked_domains = [d for d in domains if all_results.get(d, False)]

    print(f"Aman: {len(safe_domains)} | Diblokir: {len(blocked_domains)}", flush=True)

    # Update semua Bitly ke domain aman pertama
    updated_links = []
    new_active_domain = ""

    if BITLY_TOKEN and safe_domains:
        new_active_domain = safe_domains[0]
        updated_links = update_all_bitly_links(new_active_domain)

    # Susun laporan Telegram
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

    if updated_links:
        lines.append(f"\n🔗 Bitly diupdate ke: {new_active_domain}")
        for link in updated_links:
            lines.append(f"   • {link}")
    elif blocked_domains and not safe_domains:
        lines.append("\n🚨 SEMUA DOMAIN DIBLOKIR! Tambah domain cadangan baru.")
    elif not BITLY_TOKEN:
        lines.append("\n⚠️ BITLY_TOKEN belum diset di Railway Variables.")

    report = "\n".join(lines)
    print(report, flush=True)
    send_telegram(report)
    print("=== SELESAI ===", flush=True)


if __name__ == "__main__":
    main()c
