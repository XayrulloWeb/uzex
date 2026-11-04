"""Official Groq fallback with typed plans and bounded retries."""
import asyncio
import json
import os
import re
import threading
import time

import httpx

from server.provider_errors import ModelUnavailable
from server.question_checks import QuestionMismatch

API='https://api.groq.com/openai/v1'
DEFAULT_MODELS=['qwen/qwen3.8-27b','openai/gpt-oss-120b','llama-3.3-70b-versatile','llama-3.1-8b-instant']


class GroqPool:
    def __init__(self,key=None,models=None,transport=None,discover=True):
        self.key=key
        configured=models or os.getenv('UZEX_GROQ_MODELS','').split(',')
        self.models=list(dict.fromkeys(model.strip() for model in configured if model.strip())) or DEFAULT_MODELS[:]
        if any(not re.fullmatch(r'[A-Za-z0-9._/-]{1,120}',model) for model in self.models):
            raise ValueError('Invalid Groq model identifier')
        self.transport=transport
        self.discover=discover
        self.cooldown={}
        self.auth_until=0.0
        self.next_discovery=0.0
        self.lock=threading.Lock()

    @property
    def configured(self): return bool(self.key)

    def ready(self,model):
        with self.lock:
            now=time.monotonic()
            return now>=self.auth_until and now>=self.cooldown.get(model,0)

    def block(self,model,seconds):
        with self.lock: self.cooldown[model]=time.monotonic()+seconds

    async def _discover(self,client,deadline):
        if not self.discover or time.monotonic()<self.next_discovery:return
        self.next_discovery=time.monotonic()+30
        try:
            response=await client.get(API+'/models',headers={'Authorization':'Bearer '+self.key},timeout=min(4,max(.05,deadline-time.monotonic())))
            if response.status_code!=200:return
            available=[item['id'] for item in response.json().get('data',[]) if isinstance(item,dict) and isinstance(item.get('id'),str)
                       and re.fullmatch(r'[A-Za-z0-9._/-]{1,120}',item['id'])
                       and not any(word in item['id'].lower() for word in ['whisper','tts','speech','audio','guard','embed'])]
            preferred=[model for model in self.models if model in available]
            self.models=list(dict.fromkeys(preferred+sorted(available)))[:6] or self.models
            self.next_discovery=time.monotonic()+900
        except (httpx.HTTPError,ValueError,KeyError,TypeError,AttributeError):
            return

    async def generate(self,system,question,validate,budget=25.0):
        if not self.key:raise ModelUnavailable('not_configured')
        with self.lock:
            if time.monotonic()<self.auth_until:raise ModelUnavailable('all_unavailable')
        mismatch=False
        attempts=0
        try:
            async with asyncio.timeout(max(.01,budget)):
                deadline=time.monotonic()+budget
                async with httpx.AsyncClient(transport=self.transport,trust_env=True,timeout=10) as client:
                    await self._discover(client,deadline)
                    for model in self.models:
                        if time.monotonic()>=deadline:break
                        if not self.ready(model):continue
                        attempts+=1
                        try:
                            response=await client.post(API+'/chat/completions',headers={'Authorization':'Bearer '+self.key},
                                json={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':question}],
                                      'response_format':{'type':'json_object'},'temperature':0,'max_completion_tokens':4096},
                                timeout=min(10,max(.05,deadline-time.monotonic())))
                            if response.status_code in [401,403]:
                                with self.lock:self.auth_until=time.monotonic()+300
                                break
                            if response.status_code==429:
                                raw=response.headers.get('retry-after','60')
                                seconds=float(raw) if raw.replace('.','',1).isdigit() else 60
                                self.block(model,min(3600,max(15,seconds)));continue
                            if response.status_code!=200:
                                self.block(model,300 if response.status_code==404 else 15);continue
                            choice=response.json()['choices'][0]
                            if choice.get('finish_reason') not in [None,'stop']:
                                self.block(model,15);continue
                            text=choice['message']['content']
                            if not isinstance(text,str) or len(text)>16000:raise ValueError('Invalid Groq content')
                            text=re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip())
                            return validate(text),{'kind':'groq','model':model,'attempts':attempts,'used_backup':True}
                        except QuestionMismatch:
                            mismatch=True
                        except httpx.TransportError:
                            self.block(model,15)
                        except (ValueError,KeyError,IndexError,TypeError,AttributeError,json.JSONDecodeError):
                            self.block(model,15)
        except TimeoutError:
            raise ModelUnavailable('question_mismatch' if mismatch else 'deadline') from None
        raise ModelUnavailable('question_mismatch' if mismatch else 'all_unavailable')
