"""Gemini failover. Credentials only come from environment secret bindings."""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from server.question_checks import QuestionMismatch

API = 'https://generativelanguage.googleapis.com/v1beta'
DEFAULT_MODELS = ['gemini-flash-lite-latest', 'gemini-3.1-flash-lite', 'gemini-3.5-flash', 'gemini-3.8-flash', 'gemini-2.5-flash']


class ModelUnavailable(Exception):
    def __init__(self, reason='unavailable'):
        self.reason = reason
        super().__init__(reason)


class GeminiPool:
    def __init__(self, keys=None, models=None, transport=None, discover=True, budget=70.0, groq_key=None):
        self.groq_key = groq_key if groq_key is not None else (os.getenv('UZEX_GROQ_KEY') if keys is None else None)
        self.groq_models = [m.strip() for m in os.getenv('UZEX_GROQ_MODELS', 'qwen/qwen3.8-27b,openai/gpt-oss-120b').split(',') if m.strip()]
        extra_keys = [k.strip() for k in os.getenv('UZEX_GEMINI_KEYS', '').split(',') if k.strip()]
        configured_keys = keys if keys is not None else ([os.getenv('UZEX_GEMINI_KEY_PRIMARY'), os.getenv('UZEX_GEMINI_KEY_BACKUP'), os.getenv('UZEX_GEMINI_KEY_3'), os.getenv('UZEX_GEMINI_KEY_4')] + extra_keys)
        self.keys = list(dict.fromkeys(k for k in configured_keys if k))
        configured_models = models or os.getenv('UZEX_GEMINI_MODELS', '').split(',')
        self.models = list(dict.fromkeys(m.strip() for m in configured_models if m.strip())) or DEFAULT_MODELS[:]
        if any(not re.fullmatch(r'[A-Za-z0-9._/-]{1,100}', m) for m in self.models):
            raise ValueError('Invalid Gemini model identifier')
        self.transport = transport
        self.discover = discover
        self.budget = min(75.0, max(1.0, budget))
        self.cooldown: dict[tuple[int, str], float] = {}
        self.key_cooldown: dict[int, float] = {}
        self._discovered_at = 0.0
        self._lock = threading.Lock()
        self._active = 0

    @property
    def configured(self):
        return bool(self.keys or self.groq_key)

    async def _discover(self, client, deadline):
        if not self.discover or time.monotonic() - self._discovered_at < 900:
            return
        self._discovered_at = time.monotonic()-840
        for index,key in enumerate(self.keys):
            if self.key_cooldown.get(index,0)>time.monotonic():continue
            try:
                response = await client.get(API+'/models', headers={'x-goog-api-key': key}, timeout=min(4.0, max(.1, deadline-time.monotonic())))
                if response.status_code in (401,403):
                    self._block(index,'',300,whole_key=True)
                    continue
                if response.status_code != 200:continue
                available = [m['name'].removeprefix('models/') for m in response.json().get('models', [])
                             if 'generateContent' in m.get('supportedGenerationMethods', []) and re.fullmatch(r'models/[A-Za-z0-9._-]+', m.get('name', ''))]
                if not available:continue
                preferred = [m for m in self.models if m in available]
                fast = [m for m in available if 'flash' in m and not any(x in m for x in ['image', 'audio', 'tts', 'live', 'native', 'embedding'])]
                fast.sort(key=lambda m: ('preview' in m or 'exp' in m, 'lite' not in m, m))
                self.models = list(dict.fromkeys(preferred + fast))[:6] or self.models
                self._discovered_at = time.monotonic()
                return
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                continue

    def _ready(self, index, model):
        with self._lock:
            now = time.monotonic()
            return self.key_cooldown.get(index, 0) <= now and self.cooldown.get((index, model), 0) <= now

    def _block(self, index, model, seconds, whole_key=False):
        with self._lock:
            until = time.monotonic()+seconds
            if whole_key:
                self.key_cooldown[index] = until
            else:
                self.cooldown[index, model] = until

    async def generate(self, system: str, question: str, validate: Callable[[str], Any]):
        if not self.keys and not self.groq_key:
            raise ModelUnavailable('not_configured')
        with self._lock:
            if self._active >= 4:
                raise ModelUnavailable('busy')
            self._active += 1
        attempts = 0
        question_mismatch = False
        try:
            async with asyncio.timeout(self.budget):
                deadline = time.monotonic()+self.budget
                async with httpx.AsyncClient(transport=self.transport, timeout=10.0, trust_env=True) as client:
                    if self.groq_key:
                        for g_model in self.groq_models:
                            attempts += 1
                            try:
                                g_resp = await client.post('https://api.groq.com/openai/v1/chat/completions',
                                    headers={'Authorization': f'Bearer {self.groq_key}', 'Content-Type': 'application/json'},
                                    json={'model': g_model,
                                          'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': question}],
                                          'response_format': {'type': 'json_object'},
                                          'temperature': 0},
                                    timeout=min(10.0, max(.1, deadline-time.monotonic())))
                                if g_resp.status_code == 200:
                                    g_text = g_resp.json()['choices'][0]['message']['content']
                                    plan = validate(g_text)
                                    return plan, {'model': g_model, 'attempts': attempts, 'used_backup': False, 'kind': 'groq'}
                            except QuestionMismatch:
                                question_mismatch = True
                                continue
                            except Exception:
                                continue
                    await self._discover(client, deadline)
                    for index, key in enumerate(self.keys):
                        for model_index, model in enumerate(self.models):
                            if not self._ready(index, model):
                                continue
                            attempts += 1
                            try:
                                generation={'temperature':0,'maxOutputTokens':4096,'responseMimeType':'application/json'}
                                if model.startswith('gemini-2.5-flash'):
                                    generation['thinkingConfig']={'thinkingBudget':0}
                                elif model.startswith('gemini-2.5-pro'):
                                    generation['thinkingConfig']={'thinkingBudget':128}
                                response = await client.post(API+f'/models/{model}:generateContent',
                                    headers={'x-goog-api-key': key},
                                    json={'systemInstruction': {'parts': [{'text': system}]},
                                          'contents': [{'role': 'user', 'parts': [{'text': question}]}],
                                          'generationConfig': generation},
                                    timeout=min(12.0, max(.1, deadline-time.monotonic())))
                                code = response.status_code
                                invalid_api_key=False
                                if code==400:
                                    error=response.json().get('error',{})
                                    invalid_api_key=any(d.get('reason') in ['API_KEY_INVALID','API_KEY_EXPIRED'] for d in error.get('details',[]) if isinstance(d,dict))
                                if code in (401, 403) or invalid_api_key:
                                    self._block(index, model, 300, whole_key=True)
                                    break
                                if code == 429:
                                    raw_delay = response.headers.get('retry-after', '60')
                                    delay = float(raw_delay) if raw_delay.replace('.', '', 1).isdigit() else 60
                                    self._block(index, model, min(3600, max(15, delay)))
                                    continue
                                if code == 404 or code >= 500:
                                    self._block(index, model, 300 if code == 404 else 20)
                                    continue
                                if code != 200:
                                    self._block(index, model, 30)
                                    continue
                                body = response.json()
                                candidate = body.get('candidates', [{}])[0]
                                if candidate.get('finishReason') not in (None, 'STOP'):
                                    self._block(index, model, 20)
                                    continue
                                text = ''.join(p.get('text', '') for p in candidate.get('content', {}).get('parts', []) if not p.get('thought'))
                                if len(text) > 16000:
                                    raise ValueError('Model response too large')
                                text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
                                value = validate(text)
                                return value, {'model': model, 'attempts': attempts, 'used_backup': index > 0 or model_index > 0}
                            except httpx.TransportError:
                                self._block(index, model, 15)
                            except QuestionMismatch:
                                question_mismatch = True
                            except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
                                self._block(index, model, 15)
            raise ModelUnavailable('question_mismatch' if question_mismatch else 'all_unavailable')
        except TimeoutError:
            raise ModelUnavailable('deadline') from None
        finally:
            with self._lock:
                self._active -= 1


_pool: GeminiPool | None = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = GeminiPool()
    return _pool
