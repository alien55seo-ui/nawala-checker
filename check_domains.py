# check_domains.py
# FINAL VERSION — DNS Check langsung (tanpa API, tanpa limit!)
# + Cloudflare KV Auto-Update (2 tombol: daftar & login)
# + Daftar domain dibaca dari Cloudflare KV (dikelola via bot Telegram /add /del)
#   Fallback ke env DOMAINS_TO_CHECK kalau KV kosong/gagal.
#
# Env Variables di Railway:
#   TELEGRAM_TOKEN
#   TELEGRAM_CHAT_ID
#   DOMAINS_TO_CHECK           (fallback, pisah koma)
#   CF_API_TOKEN
#   CF_ACCOUNT_ID
#   CF_KV_NAMESPACE_ID
#   CF_KV_DOMAINS_NAMESPACE_ID (opsional — namespace KV worker nawala-manager;
#                               kalau kosong, pakai CF_KV_NAMESPACE_ID)
#   CF_KV_KEY_DAFTAR
#   CF_KV_KEY_LOGIN

import json
import os
import socket
import requests
from time import sleep
from typing import Dict, List, Tuple

TELEGRAM_TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")
DOMAINS_ENV         = os.environ.get("DOMAINS_TO_CHECK", "")
CF_API_TOKEN        = os.environ.get("CF_API_TOKEN", "")
CF_ACCOUNT_ID       = os.environ.get("CF_ACCOUNT_ID", "")
CF_KV_NAMESPACE_ID  = os.environ.get("CF_KV_NAMESPACE_ID", "")
CF_KV_DOMAINS_NS_ID = os.environ.get("CF_KV_DOMAINS_NAMESPACE_ID", "") or os.environ.get("CF_KV_NAMESPACE_ID", "")
CF_KV_KEY_DAFTAR    = os.environ.get("CF_KV_KEY_DAFTAR", "")
CF_KV_KEY_LOGIN     = os.environ.get("CF_KV_KEY_LOGIN", "")

# Server DNS Nawala & Komdigi (resmi pemerintah)
DNS_SERVERS = [
    "180.131.144.144",  # Nawala primary
    "180.131.145.145",  # Nawala secondary
    "103.155.26.28",    # Komdigi primary
]

# IP halaman blokir — kalau DNS return IP ini = domain diblokir
BLOCK_IPS = {
    "180.131.144.144",
    "180.131.145.145",
    "103.155.26.28",
    "103.155.26.29",
    "36.86.63.185",
    "114.0.0.0",
}


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


def load_domains_from_kv() -> List[str]:
    """Baca daftar domain dari Cloudflare KV (key: domains:<chat_id>),
    yang diisi oleh bot manager Telegram lewat /add dan /del."""
    if not CF_API_TOKEN or not CF_ACCOUNT_ID or not CF_KV_DOMAINS_NS_ID or not TELEGRAM_CHAT_ID:
        return []
    key = f"domains:{TELEGRAM_CHAT_ID}"
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{CF_KV_DOMAINS_NS_ID}/values/{key}"
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 404:
            print(f"[KV] key {key} belum ada (belum pernah /add) — pakai fallback env", flush=True)
            return []
        resp.raise_for_status()
        raw = resp.text.strip()
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return _clean_list(data)
        except json.JSONDecodeError:
            pass
        return _clean_list(raw.replace("\n", ",").split(","))
    except Exception as e:
        print(f"[KV] Gagal baca daftar domain: {type(e).__name__} - {e}", flush=True)
        return []


def load_domains() -> List[str]:
    # 1) Coba dari KV (dikelola bot Telegram)
    kv_domains = load_domains_from_kv()
    if kv_domains:
        print(f"[KV] Daftar domain dari KV: {len(kv_domains)} domain", flush=True)
        return kv_domains
    # 2) Fallback: env DOMAINS_TO_CHECK (cara lama)
    raw = (DOMAINS_ENV or "").strip()
    if not raw:
        return []
    print("[ENV] Pakai daftar domain dari env DOMAINS_TO_CHECK (fallback)", flush=True)
    return _clean_list(raw.replace("\n", ",").split(","))


