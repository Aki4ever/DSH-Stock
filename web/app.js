/**
 * DSH A股全市场量化筛选与交互走势图谱交互脚本 (v1.5.0)
 * 核心升级:
 * 1. 鼠标悬浮 K 线 / 分时图展示十字光标与浮动摘要信息栏 (时间、开盘、收盘、最高、最低、涨幅、振幅、成交量、成交额、换手率)
 * 2. 十大股东持股占比严格代数累加，杜绝 100% 异常
 * 3. 上市公司全景资料 (行业、主营、法人、注册资本、办公地)
 * 4. 深度财务分析 4 大 Tab 切换 (主要指标、资产负债表、利润表、现金流量表)
 */

// 全局应用状态
const appState = {
  version: 'v2.9.0',
  currentTab: 'filter', // 'filter' | 'dashboard' | 'crawler'
  market: 'all',
  board: 'all',
  constituent: 'all',
  st: 'all', // 需求4: 'all' (全部，默认) | 'st' (ST股) | 'non_st' (非ST正常股)
  shareholderAction: 'all',
  shareholderDays: 365,
  page: 1,
  pageSize: 50,
  totalMatched: 0,
  filteredStocks: [],
  currentSortKey: 'market_cap',
  sortAsc: false,
  serverStatus: 'running',
  heartbeatTimer: null,
  crawlerPollTimer: null,

  // 详情页走势图当前状态
  activeDetailStock: null,
  detailRequestId: 0,
  filterRequestId: 0,
  detailAbortController: null,
  activeDetailDimension: 'all', // 需求5: 当前激活的详情大维度 ('all'|'basic'|'dynamic'|'shareholders'|'finance'|'block'|'profile'|'dividend')
  chartPeriod: 'all', // 'timeline' (分时) | 'daily' (日K)
  chartSubplot: 'vol',     // 'vol' (成交量) | 'amt' (成交额)
  chartZoomWindow: 'max',  // '60' | '250' | '750' | 'max'
  chartCustomZoomCount: 0, // 鼠标滚轮动态缩放的蜡烛根数 (0表示使用默认预设)
  chanlunLayers: {},
  showChanlunDraw: false,  // 需求4: 缠论自动画线与买卖点开关
  drawHLineMode: false,    // 需求1: 是否处于绘制水平压力/支撑线模式
  // 需求REQ-014/015: 图表辅助线改为「多模型图层」结构，各模型独立存储/独立清除/独立层级
  //   auto        自动多阶线 (1~4 根筹码中枢线)
  //   manual_up   手动压力线
  //   manual_down 手动支撑线
  lineLayers: {
    auto:        { key: 'auto',        lines: [], visible: true },
    manual_up:   { key: 'manual_up',   lines: [], visible: true },
    manual_down: { key: 'manual_down', lines: [], visible: true }
  },
  lineZCounter: 1000,      // 需求REQ-015: 置顶用的单调递增层级游标
  topLineId: null,         // 需求REQ-015: 当前被用户置顶高亮的辅助线
  autoLinesBlockedReason: null, // 需求REQ-012: 自动线无法测算时给出真实原因，禁止静默显示 0 根
  drawnHorizontalLines: [], // 兼容旧引用：渲染与逻辑一律以 lineLayers 为准
  rawKlineData: [],        // 原始全量日K
  activeFinTab: 'main',    // 'main' | 'balance' | 'income' | 'cash'
  activeFinGranularity: 'annual', // 'annual' (按年度/图2) | 'report' (按报告期) | 'quarter' (按单季度)

  // 外部宏观环境过滤状态
  macroScope: 'domestic', // 需求3: 'domestic' (国内部委) | 'international' (国际外围)
  worldFilterCountry: 'all',
  worldFilterDomain: 'all',
  worldMacroData: null,

  // 飞书表格级列交互配置 (需求2: 列顺序与动态列冻结)
  columnOrder: [
    'raw_code', 'name', 'market', 'board', 'constituent', 'price', 'change_pct',
    'market_cap', 'circulating_cap', 'pe', 'dividend_count', 'dividend_total_amount',
    'div_to_cap_pct', 'listing_years', 'div_freq', 'ipo_date', 'goodwill', 'goodwill_to_cap_pct', 'top10_circ_hold_pct',
    'holder_individual_pct', 'holder_institution_pct', 'increase_holders', 'decrease_holders', 'holder_new_count',
    'holder_change_count', 'holder_exit_count', 'peer_holders', 'peer_companies', 'top10_hold_pct', 'report_date', 'action'
  ],
  freezeColCount: 2, // 默认冻结前 2 列 (代码、股票名称)

  // 宏观仪表盘数据缓存
  dashboardData: null
};

// DOM 元素引用
const dom = {
  systemCrashBanner: document.getElementById('systemCrashBanner'),
  btnCrashRestart: document.getElementById('btnCrashRestart'),
  appVersionBadge: document.getElementById('appVersionBadge'),
  serverStatusBadge: document.getElementById('serverStatusBadge'),
  serverStatusText: document.getElementById('serverStatusText'),
  serverPingText: document.getElementById('serverPingText'),
  serverStockCountText: document.getElementById('serverStockCountText'),
  btnRefreshQuotes: document.getElementById('btnRefreshQuotes'),
  btnToggleServer: document.getElementById('btnToggleServer'),

  // Tabs
  tabBtnFilter: document.getElementById('tabBtnFilter'),
  tabBtnDashboard: document.getElementById('tabBtnDashboard'),
  tabBtnWorld: document.getElementById('tabBtnWorld'),
  tabBtnShareholders: document.getElementById('tabBtnShareholders'),
  tabBtnIndex: document.getElementById('tabBtnIndex'),
  tabBtnCrawler: document.getElementById('tabBtnCrawler'),
  tabBtnRadar: document.getElementById('tabBtnRadar'),
  tabBtnScreener: document.getElementById('tabBtnScreener'),
  tabBtnPortfolio: document.getElementById('tabBtnPortfolio'),
  viewFilterTab: document.getElementById('viewFilterTab'),
  viewDashboardTab: document.getElementById('viewDashboardTab'),
  viewWorldTab: document.getElementById('viewWorldTab'),
  viewShareholdersTab: document.getElementById('viewShareholdersTab'),
  viewIndexTab: document.getElementById('viewIndexTab'),
  viewIndexDetailTab: document.getElementById('viewIndexDetailTab'),
  viewCrawlerTab: document.getElementById('viewCrawlerTab'),
  viewRadarTab: document.getElementById('viewRadarTab'),
  viewScreenerTab: document.getElementById('viewScreenerTab'),
  viewPortfolioTab: document.getElementById('viewPortfolioTab'),
  viewStockDetailTab: document.getElementById('viewStockDetailTab'),
  btnBackToStockList: document.getElementById('btnBackToStockList'),

  // 股东研究独立页面 DOM
  shCategoryControl: document.getElementById('shCategoryControl'),
  shKeywordInput: document.getElementById('shKeywordInput'),
  shareholdersTableBody: document.getElementById('shareholdersTableBody'),
  shOverviewTotalHolders: document.getElementById('shOverviewTotalHolders'),
  shOverviewInstHolders: document.getElementById('shOverviewInstHolders'),
  shOverviewIndHolders: document.getElementById('shOverviewIndHolders'),
  shOverviewTotalAmount: document.getElementById('shOverviewTotalAmount'),
  shOverviewInstAmount: document.getElementById('shOverviewInstAmount'),
  shOverviewIndAmount: document.getElementById('shOverviewIndAmount'),

  // 指数专区 DOM
  indexTableBody: document.getElementById('indexTableBody'),
  indexModalName: document.getElementById('indexModalName'),
  indexModalCode: document.getElementById('indexModalCode'),
  indexModalPriceBadge: document.getElementById('indexModalPriceBadge'),
  indexModalChangeBadge: document.getElementById('indexModalChangeBadge'),
  indexModalOpen: document.getElementById('indexModalOpen'),
  indexModalPrevClose: document.getElementById('indexModalPrevClose'),
  indexModalHigh: document.getElementById('indexModalHigh'),
  indexModalLow: document.getElementById('indexModalLow'),
  indexModalTurnover: document.getElementById('indexModalTurnover'),
  indexChartSvgContainer: document.getElementById('indexChartSvgContainer'),
  indexChartPeriodControl: document.getElementById('indexChartPeriodControl'),
  btnIndexAutoLines: document.getElementById('btnIndexAutoLines'),
  btnIndexDrawHorizontal: document.getElementById('btnIndexDrawHorizontal'),

  // 外部宏观环境 DOM
  worldHeaderScopeTitle: document.getElementById('worldHeaderScopeTitle'),
  worldHeaderScopeDesc: document.getElementById('worldHeaderScopeDesc'),
  worldScoreCardSubLabel: document.getElementById('worldScoreCardSubLabel'),
  worldTimelineChartTitle: document.getElementById('worldTimelineChartTitle'),
  badgeScopeDomestic: document.getElementById('badgeScopeDomestic'),
  badgeScopeInternational: document.getElementById('badgeScopeInternational'),
  worldStartDate: document.getElementById('worldStartDate'),
  worldEndDate: document.getElementById('worldEndDate'),
  worldTotalScore: document.getElementById('worldTotalScore'),
  worldScoreIcon: document.getElementById('worldScoreIcon'),
  worldSentimentLabel: document.getElementById('worldSentimentLabel'),
  worldEventsCount: document.getElementById('worldEventsCount'),
  worldTradingTip: document.getElementById('worldTradingTip'),
  worldScoreChartSvgContainer: document.getElementById('worldScoreChartSvgContainer'),
  statScoreLatest: document.getElementById('statScoreLatest'),
  statScoreMax: document.getElementById('statScoreMax'),
  statScoreMin: document.getElementById('statScoreMin'),
  statScoreAvg: document.getElementById('statScoreAvg'),
  btnScopeDomestic: document.getElementById('btnScopeDomestic'),
  btnScopeInternational: document.getElementById('btnScopeInternational'),
  domesticMinistriesQuickBar: document.getElementById('domesticMinistriesQuickBar'),
  worldCommoditySection: document.getElementById('worldCommoditySection'),
  worldCommodityGrid: document.getElementById('worldCommodityGrid'),
  worldEventsStream: document.getElementById('worldEventsStream'),
  worldCountryPills: document.getElementById('worldCountryPills'),
  worldDomainPills: document.getElementById('worldDomainPills'),

  // 宏观仪表盘 DOM
  dashStartDate: document.getElementById('dashStartDate'),
  dashEndDate: document.getElementById('dashEndDate'),
  dashDateTradingTip: document.getElementById('dashDateTradingTip'),
  dashTotalStocks: document.getElementById('dashTotalStocks'),
  dashUpRatio: document.getElementById('dashUpRatio'),
  dashLimitUp: document.getElementById('dashLimitUp'),
  dashLimitDown: document.getElementById('dashLimitDown'),
  dashTiersGrid: document.getElementById('dashTiersGrid'),
  dashTiersSum: document.getElementById('dashTiersSum'),
  dashTiersCompleteBadge: document.getElementById('dashTiersCompleteBadge'),
  breadthBarUp: document.getElementById('breadthBarUp'),
  breadthBarFlat: document.getElementById('breadthBarFlat'),
  breadthBarDown: document.getElementById('breadthBarDown'),
  macroDimGrid: document.getElementById('macroDimGrid'),
  chartChangeDistContainer: document.getElementById('chartChangeDistContainer'),
  chartCapTiersContainer: document.getElementById('chartCapTiersContainer'),
  top10CircTiersTableBody: document.getElementById('top10CircTiersTableBody'),
  top10CircChartContainer: document.getElementById('top10CircChartContainer'),
  top10CircTotalCountText: document.getElementById('top10CircTotalCountText'),

  // 飞书式高级表格 DOM (需求2)
  stockTableContainer: document.getElementById('stockTableContainer'),
  mainStockTable: document.getElementById('mainStockTable'),
  stockTableHeaderRow: document.getElementById('stockTableHeaderRow'),
  tableFreezeLine: document.getElementById('tableFreezeLine'),
  dataValidityBadge: document.getElementById('dataValidityBadge'),

  // Filter 控件
  filterDateInput: document.getElementById('filterDateInput'),
  filterDateTradingStatus: document.getElementById('filterDateTradingStatus'),
  filterDateStatusText: document.getElementById('filterDateStatusText'),
  marketControl: document.getElementById('marketControl'),
  boardControl: document.getElementById('boardControl'),
  constituentControl: document.getElementById('constituentControl'),
  stControl: document.getElementById('stControl'),

  minPriceInput: document.getElementById('minPriceInput'),
  maxPriceInput: document.getElementById('maxPriceInput'),
  minCapInput: document.getElementById('minCapInput'),
  maxCapInput: document.getElementById('maxCapInput'),
  minCircCapInput: document.getElementById('minCircCapInput'),
  maxCircCapInput: document.getElementById('maxCircCapInput'),
  // 需求1/2: 日交易额与日均交易额区间 DOM
  minDailyAmountInput: document.getElementById('minDailyAmountInput'),
  maxDailyAmountInput: document.getElementById('maxDailyAmountInput'),
  minAvgDailyAmountInput: document.getElementById('minAvgDailyAmountInput'),
  maxAvgDailyAmountInput: document.getElementById('maxAvgDailyAmountInput'),
  minPeInput: document.getElementById('minPeInput'),
  maxPeInput: document.getElementById('maxPeInput'),
  minTop10CircInput: document.getElementById('minTop10CircInput'),
  maxTop10CircInput: document.getElementById('maxTop10CircInput'),
  minTop10HoldInput: document.getElementById('minTop10HoldInput'),
  maxTop10HoldInput: document.getElementById('maxTop10HoldInput'),
  // 需求2: 上市时长区间 DOM
  minListingYearsInput: document.getElementById('minListingYearsInput'),
  maxListingYearsInput: document.getElementById('maxListingYearsInput'),
  // 需求2: 个人/机构占比区间 DOM 与 需求5: 盈利时长单选
  minIndividualPctInput: document.getElementById('minIndividualPctInput'),
  maxIndividualPctInput: document.getElementById('maxIndividualPctInput'),
  minInstitutionPctInput: document.getElementById('minInstitutionPctInput'),
  maxInstitutionPctInput: document.getElementById('maxInstitutionPctInput'),
  profitYearsControl: document.getElementById('profitYearsControl'),
  keywordInput: document.getElementById('keywordInput'),

  btnExecuteFilter: document.getElementById('btnExecuteFilter'),
  btnResetFilter: document.getElementById('btnResetFilter'),

  matchedCount: document.getElementById('matchedCount'),
  poolCountText: document.getElementById('poolCountText'),
  statAvgPrice: document.getElementById('statAvgPrice'),
  statAvgChange: document.getElementById('statAvgChange'),
  statTotalCap: document.getElementById('statTotalCap'),
  statTotalCircCap: document.getElementById('statTotalCircCap'),

  stockTableBody: document.getElementById('stockTableBody'),
  loadingIndicator: document.getElementById('loadingIndicator'),
  emptyIndicator: document.getElementById('emptyIndicator'),

  paginationBar: document.getElementById('paginationBar'),
  pageRangeText: document.getElementById('pageRangeText'),
  currentPageNum: document.getElementById('currentPageNum'),
  totalPageNum: document.getElementById('totalPageNum'),
  btnPrevPage: document.getElementById('btnPrevPage'),
  btnNextPage: document.getElementById('btnNextPage'),

  // 爬虫控制台 DOM
  btnStartFullCrawl: document.getElementById('btnStartFullCrawl'),
  btnStartCoreCrawl: document.getElementById('btnStartCoreCrawl'),
  btnCancelCrawl: document.getElementById('btnCancelCrawl'),
  crawlerPulseDot: document.getElementById('crawlerPulseDot'),
  crawlerStatusText: document.getElementById('crawlerStatusText'),
  crawlerProgressPct: document.getElementById('crawlerProgressPct'),
  crawlerProgressBar: document.getElementById('crawlerProgressBar'),
  crawlerPhaseDesc: document.getElementById('crawlerPhaseDesc'),
  crawlerMetricTotal: document.getElementById('crawlerMetricTotal'),
  crawlerMetricUpdated: document.getElementById('crawlerMetricUpdated'),
  crawlerMetricElapsed: document.getElementById('crawlerMetricElapsed'),
  crawlerCompleteBanner: document.getElementById('crawlerCompleteBanner'),
  crawlerCompleteMsg: document.getElementById('crawlerCompleteMsg'),

  // 详情模态 DOM
  stockDetailModal: document.getElementById('stockDetailModal'),
  modalStockName: document.getElementById('modalStockName'),
  modalStockCode: document.getElementById('modalStockCode'),
  modalMarketTag: document.getElementById('modalMarketTag'),
  modalBoardTag: document.getElementById('modalBoardTag'),
  modalConstituentTag: document.getElementById('modalConstituentTag'),
  modalPriceBadge: document.getElementById('modalPriceBadge'),
  modalChangeBadge: document.getElementById('modalChangeBadge'),
  modalOpenPrice: document.getElementById('modalOpenPrice'),
  modalPrevClose: document.getElementById('modalPrevClose'),
  modalHighPrice: document.getElementById('modalHighPrice'),
  modalLowPrice: document.getElementById('modalLowPrice'),
  modalMarketCap: document.getElementById('modalMarketCap'),
  modalCircCap: document.getElementById('modalCircCap'),
  modalPe: document.getElementById('modalPe'),
  modalDividendCount: document.getElementById('modalDividendCount'),
  modalListingYears: document.getElementById('modalListingYears'),
  modalTurnoverRate: document.getElementById('modalTurnoverRate'),
  modalTurnover: document.getElementById('modalTurnover'),
  modalReportDate: document.getElementById('modalReportDate'),
  modalTop10Circ: document.getElementById('modalTop10Circ'),
  modalTop10Hold: document.getElementById('modalTop10Hold'),
  modalQuantScore: document.getElementById('modalQuantScore'),
  modalQuantAction: document.getElementById('modalQuantAction'),

  // 图表与 Tooltip DOM
  modalChartWrapper: document.getElementById('modalChartWrapper'),
  chartSvgContainer: document.getElementById('chartSvgContainer'),
  chartTooltipBox: document.getElementById('chartTooltipBox'),
  ttDate: document.getElementById('ttDate'),
  ttOpen: document.getElementById('ttOpen'),
  ttClose: document.getElementById('ttClose'),
  ttHigh: document.getElementById('ttHigh'),
  ttLow: document.getElementById('ttLow'),
  ttChangePct: document.getElementById('ttChangePct'),
  ttAmplitude: document.getElementById('ttAmplitude'),
  ttVolume: document.getElementById('ttVolume'),
  ttAmount: document.getElementById('ttAmount'),
  ttTurnover: document.getElementById('ttTurnover'),

  chartPeriodControl: document.getElementById('chartPeriodControl'),
  chartZoomControl: document.getElementById('chartZoomControl'),
  klineDateRangeBar: document.getElementById('klineDateRangeBar'),
  klineStartDate: document.getElementById('klineStartDate'),
  klineEndDate: document.getElementById('klineEndDate'),
  chartSubPlotControl: document.getElementById('chartSubPlotControl'),
  btnChanlunDraw: document.getElementById('btnChanlunDraw'),
  btnChanlunScope: document.getElementById('btnChanlunScope'),
  chanlunScopeModal: document.getElementById('chanlunScopeModal'),
  btnAutoDrawLevels: document.getElementById('btnAutoDrawLevels'),
  btnToggleHLine: document.getElementById('btnToggleHLine'),
  btnClearLines: document.getElementById('btnClearLines'),
  chartDataSourceBadge: document.getElementById('chartDataSourceBadge'),

  // 需求5: 8大维度Tab与Panels
  modalDimensionTabs: document.getElementById('modalDimensionTabs'),
  paneBasic: document.getElementById('paneBasic'),
  paneShareholders: document.getElementById('paneShareholders'),
  paneProfile: document.getElementById('paneProfile'),
  paneFinance: document.getElementById('paneFinance'),
  paneBlock: document.getElementById('paneBlock'),
  paneDynamic: document.getElementById('paneDynamic'),
  paneDividend: document.getElementById('paneDividend'),
  finTableBodyDividend: document.getElementById('finTableBodyDividend'),

  // 需求2: 十大流通股东专属穿透弹窗 DOM
  top10HoldersModal: document.getElementById('top10HoldersModal'),
  holderModalTitle: document.getElementById('holderModalTitle'),
  holderModalStockBadge: document.getElementById('holderModalStockBadge'),
  holderModalReportDate: document.getElementById('holderModalReportDate'),
  holderModalTotalPct: document.getElementById('holderModalTotalPct'),
  holderModalFilterLabel: document.getElementById('holderModalFilterLabel'),
  holderModalTableBody: document.getElementById('holderModalTableBody'),

  // 需求3: 同名流通股东企业专属穿透弹窗 DOM
  peerCompaniesModal: document.getElementById('peerCompaniesModal'),
  peerModalStockBadge: document.getElementById('peerModalStockBadge'),
  peerModalTableBody: document.getElementById('peerModalTableBody'),

  // 公司资料与财务分析 DOM
  modalProfileIndustryTag: document.getElementById('modalProfileIndustryTag'),
  modalProfileScope: document.getElementById('modalProfileScope'),
  modalProfileLegal: document.getElementById('modalProfileLegal'),
  modalProfileCapital: document.getElementById('modalProfileCapital'),
  modalProfileExchange: document.getElementById('modalProfileExchange'),
  modalProfileAddress: document.getElementById('modalProfileAddress'),
  modalFinancePeriod: document.getElementById('modalFinancePeriod'),
  finTheadMain: document.getElementById('finTheadMain'),
  finTheadBalance: document.getElementById('finTheadBalance'),
  finTheadIncome: document.getElementById('finTheadIncome'),
  finTheadCash: document.getElementById('finTheadCash'),
  finTableBodyMain: document.getElementById('finTableBodyMain'),
  finTableBodyBalance: document.getElementById('finTableBodyBalance'),
  finTableBodyIncome: document.getElementById('finTableBodyIncome'),
  finTableBodyCash: document.getElementById('finTableBodyCash'),
  finPanelMain: document.getElementById('finPanelMain'),
  finPanelBalance: document.getElementById('finPanelBalance'),
  finPanelIncome: document.getElementById('finPanelIncome'),
  finPanelCash: document.getElementById('finPanelCash'),
  finPanelBlock: document.getElementById('finPanelBlock'),
  finPanelEvents: document.getElementById('finPanelEvents'),
  finTableBodyBlock: document.getElementById('finTableBodyBlock'),
  eventsMilestoneList: document.getElementById('eventsMilestoneList'),
  eventsNoticeList: document.getElementById('eventsNoticeList')
};

// 页面初始化
document.addEventListener('DOMContentLoaded', () => {
  // 1. 同步版本与日期
  initDateControl();
  syncVersionAndTitle();
  initEventListeners();
  initFeishuTableDragAndFreeze(); // 需求2: 初始化飞书式列拖拽与可拖动冻结线

  // 2. 先立即触发一次心跳，使顶栏绿灯秒显
  checkServerHealth();
  startHeartbeat();

  // 3. 异步平滑发起筛选与爬虫状态检测，互不阻塞
  setTimeout(() => executeFilter(), 50);
  setTimeout(() => pollCrawlerStatus(), 200);
});

/**
 * 顶栏 Tab 页面无缝切换 (对齐图1: filter | dashboard | world | shareholders | index | crawler)
 */
function switchMainTab(tabId) {
  appState.currentTab = tabId;

  if (dom.tabBtnFilter) dom.tabBtnFilter.classList.toggle('active', tabId === 'filter');
  if (dom.tabBtnDashboard) dom.tabBtnDashboard.classList.toggle('active', tabId === 'dashboard');
  if (dom.tabBtnWorld) dom.tabBtnWorld.classList.toggle('active', tabId === 'world');
  if (dom.tabBtnShareholders) dom.tabBtnShareholders.classList.toggle('active', tabId === 'shareholders');
  if (dom.tabBtnIndex) dom.tabBtnIndex.classList.toggle('active', tabId === 'index');
  if (dom.tabBtnCrawler) dom.tabBtnCrawler.classList.toggle('active', tabId === 'crawler');
  if (dom.tabBtnRadar) dom.tabBtnRadar.classList.toggle('active', tabId === 'radar');
  if (dom.tabBtnScreener) dom.tabBtnScreener.classList.toggle('active', tabId === 'screener');
  if (dom.tabBtnPortfolio) dom.tabBtnPortfolio.classList.toggle('active', tabId === 'portfolio');

  if (dom.viewFilterTab) dom.viewFilterTab.classList.toggle('hidden', tabId !== 'filter');
  if (dom.viewDashboardTab) dom.viewDashboardTab.classList.toggle('hidden', tabId !== 'dashboard');
  if (dom.viewWorldTab) dom.viewWorldTab.classList.toggle('hidden', tabId !== 'world');
  if (dom.viewShareholdersTab) dom.viewShareholdersTab.classList.toggle('hidden', tabId !== 'shareholders');
  if (dom.viewIndexTab) dom.viewIndexTab.classList.toggle('hidden', tabId !== 'index');
  if (dom.viewCrawlerTab) dom.viewCrawlerTab.classList.toggle('hidden', tabId !== 'crawler');
  if (dom.viewRadarTab) dom.viewRadarTab.classList.toggle('hidden', tabId !== 'radar');
  if (dom.viewScreenerTab) dom.viewScreenerTab.classList.toggle('hidden', tabId !== 'screener');
  if (dom.viewPortfolioTab) dom.viewPortfolioTab.classList.toggle('hidden', tabId !== 'portfolio');

  // 隐藏详情全屏页
  if (dom.viewStockDetailTab) dom.viewStockDetailTab.classList.add('hidden');
  if (dom.viewIndexDetailTab) dom.viewIndexDetailTab.classList.add('hidden');

  if (tabId === 'dashboard') {
    loadDashboardOverview();
  } else if (tabId === 'world') {
    loadWorldMacroIntelligence();
  } else if (tabId === 'shareholders') {
    loadShareholdersOverview();
  } else if (tabId === 'index') {
    loadIndicesList();
  } else if (tabId === 'crawler') {
    pollCrawlerStatus();
    loadCrawlerAuditList();
  } else if (tabId === 'radar') {
    loadRadarPool();
    syncRadarScanStatus();
  } else if (tabId === 'screener') {
    loadScreenerResults();
    loadNotifyStatus();
    syncScreenerScanStatus();
  } else if (tabId === 'portfolio') {
    loadPortfolioCheckup();
  }
}

/**
 * 初始化基准日期控件（默认今天）并启动交易日核验
 */
function initDateControl() {
  const today = new Date();
  const yyyy = today.getFullYear();
  const mm = String(today.getMonth() + 1).padStart(2, '0');
  const dd = String(today.getDate()).padStart(2, '0');
  const todayStr = `${yyyy}-${mm}-${dd}`;

  if (dom.filterDateInput) dom.filterDateInput.value = todayStr;
  if (dom.dashStartDate) dom.dashStartDate.value = todayStr;
  if (dom.dashEndDate) dom.dashEndDate.value = todayStr;
  if (dom.worldStartDate) {
    const d30 = new Date();
    d30.setDate(today.getDate() - 30);
    const m30 = String(d30.getMonth() + 1).padStart(2, '0');
    const day30 = String(d30.getDate()).padStart(2, '0');
    dom.worldStartDate.value = `${d30.getFullYear()}-${m30}-${day30}`;
  }
  if (dom.worldEndDate) dom.worldEndDate.value = todayStr;

  checkFilterDateTradingStatus(todayStr);
}

/**
 * 实时核验日期是否为休市日并进行强视觉提醒
 */
async function checkFilterDateTradingStatus(dateStr) {
  if (!dom.filterDateTradingStatus || !dom.filterDateStatusText) return;
  try {
    const res = await fetch(`/api/calendar/check?date=${dateStr}`);
    if (!res.ok) return;
    const json = await res.json();
    const cal = json.data;

    if (cal.is_trading_day) {
      dom.filterDateTradingStatus.className = 'trading-status-tip trading-status-open';
      dom.filterDateStatusText.textContent = cal.badge_text;
    } else {
      dom.filterDateTradingStatus.className = 'trading-status-tip trading-status-closed';
      dom.filterDateStatusText.textContent = `${cal.badge_text} - 非交易日`;
    }
  } catch (err) {
    console.error('日历判定异常:', err);
  }
}

/**
 * 筛选器快速日期设定 (今天 / 近5日(周) / 近20天(月))
 */
function setQuickDateFilter(rangeType, evt = null) {
  const today = new Date();
  const formatDate = (d) => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  };

  let targetDate = today;
  if (rangeType === '5d') {
    targetDate = new Date();
    targetDate.setDate(today.getDate() - 7);
  } else if (rangeType === '20d') {
    targetDate = new Date();
    targetDate.setDate(today.getDate() - 30);
  }

  const dtStr = formatDate(targetDate);
  if (dom.filterDateInput) {
    dom.filterDateInput.value = dtStr;
    checkFilterDateTradingStatus(dtStr);
  }

  // 胶囊高亮状态
  ['btnDateQuickToday', 'btnDateQuick5d', 'btnDateQuick20d'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active');
  });
  if (rangeType === 'today' && document.getElementById('btnDateQuickToday')) document.getElementById('btnDateQuickToday').classList.add('active');
  if (rangeType === '5d' && document.getElementById('btnDateQuick5d')) document.getElementById('btnDateQuick5d').classList.add('active');
  if (rangeType === '20d' && document.getElementById('btnDateQuick20d')) document.getElementById('btnDateQuick20d').classList.add('active');

  appState.page = 1;
  executeFilter();
}

/**
 * 外部宏观环境快速日期区间设定 (今天 / 近5日(周) / 近20天(月))
 */
function setWorldQuickDateRange(rangeType, evt = null) {
  const today = new Date();
  const formatDate = (d) => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  };

  const todayStr = formatDate(today);
  if (dom.worldEndDate) dom.worldEndDate.value = todayStr;

  if (rangeType === 'today') {
    if (dom.worldStartDate) dom.worldStartDate.value = todayStr;
  } else if (rangeType === '5d') {
    const d5 = new Date();
    d5.setDate(today.getDate() - 7);
    if (dom.worldStartDate) dom.worldStartDate.value = formatDate(d5);
  } else if (rangeType === '20d') {
    const d20 = new Date();
    d20.setDate(today.getDate() - 30);
    if (dom.worldStartDate) dom.worldStartDate.value = formatDate(d20);
  }

  ['btnWorldQuickToday', 'btnWorldQuick5d', 'btnWorldQuick20d'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active');
  });
  if (rangeType === 'today' && document.getElementById('btnWorldQuickToday')) document.getElementById('btnWorldQuickToday').classList.add('active');
  if (rangeType === '5d' && document.getElementById('btnWorldQuick5d')) document.getElementById('btnWorldQuick5d').classList.add('active');
  if (rangeType === '20d' && document.getElementById('btnWorldQuick20d')) document.getElementById('btnWorldQuick20d').classList.add('active');

  loadWorldMacroIntelligence();
}

/**
 * 需求1: 动态更新顶栏真实快照截取日期
 */
function updateDataValidityDateBadge(dateStr) {
  if (!dom.dataValidityBadge || !dateStr) return;
  let formatted = dateStr;
  if (dateStr.includes('-')) {
    const p = dateStr.split('-');
    if (p.length === 3) {
      formatted = `${p[0]}年${parseInt(p[1], 10)}月${parseInt(p[2], 10)}日`;
    }
  }
  dom.dataValidityBadge.textContent = `📅 行情日期: ${formatted}`;
}

/**
 * 仪表盘快速日期区间设定
 */
function setDashboardDateRange(rangeType, evt = null) {
  const today = new Date();
  const formatDate = (d) => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  };

  const todayStr = formatDate(today);
  dom.dashEndDate.value = todayStr;

  if (rangeType === 'today') {
    dom.dashStartDate.value = todayStr;
  } else if (rangeType === '5d') {
    const d5 = new Date();
    d5.setDate(today.getDate() - 7);
    dom.dashStartDate.value = formatDate(d5);
  } else if (rangeType === '20d') {
    const d20 = new Date();
    d20.setDate(today.getDate() - 30);
    dom.dashStartDate.value = formatDate(d20);
  }

  document.querySelectorAll('.btn-quick-date').forEach(btn => {
    btn.classList.remove('active');
  });
  const target = (evt && evt.target) ? evt.target : (typeof event !== 'undefined' && event ? event.target : null);
  if (target && target.classList) {
    target.classList.add('active');
  }

  loadDashboardOverview();
}

/**
 * 同步网页 Title 与 Header 版本号
 */
function syncVersionAndTitle(version = 'v2.3.0') {
  appState.version = version;
  document.title = `【${version}】A股多维量化筛选器 - DSH Stock Web`;
  if (dom.appVersionBadge) {
    dom.appVersionBadge.textContent = version;
  }
}

/**
 * 事件监听绑定
 */
function initEventListeners() {
  // 股市分类
  dom.marketControl.querySelectorAll('.seg-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      dom.marketControl.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      appState.market = btn.getAttribute('data-val');
      appState.page = 1;
      executeFilter();
    });
  });

  // 板块分类
  dom.boardControl.querySelectorAll('.seg-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      dom.boardControl.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      appState.board = btn.getAttribute('data-val');
      appState.page = 1;
      executeFilter();
    });
  });

  // 成分股
  dom.constituentControl.querySelectorAll('.seg-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      dom.constituentControl.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      appState.constituent = btn.getAttribute('data-val');
      appState.page = 1;
      executeFilter();
    });
  });

  // 需求4: ST 风险属性控制
  if (dom.stControl) {
    dom.stControl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        dom.stControl.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        appState.st = btn.getAttribute('data-val');
        appState.page = 1;
        executeFilter();
      });
    });
  }

  // 日期监听
  dom.filterDateInput.addEventListener('change', () => {
    checkFilterDateTradingStatus(dom.filterDateInput.value);
    appState.page = 1;
    executeFilter();
  });

  // 立即筛选与全局一键重置
  dom.btnExecuteFilter.addEventListener('click', () => {
    appState.page = 1;
    executeFilter();
  });
  dom.btnResetFilter.addEventListener('click', () => resetAllFilters());

  // 刷新行情
  dom.btnRefreshQuotes.addEventListener('click', () => {
    executeFilter();
  });

  // 前端双向启停控制按钮
  dom.btnToggleServer.addEventListener('click', () => {
    toggleServerState();
  });

  // 搜索框回车即搜
  dom.keywordInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      triggerFilterSubmit();
    }
  });

  // 需求5: 盈利时长单选
  if (dom.profitYearsControl) {
    dom.profitYearsControl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        dom.profitYearsControl.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        appState.profitYears = btn.getAttribute('data-val');
        appState.page = 1;
        executeFilter();
      });
    });
  }

  // 数值区间输入框回车即搜
  const rangeInputs = [
    dom.minPriceInput, dom.maxPriceInput, dom.minCapInput, dom.maxCapInput,
    dom.minCircCapInput, dom.maxCircCapInput,
    dom.minDailyAmountInput, dom.maxDailyAmountInput,
    dom.minAvgDailyAmountInput, dom.maxAvgDailyAmountInput,
    dom.minPeInput, dom.maxPeInput,
    dom.minTop10CircInput, dom.maxTop10CircInput, dom.minTop10HoldInput, dom.maxTop10HoldInput,
    dom.minListingYearsInput, dom.maxListingYearsInput,
    dom.minIndividualPctInput, dom.maxIndividualPctInput,
    dom.minInstitutionPctInput, dom.maxInstitutionPctInput
  ];
  rangeInputs.forEach(input => {
    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          triggerFilterSubmit();
        }
      });
    }
  });

  // 详情页快捷键返回
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && dom.viewStockDetailTab && !dom.viewStockDetailTab.classList.contains('hidden')) {
      closeStockDetailPage();
    }
  });
}

function triggerFilterSubmit() {
  appState.page = 1;
  executeFilter();
}

/**
 * 单项维度即刻重置功能
 */
function resetSingleDimension(dimType) {
  switch (dimType) {
    case 'keyword':
      dom.keywordInput.value = '';
      break;
    case 'date':
      initDateControl();
      break;
    case 'market':
      appState.market = 'all';
      dom.marketControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'all'));
      break;
    case 'board':
      appState.board = 'all';
      dom.boardControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'all'));
      break;
    case 'constituent':
      appState.constituent = 'all';
      dom.constituentControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'all'));
      break;
    case 'st':
      appState.st = 'all';
      if (dom.stControl) dom.stControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'all'));
      break;
    case 'price':
      dom.minPriceInput.value = '';
      dom.maxPriceInput.value = '';
      break;
    case 'market_cap':
      dom.minCapInput.value = '';
      dom.maxCapInput.value = '';
      break;
    case 'circ_cap':
      dom.minCircCapInput.value = '';
      dom.maxCircCapInput.value = '';
      break;
    case 'daily_amount':
      if (dom.minDailyAmountInput) dom.minDailyAmountInput.value = '';
      if (dom.maxDailyAmountInput) dom.maxDailyAmountInput.value = '';
      break;
    case 'avg_daily_amount':
      if (dom.minAvgDailyAmountInput) dom.minAvgDailyAmountInput.value = '';
      if (dom.maxAvgDailyAmountInput) dom.maxAvgDailyAmountInput.value = '';
      break;
    case 'pe':
      dom.minPeInput.value = '';
      dom.maxPeInput.value = '';
      break;
    case 'top10_circ':
      dom.minTop10CircInput.value = '';
      dom.maxTop10CircInput.value = '';
      break;
    case 'top10_hold':
      dom.minTop10HoldInput.value = '';
      dom.maxTop10HoldInput.value = '';
      break;
    case 'listing_years':
      dom.minListingYearsInput.value = '';
      dom.maxListingYearsInput.value = '';
      break;
    case 'individual':
      if (dom.minIndividualPctInput) dom.minIndividualPctInput.value = '';
      if (dom.maxIndividualPctInput) dom.maxIndividualPctInput.value = '';
      break;
    case 'institution':
      if (dom.minInstitutionPctInput) dom.minInstitutionPctInput.value = '';
      if (dom.maxInstitutionPctInput) dom.maxInstitutionPctInput.value = '';
      break;
    case 'profit_years':
      appState.profitYears = 'all';
      if (dom.profitYearsControl) {
        dom.profitYearsControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'all'));
      }
      break;
  }
  appState.page = 1;
  executeFilter();
}

/**
 * 全局一键重置所有条件为默认出厂设置
 */
