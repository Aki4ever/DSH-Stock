"""五类图形的唯一计算入口；采用可复现、带规则版本的缠论工程口径。"""
from scripts.chanlun_core import RawBar, handle_inclusion, identify_fenxing, calculate_macd

RULES = {'version':'1.0', 'pen':'合并K线顶底分型交替，中心间距>=4；同向延伸取极值',
         'segment':'反向笔特征序列去包含后分型；至少三笔；缺口分型待反向特征分型确认',
         'pivot':'连续三笔价格区间的严格交集；笔级中枢，不冒充线段级中枢',
         'divergence':'相邻同向笔价格创新极值且MACD绝对柱面积缩小；笔背离，不等于完整趋势背驰',
         'ma_entanglement':'MA5/10/20极差÷三均线均值<=1%，连续>=3根；周期、阈值可配置',
         'buy_sell':'第一类＝趋势（两个同向且不重叠的连续中枢）中最后一个中枢离开段出现趋势背驰（创新极值且MACD面积缩小）；'
                    '第二类＝第一类之后首次次级别回抽不创新极值；第三类＝离开中枢后回抽不重新回到中枢区间（买点回抽低点>ZG，卖点反抽高点<ZD）。'
                    '全部判定只使用该点及其之前的数据，不使用未来函数'}


def build_pens(fractals, processed, bars, macd):
    points = []
    for f in fractals:
        if not points:
            points.append(f); continue
        last = points[-1]
        if f.fx_type == last.fx_type:
            if (f.value-last.value) * (1 if f.fx_type=='TOP' else -1) > 0:
                points[-1] = f
        elif f.index-last.index >= 4 and (f.value-last.value) * (1 if f.fx_type=='TOP' else -1) > 0:
            points.append(f)
    dates = {b.time_str:i for i,b in enumerate(bars)}
    out = []
    for a,b in zip(points,points[1:]):
        i,j = dates[a.time_str], dates[b.time_str]
        out.append({'start_time':a.time_str,'end_time':b.time_str,'start_price':a.value,'end_price':b.value,
                    'start_index':i,'end_index':j,'high':max(a.value,b.value),'low':min(a.value,b.value),
                    'direction':1 if b.value>a.value else -1,
                    'macd_area':sum(abs(m['hist']) for m in macd[i:j+1]),'status':'confirmed'})
    # The latest endpoint can extend with subsequent bars.
    if out: out[-1]['status']='provisional'
    return out


def feature_turn(pens, start, direction):
    seq=[]
    for i in range(start, len(pens)):
        p=pens[i]
        if p['direction']==direction:continue
        cur={'high':p['high'],'low':p['low'],'index':i}
        if seq and ((cur['high']>=seq[-1]['high'] and cur['low']<=seq[-1]['low']) or
                    (cur['high']<=seq[-1]['high'] and cur['low']>=seq[-1]['low'])):
            prev=seq[-1]; op=max if direction>0 else min
            if (cur['high']>prev['high'] if direction>0 else cur['low']<prev['low']):prev['index']=i
            prev['high']=op(prev['high'],cur['high']);prev['low']=op(prev['low'],cur['low'])
        else:seq.append(cur)
        if len(seq)<3:continue
        a,b,c=seq[-3:]
        turn=(b['high']>a['high'] and b['high']>c['high'] and b['low']>a['low'] and b['low']>c['low']) if direction>0 else (b['low']<a['low'] and b['low']<c['low'] and b['high']<a['high'] and b['high']<c['high'])
        if turn and b['index']-start>=3:
            gap=b['low']>a['high'] if direction>0 else b['high']<a['low']
            return b['index'],i,gap
    return None


