"""Real Qwen SSE transport with durable, credential-free checkpoints."""
import asyncio
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import httpx

MODEL = 'qwen3.8-27b'
URL = 'https://openapi.seu.edu.cn/v1/chat/completions'


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8', newline='\n') as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def object_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def append(path, value):
    with Path(path).open('a', encoding='utf-8', newline='\n') as file:
        file.write(json.dumps(value, ensure_ascii=False) + '\n')
        file.flush()


class CallFailure(RuntimeError):
    pass


class Transport:
    def __init__(self, batch, cell, credential, resume_uncertain=False):
        self.batch, self.cell = Path(batch), Path(cell)
        self.key = credential
        self.resume_uncertain = resume_uncertain
        self.sequence = 0
        self.known_tokens = 0
        self.output_tokens = 0
        self.replayed = 0
        self.calls = []

    async def call(self, stage, messages, tools=None, max_tokens=8192):
        if len(json.dumps(messages, ensure_ascii=False)) > 120000:
            raise CallFailure('input_character_budget')
        if self.known_tokens >= 250000 or self.output_tokens + max_tokens > 14336:
            raise CallFailure('cell_token_budget')
        self.sequence += 1
        directory = self.cell / 'calls' / f'{self.sequence:02d}_{stage}'
        payload = dict(model=MODEL, messages=messages, temperature=0, top_p=0.95,
                       presence_penalty=0, frequency_penalty=0, stream=True,
                       stream_options={'include_usage': True}, max_tokens=max_tokens,
                       chat_template_kwargs={'enable_thinking': True})
        if tools:
            payload.update(tools=tools, tool_choice='auto', parallel_tool_calls=False)
        request_hash = object_sha(payload)
        directory.mkdir(parents=True, exist_ok=True)
        if (directory / 'request.json').exists():
            if object_sha(read(directory / 'request.json')) != request_hash:
                raise CallFailure('checkpoint_request_mismatch')
        else:
            save(directory / 'request.json', payload)
        attempts = sorted(directory.glob('attempt_*'))
        for attempt in attempts:
            status = read(attempt / 'status.json')
            if status['state'] == 'completed':
                response = read(attempt / 'response.json')
                if status['response_sha256'] != sha(attempt / 'response.json'):
                    raise CallFailure('cached_response_changed')
                self.replayed += 1
                return self._account(stage, directory, attempt, response, True)
            if status['state'] == 'in_flight' and not self.resume_uncertain:
                raise CallFailure('uncertain_previous_request_requires_explicit_reconciliation')
            if status['state'] == 'cancelled' and not self.resume_uncertain:
                raise CallFailure('previous_request_cancelled_no_automatic_resend')
            if status['state'] == 'failed' and not status.get('retryable') and status.get('reason')!='TimeoutError':
                raise CallFailure('previous_nonretryable_failure')
        # Two physical attempts per logical request, including failures from prior processes.
        for index in range(len(attempts) + 1, 3):
            attempt = directory / f'attempt_{index:02d}'
            attempt.mkdir(exist_ok=False)
            ledger_path = self.batch / 'network_checkpoint.json'
            ledger = read(ledger_path) if ledger_path.exists() else {'network_attempts': 0}
            if ledger['network_attempts'] >= 120:
                save(attempt / 'status.json', {'state': 'not_sent', 'reason': 'batch_request_budget'})
                raise CallFailure('batch_request_budget')
            ledger.update(network_attempts=ledger['network_attempts'] + 1, current=str(attempt.relative_to(self.batch)), updated_at=now())
            status = {'state': 'in_flight', 'started_at': now(), 'request_sha256': request_hash,
                      'stage': stage, 'retry': index > 1, 'global_request_number': ledger['network_attempts']}
            save(attempt / 'status.json', status)
            save(ledger_path, ledger)
            print(f"API {ledger['network_attempts']} {self.cell.name} {stage} attempt{index}", flush=True)
            start = time.monotonic()
            content, reasoning = [], []
            tool_chunks = {}
            usage, finish, first_token = None, None, None
            models = set()
            done = False
            last_save = start
            retryable = False
            try:
                async with asyncio.timeout(900):
                    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=20), trust_env=False, follow_redirects=False) as client:
                        async with client.stream('POST', URL, json=payload, headers={'Authorization': 'Bearer ' + self.key}) as response:
                            status['http_status'] = response.status_code
                            save(attempt / 'status.json', status)
                            if response.status_code != 200:
                                retryable = response.status_code in (429, 502, 503, 504)
                                raise CallFailure('http_status_' + str(response.status_code))
                            with (attempt / 'stream.jsonl').open('w', encoding='utf-8') as stream_file:
                                async for line in response.aiter_lines():
                                    if not line.startswith('data:'):
                                        continue
                                    body = line[5:].strip()
                                    if body == '[DONE]':
                                        done = True
                                        break
                                    chunk = json.loads(body)
                                    stream_file.write(json.dumps(chunk, ensure_ascii=False) + '\n')
                                    stream_file.flush()
                                    if chunk.get('error'):
                                        raise CallFailure('stream_error')
                                    if chunk.get('model'):
                                        models.add(chunk['model'])
                                    usage = chunk.get('usage') or usage
                                    for choice in chunk.get('choices', []):
                                        if choice.get('index', 0) != 0:
                                            raise CallFailure('multiple_choices_not_supported')
                                        delta = choice.get('delta') or {}
                                        c = delta.get('content') or ''
                                        r = delta.get('reasoning') or delta.get('reasoning_content') or ''
                                        content.append(c)
                                        reasoning.append(r)
                                        for part in delta.get('tool_calls') or []:
                                            target = tool_chunks.setdefault(part.get('index', 0), {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                                            target['id'] += part.get('id') or ''
                                            for key in ('name', 'arguments'):
                                                target['function'][key] += (part.get('function') or {}).get(key) or ''
                                        if first_token is None and (c or r or delta.get('tool_calls')):
                                            first_token = time.monotonic() - start
                                        finish = choice.get('finish_reason') or finish
                                    if time.monotonic() - last_save > 2:
                                        status.update(elapsed_seconds=time.monotonic()-start, content_chars=sum(map(len, content)), reasoning_chars=sum(map(len, reasoning)))
                                        save(attempt / 'status.json', status)
                                        last_save = time.monotonic()
                message = {'role': 'assistant', 'content': ''.join(content) or None}
                if tool_chunks:
                    message['tool_calls'] = [tool_chunks[k] for k in sorted(tool_chunks)]
                response_data = {'model': next(iter(models), None), 'message': message, 'reasoning_content': ''.join(reasoning), 'usage': usage, 'finish_reason': finish}
                save(attempt / 'response.json', response_data)
                if models != {MODEL} or not done or finish not in ('stop', 'tool_calls'):
                    raise CallFailure('incomplete_or_wrong_model_response')
                if not tools and (finish != 'stop' or not message['content']):
                    raise CallFailure('generation_not_complete')
                if tools and not message.get('tool_calls') and not message['content']:
                    raise CallFailure('empty_planner_response')
                status.update(state='completed', ended_at=now(), elapsed_seconds=time.monotonic()-start,
                              first_token_seconds=first_token, usage=usage, finish_reason=finish,
                              content_chars=sum(map(len, content)), reasoning_chars=sum(map(len, reasoning)),
                              response_sha256=sha(attempt / 'response.json'))
                save(attempt / 'status.json', status)
                save(directory / 'checkpoint.json', {'state': 'completed', 'selected_attempt': attempt.name, 'request_sha256': request_hash})
                return self._account(stage, directory, attempt, response_data, False)
            except asyncio.CancelledError:
                status.update(state='cancelled', reason='caller_timeout_or_cancellation', elapsed_seconds=time.monotonic()-start, ended_at=now())
                save(attempt / 'status.json', status)
                raise
            except Exception as exc:
                retryable = retryable or isinstance(exc, (httpx.RemoteProtocolError, httpx.ReadError, httpx.ReadTimeout, httpx.ConnectError, httpx.ConnectTimeout))
                status.update(state='failed', error_type=type(exc).__name__, reason=str(exc) if isinstance(exc, CallFailure) else type(exc).__name__,
                              elapsed_seconds=time.monotonic()-start, ended_at=now(), retryable=retryable,
                              partial_content_chars=sum(map(len, content)), partial_reasoning_chars=sum(map(len, reasoning)))
                save(attempt / 'status.json', status)
                if not retryable:
                    raise CallFailure(status['reason']) from None
                print(f"RETRYABLE {self.cell.name} {stage} {status['error_type']}", flush=True)
                if index < 2:
                    await asyncio.sleep(2)
        raise CallFailure('logical_call_attempts_exhausted')

    def _account(self, stage, directory, attempt, response, replayed):
        usage = response.get('usage') or {}
        self.known_tokens += usage.get('total_tokens', 0)
        self.output_tokens += usage.get('completion_tokens', 0)
        self.calls.append({'stage': stage, 'logical_call': str(directory.relative_to(self.cell)),
                           'selected_attempt': attempt.name, 'replayed': replayed, 'usage': usage})
        return response['message']
