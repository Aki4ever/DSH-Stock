"""五类图形的唯一计算入口；采用可复现、带规则版本的缠论工程口径。"""
from scripts.chanlun_core import RawBar, handle_inclusion, identify_fenxing, calculate_macd

RULES = {'version':'1.0', 'pen':'合并K线顶底分型交替，中心间距>=4；同向延伸取极值',
         'segment':'反向笔特征序列去包含后分型；至少三笔；缺口分型待反向特征分型确认',
         'pivot':'连续三笔价格区间的严格交集；笔级中枢，不冒充线段级中枢',
         'divergence':'相邻同向笔价格创新极值且MACD绝对柱面积缩小；笔背离，不等于完整趋势背驰',
         'ma_entanglement':'MA5/10/20极差÷三均线均值<=1%，连续>=3根；周期、阈值可配置'}


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
    return dict(data, code=code, status='available' if len(bars)>=max(periods) else 'insufficient',
                counts={k:len(v) for k,v in data.items()},rules=RULES,parameters={'ma_periods':list(periods),'threshold_pct':threshold_pct,'min_bars':min_bars},
                ma=ma,dates=[b["date"] for b in bars],bar_count=len(bars),computed_on='全部已获取历史；显示窗口不改变判定')