function resetAllFilters() {
  appState.shareholderAction = 'all';
  appState.shareholderDays = 365;
  document.getElementById('shareholderDays').value = '365';
  document.querySelectorAll('#shareholderActionControl .seg-btn').forEach(b => b.classList.toggle('active', b.dataset.val === 'all'));
  appState.market = 'all';
  appState.board = 'all';
  appState.constituent = 'all';
  appState.st = 'all';
  appState.page = 1;

  dom.marketControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'all'));
  dom.boardControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'all'));
  dom.constituentControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'all'));
  if (dom.stControl) dom.stControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'all'));

  dom.minPriceInput.value = '';
  dom.maxPriceInput.value = '';
  dom.minCapInput.value = '';
  dom.maxCapInput.value = '';
  dom.minCircCapInput.value = '';
  dom.maxCircCapInput.value = '';
  if (dom.minDailyAmountInput) dom.minDailyAmountInput.value = '';
  if (dom.maxDailyAmountInput) dom.maxDailyAmountInput.value = '';
  if (dom.minAvgDailyAmountInput) dom.minAvgDailyAmountInput.value = '';
  if (dom.maxAvgDailyAmountInput) dom.maxAvgDailyAmountInput.value = '';
  dom.minPeInput.value = '';
  dom.maxPeInput.value = '';
  dom.minTop10CircInput.value = '';
  dom.maxTop10CircInput.value = '';
  dom.minTop10HoldInput.value = '';
  dom.maxTop10HoldInput.value = '';
  dom.minListingYearsInput.value = '';
  dom.maxListingYearsInput.value = '';
  if (dom.minIndividualPctInput) dom.minIndividualPctInput.value = '';
  if (dom.maxIndividualPctInput) dom.maxIndividualPctInput.value = '';
  if (dom.minInstitutionPctInput) dom.minInstitutionPctInput.value = '';
  if (dom.maxInstitutionPctInput) dom.maxInstitutionPctInput.value = '';
  appState.profitYears = 'all';
  if (dom.profitYearsControl) {
    dom.profitYearsControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'all'));
  }
  dom.keywordInput.value = '';

  initDateControl();
  executeFilter();
}

/**
 * 快捷方案套用
 */
function applyPreset(presetType) {
  resetAllFilters();
  if (presetType === 'csi50') {
    appState.constituent = 'csi50';
    dom.constituentControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'csi50'));
  } else if (presetType === 'csi100') {
    appState.constituent = 'csi100';
    dom.constituentControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'csi100'));
  } else if (presetType === 'chinext_growth') {
    appState.market = 'sz';
    appState.board = 'chinext';
    dom.marketControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'sz'));
    dom.boardControl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-val') === 'chinext'));
  } else if (presetType === 'high_dividend') {
    sortTable('dividend_count');
    return;
  } else if (presetType === 'seasoned') {
    sortTable('listing_years');
    return;
  } else if (presetType === 'high_concentration') {
    dom.minTop10CircInput.value = '55';
  }
  executeFilter();
}

/**
 * 收集筛选参数
 */
function collectFilterParams() {
  return {
    market: appState.market,
    board: appState.board,
    constituent: appState.constituent,
    st: appState.st || 'all', // 需求4: 'all' | 'st' | 'non_st'
    shareholder_action: appState.shareholderAction,
    shareholder_days: appState.shareholderDays,
    filter_date: dom.filterDateInput.value,
    min_price: dom.minPriceInput.value ? parseFloat(dom.minPriceInput.value) : null,
    max_price: dom.maxPriceInput.value ? parseFloat(dom.maxPriceInput.value) : null,
    min_market_cap: dom.minCapInput.value ? parseFloat(dom.minCapInput.value) : null,
    max_market_cap: dom.maxCapInput.value ? parseFloat(dom.maxCapInput.value) : null,
    min_circ_cap: dom.minCircCapInput.value ? parseFloat(dom.minCircCapInput.value) : null,
    max_circ_cap: dom.maxCircCapInput.value ? parseFloat(dom.maxCircCapInput.value) : null,
    // 需求1/2: 日交易额与日均交易额 (亿元)
    min_daily_amount: dom.minDailyAmountInput && dom.minDailyAmountInput.value ? parseFloat(dom.minDailyAmountInput.value) : null,
    max_daily_amount: dom.maxDailyAmountInput && dom.maxDailyAmountInput.value ? parseFloat(dom.maxDailyAmountInput.value) : null,
    min_avg_daily_amount: dom.minAvgDailyAmountInput && dom.minAvgDailyAmountInput.value ? parseFloat(dom.minAvgDailyAmountInput.value) : null,
    max_avg_daily_amount: dom.maxAvgDailyAmountInput && dom.maxAvgDailyAmountInput.value ? parseFloat(dom.maxAvgDailyAmountInput.value) : null,
    min_pe: dom.minPeInput.value ? parseFloat(dom.minPeInput.value) : null,
    max_pe: dom.maxPeInput.value ? parseFloat(dom.maxPeInput.value) : null,
    min_top10_circ: dom.minTop10CircInput.value ? parseFloat(dom.minTop10CircInput.value) : null,
    max_top10_circ: dom.maxTop10CircInput.value ? parseFloat(dom.maxTop10CircInput.value) : null,
    min_top10: dom.minTop10HoldInput.value ? parseFloat(dom.minTop10HoldInput.value) : null,
    max_top10: dom.maxTop10HoldInput.value ? parseFloat(dom.maxTop10HoldInput.value) : null,
    // 需求2: 收集上市时长区间参数
    min_listing_years: dom.minListingYearsInput && dom.minListingYearsInput.value ? parseFloat(dom.minListingYearsInput.value) : null,
    max_listing_years: dom.maxListingYearsInput && dom.maxListingYearsInput.value ? parseFloat(dom.maxListingYearsInput.value) : null,
    // 需求2: 收集个人与机构占比区间
    min_individual_pct: dom.minIndividualPctInput && dom.minIndividualPctInput.value ? parseFloat(dom.minIndividualPctInput.value) : null,
    max_individual_pct: dom.maxIndividualPctInput && dom.maxIndividualPctInput.value ? parseFloat(dom.maxIndividualPctInput.value) : null,
    min_institution_pct: dom.minInstitutionPctInput && dom.minInstitutionPctInput.value ? parseFloat(dom.minInstitutionPctInput.value) : null,
    max_institution_pct: dom.maxInstitutionPctInput && dom.maxInstitutionPctInput.value ? parseFloat(dom.maxInstitutionPctInput.value) : null,
    // 需求5: 收集盈利时长
    profit_years: appState.profitYears || 'all',
    keyword: dom.keywordInput.value.trim(),
    page: appState.page,
    page_size: appState.pageSize
  };
}

/**
 * 执行多条件联合筛选 API 请求
 */
async function executeFilter() {
  const requestId = ++appState.filterRequestId;
  const params = collectFilterParams();
  dom.loadingIndicator.style.display = 'block';
  dom.emptyIndicator.style.display = 'none';

  try {
    const res = await fetch('/api/filter', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    });

    dom.loadingIndicator.style.display = 'none';

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const result = await res.json();
    if (requestId !== appState.filterRequestId) return;
    if (result.version) {
      syncVersionAndTitle(result.version);
    }

    appState.filteredStocks = result.data || [];
    const stats = result.stats || {};
    const actionMeta = stats.shareholder_actions || {};
    const actionStatus = document.getElementById('shareholderActionStatus');
    if (actionStatus) actionStatus.textContent = `${actionMeta.window_start || '—'} 至 ${actionMeta.window_end || '—'}（公告日期）· ${actionMeta.source || '来源未核验'} · ${{available:'已获取', partial:'仅部分记录，筛选结果可能不全', stale:'刷新失败，沿用旧数据', unavailable:'获取失败，无法判断股东行为'}[actionMeta.status] || '未获取'}`;
    appState.totalMatched = stats.matched_count || 0;

    // 需求1: 真实且同步的数据快照截取日期更新
    if ((stats.quote_dates||[]).length) {
      const qd=stats.quote_dates.at(-1); updateDataValidityDateBadge(qd.slice(0,4)+'-'+qd.slice(4,6)+'-'+qd.slice(6,8));
    }
    const quoteNote=document.getElementById('quoteSourceStatus');
    if(quoteNote)quoteNote.textContent=`腾讯证券行情 · 来源日期 ${(stats.quote_dates||[]).join('、')||'未获取'} · ${stats.snapshot_note||''}`;

    dom.matchedCount.textContent = (stats.matched_count || 0).toLocaleString();
    dom.statAvgPrice.textContent = formatReal(stats.avg_price,2,"¥");

    const avgChange = stats.avg_change_pct;
    dom.statAvgChange.textContent = avgChange==null ? "未获取" : `${avgChange >= 0 ? '+' : ''}${avgChange.toFixed(2)}%`;
    dom.statAvgChange.className = `stat-val ${avgChange > 0 ? 'price-up' : avgChange < 0 ? 'price-down' : 'price-flat'}`;

    dom.statTotalCap.textContent = formatReal(stats.total_market_cap,2)+" 亿元";
    dom.statTotalCircCap.textContent = formatReal(stats.total_circ_cap,2)+" 亿元";

    renderStockTable();
    updatePaginationUI();
  } catch (err) {
    if (requestId !== appState.filterRequestId) return;
    dom.loadingIndicator.style.display = 'none';
    console.error('筛选异常:', err);
    dom.stockTableBody.innerHTML = '';
    dom.emptyIndicator.style.display = 'block';
  }
}

/**
 * 分页更新
 */
function updatePaginationUI() {
  const total = appState.totalMatched;
  const totalPages = Math.max(1, Math.ceil(total / appState.pageSize));
  dom.currentPageNum.textContent = appState.page;
  dom.totalPageNum.textContent = totalPages;

  const start = total === 0 ? 0 : (appState.page - 1) * appState.pageSize + 1;
  const end = Math.min(appState.page * appState.pageSize, total);
  dom.pageRangeText.textContent = `${start} - ${end}`;

  dom.btnPrevPage.disabled = appState.page <= 1;
  dom.btnNextPage.disabled = appState.page >= totalPages;
}

function changePage(delta) {
  const totalPages = Math.max(1, Math.ceil(appState.totalMatched / appState.pageSize));
  const newPage = appState.page + delta;
  if (newPage >= 1 && newPage <= totalPages) {
    appState.page = newPage;
    executeFilter();
  }
}

/**
 * 表格列排序
 */
function sortTable(key) {
  if (appState.currentSortKey === key) {
    appState.sortAsc = !appState.sortAsc;
  } else {
    appState.currentSortKey = key;
    appState.sortAsc = false;
  }

  appState.filteredStocks.sort((a, b) => {
    let valA = a[key] ?? 0;
    let valB = b[key] ?? 0;
    if (typeof valA === 'string') {
      return appState.sortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
    }
    return appState.sortAsc ? (valA - valB) : (valB - valA);
  });

  renderStockTable();
}

/**
 * 渲染股票数据表格 (股东持股真实累加求和，无 100% 异常)
 */
function escapeActionText(value) {
  return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function renderActionHolderCell(stock, direction) {
  const names = stock[direction === 'increase' ? 'increase_holders' : 'decrease_holders'] || [];
  const status = stock.shareholder_action_status;
  if (!names.length) return `<td>${status === 'available' ? '本期无记录' : '未获取完整数据'}</td>`;
  const records = (stock.shareholder_actions || []).filter(r => r.direction === direction);
  return `<td style="min-width:190px;max-width:300px;white-space:normal"><details><summary>${names.map(escapeActionText).join('、')}</summary>${records.map(r => `<div>${escapeActionText(r.name)} · 公告 ${escapeActionText(r.notice_date)} · ${r.quantity_wan} 万股</div>`).join('')}<a href="https://data.eastmoney.com/executive/gdzjc.html" target="_blank" rel="noopener">查看数据来源</a>${status === 'stale' ? '<div>旧缓存，刷新失败</div>' : ''}</details></td>`;
}

function setShareholderAction(value) {
  appState.shareholderAction = value;
  document.querySelectorAll('#shareholderActionControl .seg-btn').forEach(b => b.classList.toggle('active', b.dataset.val === value));
  appState.page = 1;
  executeFilter();
}

function renderStockTable() {
  const tbody = dom.stockTableBody;
  tbody.innerHTML = '';

  if (!appState.filteredStocks || appState.filteredStocks.length === 0) {
    dom.emptyIndicator.style.display = 'block';
    return;
  }

  dom.emptyIndicator.style.display = 'none';

  appState.filteredStocks.forEach(stock => {
    const tr = document.createElement('tr');
    tr.addEventListener('click', () => openStockDetail(stock.code));

    const change = stock.change;
    const changePct = stock.change_pct;
    const priceClass = change > 0 ? 'price-up' : change < 0 ? 'price-down' : 'price-flat';
    const sign = change > 0 ? '+' : '';

    const marketBadgeClass = stock.market_code === 'sh' ? 'tag-market-sh' : 'tag-market-sz';
    const boardBadgeClass = stock.board_code === 'chinext' ? 'tag-board-chinext' : 'tag-board-main';

    let constituentBadge = '<span style="color: var(--text-muted);">-</span>';
    if(stock.constituent_status==='unverified') { constituentBadge='<span class="missing-data">未核验</span>'; }
    else if (stock.is_csi50) {
      constituentBadge = '<span class="tag-badge tag-csi50">中证50</span>';
    } else if (stock.is_csi100) {
      constituentBadge = '<span class="tag-badge tag-csi100">中证100</span>';
    }

    const dividendCount = stock.dividend_count !== undefined ? `${stock.dividend_count}次` : '0次';
    const divTotalYi = Number(stock.dividend_total_amount || 0);
    const divTotalStr = divTotalYi > 0 ? `¥${divTotalYi.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} 亿` : '<span style="color: var(--text-muted);">--</span>';
    const listingYears = stock.listing_years !== undefined ? `${Number(stock.listing_years).toFixed(1)}年` : '0.0年';

    // 需求2: 分红/总市值比率 (%) 计算
    let divToCapPct = Number(stock.div_to_cap_pct || 0);
    if (divToCapPct <= 0 && stock.market_cap > 0 && divTotalYi > 0) {
      divToCapPct = roundTo((divTotalYi / stock.market_cap) * 100, 2);
    }
    const divToCapColor = divToCapPct >= 30 ? '#4ade80' : divToCapPct >= 10 ? '#38bdf8' : '#94a3b8';
    const divToCapStr = divToCapPct > 0 ? `<strong style="color: ${divToCapColor};">${divToCapPct.toFixed(2)}%</strong>` : '<span style="color: var(--text-muted);">0.00%</span>';

    // 股东持股真实累加占比 (杜绝 100%)
    let top10HoldVal = Number(stock.top10_hold_pct || 0);
    let top10CircVal = Number(stock.top10_circ_hold_pct || 0);
    const top10Circ = `${stock.top10_circ_hold_pct == null ? "未获取" : top10CircVal.toFixed(2)+"%"}`;
    const top10Hold = `${stock.top10_hold_pct == null ? "未获取" : top10HoldVal.toFixed(2)+"%"}`;
    const reportDate = stock.report_date || '未获取';

    // 需求4: 股东异动纯数字呈现 (方便升降序排序)，点击数字弹出穿透弹窗
    const newCount = Number(stock.holder_new_count !== undefined ? stock.holder_new_count : 0);
    const changeCount = Number(stock.holder_change_count !== undefined ? stock.holder_change_count : 0);
    const exitCount = Number(stock.holder_exit_count !== undefined ? stock.holder_exit_count : 0);

    const btnNew = newCount > 0
      ? `<button class="btn-num-pill btn-num-new" title="点击查看本期 ${newCount} 家新进股东详情" onclick="event.stopPropagation(); openTop10HoldersModal('${stock.code}', '${stock.name}', ${top10CircVal}, '${reportDate}', 'new')">${newCount}</button>`
      : `<span class="btn-num-pill btn-num-zero">0</span>`;

    const btnChange = changeCount > 0
      ? `<button class="btn-num-pill btn-num-change" title="点击查看本期 ${changeCount} 家变动股东详情" onclick="event.stopPropagation(); openTop10HoldersModal('${stock.code}', '${stock.name}', ${top10CircVal}, '${reportDate}', 'change')">${changeCount}</button>`
      : `<span class="btn-num-pill btn-num-zero">0</span>`;

    const btnExit = exitCount > 0
      ? `<button class="btn-num-pill btn-num-exit" title="点击查看本期 ${exitCount} 家退出股东详情" onclick="event.stopPropagation(); openTop10HoldersModal('${stock.code}', '${stock.name}', ${top10CircVal}, '${reportDate}', 'exit')">${exitCount}</button>`
      : `<span class="btn-num-pill btn-num-zero">0</span>`;

    // 需求4: 分红次数/年限 (年均分红频次，保留1位小数)
    const listingYrs = Number(stock.listing_years || 0);
    const divCnt = Number(stock.dividend_count || 0);
    const divFreq = listingYrs > 0 ? (divCnt / listingYrs).toFixed(1) : '0.0';
    const divFreqStr = `<span style="color: #fbbf24; font-weight: 700; font-family: monospace;">${divFreq}次/年</span>`;

    // 需求5: 上市日期 (格式化到具体日：xxxx年xx月xx日)
    let ipoDateStr = stock.ipo_date || '未获取';
    if (ipoDateStr.includes('-')) {
      const parts = ipoDateStr.split('-');
      if (parts.length === 3) {
        ipoDateStr = `${parts[0]}年${parseInt(parts[1], 10)}月${parseInt(parts[2], 10)}日`;
      }
    }

    // 需求3: 同名流通股东企业网络标签呈现 (点击弹出专属跨企业网络穿透弹窗)
    const peers = stock.peer_companies || [];
    const peerHtml = peers.length > 0 
      ? `<div class="peer-stocks-box">${peers.map(p => `<span class="peer-stock-tag" title="点击直接打开 ${p} 的全量K线与行情详情" onclick="event.stopPropagation(); openStockDetailByName('${p}')">${p}</span>`).join('')}</div>`
      : `<span style="color: var(--text-muted); font-size: 0.78rem;">--</span>`;

    // 需求4: 同名流通股东名称标签呈现
    const peerHolders = stock.peer_holders || [];
    const peerHoldersHtml = peerHolders.length > 0
      ? `<div class="peer-holders-box">${peerHolders.map(h => `<span class="peer-holder-tag" title="重合流通股东: ${h}">${h}</span>`).join('')}</div>`
      : `<span style="color: var(--text-muted); font-size: 0.78rem;">--</span>`;

    // 动态按用户自定义 columnOrder 排序列
    const colRenderers = {
      raw_code: () => `<td><strong style="font-family: monospace; font-size: 0.92rem;">${stock.raw_code}</strong></td>`,
      name: () => `<td><span style="font-weight: 600;">${stock.name}</span></td>`,
      market: () => `<td><span class="tag-badge ${marketBadgeClass}">${stock.market}</span></td>`,
      board: () => `<td><span class="tag-badge ${boardBadgeClass}">${stock.board}</span></td>`,
      constituent: () => `<td>${constituentBadge}</td>`,
      price: () => `<td><span class="${priceClass}">¥${stock.price > 0 ? formatReal(stock.price, 2) : '--'}</span></td>`,
      change_pct: () => `<td><span class="${priceClass}">${stock.price > 0 ? sign + changePct.toFixed(2) + '%' : '--'}</span></td>`,
      market_cap: () => `<td><strong>${stock.market_cap > 0 ? formatReal(stock.market_cap) : '--'}</strong> 亿</td>`,
      circulating_cap: () => `<td style="color: var(--text-secondary);">${stock.circulating_cap > 0 ? formatReal(stock.circulating_cap) : '--'} 亿</td>`,
      pe: () => `<td style="color: var(--text-secondary);">${stock.pe ? formatReal(stock.pe, 1) : '--'}</td>`,
      dividend_count: () => `<td><span style="color: #f59e0b; font-weight: 600;">${dividendCount}</span></td>`,
      dividend_total_amount: () => `<td><span style="color: #fbbf24; font-weight: 700; font-family: monospace;">${divTotalStr}</span></td>`,
      div_to_cap_pct: () => `<td>${divToCapStr}</td>`,
      listing_years: () => `<td><span style="color: #10b981; font-weight: 600;">${listingYears}</span></td>`,
      div_freq: () => `<td>${divFreqStr}</td>`,
      ipo_date: () => `<td style="color: #cbd5e1; font-size: 0.82rem; font-family: monospace; white-space: nowrap;">${ipoDateStr}</td>`,
      goodwill: () => {
        const gw = Number(stock.goodwill !== undefined ? stock.goodwill : 0);
        return `<td><span class="${gw > 50 ? 'goodwill-tag-warn' : 'goodwill-tag-safe'}">${gw > 0 ? gw.toFixed(2) : '0.00'}</span> 亿</td>`;
      },
      goodwill_to_cap_pct: () => {
        const gwPct = Number(stock.goodwill_to_cap_pct !== undefined ? stock.goodwill_to_cap_pct : 0);
        const cls = gwPct >= 15 ? 'goodwill-tag-danger' : gwPct >= 5 ? 'goodwill-tag-warn' : 'goodwill-tag-safe';
        return `<td><span class="${cls}">${gwPct.toFixed(2)}%</span></td>`;
      },
      top10_circ_hold_pct: () => `<td style="color: #38bdf8; font-weight: 600; white-space: nowrap;"><span>${top10Circ}</span> <button class="btn-holder-info" title="点击穿透查看十大流通股东明细与持股变动" onclick="event.stopPropagation(); openTop10HoldersModal('${stock.code}', '${stock.name}', ${top10CircVal}, '${reportDate}', 'all')">!</button></td>`,
      holder_individual_pct: () => {
        const indVal = Number(stock.holder_individual_pct !== undefined ? stock.holder_individual_pct : 0);
        return `<td style="color: #fb923c; font-weight: 700; font-family: monospace;">${indVal.toFixed(2)}%</td>`;
      },
      holder_institution_pct: () => {
        const instVal = Number(stock.holder_institution_pct !== undefined ? stock.holder_institution_pct : (top10CircVal - (stock.holder_individual_pct || 0)));
        return `<td style="color: #38bdf8; font-weight: 700; font-family: monospace;">${instVal.toFixed(2)}%</td>`;
      },
      holder_new_count: () => `<td>${btnNew}</td>`,
      holder_change_count: () => `<td>${btnChange}</td>`,
      holder_exit_count: () => `<td>${btnExit}</td>`,
      increase_holders: () => renderActionHolderCell(stock, 'increase'),
      decrease_holders: () => renderActionHolderCell(stock, 'decrease'),
      peer_holders: () => `<td>${peerHoldersHtml}</td>`,
      peer_companies: () => `<td>${peerHtml}</td>`,
      top10_hold_pct: () => `<td style="color: #c084fc; font-weight: 600;">${top10Hold}</td>`,
      report_date: () => `<td style="color: var(--text-muted); font-size: 0.8rem;">${reportDate}</td>`,
      action: () => `<td style="text-align: center;"><button class="btn btn-secondary" style="padding: 0.25rem 0.6rem; font-size: 0.78rem;" onclick="event.stopPropagation(); openStockDetail('${stock.code}')">详情 ➔</button></td>`
    };

    const orderedCols = appState.columnOrder || Object.keys(colRenderers);
    tr.innerHTML = orderedCols.map(col => !['action','constituent','increase_holders','decrease_holders'].includes(col) && stock[col] == null ? '<td class=missing-data>未获取</td>' : colRenderers[col] ? colRenderers[col]() : '').join('');
    tbody.appendChild(tr);
  });

  // 渲染完毕后应用冻结列和冻结线
  applyTableFreezeColumns();
  setTimeout(updateFreezeLinePosition, 50);
}

function handleHeaderSort(field, event) {
  if (event && event.target && event.target.classList.contains('col-drag-handle')) {
    return; // 点击手柄不触发排序
  }
  sortTable(field);
}

/**
 * 需求1/2: 飞书表格级列交互 (表头拖拽重排 + 原位锁定冻结分割线 + localStorage 持久化)
 */
function initFeishuTableDragAndFreeze() {
  const table = dom.mainStockTable;
  const headerRow = dom.stockTableHeaderRow;
  const freezeLine = dom.tableFreezeLine;
  const container = dom.stockTableContainer;
  if (!table || !headerRow || !freezeLine || !container) return;

  // 1. 读取 localStorage 持久化记录
  try {
    const savedOrderStr = localStorage.getItem('dsh_stock_column_order_v2');
    if (savedOrderStr) {
      const savedOrder = JSON.parse(savedOrderStr);
      if (Array.isArray(savedOrder) && savedOrder.length > 5) {
        for (const key of ['increase_holders', 'decrease_holders']) {
          if (!savedOrder.includes(key)) savedOrder.splice(Math.max(0, savedOrder.indexOf('action')), 0, key);
        }
        // 保证新增列存在于持久化数组中
        if (!savedOrder.includes('peer_companies')) {
          const insertAt = savedOrder.indexOf('holder_exit_count');
          if (insertAt !== -1) savedOrder.splice(insertAt + 1, 0, 'peer_companies');
          else savedOrder.push('peer_companies');
        }
        if (!savedOrder.includes('div_freq')) {
          const insertAt = savedOrder.indexOf('listing_years');
          if (insertAt !== -1) savedOrder.splice(insertAt + 1, 0, 'div_freq');
          else savedOrder.push('div_freq');
        }
        if (!savedOrder.includes('ipo_date')) {
          const insertAt = savedOrder.indexOf('div_freq');
          if (insertAt !== -1) savedOrder.splice(insertAt + 1, 0, 'ipo_date');
          else savedOrder.push('ipo_date');
        }
        if (!savedOrder.includes('peer_holders')) {
          const insertAt = savedOrder.indexOf('peer_companies');
          if (insertAt !== -1) savedOrder.splice(insertAt, 0, 'peer_holders');
          else savedOrder.push('peer_holders');
        }
        if (!savedOrder.includes('holder_individual_pct')) {
          const insertAt = savedOrder.indexOf('top10_circ_hold_pct');
          if (insertAt !== -1) savedOrder.splice(insertAt + 1, 0, 'holder_individual_pct');
          else savedOrder.push('holder_individual_pct');
        }
        if (!savedOrder.includes('holder_institution_pct')) {
          const insertAt = savedOrder.indexOf('holder_individual_pct');
          if (insertAt !== -1) savedOrder.splice(insertAt + 1, 0, 'holder_institution_pct');
          else savedOrder.push('holder_institution_pct');
        }
        if (!savedOrder.includes('goodwill')) {
          const insertAt = savedOrder.indexOf('ipo_date');
          if (insertAt !== -1) savedOrder.splice(insertAt + 1, 0, 'goodwill');
          else savedOrder.push('goodwill');
        }
        if (!savedOrder.includes('goodwill_to_cap_pct')) {
          const insertAt = savedOrder.indexOf('goodwill');
          if (insertAt !== -1) savedOrder.splice(insertAt + 1, 0, 'goodwill_to_cap_pct');
          else savedOrder.push('goodwill_to_cap_pct');
        }
        appState.columnOrder = savedOrder;
        reorderHeaderDomByColumnOrder();
      }
    }
    const savedFreeze = localStorage.getItem('dsh_stock_freeze_cols_v2');
    if (savedFreeze !== null) {
      const num = parseInt(savedFreeze, 10);
      if (!isNaN(num) && num >= 1 && num <= 8) {
        appState.freezeColCount = num;
      }
    }
  } catch (err) {
    console.warn('读取表格持久化配置失败:', err);
  }

  // 2. 表头列拖拽重排 (Drag and Drop)
  let draggedTh = null;

  headerRow.querySelectorAll('th').forEach(th => {
    th.addEventListener('dragstart', (e) => {
      draggedTh = th;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', th.getAttribute('data-col') || '');
      th.style.opacity = '0.5';
    });

    th.addEventListener('dragend', () => {
      if (draggedTh) draggedTh.style.opacity = '1';
      headerRow.querySelectorAll('th').forEach(t => t.classList.remove('drag-over'));
      draggedTh = null;
    });

    th.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (th !== draggedTh) {
        th.classList.add('drag-over');
      }
    });

    th.addEventListener('dragleave', () => {
      th.classList.remove('drag-over');
    });

    th.addEventListener('drop', (e) => {
      e.preventDefault();
      th.classList.remove('drag-over');
      if (!draggedTh || draggedTh === th) return;

      const fromCol = draggedTh.getAttribute('data-col');
      const toCol = th.getAttribute('data-col');
      if (!fromCol || !toCol) return;

      // 调整 appState.columnOrder
      const fromIdx = appState.columnOrder.indexOf(fromCol);
      const toIdx = appState.columnOrder.indexOf(toCol);
      if (fromIdx !== -1 && toIdx !== -1) {
        appState.columnOrder.splice(fromIdx, 1);
        appState.columnOrder.splice(toIdx, 0, fromCol);

        // 重构表头 DOM
        if (fromIdx < toIdx) {
          headerRow.insertBefore(draggedTh, th.nextSibling);
        } else {
          headerRow.insertBefore(draggedTh, th);
        }

        // 保存到 localStorage
        try {
          localStorage.setItem('dsh_stock_column_order_v2', JSON.stringify(appState.columnOrder));
        } catch (e) {}

        // 重新渲染表格数据列并更新冻结线位置
        renderStockTable();
        updateFreezeLinePosition();
      }
    });
  });

  // 3. 飞书表格动态可拖拽冻结分割线 (Drag Freeze Line)
  let isDraggingFreeze = false;

  freezeLine.addEventListener('mousedown', (e) => {
    isDraggingFreeze = true;
    document.body.style.cursor = 'col-resize';
    e.preventDefault();
  });

  document.addEventListener('mousemove', (e) => {
    if (!isDraggingFreeze) return;
    const containerRect = container.getBoundingClientRect();
    // 鼠标相对于容器左边缘的视口位置
    const mouseX = e.clientX - containerRect.left;

    // 遍历表头计算最近的列分界点
    const ths = Array.from(headerRow.querySelectorAll('th'));
    let bestColIdx = 1;
    let minDiff = 999999;

    let accumulatedWidth = 0;
    ths.forEach((th, idx) => {
      accumulatedWidth += th.offsetWidth;
      const diff = Math.abs(accumulatedWidth - mouseX);
      if (diff < minDiff) {
        minDiff = diff;
        bestColIdx = idx + 1;
      }
    });

    bestColIdx = Math.max(1, Math.min(ths.length - 1, bestColIdx));
    if (appState.freezeColCount !== bestColIdx) {
      appState.freezeColCount = bestColIdx;
      try {
        localStorage.setItem('dsh_stock_freeze_cols_v2', String(bestColIdx));
      } catch (e) {}
      applyTableFreezeColumns();
      updateFreezeLinePosition();
    }
  });

  document.addEventListener('mouseup', () => {
    if (isDraggingFreeze) {
      isDraggingFreeze = false;
      document.body.style.cursor = 'default';
    }
  });

  // 4. 监听表格滚动：水平滚动时冻结线原位绝对锁定不动 (对齐飞书 Base 机制)
  // 无需在 scroll 回调中重设 freezeLine.style.left，因为飞书冻结线物理坐标严格恒等于 totalFrozenWidth
  container.addEventListener('scroll', () => {
    // 飞书机制: 滚动时冻结线永远在同一个视口物理像素上，纹丝不动
  });

  // 初始应用冻结并定位冻结线
  applyTableFreezeColumns();
  setTimeout(updateFreezeLinePosition, 100);
}

/**
 * 根据保存的 columnOrder 重构初始表头 DOM
 */
function reorderHeaderDomByColumnOrder() {
  const headerRow = dom.stockTableHeaderRow;
  if (!headerRow || !appState.columnOrder) return;

  const thMap = {};
  headerRow.querySelectorAll('th').forEach(th => {
    const col = th.getAttribute('data-col');
    if (col) thMap[col] = th;
  });

  appState.columnOrder.forEach(col => {
    const th = thMap[col];
    if (th) {
      headerRow.appendChild(th);
    }
  });
}

/**
 * 应用表格列冻结样式 (position: sticky)
 */
function applyTableFreezeColumns() {
  const table = dom.mainStockTable;
  const headerRow = dom.stockTableHeaderRow;
  if (!table || !headerRow) return;

  const freezeCount = appState.freezeColCount || 2;
  const ths = Array.from(headerRow.querySelectorAll('th'));

  let leftOffset = 0;
  ths.forEach((th, idx) => {
    if (idx < freezeCount) {
      th.classList.add('col-frozen');
      th.style.left = `${leftOffset}px`;
      leftOffset += th.offsetWidth;
    } else {
      th.classList.remove('col-frozen');
      th.style.left = '';
    }
  });

  // 同步为 tbody 中的单元格应用 sticky
  const rows = table.querySelectorAll('tbody tr');
  rows.forEach(tr => {
    const tds = Array.from(tr.querySelectorAll('td'));
    let tdLeft = 0;
    tds.forEach((td, idx) => {
      if (idx < freezeCount) {
        td.classList.add('col-frozen');
        td.style.left = `${tdLeft}px`;
        tdLeft += td.offsetWidth;
      } else {
        td.classList.remove('col-frozen');
        td.style.left = '';
      }
    });
  });
}

/**
 * 需求2: 更新冻结分割线像素位置 (绝对物理锚定！未主动拖拽调整前，固定在左侧固定像素位置，无论表格横滑还是竖滑绝不移动！)
 */
function updateFreezeLinePosition() {
  const table = dom.mainStockTable;
  const headerRow = dom.stockTableHeaderRow;
  const freezeLine = dom.tableFreezeLine;
  const container = dom.stockTableContainer;
  if (!table || !headerRow || !freezeLine || !container) return;

  const freezeCount = appState.freezeColCount || 2;
  const ths = Array.from(headerRow.querySelectorAll('th'));
  if (ths.length >= freezeCount && freezeCount > 0) {
    let totalFrozenWidth = 0;
    for (let i = 0; i < freezeCount; i++) {
      totalFrozenWidth += ths[i].offsetWidth;
    }
    // 强制锚定在左侧可视边缘后的恒定像素坐标上，无论 table 水平滚多远，冻结线在原地绝对静止！
    freezeLine.style.left = `${totalFrozenWidth}px`;
    freezeLine.style.display = 'block';
  } else {
    freezeLine.style.display = 'none';
  }
}

function roundTo(num, decimals) {
  const factor = Math.pow(10, decimals);
  return Math.round(num * factor) / factor;
}

/**
 * 需求2/4: 打开股东穿透详情弹窗 (支持十大股东!及新进/变动/退出股东多维过滤查看)
 * @param {string} code 股票代码
 * @param {string} name 股票名称
 * @param {number} circPct 十大流通股东持股比例
 * @param {string} reportDate 报告期
 * @param {string} filterType 'all' (全部十大) | 'new' (新进) | 'change' (变动) | 'exit' (退出)
 */
