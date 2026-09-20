# -*- coding: utf-8 -*-
"""Generate numerical teaching SVGs. No live quotes or investment signals."""
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'assets'
OUT.mkdir(exist_ok=True)
INK, MUTED, TEAL, ORANGE = '#183642', '#546d76', '#087f8c', '#bc5a2e'
BG, PALE, LINE = '#f7f6f0', '#e6f2f1', '#ccd9db'

class Figure:
    def __init__(self, title, subtitle, height=760):
        self.h = height
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img"><title>{escape(title)}</title><desc>{escape(subtitle)}</desc>', '<style>text{font-family:"PingFang SC","Heiti SC","STHeiti",sans-serif}</style>']
        self.rect(0, 0, 1200, height, BG)
        self.text(44, 54, title, 32, INK, '600')
        self.text(44, 90, subtitle, 18, MUTED)
        self.text(44, height-25, '自制教学示意 · 非真实行情 · 定义与前提见教程及原作者出处', 17, MUTED)
    def text(self, x, y, s, size=20, color=INK, weight='400', anchor='start'):
        self.parts.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{escape(str(s))}</text>')
    def rect(self, x,y,w,h,fill=PALE,stroke='none',rx=0):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}"/>')
    def line(self,x1,y1,x2,y2,color=INK,width=3,dash=''):
        self.parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" stroke-dasharray="{dash}" stroke-linecap="round"/>')
    def point(self,x,y,color=TEAL,r=5):
        self.parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>')
    def poly(self,points,color=TEAL,width=4,dash=''):
        self.parts.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="{width}" stroke-dasharray="{dash}" stroke-linejoin="round"/>')
    def box(self,x,y,w,h,title,lines):
        self.rect(x,y,w,h,'white',LINE,14)
        self.text(x+22,y+35,title,23,TEAL,'600')
        for i,s in enumerate(lines): self.text(x+22,y+71+28*i,s,18)
    def save(self,name):
        (OUT/(name+'.svg')).write_text('\n'.join(self.parts)+ '</svg>',encoding='utf-8')

def bars(f, intervals, x, y, w, h, lo, hi, names=None, emphasis=1):
    """Every interval uses the same numeric vertical coordinate within a panel."""
    py=lambda v:y+h-(v-lo)/(hi-lo)*h
    points=[]
    for i,(low,high) in enumerate(intervals):
        px=x+(i+.5)*w/len(intervals); c=TEAL if i==emphasis else MUTED
        f.line(px,py(high),px,py(low),c,7)
        f.line(px-12,py(high),px+12,py(high),c,3)
        f.line(px-12,py(low),px+12,py(low),c,3)
        f.text(px+19,py(high)+5,high,17,c)
        f.text(px+19,py(low)+5,low,17,c)
        f.text(px,y+h+29,names[i] if names else f't{i+1}',17,MUTED,anchor='middle')
        points.append((px,py(low),py(high)))
    return points,py

f=Figure('01  缠论的学习框架','先整理形态，再辨认结构，最后比较力度与位置。',680)
for i,(a,b) in enumerate([('K线',['固定采样周期','高低区间']),('包含处理',['按方向合并','形成分析序列']),('分型',['三个相邻元素','顶 / 底']),('笔',['合格顶底连接','固定笔规则']),('线段',['至少三笔起步','检查结束条件'])]):
    f.box(44+i*228,142,200,145,a,b)
    if i<4:f.text(250+i*228,225,'→',25,TEAL)
f.box(44,341,528,154,'递归结构层',['确定基础单位 → 最小中枢 → 更高级结构','同级中枢的数量与关系 → 盘整 / 上涨 / 下跌'])
f.box(600,341,556,154,'分析层',['先确认级别、比较段与完成状态','研究力度与背驰 → 核对一 / 二 / 三类买卖点'])
f.text(52,555,'关联不等于一一对应：一笔 ≠ 任意次级别走势；K线周期 ≠ 结构级别。',23,ORANGE)
f.text(52,594,'每一步都记录：采用什么规则、哪些已确认、还缺什么证据。',21)
f.save('01_framework')