def build_segments(pens):
    out=[];start=0
    while start<len(pens):
        direction=pens[start]['direction'];turn=feature_turn(pens,start,direction)
        if not turn:
            if len(pens)-start>=3:
                out.append(dict(pens[start],end_time=pens[-1]['end_time'],end_price=pens[-1]['end_price'],end_index=pens[-1]['end_index'],status='provisional',pen_count=len(pens)-start))
            break
        split,confirmed_at,gap=turn
        if gap and not feature_turn(pens,split,-direction):
            out.append(dict(pens[start],end_time=pens[split-1]['end_time'],end_price=pens[split-1]['end_price'],end_index=pens[split-1]['end_index'],status='provisional',reason='特征序列缺口待确认',pen_count=split-start));break
        end=pens[split-1]
        out.append(dict(pens[start],end_time=end['end_time'],end_price=end['end_price'],end_index=end['end_index'],status='confirmed',pen_count=split-start,confirmed_at=pens[confirmed_at]['end_time']))
        start=split
    for segment in out:
        segment['high']=max(segment['start_price'],segment['end_price'])
        segment['low']=min(segment['start_price'],segment['end_price'])
    return out


def build_pivots(pens):
    result=[];i=0
    while i+2<len(pens):
        group=pens[i:i+3];zg=min(p['high'] for p in group);zd=max(p['low'] for p in group)
        if zg<=zd:i+=1;continue
        j=i+2
        while j+1<len(pens) and pens[j+1]['high']>zd and pens[j+1]['low']<zg:j+=1
        result.append({'start_time':pens[i]['start_time'],'end_time':pens[j]['end_time'],'zg':zg,'zd':zd,'level':'pen',
                       'start_index':pens[i]['start_index'],'end_index':pens[j]['end_index'],
                       'status':'provisional' if j==len(pens)-1 else 'confirmed'})
        i=j+1
    return result


def build_divergences(pens):
    out=[]
    for i in range(2,len(pens)):
        p,old=pens[i],pens[i-2]
        if p['direction']!=old['direction']:continue
        if (p['end_price']-old['end_price'])*p['direction']>0 and old['macd_area']>0 and p['macd_area']<old['macd_area']:
            out.append({'time':p['end_time'],'price':p['end_price'],'index':p['end_index'],'direction':p['direction'],
                        'kind':'顶背离' if p['direction']>0 else '底背离','status':p['status'],
                        'previous_area':old['macd_area'],'current_area':p['macd_area'],'reference_time':old['end_time']})
    return out


BS_LABELS = {'buy1': '第一类买点', 'buy2': '第二类买点', 'buy3': '第三类买点',
             'sell1': '第一类卖点', 'sell2': '第二类卖点', 'sell3': '第三类卖点'}


def _first_pen_from(pens, index, direction=None):
    """定位从 index 起（含）的第一笔同向笔；仅向后取用，不含任何未来判定。"""
    for p in pens:
        if p['start_index'] < index: continue
        if direction is not None and p['direction'] != direction: continue
        return p
    return None


def _last_pen_before(pens, index, direction):
    """定位 end_index <= index 的最后一笔同向笔（＝进入后续中枢的那一段）。"""
    found = None
    for p in pens:
        if p['end_index'] <= index and p['direction'] == direction:
            found = p
    return found


def _worse(states):
    return 'provisional' if any(s == 'provisional' for s in states) else 'confirmed'