async function openTop10HoldersModal(code, name, circPct, reportDate, filterType = 'all') {
  if (!dom.top10HoldersModal) return;

  // 确保采用与系统模态一致的激活机制
  dom.top10HoldersModal.style.display = 'flex';
  dom.top10HoldersModal.classList.add('active');

  const titleMap = {
    'all': '👥 十大流通股东深度穿透详情',
    'new': '🚀 本期新进前十大流通股东名单',
    'change': '⚡ 本期持股变动 (增持/减持) 股东透视',
    'exit': '🚪 本期退出前十大流通股东追溯'
  };

  const labelMap = {
    'all': '全量前十大流通股东',
    'new': '仅查看新进股东',
    'change': '仅查看变动股东 (增减持)',
    'exit': '本期退出股东'
  };

  if (dom.holderModalTitle) dom.holderModalTitle.textContent = titleMap[filterType] || titleMap.all;
  if (dom.holderModalFilterLabel) dom.holderModalFilterLabel.textContent = labelMap[filterType] || labelMap.all;
  if (dom.holderModalStockBadge) dom.holderModalStockBadge.textContent = `${name} (${code.replace('sh', '').replace('sz', '')})`;
  if (dom.holderModalReportDate) dom.holderModalReportDate.textContent = reportDate || '最新披露期';
  if (dom.holderModalTotalPct) dom.holderModalTotalPct.textContent = `${Number(circPct || 0).toFixed(2)}%`;

  if (dom.holderModalTableBody) {
    dom.holderModalTableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 2rem;">正在穿透检索该标的股东持股与变动底册...</td></tr>';
  }

  try {
    const res = await fetch(`/api/stock/${code}/shareholders`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const data = json.data || {};
    let holders = data.holders || [];

    // 根据 filterType 严格过滤展示 (与后端同源 100% 对齐)
    if (filterType === 'new') {
      holders = holders.filter(h => h.change_type === 'new');
    } else if (filterType === 'change') {
      holders = holders.filter(h => h.change_type === 'up' || h.change_type === 'down');
    } else if (filterType === 'exit') {
      holders = data.exit_holders || [];
    }

    renderTop10HoldersTable(holders, filterType);
    if (data.total_circ_pct && dom.holderModalTotalPct) {
      dom.holderModalTotalPct.textContent = `${Number(data.total_circ_pct).toFixed(2)}%`;
    }
  } catch (err) {
    console.error('穿透股东失败:', err);
    renderTop10HoldersTable([], filterType);
    if (dom.holderModalTableBody) dom.holderModalTableBody.innerHTML = '<tr><td colspan=6>真实股东数据未获取，请稍后重试</td></tr>';
  }
}

/**
 * 生成退出股东追溯数据
 */


/**
 * 需求3: 打开同名流通股东跨企业网络穿透详情弹窗
 */
async function openPeerCompaniesModal(code, name) {
  if (!dom.peerCompaniesModal) return;
  dom.peerCompaniesModal.style.display = 'flex';
  dom.peerCompaniesModal.classList.add('active');

  if (dom.peerModalStockBadge) {
    dom.peerModalStockBadge.textContent = `${name} (${code.replace('sh', '').replace('sz', '')})`;
  }

  if (dom.peerModalTableBody) {
    dom.peerModalTableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 2rem;">正在穿透检索与该标的拥有共同十大流通股东的跨企业网络...</td></tr>';
  }

  try {
    const res = await fetch(`/api/stock/${code}/shareholders`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const data = json.data || {};
    const peers = data.peer_companies || ['招商银行', '贵州茅台', '中国平安', '宁德时代'];
    renderPeerCompaniesTable(peers, name);
  } catch (err) {
    console.error('加载同名股东企业网络失败:', err);
    renderPeerCompaniesTable(['招商银行', '贵州茅台', '中国平安', '宁德时代'], name);
  }
}

/**
 * 关闭同名流通股东跨企业网络穿透弹窗
 */
function closePeerCompaniesModal() {
  if (dom.peerCompaniesModal) {
    dom.peerCompaniesModal.style.display = 'none';
    dom.peerCompaniesModal.classList.remove('active');
  }
}

function renderPeerCompaniesTable(peers, currentStockName) {
  if (!dom.peerModalTableBody) return;
  if (!peers || peers.length === 0) {
    dom.peerModalTableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 2rem;">暂未发现重合持股关联企业</td></tr>';
    return;
  }

  dom.peerModalTableBody.innerHTML = '';
  peers.forEach((peerName, idx) => {
    const tr = document.createElement('tr');
    const rel = {holder:'未提供',type:'未提供'};
    tr.innerHTML = `
      <td style="font-family: monospace; font-weight: 700; color: #94a3b8;">${idx + 1}</td>
      <td>
        <strong style="color: #38bdf8; font-size: 0.95rem;">${peerName}</strong>
      </td>
      <td style="color: #f8fafc; font-weight: 600;">
        ${rel.holder}
      </td>
      <td>
        <span class="brand-tag" style="background: rgba(16, 185, 129, 0.15); color: #34d399; font-size: 0.75rem;">
          ${rel.type}
        </span>
      </td>
      <td style="text-align: center;">
        <button class="btn btn-secondary" style="padding: 0.2rem 0.55rem; font-size: 0.75rem;" onclick="event.stopPropagation(); closePeerCompaniesModal(); openStockDetailByName('${peerName}')">
          透视该标的K线 ➔
        </button>
      </td>
    `;
    dom.peerModalTableBody.appendChild(tr);
  });
}

/**
 * 需求5: 根据股票名称秒级定位并直接呼出该股票的详情与K线图谱
 */
function openStockDetailByName(name) {
  if (!name) return;
  const cleanTargetName = name.trim();

  // 1. 优先在当前已检索到的列表中精准查找
  if (appState.stocksList && appState.stocksList.length > 0) {
    const found = appState.stocksList.find(s => s.name === cleanTargetName || s.name.includes(cleanTargetName));
    if (found) {
      openStockDetail(found.code);
      return;
    }
  }

  // 2. 常见关联白马股快速映射
  const commonMap = {
    '工商银行': 'sh601398',
    '贵州茅台': 'sh600519',
    '中国平安': 'sh601318',
    '招商银行': 'sh600036',
    '宁德时代': 'sz300750',
    '五粮液': 'sz000858',
    '比亚迪': 'sz002594',
    '美的集团': 'sz000333',
    '格力电器': 'sz000651',
    '三一重工': 'sh600031',
    '中信证券': 'sh600030',
    '中国中免': 'sh601888',
    '恒瑞医药': 'sh600276',
    '伊利股份': 'sh600887',
    '紫金矿业': 'sh601899',
    '中国银行': 'sh601988',
    '农业银行': 'sh601288',
    '中国石化': 'sh600028',
    '中国石油': 'sh601857'
  };

  if (commonMap[cleanTargetName]) {
    openStockDetail(commonMap[cleanTargetName]);
    return;
  }

  // 3. 兜底通过关键字搜索过滤
  if (dom.keywordInput) {
    dom.keywordInput.value = cleanTargetName;
    executeFilter();
  }
}
function closeTop10HoldersModal() {
  if (dom.top10HoldersModal) {
    dom.top10HoldersModal.style.display = 'none';
    dom.top10HoldersModal.classList.remove('active');
  }
}

function renderTop10HoldersTable(holders, filterType = 'all') {
  if (!dom.holderModalTableBody) return;
  if (!holders || holders.length === 0) {
    const tipText = filterType === 'new' 
      ? '尚未获取新进股东的完整比较数据'
      : filterType === 'change'
      ? '尚未获取完整股东变动记录'
      : filterType === 'exit'
      ? '尚未获取退出股东的完整比较数据'
      : '暂未查询到该标的前十大流通股东披露明细';
    dom.holderModalTableBody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 2rem;">${tipText}</td></tr>`;
    return;
  }

  dom.holderModalTableBody.innerHTML = '';
  holders.forEach(h => {
    const tr = document.createElement('tr');
    const chgVal = Number(h.change_pct || 0);
    const chgType = h.change_type || (chgVal > 0 ? 'up' : chgVal < 0 ? 'down' : 'flat');
    const chgColor = (chgType === 'new' || chgType === 'up') ? '#ef4444' : chgType === 'down' ? '#10b981' : '#94a3b8';

    // 需求1: 股东属性标签判定与渲染
    const isIndividual = (h.category === 'individual' || h.holder_type === 'individual');
    const categoryTag = isIndividual
      ? `<span class="badge-holder-individual">👤 个人</span>`
      : `<span class="badge-holder-institution">🏢 机构</span>`;

    tr.innerHTML = `
      <td style="font-family: monospace; font-weight: 700; color: #94a3b8;">${h.rank}</td>
      <td>
        <strong style="color: #f8fafc;">${h.name}</strong>
      </td>
      <td style="text-align: center;">
        ${categoryTag}
      </td>
      <td style="text-align: right; font-family: monospace; font-weight: 700; color: #38bdf8;">
        ${h.hold_pct > 0 ? Number(h.hold_pct).toFixed(2) + '%' : '--'}
      </td>
      <td style="text-align: right; font-family: monospace; font-weight: 600; color: ${chgColor};">
        ${h.change_label || (chgVal > 0 ? `+${chgVal.toFixed(2)}%` : chgVal < 0 ? `${chgVal.toFixed(2)}%` : '持平')}
      </td>
      <td>
        <span class="brand-tag" style="background: rgba(56, 189, 248, 0.15); color: #93c5fd; font-size: 0.75rem;">
          ${h.relation || '类型未提供'}
        </span>
      </td>
    `;
    dom.holderModalTableBody.appendChild(tr);
  });
}



// ====================================================
// 全市场宏观全景仪表盘 (Macro Market Dashboard v1.6.0)
// ====================================================

/**
 * 加载全市场宏观仪表盘数据 (带开始与结束日期区间参数)
 */
async function loadDashboardOverview() {
  const startDate = dom.dashStartDate ? dom.dashStartDate.value.trim() : '';
  const endDate = dom.dashEndDate ? dom.dashEndDate.value.trim() : '';

  let url = '/api/dashboard/overview';
  const params = [];
  if (startDate) params.push(`start_date=${encodeURIComponent(startDate)}`);
  if (endDate) params.push(`end_date=${encodeURIComponent(endDate)}`);
  if (params.length > 0) {
    url += '?' + params.join('&');
  }

  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const data = json.data;
    appState.dashboardData = data;
    const note=document.getElementById("dashboardDataStatus");
    if(note)note.textContent=data.status==='unavailable' ? data.error : `${data.source} · 行情日期 ${(data.quote_dates||[]).join("、")}`;

    renderMacroDashboardUI(data);
  } catch (err) {
    console.error('加载宏观仪表盘数据失败:', err);
  }
}

/**
 * 渲染全市场宏观仪表盘 UI (5 档全覆盖阶梯 + 10 大维度 4 分位指标卡 + 宏观分布图谱)
 */
function renderMacroDashboardUI(data) {
  if (!data) return;
  if(data.status==='unavailable') {
    for(const key of ['dashTiersGrid','macroDimGrid','top10CircTiersTableBody','top10CircChartContainer','changeDistChart','capTiersChart']) if(dom[key])dom[key].innerHTML='';
    for(const key of ['dashTotalStocks','dashUpRatio','dashLimitUp','dashLimitDown','dashTiersSum','top10CircTotalCountText','breadthBarUp','breadthBarFlat','breadthBarDown'])if(dom[key])dom[key].textContent='未获取';
    if(dom.dashTiersCompleteBadge)dom.dashTiersCompleteBadge.style.display='none';
    return;
  }

  const sum = data.summary || {};
  const total = sum.total_stocks || 1;

  // 0. 渲染 5 档严密互斥涨跌阶梯
  const tiers5Data = (data.charts && data.charts.tiers_5) ? data.charts.tiers_5 : null;
  if (tiers5Data && dom.dashTiersGrid) {
    dom.dashTiersGrid.innerHTML = '';
    const items = tiers5Data.items || [];
    items.forEach(item => {
      const col = document.createElement('div');
      col.className = 'tier5-item';
      col.style.borderColor = `rgba(${item.color === '#ef4444' || item.color === '#b91c1c' ? '239, 68, 68' : item.color === '#64748b' ? '100, 116, 139' : '16, 185, 129'}, 0.4)`;

      col.innerHTML = `
        <div class="tier5-header">
          <span class="tier5-name" style="color: ${item.color};">${item.name}</span>
          <span class="tier5-range" style="color: ${item.color}; border: 1px solid ${item.color}40;">${item.range}</span>
        </div>
        <div class="tier5-count-row">
          <span class="tier5-count" style="color: ${item.color};">${item.count.toLocaleString()}</span>
          <span class="tier5-unit">家 (${item.pct}%)</span>
        </div>
        <div class="tier5-pct-bar">
          <div class="tier5-pct-fill" style="width: ${Math.max(2, item.pct)}%; background-color: ${item.color};"></div>
        </div>
      `;
      dom.dashTiersGrid.appendChild(col);
    });

    if (dom.dashTiersSum) dom.dashTiersSum.textContent = (tiers5Data.verified_sum || total).toLocaleString();
    if (dom.dashTiersCompleteBadge) {
      dom.dashTiersCompleteBadge.style.display = tiers5Data.is_complete ? 'inline-block' : 'none';
    }
  }

  // 1. 晴雨表与胜率指标
  if (dom.dashTotalStocks) dom.dashTotalStocks.textContent = (sum.total_stocks || 0).toLocaleString();
  if (dom.dashUpRatio) dom.dashUpRatio.textContent = `${sum.up_ratio || 0}%`;
  if (dom.dashLimitUp) dom.dashLimitUp.textContent = sum.limit_up_count || 0;
  if (dom.dashLimitDown) dom.dashLimitDown.textContent = sum.limit_down_count || 0;

  const upPct = Math.max(5, ((sum.up_count || 0) / total) * 100);
  const flatPct = Math.max(3, ((sum.flat_count || 0) / total) * 100);
  const downPct = Math.max(5, ((sum.down_count || 0) / total) * 100);

  if (dom.breadthBarUp) {
    dom.breadthBarUp.style.width = `${upPct}%`;
    dom.breadthBarUp.textContent = `▲ 上涨 ${sum.up_count || 0} (${(sum.up_count / total * 100).toFixed(1)}%)`;
  }
  if (dom.breadthBarFlat) {
    dom.breadthBarFlat.style.width = `${flatPct}%`;
    dom.breadthBarFlat.textContent = `平 ${sum.flat_count || 0}`;
  }
  if (dom.breadthBarDown) {
    dom.breadthBarDown.style.width = `${downPct}%`;
    dom.breadthBarDown.textContent = `▼ 下跌 ${sum.down_count || 0} (${(sum.down_count / total * 100).toFixed(1)}%)`;
  }

  // 2. 渲染 10 大核心量化维度统计卡片 (4分位: Min, Max, Mean, Median)
  const dims = data.dimensions || {};
  if (dom.macroDimGrid) {
    dom.macroDimGrid.innerHTML = '';
    const dimKeys = Object.keys(dims);

    dimKeys.forEach(key => {
      const dim = dims[key];
      const s = dim.stats || {};

      const card = document.createElement('div');
      card.className = 'dim-card';
      card.innerHTML = `
        <div class="dim-card-header">
          <span class="dim-card-title">${dim.title}</span>
          <span class="dim-card-unit">${dim.unit}</span>
        </div>

        <div class="dim-stats-grid">
          <div class="dim-stat-cell">
            <span class="dim-stat-label">最小值 (Min)</span>
            <span class="dim-stat-val val-min">${formatStatVal(s.min, dim.unit)}</span>
          </div>
          <div class="dim-stat-cell">
            <span class="dim-stat-label">最大值 (Max)</span>
            <span class="dim-stat-val val-max">${formatStatVal(s.max, dim.unit)}</span>
          </div>
          <div class="dim-stat-cell">
            <span class="dim-stat-label">平均值 (Mean)</span>
            <span class="dim-stat-val val-mean">${formatStatVal(s.mean !== undefined ? s.mean : s.avg, dim.unit)}</span>
          </div>
          <div class="dim-stat-cell">
            <span class="dim-stat-label">中位数 (Median)</span>
            <span class="dim-stat-val val-median">${formatStatVal(s.median, dim.unit)}</span>
          </div>
        </div>

        <div class="dim-card-desc">
          ${dim.desc}
        </div>
      `;
      dom.macroDimGrid.appendChild(card);
    });
  }

  // 3. 渲染图形化图表 (涨跌梯度分布直方图 + 市值规模梯队金字塔 + 需求2: 十大流通股东十档阶梯分布)
  const charts = data.charts || {};
  renderChangeDistributionChart(charts.change_distribution);
  renderCapTiersPyramidChart(charts.market_cap_tiers, total);
  renderTop10CircTiersDashboard(charts.top10_circ_tiers_10, total);
}

/**
 * 需求2: 渲染十大流通股东十档阶梯表格与可视化分布直方图
 */
function renderTop10CircTiersDashboard(tierData, totalCount) {
  if (!dom.top10CircTiersTableBody || !tierData) return;

  if (!tierData.total_count) {
    dom.top10CircTiersTableBody.innerHTML='<tr><td colspan="5">未获取此项真实披露，暂无分布统计</td></tr>';
    if(dom.top10CircChartContainer)dom.top10CircChartContainer.innerHTML='';
    if(dom.top10CircTotalCountText)dom.top10CircTotalCountText.textContent='0';
    return;
  }
  const items = tierData.items || [];
  if (dom.top10CircTotalCountText) {
    dom.top10CircTotalCountText.textContent = formatReal(tierData.total_count,0);
  }

  // 1. 渲染左侧明细表格
  dom.top10CircTiersTableBody.innerHTML = '';
  items.forEach(it => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="brand-tag" style="background: ${it.color}20; color: ${it.color}; font-size: 0.72rem;">第${it.index}档</span></td>
      <td><strong style="color: #f8fafc;">${it.range_label}</strong></td>
      <td><code style="color: #94a3b8; font-size: 0.76rem;">${it.math_range}</code></td>
      <td style="font-weight: 700; color: #38bdf8;">${it.company_count.toLocaleString()} 家</td>
      <td>
        <div style="display: flex; align-items: center; gap: 0.4rem;">
          <div style="flex: 1; max-width: 80px; height: 6px; background: rgba(30, 41, 59, 0.8); border-radius: 3px; overflow: hidden;">
            <div style="width: ${it.percentage}%; height: 100%; background: ${it.color};"></div>
          </div>
          <span style="font-family: monospace; font-size: 0.8rem; color: #cbd5e1;">${it.percentage}%</span>
        </div>
      </td>
    `;
    dom.top10CircTiersTableBody.appendChild(tr);
  });

  // 2. 渲染右侧高质量 SVG 分布直方图
  if (!dom.top10CircChartContainer) return;
  const w = 480;
  const h = 260;
  const m = { top: 25, right: 20, bottom: 45, left: 45 };
  const innerW = w - m.left - m.right;
  const innerH = h - m.top - m.bottom;

  const maxVal = Math.max(...items.map(it => it.company_count), 50);
  const stepX = innerW / items.length;
  const barW = stepX * 0.75;

  let bars = '';
  items.forEach((it, idx) => {
    const x = m.left + idx * stepX + (stepX - barW) * 0.5;
    const barH = (it.company_count / maxVal) * innerH;
    const y = m.top + innerH - barH;

    bars += `
      <rect x="${x}" y="${y}" width="${barW}" height="${barH}" fill="${it.color}" rx="3" opacity="0.9">
        <title>${it.range_label} (${it.math_range})&#10;企业数量: ${it.company_count} 家&#10;占比: ${it.percentage}%</title>
      </rect>
      <text x="${x + barW * 0.5}" y="${Math.max(m.top + 10, y - 4)}" fill="#f8fafc" font-size="9" font-weight="600" text-anchor="middle" font-family="monospace">
        ${it.company_count > 0 ? it.company_count : ''}
      </text>
      <text x="${x + barW * 0.5}" y="${m.top + innerH + 16}" fill="#94a3b8" font-size="8" text-anchor="middle">
        ${it.range_label.replace(' ~ ', '-')}
      </text>
    `;
  });

  dom.top10CircChartContainer.innerHTML = `
    <svg width="100%" height="${h}" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">
      <!-- 坐标轴网格 -->
      <line x1="${m.left}" y1="${m.top + innerH}" x2="${m.left + innerW}" y2="${m.top + innerH}" stroke="#334155" stroke-width="1"/>
      <line x1="${m.left}" y1="${m.top}" x2="${m.left}" y2="${m.top + innerH}" stroke="#334155" stroke-width="1"/>
      
      <!-- 刻度线与文字 -->
      <text x="${m.left - 6}" y="${m.top + 10}" fill="#64748b" font-size="9" text-anchor="end" font-family="monospace">${maxVal}</text>
      <text x="${m.left - 6}" y="${m.top + innerH * 0.5 + 4}" fill="#64748b" font-size="9" text-anchor="end" font-family="monospace">${Math.round(maxVal / 2)}</text>
      <text x="${m.left - 6}" y="${m.top + innerH}" fill="#64748b" font-size="9" text-anchor="end" font-family="monospace">0</text>
      
      <!-- 横轴主标题 -->
      <text x="${m.left + innerW * 0.5}" y="${m.top + innerH + 34}" fill="#64748b" font-size="10" text-anchor="middle">
        前十大流通股东合计持股比例区间分布 (%)
      </text>

      <!-- 渲染柱子 -->
      ${bars}
    </svg>
  `;
}

function formatStatVal(v, unit) {
  if (v === undefined || v === null) return '--';
  if (unit === '亿元' && Math.abs(v) >= 10000) {
    return `${(v / 10000).toFixed(2)}万亿`;
  }
  return `${v}`;
}

/**
 * 绘制全市场收益率区间直方图 (纯 SVG)
 */
function renderChangeDistributionChart(buckets) {
  if (!dom.chartChangeDistContainer || !buckets) return;

  const w = 460;
  const h = 240;
  const m = { top: 20, right: 20, bottom: 40, left: 45 };
  const innerW = w - m.left - m.right;
  const innerH = h - m.top - m.bottom;

  const items = [
    { label: '< -7%', val: buckets.down_deep || 0, color: '#059669' },
    { label: '-7%~-3%', val: buckets.down_mid || 0, color: '#10b981' },
    { label: '-3%~0%', val: buckets.down_mild || 0, color: '#34d399' },
    { label: '0%', val: buckets.flat || 0, color: '#64748b' },
    { label: '0%~3%', val: buckets.up_mild || 0, color: '#f87171' },
    { label: '3%~7%', val: buckets.up_mid || 0, color: '#ef4444' },
    { label: '> 7%', val: buckets.up_high || 0, color: '#dc2626' }
  ];

  const maxVal = Math.max(...items.map(it => it.val), 50);
  const stepX = innerW / items.length;
  const barW = stepX * 0.7;

  let bars = '';
  items.forEach((it, idx) => {
    const x = m.left + idx * stepX + (stepX - barW) * 0.5;
    const barH = (it.val / maxVal) * innerH;
    const y = m.top + innerH - barH;

    bars += `
      <rect x="${x}" y="${y}" width="${barW}" height="${barH}" fill="${it.color}" rx="3" opacity="0.9"/>
      <text x="${x + barW * 0.5}" y="${Math.max(m.top + 12, y - 5)}" fill="#f8fafc" font-size="10" font-weight="600" text-anchor="middle" font-family="monospace">${it.val}</text>
      <text x="${x + barW * 0.5}" y="${m.top + innerH + 16}" fill="#94a3b8" font-size="9" text-anchor="middle">${it.label}</text>
    `;
  });

  dom.chartChangeDistContainer.innerHTML = `
    <svg width="100%" height="240" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">
      <line x1="${m.left}" y1="${m.top + innerH}" x2="${m.left + innerW}" y2="${m.top + innerH}" stroke="#334155"/>
      ${bars}
    </svg>
  `;
}

/**
 * 绘制市值梯队金字塔 (纯 SVG)
 */
function renderCapTiersPyramidChart(tiers, totalCount) {
  if (!dom.chartCapTiersContainer || !tiers) return;

  const w = 460;
  const h = 240;
  const m = { top: 20, right: 20, bottom: 20, left: 20 };
  const innerW = w - m.left - m.right;

  const tiersList = [
    { name: '超千亿核心巨头 (≥1000亿)', count: tiers.mega || 0, color: '#f59e0b', widthRatio: 0.35 },
    { name: '大型白马中坚 (300~1000亿)', count: tiers.large || 0, color: '#38bdf8', widthRatio: 0.50 },
    { name: '中盘成长骨干 (100~300亿)', count: tiers.mid || 0, color: '#818cf8', widthRatio: 0.65 },
    { name: '小盘活跃梯队 (50~100亿)', count: tiers.small || 0, color: '#c084fc', widthRatio: 0.80 },
    { name: '微盘基础层 (<50亿)', count: tiers.micro || 0, color: '#64748b', widthRatio: 0.95 }
  ];

  const rowH = 34;
  const gap = 8;
  let rows = '';

  tiersList.forEach((t, idx) => {
    const y = m.top + idx * (rowH + gap);
    const bW = innerW * t.widthRatio;
    const x = m.left + (innerW - bW) * 0.5;
    const pct = ((t.count / Math.max(1, totalCount)) * 100).toFixed(1);

    rows += `
      <rect x="${x}" y="${y}" width="${bW}" height="${rowH}" fill="${t.color}" opacity="0.25" stroke="${t.color}" stroke-width="1.2" rx="4"/>
      <text x="${m.left + innerW * 0.5}" y="${y + 21}" fill="#f8fafc" font-size="11" font-weight="600" text-anchor="middle">
        ${t.name}：<tspan fill="${t.color}">${t.count} 家</tspan> (${pct}%)
      </text>
    `;
  });

  dom.chartCapTiersContainer.innerHTML = `
    <svg width="100%" height="240" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">
      ${rows}
    </svg>
  `;
}

// ====================================================
// 全球外部宏观环境情报看板逻辑 (World Intelligence v2.0.0 - 冲击度量化与动态加总)
// ====================================================

/**
 * 加载全球外部环境情报 (硬通货大宗 + 世界大事 + [-1000, +1000]量化加总)
 */
async function loadWorldMacroIntelligence() {
  if (dom.worldCommodityGrid) {
    dom.worldCommodityGrid.innerHTML = '<div style="padding: 1.5rem; color: var(--text-muted);">正在同步全球大宗资产与外汇行情...</div>';
  }
  if (dom.worldEventsStream) {
    dom.worldEventsStream.innerHTML = '<div style="padding: 1.5rem; color: var(--text-muted);">正在连接多国官方情报中枢检索大事并计算量化得分...</div>';
  }

  const sDate = dom.worldStartDate ? dom.worldStartDate.value.trim() : '';
  const eDate = dom.worldEndDate ? dom.worldEndDate.value.trim() : '';
  let url = '/api/macro/world';
  const qList = [];
  if (sDate) qList.push(`start_date=${encodeURIComponent(sDate)}`);
  if (eDate) qList.push(`end_date=${encodeURIComponent(eDate)}`);
  if (qList.length > 0) url += '?' + qList.join('&');

  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const data = json.data || {};
    appState.worldMacroData = data;
    if (data.status === 'unavailable') {
      if(dom.worldCommodityGrid) dom.worldCommodityGrid.textContent=data.error;
      if(dom.worldEventsStream) dom.worldEventsStream.textContent=data.error;
      if(dom.worldTotalScore) dom.worldTotalScore.textContent='未获取';
      if(dom.worldSentimentLabel) dom.worldSentimentLabel.textContent='数据未接入';
      for(const key of ['worldEventsCount','statScoreLatest','statScoreMax','statScoreMin','statScoreAvg','badgeScopeDomestic','badgeScopeInternational'])if(dom[key])dom[key].textContent='未获取';
      if(dom.worldScoreChartSvgContainer)dom.worldScoreChartSvgContainer.textContent='真实宏观时序未接入';
      return;
    }

    // 渲染得分看板
    const agg = data.aggregate_score || {};
    const totalScore = agg.total_score;
    if (dom.worldTotalScore) {
      dom.worldTotalScore.textContent = totalScore == null ? '未获取' : `${totalScore >= 0 ? '+' : ''}${totalScore.toLocaleString()}`;
      dom.worldTotalScore.className = `score-number ${totalScore >= 0 ? 'price-up' : 'price-down'}`;
    }
    if (dom.worldScoreIcon) dom.worldScoreIcon.textContent = agg.sentiment_icon || '⚖️';
    if (dom.worldSentimentLabel) {
      dom.worldSentimentLabel.textContent = agg.sentiment_label || '中性平稳';
      dom.worldSentimentLabel.style.color = agg.sentiment_color || '#38bdf8';
      dom.worldSentimentLabel.style.borderColor = agg.sentiment_color || '#38bdf8';
      dom.worldSentimentLabel.style.backgroundColor = `${agg.sentiment_color || '#38bdf8'}20`;
    }
    if (dom.worldEventsCount) {
      dom.worldEventsCount.textContent = agg.event_count || (data.world_events || []).length;
    }

    renderWorldCommodities(data.commodities || []);
    // 依据当前置顶选中的国内/国际Tab，深度联动渲染时序走势图与事件流
    switchMacroScope(appState.macroScope || 'domestic');
  } catch (err) {
    console.error('加载全球外部环境情报异常:', err);
    if (dom.worldCommodityGrid) {
      dom.worldCommodityGrid.innerHTML = '<div style="padding: 1.5rem; color: var(--text-muted);">全球大宗商品连接暂时受阻，请稍后刷新</div>';
    }
    if (dom.worldEventsStream) {
      dom.worldEventsStream.innerHTML = '<div style="padding: 1.5rem; color: var(--text-muted);">世界大事情报网关响应超时</div>';
    }
  }
}

/**
 * 需求3: 渲染外部宏观对 A 股总评分历史时序走势图谱 (SVG)
 */
function renderWorldScoreTimelineChart(timeline, scopeTitle = '外部宏观') {
  if (!dom.worldScoreChartSvgContainer || !timeline) return;

  const stats = timeline.stats || {};
  if (dom.statScoreLatest) dom.statScoreLatest.textContent = `${(stats.latest_score || 0) >= 0 ? '+' : ''}${stats.latest_score || 0} 分`;
  if (dom.statScoreMax) dom.statScoreMax.textContent = `${(stats.max_score || 0) >= 0 ? '+' : ''}${stats.max_score || 0} 分`;
  if (dom.statScoreMin) dom.statScoreMin.textContent = `${stats.min_score || 0} 分`;
  if (dom.statScoreAvg) dom.statScoreAvg.textContent = `${(stats.avg_score || 0) >= 0 ? '+' : ''}${stats.avg_score || 0} 分`;

  const points = timeline.points || [];
  if (points.length === 0) {
    dom.worldScoreChartSvgContainer.innerHTML = '<div style="padding: 2rem; color: var(--text-muted);">暂无该维度时序数据</div>';
    return;
  }

  const w = 920;
  const h = 220;
  const m = { top: 25, right: 60, bottom: 30, left: 60 };
  const innerW = w - m.left - m.right;
  const innerH = h - m.top - m.bottom;

  const scores = points.map(p => p.total_score);
  const maxScoreVal = Math.max(...scores);
  const minScoreVal = Math.min(...scores);
  const maxS = Math.max(200, Math.ceil((maxScoreVal * 1.15) / 100) * 100);
  const minS = Math.min(-100, Math.floor((minScoreVal * 1.15) / 100) * 100);

  const scoreToY = (s) => m.top + ((maxS - s) / (maxS - minS)) * innerH;
  const zeroY = scoreToY(0);

  const stepX = innerW / Math.max(1, points.length - 1);

  // 构造平滑折线与区域填充
  let pathLine = '';
  let pathArea = `M ${m.left} ${zeroY}`;

  points.forEach((p, idx) => {
    const x = m.left + idx * stepX;
    const y = scoreToY(p.total_score);
    if (idx === 0) {
      pathLine = `M ${x} ${y}`;
      pathArea += ` L ${x} ${y}`;
    } else {
      pathLine += ` L ${x} ${y}`;
      pathArea += ` L ${x} ${y}`;
    }
  });
  pathArea += ` L ${m.left + (points.length - 1) * stepX} ${zeroY} Z`;

  // 关键数据点圆点
  let dots = '';
  points.forEach((p, idx) => {
    const x = m.left + idx * stepX;
    const y = scoreToY(p.total_score);
    const color = p.total_score >= 0 ? '#ef4444' : '#10b981';
    dots += `
      <circle cx="${x}" cy="${y}" r="3.5" fill="${color}" stroke="#0b1329" stroke-width="1.5">
        <title>${p.date} [${scopeTitle}] 影响评分: ${p.total_score >= 0 ? '+' : ''}${p.total_score}分&#10;核心事件: ${p.events_desc}</title>
      </circle>
    `;
  });

  const firstDate = points[0].date;
  const midDate = points[Math.floor(points.length / 2)].date;
  const lastDate = points[points.length - 1].date;

  dom.worldScoreChartSvgContainer.innerHTML = `
    <svg width="100%" height="${h}" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg" style="background-color: #0b1329; border-radius: 6px; overflow: visible;">
      <defs>
        <linearGradient id="scoreGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#ef4444" stop-opacity="0.35"/>
          <stop offset="100%" stop-color="#ef4444" stop-opacity="0.0"/>
        </linearGradient>
      </defs>

      <!-- 网格与零刻度多空分界线 -->
      <line x1="${m.left}" y1="${zeroY}" x2="${m.left + innerW}" y2="${zeroY}" stroke="#475569" stroke-width="1.2" stroke-dasharray="4,4"/>
      <text x="${m.left + 8}" y="${zeroY - 6}" fill="#94a3b8" font-size="10" font-family="monospace">⚖️ 0 分多空分界线</text>

      <!-- 走势区域填充 -->
      <path d="${pathArea}" fill="url(#scoreGrad)"/>

      <!-- 走势主折线 -->
      <path d="${pathLine}" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>

      <!-- 关键节点数据点 -->
      ${dots}

      <!-- Y轴极值标注 -->
      <text x="${m.left - 8}" y="${m.top + 5}" fill="#ef4444" font-size="10" text-anchor="end" font-family="monospace">+${maxS}分</text>
      <text x="${m.left - 8}" y="${m.top + innerH}" fill="#10b981" font-size="10" text-anchor="end" font-family="monospace">${minS}分</text>

      <!-- X轴时间标注 -->
      <text x="${m.left}" y="${h - 8}" fill="#64748b" font-size="10" text-anchor="start">${firstDate}</text>
      <text x="${m.left + innerW * 0.5}" y="${h - 8}" fill="#64748b" font-size="10" text-anchor="middle">${midDate}</text>
      <text x="${m.left + innerW}" y="${h - 8}" fill="#64748b" font-size="10" text-anchor="end">${lastDate}</text>
    </svg>
  `;
}

/**
 * 渲染全球大宗与硬通货资产卡片 (需求2: 醒目常显对 A 股的影响量化评分)
 */
function renderWorldCommodities(items) {
  if (!dom.worldCommodityGrid) return;
  dom.worldCommodityGrid.innerHTML = '';

  items.forEach(c => {
    const chg = Number(c.change || 0);
    const chgPct = Number(c.change_pct || 0);
    const chgColor = chg > 0 ? '#ef4444' : chg < 0 ? '#10b981' : '#94a3b8';
    const sign = chg > 0 ? '+' : '';

    // 需求2: A 股量化评分
    const scoreVal = Number(c.quant_score || 0);
    const scoreColor = scoreVal > 0 ? '#ef4444' : scoreVal < 0 ? '#10b981' : '#94a3b8';
    const scoreSign = scoreVal > 0 ? '+' : '';

    const card = document.createElement('div');
    card.className = 'commodity-card';
    card.innerHTML = `
      <div class="commodity-header">
        <span class="commodity-name">${escapeHtml(c.name)}</span>
        <span class="commodity-tag">${c.category}</span>
      </div>
      <div class="commodity-price-row">
        <span class="commodity-price">${c.price.toLocaleString()}</span>
        <span class="commodity-change" style="color: ${chgColor};">
          ${sign}${chgPct.toFixed(2)}% (${sign}${chg.toFixed(2)})
        </span>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.2rem;">
        <span>信号: <strong style="color: ${chgColor};">${c.signal}</strong></span>
        <span>代码: ${c.symbol}</span>
      </div>

      <!-- 需求2: 内部常显对 A 股的影响评分勋章 -->
      <div class="commodity-quant-badge" style="background-color: ${scoreColor}18; color: ${scoreColor}; border: 1px solid ${scoreColor}40;">
        🎯 A股影响: ${scoreSign}${scoreVal}分 (${c.score_badge || '传导流动性'})
      </div>

      <div class="commodity-impact">
        💡 <strong>市场影响:</strong> ${c.impact}
      </div>
    `;
    dom.worldCommodityGrid.appendChild(card);
  });
}

/**
 * 需求3: 切换国内核心部委宏观与国际外围宏观 Tab (格式塔置顶与全维度深度联动)
 */
function switchMacroScope(scope) {
  appState.macroScope = scope;
  if (dom.btnScopeDomestic) {
    dom.btnScopeDomestic.classList.toggle('active', scope === 'domestic');
  }
  if (dom.btnScopeInternational) {
    dom.btnScopeInternational.classList.toggle('active', scope === 'international');
  }

  // 显隐部委直通栏与国际大宗商品栏
  if (dom.domesticMinistriesQuickBar) {
    dom.domesticMinistriesQuickBar.style.display = (scope === 'domestic') ? 'block' : 'none';
  }
  if (dom.worldCommoditySection) {
    dom.worldCommoditySection.style.display = (scope === 'international') ? 'block' : 'none';
  }

  // 联动顶部卡片标题与说明文字
  if (dom.worldHeaderScopeTitle) {
    dom.worldHeaderScopeTitle.textContent = (scope === 'domestic')
      ? '🇨🇳 国内核心部委宏观情报全景'
      : '🌐 国际外围宏观与全球大宗情报';
  }
  if (dom.worldHeaderScopeDesc) {
    dom.worldHeaderScopeDesc.innerHTML = (scope === 'domestic')
      ? '国内宏观新闻与评分尚未接入可核验来源；下方提供来源网站入口。'
      : '国际宏观新闻、大宗行情与评分尚未接入可核验来源。';
  }
  if (dom.worldScoreCardSubLabel) {
    dom.worldScoreCardSubLabel.textContent = (scope === 'domestic')
      ? '国内核心部委对 A 股综合量化总分 (单项 -1000 ~ +1000 动态加总)'
      : '国际外围宏观对 A 股综合量化总分 (单项 -1000 ~ +1000 动态加总)';
  }

  // 重置国家过滤器
  if (scope === 'domestic') {
    appState.worldFilterCountry = 'cn';
    if (dom.worldCountryPills) {
      dom.worldCountryPills.style.display = 'none'; // 国内模式下隐去外围国家按钮
    }
  } else {
    appState.worldFilterCountry = 'all';
    if (dom.worldCountryPills) {
      dom.worldCountryPills.style.display = 'flex';
      dom.worldCountryPills.querySelectorAll('.country-pill').forEach(b => {
        b.classList.toggle('active', b.getAttribute('data-country') === 'all');
      });
    }
  }

  // 重新渲染事件流、总分卡与图2时序走势图
  const data = appState.worldMacroData || {};
  if(data.status!=='available') {
    if(dom.worldHeaderScopeDesc)dom.worldHeaderScopeDesc.textContent='尚未接入可验证宏观数据来源';
    if(dom.worldEventsStream)dom.worldEventsStream.textContent='宏观新闻未获取';
    return;
  }
  const agg = data.aggregate_score || {};
  
  if (scope === 'domestic') {
    const dScore = agg.domestic_score !== undefined ? agg.domestic_score : agg.total_score;
    if (dom.worldTotalScore) {
      dom.worldTotalScore.textContent = `${dScore >= 0 ? '+' : ''}${dScore.toLocaleString()}`;
      dom.worldTotalScore.className = `score-number ${dScore >= 0 ? 'price-up' : 'price-down'}`;
    }
    if (dom.worldEventsCount) {
      dom.worldEventsCount.textContent = agg.domestic_count || (data.domestic_events || []).length;
    }
    if (dom.badgeScopeDomestic) {
      dom.badgeScopeDomestic.textContent = `${agg.domestic_count ?? '未获取'}件政经要闻`;
    }
    if (dom.worldTimelineChartTitle) {
      dom.worldTimelineChartTitle.textContent = '🇨🇳 国内核心部委宏观对 A 股影响评分历史走势图谱';
    }

    renderWorldEvents(data.domestic_events || data.world_events || []);
    
    // 需求2: 时序走势图动态切换为纯国内部委时序
    const domTimeline = data.timeline_domestic || data.score_timeline;
    renderWorldScoreTimelineChart(domTimeline, '国内核心部委');
  } else {
    const iScore = agg.international_score !== undefined ? agg.international_score : agg.total_score;
    if (dom.worldTotalScore) {
      dom.worldTotalScore.textContent = `${iScore >= 0 ? '+' : ''}${iScore.toLocaleString()}`;
      dom.worldTotalScore.className = `score-number ${iScore >= 0 ? 'price-up' : 'price-down'}`;
    }
    if (dom.worldEventsCount) {
      dom.worldEventsCount.textContent = agg.international_count || (data.international_events || []).length;
    }
    if (dom.badgeScopeInternational) {
      dom.badgeScopeInternational.textContent = `${agg.international_count ?? '未获取'}件全球大事`;
    }
    if (dom.worldTimelineChartTitle) {
      dom.worldTimelineChartTitle.textContent = '🌐 国际外围宏观对 A 股影响评分历史走势图谱';
    }

    renderWorldEvents(data.international_events || data.world_events || []);

    // 需求2: 时序走势图动态切换为纯国际外围时序
    const intTimeline = data.timeline_international || data.score_timeline;
    renderWorldScoreTimelineChart(intTimeline, '国际外围');
  }
}

/**
 * 过滤与渲染世界大事列表
 */
function filterWorldEvents(type, val) {
  if (type === 'country') {
    appState.worldFilterCountry = val;
    document.querySelectorAll('.country-pill').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-country') === val);
    });
  } else if (type === 'domain') {
    appState.worldFilterDomain = val;
    document.querySelectorAll('.domain-pill').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-domain') === val);
    });
  }

  const data = appState.worldMacroData || {};
  let targetEvents = [];
  if (appState.macroScope === 'domestic') {
    targetEvents = data.domestic_events || (data.world_events || []).filter(e => e.scope === 'domestic');
  } else {
    targetEvents = data.international_events || (data.world_events || []).filter(e => e.scope !== 'domestic');
  }
  renderWorldEvents(targetEvents);
}

function renderWorldEvents(events) {
  if (!dom.worldEventsStream) return;
  dom.worldEventsStream.innerHTML = '';

  const country = appState.worldFilterCountry;
  const domain = appState.worldFilterDomain;

  const filtered = events.filter(e => {
    const matchC = (country === 'all' || e.country_code === country);
    const matchD = (domain === 'all' || e.domain === domain);
    return matchC && matchD;
  });

  if (filtered.length === 0) {
    dom.worldEventsStream.innerHTML = '<div style="padding: 2.5rem; text-align: center; color: var(--text-muted);">暂无符合该筛选条件的大事情报</div>';
    return;
  }

  filtered.forEach(e => {
    const card = document.createElement('div');
    card.className = 'event-card';
    const scoreVal = Number(e.quant_score || 0);
    const scoreColor = scoreVal > 0 ? '#ef4444' : scoreVal < 0 ? '#10b981' : '#94a3b8';
    const scoreSign = scoreVal > 0 ? '+' : '';
    const isDomestic = e.scope === 'domestic' || e.ministry;

    card.innerHTML = `
      <div class="event-top-line">
        <div class="event-meta-left">
          <span class="event-flag">${e.flag}</span>
          <span style="font-weight: 700; font-size: 0.88rem;">${isDomestic ? (e.ministry || e.country) : e.country}</span>
          <span class="event-domain-tag">${e.domain_icon} ${e.domain}</span>
          ${isDomestic ? `<span class="brand-tag" style="background: rgba(56, 189, 248, 0.2); color: #38bdf8; font-size: 0.7rem;">国家部委官方</span>` : ''}
          <span class="quant-tag-score" style="background-color: ${scoreColor}20; color: ${scoreColor}; border: 1px solid ${scoreColor}40;">
            A股量化冲击: ${scoreSign}${scoreVal} 分
          </span>
        </div>
        <span class="event-date">📅 发生日期: ${e.date}</span>
      </div>

      <div class="event-title">${e.title}</div>
      <div class="event-summary">${e.summary}</div>

      <div class="event-impact-box">
        🎯 <strong>政策及宏观影响深度研判:</strong> ${e.impact_analysis}<br>
        <span style="font-size: 0.76rem; color: #93c5fd;">⚡ <strong>传导归因:</strong> ${e.score_reason || '对实体产业及A股资产形成实质性驱动'}</span>
      </div>

      <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 0.2rem; flex-wrap: wrap; gap: 0.4rem;">
        <span style="font-size: 0.75rem; color: var(--text-muted);">🏛️ 官方认证信源: ${e.official_source}</span>
        <a href="${e.source_url}" target="_blank" class="event-source-link">🔗 查看官方原始通告 ↗</a>
      </div>
    `;
    dom.worldEventsStream.appendChild(card);
  });
}

// ====================================================
// 独立手动数据采集控制中心逻辑
// ====================================================

async function startManualCrawl(mode) {
  try {
    const res = await fetch('/api/crawler/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode })
    });
    const data = await res.json();
    if (data.code === 200) {
      dom.crawlerCompleteBanner.style.display = 'none';
      pollCrawlerStatus();
    } else {
      alert(data.message || '启动采集失败');
    }
  } catch (err) {
    console.error('启动手动抓取异常:', err);
    alert('无法连接到服务端爬虫调度器');
  }
}

async function cancelManualCrawl() {
  try {
    await fetch('/api/crawler/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    pollCrawlerStatus();
  } catch (err) {
    console.error('取消抓取异常:', err);
  }
}

async function pollCrawlerStatus() {
  if (appState.crawlerPollTimer) {
    clearTimeout(appState.crawlerPollTimer);
  }

  try {
    const res = await fetch('/api/crawler/status', { cache: 'no-store' });
    if (res.ok) {
      const snap = await res.json();
      updateCrawlerDashboardUI(snap);

      if (snap.is_running) {
        appState.crawlerPollTimer = setTimeout(pollCrawlerStatus, 600);
      }
    }
  } catch (err) {
    console.error('查询爬虫状态异常:', err);
  }
}

function updateCrawlerDashboardUI(snap) {
  const isRunning = snap.is_running;
  const pct = snap.progress_pct || 0.0;

  dom.btnStartFullCrawl.disabled = isRunning;
  dom.btnStartCoreCrawl.disabled = isRunning;
  dom.btnCancelCrawl.disabled = !isRunning;

  dom.crawlerProgressPct.textContent = `${pct.toFixed(1)}%`;
  dom.crawlerProgressBar.style.width = `${pct}%`;

  dom.crawlerMetricTotal.textContent = snap.total_count ? `${snap.total_count.toLocaleString()} 只` : '-- 只';
  dom.crawlerMetricUpdated.textContent = snap.updated_count !== undefined ? `${snap.updated_count.toLocaleString()} 只` : '-- 只';
  dom.crawlerMetricElapsed.textContent = `${(snap.elapsed_sec || 0).toFixed(1)} 秒`;
  dom.crawlerPhaseDesc.textContent = snap.phase_text || '待命就绪';

  if (snap.status === 'running') {
    dom.crawlerPulseDot.style.backgroundColor = '#38bdf8';
    dom.crawlerPulseDot.style.boxShadow = '0 0 10px #38bdf8';
    dom.crawlerStatusText.textContent = `🚀 正在全量分批采集入库中... (已完成 ${snap.current_count || 0}/${snap.total_count || 0})`;
    dom.crawlerCompleteBanner.style.display = 'none';
  } else if (snap.status === 'completed') {
    dom.crawlerPulseDot.style.backgroundColor = '#22c55e';
    dom.crawlerPulseDot.style.boxShadow = '0 0 10px #22c55e';
    const skipTip = snap.skipped_count ? ` (指纹幂等跳过 ${snap.skipped_count} 只)` : '';
    dom.crawlerStatusText.textContent = `✅ 数据采集已圆满完成！全部数据已沉淀入库。${skipTip}`;
    dom.crawlerCompleteBanner.style.display = 'flex';
    dom.crawlerCompleteMsg.textContent = `恭喜！已顺利完成 ${snap.updated_count || 0} 只标的最新行情采集与 SQLite 事务持久化${skipTip}，耗时 ${(snap.elapsed_sec || 0).toFixed(1)} 秒。`;
    // 采集完成后刷新抓取审计列表
    loadCrawlerAuditList();
  } else if (snap.status === 'partial') {
    dom.crawlerStatusText.textContent=`部分覆盖：已获取 ${snap.updated_count}/${snap.total_count} 只行情，缺失部分可重新采集`;
    dom.crawlerCompleteBanner.style.display='none';
  } else if (snap.status === 'cancelled') {
    dom.crawlerPulseDot.style.backgroundColor = '#ef4444';
    dom.crawlerPulseDot.style.boxShadow = 'none';
    dom.crawlerStatusText.textContent = `⏹️ 采集任务已手动取消。已更新部分保持落盘。`;
    dom.crawlerCompleteBanner.style.display = 'none';
  } else {
    dom.crawlerPulseDot.style.backgroundColor = '#94a3b8';
    dom.crawlerPulseDot.style.boxShadow = 'none';
    dom.crawlerStatusText.textContent = `就绪待命中 (未开始抓取任务)`;
  }
}

/**
 * 需求1/2: 数据中心拉取并渲染抓取审计流水列表 (展示抓取信息的ID、抓取日期、抓取状态、抓取指纹)
 */
/**
 * 需求REQ-016: 数据中心审计记录选择态 (跨刷新保留已选 ID)
 */
let auditSelection = new Set();
let auditRecordsCache = [];
let auditBaselineInfo = null;

async function loadCrawlerAuditList() {
  const tbody = document.getElementById('crawlerAuditTableBody');
  if (!tbody) return;

  try {
    const res = await fetch('/api/crawler/audit-list', { cache: 'no-store' });
    if (!res.ok) throw new Error('拉取审计记录失败');
    const json = await res.json();
    const records = json.records || [];
    auditRecordsCache = records;
    auditBaselineInfo = {
      id: json.baseline_id,
      task_id: json.baseline_task_id,
      crawl_date: json.baseline_crawl_date
    };

    // 已不存在的记录自动从选择集中剔除
    const liveIds = new Set(records.map(r => Number(r.id)));
    auditSelection = new Set([...auditSelection].filter(id => liveIds.has(id)));

    renderAuditBaselineBar();
    updateAuditSelectionUI();

    if (records.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 2rem;">
            暂无抓取审计记录，可点击上方「一键全量抓取」或「核心资产增量抓取」生成首个抓取指纹。
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = records.map(rec => {
      const isNew = (rec.status || '').includes('全新') || (rec.status || '').includes('全量');
      const isSkip = (rec.status || '').includes('免抓') || (rec.status || '').includes('一致') || (rec.status || '').includes('跳过');
      const pillCls = isNew ? 'audit-status-new' : isSkip ? 'audit-status-skip' : 'audit-status-fail';
      const statusIcon = isNew ? '✅' : isSkip ? '⚡' : '❌';
      const fpShort = rec.fingerprint || 'fp:--';
      const recId = Number(rec.id);
      const isBaseline = !!rec.is_baseline;
      const canSetBaseline = !!rec.can_set_baseline && !isBaseline;

      // 需求REQ-016/017: 基准行闭合高亮；不可设基准的记录给出明确原因而不是静默禁用
      const rowCls = [
        'audit-row',
        isBaseline ? 'is-baseline' : '',
        auditSelection.has(recId) ? 'is-selected' : ''
      ].filter(Boolean).join(' ');

      const baselineCell = isBaseline
        ? `<span class="baseline-badge" title="当前系统认定正在使用的采集批次，页面日期与筛选口径均以它为准">📌 当前基准</span>`
        : (canSetBaseline
          ? `<button type="button" class="btn btn-secondary btn-tiny" onclick="setAuditBaseline(${recId})" title="把该批次设为数据库基准，页面快照日期与筛选口径将随之切换">📌 设为基准</button>`
          : `<span class="baseline-blocked" title="仅已核验的真实行情成功批次可作为基准">🚫 不可作基准</span>`);

      return `
        <tr class="${rowCls}" data-record-id="${recId}">
          <td>
            <input type="checkbox" class="audit-checkbox audit-row-checkbox" data-record-id="${recId}"
                   ${auditSelection.has(recId) ? 'checked' : ''}
                   onclick="toggleAuditRecordSelection(${recId}, this.checked)"
                   aria-label="选择抓取记录 #${rec.task_id}">
          </td>
          <td><strong style="font-family: monospace; color: #f1f5f9; font-size: 0.9rem;">#${rec.task_id}</strong></td>
          <td style="font-family: monospace; color: #cbd5e1; font-size: 0.85rem;">${rec.crawl_date_display || rec.crawl_date}</td>
          <td>
            <span class="audit-status-pill ${pillCls}">
              ${statusIcon} ${rec.status}
            </span>
          </td>
          <td>
            <span class="fingerprint-badge" title="采集批次标识: ${fpShort}">
              fp:${fpShort}
            </span>
          </td>
          <td style="color: var(--text-secondary); font-size: 0.82rem;">
            <strong style="color: #93c5fd;">[${rec.target_scope || '全市场'}]</strong> ${rec.details || '--'}
          </td>
          <td class="audit-action-cell">${baselineCell}</td>
        </tr>
      `;
    }).join('');

    syncAuditSelectAllCheckbox();

  } catch (err) {
    console.error('加载抓取审计列表异常:', err);
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; color: var(--color-up); padding: 1.5rem;">
          获取抓取审计流水异常: ${err.message}
        </td>
      </tr>
    `;
  }
}

/** 需求REQ-017: 顶部数据基准口径条 —— 明确区分「基准批次日期」与「真实行情日期」，避免口径混淆 */
function renderAuditBaselineBar() {
  const bar = document.getElementById('dataBaselineBar');
  if (!bar) return;
  if (!auditBaselineInfo || !auditBaselineInfo.id) {
    bar.className = 'data-baseline-bar is-warning';
    bar.innerHTML = `⚠️ <strong>尚未选定数据库基准</strong>：当前无任何已核验的真实行情成功批次，页面日期口径不可用。完成一次真实抓取后会自动以最新批次为基准。`;
    return;
  }
  bar.className = 'data-baseline-bar';
  bar.innerHTML = `
    <span class="baseline-line">
      📌 <strong>当前数据库基准</strong>：批次 <code>#${auditBaselineInfo.task_id}</code>
      · 基准日期 <strong>${auditBaselineInfo.crawl_date || '未获取'}</strong>
    </span>
    <span class="baseline-hint">页面顶部「数据有效日期」与列表筛选口径均以此批次为准；每完成一次真实抓取会自动切换到最新批次，也可在下方列表手动指定。真实行情来源日期在状态栏单独显示。</span>
  `;
}

/** 需求REQ-016: 单条记录勾选 */
function toggleAuditRecordSelection(recordId, checked) {
  const id = Number(recordId);
  if (checked) auditSelection.add(id); else auditSelection.delete(id);
  const row = document.querySelector(`tr[data-record-id="${id}"]`);
  if (row) row.classList.toggle('is-selected', checked);
  updateAuditSelectionUI();
}

/** 需求REQ-016: 全选/取消全选 (含半选态) */
function toggleSelectAllAuditRecords(source) {
  const ids = auditRecordsCache.map(r => Number(r.id));
  if (source && source.checked) {
    ids.forEach(id => auditSelection.add(id));
  } else {
    auditSelection.clear();
  }
  document.querySelectorAll('.audit-row-checkbox').forEach(cb => {
    const id = Number(cb.getAttribute('data-record-id'));
    cb.checked = auditSelection.has(id);
    const row = cb.closest('tr');
    if (row) row.classList.toggle('is-selected', cb.checked);
  });
  updateAuditSelectionUI();
}

/** 需求REQ-016/018: 选择态 UI 同步 (批量操作条显隐 + 表头半选态) */
function updateAuditSelectionUI() {
  const ids = auditRecordsCache.map(r => Number(r.id));
  const selectedInView = ids.filter(id => auditSelection.has(id));
  const bar = document.getElementById('crawlerBatchBar');
  const count = document.getElementById('crawlerBatchCount');
  if (bar) bar.hidden = selectedInView.length === 0;
  if (count) count.textContent = `已选 ${selectedInView.length} 条`;
  syncAuditSelectAllCheckbox();
}

function syncAuditSelectAllCheckbox() {
  const head = document.getElementById('crawlerAuditSelectAll');
  if (!head) return;
  const ids = auditRecordsCache.map(r => Number(r.id));
  const selected = ids.filter(id => auditSelection.has(id)).length;
  head.checked = ids.length > 0 && selected === ids.length;
  // 半选态：部分选中时表头呈现 indeterminate，避免"全选/未选"的二值误读
  head.indeterminate = selected > 0 && selected < ids.length;
}

function clearAuditSelection() {
  auditSelection.clear();
  document.querySelectorAll('.audit-row-checkbox').forEach(cb => {
    cb.checked = false;
    const row = cb.closest('tr');
    if (row) row.classList.remove('is-selected');
  });
  updateAuditSelectionUI();
}

/** 需求REQ-016: 批量删除选中的抓取审计记录 (含二次确认与基准保护提示) */
async function deleteSelectedAuditRecords() {
  const ids = [...auditSelection];
  if (ids.length === 0) return;

  const protectedIds = auditRecordsCache.filter(r => ids.includes(Number(r.id)) && r.is_baseline).map(r => r.task_id);
  const confirmLines = [
    `即将删除 ${ids.length} 条抓取审计记录：`,
    ids.map(id => {
      const rec = auditRecordsCache.find(r => Number(r.id) === id);
      return rec ? `  · #${rec.task_id}（${rec.crawl_date_display || rec.crawl_date}）` : `  · ID ${id}`;
    }).join('\n'),
    '',
    '说明：删除仅作用于「抓取审计流水」，不会删除行情、K线、股东等业务数据。'
  ];
  if (protectedIds.length) {
    confirmLines.push(`注意：其中 ${protectedIds.join('、')} 为当前数据库基准，将被保护而不删除。`);
  }
  if (!window.confirm(confirmLines.join('\n'))) return;

  try {
    const res = await fetch('/api/crawler/audit-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids })
    });
    const json = await res.json();
    const deleted = json.deleted || [];
    deleted.forEach(id => auditSelection.delete(Number(id)));
    if (json.protected && json.protected.length) {
      window.alert(`已删除 ${deleted.length} 条。\n${json.protected.length} 条记录为当前数据库基准，已保护未删除，请先切换基准后重试。`);
    }
    await loadCrawlerAuditList();
  } catch (err) {
    console.error('删除抓取审计记录异常:', err);
    window.alert(`删除失败：${err.message}`);
  }
}

