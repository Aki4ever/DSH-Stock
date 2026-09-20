"""指数行情、历史均来自同一真实来源；失败不合成报价。"""
from scripts.verified_quotes import fetch_quotes
from scripts.history_service import get_daily_history
from scripts.real_chart_engine import fetch_real_timeline
from scripts.verified_sources import meta
class IndexEngine:
    INDEX_CODES=['sh000001','sz399001']
    @classmethod
    def get_indices_list(cls):
        rows={r['code']:r for r in fetch_quotes(cls.INDEX_CODES)}
        return [rows.get(c,dict(code=c,name=n,price=None,prev_close=None,change=None,change_pct=None,turnover_yi=None,timestamp=None,status='unavailable')) for c,n in [('sh000001','上证指数'),('sz399001','深证成指')]]
    @classmethod
    def get_index_detail(cls,code):
        if code not in cls.INDEX_CODES:return None
        row=next(r for r in cls.get_indices_list() if r['code']==code);h=get_daily_history(code)
        row.update(daily_bars=h['bars'],history_meta={k:v for k,v in h.items() if k!='bars'},timeline_data=fetch_real_timeline(code))
        return row