def build_buy_sell_points(pens, pivots):
    """需求REQ-040: 缠论三类买卖点（严格遵循缠论定义，只使用判定点及其之前的数据）。

    - 第一类买点/卖点：**趋势**（两个同向且互不重叠的连续中枢）中，最后一个中枢的离开段
      相对该中枢的进入段出现**趋势背驰**（价格创新极值 + MACD 绝对柱面积缩小）。
      注意：本项目 RULES 已声明「笔背离 ≠ 完整趋势背驰」，因此这里必须要求趋势结构，
      不使用单笔背离直接冒充第一类买卖点。
    - 第二类买点/卖点：第一类买卖点之后的**第一次次级别回抽/反弹不创新极值**。
    - 第三类买点/卖点：次级别走势**离开中枢**后，回抽不重新回到中枢区间
      （买点：回抽低点 > 中枢上沿 ZG；卖点：反抽高点 < 中枢下沿 ZD）。
    """
    out = []
    seen = set()

    def push(kind, index, time, price, reason, status):
        key = (kind, int(index))
        if key in seen: return
        seen.add(key)
        out.append({'type': kind, 'label': BS_LABELS[kind], 'index': int(index), 'time': time,
                    'price': round(float(price), 4), 'reason': reason, 'status': status})

    # ---------- 第一类买卖点：趋势 + 趋势背驰 ----------
    for k in range(1, len(pivots)):
        prev, last = pivots[k - 1], pivots[k]
        down_trend = last['zg'] < prev['zd']          # 后一中枢完全位于前一中枢下方 → 下跌趋势
        up_trend = last['zd'] > prev['zg']            # 后一中枢完全位于前一中枢上方 → 上涨趋势
        if not (down_trend or up_trend): continue
        direction = -1 if down_trend else 1
        leave = _first_pen_from(pens, last['end_index'], direction)
        if not leave: continue
        enter = _last_pen_before(pens, last['start_index'], direction)
        if not enter or enter['macd_area'] <= 0: continue
        made_extreme = leave['end_price'] < enter['end_price'] if down_trend else leave['end_price'] > enter['end_price']
        if not made_extreme or leave['macd_area'] >= enter['macd_area']: continue
        kind = 'buy1' if down_trend else 'sell1'
        trend_word = '下跌' if down_trend else '上涨'
        reason = (f"{trend_word}趋势：中枢 ¥{prev['zd']:.2f}~¥{prev['zg']:.2f} → ¥{last['zd']:.2f}~¥{last['zg']:.2f}（不重叠）；"
                  f"离开段{'创新低' if down_trend else '创新高'} ¥{leave['end_price']:.2f}，"
                  f"MACD面积 {enter['macd_area']:.2f} → {leave['macd_area']:.2f}（力度衰竭＝趋势背驰）")
        push(kind, leave['end_index'], leave['end_time'], leave['end_price'], reason,
             _worse([prev['status'], last['status'], leave['status'], enter['status']]))

    # ---------- 第二类买卖点：第一类之后首次次级别回抽不创新极值 ----------
    for first in [p for p in list(out) if p['type'] in ('buy1', 'sell1')]:
        direction = -1 if first['type'] == 'buy1' else 1
        back = _first_pen_from(pens, first['index'], direction)
        if not back: continue
        held = back['end_price'] > first['price'] if direction == -1 else back['end_price'] < first['price']
        if not held: continue
        kind = 'buy2' if direction == -1 else 'sell2'
        reason = (f"{BS_LABELS[first['type']]}（{first['time']} ¥{first['price']:.2f}）之后的第一次"
                  f"{'回调' if direction == -1 else '反弹'}收于 ¥{back['end_price']:.2f}，"
                  f"{'未创新低' if direction == -1 else '未创新高'}（不破 ¥{first['price']:.2f}）")
        push(kind, back['end_index'], back['end_time'], back['end_price'], reason,
             _worse([first['status'], back['status']]))

    # ---------- 第三类买卖点：离开中枢后回抽不回中枢区间 ----------
    for c in pivots:
        up = _first_pen_from(pens, c['end_index'], 1)
        if up and up['end_price'] > c['zg']:
            back = _first_pen_from(pens, up['end_index'], -1)
            if back and back['end_price'] > c['zg']:
                reason = (f"中枢 ¥{c['zd']:.2f}~¥{c['zg']:.2f} 被向上离开（高点 ¥{up['end_price']:.2f}）；"
                          f"回调低点 ¥{back['end_price']:.2f} 未回到中枢区间（> ZG ¥{c['zg']:.2f}）")
                push('buy3', back['end_index'], back['end_time'], back['end_price'], reason,
                     _worse([c['status'], up['status'], back['status']]))
        down = _first_pen_from(pens, c['end_index'], -1)
        if down and down['end_price'] < c['zd']:
            back = _first_pen_from(pens, down['end_index'], 1)
            if back and back['end_price'] < c['zd']:
                reason = (f"中枢 ¥{c['zd']:.2f}~¥{c['zg']:.2f} 被向下离开（低点 ¥{down['end_price']:.2f}）；"
                          f"反抽高点 ¥{back['end_price']:.2f} 未回到中枢区间（< ZD ¥{c['zd']:.2f}）")
                push('sell3', back['end_index'], back['end_time'], back['end_price'], reason,
                     _worse([c['status'], down['status'], back['status']]))

    out.sort(key=lambda p: (p['index'], p['type']))
    return out