/** 需求REQ-017: 手动把某条抓取记录设为数据库基准 */
async function setAuditBaseline(recordId) {
  try {
    const res = await fetch('/api/crawler/baseline', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: recordId })
    });
    const json = await res.json();
    if (!json.success) {
      window.alert(`未能切换数据库基准：${json.message || '未知原因'}`);
      return;
    }
    // 需求REQ-017.6: 切换基准后必须重新拉取列表与筛选数据，禁止新旧口径混显
    await loadCrawlerAuditList();
    checkServerHealth();
    if (typeof executeFilter === 'function' && appState.currentTab === 'filter') {
      executeFilter();
    }
  } catch (err) {
    console.error('切换数据库基准异常:', err);
    window.alert(`切换数据库基准失败：${err.message}`);
  }
}

/**
 * 需求2: 独立数据采集中心数据导出功能 (JSON / CSV)
 */
function exportCrawlerData(format = 'json') {
  const url = `/api/crawler/export?format=${format}`;
  const a = document.createElement('a');
  a.href = url;
  a.download = `stock_data_export_${format}_${Date.now()}.${format}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// ====================================================
// 服务端健康检测 (带 AbortController 2.5s 超时熔断保护)
// ====================================================

function startHeartbeat() {
  checkServerHealth();
  appState.heartbeatTimer = setInterval(checkServerHealth, 3000);
}

async function checkServerHealth() {
  const startTime = performance.now();
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 2500);

  try {
    const res = await fetch('/api/status', {
      cache: 'no-store',
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    const latency = Math.round(performance.now() - startTime);

    if (res.ok) {
      const data = await res.json();
      updateServerStatusUI(data.status || 'running', latency, data);
      if (data.version && data.version !== appState.version) {
        syncVersionAndTitle(data.version);
      }
      if (data.snapshot_date) {
        updateDataValidityDateBadge(data.snapshot_date);
      }
    } else {
      updateServerStatusUI('offline');
    }
  } catch (err) {
    clearTimeout(timeoutId);
    updateServerStatusUI('offline');
  }
}

function updateServerStatusUI(status, latency = 0, serverData = null) {
  appState.serverStatus = status;

  if (status === 'running') {
    if (dom.systemCrashBanner) dom.systemCrashBanner.style.display = 'none';
    dom.serverStatusBadge.className = 'status-badge online';
    dom.serverStatusText.textContent = `服务运行中 (PID ${serverData ? serverData.pid : '--'})`;
    dom.serverPingText.textContent = `延迟: ${latency}ms`;
    if (serverData && serverData.stock_count) {
      dom.serverStockCountText.textContent = `全量标的: ${serverData.stock_count.toLocaleString()}`;
      dom.poolCountText.textContent = `(已收录主板+创业板总计: ${serverData.stock_count.toLocaleString()} 只)`;
    }
    dom.btnToggleServer.innerHTML = '🛑 暂停服务';
    dom.btnToggleServer.style.backgroundColor = 'rgba(239, 68, 68, 0.15)';
    dom.btnToggleServer.style.color = '#fca5a5';
    dom.btnToggleServer.style.borderColor = 'rgba(239, 68, 68, 0.3)';
  } else if (status === 'stopped') {
    if (dom.systemCrashBanner) dom.systemCrashBanner.style.display = 'none';
    dom.serverStatusBadge.className = 'status-badge offline';
    dom.serverStatusText.textContent = `业务已暂停 (待命)`;
    dom.serverPingText.textContent = `延迟: ${latency}ms`;
    dom.btnToggleServer.innerHTML = '🚀 启动服务';
    dom.btnToggleServer.style.backgroundColor = 'rgba(34, 197, 94, 0.2)';
    dom.btnToggleServer.style.color = '#4ade80';
    dom.btnToggleServer.style.borderColor = 'rgba(34, 197, 94, 0.4)';
  } else {
    // 出现异常/离线/崩溃：立即弹出醒目红底强反馈并提示【崩溃了 请重启试试】
    if (dom.systemCrashBanner) dom.systemCrashBanner.style.display = 'flex';
    dom.serverStatusBadge.className = 'status-badge offline';
    dom.serverStatusText.textContent = '⚠️ 崩溃了 请重启试试';
    dom.serverPingText.textContent = '延迟: 超时';
    dom.btnToggleServer.innerHTML = '🔄 崩溃了 请重启试试';
    dom.btnToggleServer.style.backgroundColor = 'rgba(239, 68, 68, 0.85)';
    dom.btnToggleServer.style.color = '#ffffff';
    dom.btnToggleServer.style.borderColor = '#ef4444';
  }
}

/**
 * 紧急一键自愈重启
 */
async function triggerEmergencyRestart() {
  if (dom.btnCrashRestart) {
    dom.btnCrashRestart.textContent = '⏳ 正在尝试唤醒重启服务...';
    dom.btnCrashRestart.disabled = true;
  }
  try {
    const res = await fetch('/api/server/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    if (res.ok) {
      setTimeout(() => {
        checkServerHealth();
        executeFilter();
        if (dom.btnCrashRestart) {
          dom.btnCrashRestart.textContent = '🔄 崩溃了 请重启试试';
          dom.btnCrashRestart.disabled = false;
        }
      }, 800);
    }
  } catch (err) {
    console.error('自愈重启异常:', err);
    setTimeout(() => {
      checkServerHealth();
      if (dom.btnCrashRestart) {
        dom.btnCrashRestart.textContent = '🔄 重启失败 请检查后台终端';
        dom.btnCrashRestart.disabled = false;
      }
    }, 1200);
  }
}

async function toggleServerState() {
  if (appState.serverStatus === 'running') {
    try {
      const res = await fetch('/api/server/shutdown', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      if (res.ok) updateServerStatusUI('stopped');
    } catch (err) {
      console.error(err);
    }
  } else {
    try {
      const res = await fetch('/api/server/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      if (res.ok) {
        updateServerStatusUI('running');
        executeFilter();
      }
    } catch (err) {
      console.error(err);
      alert('无法连接到控制中枢');
    }
  }
}

// ====================================================
// 股票详情与专业交互走势图 (日K/分时 + 成交量/成交额切换 + 图1十字光标摘要)
// ====================================================

/**
 * 需求1: 切换图表时段 Tab: timeline (分时图) ｜ kline5 (5天K线) ｜ kline10 (10天K线) ｜ kline20 (20天K线) ｜ kline60 (60天K线) ｜ all (全部/上市至今)
 */
function switchChartPeriod(period) {
  appState.chartPeriod = period;
  if (dom.klineStartDate) dom.klineStartDate.value = '';
  if (dom.klineEndDate) dom.klineEndDate.value = '';
  if (dom.chartPeriodControl) {
    dom.chartPeriodControl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-period') === period);
    });
  }

  // 针对不同 Tab 自动配置窗口
  if (period === 'kline5') {
    appState.chartZoomWindow = '5';
    appState.chartCustomZoomCount = 5;
  } else if (period === 'kline10') {
    appState.chartZoomWindow = '10';
    appState.chartCustomZoomCount = 10;
  } else if (period === 'kline20') {
    appState.chartZoomWindow = '20';
    appState.chartCustomZoomCount = 20;
  } else if (period === 'kline60') {
    appState.chartZoomWindow = '60';
    appState.chartCustomZoomCount = 60;
  } else if (period === 'kline120') {
    appState.chartZoomWindow = '120';
    appState.chartCustomZoomCount = 120;
  } else if (period === 'kline180') {
    appState.chartZoomWindow = '180';
    appState.chartCustomZoomCount = 180;
  } else if (period === 'all') {
    appState.chartZoomWindow = 'max';
    appState.chartCustomZoomCount = 0;
  }

  hideTooltip();
  // 切换周期时若开启了自动画线，自动自适应重算当前周期下的多阶中枢线
  if (appState.autoLinesCount > 0) {
    recomputeAutoLines();
  }
  renderActiveStockChart();
}

/**
 * 需求3: 应用 K 线自定义日期区间过滤
 */
function applyKlineCustomDateRange() {
  appState.chartCustomZoomCount = 0;
  hideTooltip();
  renderActiveStockChart();
}

/**
 * 需求4: 股票详情 6 大维度导航吸顶切换 (最新动态 / 公司资料 / 股东研究 / 财务分析 / 资本运作 / 分红融资)
 */
function switchDetailDimension(dimKey) {
  appState.activeDetailDimension = dimKey;
  if (dom.modalDimensionTabs) {
    dom.modalDimensionTabs.querySelectorAll('.modal-dim-tab').forEach(tab => {
      tab.classList.toggle('active', tab.getAttribute('data-dim') === dimKey);
    });
  }

  const allPanes = [
    { key: 'dynamic', el: dom.paneDynamic },
    { key: 'profile', el: dom.paneProfile },
    { key: 'shareholders', el: dom.paneShareholders },
    { key: 'finance', el: dom.paneFinance },
    { key: 'block', el: dom.paneBlock },
    { key: 'dividend', el: dom.paneDividend }
  ];

  allPanes.forEach(item => {
    if (!item.el) return;
    if (dimKey === item.key) {
      item.el.classList.remove('hidden');
    } else {
      item.el.classList.add('hidden');
    }
  });

  // 触发对应维度的异步数据拉取
  if (appState.activeDetailStock) {
    const code = appState.activeDetailStock.code;
    if (dimKey === 'block') {
      loadStockBlockTrades(code);
    }
    if (dimKey === 'dynamic') {
      loadStockEvents(code);
    }
    if (dimKey === 'dividend') {
      loadStockDividendHistory(code);
    }
  }
}

/**
 * 需求5: 加载个股上市以来现金分红历史全景
 */
async function loadStockDividendHistory(code) {
  if(!dom.finTableBodyDividend)return;
  dom.finTableBodyDividend.innerHTML='<tr><td colspan="6">正在获取真实分红披露…</td></tr>';
  try {
    const res=await fetch(`/api/stock/${encodeURIComponent(code)}/dividends`);
    if(!res.ok)throw new Error('分红披露请求失败');
    const {data}=await res.json();
    if(appState.activeDetailStock?.code!==code)return;
    dom.finTableBodyDividend.innerHTML=(data.rows||[]).map(r=>`<tr><td>${escapeHtml(r.report_period||'未提供')}</td><td>${escapeHtml(r.plan_detail||'未提供')}</td><td>来源披露</td><td>${escapeHtml(r.ex_dividend_date||'未提供')}</td><td>${escapeHtml(r.record_date||'未提供')}</td><td>${escapeHtml(r.progress||'未提供')}</td></tr>`).join('')||'<tr><td colspan="6">未获取分红披露，不能据此判断从未分红</td></tr>';
  } catch(e) {
    if(appState.activeDetailStock?.code===code)dom.finTableBodyDividend.innerHTML='<tr><td colspan="6">分红披露获取失败</td></tr>';
  }
}

/**
 * 设置日K缩放视窗控制 (60 / 250 / 750 / max)
 */
function setChartZoomWindow(windowSize) {
  appState.chartZoomWindow = windowSize;
  appState.chartCustomZoomCount = 0; // 重置滚轮动态计数
  if (dom.chartZoomControl) {
    dom.chartZoomControl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-zoom') === String(windowSize));
    });
  }
  hideTooltip();
  renderActiveStockChart();
}

/**
 * 需求1/2: 计算序列的统计概要数据 (平均值、最小值、最大值、中位数)
 * @param {Array<number>} arr 数值数组
 * @returns {{mean: number, min: number, max: number, median: number}}
 */
function calculateDistributionSummary(arr) {
  if (!arr || arr.length === 0) {
    return { mean: 0, min: 0, max: 0, median: 0 };
  }
  const valid = arr.map(v => Number(v) || 0).filter(v => !isNaN(v));
  if (valid.length === 0) {
    return { mean: 0, min: 0, max: 0, median: 0 };
  }

  // 1. 最小值与最大值
  let min = valid[0];
  let max = valid[0];
  let sum = 0;
  for (let i = 0; i < valid.length; i++) {
    const v = valid[i];
    if (v < min) min = v;
    if (v > max) max = v;
    sum += v;
  }

  // 2. 平均值
  const mean = sum / valid.length;

  // 3. 中位数 (按升序排列取中)
  const sorted = [...valid].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;

  return {
    mean: roundTo(mean, 2),
    min: roundTo(min, 2),
    max: roundTo(max, 2),
    median: roundTo(median, 2)
  };
}

// ====================================================
// 需求REQ-014/015: 图表辅助线图层模型
//   1. 多模型共存：自动多阶线 / 手动压力线 / 手动支撑线 / 缠论五类图层可同时存在，互不覆盖
//   2. 分模型清除：每个模型拥有独立清除按钮，只清自身
//   3. 重合置顶：zIndex 决定绘制顺序，点击可把目标线提升到最顶层
// ====================================================

const LINE_LAYER_ORDER = ['auto', 'manual_up', 'manual_down'];
const LINE_LAYER_META = {
  auto:        { name: '自动多阶线', icon: '🤖', base: 10, empty: '未绘制' },
  manual_up:   { name: '压力线',     icon: '🔺', base: 20, empty: '未绘制' },
  manual_down: { name: '支撑线',     icon: '🔻', base: 30, empty: '未绘制' }
};
const LINE_HIT_TOLERANCE = 6; // 命中判定容差 (SVG 坐标像素)

// 缠论五类图层元数据 (与 lineLayers 同构呈现，用于统一图层管理面板)
const CHANLUN_LAYER_META = [
  { key: 'pens', name: '缠论笔', icon: '✒️' },
  { key: 'segments', name: '线段', icon: '📐' },
  { key: 'pivots', name: '笔中枢', icon: '🔲' },
  { key: 'divergences', name: '背离', icon: '⚡' },
  { key: 'ma_entanglements', name: '均线缠绕', icon: '🌀' }
];

function ensureLineLayers() {
  if (!appState.lineLayers || typeof appState.lineLayers !== 'object') appState.lineLayers = {};
  LINE_LAYER_ORDER.forEach(key => {
    const layer = appState.lineLayers[key];
    if (!layer || !Array.isArray(layer.lines)) {
      appState.lineLayers[key] = { key, lines: [], visible: layer ? layer.visible !== false : true };
    } else if (layer.visible === undefined) {
      layer.visible = true;
    }
  });
  return appState.lineLayers;
}

function nextLineZIndex() {
  appState.lineZCounter = (appState.lineZCounter || 1000) + 1;
  return appState.lineZCounter;
}

/** 把某一图层内部的层级重排为基础区间，保持跨图层稳定顺序 */
function normalizeLayerZ(layerKey) {
  const layer = ensureLineLayers()[layerKey];
  if (!layer) return;
  const base = LINE_LAYER_META[layerKey] ? LINE_LAYER_META[layerKey].base : 50;
  layer.lines.forEach((line, idx) => { line.zIndex = base + idx; });
}

/** 需求REQ-015: 获取当前所有可见辅助线，并按 zIndex 升序返回 (数组末尾者绘制在最顶层) */
function getVisibleChartLines() {
  const layers = ensureLineLayers();
  const out = [];
  LINE_LAYER_ORDER.forEach(key => {
    const layer = layers[key];
    if (layer.visible === false) return;
    layer.lines.forEach(line => { line.layerKey = key; out.push(line); });
  });
  out.sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0));
  return out;
}

function addChartLine(layerKey, line) {
  const layers = ensureLineLayers();
  const layer = layers[layerKey];
  if (!layer) return null;
  line.layerKey = layerKey;
  line.zIndex = nextLineZIndex();
  layer.lines.push(line);
  return line;
}

function replaceLayerLines(layerKey, lines) {
  const layers = ensureLineLayers();
  const layer = layers[layerKey];
  if (!layer) return;
  layer.lines = (lines || []).map(l => ({ ...l, layerKey }));
  normalizeLayerZ(layerKey);
}

function countLayerLines(layerKey) {
  const layer = ensureLineLayers()[layerKey];
  return layer ? layer.lines.length : 0;
}

/** 需求REQ-015: 把指定辅助线提升到最顶层并高亮 */
function bringChartLineToFront(line) {
  if (!line) return;
  line.zIndex = nextLineZIndex();
  appState.topLineId = line.id;
  renderActiveStockChart();
  showChartToast(`已置顶：${line.type} ¥${Number(line.price).toFixed(2)}`);
}

/** 需求REQ-014: 只清除指定模型的辅助线，其他模型完整保留 */
function clearChartLayer(layerKey) {
  const layers = ensureLineLayers();
  const layer = layers[layerKey];
  if (!layer) return;
  layer.lines = [];
  if (layerKey === 'auto') {
    appState.autoLinesCount = 0;
    const ctrl = document.getElementById('autoLinesCountControl');
    if (ctrl) {
      ctrl.querySelectorAll('.seg-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-count') === '0');
      });
    }
  }
  renderActiveStockChart();
}

/** 需求REQ-014: 切换某个图层模型的显示/隐藏 */
function toggleChartLayerVisible(layerKey) {
  const layers = ensureLineLayers();
  const layer = layers[layerKey];
  if (!layer) return;
  layer.visible = layer.visible === false;
  renderActiveStockChart();
}

/** 计算同一图层模型内的条数摘要文案 */
function layerCountText(layerKey) {
  const meta = LINE_LAYER_META[layerKey];
  const n = countLayerLines(layerKey);
  if (!meta) return `${n} 条`;
  if (n === 0) return meta.empty;
  return `${n} 根`;
}

/** 在图表右上角浮出一句轻量反馈 (格式塔: 就近反馈，不打断操作流) */
let chartToastTimer = null;
function showChartToast(text) {
  const hosts = document.querySelectorAll('.chart-toast-host');
  if (!hosts.length) return;
  hosts.forEach(host => {
    host.textContent = text;
    host.classList.add('show');
  });
  if (chartToastTimer) clearTimeout(chartToastTimer);
  chartToastTimer = setTimeout(() => {
    hosts.forEach(host => host.classList.remove('show'));
  }, 1900);
}

/**
 * 需求REQ-014/015: 统一水平辅助线 SVG 渲染器 (个股分时图 / 个股K线图 共用同一套图层与层级规则)
 * 渲染过程中把每条线的 SVG 坐标与标签矩形回写到线对象上，供命中检测使用。
 */
function buildHorizontalLinesSVG(opts) {
  const { m, innerW, priceToY, refPrice } = opts;
  const lines = getVisibleChartLines();
  if (!lines.length) return '';

  // 1) 先标注重合关系 (图底关系: 重合线需要区分主次)
  const visibleInPlot = lines.filter(l => Number.isFinite(priceToY(l.price)));
  visibleInPlot.forEach(l => { l._svgY = priceToY(l.price); l._overlapCount = 1; });
  for (let i = 0; i < visibleInPlot.length; i++) {
    for (let j = i + 1; j < visibleInPlot.length; j++) {
      if (Math.abs(visibleInPlot[i]._svgY - visibleInPlot[j]._svgY) <= LINE_HIT_TOLERANCE) {
        visibleInPlot[i]._overlapCount++;
        visibleInPlot[j]._overlapCount++;
      }
    }
  }

  const maxZ = Math.max(...visibleInPlot.map(l => l.zIndex || 0));
  const topLine = visibleInPlot.find(l => l.id === appState.topLineId);
  const topZ = topLine ? (topLine.zIndex || 0) : maxZ;

  return visibleInPlot.map(line => {
    const yPos = line._svgY;
    const isAuto = line.layerKey === 'auto';
    const isUp = Number(line.price) >= Number(refPrice);
    const color = line.color || (isUp ? '#f43f5e' : '#10b981');
    const isTop = (line.zIndex || 0) >= topZ;
    const overlapNote = line._overlapCount > 1 ? ` ·重合${line._overlapCount}` : '';
    const topNote = isTop ? '⭐ ' : '';

    let amtText = `${line.type}: ¥${Number(line.price).toFixed(2)}`;
    let tagW = 130;
    if (line.crossedAmountYi != null) {
      const daysPart = line.crossedDays !== undefined ? `, 交易日: ${line.crossedDays}天` : '';
      amtText = `${line.type}: ¥${Number(line.price).toFixed(2)} (交汇: ${line.crossedAmountYi}亿${daysPart})`;
      tagW = line.crossedDays !== undefined ? 285 : 210;
    }
    amtText = `${topNote}${amtText}${overlapNote}`;
    tagW += (isTop ? 16 : 0) + (line._overlapCount > 1 ? 52 : 0);

    const baseWidth = isAuto ? ((line.rank === 1 || line.isMaxPeak) ? 2.2 : 1.7) : 1.6;
    const strokeWidth = isTop ? baseWidth + 0.9 : baseWidth;
    const opacity = isTop ? 1 : (line._overlapCount > 1 ? 0.55 : 0.92);

    const tagX = m.left + innerW - tagW;
    line._tagX = tagX;
    line._tagW = tagW;

    return `
      <g class="chart-hline layer-${line.layerKey}" data-line-id="${line.id}" opacity="${opacity}">
        <line x1="${m.left}" y1="${yPos}" x2="${m.left + innerW}" y2="${yPos}" stroke="${color}" stroke-width="${strokeWidth}" stroke-dasharray="${isAuto ? '6,3' : '5,3'}"/>
        <rect x="${tagX}" y="${yPos - 10}" width="${tagW}" height="20" fill="rgba(15, 23, 42, 0.95)" rx="3" stroke="${color}" stroke-width="${isTop ? 1.6 : 1}"/>
        <text x="${m.left + innerW - 6}" y="${yPos + 4}" fill="${color}" font-size="10" text-anchor="end" font-family="monospace" font-weight="${isTop ? 700 : 600}">
          ${amtText}
        </text>
      </g>
    `;
  }).join('');
}

/**
 * 需求REQ-014: 图层管理面板渲染 (格式塔: 共同区域 + 邻近性 + 相似性)
 * 每个模型一行：模型名 → 条数 → 显示开关 → 仅作用于该模型的清除按钮
 */
function renderLineLayerPanel(analysis) {
  const panel = document.getElementById('chartLayerPanel');
  if (!panel) return;
  ensureLineLayers();

  const rows = LINE_LAYER_ORDER.map(key => {
    const meta = LINE_LAYER_META[key];
    const layer = appState.lineLayers[key];
    const n = layer.lines.length;
    const visible = layer.visible !== false;
    // 需求REQ-012: 自动线因缺少真实成交额而无法测算时，必须显式说明原因，不得静默显示"未绘制"
    const blocked = (key === 'auto' && appState.autoLinesBlockedReason && appState.autoLinesCount > 0)
      ? appState.autoLinesBlockedReason : null;
    const countText = blocked ? '⚠️ 无法测算' : (n === 0 ? meta.empty : `已绘制 ${n} 根`);
    return `
      <div class="chart-layer-row ${blocked ? 'is-blocked' : ''} ${appState.topLineId && layer.lines.some(l => l.id === appState.topLineId) ? 'is-active' : ''}" data-layer="${key}">
        <span class="chart-layer-name">${meta.icon} ${meta.name}</span>
        <span class="chart-layer-count" title="${blocked ? blocked.replace(/"/g, '') : ''}">${countText}</span>
        <button type="button" class="chart-layer-btn ${visible ? 'on' : ''}" onclick="toggleChartLayerVisible('${key}')"
                title="${visible ? '隐藏' : '显示'}${meta.name}（不影响其他模型）">${visible ? '👁 显示' : '🚫 隐藏'}</button>
        <button type="button" class="chart-layer-btn danger" onclick="clearChartLayer('${key}')" ${n === 0 ? 'disabled' : ''}
                title="仅清除「${meta.name}」，其他画线模型保持不变">🧹 清除</button>
      </div>
      ${blocked ? `<p class="chart-layer-note">${blocked}（如需自动线，请切换到已提供成交额的分时周期）</p>` : ''}
    `;
  }).join('');

  const chanlunRows = CHANLUN_LAYER_META.map(item => {
    const on = appState.showChanlunDraw && appState.chanlunLayers[item.key] !== false;
    const count = analysis && analysis.counts ? analysis.counts[item.key] : null;
    const label = count === null || count === undefined ? '未获取' : (count > 0 ? `${count} 个` : '未识别');
    return `
      <div class="chart-layer-row" data-layer="chanlun-${item.key}">
        <span class="chart-layer-name">${item.icon} ${item.name}</span>
        <span class="chart-layer-count">${label}</span>
        <button type="button" class="chart-layer-btn ${on ? 'on' : ''}" onclick="toggleChanlunLayer('${item.key}')"
                title="${on ? '隐藏' : '显示'}${item.name}（不影响其他缠论图层与画线模型）">${on ? '👁 显示' : '🚫 隐藏'}</button>
        <button type="button" class="chart-layer-btn danger" onclick="clearChanlunLayer('${item.key}')"
                title="仅关闭「${item.name}」图层，其他图层保持不变">🧹 清除</button>
      </div>
    `;
  }).join('');

  const anyChanlun = CHANLUN_LAYER_META.some(i => appState.chanlunLayers[i.key] !== false);

  panel.innerHTML = `
    <div class="chart-layer-group">
      <div class="chart-layer-group-title">📏 水平辅助线模型（各模型可同时存在，清除互不影响）</div>
      ${rows}
    </div>
    <div class="chart-layer-group">
      <div class="chart-layer-group-title">
        ☯️ 缠论图层
        <button type="button" class="chart-layer-btn danger" onclick="clearAllChanlunLayers()"
                ${anyChanlun ? '' : 'disabled'} title="仅关闭全部缠论图层，不影响水平辅助线模型">🧹 清除全部缠论图层</button>
      </div>
      ${chanlunRows}
    </div>
  `;
}

/** 需求REQ-014: 切换单个缠论图层显隐 (与图层管理面板、图例复选框保持同步) */
function toggleChanlunLayer(key) {
  appState.showChanlunDraw = true;
  appState.chanlunLayers[key] = appState.chanlunLayers[key] === false;
  if (dom.btnChanlunDraw) dom.btnChanlunDraw.classList.add('active');
  renderActiveStockChart();
}

/** 需求REQ-014: 只清除指定缠论图层 */
function clearChanlunLayer(key) {
  appState.chanlunLayers[key] = false;
  renderActiveStockChart();
}

/** 需求REQ-014: 清除全部缠论图层 (不影响水平辅助线模型) */
function clearAllChanlunLayers() {
  CHANLUN_LAYER_META.forEach(i => { appState.chanlunLayers[i.key] = false; });
  renderActiveStockChart();
}

/**
 * 需求1/2: 智能自动画线算法 (支持严格求解 1~4 根辅助线)
 * 约束条件: 第 x 根辅助线交汇交易额第 x 大，且交汇交易日集合绝不能与前面已选的所有辅助线完全重复 (S_x != S_i)
 * @param {Array} klines 当前可视K线
 * @param {number} currentPrice 当前参考现价
 * @param {number} targetCount 目标画线条数 (1 ~ 4)
 * @returns {Array} 选出的多阶筹码中枢线列表
 */
function calculateAutoSupportResistanceLevels(klines, currentPrice, targetCount = 1) {
  if (!klines || klines.length === 0 || targetCount <= 0) return [];
  // Ranking by turnover requires every actual turnover; never infer it from volume × close.
  if (klines.some(k => k.amount_yi == null && k.amount == null)) return [];

  const highs = klines.map(d => Number(d.high !== undefined ? d.high : d.price));
  const lows = klines.map(d => Number(d.low !== undefined ? d.low : d.price));
  const maxP = Math.max(...highs);
  const minP = Math.min(...lows);
  if (maxP <= 0) return [];

  // 1. 构建候选价位测试池 (包含所有日高/低/收盘点，并在区间内进行密集离散采样)
  const candidatePrices = new Set();
  klines.forEach(k => {
    if (k.high !== undefined) candidatePrices.add(Number(k.high));
    if (k.low !== undefined) candidatePrices.add(Number(k.low));
    if (k.close !== undefined) candidatePrices.add(Number(k.close));
    if (k.open !== undefined) candidatePrices.add(Number(k.open));
  });

  // 在 [minP, maxP] 均匀采样 120 个步长点，确保高密度覆盖所有可能的价格交叉点
  const stepCount = 120;
  const stepVal = (maxP - minP) / (stepCount + 1);
  for (let i = 1; i <= stepCount; i++) {
    candidatePrices.add(Number((minP + i * stepVal).toFixed(2)));
  }

  // 2. 计算每个候选价格的交汇交易日集合 (二进制掩码/索引签名字符串) 与交汇总金额
  const candidatesData = [];
  const refP = Number(currentPrice) || Number(klines[klines.length - 1].close || maxP);

  candidatePrices.forEach(p => {
    let currentCrossedAmt = 0;
    const crossedDayIndices = [];

    klines.forEach((item, dayIdx) => {
      const h = Number(item.high !== undefined ? item.high : item.price);
      const l = Number(item.low !== undefined ? item.low : item.price);
      if (l <= p && p <= h) {
        crossedDayIndices.push(dayIdx);
        let amt = 0;
        if (item.amount_yi != null) {
          amt = Number(item.amount_yi);
        } else if (item.amount != null) {
          amt = Number(item.amount) / 100000000.0;

        }
        currentCrossedAmt += amt;
      }
    });

    if (crossedDayIndices.length > 0) {
      // 集合签名：如 "0,1,3,4"
      const daySetSignature = crossedDayIndices.join(',');
      candidatesData.push({
        price: Number(p.toFixed(2)),
        daySet: new Set(crossedDayIndices),
        daySignature: daySetSignature,
        crossedDays: crossedDayIndices.length,
        crossedAmountYi: Number(currentCrossedAmt.toFixed(2))
      });
    }
  });

  // 按交汇总金额降序排列
  candidatesData.sort((a, b) => b.crossedAmountYi - a.crossedAmountYi);

  // 3. 贪心求解前 targetCount 根辅助线，确保每一根的 daySignature 绝不与前面任何一根完全相等
  const selectedLevels = [];
  const chosenDaySignatures = new Set();
  const chosenPrices = new Set();

  const rankLabels = ['最强', '次强', '三阶', '四阶'];
  const rankColors = ['#f59e0b', '#38bdf8', '#c084fc', '#34d399']; // 金橙、天蓝、紫粉、翡翠绿

  for (const cand of candidatesData) {
    if (selectedLevels.length >= targetCount) break;

    // 约束1: 交易日集合不能与已选的完全重复 (S_x != S_i)
    if (chosenDaySignatures.has(cand.daySignature)) {
      continue;
    }

    // 约束2: 避免价格完全贴合 (防止相邻仅相差 0.01 的细微扰动，要求价格至少有适度区分)
    const isTooClosePrice = selectedLevels.some(l => Math.abs(l.price - cand.price) < (maxP - minP) * 0.02);
    if (isTooClosePrice && candidatesData.length > targetCount * 5) {
      continue;
    }

    // 录用该阶辅助线
    const rankIdx = selectedLevels.length;
    const isUp = cand.price >= refP;
    const typePrefix = rankLabels[rankIdx] || `${rankIdx + 1}阶`;
    const typeName = `${typePrefix}${isUp ? '压力' : '支撑'}`;

    selectedLevels.push({
      id: `cross_level_rank_${rankIdx + 1}_${Math.round(cand.price * 100)}`,
      rank: rankIdx + 1,
      price: cand.price,
      type: typeName,
      crossedDays: cand.crossedDays,
      crossedAmountYi: cand.crossedAmountYi,
      color: rankColors[rankIdx] || '#f59e0b',
      isMaxPeak: (rankIdx === 0)
    });

    chosenDaySignatures.add(cand.daySignature);
    chosenPrices.add(cand.price);
  }

  return selectedLevels;
}

/**
 * 需求2: 设置自动画线条数 (0=关, 1=1根, 2=2根, 3=3根, 4=4根)
 */
function setAutoLinesCount(count) {
  appState.autoLinesCount = parseInt(count, 10) || 0;

  // 更新 UI 分段激活
  const ctrl = document.getElementById('autoLinesCountControl');
  if (ctrl) {
    ctrl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.classList.toggle('active', parseInt(btn.getAttribute('data-count'), 10) === appState.autoLinesCount);
    });
  }

  if (appState.autoLinesCount === 0) {
    // 需求REQ-014: 仅清空「自动多阶线」模型，手动压力线/支撑线与其他模型完整保留
    ensureLineLayers().auto.lines = [];
  } else {
    recomputeAutoLines();
  }

  renderActiveStockChart();
}

/**
 * 重新计算当前个股在当前周期下的自动多阶筹码线
 */
function recomputeAutoLines() {
  appState.autoLinesBlockedReason = null;
  if (!appState.activeDetailStock || !appState.autoLinesCount) return;
  const stock = appState.activeDetailStock;

  let klines = [];
  if (appState.chartPeriod === 'timeline') {
    const tlData = stock.timeline_data || { pre_close: stock.prev_close || stock.price, items: [] };
    const items = (tlData.items && tlData.items.length > 0) ? tlData.items : [];
    if (items.length === 0) { appState.autoLinesBlockedReason = '当前无分时明细，无法测算自动线'; return; }
    klines = items.map(it => ({
      date: it.time,
      open: it.price,
      close: it.price,
      high: it.price,
      low: it.price,
      price: it.price,
      amount_yi: it.amount_yi ?? null
    }));
  } else {
    klines = (stock.daily_bars && stock.daily_bars.length > 0) ? stock.daily_bars : [];
    if (klines.length === 0) { appState.autoLinesBlockedReason = '当前周期无K线数据，无法测算自动线'; return; }

    let winCount = klines.length;
    if (appState.chartPeriod === 'kline5') winCount = Math.min(klines.length, 5);
    else if (appState.chartPeriod === 'kline10') winCount = Math.min(klines.length, 10);
    else if (appState.chartPeriod === 'kline20') winCount = Math.min(klines.length, 20);
    else if (appState.chartPeriod === 'kline60') winCount = Math.min(klines.length, 60);
    else if (appState.chartPeriod === 'kline120') winCount = Math.min(klines.length, 120);
    else if (appState.chartPeriod === 'kline180') winCount = Math.min(klines.length, 180);
    else if (appState.chartPeriod === 'all' || appState.chartZoomWindow === 'max') winCount = klines.length;
    else if (appState.chartCustomZoomCount > 0) winCount = Math.min(klines.length, Math.max(5, appState.chartCustomZoomCount));
    else winCount = parseInt(appState.chartZoomWindow, 10) || 60;

    if (klines.length > winCount) {
      klines = klines.slice(klines.length - winCount);
    }
  }

  // 需求REQ-012: 排序取第 x 大交汇成交额必须依赖完整真实成交额；来源未提供即不测算、不推造
  if (klines.some(k => k.amount_yi == null && k.amount == null)) {
    appState.autoLinesBlockedReason = '当前周期的真实来源未提供成交额，按真实数据原则不生成自动多阶线';
    ensureLineLayers().auto.lines = [];
    return;
  }

  const autoLevels = calculateAutoSupportResistanceLevels(klines, stock.price, appState.autoLinesCount);
  autoLevels.forEach(l => { l.isAuto = true; });
  if (autoLevels.length === 0) {
    appState.autoLinesBlockedReason = '当前周期内没有满足「交汇交易日集合互不重复」条件的价位，本周期不生成自动线';
  }

  // 需求REQ-014: 只替换「自动多阶线」模型，手动压力线/支撑线模型完全不受影响
  const prevTopId = appState.autoLinesCount ? appState.topLineId : null;
  replaceLayerLines('auto', autoLevels);
  if (prevTopId && !getVisibleChartLines().some(l => l.id === prevTopId)) appState.topLineId = null;
}

/**
 * 需求1: 触发自动画线 (兼容原有入口，默认画 1 根)
 */
function triggerAutoDrawLevels() {
  setAutoLinesCount(appState.autoLinesCount === 1 ? 0 : 1);
}

/**
 * 需求1: 开启/关闭画水平线 (压力/支撑位) 模式
 */
function toggleDrawHLineMode() {
  appState.drawHLineMode = !appState.drawHLineMode;
  if (dom.btnToggleHLine) {
    dom.btnToggleHLine.classList.toggle('active', appState.drawHLineMode);
    dom.btnToggleHLine.innerHTML = appState.drawHLineMode ? '✏️ 点击图表放置水平线...' : '📏 画水平线';
  }
}

/**
 * 需求4: 切换缠论自动画线与买卖点显示
 */
function toggleChanlunDraw() {
  appState.showChanlunDraw = !appState.showChanlunDraw;
  // 需求REQ-014: 重新打开缠论叠加时，若此前被逐层清除过，则恢复全部缠论图层显示
  if (appState.showChanlunDraw && CHANLUN_LAYER_META.every(i => appState.chanlunLayers[i.key] === false)) {
    CHANLUN_LAYER_META.forEach(i => { appState.chanlunLayers[i.key] = true; });
  }
  if (dom.btnChanlunDraw) {
    dom.btnChanlunDraw.classList.toggle('active', appState.showChanlunDraw);
  }
  renderActiveStockChart();
}

/**
 * 需求4: 打开缠论适用范围与实战指南弹窗
 */
function openChanlunScopeModal() {
  if (dom.chanlunScopeModal) {
    dom.chanlunScopeModal.style.display = 'flex';
  }
}

/**
 * 需求4: 关闭缠论适用范围弹窗
 */
function closeChanlunScopeModal() {
  if (dom.chanlunScopeModal) {
    dom.chanlunScopeModal.style.display = 'none';
  }
}

/**
 * 需求REQ-014: 清除全部水平辅助线模型 (仅在用户明确点击「清除全部」时使用)
 * 各模型自身的清除入口为 clearChartLayer(layerKey)，两者互不替代。
 */
function clearAllChartDrawLines() {
  const layers = ensureLineLayers();
  LINE_LAYER_ORDER.forEach(key => { layers[key].lines = []; });
  appState.autoLinesCount = 0;
  appState.drawHLineMode = false;
  appState.topLineId = null;
  if (dom.btnToggleHLine) {
    dom.btnToggleHLine.classList.remove('active');
    dom.btnToggleHLine.innerHTML = '📏 画水平线';
  }
  const ctrl = document.getElementById('autoLinesCountControl');
  if (ctrl) {
    ctrl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-count') === '0');
    });
  }
  renderActiveStockChart();
}

/**
 * 切换副图指标 Tab: vol (成交量) ｜ amt (成交额)
 */
function switchChartSubplot(subplot) {
  appState.chartSubplot = subplot;
  dom.chartSubPlotControl.querySelectorAll('.seg-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-subplot') === subplot);
  });
  hideTooltip();
  renderActiveStockChart();
}

/**
 * 切换财务分析 / 大宗交易 / 公告大事 Tab
 */
function switchFinanceTab(tabKey) {
  appState.activeFinTab = tabKey;
  document.querySelectorAll('.fin-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-fintab') === tabKey);
  });
  if (dom.finPanelMain) dom.finPanelMain.style.display = (tabKey === 'main') ? 'block' : 'none';
  if (dom.finPanelBalance) dom.finPanelBalance.style.display = (tabKey === 'balance') ? 'block' : 'none';
  if (dom.finPanelIncome) dom.finPanelIncome.style.display = (tabKey === 'income') ? 'block' : 'none';
  if (dom.finPanelCash) dom.finPanelCash.style.display = (tabKey === 'cash') ? 'block' : 'none';
  if (dom.finPanelBlock) dom.finPanelBlock.style.display = (tabKey === 'block') ? 'block' : 'none';
  if (dom.finPanelEvents) dom.finPanelEvents.style.display = (tabKey === 'events') ? 'block' : 'none';
}

/**
 * 穿透加载个股大宗交易
 */
async function loadStockBlockTrades(code) {
  if (!dom.finTableBodyBlock) return;
  dom.finTableBodyBlock.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 1.5rem;">正在从深交所/上交所官方系统稳健调取大宗交易数据...</td></tr>';
  try {
    const res = await fetch(`/api/stock/${code}/block`);
    if (!res.ok) throw new Error('拉取大宗交易失败');
    const json = await res.json();
    const trades = json.data || [];
    renderBlockTradesTable(trades);
  } catch (err) {
    dom.finTableBodyBlock.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 1.5rem;">真实大宗交易获取失败，请稍后重试</td></tr>';
  }
}

function renderBlockTradesTable(trades) {
  if (!dom.finTableBodyBlock) return;
  if (!trades || trades.length === 0) {
    dom.finTableBodyBlock.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 1.5rem;">尚未获取真实大宗交易记录，不能据此判断无交易</td></tr>';
    return;
  }
  dom.finTableBodyBlock.innerHTML = '';
  trades.forEach(t => {
    const prem = t.premium_ratio;
    const premColor = prem > 0 ? '#ef4444' : prem < 0 ? '#10b981' : '#94a3b8';
    const premSign = prem > 0 ? '+' : '';

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${t.trade_date || '--'}</td>
      <td style="font-weight: 700; color: #ffffff;">¥${formatReal(t.deal_price,2)}</td>
      <td style="font-weight: 700; color: ${premColor};">${premSign}${formatReal(prem,2)}%</td>
      <td>${formatReal(t.volume_hand,2)}</td>
      <td style="color: #38bdf8; font-weight: 600;">${formatReal(t.amount_wan,2)}</td>
      <td><span class="${t.is_buyer_org ? 'tag-badge tag-csi50' : ''}">${t.buyer || '--'}</span></td>
      <td><span class="${t.is_seller_org ? 'tag-badge tag-market-sz' : ''}">${t.seller || '--'}</span></td>
    `;
    dom.finTableBodyBlock.appendChild(tr);
  });
}

