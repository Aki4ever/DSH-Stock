"""真实行情采集；旧无来源缓存不进入产品。"""
import time
from datetime import datetime
from scripts.anti_crawler import robust_fetch
from scripts.verified_sources import number, meta, cache_put, cache_get

FIELDS={'price':3,'prev_close':4,'open':5,'high':33,'low':34,'volume':6,'turnover_rate':38,'pe':39,'market_cap':45,'circulating_cap':44,'change':31,'change_pct':32}


def fetch_quotes(codes):
    result=[]
    for start in range(0,len(codes),45):
        batch=codes[start:start+45]
        url='https://qt.gtimg.cn/q='+','.join(batch)
        content=robust_fetch(url,referer='https://gu.qq.com',timeout=4,max_retries=1,encoding='gbk')
        for line in (content or '').split(';'):
            if '=' not in line:continue
            k,value=line.strip().split('=',1);code=k.replace('v_','').strip();parts=value.strip().strip('"').split('~')
            if code not in batch or len(parts)<46:continue
            row={key:number(parts[i]) for key,i in FIELDS.items()}
            if not row['price']:continue
            try: quote_time=datetime.strptime(parts[30], '%Y%m%d%H%M%S')
            except ValueError: continue
            if quote_time.date()>datetime.now().date():continue
            row.update(code=code,name=parts[1],timestamp=parts[30],is_mock=False,quote_meta=meta('腾讯证券公开行情'))
            n=number(parts[37]);row['turnover']=n*10000 if n is not None else None
            row['turnover_yi']=n/10000 if n is not None else None
            # Tencent volume is in lots. The list uses lots; provenance makes units explicit.
            row['quote_meta']['volume_unit']='手';row['quote_meta']['source_url']=url;row['quote_meta']['quote_time']=parts[30]
            for old,new in [('change_val','change'),('open_p','open'),('high_p','high'),('low_p','low')]:row[old]=row.get(new)
            cache_put('quote:v2:'+code,row);result.append(row)
    return result


def clean_legacy_stock(row, keep_constituent=False):
    """
    把「旧版未验证行情」相关字段一律置空（REQ-012 禁止无来源数据冒充）。

    `keep_constituent`（默认 False，保持原有行为不变）：
        默认把 `is_csi50/is_csi100` 置空并标 `constituent_status='unverified'`，因为
        **行情行**携带的成分标记属未核验来源。
        但 `stock_db.load_all_stocks_from_db()` 读的是 **stocks_master 的名单标记位**，
        其来源由 `config/constituents.json` 的 `verified_source/as_of` 背书（未核验时名单
        不会被加载、也不会写回该列），属已核验口径；该调用点传 `keep_constituent=True`，
        修掉「名单已核验却在内存里被清空」造成的恒 0 死功能。
    """
    row=dict(row)
    for key in ['ipo_date','listing_years','dividend_count','dividend_total_amount','top10_hold_pct','top10_circ_hold_pct','report_date','avg_daily_amount','profit_years']:
        row[key]=None
    for key in list(FIELDS)+['turnover','turnover_yi','change_val','open_p','high_p','low_p']:row[key]=None
    if keep_constituent:
        row['constituent_status']='verified' if (row.get('is_csi50') or row.get('is_csi100')) else 'not_listed'
    else:
        row['is_csi50']=None;row['is_csi100']=None;row['constituent_status']='unverified';
    row['timestamp']=None;row['quote_meta']=meta(None,'unavailable','旧数据未验证，待重新获取')
    cached=cache_get('quote:v2:'+row['code'])
    if cached:
        row.update(cached)
        for old,new in [('change_val','change'),('open_p','open'),('high_p','high'),('low_p','low')]:row[old]=cached.get(new)
        if time.time()-cached['quote_meta']['fetched_epoch']>300:row['quote_meta']=dict(cached['quote_meta'],status='stale')
    return row
