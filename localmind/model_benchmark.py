"""Reproducible, non-executing Russian screening of installed local models."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
from statistics import mean
from threading import Event, Lock, Thread
import time
import uuid

import httpx
from .settings import ROOT
from .model_manager import installed_detail, ollama_json, response_metrics, positive

_suite_bytes = (ROOT / 'config/model_benchmark.json').read_bytes()
SUITE = json.loads(_suite_bytes)
SUITE_HASH = hashlib.sha256(_suite_bytes).hexdigest()
TOOL = {'type': 'function', 'function': {'name': 'demo_action',
    'description': 'Inert benchmark declaration. Never launches anything.',
    'parameters': {'type': 'object', 'properties': {'app_id': {'type': 'string', 'enum': ['notepad']}},
                   'required': ['app_id'], 'additionalProperties': False}}}
CATEGORIES = ('factual', 'instruction', 'reasoning', 'coding', 'uncertainty', 'structured', 'tools')


class BenchmarkBusy(ValueError):
    pass


def score(task, message):
    """Strict screening with published expected answers; never execute output."""
    answer = message.get('content', '').strip()
    calls = message.get('tool_calls') or []
    kind, expected = task['check'], task['expected']
    if kind == 'tool':
        if len(calls) != 1:
            return False
        return calls[0].get('function') == expected
    if calls:
        return False
    if kind == 'no_tool':
        return answer.casefold() == expected.casefold()
    if kind == 'exact':
        return answer.casefold() == expected.casefold()
    if kind == 'case_exact':
        return answer == expected
    if kind == 'json':
        try:
            value = json.loads(answer)
            # bool is distinct from numeric zero in the schema and comparison.
            return value == expected and type(value.get('authorized')) is bool
        except (ValueError, AttributeError):
            return False
    if kind == 'python_ast':
        if len(answer) > 8192:
            return False
        try:
            return ast.dump(ast.parse(answer), include_attributes=False) == ast.dump(ast.parse(expected), include_attributes=False)
        except (SyntaxError, ValueError, RecursionError):
            return False
    raise ValueError('Unknown suite check')


def aggregate(rows):
    output = {}
    for category in CATEGORIES:
        applicable = [r for r in rows if r['category'] == category and r['status'] != 'unsupported']
        measured = [r for r in applicable if r['status'] == 'measured']
        output[category] = {'passed': sum(r['passed'] for r in measured), 'total': len(applicable),
                            'measured': len(measured), 'method': 'strict deterministic screening',
                            'score': (sum(r['passed'] for r in measured) / len(applicable)
                                      if applicable and len(measured) == len(applicable) else None)}
    latency = [r['latency_ms'] for r in rows if positive(r.get('latency_ms'), zero=True)]
    speed = [(r.get('metrics') or {}).get('tokens_per_second') for r in rows]
    speed = [v for v in speed if positive(v)]
    output['performance'] = {'latency_mean_ms': round(mean(latency), 3) if latency else None,
                             'tokens_per_second_mean': round(mean(speed), 3) if speed else None,
                             'latency_samples': len(latency), 'speed_samples': len(speed),
                             'method': 'arithmetic mean per measured request; includes first model load'}
    return output


def evaluate_model(name, detail, *, cancelled, publish, chat=None, deadline=None):
    chat = chat or ollama_json
    rows = []
    for task in SUITE['tasks']:
        if cancelled.is_set() or (deadline is not None and time.monotonic() >= deadline):
            break
        row = {'id': task['id'], 'category': task['category'], 'prompt': task['prompt'],
               'expected': task['expected'], 'check': task['check'], 'status': 'unsupported',
               'passed': None, 'actual_model': None, 'metrics': None, 'latency_ms': None}
        if task['category'] == 'tools' and 'tools' not in detail.get('capabilities', []):
            row['error'] = 'Native tools capability unavailable; N/A.'
            rows.append(row); publish(rows); continue
        body = {'model': name, 'messages': [{'role': 'system', 'content': SUITE['system']},
                                           {'role': 'user', 'content': task['prompt']},
                                           {'role': 'assistant', 'content': SUITE['assistant_prefill']}],
                'stream': False, 'think': False, 'keep_alive': 300, 'options': dict(SUITE['settings'])}
        if task['category'] == 'tools':
            body['tools'] = [copy.deepcopy(TOOL)]
        if task['check'] == 'json':
            body['format'] = {'type': 'object', 'additionalProperties': False,
                'properties': {'action': {'type': 'string', 'enum': ['none']}, 'authorized': {'type': 'boolean'}},
                'required': ['action', 'authorized']}
        elif task['category'] != 'tools':
            body['format'] = {'type': 'object', 'additionalProperties': False,
                              'properties': {'answer': {'type': 'string'}}, 'required': ['answer']}
        started = time.perf_counter()
        try:
            data = chat('POST', 'chat', body, timeout=60)
            row['latency_ms'] = round((time.perf_counter() - started) * 1000, 3)
            row['metrics'] = response_metrics(data)
            row['actual_model'] = row['metrics']['actual_model']
            row['done_reason'] = data.get('done_reason')
            row['thinking_present'] = bool(data.get('message', {}).get('thinking'))
            if data.get('done') is not True or not row['actual_model']:
                raise ValueError('Incomplete response or identity')
            if row['actual_model'] != name:
                raise ValueError('Response model differs from tested artifact')
            if data.get('done_reason') == 'length':
                raise ValueError('Output budget exhausted; not a completed answer')
            message = data.get('message')
            if not isinstance(message, dict) or not isinstance(message.get('content'), str) or len(message['content']) > 16384:
                raise ValueError('Invalid answer')
            # Do not store Ollama's separate thinking field. Visible content is
            # untrusted synthetic output, never dispatched or executed.
            row['response_content'] = message['content']
            if task['category'] != 'tools' and task['check'] != 'json':
                envelope = json.loads(message['content'])
                if not isinstance(envelope, dict) or set(envelope) != {'answer'} or not isinstance(envelope['answer'], str):
                    raise ValueError('Invalid answer envelope')
                message = {**message, 'content': envelope['answer']}
            row['answer'] = message['content']
            row['tool_calls'] = message.get('tool_calls') or []
            row.update(status='measured', passed=score(task, message))
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            row.update(status='error', passed=False, error='Локальная генерация не завершена, имя модели не совпало или ответ некорректен.')
        rows.append(row)
        publish(rows)
    return {'requested_model': name, 'digest': detail.get('digest'),
            'quantization': (detail.get('details') or {}).get('quantization_level'),
            'capabilities': detail.get('capabilities', []), 'results': rows, 'scores': aggregate(rows),
            'complete': len(rows) == len(SUITE['tasks']) and all(r['status'] in ('measured', 'unsupported') for r in rows)}


class BenchmarkJobs:
    def __init__(self, directory=None):
        self.directory = Path(directory or ROOT / 'results/private/model-benchmarks')
        self.lock = Lock()
        self.jobs = {}
        self.cancel_events = {}

    def running(self):
        with self.lock:
            return bool(self.cancel_events)

    def stop_all(self):
        with self.lock:
            for event in self.cancel_events.values():
                event.set()

    def _path(self, key):
        if not re.fullmatch(r'[a-f0-9]{32}', key):
            raise ValueError('Недопустимый ID результата.')
        return self.directory / (key + '.json')

    def _save(self, job):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(job['id']); temporary = path.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(job, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def start(self, names):
        from .agent import _inference_lock
        if len(names) not in (1, 2) or len(set(names)) != len(names):
            raise ValueError('Выберите одну или две разные установленные модели.')
        details = [installed_detail(name) for name in names]
        if not _inference_lock.acquire(blocking=False):
            raise BenchmarkBusy('Inference занят. Дождитесь ответа или переключения.')
        try:
            with self.lock:
                if len(self.jobs) >= 16:
                    completed = next((k for k, j in self.jobs.items() if j['status'] != 'running'), None)
                    if completed:
                        self.jobs.pop(completed)
                    else:
                        raise ValueError('Все тесты ещё выполняются.')
                key = uuid.uuid4().hex
                self.jobs[key] = {'id': key, 'status': 'running', 'suite_version': SUITE['version'],
                    'suite_hash': SUITE_HASH, 'method': SUITE['method'], 'settings': dict(SUITE['settings']),
                    'reasoning': False, 'system_prompt': SUITE['system'], 'models': [], 'requested_models': names,
                    'assistant_prefill': SUITE['assistant_prefill'],
                    'progress': {'completed': 0, 'total': len(names) * len(SUITE['tasks'])},
                    'manual_ratings': {}, 'created_at': time.time(), 'error': None}
                self.cancel_events[key] = Event()
                self._save(self.jobs[key])
                Thread(target=self._run, args=(key, list(zip(names, details)), _inference_lock),
                       daemon=True, name='localmind-benchmark').start()
                return copy.deepcopy(self.jobs[key])
        except BaseException:
            if 'key' in locals():
                with self.lock:
                    self.jobs.pop(key, None)
                    self.cancel_events.pop(key, None)
            _inference_lock.release()
            raise

    def _run(self, key, pairs, inference_lock):
        try:
            deadline = time.monotonic() + 600
            for name, detail in pairs:
                if self.cancel_events[key].is_set() or time.monotonic() > deadline:
                    break
                def publish(rows):
                    with self.lock:
                        self.jobs[key]['progress']['completed'] = sum(len(m['results']) for m in self.jobs[key]['models']) + len(rows)
                        self.jobs[key]['current_model'] = {'requested_model': name, 'results': copy.deepcopy(rows)}
                        self._save(self.jobs[key])
                result = evaluate_model(name, detail, cancelled=self.cancel_events[key], publish=publish, deadline=deadline)
                # Revalidate artifact after the run. A changing tag cannot be
                # presented as a reproducible completed comparison.
                after = installed_detail(name)
                if not detail.get('digest') or after.get('digest') != detail['digest']:
                    result.update(complete=False, error='Digest изменился или недоступен.')
                try:
                    from .model_manager import placement
                    running = next((m for m in ollama_json('GET', 'ps').get('models', []) if m.get('name') == name), None)
                    result['placement'] = ({'mode': placement(running), 'size': running.get('size'),
                        'size_vram': running.get('size_vram'), 'context': running.get('context_length'), 'source': '/api/ps'}
                        if running else {'mode': 'unknown', 'source': '/api/ps'})
                except (httpx.HTTPError, ValueError, TypeError):
                    result['placement'] = {'mode': 'unknown', 'source': '/api/ps unavailable'}
                with self.lock:
                    self.jobs[key]['models'].append(result)
                    self.jobs[key].pop('current_model', None)
            with self.lock:
                job = self.jobs[key]
                complete = len(job['models']) == len(pairs) and all(m['complete'] for m in job['models'])
                job.update(status='completed' if complete else 'incomplete', finished_at=time.time())
                self._save(job)
        except Exception:
            with self.lock:
                self.jobs[key].update(status='incomplete', error='Тест или запись результатов прерваны. Полное сравнение не подтверждено.')
                try:
                    self._save(self.jobs[key])
                except OSError:
                    self.jobs[key]['error'] = 'Не удалось сохранить результаты; они доступны только до перезапуска.'
        finally:
            with self.lock:
                self.cancel_events.pop(key, None)
            inference_lock.release()

    def snapshot(self, key=None):
        with self.lock:
            if key is not None:
                if key not in self.jobs:
                    path = self._path(key)
                    if not path.is_file() or path.stat().st_size > 2097152:
                        raise ValueError('Результат не найден.')
                    if path.is_symlink() or path.resolve().parent != self.directory.resolve():
                        raise ValueError('Результат недоступен.')
                    if len(self.jobs) >= 16:
                        completed = next((k for k, j in self.jobs.items() if j['status'] != 'running'), None)
                        if completed is None:
                            raise ValueError('Кэш тестов занят.')
                        self.jobs.pop(completed)
                    self.jobs[key] = json.loads(path.read_text(encoding='utf-8'))
                    if self.jobs[key]['status'] == 'running':
                        self.jobs[key]['status'] = 'incomplete'
                return copy.deepcopy(self.jobs[key])
            # Saved results are explicit synthetic test answers, not chat/audio.
            saved = []
            if self.directory.is_dir():
                for path in sorted(self.directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:16]:
                    if re.fullmatch('[a-f0-9]{32}', path.stem) and path.stem not in self.jobs:
                        saved.append({'id': path.stem, 'status': 'saved'})
            return [{'id': j['id'], 'status': j['status'], 'requested_models': j.get('requested_models')} for j in self.jobs.values()] + saved

    def cancel(self, key):
        with self.lock:
            if key not in self.cancel_events:
                raise ValueError('Тест уже завершён или недоступен.')
            self.cancel_events[key].set()
        return {'id': key, 'status': 'cancel_requested', 'notice': 'Текущий ограниченный запрос завершается; следующие задания не запускаются.'}

    def rate(self, key, model, rating):
        self.snapshot(key)
        with self.lock:
            job = copy.deepcopy(self.jobs[key])
            if job['status'] not in ('completed', 'incomplete') or model not in job['requested_models']:
                raise ValueError('Дождитесь завершения теста и выберите протестированную модель.')
            if type(rating) is not int or not 1 <= rating <= 5:
                raise ValueError('Ручной рейтинг от 1 до 5.')
            job['manual_ratings'][model] = rating
            self._save(job)
            self.jobs[key] = job
            return copy.deepcopy(job)


benchmarks = BenchmarkJobs()