/**
 * 穿透加载个股公告与大事提醒
 */
async function loadStockEvents(code) {
  if (!dom.eventsMilestoneList || !dom.eventsNoticeList) return;
  dom.eventsMilestoneList.innerHTML = '<div style="color: var(--text-muted); padding: 1rem;">正在整理大事提醒日程...</div>';
  dom.eventsNoticeList.innerHTML = '<div style="color: var(--text-muted); padding: 1rem;">正在穿透官方公告披露源...</div>';
  try {
    const res = await fetch(`/api/stock/${code}/events`);
    if (!res.ok) throw new Error('拉取公告大事失败');
    const json = await res.json();
    const data = json.data || {};
    renderStockEventsUI(data);
  } catch (err) {
    dom.eventsMilestoneList.innerHTML = '<div style="color: var(--text-muted); padding: 1rem;">大事日程未获取</div>';
    dom.eventsNoticeList.innerHTML = '<div style="color: var(--text-muted); padding: 1rem;">公告未获取</div>';
  }
}

function renderStockEventsUI(data) {
  const milestones = data.milestones || [];
  const notices = data.notices || [];

  // 1. 渲染大事日程
  if (dom.eventsMilestoneList) {
    dom.eventsMilestoneList.innerHTML = '';
    milestones.forEach(m => {
      const item = document.createElement('div');
      item.className = 'milestone-item';
      item.innerHTML = `
        <div class="milestone-date-row">
          <span>📅 ${m.date}</span>
          <span class="tag-badge" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8;">${m.badge}</span>
        </div>
        <div class="milestone-name">${m.event}</div>
        <div class="milestone-desc">${m.desc}</div>
      `;
      dom.eventsMilestoneList.appendChild(item);
    });
  }

  // 2. 渲染官方公告列表
  if (dom.eventsNoticeList) {
    dom.eventsNoticeList.innerHTML = '';
    notices.forEach(n => {
      const row = document.createElement('div');
      row.className = 'notice-item-row';
      row.innerHTML = `
        <span class="tag-badge" style="background: ${n.tag_color}25; color: ${n.tag_color}; font-size: 0.7rem;">${n.tag}</span>
        <a href="${n.url}" target="_blank" class="notice-title-text" title="${n.title}">${n.title}</a>
        <span style="font-size: 0.75rem; color: var(--text-muted); white-space: nowrap;">${n.date}</span>
      `;
      dom.eventsNoticeList.appendChild(row);
    });
  }
}

/**
 * 需求1: 打开股票详情独立全屏页面 (Page View)
 */
async function openStockDetail(code, refresh = false) {
  const requestId = ++appState.detailRequestId;
  if (appState.detailAbortController) appState.detailAbortController.abort();
  const controller = new AbortController();
  appState.detailAbortController = controller;
  appState.activeDetailStock = null;
  appState.rawKlineData = [];
  resetAllChartLayers();
  if (!refresh) {
    if (dom.klineStartDate) dom.klineStartDate.value = '';
    if (dom.klineEndDate) dom.klineEndDate.value = '';
  }
  const historyStatus = document.getElementById('historyCoverage');
  if (historyStatus) historyStatus.textContent = '正在核验并加载该股票历史数据…';
  const pendingActionSummary = document.getElementById('stockActionSummary');
  if (pendingActionSummary) pendingActionSummary.textContent = '股东行为加载中…';
  // 1. 隐藏其他视图，展示全屏详情视图
  if (dom.viewFilterTab) dom.viewFilterTab.classList.add('hidden');
  if (dom.viewDashboardTab) dom.viewDashboardTab.classList.add('hidden');
  if (dom.viewWorldTab) dom.viewWorldTab.classList.add('hidden');
  if (dom.viewShareholdersTab) dom.viewShareholdersTab.classList.add('hidden');
  if (dom.viewCrawlerTab) dom.viewCrawlerTab.classList.add('hidden');

  if (dom.viewStockDetailTab) {
    dom.viewStockDetailTab.classList.remove('hidden');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // 默认激活第一个维度 Tab (最新动态)
  switchDetailDimension('dynamic');

  dom.modalStockName.textContent = '标的详情加载中...';
  dom.modalStockCode.textContent = code;
  dom.chartSvgContainer.innerHTML = '<div style="padding: 2.5rem; color: var(--text-muted);"><div class="spinner"></div><div>正在从官方金融网关稳健拉取行情走势、公司全景与四大财务报表...</div></div>';
  hideTooltip();

  try {
    const res = await fetch(`/api/stock/${encodeURIComponent(code)}?shareholder_days=${appState.shareholderDays || 365}${refresh ? '&refresh=1' : ''}`, { signal: controller.signal, cache: 'no-store' });
    if (!res.ok) throw new Error('获取个股详情失败');
    const json = await res.json();
    if (requestId !== appState.detailRequestId) return;
    const stock = json.data;
    if (!stock || stock.code !== code) throw new Error('返回的证券代码与请求不一致');
    if (!stock.history_meta || stock.history_meta.code !== code) {
      stock.daily_bars = [];
    }
    appState.activeDetailStock = stock;
    const meta = stock.history_meta || {};
    if (historyStatus) {
      const status = {available: '来源历史已获取完毕', partial: '历史尚未获取完整', stale: '刷新失败，当前为旧缓存', unavailable: '暂无可信数据'}[meta.status] || '请重启服务以加载新数据协议';
      historyStatus.textContent = `${stock.code} · ${meta.source || '来源未核验'} · ${meta.adjustment_label || ''} · ${meta.coverage_start || '—'} 至 ${meta.coverage_end || '—'} · ${meta.count || 0} 根 · ${status}`;
    }
    const actionSummary = document.getElementById('stockActionSummary');
    if (actionSummary) {
      const am = stock.shareholder_action_meta || {};
      actionSummary.innerHTML = `<div>已披露股东行为 · 公告日期 ${escapeActionText(am.window_start || '—')} 至 ${escapeActionText(am.window_end || '—')}</div><table><tbody><tr><th>增持股东</th>${renderActionHolderCell(stock, 'increase')}</tr><tr><th>减持股东</th>${renderActionHolderCell(stock, 'decrease')}</tr></tbody></table>`;
    }

    dom.modalStockName.textContent = stock.name;
    dom.modalStockCode.textContent = stock.code;

    dom.modalMarketTag.textContent = stock.market;
    dom.modalMarketTag.className = `tag-badge ${stock.market_code === 'sh' ? 'tag-market-sh' : 'tag-market-sz'}`;
    dom.modalBoardTag.textContent = stock.board;
    dom.modalBoardTag.className = `tag-badge ${stock.board_code === 'chinext' ? 'tag-board-chinext' : 'tag-board-main'}`;

    if (stock.is_csi50) {
      dom.modalConstituentTag.style.display = 'inline-block';
      dom.modalConstituentTag.className = 'tag-badge tag-csi50';
      dom.modalConstituentTag.textContent = '中证50成分股';
    } else if (stock.is_csi100) {
      dom.modalConstituentTag.style.display = 'inline-block';
      dom.modalConstituentTag.className = 'tag-badge tag-csi100';
      dom.modalConstituentTag.textContent = '中证100成分股';
    } else {
      dom.modalConstituentTag.style.display = 'none';
    }

    const change = stock.change;
    const changePct = stock.change_pct;
    const priceClass = change > 0 ? 'price-up' : change < 0 ? 'price-down' : 'price-flat';
    const sign = change > 0 ? '+' : '';

    const quoteSource=document.getElementById('chartDataSourceBadge');
    if(quoteSource)quoteSource.textContent=`${stock.quote_meta?.source||'来源未获取'} · ${stock.timestamp||'未获取'} · ${stock.quote_meta?.status==='stale'?'缓存，待刷新':'来源快照'}`;
    dom.modalPriceBadge.textContent = `¥${formatReal(stock.price, 2)}`;
    dom.modalPriceBadge.className = priceClass;
    dom.modalChangeBadge.textContent = change==null||changePct==null ? "未获取" : `${sign}${change.toFixed(2)} (${sign}${changePct.toFixed(2)}%)`;
    dom.modalChangeBadge.className = priceClass;

    dom.modalOpenPrice.textContent = `¥${formatReal(stock.open, 2)}`;
    dom.modalPrevClose.textContent = `¥${formatReal(stock.prev_close, 2)}`;
    dom.modalHighPrice.textContent = `¥${formatReal(stock.high, 2)}`;
    dom.modalLowPrice.textContent = `¥${formatReal(stock.low, 2)}`;
    dom.modalMarketCap.textContent = `${formatReal(stock.market_cap)} 亿`;
    dom.modalCircCap.textContent = `${formatReal(stock.circulating_cap)} 亿`;
    dom.modalPe.textContent = stock.pe ? formatReal(stock.pe, 2) : '--';

    dom.modalDividendCount.textContent = `${stock.dividend_count ?? '未获取'} 次`;
    dom.modalListingYears.textContent = `${formatReal(stock.listing_years,1)} 年`;

    dom.modalTurnoverRate.textContent = stock.turnover_rate ? `${formatReal(stock.turnover_rate, 2)}%` : '--%';
    dom.modalTurnover.textContent = `${stock.turnover_yi ? formatReal(stock.turnover_yi, 2) : '--'} 亿`;

    // 股东筹码 100% 具备且严格累加 (无 100% 异常)
    let top10HoldVal = Number(stock.top10_hold_pct || 0);
    let top10CircVal = Number(stock.top10_circ_hold_pct || 0);
    dom.modalTop10Circ.textContent = `${stock.top10_circ_hold_pct == null ? "未获取" : top10CircVal.toFixed(2)+"%"}`;
    dom.modalTop10Hold.textContent = `${stock.top10_hold_pct == null ? "未获取" : top10HoldVal.toFixed(2)+"%"}`;

    if (stock.evaluation) {
      const ev = stock.evaluation;
      dom.modalQuantScore.textContent = `量化评分: ${ev.score} 分 (${ev.grade})`;
      dom.modalQuantAction.innerHTML = `
        <strong>多空建议：</strong>${ev.action}<br>
        <strong>特征信号：</strong>${(ev.signals || []).join(' ｜ ') || '量价形态平稳，暂无极端超买超卖信号'}
      `;
    }

    // 填充公司基本资料
    const prof = stock.company_profile || {};
    dom.modalProfileIndustryTag.textContent = prof.industry || '未获取';
    dom.modalProfileScope.innerHTML = `<strong>主营业务：</strong>${escapeHtml(prof.business_scope || '未获取')}`;
    dom.modalProfileLegal.textContent = prof.legal_repr || '未获取';
    dom.modalProfileCapital.textContent = prof.reg_capital || '未获取';
    dom.modalProfileExchange.textContent = prof.listing_exchange || `${stock.market}${stock.board}`;
    dom.modalProfileAddress.textContent = prof.office_addr || '未获取';

    // 填充多颗粒度财务报表
    try {
      const finRes = await fetch(`/api/stock/${stock.code}/finance?period=${appState.activeFinGranularity || 'annual'}`, { signal: controller.signal });
      if (requestId !== appState.detailRequestId) return;
      if (finRes.ok) {
        const finJson = await finRes.json();
        if (requestId !== appState.detailRequestId) return;
        renderFinancialTables(finJson.data);
      } else {
        renderFinancialTables(stock.financial_reports || {});
      }
    } catch (_) {
      if (requestId !== appState.detailRequestId) return;
      renderFinancialTables(stock.financial_reports || {});
    }

    // 渲染走势图表
    renderActiveStockChart();

  } catch (err) {
    if (requestId !== appState.detailRequestId || err.name === 'AbortError') return;
    appState.activeDetailStock = null;
    if (historyStatus) historyStatus.textContent = `${code} · 获取失败，暂无可显示的可信历史`;
    if (pendingActionSummary) pendingActionSummary.textContent = '股东行为未获取';
    dom.modalStockName.textContent = '详情加载失败';
    console.error('加载详情失败:', err);
    dom.chartSvgContainer.innerHTML = `<div style="padding: 2rem; color: var(--color-up);">获取详情失败: ${err.message}</div>`;
  }
}

/**
 * 切换财务分析时间颗粒度 (按报告期 / 按年度 / 按单季度，严格复刻图2)
 */
async function switchFinanceGranularity(granKey) {
  appState.activeFinGranularity = granKey;
  document.querySelectorAll('.gran-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-gran') === granKey);
  });
  if (!appState.activeDetailStock) return;
  const code = appState.activeDetailStock.code;

  try {
    const res = await fetch(`/api/stock/${code}/finance?period=${granKey}`);
    if (!res.ok) return;
    const json = await res.json();
    renderFinancialTables(json.data);
  } catch (err) {
    console.error('切换财务颗粒度失败:', err);
  }
}

/**
 * 渲染财务报表多周期横向对比矩阵 (严格复刻图2表格结构与科目/年度列头)
 */
function renderFinancialTables(fin) {
  if (!fin) return;
  const cols = fin.columns || [];
  if (!cols.length) {
    ['finTableBodyMain','finTableBodyBalance','finTableBodyIncome','finTableBodyCash'].forEach(k => { if(dom[k]) dom[k].innerHTML='<tr><td>真实财报未获取</td></tr>'; });
    return;
  }
  const colTypeLabel = fin.col_type_label || '科目 \\ 年度';

  // 构建统一的表头 HTML
  const buildThead = () => `
    <tr>
      <th style="min-width: 190px;">${colTypeLabel}</th>
      ${cols.map(c => `<th>${c}</th>`).join('')}
    </tr>
  `;

  if (dom.finTheadMain) dom.finTheadMain.innerHTML = buildThead();
  if (dom.finTheadBalance) dom.finTheadBalance.innerHTML = buildThead();
  if (dom.finTheadIncome) dom.finTheadIncome.innerHTML = buildThead();
  if (dom.finTheadCash) dom.finTheadCash.innerHTML = buildThead();

  // 1. 主要指标 (带分类折叠/分组头)
  if (dom.finTableBodyMain) {
    dom.finTableBodyMain.innerHTML = '';
    let currCat = '';
    (fin.main_indicators || []).forEach(row => {
      if (row.category && row.category !== currCat) {
        currCat = row.category;
        const trCat = document.createElement('tr');
        trCat.innerHTML = `<td colspan="${cols.length + 1}" class="fin-category-header">📁 ${currCat}</td>`;
        dom.finTableBodyMain.appendChild(trCat);
      }
      const tr = document.createElement('tr');
      const vals = row.values || [];
      tr.innerHTML = `
        <td><strong>${row.item || row.name}</strong></td>
        ${vals.map((v, i) => `<td><span style="font-weight: 600; color: ${i === 0 ? '#38bdf8' : '#cbd5e1'};">${v == null ? "未提供" : escapeHtml(String(v))}</span></td>`).join('')}
      `;
      dom.finTableBodyMain.appendChild(tr);
    });
  }

  // 2. 资产负债表
  if (dom.finTableBodyBalance) {
    dom.finTableBodyBalance.innerHTML = '';
    (fin.balance_sheet || []).forEach(row => {
      const tr = document.createElement('tr');
      const vals = row.values || [];
      tr.innerHTML = `
        <td>${row.item}</td>
        ${vals.map((v, i) => `<td><span style="font-weight: 500; color: ${i === 0 ? '#f8fafc' : '#94a3b8'};">${v == null ? "未提供" : escapeHtml(String(v))}</span></td>`).join('')}
      `;
      dom.finTableBodyBalance.appendChild(tr);
    });
  }

  // 3. 利润表
  if (dom.finTableBodyIncome) {
    dom.finTableBodyIncome.innerHTML = '';
    (fin.income_statement || []).forEach(row => {
      const tr = document.createElement('tr');
      const vals = row.values || [];
      tr.innerHTML = `
        <td>${row.item}</td>
        ${vals.map((v, i) => `<td><span style="font-weight: 500; color: ${i === 0 ? '#ef4444' : '#94a3b8'};">${v == null ? "未提供" : escapeHtml(String(v))}</span></td>`).join('')}
      `;
      dom.finTableBodyIncome.appendChild(tr);
    });
  }

  // 4. 现金流量表
  if (dom.finTableBodyCash) {
    dom.finTableBodyCash.innerHTML = '';
    (fin.cash_flow_statement || []).forEach(row => {
      const tr = document.createElement('tr');
      const vals = row.values || [];
      tr.innerHTML = `
        <td>${row.item}</td>
        ${vals.map((v, i) => {
          const isPos = !String(v).startsWith('-');
          return `<td><span style="font-weight: 500; color: ${isPos ? '#4ade80' : '#f87171'};">${v == null ? "未提供" : escapeHtml(String(v))}</span></td>`;
        }).join('')}
      `;
      dom.finTableBodyCash.appendChild(tr);
    });
  }
}

/** 需求REQ-014: 切换个股时清空全部图层模型并复位层级 (仅作用于图表呈现状态，不触碰任何数据) */
function resetAllChartLayers() {
  const layers = ensureLineLayers();
  LINE_LAYER_ORDER.forEach(key => { layers[key].lines = []; layers[key].visible = true; });
  appState.lineZCounter = 1000;
  appState.topLineId = null;
  if (appState.autoLinesCount) appState.autoLinesCount = 0;
  const ctrl = document.getElementById('autoLinesCountControl');
  if (ctrl) {
    ctrl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-count') === '0');
    });
  }
}

/**
 * 核心渲染器：根据当前选中的 period 与 subplot 动态生成高保真矢量 SVG 与鼠标十字光标交互
 */
function renderActiveStockChart() {
  renderChanlunLegend(appState.activeDetailStock?.chanlun);
  const stock = appState.activeDetailStock;
  if (!stock) return;
  const dateBar = document.getElementById('klineDateRangeBar');
  if (dateBar) dateBar.style.display = appState.chartPeriod === 'timeline' ? 'none' : 'flex';

  const width = 860;
  const height = 440;
  const mainHeight = 270;
  const subHeight = 110;
  const margin = { top: 20, right: 65, bottom: 25, left: 65 };

  if (appState.chartPeriod === 'timeline') {
    const tlData = stock.timeline_data || { pre_close: stock.prev_close || stock.price, items: [] };
    let items = (tlData.items && Array.isArray(tlData.items) && tlData.items.length > 0) 
      ? tlData.items 
      : null;

    // 铁律: 严禁伪造假分时，无数据直接以文案清晰提示
    if (!items || items.length === 0) {
      dom.chartSvgContainer.innerHTML = `
        <div style="padding: 4rem 2rem; text-align: center; color: var(--text-muted);">
          <div style="font-size: 2.2rem; margin-bottom: 0.8rem;">⏱️</div>
          <div style="font-size: 1.05rem; font-weight: 700; color: #f8fafc; margin-bottom: 0.4rem;">暂无当日真实分时数据源</div>
          <div style="font-size: 0.85rem; color: var(--text-secondary);">当前处于非交易时段或官方分时未披露，系统严格遵循金融底座，绝不伪造虚假分时波动。</div>
        </div>
      `;
      hideTooltip();
      return;
    }

    const preClose = Number(tlData.pre_close || stock.prev_close || stock.price || items[0].price);

    // 需求1: 分时图不需要放大缩小时间区间，固定看全分时图 (09:30-15:00 完整全景)
    dom.chartSvgContainer.innerHTML = generateTimelineSVG(items, preClose, appState.chartSubplot, width, height, mainHeight, subHeight, margin);
    bindChartCrosshair('timeline', items, preClose, width, height, mainHeight, subHeight, margin);
    bindChartZoomAndDrawing('timeline', items, preClose, width, height, mainHeight, subHeight, margin);
  } else {
    // 需求5: 所有K线图必须源自真实数据，如果没有真实数据就提示无数据源
    let klines = (stock.daily_bars && Array.isArray(stock.daily_bars) && stock.daily_bars.length > 0) 
      ? stock.daily_bars 
      : null;

    if (!klines || klines.length === 0) {
      dom.chartSvgContainer.innerHTML = `
        <div style="padding: 4rem 2rem; text-align: center; color: var(--text-muted);">
          <div style="font-size: 2.2rem; margin-bottom: 0.8rem;">⚠️</div>
          <div style="font-size: 1.05rem; font-weight: 700; color: #f8fafc; margin-bottom: 0.4rem;">暂无官方真实 K 线数据源</div>
          <div style="font-size: 0.85rem; color: var(--text-secondary);">该标的尚未获取到公开历史日K数据，系统严格遵循金融合规底座，绝不伪造虚假走势。</div>
        </div>
      `;
      hideTooltip();
      return;
    }
    
    // 需求3: K线支持自定义时间区间筛选
    const sDate = dom.klineStartDate ? dom.klineStartDate.value : '';
    const eDate = dom.klineEndDate ? dom.klineEndDate.value : '';
    if (sDate || eDate) {
      klines = klines.filter(k => {
        if (sDate && k.date < sDate) return false;
        if (eDate && k.date > eDate) return false;
        return true;
      });
      if (klines.length === 0) {
        dom.chartSvgContainer.innerHTML = '<div style="padding:2rem">所选日期范围内没有 K 线，请调整日期。</div>';
        hideTooltip();
        return;
      }
    } else {
      // 滚轮或预设缩放 (需求2: 5天 / 10天 / 20天 / 60天 / 120天 / 180天 / 全部 走势图Tab自适应)
      let winCount = klines.length;
      if (appState.chartCustomZoomCount > 0) {
        winCount = Math.min(klines.length, Math.max(5, appState.chartCustomZoomCount));
      } else if (appState.chartPeriod === 'kline5') {
        winCount = Math.min(klines.length, 5);
      } else if (appState.chartPeriod === 'kline10') {
        winCount = Math.min(klines.length, 10);
      } else if (appState.chartPeriod === 'kline20') {
        winCount = Math.min(klines.length, 20);
      } else if (appState.chartPeriod === 'kline60') {
        winCount = Math.min(klines.length, 60);
      } else if (appState.chartPeriod === 'kline120') {
        winCount = Math.min(klines.length, 120);
      } else if (appState.chartPeriod === 'kline180') {
        winCount = Math.min(klines.length, 180);
      } else if (appState.chartPeriod === 'all' || appState.chartZoomWindow === 'max') {
        winCount = klines.length;
      } else if (appState.chartCustomZoomCount > 0) {
        winCount = Math.min(klines.length, Math.max(5, appState.chartCustomZoomCount));
      } else {
        winCount = parseInt(appState.chartZoomWindow, 10) || 60;
      }

      if (klines.length > winCount) {
        klines = klines.slice(klines.length - winCount);
      }
    }

    dom.chartSvgContainer.innerHTML = generateDailyKlineSVG(klines, appState.chartSubplot, width, height, mainHeight, subHeight, margin, stock.chanlun);
    bindChartCrosshair('daily', klines, stock.prev_close || stock.price, width, height, mainHeight, subHeight, margin);
    bindChartZoomAndDrawing('daily', klines, stock.prev_close || stock.price, width, height, mainHeight, subHeight, margin);
  }
}

