import os

# 生成两个精美的SVG矢量图：
# 1. chanlun_concepts.svg (包含关系、分型、笔、中枢结构)
# 2. chanlun_three_buys.svg (三类买点全景推导与走势演化)

svg1 = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 850" width="100%" height="100%">
  <defs>
    <style>
      .title { font-family: system-ui, -apple-system, sans-serif; font-weight: bold; font-size: 22px; fill: #1e293b; }
      .subtitle { font-family: system-ui, -apple-system, sans-serif; font-size: 14px; fill: #64748b; }
      .section-title { font-family: system-ui, -apple-system, sans-serif; font-weight: bold; font-size: 16px; fill: #0f172a; }
      .label { font-family: system-ui, -apple-system, sans-serif; font-size: 13px; fill: #334155; }
      .bold-label { font-family: system-ui, -apple-system, sans-serif; font-weight: bold; font-size: 13px; fill: #0f172a; }
      .note { font-family: system-ui, -apple-system, sans-serif; font-size: 11px; fill: #64748b; }
      .box { fill: #f8fafc; stroke: #cbd5e1; stroke-width: 1.5; rx: 8; }
      .k-up { fill: #ef4444; stroke: #dc2626; stroke-width: 1.5; }
      .k-down { fill: #10b981; stroke: #059669; stroke-width: 1.5; }
      .k-wick-up { stroke: #dc2626; stroke-width: 1.5; }
      .k-wick-down { stroke: #059669; stroke-width: 1.5; }
      .bi-line { stroke: #2563eb; stroke-width: 3; stroke-linecap: round; }
      .pivot-box { fill: rgba(59, 130, 246, 0.12); stroke: #3b82f6; stroke-width: 2; stroke-dasharray: 4; }
    </style>
    <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1.5 L 10 5 L 0 8.5 z" fill="#2563eb" />
    </marker>
  </defs>

  <!-- 背景 -->
  <rect width="1000" height="850" fill="#ffffff" />

  <!-- 头部标题 -->
  <text x="50" y="45" class="title">缠论核心形态学教学图解（基础构建）</text>
  <text x="50" y="70" class="subtitle">K线包含处理 → 分型 → 成笔条件 → 走势中枢定义</text>

  <!-- 模块1：K线包含关系处理 -->
  <g transform="translate(50, 95)">
    <rect width="420" height="340" class="box" />
    <text x="20" y="30" class="section-title">1. K线包含关系处理</text>
    <text x="20" y="52" class="note">两相邻K线存在完全包含时，按前一趋势方向结合：</text>

    <!-- 向上包含 -->
    <g transform="translate(20, 70)">
      <text x="0" y="15" class="bold-label">向上合并（高高原则）: 取高点中高者，低点中高者</text>
      <!-- 原K线1 -->
      <line x1="40" y1="40" x2="40" y2="130" class="k-wick-up"/>
      <rect x="30" y="55" width="20" height="60" class="k-up"/>
      <!-- 原K线2（包含在1中） -->
      <line x1="80" y1="50" x2="80" y2="110" class="k-wick-down"/>
      <rect x="70" y="65" width="20" height="35" class="k-down"/>

      <!-- 箭头 -->
      <path d="M 120 85 L 155 85" stroke="#64748b" stroke-width="2" marker-end="url(#arrow)"/>

      <!-- 合并后K线 -->
      <line x1="200" y1="40" x2="200" y2="130" class="k-wick-up"/>
      <rect x="185" y="55" width="30" height="55" class="k-up"/>
      <text x="175" y="155" class="note">max(G1,G2), max(D1,D2)</text>
    </g>

    <!-- 向下包含 -->
    <g transform="translate(20, 195)">
      <text x="0" y="15" class="bold-label">向下合并（低低原则）: 取高点中低者，低点中低者</text>
      <!-- 原K线1 -->
      <line x1="40" y1="40" x2="40" y2="125" class="k-wick-down"/>
      <rect x="30" y="50" width="20" height="60" class="k-down"/>
      <!-- 原K线2（包含在1中） -->
      <line x1="80" y1="55" x2="80" y2="110" class="k-wick-up"/>
      <rect x="70" y="65" width="20" height="35" class="k-up"/>

      <!-- 箭头 -->
      <path d="M 120 85 L 155 85" stroke="#64748b" stroke-width="2" marker-end="url(#arrow)"/>

      <!-- 合并后K线 -->
      <line x1="200" y1="55" x2="200" y2="125" class="k-wick-down"/>
      <rect x="185" y="65" width="30" height="60" class="k-down"/>
      <text x="175" y="140" class="note">min(G1,G2), min(D1,D2)</text>
    </g>
  </g>

  <!-- 模块2：顶分型与底分型 -->
  <g transform="translate(510, 95)">
    <rect width="440" height="340" class="box" />
    <text x="20" y="30" class="section-title">2. 顶分型与底分型</text>
    <text x="20" y="52" class="note">经过包含关系处理后的3根连续K线构成基本形态</text>

    <!-- 顶分型 -->
    <g transform="translate(30, 80)">
      <text x="25" y="0" class="bold-label" fill="#dc2626">顶分型（中间K线高点最高，低点也最高）</text>
      <!-- K1 -->
      <line x1="40" y1="40" x2="40" y2="100" class="k-wick-up"/>
      <rect x="32" y="50" width="16" height="40" class="k-up"/>
      <!-- K2(顶) -->
      <line x1="80" y1="15" x2="80" y2="85" class="k-wick-up"/>
      <rect x="72" y="25" width="16" height="45" class="k-up"/>
      <circle cx="80" cy="15" r="4" fill="#dc2626" />
      <text x="70" y="10" class="note" fill="#dc2626" font-weight="bold">顶</text>
      <!-- K3 -->
      <line x1="120" y1="35" x2="120" y2="105" class="k-wick-down"/>
      <rect x="112" y="45" width="16" height="45" class="k-down"/>
      <text x="160" y="60" class="note">顶分型形成预警：</text>
      <text x="160" y="80" class="note">多头衰竭，可能成顶</text>
    </g>

    <!-- 底分型 -->
    <g transform="translate(30, 205)">
      <text x="25" y="0" class="bold-label" fill="#059669">底分型（中间K线低点最低，高点也最低）</text>
      <!-- K1 -->
      <line x1="40" y1="20" x2="40" y2="85" class="k-wick-down"/>
      <rect x="32" y="30" width="16" height="45" class="k-down"/>
      <!-- K2(底) -->
      <line x1="80" y1="40" x2="80" y2="110" class="k-wick-down"/>
      <rect x="72" y="50" width="16" height="50" class="k-down"/>
      <circle cx="80" cy="110" r="4" fill="#059669" />
      <text x="70" y="125" class="note" fill="#059669" font-weight="bold">底</text>
      <!-- K3 -->
      <line x1="120" y1="25" x2="120" y2="90" class="k-wick-up"/>
      <rect x="112" y="35" width="16" height="40" class="k-up"/>
      <text x="160" y="60" class="note">底分型形成预警：</text>
      <text x="160" y="80" class="note">空头衰竭，可能成底</text>
    </g>
  </g>

  <!-- 模块3：笔的构成条件 -->
  <g transform="translate(50, 465)">
    <rect width="420" height="345" class="box" />
    <text x="20" y="30" class="section-title">3. 一“笔”的严格定义</text>
    <text x="20" y="52" class="note">相邻顶分型与底分型之间，无共用K线，且至少有1根独立K线（总计≥5根K线）</text>

    <g transform="translate(30, 80)">
      <!-- 5根K线画向上笔 -->
      <!-- K1: 属于底分型 -->
      <rect x="20" y="150" width="14" height="30" class="k-down"/>
      <!-- K2: 底分型极值K -->
      <rect x="50" y="170" width="14" height="30" class="k-down"/>
      <circle cx="57" cy="205" r="4" fill="#059669"/>
      <!-- K3: 属于底分型 -->
      <rect x="80" y="130" width="14" height="40" class="k-up"/>
      <!-- K4: 独立K线（顶底不共用） -->
      <rect x="120" y="90" width="14" height="40" class="k-up"/>
      <text x="118" y="75" class="note" fill="#2563eb">独立K线</text>
      <!-- K5: 属于顶分型 -->
      <rect x="160" y="60" width="14" height="40" class="k-up"/>
      <!-- K6: 顶分型极值K -->
      <rect x="190" y="25" width="14" height="45" class="k-up"/>
      <circle cx="197" cy="20" r="4" fill="#dc2626"/>
      <!-- K7: 属于顶分型 -->
      <rect x="220" y="50" width="14" height="35" class="k-down"/>

      <!-- 笔连线 -->
      <line x1="57" y1="205" x2="197" y2="20" class="bi-line" marker-end="url(#arrow)"/>
      <text x="100" y="175" class="bold-label" fill="#2563eb" transform="rotate(-36 100,175)">一笔向上</text>

      <path d="M 20 225 L 94 225" stroke="#059669" stroke-width="2"/>
      <text x="35" y="242" class="note" fill="#059669">底分型区间</text>

      <path d="M 160 225 L 234 225" stroke="#dc2626" stroke-width="2"/>
      <text x="175" y="242" class="note" fill="#dc2626">顶分型区间</text>
    </g>
  </g>

  <!-- 模块4：走势中枢定义 -->
  <g transform="translate(510, 465)">
    <rect width="440" height="345" class="box" />
    <text x="20" y="30" class="section-title">4. 走势中枢核心结构</text>
    <text x="20" y="52" class="note">某级别连续三个次级别走势类型（至少三笔）的重叠部分</text>

    <g transform="translate(40, 80)">
      <!-- 三笔折线 -->
      <!-- 笔0进: A->B -->
      <line x1="20" y1="210" x2="70" y2="60" stroke="#94a3b8" stroke-width="2" stroke-dasharray="3"/>
      <text x="30" y="140" class="note">进入段</text>

      <!-- 笔1: B->C (下) -->
      <line x1="70" y1="60" x2="140" y2="170" stroke="#2563eb" stroke-width="3"/>
      <text x="60" y="50" class="label">B (g1)</text>

      <!-- 笔2: C->D (上) -->
      <line x1="140" y1="170" x2="210" y2="80" stroke="#2563eb" stroke-width="3"/>
      <text x="130" y="190" class="label">C (d1)</text>

      <!-- 笔3: D->E (下) -->
      <line x1="210" y1="80" x2="280" y2="150" stroke="#2563eb" stroke-width="3"/>
      <text x="210" y="70" class="label">D (g2)</text>
      <text x="280" y="170" class="label">E (d2)</text>

      <!-- 笔4出: E->F -->
      <line x1="280" y1="150" x2="350" y2="30" stroke="#94a3b8" stroke-width="2" stroke-dasharray="3"/>
      <text x="320" y="100" class="note">离开段</text>

      <!-- 中枢箱体 [ZD, ZG] -->
      <!-- ZG = min(g1, g2) = g2 = 80 -->
      <!-- ZD = max(d1, d2) = d2 = 150 -->
      <rect x="70" y="80" width="210" height="70" class="pivot-box"/>

      <!-- 标注线 -->
      <line x1="50" y1="80" x2="310" y2="80" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="2"/>
      <text x="315" y="85" class="bold-label" fill="#dc2626">ZG = min(g1, g2)</text>

      <line x1="50" y1="150" x2="310" y2="150" stroke="#059669" stroke-width="1.5" stroke-dasharray="2"/>
      <text x="315" y="155" class="bold-label" fill="#059669">ZD = max(d1, d2)</text>

      <text x="120" y="120" class="bold-label" fill="#1e40af">中枢区间 [ZD, ZG]</text>
    </g>
  </g>
</svg>
'''

svg2 = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 780" width="100%" height="100%">
  <defs>
    <style>
      .title { font-family: system-ui, -apple-system, sans-serif; font-weight: bold; font-size: 22px; fill: #1e293b; }
      .subtitle { font-family: system-ui, -apple-system, sans-serif; font-size: 14px; fill: #64748b; }
      .label { font-family: system-ui, -apple-system, sans-serif; font-size: 13px; fill: #1e293b; font-weight: bold; }
      .sublabel { font-family: system-ui, -apple-system, sans-serif; font-size: 12px; fill: #475569; }
      .tag { font-family: system-ui, -apple-system, sans-serif; font-weight: bold; font-size: 13px; fill: #ffffff; }
      .pivot-a { fill: rgba(239, 68, 68, 0.08); stroke: #ef4444; stroke-width: 1.5; stroke-dasharray: 4; }
      .pivot-b { fill: rgba(245, 158, 11, 0.08); stroke: #f59e0b; stroke-width: 1.5; stroke-dasharray: 4; }
      .pivot-c { fill: rgba(16, 185, 129, 0.08); stroke: #10b981; stroke-width: 1.5; stroke-dasharray: 4; }
      .trend-down { stroke: #ef4444; stroke-width: 3.5; stroke-linecap: round; stroke-linejoin: round; }
      .trend-up { stroke: #10b981; stroke-width: 3.5; stroke-linecap: round; stroke-linejoin: round; }
      .macd-line { stroke: #64748b; stroke-width: 1.5; }
    </style>
  </defs>

  <rect width="1000" height="780" fill="#ffffff" />

  <!-- 标题 -->
  <text x="50" y="45" class="title">缠论三大类买点全景演化图 (Three Buy Points)</text>
  <text x="50" y="70" class="subtitle">从下跌趋势背驰（一买）到转折确认（二买），再到中枢突破确认（三买）的全生命周期</text>

  <!-- 主图坐标/走势区域 -->
  <g transform="translate(50, 90)">
    <!-- 中枢A (下跌趋势中第1个中枢) -->
    <rect x="90" y="90" width="100" height="70" class="pivot-a"/>
    <text x="115" y="130" class="sublabel" fill="#ef4444">中枢 A</text>

    <!-- 中枢B (下跌趋势中第2个中枢) -->
    <rect x="250" y="220" width="100" height="70" class="pivot-a"/>
    <text x="275" y="260" class="sublabel" fill="#ef4444">中枢 B</text>

    <!-- 下跌走势折线：A中枢前进段、震荡、连接段、B中枢震荡、底背驰离开段 -->
    <!-- (10,40) -> (90,160) -> (140,90) -> (190,160) -> (250,290) -> (300,220) -> (350,290) -> (430,370)一买 -->
    <polyline points="
      20,40 
      90,160 140,90 190,160 
      250,290 300,220 350,290 
      430,370" 
      class="trend-down" fill="none"/>

    <!-- 离开段 c 对比连接段 b: 发生背驰 -->
    <path d="M 200 180 L 245 280" stroke="#f43f5e" stroke-width="2" stroke-dasharray="3"/>
    <text x="205" y="235" class="sublabel" fill="#f43f5e">b段(跌急)</text>

    <path d="M 355 300 L 420 365" stroke="#f43f5e" stroke-width="2" stroke-dasharray="3"/>
    <text x="390" y="325" class="sublabel" fill="#f43f5e">c段(跌缓背驰)</text>

    <!-- 第一类买点 1B -->
    <circle cx="430" cy="370" r="8" fill="#ef4444" />
    <rect x="405" y="390" width="50" height="24" rx="4" fill="#ef4444" />
    <text x="415" y="407" class="tag">1 买</text>
    <text x="350" y="435" class="sublabel">下跌趋势背驰转折点</text>
    <text x="350" y="450" class="sublabel" fill="#ef4444">c段跌幅与MACD发生背驰</text>

    <!-- 一买后反弹进新中枢构建，随后二买 -->
    <!-- (430,370) -> (520,230) -> (580,310)二买 -->
    <polyline points="430,370 520,230 580,310" class="trend-up" fill="none"/>

    <!-- 第二类买点 2B -->
    <circle cx="580" cy="310" r="8" fill="#f59e0b" />
    <rect x="555" y="330" width="50" height="24" rx="4" fill="#f59e0b" />
    <text x="565" y="347" class="tag">2 买</text>
    <text x="540" y="375" class="sublabel">次级别回踩不创新低</text>
    <text x="540" y="390" class="sublabel" fill="#f59e0b">右侧转折确认(不破1B底)</text>

    <!-- 构建上涨中枢并向上突破 -->
    <!-- (580,310) -> (660,190) -> (720,250) -> (800,120)突破离开段 -> (860,170)三买 -> (930,80) -->
    <polyline points="580,310 660,190 720,250 800,120 860,165 930,60" class="trend-up" fill="none"/>

    <!-- 新构建的中枢 C -->
    <!-- 包含波动 (520,230)到(660,190)到(720,250) -->
    <rect x="520" y="190" width="200" height="60" class="pivot-c"/>
    <text x="590" y="225" class="sublabel" fill="#10b981">上涨新中枢 C</text>

    <!-- 中枢最高点 ZG 延伸线 -->
    <line x1="520" y1="190" x2="900" y2="190" stroke="#10b981" stroke-width="1.5" stroke-dasharray="3"/>
    <text x="680" y="180" class="sublabel" fill="#10b981">中枢上沿 ZG</text>

    <!-- 第三类买点 3B -->
    <circle cx="860" cy="165" r="8" fill="#10b981" />
    <rect x="835" y="125" width="50" height="24" rx="4" fill="#10b981" />
    <text x="845" y="142" class="tag">3 买</text>
    <text x="820" y="105" class="sublabel">中枢突破回抽不破ZG</text>
    <text x="820" y="90" class="sublabel" fill="#10b981">主升浪起爆点(高胜率)</text>
  </g>

  <!-- 底部MACD示意区 -->
  <g transform="translate(50, 580)">
    <rect width="900" height="150" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1" rx="6"/>
    <text x="20" y="25" class="label">MACD 面积背驰直观验证 (一买前夕)</text>
    <line x1="20" y1="85" x2="880" y2="85" class="macd-line"/>
    <text x="840" y="80" class="sublabel">0轴</text>

    <!-- b段绿柱面积 (大) -->
    <path d="M 180 85 Q 210 135 240 85" fill="#ef4444" opacity="0.6"/>
    <text x="195" y="120" class="tag" fill="#ffffff" font-size="11">绿柱面积大</text>

    <!-- 黄白线在b段深探 -->
    <path d="M 80 70 Q 150 90 190 120 T 250 88 T 320 86 T 380 100 T 430 83" fill="none" stroke="#2563eb" stroke-width="2"/>

    <!-- c段绿柱面积 (小，虽然价格创新低，但面积缩小) -->
    <path d="M 360 85 Q 395 105 430 85" fill="#ef4444" opacity="0.6"/>
    <text x="375" y="100" class="tag" fill="#ffffff" font-size="11">面积萎缩</text>

    <!-- 背驰对比箭头 -->
    <path d="M 230 140 L 380 120" stroke="#dc2626" stroke-width="2" marker-end="url(#arrow)"/>
    <text x="260" y="145" class="sublabel" fill="#dc2626">价格创新低，指标动能未创新低 → 底背驰确立 (1B)</text>

    <!-- 突破0轴与回抽 -->
    <path d="M 430 83 Q 500 45 560 70 T 680 40 T 780 30 T 860 65 T 900 35" fill="none" stroke="#10b981" stroke-width="2"/>
    <text x="570" y="65" class="sublabel" fill="#10b981">一买后双线冲过0轴</text>
    <text x="810" y="55" class="sublabel" fill="#10b981">三买时回抽0轴不破</text>
  </g>
</svg>
'''

with open('chanlun_concepts.svg', 'w', encoding='utf-8') as f:
    f.write(svg1)

with open('chanlun_three_buys.svg', 'w', encoding='utf-8') as f:
    f.write(svg2)

print("SVGs created successfully!")