def chunk(lst: List[str], n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


# ================= DNS CHECK =================
# Status hasil cek: "blocked" | "safe" | "unknown"
#   blocked = ada server yang balas IP halaman blokir
#   safe    = minimal 1 server menjawab dan tidak ada tanda blokir
#   unknown = SEMUA server gagal menjawab (timeout/refused) -> tidak bisa dipastikan
DNS_RETRIES = 2  # jumlah percobaan ulang per server kalau timeout


def check_domain_dns(domain: str) -> str:
    """
    Cek domain via DNS langsung ke server Nawala & Komdigi.
    Return "blocked" / "safe" / "unknown".
    """
    try:
        import dns.resolver

        got_answer = False  # apakah ada server yang berhasil menjawab (apapun isinya)

        for dns_server in DNS_SERVERS:
            for attempt in range(1, DNS_RETRIES + 1):
                try:
                    resolver = dns.resolver.Resolver()
                    resolver.nameservers = [dns_server]
                    resolver.timeout = 5
                    resolver.lifetime = 5

                    answers = resolver.resolve(domain, 'A')
                    got_answer = True
                    for rdata in answers:
                        ip = str(rdata)
                        if ip in BLOCK_IPS:
                            print(f"    {domain}: BLOCKED (via {dns_server} → {ip})", flush=True)
                            return "blocked"
                    break  # server menjawab & tidak blokir -> lanjut ke server berikutnya

                except dns.resolver.NXDOMAIN:
                    # Domain tidak ada di DNS -> server menjawab, dianggap aman
                    got_answer = True
                    break
                except dns.resolver.NoAnswer:
                    # Server menjawab tapi tanpa record A -> tetap dihitung "menjawab"
                    got_answer = True
                    break
                except Exception as e:
                    print(f"    {domain}: DNS error ({dns_server}) percobaan {attempt}/{DNS_RETRIES}: {e}", flush=True)
                    sleep(0.5)
                    continue  # coba lagi server yang sama

        if got_answer:
            return "safe"   # ada server menjawab, tidak ada tanda blokir
        return "unknown"    # tidak ada satu pun server yang menjawab

    except ImportError:
        # Fallback kalau dnspython tidak tersedia
        print("    [WARNING] dnspython tidak tersedia, pakai socket fallback", flush=True)
        try:
            ip = socket.gethostbyname(domain)
            if ip in BLOCK_IPS:
                print(f"    {domain}: BLOCKED (socket → {ip})", flush=True)
                return "blocked"
            return "safe"
        except Exception:
            return "unknown"


def check_domains_dns(domains: List[str]) -> Dict[str, str]:
    """Cek semua domain via DNS. Return dict {domain: status}."""
    results = {}
    for domain in domains:
        status = check_domain_dns(domain)
        results[domain] = status
        if status == "safe":
            print(f"    {domain}: OK", flush=True)
        elif status == "unknown":
            print(f"    {domain}: UNKNOWN (semua server DNS gagal menjawab)", flush=True)
        sleep(0.5)  # jeda kecil antar domain
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
    print("=== Nawala Checker (DNS Mode) START ===", flush=True)
    domains = load_domains()
    print(f"Total domain: {len(domains)}", flush=True)

    if not domains:
        send_telegram("Tidak ada domain untuk dicek.")
        return

    # Cek semua domain via DNS
    print("[DNS] Mengecek domain via server Nawala & Komdigi...", flush=True)
    all_results = check_domains_dns(domains)

    safe_domains    = [d for d in domains if all_results.get(d) == "safe"]
    blocked_domains = [d for d in domains if all_results.get(d) == "blocked"]
    unknown_domains = [d for d in domains if all_results.get(d) == "unknown"]

    print(f"Aman: {len(safe_domains)} | Diblokir: {len(blocked_domains)} | Tidak yakin: {len(unknown_domains)}", flush=True)

    # Pilih domain untuk DAFTAR (ke-1) dan LOGIN (ke-2)
    # Hanya dari domain yang PASTI aman (bukan yang "tidak yakin")
    domain_daftar = safe_domains[0] if len(safe_domains) >= 1 else None
    domain_login  = safe_domains[1] if len(safe_domains) >= 2 else safe_domains[0] if safe_domains else None

    # Update Cloudflare KV
    kv_daftar_ok = False
    kv_login_ok  = False

    if domain_daftar and CF_KV_KEY_DAFTAR:
        kv_daftar_ok = update_cloudflare_kv(CF_KV_KEY_DAFTAR, domain_daftar)
    if domain_login and CF_KV_KEY_LOGIN:
        kv_login_ok = update_cloudflare_kv(CF_KV_KEY_LOGIN, domain_login)

    # Susun laporan Telegram
    ICON = {"blocked": "🔴", "safe": "🟢", "unknown": "⚠️"}
    LABEL = {"blocked": "Blocked", "safe": "Aman", "unknown": "Tidak yakin (DNS timeout)"}
    lines = ["📊 Domain Status Report"]
    for d in domains:
        st = all_results.get(d, "unknown")
        lines.append(f"{ICON[st]} {d}: {LABEL[st]}")

    lines.append("")
    summary = f"✅ Aman: {len(safe_domains)} | 🔴 Diblokir: {len(blocked_domains)}"
    if unknown_domains:
        summary += f" | ⚠️ Tidak yakin: {len(unknown_domains)}"
    lines.append(summary)

    if unknown_domains:
        lines.append("")
        lines.append("⚠️ Server DNS Nawala tidak menjawab untuk sebagian domain — cek manual: " + ", ".join(unknown_domains))

    if kv_daftar_ok or kv_login_ok:
        lines.append("")
        if kv_daftar_ok:
            lines.append(f"🔵 DAFTAR → {domain_daftar}")
        if kv_login_ok:
            lines.append(f"🟡 LOGIN  → {domain_login}")
    elif not safe_domains:
        lines.append("\n🚨 TIDAK ADA DOMAIN AMAN! Tambah domain cadangan baru.")

    report = "\n".join(lines)
    print(report, flush=True)
    send_telegram(report)
    print("=== SELESAI ===", flush=True)


if __name__ == "__main__":
    main()