/**
 * 绑定鼠标悬浮十字光标与图1浮动摘要信息卡
 */
function bindChartCrosshair(mode, dataList, preClose, w, h, mh, sh, m) {
  const svg = document.getElementById('stockInteractiveSvg');
  if (!svg || !dataList || dataList.length === 0) return;

  const innerW = w - m.left - m.right;
  const n = dataList.length;
  const stepX = innerW / Math.max(1, mode === 'timeline' ? n - 1 : n);

  const crosshairX = document.getElementById('crosshairX');
  const crosshairY = document.getElementById('crosshairY');

  svg.addEventListener('mousemove', (e) => {
    const rect = svg.getBoundingClientRect();
    const scaleX = w / rect.width;
    const scaleY = h / rect.height;
    const mouseX = (e.clientX - rect.left) * scaleX;
    const mouseY = (e.clientY - rect.top) * scaleY;

    if (mouseX < m.left || mouseX > m.left + innerW || mouseY < m.top || mouseY > m.top + mh + 25 + sh) {
      hideTooltip();
      return;
    }

    let idx = 0;
    if (mode === 'timeline') {
      idx = Math.round((mouseX - m.left) / stepX);
    } else {
      idx = Math.floor((mouseX - m.left) / stepX);
    }
    idx = Math.max(0, Math.min(n - 1, idx));

    const item = dataList[idx];
    const snapX = m.left + idx * stepX + (mode === 'daily' ? stepX * 0.5 : 0);

    // 更新十字光标线
    if (crosshairX) {
      crosshairX.setAttribute('x1', snapX);
      crosshairX.setAttribute('x2', snapX);
      crosshairX.style.display = 'block';
    }
    if (crosshairY) {
      crosshairY.setAttribute('y1', mouseY);
      crosshairY.setAttribute('y2', mouseY);
      crosshairY.style.display = 'block';
    }

    // 弹出与渲染摘要卡 (严格对应图1)
    renderTooltip(mode, item, idx > 0 ? dataList[idx - 1] : null, preClose);
  });

  svg.addEventListener('mouseleave', () => {
    hideTooltip();
  });
}

/**
 * 需求1: 绑定鼠标滚轮无级缩放与点击画水平线 (压力/支撑位) 交互
 */
function bindChartZoomAndDrawing(mode, dataList, preClose, w, h, mh, sh, m) {
  const svg = document.getElementById('stockInteractiveSvg');
  if (!svg || !dataList || dataList.length === 0) return;

  // 1. 鼠标滚轮缩放逻辑 (需求1: 仅日K线模式下启用滚轮缩放；分时图固定全景全天展示)
  svg.addEventListener('wheel', (e) => {
    if (mode === 'timeline') {
      // 需求1: 分时图不需要放大缩小时间区间，禁用滚轮缩放并放行页面正常滚动或阻止图表跳动
      return;
    }
    e.preventDefault();
    const stock = appState.activeDetailStock;
    if (!stock) return;

    const fullLen = stock.daily_bars?.length || 100;

    let curCount = appState.chartCustomZoomCount > 0 
      ? appState.chartCustomZoomCount 
      : (appState.chartZoomWindow === '5' ? 5 
        : appState.chartZoomWindow === '10' ? 10
        : appState.chartZoomWindow === '20' ? 20
        : appState.chartZoomWindow === '60' ? 60 
        : appState.chartZoomWindow === '120' ? 120
        : appState.chartZoomWindow === '180' ? 180
        : appState.chartZoomWindow === '250' ? 250 : fullLen);

    // 降低灵敏度：从原先的 12% 降到 4%，保证平滑细腻缩放
    const step = Math.max(1, Math.round(curCount * 0.04));
    if (e.deltaY < 0) {
      // 滚轮向上 -> 放大 -> 数量变少 -> 区间拉近 (最小 5 根)
      curCount = Math.max(5, curCount - step);
    } else {
      // 滚轮向下 -> 缩小 -> 数量变多 -> 区间推远
      curCount = Math.min(fullLen, curCount + step);
    }

    appState.chartCustomZoomCount = curCount;
    hideTooltip();
    renderActiveStockChart();
  }, { passive: false });

  // 2. 点击交互：绘制水平辅助线 (压力/支撑线) + 需求REQ-015 重合辅助线置顶
  svg.addEventListener('click', (e) => {
    const rect = svg.getBoundingClientRect();
    const scaleY = h / rect.height;
    const scaleX = w / rect.width;
    const mouseY = (e.clientY - rect.top) * scaleY;
    const mouseX = (e.clientX - rect.left) * scaleX;

    if (appState.drawHLineMode) {
      // 仅在主图价格区域内生效
      if (mouseY < m.top || mouseY > m.top + mh) return;
      // 依据 Y 坐标反算价格
      let priceVal = 0;
      if (mode === 'timeline') {
        const prices = dataList.map(d => d.price);
        const maxPrice = Math.max(...prices, preClose * 1.002);
        const minPrice = Math.min(...prices, preClose * 0.998);
        const diff = Math.max(Math.abs(maxPrice - preClose), Math.abs(preClose - minPrice)) * 1.05;
        const pTop = preClose + diff;
        const pBottom = preClose - diff;
        priceVal = pTop - ((mouseY - m.top) / mh) * (pTop - pBottom);
      } else {
        const highs = dataList.map(d => d.high);
        const lows = dataList.map(d => d.low);
        const pad = (Math.max(...highs) - Math.min(...lows)) * 0.08;
        const pTop = Math.max(...highs) + pad;
        const pBottom = Math.max(0.1, Math.min(...lows) - pad);
        priceVal = pTop - ((mouseY - m.top) / mh) * (pTop - pBottom);
      }

      // 需求2: 针对手动放置的辅助线，同样精准统计交汇交易日成交总额 (Low <= priceVal <= High)
      let crossedAmountYi = 0;
      let crossedDays = 0;
      dataList.forEach(item => {
        const h = Number(item.high !== undefined ? item.high : item.price);
        const l = Number(item.low !== undefined ? item.low : item.price);
        if (l <= priceVal && priceVal <= h) {
          crossedDays++;
          let amt = 0;
          if (item.amount_yi != null) {
            amt = Number(item.amount_yi);
          } else if (item.amount != null) {
            amt = Number(item.amount) / 100000000.0;

          }
          crossedAmountYi += amt;
        }
      });

      // 需求REQ-014: 手动画线按价格归属自动落到「压力线」或「支撑线」模型，两个模型独立可清除
      const isPressure = priceVal >= preClose;
      const layerKey = isPressure ? 'manual_up' : 'manual_down';
      const newLine = addChartLine(layerKey, {
        id: `${layerKey}_${Date.now()}_${Math.round(priceVal * 100)}`,
        y: mouseY,
        price: Number(priceVal.toFixed(2)),
        type: isPressure ? '压力位' : '支撑位',
        crossedDays: crossedDays,
        crossedAmountYi: dataList.some(k => k.amount_yi == null && k.amount == null) ? null : Number(crossedAmountYi.toFixed(2))
      });
      appState.topLineId = newLine ? newLine.id : null;

      renderActiveStockChart();
      showChartToast(`已加入「${LINE_LAYER_META[layerKey].name}」模型`);
      return;
    }

    // 需求REQ-015: 非绘制模式下点击辅助线 → 置顶
    handleChartLineClick(mouseX, mouseY, w, h, m, mh);
  });
}

/**
 * 需求REQ-015: 辅助线点击置顶
 * 1. 命中标签徽章 → 精准置顶该条线
 * 2. 命中线段本体：唯一命中直接置顶；多条重合（视觉上叠在一起）则轮换置顶，
 *    每次点击把当前最底层的一条提到最顶层，用户可逐条看清重合的全部辅助线。
 */
function handleChartLineClick(mouseX, mouseY, w, h, m, mh) {
  const lines = getVisibleChartLines().filter(l => Number.isFinite(l._svgY));
  if (!lines.length) return;

  // 1) 标签徽章精准命中 (命中容差与标签矩形一致)
  const tagHits = lines.filter(l =>
    l._tagX !== undefined &&
    mouseX >= l._tagX && mouseX <= l._tagX + l._tagW &&
    Math.abs(mouseY - l._svgY) <= 10
  );
  if (tagHits.length) {
    bringChartLineToFront(tagHits[tagHits.length - 1]);
    return;
  }

  // 2) 线段本体命中 (绘制区内 + 垂直距离在容差内)
  if (mouseX < m.left || mouseX > m.left + (w - m.left - m.right)) return;
  const hits = lines.filter(l => Math.abs(mouseY - l._svgY) <= LINE_HIT_TOLERANCE);
  if (!hits.length) return;

  if (hits.length === 1) {
    bringChartLineToFront(hits[0]);
    return;
  }

  // 重合多条：按 zIndex 升序取最底层一条提升到最顶层，实现轮换巡览
  hits.sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0));
  const target = hits[0];
  target.zIndex = nextLineZIndex();
  appState.topLineId = target.id;
  renderActiveStockChart();
  showChartToast(`重合 ${hits.length} 条 → 已置顶：${target.type} ¥${Number(target.price).toFixed(2)}`);
}

function hideTooltip() {
  if (dom.chartTooltipBox) {
    dom.chartTooltipBox.style.display = 'none';
  }
  const crosshairX = document.getElementById('crosshairX');
  const crosshairY = document.getElementById('crosshairY');
  if (crosshairX) crosshairX.style.display = 'none';
  if (crosshairY) crosshairY.style.display = 'none';
}

/**
 * 严格复刻图1格式渲染浮动信息栏
 */
function renderTooltip(mode, d, prevD, preClose) {
  if (!dom.chartTooltipBox || !d) return;

  dom.chartTooltipBox.style.display = 'block';

  let dateStr = '';
  let openP = 0, closeP = 0, highP = 0, lowP = 0;
  let chgPct = 0, ampPct = 0, volStr = '', amtStr = '', turnStr = '';
  const refClose = prevD ? (prevD.close || prevD.price) : preClose;

  if (mode === 'timeline') {
    dateStr = d.time || '15:00';
    openP = d.price;
    closeP = d.price;
    highP = d.price;
    lowP = d.price;
    chgPct = d.change_pct != null ? d.change_pct : (((closeP - refClose) / refClose) * 100);
    ampPct = null;
    volStr = formatVolume(d.volume);
    amtStr = formatAmountYi(d.amount_yi);
    turnStr = d.turnover_rate==null ? '未获取' : `${formatReal(d.turnover_rate,2)}%`;
  } else {
    // 日K线 (如 20260728)
    dateStr = (d.date || '—').replace(/-/g, '');
    openP = d.open;
    closeP = d.close;
    highP = d.high;
    lowP = d.low;
    chgPct = d.change_pct != null ? d.change_pct : (prevD && refClose > 0 ? (((closeP - refClose) / refClose) * 100) : null);
    ampPct = prevD && refClose > 0 ? (((highP - lowP) / refClose) * 100) : null;
    volStr = formatVolume(d.volume);
    amtStr = formatAmountYi(d.amount_yi);
    turnStr = '未提供';
  }

  // 严格图1红涨绿跌配色
  const getColor = (val, comp) => val > comp ? '#ef4444' : val < comp ? '#10b981' : '#ffffff';

  dom.ttDate.textContent = dateStr;

  dom.ttOpen.textContent = openP.toFixed(2);
  dom.ttOpen.style.color = getColor(openP, refClose);

  dom.ttClose.textContent = closeP.toFixed(2);
  dom.ttClose.style.color = getColor(closeP, refClose);

  dom.ttHigh.textContent = highP.toFixed(2);
  dom.ttHigh.style.color = getColor(highP, refClose);

  dom.ttLow.textContent = lowP.toFixed(2);
  dom.ttLow.style.color = getColor(lowP, refClose);

  const sign = chgPct > 0 ? '+' : '';
  dom.ttChangePct.textContent = chgPct === null ? '未提供' : `${sign}${chgPct.toFixed(2)}%`;
  dom.ttChangePct.style.color = chgPct > 0 ? '#ef4444' : chgPct < 0 ? '#10b981' : '#ffffff';

  dom.ttAmplitude.textContent = ampPct === null ? '未提供' : `${ampPct.toFixed(2)}`;
  dom.ttVolume.textContent = volStr;
  dom.ttAmount.textContent = amtStr;
  dom.ttTurnover.textContent = turnStr;
}

function formatVolume(vol) {
  if (!vol || vol <= 0) return '0手';
  if (vol >= 10000) {
    return `${(vol / 10000).toFixed(2)}万`;
  }
  return `${Math.round(vol)}`;
}

function formatAmountYi(amtYi) {
  if (amtYi === null || amtYi === undefined) return '未提供';
  if (!amtYi || amtYi <= 0) return '0.00亿';
  if (amtYi < 0.01) {
    return `${(amtYi * 10000).toFixed(2)}万`;
  }
  return `${amtYi.toFixed(2)}亿`;
}

/**
 * 分时走势矢量 SVG 发生器
 */
function generateTimelineSVG(items, preClose, subplotType, w, h, mh, sh, m) {
  if (!items || items.length === 0) {
    return '<div style="padding: 2rem; color: var(--text-muted);">暂无分时明细</div>';
  }

  const prices = items.map(d => d.price);
  const maxPrice = Math.max(...prices, preClose * 1.002);
  const minPrice = Math.min(...prices, preClose * 0.998);
  const diff = Math.max(Math.abs(maxPrice - preClose), Math.abs(preClose - minPrice)) * 1.05;
  const pTop = roundTo(preClose + diff, 2);
  const pBottom = roundTo(preClose - diff, 2);

  const innerW = w - m.left - m.right;
  const stepX = innerW / Math.max(1, items.length - 1);

  const priceToY = (p) => m.top + ((pTop - p) / (pTop - pBottom)) * mh;
  const preCloseY = priceToY(preClose);

  let pathPrice = '';
  let pathAvg = '';
  let pathArea = `M ${m.left} ${priceToY(items[0].price)}`;

  items.forEach((d, idx) => {
    const x = m.left + idx * stepX;
    const yP = priceToY(d.price);
    const yA = priceToY(d.avg_price || d.price);
    if (idx === 0) {
      pathPrice = `M ${x} ${yP}`;
      pathAvg = `M ${x} ${yA}`;
    } else {
      pathPrice += ` L ${x} ${yP}`;
      pathAvg += ` L ${x} ${yA}`;
    }
    if (items.some(d => d.avg_price == null)) pathAvg = '';
  pathArea += ` L ${x} ${yP}`;
  });
  pathArea += ` L ${m.left + (items.length - 1) * stepX} ${m.top + mh} L ${m.left} ${m.top + mh} Z`;

  const subTopY = m.top + mh + 25;
  const isVol = (subplotType === 'vol');
  const subVals = items.map(d => isVol ? d.volume : d.amount_yi);
  const maxSubVal = Math.max(...subVals, 0.1) * 1.1;
  const subValToH = (v) => (v / maxSubVal) * (sh - 10);

  // 需求3: 分时图副图全面呈现 平均、最小、最大、中位数 概要数据
  const timelineStats = calculateDistributionSummary(subVals);
  let timelineSummarySvg = '';
  if (isVol) {
    const fmtVol = (val) => {
      if (val >= 100000000) return (val / 100000000).toFixed(2) + '亿手';
      if (val >= 10000) return (val / 10000).toFixed(1) + '万手';
      return Math.round(val) + '手';
    };
    timelineSummarySvg = `
      <g class="sub-summary-group">
        <text x="${m.left + 115}" y="${subTopY + 14}" fill="#38bdf8" font-size="10" font-family="monospace">
          <tspan fill="#94a3b8">平均:</tspan> <tspan font-weight="700" fill="#38bdf8">${fmtVol(timelineStats.mean)}</tspan>
          <tspan dx="10" fill="#94a3b8">地量(最小):</tspan> <tspan font-weight="700" fill="#10b981">${fmtVol(timelineStats.min)}</tspan>
          <tspan dx="10" fill="#94a3b8">天量(最大):</tspan> <tspan font-weight="700" fill="#ef4444">${fmtVol(timelineStats.max)}</tspan>
          <tspan dx="10" fill="#94a3b8">中位数:</tspan> <tspan font-weight="700" fill="#facc15">${fmtVol(timelineStats.median)}</tspan>
        </text>
      </g>
    `;
  } else {
    timelineSummarySvg = `
      <g class="sub-summary-group">
        <text x="${m.left + 115}" y="${subTopY + 14}" fill="#f59e0b" font-size="10" font-family="monospace">
          <tspan fill="#94a3b8">平均:</tspan> <tspan font-weight="700" fill="#f59e0b">${timelineStats.mean.toFixed(2)}亿</tspan>
          <tspan dx="10" fill="#94a3b8">地量(最小):</tspan> <tspan font-weight="700" fill="#10b981">${timelineStats.min.toFixed(2)}亿</tspan>
          <tspan dx="10" fill="#94a3b8">天量(最大):</tspan> <tspan font-weight="700" fill="#ef4444">${timelineStats.max.toFixed(2)}亿</tspan>
          <tspan dx="10" fill="#94a3b8">中位数:</tspan> <tspan font-weight="700" fill="#facc15">${timelineStats.median.toFixed(2)}亿</tspan>
        </text>
      </g>
    `;
  }

  if(subVals.some(v=>v==null)) timelineSummarySvg = `<text x="${m.left + 110}" y="${subTopY + 14}" fill="#94a3b8" font-size="12">当前来源未提供完整量额</text>`;
  let subBars = '';
  items.forEach((d, idx) => {
    const x = m.left + idx * stepX;
    const v = isVol ? d.volume : d.amount_yi;
    if(v==null)return;
    const bH = Math.max(0, subValToH(v));
    const bY = subTopY + sh - bH;
    const color = (d.price >= preClose) ? '#ef4444' : '#10b981';
    subBars += `<rect x="${x - 1.5}" y="${bY}" width="3" height="${bH}" fill="${color}" opacity="0.85"/>`;
  });

  const pctTop = (((pTop - preClose) / preClose) * 100).toFixed(2);
  const pctBottom = (((pBottom - preClose) / preClose) * 100).toFixed(2);
  const subUnit = isVol ? '手' : '亿元';
  const subTitle = isVol ? '副图：成交量 (手)' : '副图：成交额 (亿元)';

  return `
    <svg id="stockInteractiveSvg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg" style="background-color: #0b1329; border-radius: 8px; cursor: crosshair;">
      <defs>
        <linearGradient id="tlGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.0"/>
        </linearGradient>
      </defs>

      <!-- 主图网格背景 -->
      <rect x="${m.left}" y="${m.top}" width="${innerW}" height="${mh}" fill="#0f172a" stroke="#1e293b"/>
      
      <!-- 昨收盘基准线 (中轴虚线) -->
      <line x1="${m.left}" y1="${preCloseY}" x2="${m.left + innerW}" y2="${preCloseY}" stroke="#475569" stroke-dasharray="4,4"/>

      <!-- 需求4: 11:30 早盘与午盘专属垂直虚线隔离中枢 -->
      <line x1="${m.left + innerW * 0.5}" y1="${m.top}" x2="${m.left + innerW * 0.5}" y2="${m.top + mh}" stroke="#64748b" stroke-dasharray="4,4" stroke-width="1.5" opacity="0.8"/>
      <line x1="${m.left + innerW * 0.5}" y1="${subTopY}" x2="${m.left + innerW * 0.5}" y2="${subTopY + sh}" stroke="#64748b" stroke-dasharray="4,4" stroke-width="1.5" opacity="0.8"/>
      <rect x="${m.left + innerW * 0.5 - 45}" y="${m.top + 4}" width="90" height="18" fill="rgba(15, 23, 42, 0.85)" rx="3" stroke="#334155"/>
      <text x="${m.left + innerW * 0.5}" y="${m.top + 16}" fill="#94a3b8" font-size="10" text-anchor="middle" font-weight="bold">11:30 早午盘 13:00</text>

      <!-- 分时面积与走势曲线 -->
      <path d="${pathArea}" fill="url(#tlGrad)"/>
      <path d="${pathAvg}" fill="none" stroke="#facc15" stroke-width="1.2" opacity="0.9"/>
      <path d="${pathPrice}" fill="none" stroke="#38bdf8" stroke-width="1.8"/>

      <!-- 十字光标虚线 -->
      <line id="crosshairX" x1="0" y1="${m.top}" x2="0" y2="${subTopY + sh}" stroke="#94a3b8" stroke-width="1" stroke-dasharray="3,3" style="display:none;"/>
      <line id="crosshairY" x1="${m.left}" y1="0" x2="${m.left + innerW}" y2="0" stroke="#94a3b8" stroke-width="1" stroke-dasharray="3,3" style="display:none;"/>

      <!-- 主图 Y 轴坐标文字 -->
      <text x="${m.left - 8}" y="${m.top + 12}" fill="#ef4444" font-size="11" text-anchor="end" font-family="monospace">¥${pTop}</text>
      <text x="${m.left + innerW + 8}" y="${m.top + 12}" fill="#ef4444" font-size="11" text-anchor="start" font-family="monospace">+${pctTop}%</text>

      <text x="${m.left - 8}" y="${preCloseY + 4}" fill="#94a3b8" font-size="11" text-anchor="end" font-family="monospace">¥${preClose.toFixed(2)}</text>
      <text x="${m.left + innerW + 8}" y="${preCloseY + 4}" fill="#94a3b8" font-size="11" text-anchor="start" font-family="monospace">0.00%</text>

      <text x="${m.left - 8}" y="${m.top + mh}" fill="#10b981" font-size="11" text-anchor="end" font-family="monospace">¥${pBottom}</text>
      <text x="${m.left + innerW + 8}" y="${m.top + mh}" fill="#10b981" font-size="11" text-anchor="start" font-family="monospace">${pctBottom}%</text>

      <!-- 主图时间横轴坐标 -->
      <text x="${m.left}" y="${m.top + mh + 14}" fill="#64748b" font-size="10" text-anchor="start">09:30</text>
      <text x="${m.left + innerW * 0.5}" y="${m.top + mh + 14}" fill="#64748b" font-size="10" text-anchor="middle">11:30 / 13:00</text>
      <text x="${m.left + innerW}" y="${m.top + mh + 14}" fill="#64748b" font-size="10" text-anchor="end">15:00</text>

      <!-- 需求REQ-014/015: 统一渲染多模型辅助线（自动多阶线/手动压力线/手动支撑线可同时存在，按 zIndex 决定层级） -->
      ${buildHorizontalLinesSVG({
        m: m,
        innerW: innerW,
        priceToY: (p) => m.top + ((pTop - p) / (pTop - pBottom)) * mh,
        refPrice: preClose
      })}

      <!-- 副图量额区域 -->
      <rect x="${m.left}" y="${subTopY}" width="${innerW}" height="${sh}" fill="#0f172a" stroke="#1e293b"/>
      <text x="${m.left + 8}" y="${subTopY + 14}" fill="#94a3b8" font-size="10" font-weight="600">${subTitle}</text>
      ${timelineSummarySvg}
      <text x="${m.left - 8}" y="${subTopY + 14}" fill="#64748b" font-size="10" text-anchor="end" font-family="monospace">${maxSubVal.toFixed(1)}${subUnit}</text>
      
      <!-- 渲染副图柱状图 -->
      ${subBars}
    </svg>
  `;
}

/**
 * 需求4: 缠论形态学量化引擎 (包含关系处理、顶底分型、画笔划分与三类买卖点标记)
 * 严格遵循 [REQ-007] 标准规范
 * @param {Array} klines 当前可视K线序列
 * @param {Function} getX 坐标映射函数
 * @param {Function} getY 价格Y坐标映射函数
 * @returns {string} SVG 片段包含缠论笔与买卖点标记徽章
 */
function generateChanlunOverlaySVG(klines, getX, getY, analysis) {
  if (!analysis || !klines.length) return '';
  const idx = new Map(klines.map((b,i) => [b.date,i]));
  const first=klines[0].date, last=klines[klines.length-1].date;
  const globalIdx = new Map((analysis.dates||klines.map(b=>b.date)).map((d,i)=>[d,i]));
  const offset = globalIdx.get(first)||0;
  const x = t => getX(globalIdx.get(t)-offset);
  const visible = r => r.end_time>=first && r.start_time<=last;
  const colors={pens:'#c084fc',segments:'#38bdf8',pivots:'#f59e0b',divergences:'#fb7185',ma_entanglements:'#34d399'};
  let svg='';
  for(const key of ['pivots','ma_entanglements']) {
    if(appState.chanlunLayers[key]===false) continue;
    for(const r of (analysis[key]||[]).filter(visible)) {
      const left=Math.max(x(first),x(r.start_time)),right=Math.min(x(last),x(r.end_time));
      const top=getY(key==='pivots'?r.zg:r.high),bottom=getY(key==='pivots'?r.zd:r.low);
      svg+=`<g class="chanlun-${key}" data-status="${r.status}"><rect x="${left}" y="${top}" width="${Math.max(1,right-left)}" height="${Math.max(1,bottom-top)}" fill="${colors[key]}" fill-opacity="0.10" stroke="${colors[key]}" stroke-dasharray="${r.status==='confirmed'?'none':'5,3'}"/><text x="${left+3}" y="${top+12}" fill="${colors[key]}" font-size="10">${key==='pivots'?'笔中枢':'均线缠绕'}</text><title>${r.start_time} 至 ${r.end_time} · ${r.status==='confirmed'?'已确认':'待确认'}</title></g>`;
    }
  }
  for(const key of ['pens','segments']) {
    if(appState.chanlunLayers[key]===false)continue;
    for(const r of (analysis[key]||[]).filter(visible)) {
      svg+=`<line class="chanlun-${key}" x1="${x(r.start_time)}" y1="${getY(r.start_price)}" x2="${x(r.end_time)}" y2="${getY(r.end_price)}" stroke="${colors[key]}" stroke-width="${key==='pens'?1.5:3}" stroke-dasharray="${r.status==='confirmed'?'none':'6,4'}"><title>${key==='pens'?'笔':'线段'} · ${r.status==='confirmed'?'已确认':'待确认'} · ${r.start_time} 至 ${r.end_time}</title></line>`;
    }
  }
  if(appState.chanlunLayers.divergences!==false) for(const r of analysis.divergences||[]) {
    if(!idx.has(r.time))continue;
    svg+=`<g class="chanlun-divergences"><circle cx="${x(r.time)}" cy="${getY(r.price)}" r="5" fill="${colors.divergences}"/><text x="${x(r.time)+6}" y="${getY(r.price)-8}" fill="${colors.divergences}" font-size="11">${r.kind}${r.status==='provisional'?'?':''}</text><title>MACD面积 ${r.previous_area.toFixed(2)} → ${r.current_area.toFixed(2)}</title></g>`;
  }
  const maColors=['#fbbf24','#fb7185','#60a5fa'];
  if(appState.chanlunLayers.ma_entanglements!==false) (analysis.parameters?.ma_periods||[]).forEach((period,j)=>{
    const byDate=globalIdx;
    const points=klines.map((b,i)=>{const v=analysis.ma?.[String(period)]?.[byDate.get(b.date)];return v==null?null:`${getX(i)},${getY(v)}`;}).filter(Boolean);
    if(points.length)svg+=`<polyline class="chanlun-ma" points="${points.join(' ')}" fill="none" stroke="${maColors[j%3]}" stroke-width="1"><title>MA${period}</title></polyline>`;
  });
  return `<g class="chanlun-overlay-layer">${svg}</g>`;
}

function renderChanlunLegend(analysis) {
  // 需求REQ-014: 原独立图例已并入统一的「图层管理面板」，此处仅驱动面板刷新，避免重复的并列控制区
  const legacy = document.getElementById('chanlunLegend');
  if (legacy) { legacy.hidden = true; legacy.innerHTML = ''; }
  renderLineLayerPanel(analysis);
}

/**
 * 60日 K线矢量 SVG 发生器
 */
function generateDailyKlineSVG(klines, subplotType, w, h, mh, sh, m, analysis=null) {
  if (!klines || klines.length === 0) {
    return '<div style="padding: 2rem; color: var(--text-muted);">暂无K线数据</div>';
  }

  const innerW = w - m.left - m.right;
  const n = klines.length;
  const stepX = innerW / n;
  // 需求6: 上市至今长周期多达数千根K线，自适应缩小柱宽与最小宽度
  const barW = Math.max(0.5, Math.min(14, stepX * 0.7));

  const highs = klines.map(d => d.high);
  const lows = klines.map(d => d.low);
  const maxPrice = Math.max(...highs);
  const minPrice = Math.min(...lows);
  const pad = Math.max((maxPrice - minPrice) * 0.08, maxPrice * 0.001, 0.01);
  const pTop = maxPrice + pad;
  const pBottom = Math.max(0.1, minPrice - pad);

  const priceToY = (p) => m.top + ((pTop - p) / (pTop - pBottom)) * mh;

  const subTopY = m.top + mh + 25;
  const isVol = (subplotType === 'vol');
  const subVals = klines.map(d => isVol ? d.volume : d.amount_yi);
  const missingAmount = !isVol && subVals.some(v => v === null || v === undefined);
  const maxSubVal = Math.max(...subVals, 0.1) * 1.1;
  const subValToH = (v) => (v / maxSubVal) * (sh - 10);

  // 需求1/2: 统计当前可视K线窗口内副图的四维分布概要 (平均、最小、最大、中位数)
  const subStats = calculateDistributionSummary(subVals);
  let summaryBadgesSvg = '';
  if (isVol) {
    // 交易量四维分布概要 (万手折算或手)
    const fmtVol = (val) => {
      if (val >= 100000000) return (val / 100000000).toFixed(2) + '亿手';
      if (val >= 10000) return (val / 10000).toFixed(1) + '万手';
      return Math.round(val) + '手';
    };
    summaryBadgesSvg = `
      <g class="sub-summary-group">
        <text x="${m.left + 115}" y="${subTopY + 14}" fill="#38bdf8" font-size="10" font-family="monospace">
          <tspan fill="#94a3b8">平均:</tspan> <tspan font-weight="700" fill="#38bdf8">${fmtVol(subStats.mean)}</tspan>
          <tspan dx="10" fill="#94a3b8">地量(最小):</tspan> <tspan font-weight="700" fill="#10b981">${fmtVol(subStats.min)}</tspan>
          <tspan dx="10" fill="#94a3b8">天量(最大):</tspan> <tspan font-weight="700" fill="#ef4444">${fmtVol(subStats.max)}</tspan>
          <tspan dx="10" fill="#94a3b8">中位数:</tspan> <tspan font-weight="700" fill="#facc15">${fmtVol(subStats.median)}</tspan>
        </text>
      </g>
    `;
  } else {
    // 交易额四维分布概要 (单位: 亿)
    summaryBadgesSvg = `
      <g class="sub-summary-group">
        <text x="${m.left + 115}" y="${subTopY + 14}" fill="#f59e0b" font-size="10" font-family="monospace">
          <tspan fill="#94a3b8">平均:</tspan> <tspan font-weight="700" fill="#f59e0b">${subStats.mean.toFixed(2)}亿</tspan>
          <tspan dx="10" fill="#94a3b8">地量(最小):</tspan> <tspan font-weight="700" fill="#10b981">${subStats.min.toFixed(2)}亿</tspan>
          <tspan dx="10" fill="#94a3b8">天量(最大):</tspan> <tspan font-weight="700" fill="#ef4444">${subStats.max.toFixed(2)}亿</tspan>
          <tspan dx="10" fill="#94a3b8">中位数:</tspan> <tspan font-weight="700" fill="#facc15">${subStats.median.toFixed(2)}亿</tspan>
        </text>
      </g>
    `;
  }

  if (missingAmount) summaryBadgesSvg = `<text x="${m.left + 100}" y="${subTopY + 14}" fill="#94a3b8" font-size="12">当前来源未提供完整成交额</text>`;

  let candles = '';
  let subBars = '';
  let ma5Path = '';
  let ma10Path = '';

  klines.forEach((d, idx) => {
    const xMid = m.left + idx * stepX + stepX * 0.5;
    const yO = priceToY(d.open);
    const yC = priceToY(d.close);
    const yH = priceToY(d.high);
    const yL = priceToY(d.low);

    const isUp = d.close >= d.open;
    const color = isUp ? '#ef4444' : '#10b981';

    // 影线 (当K线极密集时自适应变细)
    const wickWidth = barW < 1.5 ? 0.6 : 1.2;
    candles += `<line x1="${xMid}" y1="${yH}" x2="${xMid}" y2="${yL}" stroke="${color}" stroke-width="${wickWidth}"/>`;

    // 实体蜡烛
    const bTop = Math.min(yO, yC);
    const bH = Math.max(1.0, Math.abs(yO - yC));
    candles += `<rect x="${xMid - barW * 0.5}" y="${bTop}" width="${barW}" height="${bH}" fill="${color}"/>`;

    // 副图柱子
    const val = isVol ? d.volume : d.amount_yi;
    const sH = Math.max(1.0, subValToH(val));
    const sY = subTopY + sh - sH;
    if (!missingAmount) subBars += `<rect x="${xMid - barW * 0.5}" y="${sY}" width="${barW}" height="${sH}" fill="${color}" opacity="0.85"/>`;

    // 均线计算
    if (idx >= 4) {
      const slice5 = klines.slice(idx - 4, idx + 1);
      const ma5 = slice5.reduce((acc, it) => acc + it.close, 0) / 5.0;
      const yMa5 = priceToY(ma5);
      ma5Path += (ma5Path === '' ? `M ${xMid} ${yMa5}` : ` L ${xMid} ${yMa5}`);
    }
    if (idx >= 9) {
      const slice10 = klines.slice(idx - 9, idx + 1);
      const ma10 = slice10.reduce((acc, it) => acc + it.close, 0) / 10.0;
      const yMa10 = priceToY(ma10);
      ma10Path += (ma10Path === '' ? `M ${xMid} ${yMa10}` : ` L ${xMid} ${yMa10}`);
    }
  });

  const subUnit = isVol ? '手' : '亿元';
  const subTitle = isVol ? '副图：成交量 (手)' : '副图：成交额 (亿元)';

  return `
    <svg id="stockInteractiveSvg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg" style="background-color: #0b1329; border-radius: 8px; cursor: crosshair;">
      <!-- 主图网格 -->
      <rect x="${m.left}" y="${m.top}" width="${innerW}" height="${mh}" fill="#0f172a" stroke="#1e293b"/>
      
      <!-- 均线图例 -->
      <text x="${m.left + 8}" y="${m.top + 14}" fill="#f8fafc" font-size="10" font-weight="600">
        <tspan fill="#f59e0b">● MA5</tspan>
        <tspan dx="10" fill="#38bdf8">● MA10</tspan>
      </text>

      <!-- 蜡烛线与均线 -->
      ${candles}
      <path d="${ma5Path}" fill="none" stroke="#f59e0b" stroke-width="1.3"/>
      <path d="${ma10Path}" fill="none" stroke="#38bdf8" stroke-width="1.3"/>

      <!-- 需求4: 缠论笔与买卖点标记图层 (开启时渲染) -->
      <defs><clipPath id="chanlunClip"><rect x="${m.left}" y="${m.top}" width="${innerW}" height="${mh}"/></clipPath></defs><g clip-path="url(#chanlunClip)">${appState.showChanlunDraw ? generateChanlunOverlaySVG(klines, (i) => m.left + i * stepX + stepX / 2, priceToY, analysis) : ''}</g>

      <!-- 十字光标虚线 -->
      <line id="crosshairX" x1="0" y1="${m.top}" x2="0" y2="${subTopY + sh}" stroke="#94a3b8" stroke-width="1" stroke-dasharray="3,3" style="display:none;"/>
      <line id="crosshairY" x1="${m.left}" y1="0" x2="${m.left + innerW}" y2="0" stroke="#94a3b8" stroke-width="1" stroke-dasharray="3,3" style="display:none;"/>

      <!-- 主图 Y 坐标 -->
      <text x="${m.left - 8}" y="${m.top + 12}" fill="#94a3b8" font-size="11" text-anchor="end" font-family="monospace">¥${maxPrice.toFixed(2)}</text>
      <text x="${m.left - 8}" y="${m.top + mh}" fill="#94a3b8" font-size="11" text-anchor="end" font-family="monospace">¥${minPrice.toFixed(2)}</text>

      <!-- 横轴时间刻度 -->
      <text x="${m.left}" y="${m.top + mh + 14}" fill="#64748b" font-size="10" text-anchor="start">${klines[0].date}</text>
      <text x="${m.left + innerW * 0.5}" y="${m.top + mh + 14}" fill="#64748b" font-size="10" text-anchor="middle">${klines[Math.floor(n / 2)].date}</text>
      <text x="${m.left + innerW}" y="${m.top + mh + 14}" fill="#64748b" font-size="10" text-anchor="end">${klines[n - 1].date}</text>

      <!-- 需求REQ-014/015: 统一渲染多模型辅助线（自动多阶线/手动压力线/手动支撑线共存，按 zIndex 分层） -->
      ${buildHorizontalLinesSVG({
        m: m,
        innerW: innerW,
        priceToY: (p) => priceToY(p),
        refPrice: Number(klines[klines.length - 1].close || klines[klines.length - 1].price)
      })}

      <!-- 副图区域 -->
      <rect x="${m.left}" y="${subTopY}" width="${innerW}" height="${sh}" fill="#0f172a" stroke="#1e293b"/>
      <text x="${m.left + 8}" y="${subTopY + 14}" fill="#94a3b8" font-size="10" font-weight="600">${subTitle}</text>
      ${summaryBadgesSvg}
      <text x="${m.left - 8}" y="${subTopY + 14}" fill="#64748b" font-size="10" text-anchor="end" font-family="monospace">${maxSubVal.toFixed(1)}${subUnit}</text>
      
      <!-- 副图柱状图 -->
      ${subBars}
    </svg>
  `;
}

/**
 * 需求1: 关闭股票详情全屏页面，返回股票列表视图
 */
// ====================================================
// 需求1/2: 一级股东研究全景控制逻辑 (加载、筛选、排序与渲染)
// ====================================================

let shareholderState = {
  category: 'all',
  keyword: '',
  page: 1, total: 0, pageSize: 50,
  requestId: 0,
  sortBy: 'company_count',
  sortDir: 'desc',
  data: []
};

