"""补充披露入口：保留来源原文，空值不补造，缓存带来源与时间。"""
import time
from datetime import date
from scripts.market_history import canonical_code
from scripts.verified_sources import dc_page, meta, cache_get, cache_put


def dividends(code, *, transport=None):
    code=canonical_code(code); key='dividends:v1:'+code; cached=cache_get(key)
    if transport is None and cached and time.time()-cached.get('fetched_epoch',0)<86400:return cached
    out=dict(meta('东方财富分红中心 RPT_SHAREBONUS_DET','unavailable'),code=code,rows=[])
    try:
        payload=dc_page('RPT_SHAREBONUS_DET',size=50,sort='REPORT_DATE',filters=f'(SECURITY_CODE="{code[2:]}")',transport=transport)
        for r in payload.get('data') or []:
            if str(r.get('NOTICE_DATE') or '')[:10]>date.today().isoformat():continue
            out['rows'].append({'report_period':str(r.get('REPORT_DATE') or '')[:10],
                'plan_detail':r.get('IMPL_PLAN_PROFILE') or r.get('PLAN_EXPLAIN'),
                'record_date':str(r.get('EQUITY_RECORD_DATE') or '')[:10],
                'ex_dividend_date':str(r.get('EX_DIVIDEND_DATE') or '')[:10],
                'progress':r.get('ASSIGN_PROGRESS')})
        out.update(status='available',provider_count=payload.get('count'),scope='最近50条来源披露')
        if transport is None:cache_put(key,out)
    except Exception as exc:out['error']='分红披露获取失败：'+str(exc)
    return out
