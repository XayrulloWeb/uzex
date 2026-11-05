"""Persistent audit log of questions asked on the server."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from server.db import ROOT

LOG_FILE = ROOT / 'data' / 'questions_log.jsonl'
_lock = threading.Lock()


def log_question(
    question: str,
    lang: str = 'ru',
    status: str = 'answer',
    answer: str = '',
    provider: dict | None = None,
    elapsed_ms: int = 0,
    reason: str | None = None,
    client_ip: str | None = None,
):
    try:
        if client_ip == 'testclient':
            return
        now = datetime.now(ZoneInfo('Asia/Tashkent')).isoformat()
        entry = {
            'timestamp': now,
            'client_ip': client_ip or '',
            'lang': lang,
            'question': question,
            'status': status,
            'reason': reason,
            'provider': provider,
            'elapsed_ms': elapsed_ms,
            'answer': answer,
        }
        line = json.dumps(entry, ensure_ascii=False) + '\n'
        with _lock:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(line)
    except Exception:
        pass


def get_recent_questions(limit: int = 50):
    try:
        if not LOG_FILE.exists():
            return []
        with _lock:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                lines = [l.strip() for l in f if l.strip()]
        entries = []
        for line in reversed(lines[-limit:]):
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
        return entries
    except Exception:
        return []