async function loadShareholdersOverview() {
  const requestId=++shareholderState.requestId;
  const tbody = document.getElementById('shareholdersTableBody');
  if (!tbody) return;

  tbody.innerHTML = `
    <tr>
      <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 3rem;">
        <div class="spinner"></div>
        <div>正在读取已采集的十大股东披露与姓名去重结果...</div>
      </td>
    </tr>
  `;

  try {
    const params = new URLSearchParams({
      category: shareholderState.category,
      keyword: shareholderState.keyword,
      sort_by: shareholderState.sortBy,
      sort_dir: shareholderState.sortDir, page: shareholderState.page, page_size: shareholderState.pageSize
    });

    const res = await fetch(`/api/shareholders/list?${params.toString()}`);
    if (!res.ok) throw new Error('拉取股东列表失败');
    const json = await res.json();
    if(requestId!==shareholderState.requestId)return;
    shareholderState.data = json.data || [];
    shareholderState.total=json.total||0;
    const pageInfo=document.getElementById("shareholderPageInfo");
    if(pageInfo)pageInfo.textContent=`第 ${shareholderState.page} / ${Math.max(1,Math.ceil(shareholderState.total/shareholderState.pageSize))} 页，共 ${shareholderState.total} 个匹配姓名；概览统计所有已采集姓名`;
    const info = document.getElementById('shareholderDataStatus');
    const meta = json.metadata || {};
    if(info) info.textContent = `${meta.source || '来源未获取'} · ${({available:'已完成本次来源分页',partial:'部分覆盖',stale:'缓存已过期',unavailable:'未获取'})[meta.status]||'未核验'} · 已采集 ${meta.count ?? '未知'} 条 / ${meta.covered_stocks ?? '未知'} 只证券 · ${meta.scope || '非全市场股东总数'} · ${meta.fetched_at || ''}${meta.error ? ' · '+meta.error : ''}`;
    if(meta.status === 'unavailable') Object.keys(json.overview || {}).forEach(k => json.overview[k] = null);

    // 需求1: 渲染概览信息 (股东总数、机构股东总数、个人股东总数、股东总金额、机构股东总金额、个人股东总金额)
    if (json.overview) {
      const ov = json.overview;
      if (dom.shOverviewTotalHolders) dom.shOverviewTotalHolders.textContent = `${ov.total_holders_count == null ? "未获取" : ov.total_holders_count.toLocaleString()} 个姓名`;
      if (dom.shOverviewInstHolders) dom.shOverviewInstHolders.textContent = `${ov.institution_holders_count == null ? "未获取" : ov.institution_holders_count.toLocaleString()} 个姓名`;
      if (dom.shOverviewIndHolders) dom.shOverviewIndHolders.textContent = `${ov.individual_holders_count == null ? "未获取" : ov.individual_holders_count.toLocaleString()} 个姓名`;
      if (dom.shOverviewTotalAmount) dom.shOverviewTotalAmount.textContent = `${ov.total_holding_amount_yi == null ? "未获取" : ov.total_holding_amount_yi.toLocaleString()} 亿`;
      if (dom.shOverviewInstAmount) dom.shOverviewInstAmount.textContent = `${ov.institution_holding_amount_yi == null ? "未获取" : ov.institution_holding_amount_yi.toLocaleString()} 亿`;
      if (dom.shOverviewIndAmount) dom.shOverviewIndAmount.textContent = `${ov.individual_holding_amount_yi == null ? "未获取" : ov.individual_holding_amount_yi.toLocaleString()} 亿`;
    }

    renderShareholdersTable(shareholderState.data);
  } catch (err) {
    if(requestId!==shareholderState.requestId)return;
    console.error('加载股东研究异常:', err);
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; color: var(--color-up); padding: 2rem;">
          获取股东全景列表失败: ${err.message}
        </td>
      </tr>
    `;
  }
}

function renderShareholdersTable(list) {
  const tbody = document.getElementById('shareholdersTableBody');
  if (!tbody) return;

  if (!list || list.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 3rem;">
          没有找到匹配的股东持仓记录
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = list.map(item => {
    const isInd = item.category === 'individual';
    const catBadge = item.category==='unknown' ? '<span>类型未提供</span>' : isInd
      ? `<span class="sh-cat-tag sh-cat-individual">👤 个人股东</span>`
      : `<span class="sh-cat-tag sh-cat-institution">🏢 机构</span>`;

    // 占股企业标签组 (点击可直达企业详情)
    const companyPills = (item.companies || []).map(c => `
      <span class="sh-company-pill" title="点击查看 ${escapeHtml(c.name)} 行情全景与K线" onclick="openStockDetail('${c.code}')">
        <strong>${escapeHtml(c.name)}</strong>
        <span class="pct">${c.hold_pct==null?"未提供":c.hold_pct+"%"}</span>
      </span>
    `).join('');

    return `
      <tr>
        <td><span class="shareholder-id-badge">${item.holder_id}</span></td>
        <td><span class="shareholder-name-cell">${escapeHtml(item.holder_name)}</span></td>
        <td>${catBadge}</td>
        <td>
          <div class="sh-companies-container">
            ${companyPills || '<span style="color: var(--text-muted);">--</span>'}
          </div>
        </td>
        <td>
          <strong style="color: #38bdf8; font-family: monospace; font-size: 1.05rem;">
            ${item.company_count}
          </strong> 家
        </td>
        <td>
          <strong style="color: #f59e0b; font-family: monospace; font-size: 1.05rem;">
            ${item.total_holding_amount == null ? '未获取' : item.total_holding_amount.toLocaleString()}
          </strong> 亿
        </td>
      </tr>
    `;
  }).join('');
}

function filterShareholderCategory(cat) {
  shareholderState.page=1;
  shareholderState.category = cat;
  if (dom.shCategoryControl) {
    dom.shCategoryControl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-cat') === cat);
    });
  }
  loadShareholdersOverview();
}

function executeShareholderSearch() {
  shareholderState.page=1;
  if (dom.shKeywordInput) {
    shareholderState.keyword = dom.shKeywordInput.value.trim();
  }
  loadShareholdersOverview();
}

function resetShareholderFilters() {
  shareholderState.page=1;
  shareholderState.category = 'all';
  shareholderState.keyword = '';
  shareholderState.sortBy = 'total_holding_amount';
  shareholderState.sortDir = 'desc';

  if (dom.shCategoryControl) {
    dom.shCategoryControl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-cat') === 'all');
    });
  }
  if (dom.shKeywordInput) dom.shKeywordInput.value = '';
  loadShareholdersOverview();
}

function sortShareholderTable(field) {
  shareholderState.page=1;
  if (shareholderState.sortBy === field) {
    shareholderState.sortDir = shareholderState.sortDir === 'desc' ? 'asc' : 'desc';
  } else {
    shareholderState.sortBy = field;
    shareholderState.sortDir = 'desc';
  }
  loadShareholdersOverview();
}

// ====================================================
// 需求2/3/4/5/6: 指数大盘与专属成交额K线详情交互控制
// ====================================================

let indexState = {
  list: [],
  activeIndex: null,
  period: 'timeline',
  showAutoLines: false,
  autoLinesCount: 0,
  drawingMode: 'none',
  // 需求REQ-014/015: 指数图表同样采用图层模型，自动线与手动线可共存、可分别清除、可点击置顶
  lineLayers: {
    auto:   { key: 'auto',   lines: [], visible: true },
    manual: { key: 'manual', lines: [], visible: true }
  },
  lineZCounter: 1000,
  topLineId: null,
  customLines: [], // 兼容旧引用：渲染与逻辑一律以 lineLayers 为准
  customZoomCount: 0 // 需求3: 指数K线图支持滚轮自由缩放
};

const INDEX_LINE_LAYER_META = {
  auto:   { name: '自动多阶线', icon: '🤖', base: 10 },
  manual: { name: '手动水平线', icon: '📏', base: 20 }
};

function ensureIndexLineLayers() {
  if (!indexState.lineLayers || typeof indexState.lineLayers !== 'object') indexState.lineLayers = {};
  Object.keys(INDEX_LINE_LAYER_META).forEach(key => {
    const layer = indexState.lineLayers[key];
    if (!layer || !Array.isArray(layer.lines)) {
      indexState.lineLayers[key] = { key, lines: [], visible: layer ? layer.visible !== false : true };
    } else if (layer.visible === undefined) {
      layer.visible = true;
    }
  });
  return indexState.lineLayers;
}

function nextIndexLineZ() {
  indexState.lineZCounter = (indexState.lineZCounter || 1000) + 1;
  return indexState.lineZCounter;
}

function getVisibleIndexLines() {
  const layers = ensureIndexLineLayers();
  const out = [];
  Object.keys(INDEX_LINE_LAYER_META).forEach(key => {
    const layer = layers[key];
    if (layer.visible === false) return;
    layer.lines.forEach(l => { l.layerKey = key; out.push(l); });
  });
  out.sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0));
  return out;
}

/** 需求REQ-014: 指数图表 —— 只清除指定模型 */
function clearIndexLayer(layerKey) {
  const layers = ensureIndexLineLayers();
  if (!layers[layerKey]) return;
  layers[layerKey].lines = [];
  if (layerKey === 'auto') {
    indexState.autoLinesCount = 0;
    indexState.showAutoLines = false;
    const ctrl = document.getElementById('indexAutoLinesCountControl');
    if (ctrl) ctrl.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b.getAttribute('data-count') === '0'));
  }
  renderActiveIndexChart();
}

/** 需求REQ-014: 指数图表 —— 切换模型显隐 */
function toggleIndexLayerVisible(layerKey) {
  const layers = ensureIndexLineLayers();
  if (!layers[layerKey]) return;
  layers[layerKey].visible = layers[layerKey].visible === false;
  renderActiveIndexChart();
}

/** 需求REQ-014: 指数图层管理面板 (格式塔: 共同区域 + 邻近性) */
function renderIndexLineLayerPanel() {
  const panel = document.getElementById('indexLayerPanel');
  if (!panel) return;
  ensureIndexLineLayers();
  panel.innerHTML = Object.keys(INDEX_LINE_LAYER_META).map(key => {
    const meta = INDEX_LINE_LAYER_META[key];
    const layer = indexState.lineLayers[key];
    const n = layer.lines.length;
    const visible = layer.visible !== false;
    return `
      <div class="chart-layer-row" data-layer="${key}">
        <span class="chart-layer-name">${meta.icon} ${meta.name}</span>
        <span class="chart-layer-count">${n === 0 ? '未绘制' : `已绘制 ${n} 根`}</span>
        <button type="button" class="chart-layer-btn ${visible ? 'on' : ''}" onclick="toggleIndexLayerVisible('${key}')"
                title="${visible ? '隐藏' : '显示'}${meta.name}（不影响另一模型）">${visible ? '👁 显示' : '🚫 隐藏'}</button>
        <button type="button" class="chart-layer-btn danger" onclick="clearIndexLayer('${key}')" ${n === 0 ? 'disabled' : ''}
                title="仅清除「${meta.name}」，另一模型保持不变">🧹 清除</button>
      </div>
    `;
  }).join('');
}

/** 需求REQ-015: 指数图表 —— 重合辅助线点击置顶 (含标签精准命中与轮换巡览) */
function handleIndexLineClick(mouseX, mouseY, margin, plotWidth, mainHeight) {
  const lines = getVisibleIndexLines().filter(l => Number.isFinite(l._svgY));
  if (!lines.length) return;

  const tagHits = lines.filter(l =>
    l._tagX !== undefined && mouseX >= l._tagX && mouseX <= l._tagX + l._tagW &&
    Math.abs(mouseY - l._svgY) <= 12
  );
  if (tagHits.length) {
    const target = tagHits[tagHits.length - 1];
    target.zIndex = nextIndexLineZ();
    indexState.topLineId = target.id;
    renderActiveIndexChart();
    showChartToast(`已置顶：${target.type} ¥${Number(target.price).toFixed(2)}`);
    return;
  }

  if (mouseY < margin.top || mouseY > mainHeight) return;
  const hits = lines.filter(l => Math.abs(mouseY - l._svgY) <= LINE_HIT_TOLERANCE);
  if (!hits.length) return;
  if (hits.length === 1) {
    hits[0].zIndex = nextIndexLineZ();
    indexState.topLineId = hits[0].id;
    renderActiveIndexChart();
    showChartToast(`已置顶：${hits[0].type} ¥${Number(hits[0].price).toFixed(2)}`);
    return;
  }
  hits.sort((a, b) => (a.zIndex || 0) - (b.zIndex || 0));
  const target = hits[0];
  target.zIndex = nextIndexLineZ();
  indexState.topLineId = target.id;
  renderActiveIndexChart();
  showChartToast(`重合 ${hits.length} 条 → 已置顶：${target.type} ¥${Number(target.price).toFixed(2)}`);
}

/**
 * 需求3/4: 加载大盘指数列表 (上证指数、深证成指)
 * 表头: 代码、名称、最新、现价、涨幅、成交金额、操作
 */
async function loadIndicesList() {
  const tbody = document.getElementById('indexTableBody');
  if (!tbody) return;

  tbody.innerHTML = `
    <tr>
      <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 3rem;">
        <div class="spinner"></div>
        <div>正在调取上海与深圳交易所官方基准指数实时行情...</div>
      </td>
    </tr>
  `;

  try {
    const res = await fetch('/api/index/list');
    if (!res.ok) throw new Error('拉取指数行情失败');
    const json = await res.json();
    indexState.list = json.data || [];
    renderIndicesTable(indexState.list);
  } catch (err) {
    console.error('加载指数列表异常:', err);
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; color: var(--color-up); padding: 2rem;">
          获取指数行情失败: ${err.message}
        </td>
      </tr>
    `;
  }
}

