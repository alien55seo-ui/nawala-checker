# check_domains.py
# VERSI API — Cek status blokir lewat API RESMI Trust Positif (Kominfo)
# Hasil sama persis dengan website trustpositif.id (bukan lagi tebak-tebakan DNS).
# + Daftar domain diambil langsung dari env DOMAINS_TO_CHECK (Railway)
# + Cloudflare KV Auto-Update tombol DAFTAR & LOGIN
#
# Env Variables di Railway:
#   TELEGRAM_TOKEN
#   TELEGRAM_CHAT_ID
#   DOMAINS_TO_CHECK           (WAJIB — daftar domain, pisah koma/newline)
#   TRUSTPOSITIF_API_KEY       (opsional — tp_xxx; tanpa key tetap jalan mode freemium)
#   CF_API_TOKEN
#   CF_ACCOUNT_ID
#   CF_KV_NAMESPACE_ID
#   CF_KV_KEY_DAFTAR
#   CF_KV_KEY_LOGIN

import json
import os
import requests
from time import sleep
from typing import Dict, List

TELEGRAM_TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")
DOMAINS_ENV         = os.environ.get("DOMAINS_TO_CHECK", "")
TP_API_KEY          = os.environ.get("TRUSTPOSITIF_API_KEY", "")
CF_API_TOKEN        = os.environ.get("CF_API_TOKEN", "")
CF_ACCOUNT_ID       = os.environ.get("CF_ACCOUNT_ID", "")
CF_KV_NAMESPACE_ID  = os.environ.get("CF_KV_NAMESPACE_ID", "")
CF_KV_KEY_DAFTAR    = os.environ.get("CF_KV_KEY_DAFTAR", "")
CF_KV_KEY_LOGIN     = os.environ.get("CF_KV_KEY_LOGIN", "")

TP_API_URL     = "https://trustpositif.id/api/v1/check"
TP_BATCH_SIZE  = 100   # API max 100 domain/request
TP_RETRIES     = 2     # coba ulang kalau request gagal


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
def _clean_list(parts: List[str]) -> List[str]:
    out = []
    for d in parts:
        x = str(d).replace("https://", "").replace("http://", "").strip().strip("/")
        if x:
            out.append(x.lower())
    return out


def load_domains() -> List[str]:
    """Daftar domain diambil langsung dari env DOMAINS_TO_CHECK (Railway)."""
    raw = (DOMAINS_ENV or "").strip()
    if not raw:
        return []
    print("[ENV] Daftar domain dari DOMAINS_TO_CHECK (Railway)", flush=True)
    return _clean_list(raw.replace("\n", ",").split(","))


