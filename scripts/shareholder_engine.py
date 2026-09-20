"""真实披露股东名册；按姓名计数，不从固定候选名单生成。"""
import hashlib
import threading
import time
import unicodedata
from datetime import date
from scripts.market_history import canonical_code
from scripts.verified_sources import dc_page, meta, number, cache_get, cache_put

SOURCE = '东方财富Choice：十大股东披露 RPT_DMSK_HOLDERS'
KEY = 'holders:latest:v1'
_lock = threading.Lock()
_memo = {}
_memo_loaded = {}


def clean_name(value):
    return unicodedata.normalize('NFKC', str(value or '')).strip()


def fetch_holder_snapshot(*, transport=None, today=None, max_pages=5000, start_page=1, workers=4):
    """Bounded parallel pages; failed/duplicate pages remain explicit and resumable."""
    from concurrent.futures import ThreadPoolExecutor
    today = (today or date.today()).isoformat()
    filters = f'(IS_MAX_REPORTDATE="1")(SECURITY_TYPE_CODE="058001001")(NOTICE_DATE<=\'{today}\')'
    rows, seen, pages_seen, errors, completed = [], set(), set(), [], []
    expected, pages, discarded = None, None, 0
    def page_data(page):
        try:
            return page, dc_page('RPT_DMSK_HOLDERS', page=page, size=50, filters=filters,
                sort='NOTICE_DATE,SECURITY_CODE,RANK', sort_types='-1,1,1', transport=transport), None
        except Exception as exc:
            return page, None, '来源请求失败：' + str(exc)
    def consume(result):
        nonlocal discarded
        page, payload, error = result
        if error:
            errors.append({'page':page, 'error':error}); return
        data=payload.get('data') or []
        fingerprint=hashlib.sha256(repr(data).encode()).hexdigest()
        if data and fingerprint in pages_seen:
            errors.append({'page':page, 'error':'来源重复分页'}); return
        pages_seen.add(fingerprint);completed.append(page)
        for raw in data:
            name=clean_name(raw.get('HOLDER_NAME'))
            period=str(raw.get('END_DATE') or '')[:10]
            notice=str(raw.get('NOTICE_DATE') or '')[:10]
            try: code=canonical_code(raw.get('SECURITY_CODE',''))
            except ValueError: discarded+=1;continue
            if not name or not period or period>today or (notice and notice>today):
                discarded+=1;continue
            key=(code,period,name)
            if key in seen:continue
            seen.add(key)
            nature=str(raw.get('HOLDER_TYPE_ORG') or raw.get('HOLDER_NATURE') or raw.get('HOLDER_NEWTYPE') or '')
            cat='individual' if ('个人' in nature or '自然人' in nature) else 'institution' if nature and nature not in ('其他','未知') else 'unknown'
            rows.append({'code':code,'stock_name':raw.get('SECURITY_NAME_ABBR') or code,'name':name,
                'category':cat,'nature':nature or None,'period':period,'notice_date':notice or None,
                'rank':raw.get('RANK'),'hold_num':number(raw.get('HOLD_NUM')),'hold_pct':number(raw.get('HOLD_RATIO')),
                'change_num':number(raw.get('HOLD_NUM_CHANGE')),
                'change_label':raw.get('HOLDNUM_CHANGE_NAME') or raw.get('DIRECTION') or '未提供','source':SOURCE})
    first=page_data(start_page); consume(first)
    if first[1]:
        expected=int(first[1].get('count') or 0);pages=int(first[1].get('pages') or 1)
        last_page=min(pages,start_page+max_pages-1)
        with ThreadPoolExecutor(max_workers=max(1,min(workers,4))) as pool:
            for result in pool.map(page_data,range(start_page+1,last_page+1)):consume(result)
    complete=start_page==1 and pages is not None and len(completed)==pages and not errors
    error=None if complete else '披露仅部分覆盖；'+('部分分页请求失败' if errors else '达到本轮分页上限')
    return dict(meta(SOURCE,'available' if complete else 'partial' if rows else 'unavailable',error),
        rows=rows,complete=complete,count=len(rows),provider_count=expected,provider_pages=pages,
        pages_completed=completed,failed_pages=errors,discarded_records=discarded,
        next_page=(max(completed)+1 if completed else start_page),
        covered_stocks=len({r['code'] for r in rows}),scope='已采集十大股东披露（保留历次采集）；不是全体证券账户',as_of=today)