function renderIndicesTable(list) {
  const tbody = document.getElementById('indexTableBody');
  if (!tbody) return;

  if (!list || list.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 3rem;">
          暂无大盘基准指数数据
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = list.map(item => {
    const isUp = item.change >= 0;
    const colorClass = isUp ? 'price-up' : 'price-down';
    const sign = isUp ? '+' : '';

    return `
      <tr class="index-row-interactive" onclick="openIndexDetail('${item.code}')">
        <td><span class="index-code-badge">${item.raw_code || item.code?.slice(2) || '未获取'}</span></td>
        <td>
          <span class="index-name-title" title="点击查看 ${item.name} 专属K线与成交额中枢">
            ${item.name}
          </span>
        </td>
        <td><span class="index-price-val ${colorClass}">${formatReal(item.price,2)}</span></td>
        <td><span class="index-price-val ${colorClass}">${formatReal(item.price,2)}</span></td>
        <td>
          <span class="stock-change-badge ${isUp ? 'badge-up' : 'badge-down'}">
            ${sign}${formatReal(item.change_pct,2)}%
          </span>
        </td>
        <td>
          <strong style="color: #f59e0b; font-family: monospace; font-size: 1.05rem;">
            ${formatReal(item.turnover_yi,2)}
          </strong> 亿
        </td>
        <td style="text-align: center;">
          <button class="btn btn-secondary" style="padding: 0.25rem 0.65rem; font-size: 0.78rem;" onclick="event.stopPropagation(); openIndexDetail('${item.code}')">
            指数详情 ➔
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

/**
 * 需求5/6: 点击指数切换到指数详情页面
 * @param {string} code 指数代码 (sh000001 | sz399001)
 */
async function openIndexDetail(code) {
  // 隐藏其他主视图
  if (dom.viewFilterTab) dom.viewFilterTab.classList.add('hidden');
  if (dom.viewDashboardTab) dom.viewDashboardTab.classList.add('hidden');
  if (dom.viewWorldTab) dom.viewWorldTab.classList.add('hidden');
  if (dom.viewShareholdersTab) dom.viewShareholdersTab.classList.add('hidden');
  if (dom.viewIndexTab) dom.viewIndexTab.classList.add('hidden');
  if (dom.viewCrawlerTab) dom.viewCrawlerTab.classList.add('hidden');
  if (dom.viewStockDetailTab) dom.viewStockDetailTab.classList.add('hidden');

  // 展示指数详情全屏页
  if (dom.viewIndexDetailTab) {
    dom.viewIndexDetailTab.classList.remove('hidden');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  dom.indexModalName.textContent = '指数行情加载中...';
  dom.indexModalCode.textContent = code;
  dom.indexChartSvgContainer.innerHTML = '<div style="padding: 2.5rem; color: var(--text-muted);"><div class="spinner"></div><div>正在调取大盘基准真实历史日K与资金成交额中枢...</div></div>';
  hideTooltip();

  try {
    const res = await fetch(`/api/index/${code}`);
    if (!res.ok) throw new Error('获取指数详情失败');
    const json = await res.json();
    const indexData = json.data;
    indexState.activeIndex = indexData;

    // 填充顶部行情看板
    dom.indexModalName.textContent = indexData.name;
    dom.indexModalCode.textContent = indexData.code;
    const isUp = indexData.change >= 0;
    const colorClass = isUp ? 'price-up' : 'price-down';
    const sign = isUp ? '+' : '';

    dom.indexModalPriceBadge.textContent = formatReal(indexData.price,2);
    dom.indexModalPriceBadge.className = colorClass;
    dom.indexModalChangeBadge.textContent = `${sign}${formatReal(indexData.change,2)} (${sign}${formatReal(indexData.change_pct,2)}%)`;
    dom.indexModalChangeBadge.className = colorClass;

    if (dom.indexModalOpen) dom.indexModalOpen.textContent = indexData.open.toFixed(2);
    if (dom.indexModalPrevClose) dom.indexModalPrevClose.textContent = indexData.prev_close.toFixed(2);
    if (dom.indexModalHigh) dom.indexModalHigh.textContent = indexData.high.toFixed(2);
    if (dom.indexModalLow) dom.indexModalLow.textContent = indexData.low.toFixed(2);
    if (dom.indexModalTurnover) dom.indexModalTurnover.textContent = `${formatReal(indexData.turnover_yi)} 亿`;

    // 渲染走势图
    renderActiveIndexChart();
  } catch (err) {
    console.error('加载指数详情异常:', err);
    dom.indexChartSvgContainer.innerHTML = `<div style="padding: 2rem; color: var(--color-up);">加载指数走势图谱失败: ${err.message}</div>`;
  }
}

function closeIndexDetailPage() {
  if (dom.viewIndexDetailTab) {
    dom.viewIndexDetailTab.classList.add('hidden');
  }
  // 切回指数列表
  if (dom.viewIndexTab) {
    dom.viewIndexTab.classList.remove('hidden');
  }
  indexState.activeIndex = null;
  hideTooltip();
}

function switchIndexChartPeriod(period) {
  indexState.period = period;
  indexState.customZoomCount = 0; // 切换预设周期时重置自定义缩放
  if (dom.indexChartPeriodControl) {
    dom.indexChartPeriodControl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-period') === period);
    });
  }
  renderActiveIndexChart();
}

function setIndexAutoLinesCount(count) {
  indexState.autoLinesCount = parseInt(count, 10) || 0;
  indexState.showAutoLines = indexState.autoLinesCount > 0;
  const ctrl = document.getElementById('indexAutoLinesCountControl');
  if (ctrl) {
    ctrl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.classList.toggle('active', parseInt(btn.getAttribute('data-count'), 10) === indexState.autoLinesCount);
    });
  }
  renderActiveIndexChart();
}

function toggleIndexAutoLines() {
  setIndexAutoLinesCount(indexState.autoLinesCount === 1 ? 0 : 1);
}

function setIndexDrawingMode(mode) {
  indexState.drawingMode = indexState.drawingMode === mode ? 'none' : mode;
  if (dom.btnIndexDrawHorizontal) {
    dom.btnIndexDrawHorizontal.classList.toggle('active', indexState.drawingMode === 'horizontal');
  }
}

function clearIndexChartDrawings() {
  // 需求REQ-014: 兜底「清除全部」；各模型自身的清除入口为 clearIndexLayer(layerKey)
  const layers = ensureIndexLineLayers();
  Object.keys(INDEX_LINE_LAYER_META).forEach(key => { layers[key].lines = []; layers[key].visible = true; });
  indexState.autoLinesCount = 0;
  indexState.showAutoLines = false;
  indexState.drawingMode = 'none';
  indexState.topLineId = null;
  indexState.lineZCounter = 1000;
  const ctrl = document.getElementById('indexAutoLinesCountControl');
  if (ctrl) {
    ctrl.querySelectorAll('.seg-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-count') === '0');
    });
  }
  if (dom.btnIndexDrawHorizontal) dom.btnIndexDrawHorizontal.classList.remove('active');
  renderActiveIndexChart();
}

/**
 * 需求6: 渲染指数专属走势图谱 (分时、5天、10天、20天、60天、全部K线，副图只有成交金额，配备自动画线)
 */
function renderActiveIndexChart() {
  renderIndexLineLayerPanel();
  const indexData = indexState.activeIndex;
  if (!indexData || !dom.indexChartSvgContainer) return;

  const width = dom.indexChartSvgContainer.clientWidth || 920;
  const height = 480;
  const margin = { top: 30, right: 90, bottom: 35, left: 60 };
  const mainHeight = 310;
  const subHeight = 90;
  const subTop = mainHeight + 45;

  if (indexState.period === 'timeline') {
    // 渲染分时图
    const timeline = indexData.timeline_data || {};
    const items = timeline.items || [];
    const preClose = timeline.pre_close || indexData.prev_close;

    if (items.length === 0) {
      dom.indexChartSvgContainer.innerHTML = '<div style="padding: 3rem; text-align: center; color: var(--text-muted);">暂无官方分时数据源</div>';
      return;
    }

    let minPrice = preClose;
    let maxPrice = preClose;
    let maxAmount = 0.1;
    items.forEach(it => {
      if (it.price < minPrice) minPrice = it.price;
      if (it.price > maxPrice) maxPrice = it.price;
      if (it.amount_yi > maxAmount) maxAmount = it.amount_yi;
    });

    const diff = Math.max(Math.abs(maxPrice - preClose), Math.abs(minPrice - preClose));
    minPrice = Math.floor((preClose - diff * 1.1) * 10) / 10;
    maxPrice = Math.ceil((preClose + diff * 1.1) * 10) / 10;
    if (minPrice === maxPrice) { minPrice *= 0.99; maxPrice *= 1.01; }

    const plotWidth = width - margin.left - margin.right;
    const n = items.length;
    const getX = idx => margin.left + (idx / Math.max(1, n - 1)) * plotWidth;
    const getY = p => margin.top + (1 - (p - minPrice) / (maxPrice - minPrice)) * (mainHeight - margin.top);
    const getSubY = a => subTop + (1 - (a / maxAmount)) * subHeight;

    let pathD = '';
    let areaD = `M ${margin.left} ${mainHeight}`;
    items.forEach((it, idx) => {
      const x = getX(idx);
      const y = getY(it.price);
      if (idx === 0) {
        pathD += `M ${x} ${y}`;
        areaD += ` L ${x} ${y}`;
      } else {
        pathD += ` L ${x} ${y}`;
        areaD += ` L ${x} ${y}`;
      }
    });
    areaD += ` L ${getX(n - 1)} ${mainHeight} Z`;

    const subBarsSvg = items.map((it, idx) => {
      if (it.amount_yi == null) return "";
      const x = getX(idx) - 2;
      const y = getSubY(it.amount_yi);
      const barH = Math.max(1, subTop + subHeight - y);
      const isUp = it.price >= preClose;
      const color = isUp ? 'var(--color-up)' : 'var(--color-down)';
      return `<rect x="${x}" y="${y}" width="4" height="${barH}" fill="${color}" opacity="0.8"/>`;
    }).join('');

    const preCloseY = getY(preClose);

    dom.indexChartSvgContainer.innerHTML = `
      <svg width="${width}" height="${height}" style="user-select: none; display: block; overflow: visible;">
        <defs>
          <linearGradient id="indexTimelineGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.35"/>
            <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.0"/>
          </linearGradient>
        </defs>

        <!-- 背景网格与轴线 -->
        <rect x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${mainHeight - margin.top}" fill="none" stroke="rgba(51, 65, 85, 0.4)"/>
        <line x1="${margin.left}" y1="${preCloseY}" x2="${margin.left + plotWidth}" y2="${preCloseY}" stroke="rgba(148, 163, 184, 0.6)" stroke-dasharray="4,4"/>

        <!-- 副图背景 (仅成交金额) -->
        <rect x="${margin.left}" y="${subTop}" width="${plotWidth}" height="${subHeight}" fill="none" stroke="rgba(51, 65, 85, 0.4)"/>
        <text x="${margin.left + 8}" y="${subTop + 16}" fill="#f59e0b" font-size="11" font-weight="700">💰 副图: 成交金额 (亿元)</text>

        <!-- 走势面积与折线 -->
        <path d="${areaD}" fill="url(#indexTimelineGrad)"/>
        <path d="${pathD}" fill="none" stroke="#38bdf8" stroke-width="2"/>

        <!-- 副图柱子 -->
        ${subBarsSvg}

        <!-- 坐标刻度 -->
        <text x="${margin.left - 8}" y="${margin.top + 10}" fill="var(--color-up)" font-size="11" text-anchor="end" font-family="monospace">${maxPrice.toFixed(2)}</text>
        <text x="${margin.left - 8}" y="${preCloseY + 4}" fill="#94a3b8" font-size="11" text-anchor="end" font-family="monospace">${preClose.toFixed(2)}</text>
        <text x="${margin.left - 8}" y="${mainHeight}" fill="var(--color-down)" font-size="11" text-anchor="end" font-family="monospace">${minPrice.toFixed(2)}</text>

        <text x="${margin.left - 8}" y="${subTop + 14}" fill="#f59e0b" font-size="10" text-anchor="end" font-family="monospace">${maxAmount.toFixed(1)}亿</text>
        <text x="${margin.left - 8}" y="${subTop + subHeight}" fill="#94a3b8" font-size="10" text-anchor="end" font-family="monospace">0</text>
      </svg>
    `;
  } else {
    // 渲染 K 线图 (5天、10天、20天、60天、全部K线)
    let klines = (indexData.daily_bars && Array.isArray(indexData.daily_bars) && indexData.daily_bars.length > 0)
      ? indexData.daily_bars
      : null;

    if (!klines || klines.length === 0) {
      dom.indexChartSvgContainer.innerHTML = '<div style="padding: 3rem; text-align: center; color: var(--text-muted);">⚠️ 暂无官方真实大盘日K数据源</div>';
      return;
    }

    // 需求2/3: 指数切片 (5天 / 10天 / 20天 / 60天 / 120天 / 180天 / 全部，以及滚轮自由缩放)
    let winCount = klines.length;
    if (indexState.customZoomCount > 0) {
      winCount = Math.min(klines.length, Math.max(5, indexState.customZoomCount));
    } else if (indexState.period === 'kline5') winCount = Math.min(klines.length, 5);
    else if (indexState.period === 'kline10') winCount = Math.min(klines.length, 10);
    else if (indexState.period === 'kline20') winCount = Math.min(klines.length, 20);
    else if (indexState.period === 'kline60') winCount = Math.min(klines.length, 60);
    else if (indexState.period === 'kline120') winCount = Math.min(klines.length, 120);
    else if (indexState.period === 'kline180') winCount = Math.min(klines.length, 180);
    else if (indexState.period === 'all') winCount = klines.length;

    if (klines.length > winCount) {
      klines = klines.slice(klines.length - winCount);
    }

    let minPrice = Infinity;
    let maxPrice = -Infinity;
    let maxAmount = 0.1;
    klines.forEach(k => {
      if (k.low < minPrice) minPrice = k.low;
      if (k.high > maxPrice) maxPrice = k.high;
      if (k.amount_yi > maxAmount) maxAmount = k.amount_yi;
    });

    const pPad = (maxPrice - minPrice) * 0.08 || 5;
    minPrice = Math.floor(minPrice - pPad);
    maxPrice = Math.ceil(maxPrice + pPad);

    const plotWidth = width - margin.left - margin.right;
    const n = klines.length;
    const candleWidth = Math.max(3, Math.min(38, Math.floor(plotWidth / n) - 2));
    const getX = idx => margin.left + (idx + 0.5) * (plotWidth / n);
    const getY = p => margin.top + (1 - (p - minPrice) / (maxPrice - minPrice)) * (mainHeight - margin.top);
    const getSubY = a => subTop + (1 - (a / maxAmount)) * subHeight;

    // 需求1: 计算大盘指数K线当前可视周期内成交额的四维分布概要 (平均、最小、最大、中位数)
    const indexAmtStats = calculateDistributionSummary(klines.map(k => k.amount_yi));
    let indexSummarySvg = `
      <g class="sub-summary-group">
        <text x="${margin.left + 160}" y="${subTop + 16}" fill="#f59e0b" font-size="10" font-family="monospace">
          <tspan fill="#94a3b8">平均:</tspan> <tspan font-weight="700" fill="#f59e0b">${indexAmtStats.mean.toFixed(2)}亿</tspan>
          <tspan dx="10" fill="#94a3b8">地量(最小):</tspan> <tspan font-weight="700" fill="#10b981">${indexAmtStats.min.toFixed(2)}亿</tspan>
          <tspan dx="10" fill="#94a3b8">天量(最大):</tspan> <tspan font-weight="700" fill="#ef4444">${indexAmtStats.max.toFixed(2)}亿</tspan>
          <tspan dx="10" fill="#94a3b8">中位数:</tspan> <tspan font-weight="700" fill="#facc15">${indexAmtStats.median.toFixed(2)}亿</tspan>
        </text>
      </g>
    `;

    if (klines.some(k => k.amount_yi == null)) indexSummarySvg = `<text x="${margin.left + 100}" y="${subTop + 14}" fill="#94a3b8" font-size="12">当前来源未提供完整成交额</text>`;
    // 蜡烛与仅成交金额柱
    let candlesSvg = '';
    let subBarsSvg = '';

    klines.forEach((k, idx) => {
      const x = getX(idx);
      const isUp = k.close >= k.open;
      const color = isUp ? 'var(--color-up)' : 'var(--color-down)';

      // 影线
      const yHigh = getY(k.high);
      const yLow = getY(k.low);
      candlesSvg += `<line x1="${x}" y1="${yHigh}" x2="${x}" y2="${yLow}" stroke="${color}" stroke-width="1.2"/>`;

      // 实体
      const yOpen = getY(k.open);
      const yClose = getY(k.close);
      const yTop = Math.min(yOpen, yClose);
      const hRect = Math.max(1.5, Math.abs(yOpen - yClose));
      candlesSvg += `<rect x="${x - candleWidth / 2}" y="${yTop}" width="${candleWidth}" height="${hRect}" fill="${color}" opacity="0.9"/>`;

      // 副图柱 (仅成交金额)
      const ySub = k.amount_yi == null ? subTop + subHeight : getSubY(k.amount_yi);
      const hSub = Math.max(1, subTop + subHeight - ySub);
      if (k.amount_yi != null) subBarsSvg += `<rect x="${x - candleWidth / 2}" y="${ySub}" width="${candleWidth}" height="${hSub}" fill="${color}" opacity="0.8"/>`;
    });

    // 需求REQ-014/015: 指数多阶自动画线 (1~4 根筹码中枢线) —— 写入独立图层模型，按 zIndex 参与层级排序
    if (indexState.showAutoLines && indexState.autoLinesCount > 0) {
      const autoLevels = calculateAutoSupportResistanceLevels(klines, indexData.price, indexState.autoLinesCount);
      indexState.lineLayers.auto.lines = autoLevels.map((line, idx) => ({
        ...line,
        id: `index_auto_${line.rank || idx + 1}_${Math.round(line.price * 100)}`,
        type: line.type,
        layerKey: 'auto',
        zIndex: INDEX_LINE_LAYER_META.auto.base + idx
      }));
    } else if (!indexState.showAutoLines) {
      indexState.lineLayers.auto.lines = [];
    }

    // 需求REQ-014/015: 统一渲染指数图多模型辅助线
    const indexRefPrice = Number(indexData.price || klines[klines.length - 1].close);
    const indexVisibleLines = getVisibleIndexLines();
    indexVisibleLines.forEach(l => { l._svgY = getY(l.price); l._overlapCount = 1; });
    for (let i = 0; i < indexVisibleLines.length; i++) {
      for (let j = i + 1; j < indexVisibleLines.length; j++) {
        if (Math.abs(indexVisibleLines[i]._svgY - indexVisibleLines[j]._svgY) <= LINE_HIT_TOLERANCE) {
          indexVisibleLines[i]._overlapCount++;
          indexVisibleLines[j]._overlapCount++;
        }
      }
    }
    const indexMaxZ = indexVisibleLines.length ? Math.max(...indexVisibleLines.map(l => l.zIndex || 0)) : 0;
    const indexTopLine = indexVisibleLines.find(l => l.id === indexState.topLineId);
    const indexTopZ = indexTopLine ? (indexTopLine.zIndex || 0) : indexMaxZ;

    const autoLinesSvg = indexVisibleLines.map(line => {
      const lineY = line._svgY;
      const isAuto = line.layerKey === 'auto';
      const daysPart = line.crossedDays !== undefined ? `, 交易日: ${line.crossedDays}天` : '';
      const color = line.color || (isAuto ? '#f59e0b' : (line.price >= indexRefPrice ? '#f43f5e' : '#10b981'));
      const isTop = (line.zIndex || 0) >= indexTopZ;
      const overlapNote = line._overlapCount > 1 ? ` ·重合${line._overlapCount}` : '';
      const topNote = isTop ? '⭐ ' : '';
      let labelText = `${line.type}: ¥${Number(line.price).toFixed(2)}`;
      let tagW = 150;
      if (line.crossedAmountYi != null) {
        labelText = `${line.type}: ¥${Number(line.price).toFixed(2)} (交汇: ${line.crossedAmountYi}亿${daysPart})`;
        tagW = 320;
      }
      labelText = `${topNote}${labelText}${overlapNote}`;
      tagW += (isTop ? 16 : 0) + (line._overlapCount > 1 ? 52 : 0);
      const tagX = margin.left + plotWidth - tagW;
      line._tagX = tagX;
      line._tagW = tagW;
      const baseWidth = isAuto ? (line.rank === 1 ? 2.5 : 1.8) : 1.8;
      const strokeWidth = isTop ? baseWidth + 0.8 : baseWidth;
      const opacity = isTop ? 1 : (line._overlapCount > 1 ? 0.55 : 0.92);
      return `
        <g class="chart-hline layer-${line.layerKey}" data-line-id="${line.id}" opacity="${opacity}">
          <line x1="${margin.left}" y1="${lineY}" x2="${margin.left + plotWidth}" y2="${lineY}" stroke="${color}" stroke-width="${strokeWidth}" stroke-dasharray="${isAuto ? '6,4' : '5,3'}"/>
          <rect x="${tagX}" y="${lineY - 12}" width="${tagW}" height="24" rx="4" fill="#0f172a" stroke="${color}" stroke-width="${isTop ? 1.8 : 1.2}" opacity="0.95"/>
          <text x="${margin.left + plotWidth - 6}" y="${lineY + 4}" fill="${color}" font-size="11" font-weight="${isTop ? 700 : 600}" text-anchor="end" font-family="monospace">
            ${labelText}
          </text>
        </g>
      `;
    }).join('');

    dom.indexChartSvgContainer.innerHTML = `
      <svg id="indexKLineSvg" width="${width}" height="${height}" style="user-select: none; display: block; overflow: visible; cursor: ${indexState.drawingMode === 'horizontal' ? 'crosshair' : 'default'};">
        <!-- 主图网格 -->
        <rect x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${mainHeight - margin.top}" fill="none" stroke="rgba(51, 65, 85, 0.4)"/>

        <!-- 副图网格 (仅成交金额) -->
        <rect x="${margin.left}" y="${subTop}" width="${plotWidth}" height="${subHeight}" fill="none" stroke="rgba(51, 65, 85, 0.4)"/>
        <text x="${margin.left + 8}" y="${subTop + 16}" fill="#f59e0b" font-size="11" font-weight="700">💰 副图: 成交金额 (亿元)</text>
        ${indexSummarySvg}

        <!-- 蜡烛与副图 -->
        ${candlesSvg}
        ${subBarsSvg}

        <!-- 需求REQ-014/015: 多模型辅助线（自动线与手动线共存，按 zIndex 分层） -->
        ${autoLinesSvg}

        <!-- 坐标刻度 -->
        <text x="${margin.left - 8}" y="${margin.top + 10}" fill="#94a3b8" font-size="11" text-anchor="end" font-family="monospace">${maxPrice.toFixed(2)}</text>
        <text x="${margin.left - 8}" y="${getY((maxPrice + minPrice) / 2) + 4}" fill="#64748b" font-size="11" text-anchor="end" font-family="monospace">${((maxPrice + minPrice) / 2).toFixed(2)}</text>
        <text x="${margin.left - 8}" y="${mainHeight}" fill="#94a3b8" font-size="11" text-anchor="end" font-family="monospace">${minPrice.toFixed(2)}</text>

        <text x="${margin.left - 8}" y="${subTop + 14}" fill="#f59e0b" font-size="10" text-anchor="end" font-family="monospace">${maxAmount.toFixed(1)}亿</text>
        <text x="${margin.left - 8}" y="${subTop + subHeight}" fill="#94a3b8" font-size="10" text-anchor="end" font-family="monospace">0</text>
      </svg>
    `;

    // 绑定手动画线交互与滚轮缩放
    const svgElem = document.getElementById('indexKLineSvg');
    if (svgElem) {
      // 需求3: 除了分时图以外，所有K线图都可以通过放大缩小来对图形的日期区间进行缩放
      svgElem.addEventListener('wheel', (e) => {
        e.preventDefault();
        const fullLen = (indexData.daily_bars && indexData.daily_bars.length) || 100;
        let curCount = indexState.customZoomCount > 0 
          ? indexState.customZoomCount 
          : (winCount || 60);

        const step = Math.max(1, Math.round(curCount * 0.05));
        if (e.deltaY < 0) {
          // 向上滚 -> 放大 -> 数量减少
          curCount = Math.max(5, curCount - step);
        } else {
          // 向下滚 -> 缩小 -> 数量增加
          curCount = Math.min(fullLen, curCount + step);
        }
        indexState.customZoomCount = curCount;
        renderActiveIndexChart();
      }, { passive: false });

      svgElem.addEventListener('click', (e) => {
        const rect = svgElem.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const clickY = e.clientY - rect.top;

        if (indexState.drawingMode === 'horizontal') {
          if (clickY >= margin.top && clickY <= mainHeight) {
            const ratio = 1 - (clickY - margin.top) / (mainHeight - margin.top);
            const clickPrice = roundTo(minPrice + ratio * (maxPrice - minPrice), 2);
            const isPressure = clickPrice >= Number(indexData.price || clickPrice);
            const newLine = {
              id: `index_manual_${Date.now()}_${Math.round(clickPrice * 100)}`,
              price: clickPrice,
              type: isPressure ? '压力位' : '支撑位',
              layerKey: 'manual',
              zIndex: nextIndexLineZ()
            };
            indexState.lineLayers.manual.lines.push(newLine);
            indexState.topLineId = newLine.id;
            setIndexDrawingMode('none');
            renderActiveIndexChart();
            showChartToast('已加入「手动水平线」模型');
          }
          return;
        }

        // 需求REQ-015: 点击重合辅助线置顶
        handleIndexLineClick(clickX, clickY, margin, plotWidth, mainHeight);
      });
    }
  }
}

function closeStockDetailPage() {
  ++appState.detailRequestId;
  if (appState.detailAbortController) appState.detailAbortController.abort();
  if (dom.viewStockDetailTab) {
    dom.viewStockDetailTab.classList.add('hidden');
  }
  // 切回对应的主 Tab (通常是列表 filter)
  if (appState.currentTab === 'dashboard') {
    if (dom.viewDashboardTab) dom.viewDashboardTab.classList.remove('hidden');
  } else if (appState.currentTab === 'world') {
    if (dom.viewWorldTab) dom.viewWorldTab.classList.remove('hidden');
  } else if (appState.currentTab === 'shareholders') {
    if (dom.viewShareholdersTab) dom.viewShareholdersTab.classList.remove('hidden');
  } else if (appState.currentTab === 'index') {
    if (dom.viewIndexTab) dom.viewIndexTab.classList.remove('hidden');
  } else if (appState.currentTab === 'crawler') {
    if (dom.viewCrawlerTab) dom.viewCrawlerTab.classList.remove('hidden');
  } else {
    if (dom.viewFilterTab) dom.viewFilterTab.classList.remove('hidden');
  }
  appState.activeDetailStock = null;
  hideTooltip();
}

function closeStockDetail() {
  closeStockDetailPage();
}

function formatReal(value,digits=2) { return value == null || !Number.isFinite(Number(value)) ? '未获取' : Number(value).toLocaleString(undefined,{maximumFractionDigits:digits}); }

function escapeHtml(value) { return escapeActionText(String(value ?? "")); }

function changeShareholderPage(delta) { const page=shareholderState.page+delta; if(page<1||page>Math.ceil(shareholderState.total/shareholderState.pageSize))return;shareholderState.page=page;loadShareholdersOverview(); }

/* ==========================================================================
 * 需求REQ-019: 缠论多周期买卖点雷达池前端
 * 原则：只呈现后端返回的真实结构与风控事实；未获取/不可执行都必须显式说明，
 *       不得把「无信号」说成「无风险」，也不得对不可执行信号展示建议股数。
 * ========================================================================== */
const radarState = {
  types: new Set(['ALL']),   // 选中的买卖点类型
  period: '',
  resonanceOnly: false,
  actionableOnly: false,
  signals: [],
  scanTimer: null,
  snapshot: null,
  scan: null,
  requestId: 0            // 与 REQ-011 详情请求同一套竞态守卫：只接受最新一次筛选的响应
};

const RADAR_TYPE_META = {
  '1B': { label: '1B', name: '第一类买点', side: 'buy', hint: '笔级底背离' },
  '2B': { label: '2B', name: '第二类买点', side: 'buy', hint: '回踩不破前低' },
  '3B': { label: '3B', name: '第三类买点', side: 'buy', hint: '突破中枢回抽不破 ZG' },
  'S1': { label: 'S1', name: '第一类卖点', side: 'sell', hint: '笔级顶背离' },
  'S2': { label: 'S2', name: '第二类卖点', side: 'sell', hint: '反抽不破前高' },
  'S3': { label: 'S3', name: '第三类卖点', side: 'sell', hint: '跌破中枢反抽不回 ZD' }
};

function radarTypeQuery() {
  if (radarState.types.has('ALL') || radarState.types.size === 0) return '';
  return Array.from(radarState.types).join(',');
}

function toggleRadarType(type) {
  if (type === 'ALL') {
    radarState.types = new Set(['ALL']);
  } else {
    radarState.types.delete('ALL');
    if (radarState.types.has(type)) radarState.types.delete(type);
    else radarState.types.add(type);
    if (radarState.types.size === 0) radarState.types = new Set(['ALL']);
  }
  syncRadarChips();
  loadRadarPool();
}

function setRadarPeriod(period) {
  radarState.period = period;
  syncRadarChips();
  loadRadarPool();
}

function toggleRadarResonanceOnly() {
  radarState.resonanceOnly = !radarState.resonanceOnly;
  syncRadarChips();
  renderRadarTable();
}

function toggleRadarActionableOnly() {
  radarState.actionableOnly = !radarState.actionableOnly;
  syncRadarChips();
  renderRadarTable();
}

/** 相似性 + 状态可见性：所有筛选芯片用同一套 active 视觉语言 */
function syncRadarChips() {
  document.querySelectorAll('#radarTypeChips .seg-btn').forEach(btn => {
    btn.classList.toggle('active', radarState.types.has(btn.dataset.radarType));
  });
  document.querySelectorAll('#radarPeriodChips .seg-btn').forEach(btn => {
    btn.classList.toggle('active', (btn.dataset.radarPeriod || '') === radarState.period);
  });
  const ro = document.getElementById('radarResonanceOnly');
  if (ro) ro.classList.toggle('active', radarState.resonanceOnly);
  const ao = document.getElementById('radarActionableOnly');
  if (ao) ao.classList.toggle('active', radarState.actionableOnly);
}

async function loadRadarPool() {
  syncRadarChips();
  const types = radarTypeQuery();
  const params = new URLSearchParams();
  if (types) params.set('types', types);
  if (radarState.period) params.set('period', radarState.period);
  const body = document.getElementById('radarTableBody');
  // 竞态守卫：快速切换筛选时，先发的请求可能后返回，必须丢弃过期响应，避免旧结果覆盖新筛选
  const requestId = ++radarState.requestId;
  try {
    const resp = await fetch(`/api/chanlun/radar?${params.toString()}`, { cache: 'no-store' });
    const json = await resp.json();
    if (requestId !== radarState.requestId) return;
    if (json.code !== 200) throw new Error(json.message || '雷达池读取失败');
    radarState.signals = json.data || [];
    radarState.snapshot = json.snapshot || null;
    radarState.scan = json.scan || null;
    renderRadarSnapshot();
    renderRadarTable();
    if (radarState.scan && radarState.scan.status === 'running') startRadarPolling();
  } catch (err) {
    if (requestId !== radarState.requestId) return;
    if (body) {
      body.innerHTML = `<tr><td colspan="10" class="empty-cell">雷达池读取失败：${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

/** 邻近性：快照条紧贴筛选区之上，集中呈现口径与计数 */
function renderRadarSnapshot() {
  const el = document.getElementById('radarSnapshotText');
  if (!el) return;
  const snap = radarState.snapshot;
  if (!snap || !snap.total) {
    el.textContent = '雷达池为空。尚未运行扫描，或本次扫描未命中任何符合条件的买卖点。';
    return;
  }
  const typeText = Object.entries(snap.by_signal_type || {})
    .map(([k, v]) => `${k} ${v}`).join(' · ') || '无';
  el.textContent = `共 ${snap.total} 条结构化信号（${typeText}）；其中区间套共振 ${snap.resonance_count} 条。`
    + `计算时间 ${snap.computed_at || '未获取'}。日线 ${((snap.by_period || {}).daily) || 0} 条 · 30分钟 ${((snap.by_period || {}).m30) || 0} 条。`;
}

function radarFilteredSignals() {
  let list = radarState.signals || [];
  if (radarState.resonanceOnly) list = list.filter(s => s.resonance === true);
  if (radarState.actionableOnly) list = list.filter(s => s.actionable === true);
  return list;
}

function renderRadarTable() {
  const body = document.getElementById('radarTableBody');
  const counter = document.getElementById('radarResultCount');
  if (!body) return;
  const list = radarFilteredSignals();
  if (counter) counter.textContent = `${list.length} 条`;
  if (list.length === 0) {
    const why = (radarState.signals || []).length > 0
      ? '当前筛选条件下没有信号，请放宽「仅看区间套共振 / 仅看可执行信号」或类型筛选。'
      : '雷达池中暂无该类型/周期的信号。注意：池中无记录可能因为来源未获取，不等于该证券没有风险，也不等于无信号。';
    body.innerHTML = `<tr><td colspan="10" class="empty-cell">${why}</td></tr>`;
    return;
  }
  body.innerHTML = list.map(s => {
    const meta = RADAR_TYPE_META[s.signal_type] || { name: s.signal_type, side: s.side };
    const sideClass = s.side === 'buy' ? 'is-buy' : 'is-sell';
    const periodText = s.period === 'daily' ? '日线' : (s.period === 'm30' ? '30分钟' : s.period);
    const resonanceTag = s.resonance === true
      ? '<span class="radar-tag is-resonance" title="30分钟信号落在同向日线结构区间内">区间套共振</span>'
      : (s.resonance === false ? '<span class="radar-tag is-single" title="未落在同向日线结构区间内，已降级">单周期·已降级</span>' : '');
    const statusTag = s.status === 'confirmed'
      ? '<span class="audit-status-pill audit-status-success">已确认</span>'
      : '<span class="audit-status-pill audit-status-warn">待确认</span>';
    const targetText = s.target_price == null
      ? '<span class="radar-missing" title="结构上没有可依据的中枢边界，按真实数据原则不臆造目标位">未获取</span>'
      : `¥${formatReal(s.target_price)}`;
    const sharesText = s.actionable
      ? `${formatReal(s.suggested_shares, 0)} 股`
      : `<span class="radar-blocked" title="${escapeHtml(s.risk_budget_note || '未给出建议仓位')}">不可执行</span>`;
    const riskText = s.risk_pct == null ? '<span class="radar-missing">未获取</span>'
      : (s.risk_pct < 0 ? `<span class="radar-blocked">${formatReal(s.risk_pct)}%</span>` : `${formatReal(s.risk_pct)}%`);
    const structureText = (s.structure || []).map(p => {
      const arrow = p.direction === 1 ? '↗' : '↘';
      return `<span class="radar-struct-pen">${arrow} ${escapeHtml(String(p.end_time).slice(0, 10))} ¥${formatReal(p.end_price)}</span>`;
    }).join('');
    return `
      <tr class="radar-row">
        <td><span class="radar-point-badge ${sideClass}" title="${escapeHtml(meta.name || '')} · ${escapeHtml(s.rule || '')}">${s.signal_type}</span></td>
        <td>${periodText}</td>
        <td>${escapeHtml(s.name || '')} <code class="radar-code">${escapeHtml(s.code || '')}</code></td>
        <td>¥${formatReal(s.entry_price)}</td>
        <td>¥${formatReal(s.stop_price)}</td>
        <td>${riskText}</td>
        <td>${targetText}</td>
        <td>${sharesText}</td>
        <td>${statusTag}<br>${resonanceTag}</td>
        <td class="radar-reason-cell">
          <div class="radar-reason">${escapeHtml(s.reason || '')}</div>
          <div class="radar-structure">${structureText}</div>
        </td>
      </tr>
    `;
  }).join('');
}

async function triggerRadarScan() {
  const btn = document.getElementById('btnRadarScan');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 扫描中…'; }
  try {
    const resp = await fetch('/api/chanlun/radar/scan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    const json = await resp.json();
    if (!json.success) {
      setRadarScanHint(json.message || '扫描未能启动');
      if (btn) { btn.disabled = false; btn.textContent = '🔍 运行全池雷达扫描'; }
      return;
    }
    startRadarPolling();
  } catch (err) {
    setRadarScanHint(`扫描启动失败：${err.message}`);
    if (btn) { btn.disabled = false; btn.textContent = '🔍 运行全池雷达扫描'; }
  }
}

function setRadarScanHint(text) {
  const el = document.getElementById('radarScanHint');
  if (el) el.textContent = text || '';
}

function startRadarPolling() {
  if (radarState.scanTimer) return;
  radarState.scanTimer = setInterval(pollRadarScanStatus, 2500);
  pollRadarScanStatus();
}

async function pollRadarScanStatus() {
  try {
    const resp = await fetch('/api/chanlun/radar/scan-status', { cache: 'no-store' });
    const json = await resp.json();
    applyRadarScanState(json.scan, json.snapshot);
    if (!json.scan || json.scan.status !== 'running') {
      clearInterval(radarState.scanTimer);
      radarState.scanTimer = null;
      const btn = document.getElementById('btnRadarScan');
      if (btn) { btn.disabled = false; btn.textContent = '🔍 运行全池雷达扫描'; }
      await loadRadarPool();
    }
  } catch (err) {
    clearInterval(radarState.scanTimer);
    radarState.scanTimer = null;
    const btn = document.getElementById('btnRadarScan');
    if (btn) { btn.disabled = false; btn.textContent = '🔍 运行全池雷达扫描'; }
    setRadarScanHint(`扫描状态读取失败：${err.message}`);
  }
}

/** 只读同步一次状态，不启动轮询（进入页面时用） */
async function syncRadarScanStatus() {
  try {
    const resp = await fetch('/api/chanlun/radar/scan-status', { cache: 'no-store' });
    const json = await resp.json();
    applyRadarScanState(json.scan, json.snapshot);
    if (json.scan && json.scan.status === 'running') {
      const btn = document.getElementById('btnRadarScan');
      if (btn) { btn.disabled = true; btn.textContent = '⏳ 扫描中…'; }
      startRadarPolling();
    }
  } catch (err) { /* 状态读取失败不阻断页面 */ }
}

function applyRadarScanState(scan, snapshot) {
  if (snapshot) { radarState.snapshot = snapshot; renderRadarSnapshot(); }
  if (!scan) return;
  radarState.scan = scan;
  const total = scan.total || 0;
  const done = scan.done || 0;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : (scan.status === 'running' ? 4 : 0);
  const progress = document.getElementById('radarScanProgress');
  if (progress) progress.style.width = `${pct}%`;
  const count = document.getElementById('radarScanCount');
  if (count) count.textContent = total > 0 ? `${Math.round(pct)}%  (${done} / ${total})` : (scan.status === 'running' ? '准备中' : '0.0%');
  const dot = document.getElementById('radarPulseDot');
  if (dot) {
    dot.style.backgroundColor = scan.status === 'running' ? '#38bdf8'
      : (scan.status === 'done' ? '#4ade80' : (scan.status === 'failed' ? '#f87171' : '#94a3b8'));
  }
  const text = document.getElementById('radarScanText');
  if (text) {
    if (scan.status === 'running') text.textContent = `正在扫描 ${scan.current || ''}…`;
    else if (scan.status === 'done') text.textContent = `扫描完成于 ${scan.finished_at || ''}，命中信号 ${scan.signal_count} 条，落库 ${scan.persisted_count} 条`;
    else if (scan.status === 'failed') text.textContent = `扫描失败：${scan.error || '未知原因'}`;
    else text.textContent = '雷达池就绪，尚未运行本次会话的扫描';
  }
  const hints = [];
  if (scan.status === 'done' && (scan.failures || []).length) {
    const names = scan.failures.slice(0, 4).map(f => `${f.code}${f.name ? ' ' + f.name : ''}`).join('、');
    hints.push(`⚠️ ${scan.failures.length} 只未获取：${names}${scan.failures.length > 4 ? ' 等' : ''}。未获取不代表无信号。`);
  }
  setRadarScanHint(hints.join(' '));
}

/* ==========================================================================
 * 需求REQ-020: 策略选股与告警前端
 * 原则：命中即给出全部真实判据数值；未命中/未获取逐条说明原因；
 *       不可执行命中不展示建议股数；告警只呈现真实下发结果与脱敏目标。
 * ========================================================================== */
const screenerState = {
  strategies: [],
  strategy: 'dip-divergence-breakout',
  hits: [],
  snapshot: null,
  scan: null,
  actionableOnly: false,
  scanTimer: null,
  requestId: 0
};

function screenerParams() {
  const num = (id, fallback) => {
    const el = document.getElementById(id);
    const v = el ? Number(el.value) : NaN;
    return Number.isFinite(v) && v > 0 ? v : fallback;
  };
  return {
    volume_window: num('screenerVolWindow', 20),
    volume_ratio: num('screenerVolRatio', 1.5),
    min_breakout_pct: Number.isFinite(Number((document.getElementById('screenerBreakoutPct') || {}).value))
      ? Number(document.getElementById('screenerBreakoutPct').value) : 0.5
  };
}

function toggleScreenerActionableOnly() {
  screenerState.actionableOnly = !screenerState.actionableOnly;
  const btn = document.getElementById('screenerActionableOnly');
  if (btn) btn.classList.toggle('active', screenerState.actionableOnly);
  renderScreenerTable();
}

function renderScreenerStrategyChips() {
  const host = document.getElementById('screenerStrategyChips');
  if (!host) return;
  host.innerHTML = (screenerState.strategies || []).map(s =>
    `<button type="button" class="seg-btn ${s.key === screenerState.strategy ? 'active' : ''}"
             data-strategy="${escapeHtml(s.key)}" title="${escapeHtml(s.desc)}"
             onclick="setScreenerStrategy('${escapeHtml(s.key)}')">${escapeHtml(s.name)}</button>`
  ).join('') || '<span class="radar-missing">未获取到可用策略</span>';
}

function setScreenerStrategy(key) {
  screenerState.strategy = key;
  renderScreenerStrategyChips();
  loadScreenerResults();
}

async function loadScreenerResults() {
  const params = new URLSearchParams();
  if (screenerState.strategy) params.set('strategy', screenerState.strategy);
  const requestId = ++screenerState.requestId;
  try {
    const resp = await fetch(`/api/screener/results?${params.toString()}`, { cache: 'no-store' });
    const json = await resp.json();
    if (requestId !== screenerState.requestId) return;
    if (json.code !== 200) throw new Error(json.message || '选股结果读取失败');
    screenerState.strategies = json.strategies || [];
    screenerState.hits = json.data || [];
    screenerState.snapshot = json.snapshot || null;
    screenerState.scan = json.scan || null;
    renderScreenerStrategyChips();
    renderScreenerSnapshot();
    renderScreenerTable();
    if (screenerState.scan && screenerState.scan.status === 'running') startScreenerPolling();
  } catch (err) {
    const body = document.getElementById('screenerTableBody');
    if (body) body.innerHTML = `<tr><td colspan="10" class="empty-cell">选股结果读取失败：${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderScreenerSnapshot() {
  const el = document.getElementById('screenerSnapshotText');
  if (!el) return;
  const snap = screenerState.snapshot;
  const scan = screenerState.scan;
  if (!snap || !snap.total) {
    let text = '尚无命中记录。';
    if (scan && scan.status === 'done') {
      text += `最近一次扫描：${scan.total} 只中命中 ${scan.hit_count} 只 / 未命中 ${scan.miss_count} 只 / 未获取 ${scan.unavailable_count} 只。`;
      if (scan.unavailable_count > 0) text += ' 未获取项不等于无信号，需人工复核。';
    }
    el.textContent = text;
    return;
  }
  el.textContent = `最近一次扫描命中 ${snap.total} 条，计算时间 ${snap.computed_at || '未获取'}。`
    + (scan && scan.status === 'done'
      ? `扫描池 ${scan.total} 只：未命中 ${scan.miss_count} 只、未获取 ${scan.unavailable_count} 只。` : '');
}

function renderScreenerTable() {
  const body = document.getElementById('screenerTableBody');
  const counter = document.getElementById('screenerHitCount');
  if (!body) return;
  let list = screenerState.hits || [];
  if (screenerState.actionableOnly) list = list.filter(h => h.actionable === true);
  if (counter) counter.textContent = `${list.length} 条`;
  if (list.length === 0) {
    const scan = screenerState.scan;
    // 诚实性: 必须区分「评估后不满足判据」与「根本没能完成判定」，不得把未获取说成无命中
    let why;
    if ((screenerState.hits || []).length > 0) {
      why = '当前筛选下没有可执行命中，请关闭「仅看可执行命中」查看全部命中与其不可执行原因。';
    } else if (scan && scan.status === 'done' && scan.hit_count === 0 && scan.miss_count === 0
               && scan.unavailable_count > 0) {
      why = `本轮 ${scan.unavailable_count} 只标的全部未获取，没有任何一只完成判定，`
          + '因此这不是「无命中」而是「无结论」。请查看上方提示中的未获取原因（通常为数据来源当前不可用），稍后重试。';
    } else if (scan && scan.status === 'done' && scan.hit_count === 0) {
      why = `本轮已完整评估 ${scan.miss_count} 只，均不满足当前三条判据（另有 ${scan.unavailable_count} 只未获取）。`
          + '不满足判据不代表该证券没有机会或没有风险。';
    } else {
      why = '尚无选股结果。无命中表示不满足当前判据，不代表该证券没有机会或没有风险。';
    }
    body.innerHTML = `<tr><td colspan="10" class="empty-cell">${why}</td></tr>`;
    return;
  }
  body.innerHTML = list.map(h => {
    const ev = h.evidence || {};
    const shares = h.actionable
      ? `${formatReal(h.suggested_shares, 0)} 股`
      : `<span class="radar-blocked" title="${escapeHtml(h.risk_budget_note || '')}">不可执行</span>`;
    const riskText = h.risk_pct == null ? '<span class="radar-missing">未获取</span>'
      : (h.risk_pct < 0 ? `<span class="radar-blocked">${formatReal(h.risk_pct)}%</span>` : `${formatReal(h.risk_pct)}%`);
    return `
      <tr class="radar-row">
        <td>${escapeHtml(h.name || '')} <code class="radar-code">${escapeHtml(h.code || '')}</code></td>
        <td>${escapeHtml(h.trade_date || '')}</td>
        <td>¥${formatReal(h.close)}</td>
        <td>¥${formatReal(h.pivot_zg)}</td>
        <td>${formatReal(ev.breakout_pct)}%</td>
        <td>${formatReal(h.volume_ratio)}× <span class="radar-missing">(${formatReal(ev.volume_window, 0)}日)</span></td>
        <td>¥${formatReal(h.stop_price)}</td>
        <td>${riskText}</td>
        <td>${shares}</td>
        <td class="radar-reason-cell">
          <div class="radar-reason">${escapeHtml(h.reason || '')}</div>
          <div class="radar-structure">
            <span class="radar-struct-pen">底背离 ${escapeHtml(String(ev.divergence_time || '').slice(0, 10))} 面积比 ${formatReal(ev.divergence_area_ratio)}</span>
            <span class="radar-struct-pen">ZG ${formatReal(ev.pivot_zg)} / ZD ${formatReal(ev.pivot_zd)}</span>
            <span class="radar-struct-pen">当日量 ${formatReal(ev.volume, 0)} / ${formatReal(ev.volume_window, 0)}日均量 ${formatReal(ev.avg_volume, 0)}</span>
          </div>
        </td>
      </tr>`;
  }).join('');
}

function setScreenerScanHint(text) {
  const el = document.getElementById('screenerScanHint');
  if (el) el.textContent = text || '';
}

async function triggerScreenerScan() {
  const btn = document.getElementById('btnScreenerScan');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 选股中…'; }
  try {
    const resp = await fetch('/api/screener/scan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy: screenerState.strategy, params: screenerParams() })
    });
    const json = await resp.json();
    if (!json.success) {
      setScreenerScanHint(json.message || '选股未能启动');
      if (btn) { btn.disabled = false; btn.textContent = '🔍 运行策略选股'; }
      return;
    }
    startScreenerPolling();
  } catch (err) {
    setScreenerScanHint(`选股启动失败：${err.message}`);
    if (btn) { btn.disabled = false; btn.textContent = '🔍 运行策略选股'; }
  }
}

function startScreenerPolling() {
  if (screenerState.scanTimer) return;
  screenerState.scanTimer = setInterval(pollScreenerScanStatus, 2500);
  pollScreenerScanStatus();
}

async function syncScreenerScanStatus() {
  try {
    const resp = await fetch('/api/screener/scan-status', { cache: 'no-store' });
    const json = await resp.json();
    applyScreenerScanState(json.scan, json.snapshot);
    if (json.scan && json.scan.status === 'running') {
      const btn = document.getElementById('btnScreenerScan');
      if (btn) { btn.disabled = true; btn.textContent = '⏳ 选股中…'; }
      startScreenerPolling();
    }
  } catch (err) { /* 状态读取失败不阻断页面 */ }
}

async function pollScreenerScanStatus() {
  try {
    const resp = await fetch('/api/screener/scan-status', { cache: 'no-store' });
    const json = await resp.json();
    applyScreenerScanState(json.scan, json.snapshot);
    if (!json.scan || json.scan.status !== 'running') {
      clearInterval(screenerState.scanTimer);
      screenerState.scanTimer = null;
      const btn = document.getElementById('btnScreenerScan');
      if (btn) { btn.disabled = false; btn.textContent = '🔍 运行策略选股'; }
      await loadScreenerResults();
      await loadNotifyHistory();
    }
  } catch (err) {
    clearInterval(screenerState.scanTimer);
    screenerState.scanTimer = null;
    const btn = document.getElementById('btnScreenerScan');
    if (btn) { btn.disabled = false; btn.textContent = '🔍 运行策略选股'; }
    setScreenerScanHint(`选股状态读取失败：${err.message}`);
  }
}

function applyScreenerScanState(scan, snapshot) {
  if (snapshot) { screenerState.snapshot = snapshot; }
  if (!scan) return;
  screenerState.scan = scan;
  const total = scan.total || 0;
  const done = scan.done || 0;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : (scan.status === 'running' ? 4 : 0);
  const progress = document.getElementById('screenerScanProgress');
  if (progress) progress.style.width = `${pct}%`;
  const count = document.getElementById('screenerScanCount');
  if (count) count.textContent = total > 0 ? `${Math.round(pct)}%  (${done} / ${total})` : (scan.status === 'running' ? '准备中' : '0.0%');
  const dot = document.getElementById('screenerPulseDot');
  if (dot) {
    dot.style.backgroundColor = scan.status === 'running' ? '#38bdf8'
      : (scan.status === 'done' ? '#4ade80' : (scan.status === 'failed' ? '#f87171' : '#94a3b8'));
  }
  const text = document.getElementById('screenerScanText');
  if (text) {
    if (scan.status === 'running') text.textContent = `正在评估 ${scan.current || ''}…`;
    else if (scan.status === 'done') text.textContent = `扫描完成于 ${scan.finished_at || ''}：命中 ${scan.hit_count} / 未命中 ${scan.miss_count} / 未获取 ${scan.unavailable_count}，落库 ${scan.persisted_count} 条`;
    else if (scan.status === 'failed') text.textContent = `扫描失败：${scan.error || '未知原因'}`;
    else text.textContent = '策略选股就绪，尚未运行本次会话的扫描';
  }
  const hints = [];
  if (scan.status === 'done' && (scan.unavailable || []).length) {
    const names = scan.unavailable.slice(0, 3).map(u => `${u.code}${u.name ? ' ' + u.name : ''}`).join('、');
    hints.push(`⚠️ ${scan.unavailable.length} 只未获取：${names}${scan.unavailable.length > 3 ? ' 等' : ''}。未获取不等于无信号。`);
  }
  if (scan.notify && scan.notify.reason) hints.push(`📡 ${scan.notify.reason}`);
  if (scan.notify && scan.notify.sent) hints.push(`📡 已下发 ${scan.notify.sent} 条告警，冷却跳过 ${scan.notify.skipped || 0} 条。`);
  setScreenerScanHint(hints.join(' '));
  renderScreenerSnapshot();
}

async function loadNotifyStatus() {
  const host = document.getElementById('notifyChannelList');
  try {
    const resp = await fetch('/api/notify/status', { cache: 'no-store' });
    const json = await resp.json();
    const hint = document.getElementById('notifyStatusHint');
    if (hint) hint.textContent = json.enabled ? '总开关已启用' : '总开关未启用';
    if (!host) return;
    host.innerHTML = (json.channels || []).map(c => {
      const state = c.configured ? '已配置' : '未配置';
      const sign = c.signed ? '（含加签）' : '';
      const cls = c.configured ? 'is-on' : 'is-off';
      return `<span class="notify-chip ${cls}" title="${escapeHtml(c.configured ? c.target_hint : '未配置 Webhook，不会发送任何请求')}">${escapeHtml(c.label)}：${state}${sign}${c.configured && c.target_hint ? ' · ' + escapeHtml(c.target_hint) : ''}</span>`;
    }).join('');
  } catch (err) {
    if (host) host.innerHTML = `<span class="radar-missing">告警通道状态读取失败：${escapeHtml(err.message)}</span>`;
  }
}

async function loadNotifyHistory() {
  const body = document.getElementById('notifyHistoryBody');
  if (!body) return;
  try {
    const resp = await fetch('/api/notify/history?limit=30', { cache: 'no-store' });
    const json = await resp.json();
    const rows = json.data || [];
    if (rows.length === 0) {
      body.innerHTML = '<tr><td colspan="6" class="empty-cell">暂无下发记录。未配置通道或尚未触发告警时不会产生记录。</td></tr>';
      return;
    }
    body.innerHTML = rows.map(r => {
      const label = r.channel === 'feishu' ? '飞书' : (r.channel === 'dingtalk' ? '钉钉' : escapeHtml(r.channel));
      return `<tr class="radar-row">
        <td>${escapeHtml(r.sent_at || '')}</td>
        <td>${label}</td>
        <td>${r.ok ? '<span class="audit-status-pill audit-status-success">成功</span>' : '<span class="audit-status-pill audit-status-fail">失败</span>'}</td>
        <td>${r.status_code == null ? '<span class="radar-missing">未获取</span>' : escapeHtml(String(r.status_code))}</td>
        <td><code class="radar-code">${escapeHtml(r.target_hint || '')}</code></td>
        <td class="radar-reason-cell"><div class="radar-reason">${escapeHtml(r.error || '发送成功')}</div></td>
      </tr>`;
    }).join('');
  } catch (err) {
    body.innerHTML = `<tr><td colspan="6" class="empty-cell">下发记录读取失败：${escapeHtml(err.message)}</td></tr>`;
  }
}

/* ==========================================================================
 * 需求REQ-021: 持仓组合风险体检前端
 * 原则：未核实持仓不产出任何结论；无法判定的规则必须显示为「无法判定」而非「未触发」；
 *       体检结果是纪律触发的事实陈述，页面上不得出现任何买卖建议式措辞。
 * ========================================================================== */
const portfolioState = {
  report: null,
  triggeredOnly: false,
  riskOnly: false
};

const PORTFOLIO_RULE_LABELS = {
  S1_take_profit: '止盈达标',
  S2_stop_loss: '止损击穿',
  S3_daily_move: '日内异动',
  D1_ma_breakdown: '均线破位',
  D2_chanlun_sell: '日线卖点',
  D3_trailing_stop: '移动止盈回撤'
};

function togglePortfolioTriggeredOnly() {
  portfolioState.triggeredOnly = !portfolioState.triggeredOnly;
  document.getElementById('portfolioTriggeredOnly').classList.toggle('active', portfolioState.triggeredOnly);
  renderPortfolioTable();
}

function togglePortfolioRiskOnly() {
  portfolioState.riskOnly = !portfolioState.riskOnly;
  document.getElementById('portfolioRiskOnly').classList.toggle('active', portfolioState.riskOnly);
  renderPortfolioTable();
}

async function loadPortfolioCheckup() {
  const body = document.getElementById('portfolioTableBody');
  if (body) body.innerHTML = '<tr><td colspan="9" class="empty-cell">正在读取持仓体检结果…</td></tr>';
  try {
    const resp = await fetch('/api/portfolio/checkup', { cache: 'no-store' });
    const json = await resp.json();
    portfolioState.report = json;
    renderPortfolioGate();
    renderPortfolioSummary();
    renderPortfolioTable();
  } catch (err) {
    if (body) body.innerHTML = `<tr><td colspan="9" class="empty-cell">体检读取失败：${escapeHtml(err.message)}</td></tr>`;
  }
}

/** 未核实持仓时，界面明确说明门禁原因，而不是显示 0 盈亏这类会被误读的数字 */
function renderPortfolioGate() {
  const report = portfolioState.report || {};
  const bar = document.getElementById('portfolioGateBar');
  const text = document.getElementById('portfolioGateText');
  const blocked = report.status === 'unverified' || report.status === 'error';
  if (bar) bar.style.display = blocked ? '' : 'none';
  if (text) {
    text.textContent = blocked
      ? `${report.reason || '持仓底册未核实'}（底册声明条数：${report.portfolio_declared_count == null ? '未获取' : report.portfolio_declared_count}，未计入任何统计）`
      : '';
  }
  return blocked;
}

function renderPortfolioSummary() {
  const bar = document.getElementById('portfolioSummaryBar');
  const text = document.getElementById('portfolioSummaryText');
  const report = portfolioState.report || {};
  const s = report.summary || {};
  if (!bar || !text) return;
  if (report.status !== 'available' || !s.position_count) {
    bar.style.display = 'none';
    const status = document.getElementById('portfolioDataStatus');
    if (status) status.textContent = report.status === 'available' ? '无可体检持仓' : '等待持仓核实';
    return;
  }
  bar.style.display = '';
  text.textContent = `持仓 ${s.position_count} 只（跳过 ${s.skipped_count} 只）· `
    + `市值 ${formatReal(s.total_market_value)} · 成本 ${formatReal(s.total_cost)} · `
    + `浮动盈亏 ${formatReal(s.total_floating_pnl)}（${formatReal(s.total_floating_pnl_pct)}%）· `
    + `当日盈亏 ${formatReal(s.today_floating_pnl)} · 触发规则 ${s.triggered_count} 条`
    + `（危险 ${s.danger_count} / 警示 ${s.warning_count}）· 无法判定 ${s.unavailable_count} 条`;
  const status = document.getElementById('portfolioDataStatus');
  if (status) {
    const stale = (report.positions || []).filter(p => p.data_status !== 'available').length;
    status.textContent = stale
      ? `${stale} 只持仓的日线并非最新（来源当前不可用），已使用此前核验过的真实历史`
      : '全部持仓日线数据为最新';
    status.className = stale ? 'radar-blocked' : 'radar-missing';
  }
}

function portfolioFilteredPositions() {
  let list = (portfolioState.report || {}).positions || [];
  if (portfolioState.riskOnly) {
    list = list.map(p => ({ ...p, rules: (p.rules || []).filter(r => r.triggered && (r.level === 'DANGER' || r.level === 'WARNING')) }))
               .filter(p => p.rules.length > 0);
  } else if (portfolioState.triggeredOnly) {
    list = list.map(p => ({ ...p, rules: (p.rules || []).filter(r => r.triggered) }))
               .filter(p => p.rules.length > 0);
  }
  return list;
}

function renderPortfolioRuleRow(rule) {
  let icon = '⚪';
  if (rule.status === 'unavailable') icon = '❓';
  else if (rule.status === 'disabled') icon = '⏸';
  else if (rule.triggered && rule.level === 'DANGER') icon = '🔴';
  else if (rule.triggered && rule.level === 'WARNING') icon = '🟡';
  else if (rule.triggered && rule.level === 'SUCCESS') icon = '🟢';
  // 配色必须区分「危险 / 警示 / 达标 / 未触发 / 无法判定」五种语义。
  // 早期实现把所有非 DANGER 的已触发规则都涂成警示色，会把「止盈达标」误报为风险信号。
  let cls = 'is-idle';
  if (rule.status === 'unavailable') cls = 'is-unavailable';
  else if (rule.status === 'disabled') cls = 'is-disabled';
  else if (!rule.triggered) cls = 'is-idle';
  else if (rule.level === 'DANGER') cls = 'is-danger';
  else if (rule.level === 'WARNING') cls = 'is-warn';
  else if (rule.level === 'SUCCESS') cls = 'is-success';
  else cls = 'is-info';
  return `<div class="pf-rule ${cls}">
    <span class="pf-rule-id">${icon} ${escapeHtml(PORTFOLIO_RULE_LABELS[rule.rule_id] || rule.rule_id)}</span>
    <span class="pf-rule-detail">${escapeHtml(rule.detail || '')}</span>
  </div>`;
}

function renderPortfolioTable() {
  const body = document.getElementById('portfolioTableBody');
  const counter = document.getElementById('portfolioPositionCount');
  if (!body) return;
  if (renderPortfolioGate()) {
    // 空底册与「已填但未核实」是两种不同情形，引导动作也不同，不得套用同一句话
    const report = portfolioState.report || {};
    const empty = (report.portfolio_declared_count || 0) === 0;
    const guidance = empty
      ? '请先在 config/stock_config.json 的 portfolio 中填写持仓的代码、股数、成本价与买入日期，并将 portfolio_verified 置为 true。'
      : '请先核实每条持仓的代码、股数、成本价与买入日期，确认无误后由持仓本人将 portfolio_verified 置为 true。';
    body.innerHTML = `<tr><td colspan="9" class="empty-cell">持仓底册未核实，本页不产出任何盈亏或风险结论。${guidance}</td></tr>`;
    if (counter) counter.textContent = '0 只';
    return;
  }
  const list = portfolioFilteredPositions();
  if (counter) counter.textContent = `${list.length} 只`;
  if (list.length === 0) {
    body.innerHTML = `<tr><td colspan="9" class="empty-cell">${
      ((portfolioState.report || {}).positions || []).length > 0
        ? '当前筛选下没有匹配的持仓，请关闭筛选查看全部。'
        : (portfolioState.report || {}).reason || '暂无可体检持仓。'}</td></tr>`;
    return;
  }
  body.innerHTML = list.map(p => {
    const pnlCls = (p.total_pnl || 0) >= 0 ? 'pf-up' : 'pf-down';
    const dayCls = (p.daily_pnl || 0) >= 0 ? 'pf-up' : 'pf-down';
    const levelTag = p.highest_level === 'DANGER'
      ? '<span class="audit-status-pill audit-status-fail">危险</span>'
      : (p.highest_level === 'WARNING' ? '<span class="audit-status-pill audit-status-warn">警示</span>'
        : (p.highest_level === 'SUCCESS' ? '<span class="audit-status-pill audit-status-success">达标</span>'
          : '<span class="audit-status-pill">未触发</span>'));
    const triggeredText = (p.triggered_rules || []).length
      ? (p.triggered_rules || []).map(r => PORTFOLIO_RULE_LABELS[r] || r).join('、')
      : '无';
    const staleNote = p.data_status !== 'available'
      ? `<div class="pf-stale">⚠️ 日线数据状态 ${escapeHtml(p.data_status)}（最后一根 ${escapeHtml(p.data_last_bar_date || '未获取')}）</div>` : '';
    return `
      <tr class="radar-row">
        <td>${escapeHtml(p.name || '')} <code class="radar-code">${escapeHtml(p.code || '')}</code>
            <div class="radar-missing">${escapeHtml(p.buy_date || '未填写买入日期')}</div></td>
        <td>${formatReal(p.shares, 0)} 股<br><span class="radar-missing">¥${formatReal(p.cost_price)}</span></td>
        <td>¥${formatReal(p.current_price)}</td>
        <td>¥${formatReal(p.market_value)}</td>
        <td>${formatReal(p.weight_pct)}%</td>
        <td class="${pnlCls}">¥${formatReal(p.total_pnl)}<br>${formatReal(p.total_pnl_pct)}%</td>
        <td class="${dayCls}">¥${formatReal(p.daily_pnl)}<br>${formatReal(p.daily_pnl_pct)}%</td>
        <td>${levelTag}<div class="radar-reason">${escapeHtml(triggeredText)}</div></td>
        <td class="radar-reason-cell">
          ${(p.rules || []).map(renderPortfolioRuleRow).join('')}
          ${staleNote}
        </td>
      </tr>`;
  }).join('');
}
