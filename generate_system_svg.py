import os

svg_content = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 700" width="100%" height="100%">
  <defs>
    <style>
      .title { font-family: system-ui, -apple-system, sans-serif; font-weight: bold; font-size: 20px; fill: #0f172a; }
      .subtitle { font-family: system-ui, -apple-system, sans-serif; font-size: 13px; fill: #64748b; }
      .card-title { font-family: system-ui, -apple-system, sans-serif; font-weight: bold; font-size: 15px; fill: #1e293b; }
      .card-sub { font-family: system-ui, -apple-system, sans-serif; font-size: 12px; fill: #475569; }
      .tag { font-family: system-ui, -apple-system, sans-serif; font-weight: bold; font-size: 12px; fill: #ffffff; }
      .flow-box { fill: #ffffff; stroke: #cbd5e1; stroke-width: 1.5; rx: 8; }
      .decision-box { fill: #f8fafc; stroke: #3b82f6; stroke-width: 2; rx: 8; }
      .rule-text { font-family: system-ui, -apple-system, sans-serif; font-size: 12px; fill: #334155; line-height: 1.5; }
      .line { stroke: #64748b; stroke-width: 2; marker-end: url(#arrow); }
      .green-line { stroke: #10b981; stroke-width: 2.5; marker-end: url(#arrow-green); }
      .red-line { stroke: #ef4444; stroke-width: 2; stroke-dasharray: 4; marker-end: url(#arrow-red); }
    </style>
    <marker id="arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 2 L 8 5 L 0 8 z" fill="#64748b" />
    </marker>
    <marker id="arrow-green" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 2 L 8 5 L 0 8 z" fill="#10b981" />
    </marker>
    <marker id="arrow-red" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 2 L 8 5 L 0 8 z" fill="#ef4444" />
    </marker>
  </defs>

  <rect width="1000" height="700" fill="#f8fafc" />

  <!-- 头部标题 -->
  <text x="50" y="45" class="title">缠论实战化交易决策与风控执行流水线</text>
  <text x="50" y="70" class="subtitle">消除主观玄学，基于“跨级别联立 + 严格几何条件 + 盈亏比非对称”的可复用工程体系</text>

  <!-- 阶段 1: 大级别定界 -->
  <g transform="translate(50, 95)">
    <rect width="260" height="230" class="flow-box" />
    <rect x="0" y="0" width="260" height="35" rx="8" fill="#e2e8f0" />
    <text x="15" y="24" class="card-title">第一步：本级别环境定位 (日线)</text>
    <text x="15" y="60" class="rule-text" font-weight="bold">选股与环境过滤：</text>
    <text x="15" y="85" class="rule-text">1. 日线处于底分型/向上笔初期</text>
    <text x="15" y="110" class="rule-text">2. 日线向上突破中枢形成强离开</text>
    <text x="15" y="135" class="rule-text">3. 过滤掉日线中枢下方背驰段前的跌势</text>
    <rect x="15" y="165" width="230" height="45" rx="4" fill="#eff6ff" stroke="#bfdbfe" />
    <text x="25" y="192" class="rule-text" fill="#1d4ed8" font-weight="bold">输出：锁定强势/转折候选标的池</text>
  </g>

  <!-- 阶段 2: 次级别精确捕捉 -->
  <g transform="translate(370, 95)">
    <rect width="260" height="230" class="flow-box" />
    <rect x="0" y="0" width="260" height="35" rx="8" fill="#dbeafe" />
    <text x="15" y="24" class="card-title" fill="#1e40af">第二步：次级别买点锁定 (30分)</text>
    <text x="15" y="60" class="rule-text" font-weight="bold">二买 / 三买信号触发：</text>
    <text x="15" y="85" class="rule-text">▸ 二买模型：回踩一笔不跌破1B底</text>
    <text x="15" y="110" class="rule-text">▸ 三买模型：次级别回抽低点 > ZG</text>
    <text x="15" y="135" class="rule-text">▸ 动力学要求：回抽段绿柱面积缩小</text>
    <rect x="15" y="165" width="230" height="45" rx="4" fill="#f0fdf4" stroke="#bbf7d0" />
    <text x="25" y="192" class="rule-text" fill="#15803d" font-weight="bold">输出：形成精确入场点 P_entry</text>
  </g>

  <!-- 阶段 3: 次次级别确认与执行 -->
  <g transform="translate(690, 95)">
    <rect width="260" height="230" class="flow-box" />
    <rect x="0" y="0" width="260" height="35" rx="8" fill="#dcfce7" />
    <text x="15" y="24" class="card-title" fill="#166534">第三步：次次级别确认 (5分钟)</text>
    <text x="15" y="60" class="rule-text" font-weight="bold">分时/5分钟区间套落地：</text>
    <text x="15" y="85" class="rule-text">1. 5分钟底分型成立并放量站上</text>
    <text x="15" y="110" class="rule-text">2. 止损点锚定：次级别回踩笔最低点</text>
    <text x="15" y="135" class="rule-text">3. 计算风险敞口 R = P_entry - P_stop</text>
    <rect x="15" y="165" width="230" height="45" rx="4" fill="#fef2f2" stroke="#fecaca" />
    <text x="25" y="192" class="rule-text" fill="#b91c1c" font-weight="bold">风控：单笔最大亏损 ≤ 总资产2%</text>
  </g>

  <!-- 连接箭头 -->
  <path d="M 310 210 L 370 210" class="line" />
  <path d="M 630 210 L 690 210" class="line" />

  <!-- 阶段 4: 下方持仓状态机管理 (核心执行规则) -->
  <g transform="translate(50, 360)">
    <rect width="900" height="300" class="decision-box" />
    <text x="25" y="35" class="card-title" font-size="16">第四步：完全分类的持仓生命周期状态机 (无预测，唯执行)</text>

    <!-- 状态分支 A: 触发止损 -->
    <g transform="translate(30, 60)">
      <rect width="250" height="200" rx="6" fill="#fff1f2" stroke="#fda4af" />
      <text x="15" y="30" class="card-title" fill="#be123c">【分支 A】走势被破坏</text>
      <text x="15" y="60" class="rule-text">条件：</text>
      <text x="15" y="80" class="rule-text">价格跌破初始止损位 (P &lt; P_stop)</text>
      <text x="15" y="105" class="rule-text">或三买后跌回中枢内 (三买失效)</text>
      <line x1="15" y1="125" x2="235" y2="125" stroke="#fecdd3" />
      <text x="15" y="150" class="rule-text" font-weight="bold" fill="#be123c">动作：100% 坚决离场止损</text>
      <text x="15" y="175" class="rule-text">意义：原分类失效，认错成本锁定在2%内</text>
    </g>

    <!-- 状态分支 B: 顺延上涨持仓 -->
    <g transform="translate(325, 60)">
      <rect width="250" height="200" rx="6" fill="#f0fdf4" stroke="#86efac" />
      <text x="15" y="30" class="card-title" fill="#15803d">【分支 B】走势生长未背驰</text>
      <text x="15" y="60" class="rule-text">条件：</text>
      <text x="15" y="80" class="rule-text">向上笔连续延伸，次级别中枢上移</text>
      <text x="15" y="105" class="rule-text">MACD黄白线稳步攀升无顶背驰</text>
      <line x1="15" y1="125" x2="235" y2="125" stroke="#bbf7d0" />
      <text x="15" y="150" class="rule-text" font-weight="bold" fill="#15803d">动作：移动止盈，持有不动</text>
      <text x="15" y="175" class="rule-text">止损位上移至新形成的次级别中枢下沿</text>
    </g>

    <!-- 状态分支 C: 触发展开卖点 -->
    <g transform="translate(620, 60)">
      <rect width="250" height="200" rx="6" fill="#fefce8" stroke="#fde047" />
      <text x="15" y="30" class="card-title" fill="#a16207">【分支 C】背驰或中枢震荡衰竭</text>
      <text x="15" y="60" class="rule-text">条件：</text>
      <text x="15" y="80" class="rule-text">1. 出现本级别第一类卖点 (顶背驰)</text>
      <text x="15" y="105" class="rule-text">2. 顶背驰后次级别反弹不过高 (二卖)</text>
      <line x1="15" y1="125" x2="235" y2="125" stroke="#fef08a" />
      <text x="15" y="150" class="rule-text" font-weight="bold" fill="#a16207">动作：一卖减半，二卖清仓</text>
      <text x="15" y="175" class="rule-text">闭环：交易圆满完成，利润兑现落袋</text>
    </g>
  </g>
</svg>
'''

with open('chanlun_execution_pipeline.svg', 'w', encoding='utf-8') as f:
    f.write(svg_content)

print("Pipeline SVG created!")
