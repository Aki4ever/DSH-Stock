"""公开来源请求与可追溯缓存。无数据、失败和陈旧数据分别表示，禁止补造。"""
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from scripts import stock_db

DC_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def request_json(url, params=None):
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'})
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.load(response)


def dc_page(report, *, page=1, size=500, filters='', sort='END_DATE,SECURITY_CODE,RANK', sort_types=None, transport=None):
    params = {'reportName': report, 'columns': 'ALL', 'pageNumber': page, 'pageSize': size,
              'filter': filters, 'sortColumns': sort, 'sortTypes': sort_types or ','.join(['-1'] * len(sort.split(','))),
              'source': 'WEB', 'client': 'WEB'}
    result = (transport or request_json)(DC_URL, params)
    if not isinstance(result, dict) or result.get('success') is not True or not isinstance(result.get('result'), dict):
        raise ValueError('来源未返回有效数据：' + str((result or {}).get('message', '响应异常')))
    return result['result']


def meta(source, status='available', error=None):
    return {'status': status, 'source': source, 'fetched_at': datetime.now(timezone.utc).isoformat(),
            'fetched_epoch': time.time(), 'error': error}


def cache_get(key):
    with stock_db.get_db_connection() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS verified_source_cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        row = conn.execute('SELECT payload FROM verified_source_cache WHERE key=?', (key,)).fetchone()
    if row:
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            return None


def cache_put(key, value):
    with stock_db.get_db_connection() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS verified_source_cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        conn.execute('INSERT INTO verified_source_cache VALUES(?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload',
                     (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