def analyze_bars(bars, *, code='', periods=(5,10,20), threshold_pct=1.0, min_bars=3):
    if len(set(periods))<2 or any(type(p)!=int or p<2 or p>250 for p in periods) or not 0<threshold_pct<=20 or not 1<=min_bars<=100:
        raise ValueError('均线参数无效')
    import math
    if any(any(not isinstance(b.get(k),(int,float)) or not math.isfinite(b[k]) or b[k]<=0 for k in ('open','close','high','low')) for b in bars):
        raise ValueError('K线价格缺失或无效')
    if any(b['high']<max(b['open'],b['close'],b['low']) or b['low']>min(b['open'],b['close'],b['high']) for b in bars):raise ValueError('K线价格区间无效')
    if [b['date'] for b in bars]!=sorted({b['date'] for b in bars}):raise ValueError('K线日期必须唯一且递增')
    raw=[RawBar(b['date'],b['open'],b['close'],b['high'],b['low'],b.get('volume') or 0) for b in bars]
    macd=calculate_macd(raw);processed=handle_inclusion(raw);fx=identify_fenxing(processed)
    # Inclusion bars keep the final member's date, but their extrema can come
    # from an earlier member. Anchor chart endpoints to that actual raw bar.
    groups=[];offset=0
    for p in processed:
        groups.append(raw[offset:offset+p.original_count]);offset+=p.original_count
    for f in fx:
        attr='high' if f.fx_type=='TOP' else 'low'
        matches=[b for b in groups[f.index] if abs(getattr(b,attr)-f.value)<0.00011]
        if matches:f.time_str=matches[-1].time_str
    pens=build_pens(fx,processed,raw,macd)
    prefix=[0.0]
    for b in bars:prefix.append(prefix[-1]+b['close'])
    ma={str(p):[None if i+1<p else (prefix[i+1]-prefix[i+1-p])/p for i in range(len(bars))] for p in periods}
    runs=[];start=None
    for i in range(len(bars)+1):
        values=[ma[str(p)][i] for p in periods] if i<len(bars) else [None]
        tight=all(v is not None for v in values) and (max(values)-min(values))/(sum(values)/len(values))*100<=threshold_pct
        if tight and start is None:start=i
        if not tight and start is not None:
            if i-start>=min_bars:
                runs.append({'start_index':start,'end_index':i-1,'start_time':bars[start]['date'],'end_time':bars[i-1]['date'],
                             'high':max(b['high'] for b in bars[start:i]),'low':min(b['low'] for b in bars[start:i]),
                             'status':'provisional' if i==len(bars) else 'confirmed','bar_count':i-start})
            start=None
    data={'pens':pens,'segments':build_segments(pens),'pivots':build_pivots(pens),'divergences':build_divergences(pens),'ma_entanglements':runs}
    # 需求REQ-040: 三类买卖点（严格缠论定义）。仅新增字段，既有字段结构与取值完全不变。
    data['buy_sell_points']=build_buy_sell_points(pens, data['pivots'])
    counts={k:len(v) for k,v in data.items()}
    counts.update({t:sum(1 for p in data['buy_sell_points'] if p['type']==t) for t in BS_LABELS})
    return dict(data, code=code, status='available' if len(bars)>=max(periods) else 'insufficient',
                counts=counts,rules=RULES,parameters={'ma_periods':list(periods),'threshold_pct':threshold_pct,'min_bars':min_bars},
                ma=ma,dates=[b["date"] for b in bars],bar_count=len(bars),computed_on='全部已获取历史；显示窗口不改变判定')