f=Figure('02  顶分型、底分型与两个反例','每根竖线表示价格区间 [L,H]；高点与低点必须一起比较。',900)
panels=[('顶分型 · 成立',[(8,10),(10,13),(9,11)],'中间高点13最高，低点10也最高。'),('底分型 · 成立',[(9,12),(7,10),(8,11)],'中间低点7最低，高点10也最低。'),('反例 · 包含尚未处理',[(8,10),(7,13),(9,11)],'中间[7,13]包住两侧，不能直接判顶。'),('反例 · 连续抬高',[(7,9),(8,10),(9,11)],'没有局部转折，不是顶，也不是底。')]
for i,(title,iv,caption) in enumerate(panels):
    x=44+(i%2)*572;y=126+(i//2)*342
    f.rect(x,y,540,316,'white',LINE,14);f.text(x+24,y+39,title,24,TEAL if i<2 else ORANGE,'600')
    bars(f,iv,x+34,y+67,440,164,6,14)
    f.text(x+24,y+286,caption,19)
f.text(44,843,'至少看到右侧元素后才能识别形状；末端未收完或仍会合并时，先标候选。',20,ORANGE)
f.save('02_fractals')

f=Figure('03  包含处理：相同输入，方向不同','A=[8,12]包含B=[9,11]；方向取自此前非包含关系。',730)
for y,title,result,rule in [(138,'此前方向向上',(9,12),'H取max(12,11)=12；L取max(8,9)=9'),(393,'此前方向向下',(8,11),'H取min(12,11)=11；L取min(8,9)=8')]:
    f.rect(44,y,1112,228,'white',LINE,14);f.text(65,y+38,title,23,TEAL,'600')
    bars(f,[(8,12),(9,11)],100,y+70,285,112,7,13,['A','B'])
    f.text(430,y+128,'→',40,TEAL)
    bars(f,[result],500,y+70,135,112,7,13,['合并后'],0)
    f.text(690,y+112,rule,20);f.text(690,y+154,'按时间顺序处理，不能跨根任意合并。',18,MUTED)
f.text(44,666,'此前方向不足时，向前补数据或标记待定；不能看K线红绿来选择方向。',20,ORANGE)
f.save('03_inclusion')

f=Figure('04  严格成笔：数清完整分型组','先完成包含处理；此例端点极值与区间关系也满足成笔要求。',800)
f.rect(44,130,1112,403,'white',LINE,14)
pts,py=bars(f,[(7,10),(5,8),(6,9),(7,10),(8,11),(9,12),(8,11)],95,183,980,230,4,13,[f'K{i}' for i in range(1,8)],-1)
f.line(pts[1][0],py(5),pts[5][0],py(12),TEAL,4)
f.text(pts[1][0]-20,py(5)+30,'底5',20,TEAL)
f.text(pts[5][0]-24,py(12)-18,'顶12',20,TEAL)
for left,right,label in [(105,495,'底分型组 K1—K3'),(665,1055,'顶分型组 K5—K7')]:
    f.line(left,478,right,478,TEAL,3);f.text((left+right)/2,510,label,20,TEAL,anchor='middle')
f.text(585,479,'K4独立',20,ORANGE,anchor='middle')
f.box(44,561,540,149,'正例：K2 → K6',['两中心之间含5根；完整两组展示需7根。','K1—K3 与 K5—K7 之间有K4。'])
f.box(612,561,544,149,'两种不足',['底组K1—K3 / 顶组K4—K6：缺独立间隔根。','底组K1—K3 / 顶组K3—K5：共用K3。'])
f.text(44,752,'“至少五根”必须说明计数对象；不能直接数原始K线，不能遗漏分型的左右元素。',19,ORANGE)
f.save('04_stroke')

f=Figure('05  线段：特征序列无缺口的例子','假定下图每一笔都已按笔规则独立确认；折点数字是价格。',880)
vals=[5,10,7,12,9,11,6];py=lambda v:445-(v-4)*30;xs=[110+i*91 for i in range(7)];points=list(zip(xs,map(py,vals)))
f.rect(44,134,725,365,'white',LINE,14)
f.poly(points,MUTED,3)
for (x,y),v in zip(points,vals):f.point(x,y);f.text(x-7,y-15,v,20)
f.line(xs[0],py(5),xs[3],py(12),TEAL,5)
f.line(xs[3],py(12),xs[-1],py(6),ORANGE,4,'8 7')
f.text(75,472,'实线：前向上线段；橙色虚线：反向段终点仍待确认。',18)
f.box(792,134,364,365,'从向下笔抽取区间',['10→7  → [7,10]','12→9  → [9,12]','11→6  → [6,11]','前两区间重叠[9,10]','属于无缺口情形。'])
f.rect(44,525,1112,268,'white',LINE,14)
f.text(66,560,'标准特征序列：顶分型',24,TEAL,'600')
bars(f,[(7,10),(9,12),(6,11)],65,587,450,129,5,13,['X1','X2','X3'])
f.text(571,609,'中间元素高点12、低点9都最高。',21)
f.text(571,652,'前段端点定位在12；要等右侧结构才确认。',21)
f.text(571,695,'起始三笔重叠[7,10]，不代表三笔时已结束。',20,ORANGE)
f.text(571,742,'有缺口时还需反向特征分型，不能套用本图。',19,MUTED)
f.save('05_segment')

f=Figure('06  中枢：三个完整次级别走势的交集','先确认组成单位和级别，再计算价格公共区间。',820)
f.rect(44,130,1112,420,'white',LINE,14)
xs=[130+i*170 for i in range(6)];v=[14,10,13,11,16,14];py=lambda n:500-(n-9)*42
f.rect(105,py(13),947,py(11)-py(13),PALE)
f.line(105,py(13),1052,py(13),TEAL,2,'6 5');f.line(105,py(11),1052,py(11),TEAL,2,'6 5')
f.text(1030,py(13)-12,'ZG=13',18,TEAL,anchor='end');f.text(1030,py(11)+25,'ZD=11',18,TEAL,anchor='end')
f.poly(list(zip(xs,map(py,v))),TEAL,4)
for i,((x,y),n) in enumerate(zip(zip(xs,map(py,v)),v)):
    f.point(x,y);f.text(x-8,y-14,n,20)
for i,s in enumerate(['A','B','C','D 离开','E 首次回试']):f.text((xs[i]+xs[i+1])/2,py((v[i]+v[i+1])/2)-18,s,18,INK,anchor='middle')
f.text(75,527,'A、B、C均已完成： [10,14] ∩ [10,13] ∩ [11,13] = [11,13]',22)
f.box(44,579,540,132,'区间计算',['ZD=max(10,10,11)=11','ZG=min(14,13,13)=13'])
f.box(612,579,544,132,'三买清晰例：还需满足图外前提',['D、E为相应次级别且均已完成；E为首次回试。','E低点14 > ZG13，留在中枢上方。'])
f.text(44,751,'三根任意折线只展示交集；未确认级别与完成状态时，不能认定正式中枢或三买。',19,ORANGE)
f.save('06_center')

f=Figure('07  背驰与三类买卖点：条件比箭头重要','图中省略内部结构，仅帮助记忆位置；没有计算MACD，也未证实背驰。',1270)
f.rect(44,130,1112,340,'white',LINE,14);py=lambda v:408-(v-7)*11
xs=[95+i*63 for i in range(10)];vals=[25,18,22,19,21,11,15,12,14,8]
for x,w,low,high,label in [(150,213,19,21,'A 同级中枢'),(403,213,12,14,'B 同级中枢')]:
    f.rect(x,py(high),w,py(low)-py(high),PALE);f.text(x,py(high)-24,label,18,TEAL)
f.poly(list(zip(xs,map(py,vals))),TEAL,3)
for index,label in [(0,'a'),(4,'b'),(8,'c')]:
    f.text((xs[index]+xs[index+1])/2,py((vals[index]+vals[index+1])/2)+28,label,23,ORANGE)
f.text(740,197,'趋势背驰的结构前提',23,TEAL,'600')
for i,s in enumerate(['A、B同级，符合趋势分离条件。','c同向创新极值，比较b与c。','还须核对级别、力度与结束条件。','本图几何形状本身不能证明背驰。']):f.text(740,239+i*36,s,18)
f.text(72,444,'另一种结构 a+B+c：围绕单中枢比较a、c，研究盘整背驰；须与上图趋势区分。',20)
mini=[('一买 1B',[16,12,14,8,11],3,'假设下跌趋势末端背驰已确认。'),('二买 2B',[8,12,9,13],2,'首次相应回调；补足级别与定位。'),('三买 3B',[12,16,14,18],2,'首次回试低点高于ZG。'),('一卖 1S',[8,12,10,16,13],3,'假设上涨趋势末端背驰已确认。'),('二卖 2S',[16,12,15,11],2,'首次相应反抽；补足级别与定位。'),('三卖 3S',[12,8,10,6],2,'首次反抽高点低于ZD。')]
for i,(title,nums,idx,caption) in enumerate(mini):
    col=i%3;row=i//3;x=44+col*376;y=500+row*307
    f.rect(x,y,360,284,'white',LINE,14);f.text(x+20,y+37,title,23,TEAL,'600')
    yy=lambda n:y+211-(n-6)*10;xx=[x+33+j*(286/(len(nums)-1)) for j in range(len(nums))]
    if i==2:
        f.rect(x+20,yy(13),320,yy(11)-yy(13),PALE);f.text(x+295,yy(13)-10,'ZG',16,TEAL)
    if i==5:
        f.rect(x+20,yy(13),320,yy(11)-yy(13),PALE);f.text(x+295,yy(11)+20,'ZD',16,TEAL)
    ps=list(zip(xx,map(yy,nums)));f.poly(ps[:idx+1],TEAL,3);f.poly(ps[idx:],MUTED,3,'5 6');f.point(*ps[idx],ORANGE,7)
    f.text(ps[idx][0]+12,ps[idx][1]-10,nums[idx],18,ORANGE)
    f.text(x+18,y+248,caption,17)
f.text(44,1166,'橙点仅示意位置；点后虚线是说明用延伸，不是预测，也不是当时已知的后续行情。',20,ORANGE)
f.text(44,1205,'二买不必先有同级一买；二、三类点可能重合；六类点都需各自的完整结构证据。',20)
f.save('07_divergence_points')
print('Generated 7 numerical SVG teaching figures.')
