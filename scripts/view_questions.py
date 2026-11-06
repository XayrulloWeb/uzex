"""CLI tool to inspect questions asked on the server (local or remote)."""
import json
import sys
import urllib.request
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / 'data' / 'questions_log.jsonl'
REMOTE_URL = 'https://uzex.xayrusha.uz/api/ai/questions-log'


def fetch_remote(limit: int = 50):
    try:
        req = urllib.request.Request(f"{REMOTE_URL}?limit={limit}", headers={'User-Agent': 'uzex-cli/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('questions', [])
    except Exception as exc:
        print(f"Error fetching from remote ({REMOTE_URL}): {exc}")
        return []


def read_local():
    if not LOG_FILE.exists():
        return []
    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        lines = [l.strip() for l in f if l.strip()]
    entries = []
    for l in lines:
        try:
            entries.append(json.loads(l))
        except Exception:
            continue
    return entries


def main():
    limit = 20
    use_remote = '--remote' in sys.argv or '-r' in sys.argv
    for arg in sys.argv[1:]:
        if arg.isdigit():
            limit = int(arg)

    if use_remote:
        entries = fetch_remote(limit)
        source = f"REMOTE ({REMOTE_URL})"
    else:
        entries = read_local()
        source = f"LOCAL ({LOG_FILE})"
        if not entries:
            # Fallback to remote if local is empty
            remote_entries = fetch_remote(limit)
            if remote_entries:
                entries = remote_entries
                source = f"REMOTE FALLBACK ({REMOTE_URL})"

    if not entries:
        print(f"No questions logged yet ({source}).")
        return

    total = len(entries)
    selected = entries[-limit:]

    print(f"\n=== UZEX OBSERVATORY: LATEST {len(selected)} of {total} QUESTIONS [{source}] ===")
    for i, e in enumerate(selected, 1):
        ts = e.get('timestamp', '')[:19].replace('T', ' ')
        ip = e.get('client_ip', 'unknown')
        lang = e.get('lang', 'ru')
        q = e.get('question', '')
        status = e.get('status', '')
        provider = e.get('provider', {})
        p_str = f"{provider.get('kind', '')}:{provider.get('model', '')}" if isinstance(provider, dict) else str(provider)
        ms = e.get('elapsed_ms', 0)
        ans = (e.get('answer') or e.get('reason') or '').replace('\n', ' ')
        if len(ans) > 130:
            ans = ans[:127] + '...'

        print(f"\n[{i}] {ts} (IP: {ip}, {lang.upper()}, {ms}ms, {p_str}) -> Status: {status}")
        print(f"    Q: {q}")
        print(f"    A: {ans}")
    print("\n" + "=" * 55 + "\n")


if __name__ == '__main__':
    main()
