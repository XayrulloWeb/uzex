"""CLI tool to inspect questions asked on the server."""
import json
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / 'data' / 'questions_log.jsonl'


def main():
    limit = 20
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        limit = int(sys.argv[1])

    if not LOG_FILE.exists():
        print(f"No questions logged yet ({LOG_FILE} not found).")
        return

    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        lines = [l.strip() for l in f if l.strip()]

    if not lines:
        print("Log is empty.")
        return

    entries = []
    for l in lines:
        try:
            entries.append(json.loads(l))
        except Exception:
            continue

    total = len(entries)
    selected = entries[-limit:]

    print(f"\n=== UZEX OBSERVATORY: LATEST {len(selected)} of {total} QUESTIONS ===")
    for i, e in enumerate(selected, 1):
        ts = e.get('timestamp', '')[:19].replace('T', ' ')
        ip = e.get('client_ip', 'unknown')
        lang = e.get('lang', 'ru')
        q = e.get('question', '')
        status = e.get('status', '')
        provider = e.get('provider', {})
        p_str = f"{provider.get('kind', '')}:{provider.get('model', '')}" if provider else "none"
        ms = e.get('elapsed_ms', 0)
        ans = (e.get('answer') or '').replace('\n', ' ')
        if len(ans) > 120:
            ans = ans[:117] + '...'

        print(f"\n[{i}] {ts} (IP: {ip}, {lang.upper()}, {ms}ms, {p_str}) -> Status: {status}")
        print(f"    Q: {q}")
        print(f"    A: {ans}")
    print("\n" + "=" * 55 + "\n")


if __name__ == '__main__':
    main()