def get_holder_snapshot(*, refresh=False, fetcher=None, allow_fetch=True):
    with _lock:
        # Memo is database-specific, so tests and isolated services cannot leak data.
        from scripts.stock_db import DB_PATH
        key = (DB_PATH, KEY)
        cached = _memo.get(key) if time.time()-_memo_loaded.get(key,0)<60 else cache_get(KEY)
        _memo_loaded[key]=time.time()
        if cached and not refresh:
            age = time.time() - cached.get('fetched_epoch', 0)
            if age < (30 if cached.get('status') == 'unavailable' else 86400):
                _memo[key] = cached
                return cached
            if not allow_fetch:
                return dict(cached, status='stale', error='缓存已过期，请刷新真实披露')
        if not allow_fetch:
            value = dict(meta(SOURCE, 'unavailable', '股东名册尚未采集'), rows=[], complete=False, count=0, covered_stocks=0)
            _memo[key] = value
            return value
        value = (fetcher or fetch_holder_snapshot)()
        if cached and cached.get('complete') and not value.get('complete'):
            return dict(cached, status='stale', error=value.get('error'))
        if cached and cached.get('rows'):
            merged={(r['code'],r['period'],r['name']):r for r in cached['rows']}
            merged.update({(r['code'],r['period'],r['name']):r for r in value['rows']})
            value['rows']=list(merged.values());value['count']=len(merged)
            value['covered_stocks']=len({r['code'] for r in value['rows']})
            if not value.get('complete'): value['status']='partial'
            if not value.get('complete') and cached.get('as_of')==value.get('as_of'):
                done=sorted(set(cached.get('pages_completed',[])+value.get('pages_completed',[])))
                value['pages_completed']=done
                value['failed_pages']=[r for r in cached.get('failed_pages',[])+value.get('failed_pages',[]) if r['page'] not in done]
                if value.get('provider_pages') and len(done)==value['provider_pages'] and done[0]==1:
                    value.update(complete=True,status='available',error=None)
        if value.get('rows') or value.get('complete'):
            cache_put(KEY, value)
            _memo[key] = value
        return value


def aggregate_holders(rows):
    # Every collected distinct name counts once, including older disclosures.
    # For each name/security pair retain the latest collected position only.
    holders, seen = {}, set()
    for r in sorted(rows,key=lambda r:r['period'],reverse=True):
        name = clean_name(r['name']); key = (r['code'], name)
        if key in seen or not name:
            continue
        seen.add(key)
        h = holders.setdefault(name, {'holder_id': 'SH-' + hashlib.sha256(name.encode()).hexdigest()[:16],
             'holder_name': name, 'category': r['category'], 'companies': [], 'total_holding_amount': None})
        if h['category'] != r['category']:
            h['category'] = 'unknown'
        h['companies'].append({'code': r['code'], 'name': r['stock_name'], 'hold_pct': r['hold_pct'],
                               'hold_num': r['hold_num'], 'period': r['period'], 'holding_amount': None})
    for h in holders.values():
        h['company_count'] = len(h['companies']); h['company_names'] = [c['name'] for c in h['companies']]
        h['category_label'] = {'individual':'个人','institution':'机构','unknown':'类型未提供'}[h['category']]
    return sorted(holders.values(), key=lambda h: (-h['company_count'], h['holder_name']))


class Top10ShareholdersEngine:
    _index_token = None
    _index = {}
    @classmethod
    def get_stock_top10_shareholders(cls, code, name='', top10_circ_pct=None, report_date=None):
        code = canonical_code(code)
        snap = get_holder_snapshot(allow_fetch=False)
        if cls._index_token != id(snap['rows']):
            cls._index = {}
            for row in snap['rows']: cls._index.setdefault(row['code'], []).append(row)
            cls._index_token = id(snap['rows'])
        rows = cls._index.get(code, [])
        period = max((r['period'] for r in rows), default=None)
        rows = [r for r in rows if r['period'] == period]
        holders = [dict(r, relation=r['nature'] or '未提供', change_pct=None,
                        change_type={'增持':'up','增加':'up','减持':'down','减少':'down','新进':'new','不变':'flat'}.get(r['change_label'],'unknown')) for r in rows]
        complete_ranks={int(r['rank']) for r in rows if str(r.get('rank','')).isdigit()} == set(range(1,11))
        def pct(cat=None):
            selected = [r for r in rows if cat is None or r['category'] == cat]
            if not complete_ranks or any(r['hold_pct'] is None for r in rows): return None
            return round(sum(r['hold_pct'] for r in selected), 4)
        return dict(meta(SOURCE, snap['status'] if rows else 'unavailable', snap.get('error')),
                    code=code, name=name, report_date=period, holders=holders, exit_holders=[],
                    disclosure_complete=complete_ranks, collected_holder_count=len(rows),
                    total_pct=pct(), individual_pct=pct('individual'), institution_pct=pct('institution'),
                    changes_summary={'new_count':None,'change_count':None,'exit_count':None},
                    peer_companies=[], peer_companies_str='未计算', peer_holders=[], peer_holders_str='未计算')

    @classmethod
    def enrich_stock_holder_metrics(cls, stock):
        d = cls.get_stock_top10_shareholders(stock['code'])
        stock.update(holder_individual_pct=d['individual_pct'], holder_institution_pct=d['institution_pct'],
                     holder_new_count=None, holder_change_count=None, holder_exit_count=None,
                     peer_companies=[], peer_companies_str='未计算', peer_holders=[], peer_holders_str='未计算',
                     goodwill=None, goodwill_to_cap_pct=None, div_freq=None, div_to_cap_pct=None)
        stock['top10_hold_pct'] = d['total_pct']; stock['report_date'] = d['report_date']
        return stock

    @classmethod
    def aggregate_market_shareholders(cls, all_stocks):
        return aggregate_holders(get_holder_snapshot(allow_fetch=False)['rows'])

    @classmethod
    def get_shareholders_overview(cls, shareholders_list):
        return {'total_holders_count':len(shareholders_list),
                'individual_holders_count':sum(h['category']=='individual' for h in shareholders_list),
                'institution_holders_count':sum(h['category']=='institution' for h in shareholders_list),
                'unknown_holders_count':sum(h['category']=='unknown' for h in shareholders_list),
                'total_holding_amount_yi':None, 'individual_holding_amount_yi':None, 'institution_holding_amount_yi':None}
