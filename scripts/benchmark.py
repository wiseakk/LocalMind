"""Collect reproducible response times. DEMO mode only unless --allow-real is supplied.

Usage: python scripts/benchmark.py --n 20 --key YOUR_KEY
"""
import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import sys
import httpx

p = argparse.ArgumentParser()
p.add_argument('--base', default='http://127.0.0.1:8765')
p.add_argument('--n', type=int, default=20)
p.add_argument('--key', default='')
p.add_argument('--allow-real', action='store_true', help='CAUTION: actuates real home devices')
a = p.parse_args()
if a.n < 1 or a.n > 500:
    sys.exit('--n: 1..500')
headers = {'X-LocalMind-Key': a.key}
with httpx.Client(timeout=120, headers=headers) as client:
    info = client.get(a.base + '/api/info').json()
    if not info.get('demo') and not a.allow_real:
        sys.exit('REAL MODE: benchmark refused. Use --allow-real to explicitly allow switching real devices.')
    rows=[]
    for i in range(a.n):
        text = ('Включи настольную лампу' if i%2==0 else 'Выключи лампу на столе')
        r=client.post(a.base + '/api/chat', json={'text':text,'history':[]})
        r.raise_for_status(); result=r.json()
        rows.append({'timestamp_utc':datetime.now(timezone.utc).isoformat(),
                     'iteration':i+1,'mode':'DEMO' if info.get('demo') else 'REAL',
                     'text':text,'engine':result['engine'],
                     'latency_ms':result['latency_ms'], 'answer':result['answer']})
        print(i+1, result['latency_ms'], 'ms', result['engine'])
out = Path(__file__).resolve().parents[1] / 'benchmark_actual.csv'
with out.open('w', encoding='utf-8-sig', newline='') as f:
    writer=csv.DictWriter(f, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
print('ACTUAL measurements saved:',out)
