"""宏观模块尚无可验证采集链路：明确不可用，禁止展示旧固定新闻和报价。"""
from scripts.verified_sources import meta
class WorldMacroEngine:
    @classmethod
    def get_world_macro_intelligence(cls,start_date=None,end_date=None):
        return dict(meta(None,'unavailable','宏观新闻与商品报价尚未接入可验证来源'),commodities=[],world_events=[],domestic_events=[],international_events=[],
                    aggregate_score={'total_score':None,'domestic_score':None,'international_score':None,'event_count':None,'sentiment_label':'未获取真实宏观数据','sentiment_color':'#94a3b8','sentiment_icon':'—'},
                    history={'points':[]},domestic_history={'points':[]},international_history={'points':[]})
