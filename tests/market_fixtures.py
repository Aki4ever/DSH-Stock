from scripts.stock_data_engine import StockQuote, KLineBar, normalize_code
from typing import Optional, List
from datetime import datetime, timedelta

def generate_mock_quote(norm_code: str) -> StockQuote:
    """生成具备真实特征的 Mock 离线行情数据（按代码哈希稳定生成）"""
    mock_db = {
        "sh000001": ("上证指数", 3058.62, 3045.20, 3048.10, 3065.80, 3042.15, 325410000, 395000000000),
        "sz399001": ("深证成指", 9560.85, 9510.30, 9520.00, 9590.20, 9495.50, 421500000, 482000000000),
        "sz399006": ("创业板指", 1880.45, 1865.10, 1868.00, 1892.50, 1860.20, 156000000, 195000000000),
        "hkHSI":    ("恒生指数", 17850.20, 17720.00, 17750.00, 17920.50, 17680.10, 120000000, 89000000000),
        "sh600519": ("贵州茅台", 1688.00, 1665.00, 1670.00, 1695.50, 1668.00, 28500, 4810000000),
        "sz300750": ("宁德时代", 205.80, 198.50, 200.00, 208.50, 199.20, 185000, 3780000000),
        "sz002594": ("比亚迪", 268.50, 262.00, 263.50, 271.00, 262.50, 98000, 2620000000),
        "sh601318": ("中国平安", 48.60, 47.90, 48.00, 48.95, 47.85, 450000, 2180000000),
        "sh688981": ("中芯国际", 89.20, 86.50, 87.00, 91.50, 86.80, 320000, 2850000000),
        "sz000001": ("平安银行", 12.85, 12.70, 12.72, 12.92, 12.68, 650000, 835000000)
    }

    if norm_code in mock_db:
        name, price, prev_close, open_p, high_p, low_p, vol, turnover = mock_db[norm_code]
    else:
        # 未收录的代码，通过哈希稳定算法生成拟真行情
        code_seed = sum(ord(c) for c in norm_code)
        name = f"标的_{norm_code}"
        base_p = 20.0 + (code_seed % 80)
        delta_pct = ((code_seed % 100) - 48) / 10.0  # -4.8% ~ +5.1%
        price = round(base_p * (1.0 + delta_pct / 100.0), 2)
        prev_close = base_p
        open_p = round(base_p * (1.0 + (delta_pct * 0.4) / 100.0), 2)
        high_p = round(max(price, open_p, prev_close) * 1.015, 2)
        low_p = round(min(price, open_p, prev_close) * 0.985, 2)
        vol = (code_seed * 123) % 200000 + 10000
        turnover = vol * price * 100

    change = round(price - prev_close, 2)
    change_pct = round((change / prev_close) * 100, 2) if prev_close > 0 else 0.0

    return StockQuote(
        code=norm_code,
        name=name,
        price=price,
        prev_close=prev_close,
        open_price=open_p,
        high=high_p,
        low=low_p,
        volume=vol,
        turnover=turnover,
        change=change,
        change_pct=change_pct,
        market="A",
        is_mock=True
    )


def generate_mock_kline(code: str, days: int = 60, end_price: Optional[float] = None) -> List[KLineBar]:
    """生成指定天数的拟真连续 K 线序列（用于指标计算与走势图绘制）"""
    norm_code, _ = normalize_code(code)
    quote = generate_mock_quote(norm_code)
    current_close = end_price if end_price is not None else quote.price

    bars: List[KLineBar] = []
    now = datetime.now()
    seed = sum(ord(c) for c in norm_code)

    # 逆推前推生成走势序列
    prices = [current_close]
    temp_p = current_close
    for i in range(days - 1):
        # 随机游走模拟（带均值回归倾向）
        pseudo_rnd = ((seed * (i + 1) * 37) % 100 - 49) / 100.0  # -0.49 ~ +0.50
        pct = pseudo_rnd * 0.035
        temp_p = max(5.0, temp_p / (1.0 + pct))
        prices.insert(0, temp_p)

    # 生成每个交易日的 K 线
    trade_date = now - timedelta(days=int(days * 1.5))
    day_count = 0

    for idx, close_p in enumerate(prices):
        while trade_date.weekday() >= 5:  # 跳过周末
            trade_date += timedelta(days=1)

        prev_p = prices[idx - 1] if idx > 0 else close_p * 0.99
        open_p = round(prev_p * (1.0 + (((seed * (idx + 3)) % 30 - 15) / 1000.0)), 2)
        high_p = round(max(open_p, close_p) * (1.0 + abs((seed * (idx + 7)) % 25) / 1000.0), 2)
        low_p = round(min(open_p, close_p) * (1.0 - abs((seed * (idx + 11)) % 25) / 1000.0), 2)
        vol = round(abs(((seed * (idx + 13)) % 50000) + 15000) * (close_p / 20.0), 1)

        bars.append(KLineBar(
            date=trade_date.strftime("%Y-%m-%d"),
            open_p=open_p,
            close_p=round(close_p, 2),
            high_p=high_p,
            low_p=low_p,
            volume=vol,
            turnover=round(vol * close_p * 100, 2)
        ))

        trade_date += timedelta(days=1)
        day_count += 1
        if day_count >= days:
            break

    return bars