def chunk(lst: List[str], n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


# ================= CEK VIA API TRUST POSITIF =================
# Status: "blocked" | "safe" | "unknown"
#   blocked = API bilang Blocked: true
#   safe    = API bilang Blocked: false
#   unknown = request API gagal / domain tidak ada di hasil
def check_batch_api(domains: List[str]) -> Dict[str, str]:
    results = {d: "unknown" for d in domains}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if TP_API_KEY:
        headers["X-API-Key"] = TP_API_KEY
    payload = {"domains": "\n".join(domains)}

    for attempt in range(1, TP_RETRIES + 1):
        try:
            resp = requests.post(TP_API_URL, headers=headers, json=payload, timeout=70)
            if resp.status_code != 200:
                print(f"[API] HTTP {resp.status_code} (percobaan {attempt}/{TP_RETRIES}): {resp.text[:300]}", flush=True)
                sleep(2)
                continue
            data = resp.json()
            if not data.get("success"):
                print(f"[API] success=false: {data.get('message')}", flush=True)
                return results
            by_domain = {}
            for item in data.get("results", []):
                dom = str(item.get("Domain", "")).strip().lower()
                by_domain[dom] = bool(item.get("Blocked"))
            for d in domains:
                if d in by_domain:
                    results[d] = "blocked" if by_domain[d] else "safe"
            st = data.get("stats", {})
            if isinstance(st, dict) and st.get("quota"):
                q = st["quota"]
                print(f"[API] OK — kuota sisa: {q.get('remaining')}/{q.get('total')} ({st.get('package_name','')})", flush=True)
            else:
                print("[API] OK", flush=True)
            return results
        except Exception as e:
            print(f"[API] Error (percobaan {attempt}/{TP_RETRIES}): {type(e).__name__} - {e}", flush=True)
            sleep(2)
    return results


def check_domains_api(domains: List[str]) -> Dict[str, str]:
    results: Dict[str, str] = {}
    for batch in chunk(domains, TP_BATCH_SIZE):
        results.update(check_batch_api(batch))
    for d in domains:
        st = results.get(d, "unknown")
        print(f"    {d}: {st.upper()}", flush=True)
    return results


# ================= CLOUDFLARE KV =================
def update_cloudflare_kv(key: str, value: str) -> bool:
    if not CF_API_TOKEN or not CF_ACCOUNT_ID or not CF_KV_NAMESPACE_ID:
        print("[CF] Cloudflare env belum lengkap!", flush=True)
        return False
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{CF_KV_NAMESPACE_ID}/values/{key}"
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "text/plain"}
    try:
        resp = requests.put(url, headers=headers, data=value, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            print(f"[CF] KV updated: {key} = {value}", flush=True)
            return True
        print(f"[CF] KV update gagal: {data}", flush=True)
        return False
    except Exception as e:
        print(f"[CF] Error: {type(e).__name__} - {e}", flush=True)
        return False


# ================= MAIN =================
def main():
    print("=== Nawala Checker (API Trust Positif) START ===", flush=True)
    domains = load_domains()
    print(f"Total domain: {len(domains)}", flush=True)
    if not domains:
        send_telegram("Tidak ada domain untuk dicek.")
        return

    print("[API] Mengecek domain via API resmi Trust Positif...", flush=True)
    all_results = check_domains_api(domains)

    safe_domains    = [d for d in domains if all_results.get(d) == "safe"]
    blocked_domains = [d for d in domains if all_results.get(d) == "blocked"]
    unknown_domains = [d for d in domains if all_results.get(d) == "unknown"]
    print(f"Aman: {len(safe_domains)} | Diblokir: {len(blocked_domains)} | Tidak yakin: {len(unknown_domains)}", flush=True)

    # Tombol DAFTAR (ke-1) & LOGIN (ke-2) — hanya dari domain yang PASTI aman
    domain_daftar = safe_domains[0] if len(safe_domains) >= 1 else None
    domain_login  = safe_domains[1] if len(safe_domains) >= 2 else safe_domains[0] if safe_domains else None

    kv_daftar_ok = False
    kv_login_ok  = False
    if domain_daftar and CF_KV_KEY_DAFTAR:
        kv_daftar_ok = update_cloudflare_kv(CF_KV_KEY_DAFTAR, domain_daftar)
    if domain_login and CF_KV_KEY_LOGIN:
        kv_login_ok = update_cloudflare_kv(CF_KV_KEY_LOGIN, domain_login)

    # Laporan Telegram
    ICON = {"blocked": "\U0001F534", "safe": "\U0001F7E2", "unknown": "⚠️"}
    LABEL = {"blocked": "Blocked", "safe": "Aman", "unknown": "Tidak yakin (API error)"}
    lines = ["\U0001F4CA Domain Status Report"]
    for d in domains:
        st = all_results.get(d, "unknown")
        lines.append(f"{ICON[st]} {d}: {LABEL[st]}")
    lines.append("")
    summary = f"✅ Aman: {len(safe_domains)} | \U0001F534 Diblokir: {len(blocked_domains)}"
    if unknown_domains:
        summary += f" | ⚠️ Tidak yakin: {len(unknown_domains)}"
    lines.append(summary)

    if unknown_domains:
        lines.append("")
        lines.append("⚠️ API tidak menjawab untuk sebagian domain — cek manual: " + ", ".join(unknown_domains))

    if kv_daftar_ok or kv_login_ok:
        lines.append("")
        if kv_daftar_ok:
            lines.append(f"\U0001F535 DAFTAR → {domain_daftar}")
        if kv_login_ok:
            lines.append(f"\U0001F7E1 LOGIN  → {domain_login}")
    elif not safe_domains and not unknown_domains:
        lines.append("\n\U0001F6A8 SEMUA DOMAIN DIBLOKIR! Tambah domain cadangan baru.")

    report = "\n".join(lines)
    print(report, flush=True)
    send_telegram(report)
    print("=== SELESAI ===", flush=True)


if __name__ == "__main__":
    main()
