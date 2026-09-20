"""大宗交易来自东方财富公开披露；失败或缺失不生成成交。"""
from scripts.market_history import canonical_code
from scripts.data_sources.block_trade_adapter import BlockTradeAdapter
class OfficialBlockTradeEngine:
    @classmethod
    def get_stock_block_trades(cls,code,current_price=0):
        return BlockTradeAdapter.get_stock_block_trades(canonical_code(code)[2:],page_size=12)
