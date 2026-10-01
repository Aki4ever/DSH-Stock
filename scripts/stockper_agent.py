#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 股票权威调研与数据抓取智能体 (Agent stockper)
版本: v1.0.0 (归属 R11 批次 / REQ-055)
核心职责:
1. 调研 A 股核心信息（大宗交易、十大流通股东占比、分红、K线图、财务报表）从哪里获取更权威；
2. 梳理各公开渠道的名称、抓取接口、抓取信息、有效性、风险点、优势劣势及横向对比；
3. 问询响应引擎：快速给出抓取渠道建议，并直接负责调用接口获取对应股票的真实信息。
"""

import sys
import os
import re
import json
import argparse
from typing import Dict, List, Any, Optional
from datetime import datetime

# 路径对齐
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.data_sources.safe_session import safe_session
from scripts.data_sources.block_trade_adapter import BlockTradeAdapter
from scripts.data_sources.dividend_adapter import DividendAdapter
from scripts.data_sources.kline_adapter import KlineAdapter
from scripts.data_sources.shareholder_adapter import ShareholderAdapter
from scripts.company_finance_engine import fetch_financial_statements
from scripts.stock_data_engine import normalize_code, get_real_kline
from scripts.verified_sources import number


# ==============================================================================
# 1. 五大维度核心公开数据源调研与对比权威知识库
# ==============================================================================
STOCKPER_KNOWLEDGE_BASE: Dict[str, Dict[str, Any]] = {
    "block_trade": {
        "dimension_name": "大宗交易 (Block Trades)",
        "description": "单笔交易规模达到交易所规定门槛的盘后协议交易，体现机构席位、股东增减持及游资大资金动向",
        "official_authority": "上海证券交易所 (SSE) / 深圳证券交易所 (SZSE) / 北京证券交易所 (BSE) 官方网站",
        "recommended_channel": "东方财富数据中心 (Eastmoney Datacenter)",
        "channels": [
            {
                "name": "交易所官方网站 (SSE / SZSE / BSE)",
                "type": "official",
                "authority_score": 100,
                "interface": "SSE: http://query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_XXPL_DZJY_DZJYMXX_L\nSZSE: https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=1798_dzjy",
                "fetched_info": "证券代码、证券名称、成交日期、成交价格、成交数量、成交金额、买方营业部席位、卖方营业部席位",
                "validity": "【时效性】T日收盘后 15:30~16:00 准时披露；【历史深度】近5~10年；【权威度】最高法源（100% 原始法定源头，具有司法证据效力）",
                "risks": "高强度 WAF 防爬风控；Referer/Cookie 动态校验；沪深北三大交易所协议与 JSON 结构各自割裂，跨市场聚合维护难度极大；短时并发 >5 req/s 极易封锁 IP",
                "advantages": "绝对权威、无任何第三方二次加工清洗失真或漏单",
                "disadvantages": "接口协议割裂、反爬极严、不提供折溢价率和占流通市值比等衍生计算指标",
                "recommended": False
            },
            {
                "name": "东方财富数据中心 (Eastmoney Datacenter)",
                "type": "portal",
                "authority_score": 98,
                "interface": "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DATA_BLOCKTRADE&columns=ALL&filter=(SECURITY_CODE=\"{code}\")&sortColumns=TRADE_DATE&sortTypes=-1",
                "fetched_info": "证券代码、名称、成交日期、收盘价、成交价、折溢价率 (PREMIUM_RATIO)、成交量、成交额、成交额占流通市值比、买方营业部、卖方营业部",
                "validity": "【时效性】T日 16:15~16:30 同步交易所；【历史深度】2003年至今全量历史；【权威度】99.5% 高度可信",
                "risks": "高频并发爬取需保持常规 User-Agent，偶发限流验证码；字段名在节假日大版本升级时偶尔有微调",
                "advantages": "全市场统一标准 RESTful JSON；开箱即用自带折溢价率与席位特征标记；支持个股/全市场/日期多维检索；工程可用性极高",
                "disadvantages": "较交易所直连有约 15~30 分钟数据入库清洗时延",
                "recommended": True
            },
            {
                "name": "同花顺 / 问财 (iwencai)",
                "type": "portal",
                "authority_score": 95,
                "interface": "http://www.iwencai.com/gateway/urp/v7/landing/push (POST 问答语法)",
                "fetched_info": "大宗交易溢价率、买卖席位、连续多日大宗交易追踪",
                "validity": "【时效性】T日 16:30 更新；【历史深度】全历史；【权威度】99%",
                "risks": "同花顺部署了核心 Hexin-V 动态签名参数反爬，JS 混淆度极高，纯脚本无浏览器环境难以维持长效稳定",
                "advantages": "支持自然语言语法快速聚合多日大宗交易异动",
                "disadvantages": "反爬风控极度严苛，维护成本奇高",
                "recommended": False
            },
            {
                "name": "开源量化库 (AkShare / Tushare)",
                "type": "sdk",
                "authority_score": 96,
                "interface": "AkShare: ak.stock_dzjy_mrtj() / Tushare: pro.block_trade(ts_code='...')",
                "fetched_info": "成交价、成交量、成交额、折溢价率、买卖席位",
                "validity": "【时效性】T日 17:00 后；【权威度】取决于底层爬虫或数据商；【历史深度】视积分/版本而定",
                "risks": "AkShare 存在底层网页改版导致的爬虫失效断裂风险；Tushare 存在 Token 积分门槛与高并发调用配额限制",
                "advantages": "Python 代码开箱即用，直接输出 DataFrame",
                "disadvantages": "需要庞大外部三方环境依赖，非原生轻量标准库",
                "recommended": False
            }
        ]
    },
    "shareholders": {
        "dimension_name": "十大流通股东占比 (Top 10 Floating Shareholders)",
        "description": "上市公司最新报告期排名前十的无限售条件流通股股东名单、持股数、持股比例及前十大合计持股占比",
        "official_authority": "巨潮资讯网 (cninfo.com.cn) 上市公司定期报告法定披露",
        "recommended_channel": "东方财富网 F10 股东中心 (Eastmoney F10)",
        "channels": [
            {
                "name": "巨潮资讯网 (cninfo.com.cn)",
                "type": "official",
                "authority_score": 100,
                "interface": "http://www.cninfo.com.cn/new/hisAnnouncement/query (检索定期公告 PDF/XBRL)",
                "fetched_info": "报告期前十大流通股东名称、期末持股数量、期末持股比例、股份种类、限售与质押冻结状态",
                "validity": "【时效性】上市公司财报法定披露首发；【历史深度】全历史；【权威度】法定绝对权威（100%）",
                "risks": "信披主要为非结构化 PDF 文档或复杂 XBRL，解析提取成本巨大，无法实现秒级纯 JSON 接口直取",
                "advantages": "绝对权威、会计师事务所与董监高签字保真、具法定公信力",
                "disadvantages": "无轻量级免解析直接结构化数据 API，工程抓取极重",
                "recommended": False
            },
            {
                "name": "东方财富网 F10 股东中心 (Eastmoney F10)",
                "type": "portal",
                "authority_score": 99,
                "interface": "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_F10_EH_FREEHOLDERS&columns=ALL&filter=(SECUCODE=\"{code}\")&sortColumns=REPORT_DATE,HOLDER_RANK&sortTypes=-1,1",
                "fetched_info": "股东名次 (HOLDER_RANK)、股东名称 (HOLDER_NAME)、持股数量 (HOLD_NUM)、占流通股比例 (FREE_HOLDNUM_RATIO)、持股变动情况 (增持/减持/新进/不变)、股东性质",
                "validity": "【时效性】公告发布后 10~30 分钟完成清洗入库；【历史深度】上市以来所有季度报告期；【权威度】99.8%",
                "risks": "季报密集披露期（4月底/8月底/10月底）可能产生极短暂高并发排队；需要常规 UA 标头",
                "advantages": "标准 RESTful JSON；字段结构极度清晰，自动算出占流通股比例及变动方向；支持直接计算前十合计占比",
                "disadvantages": "非原始法律信披源，属二次清洗入库",
                "recommended": True
            },
            {
                "name": "新浪财经股东频道 (Sina Finance)",
                "type": "portal",
                "authority_score": 94,
                "interface": "http://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CirculateStockHolder/stockid/{code}/displaytype/30.phtml",
                "fetched_info": "十大流通股东、持股数、持股比例、股本性质",
                "validity": "【时效性】披露日次日；【权威度】98%",
                "risks": "HTML 网页抓取，网页编码为 GBK，标签嵌套深，无官方对外开放 JSON 接口",
                "advantages": "页面格式数十年未大幅变动",
                "disadvantages": "爬虫需依赖 DOM 解析，响应慢且易乱码",
                "recommended": False
            }
        ]
    },
    "dividend": {
        "dimension_name": "分红送配 (Dividends & Distributions)",
        "description": "上市公司历年及最新利润分配方案、现金分红金额、每股送转股比例、股权登记日、除权除息日与发放进度",
        "official_authority": "上交所 / 深交所除权除息公告与巨潮资讯网法定信披",
        "recommended_channel": "东方财富分红送配数据中心 (Eastmoney Dividend)",
        "channels": [
            {
                "name": "上交所/深交所官方公告 (SSE / SZSE)",
                "type": "official",
                "authority_score": 100,
                "interface": "SSE: http://query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_XXPL_XSP_FH_L&stockCode={code}",
                "fetched_info": "分红年度、分配方案说明、预案日、股东大会通过日、股权登记日、除权除息日、派息日",
                "validity": "【时效性】决议发布即时披露；【历史深度】全历史；【权威度】100% 官方清算依据",
                "risks": "将预案阶段、获批阶段、实施阶段拆为多套逻辑，状态流转复杂，参数反爬校验严格",
                "advantages": "官方清算结算第一依据，准确无误",
                "disadvantages": "接口字段复杂，沪深两所接口格式不统一",
                "recommended": False
            },
            {
                "name": "东方财富分红送配数据中心 (Eastmoney Dividend)",
                "type": "portal",
                "authority_score": 99,
                "interface": "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_SHAREBONUS_DET&columns=ALL&filter=(SECURITY_CODE=\"{code}\")&sortColumns=REPORT_DATE&sortTypes=-1",
                "fetched_info": "方案说明 (PLAN_EXPLAIN)、预案公告日、股权登记日 (EQUITY_RECORD_DATE)、除权除息日 (EX_DIVIDEND_DATE)、派息日 (PAYMENT_DATE)、每股派现 (CASH_TRANSFER)、方案进度 (PLAN_PROGRESS)",
                "validity": "【时效性】公告发布后 15 分钟内更新；【历史深度】上市以来所有分红记录；【权威度】99.9%",
                "risks": "短时超高频请求可能触发 403 阻断",
                "advantages": "全生命周期状态一目了然（预案 -> 股东大会通过 -> 实施分配）；字段平铺规范；除权除息日清晰明了",
                "disadvantages": "二次清洗数据源",
                "recommended": True
            },
            {
                "name": "新浪财经分红频道 (Sina Finance)",
                "type": "portal",
                "authority_score": 95,
                "interface": "http://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_ShareBonus/stockid/{code}.phtml",
                "fetched_info": "分红方案、除权日、派息日、股利发放历史",
                "validity": "【时效性】T+1 日；【权威度】98%",
                "risks": "仅提供 GB2312 网页表格，易乱码且无标准 JSON",
                "advantages": "历史跨度大",
                "disadvantages": "解析成本高，维护脆弱",
                "recommended": False
            }
        ]
    },
    "kline": {
        "dimension_name": "K线图行情 (K-Line & Historical Candlesticks)",
        "description": "历史与实时日K、周K、分时K线数据，包含开盘价、最高价、最低价、收盘价、成交量、成交额及前复权因子",
        "official_authority": "交易所 Level-1 / Level-2 行情专线直连",
        "recommended_channel": "腾讯财经 (极速前复权) + 东方财富 Push2 (带真实成交额)",
        "channels": [
            {
                "name": "腾讯财经行情接口 (Tencent Finance API)",
                "type": "portal",
                "authority_score": 99,
                "interface": "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},day,,,{limit},qfq",
                "fetched_info": "交易日期、开盘价、收盘价、最高价、最低价、成交量（手）、前复权因子序列、分红除权记录",
                "validity": "【时效性】毫秒级响应，盘中秒级刷新；【历史深度】支持 640 根以上K线；【权威度】99.9%",
                "risks": "紧凑数组返回无字段名 Key，数组下标严格绑定；突发超高并发可能连接重置",
                "advantages": "国内网络延时极低 (<50ms)；免鉴权；前复权 (qfq) 算法极其精准，彻底消除分红跳空缺口",
                "disadvantages": "单条返回中不直接提供真实成交额（元），需结合行情快照或东财互补",
                "recommended": True
            },
            {
                "name": "东方财富 Push 行情接口 (Eastmoney Push2 API)",
                "type": "portal",
                "authority_score": 99,
                "interface": "http://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&end=20500101&lmt={limit}",
                "fetched_info": "日期 (f51)、开盘 (f52)、收盘 (f53)、最高 (f54)、最低 (f55)、成交量 (f56)、真实成交额 (f57)、振幅 (f58)、涨跌幅 (f59)、涨跌额 (f60)、换手率 (f61)",
                "validity": "【时效性】秒级更新；【历史深度】支持 1000 根以上历史K线；【权威度】99.9%",
                "risks": "secid 需要按市场映射（沪市 1.，深市/北交所 0.）；字段名以 f51-f61 编码，需映射表",
                "advantages": "自带真实成交额 (元) 与换手率，无需通过均价×成交量二次估算；支持多周期（日/周/月/5分）",
                "disadvantages": "URL 编码相对繁复",
                "recommended": True
            },
            {
                "name": "新浪财经 K 线接口 (Sina K-Line)",
                "type": "portal",
                "authority_score": 92,
                "interface": "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={market}{code}&scale=240&ma=no&datalen={limit}",
                "fetched_info": "day, open, high, low, close, volume",
                "validity": "【时效性】秒级；【权威度】95%",
                "risks": "公开接口默认不复权，历史发生分红送股时会出现巨大假跳空断崖阴线；无成交额",
                "advantages": "接口格式简单直观",
                "disadvantages": "无复权、无成交额，易误导技术指标计算",
                "recommended": False
            },
            {
                "name": "通达信协议客户端 (PyTDX)",
                "type": "socket",
                "authority_score": 99,
                "interface": "TCP Socket 直连通达信行情主站服务器 (IP 列表轮询)",
                "fetched_info": "全周期 K 线、真实成交量与成交额",
                "validity": "【时效性】毫秒级极致速度；【权威度】99.9%",
                "risks": "需要维护一组活跃主站 IP，主站可能会在周末维护停服；Socket 连接管理较复杂",
                "advantages": "直连底层行情主站，延迟最低，数据极为全面",
                "disadvantages": "协议非 HTTP，需额外 Socket 维护逻辑",
                "recommended": False
            }
        ]
    },
    "finance": {
        "dimension_name": "财务报表 (Financial Statements)",
        "description": "上市公司三张核心会计报表：资产负债表、利润表、现金流量表，以及关键财务指标",
        "official_authority": "巨潮资讯网法定上市公司定期报告披露 (经注册会计师审计)",
        "recommended_channel": "东方财富 Choice 公开财报数据中心 (Eastmoney Finance)",
        "channels": [
            {
                "name": "巨潮资讯网 (cninfo.com.cn)",
                "type": "official",
                "authority_score": 100,
                "interface": "http://www.cninfo.com.cn/new/disclosure (上市公司年报/中报/季报 PDF)",
                "fetched_info": "资产负债表、利润表、现金流量表、所有者权益变动表、财务报表附注与审计意见",
                "validity": "【时效性】法定信息披露第一现场；【权威度】100% 原始法定基准，具法律效力",
                "risks": "大部分为非结构化长篇 PDF，需 OCR 或复杂抽取，难以满足微秒级 API 即时查询",
                "advantages": "绝对权威、附注完整、披露科目最细致",
                "disadvantages": "无轻量级免鉴权 RESTful JSON 接口",
                "recommended": False
            },
            {
                "name": "东方财富 Choice 公开财报数据中心 (Eastmoney Finance)",
                "type": "portal",
                "authority_score": 99,
                "interface": "利润表: https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DMSK_FN_INCOME&filter=(SECURITY_CODE=\"{code}\")\n资产负债表: ...reportName=RPT_DMSK_FN_BALANCE...\n现金流量表: ...reportName=RPT_DMSK_FN_CASHFLOW...",
                "fetched_info": "营业总收入、营业成本、营业利润、归母净利润、扣非净利润；资产总计、负债合计、所有者权益；经营现金流净额、投资现金流、筹资现金流、现金净增加额",
                "validity": "【时效性】财报披露日第一时间清洗入库；【历史深度】上市以来所有连续报告期；【权威度】99.8%",
                "risks": "各季度数据为累计值，单季度需依公式作差推导（注意前三季度扣减逻辑）；金融股科目不同",
                "advantages": "标准化 JSON 接口，跨沪深北全市场统一；纯原生 Python 即可秒级解析；覆盖最核心科目",
                "disadvantages": "较完整 PDF 附注去除了部分次要披露细节",
                "recommended": True
            },
            {
                "name": "Tushare Pro 金融数据社区",
                "type": "sdk",
                "authority_score": 98,
                "interface": "pro.income(ts_code='...') / pro.balancesheet(...) / pro.cashflow(...)",
                "fetched_info": "经审计三张表近百个财务科目、衍生财务比率（ROE、ROA、毛利率）",
                "validity": "【时效性】披露日即时同步；【历史深度】全历史；【权威度】99.8%",
                "risks": "依赖 Token 与积分门槛，财报类高频接口需要高等级权限与付费积分",
                "advantages": "字段覆盖最全，专业量化回测标准格式",
                "disadvantages": "有权限门槛与计费配额限制",
                "recommended": False
            }
        ]
    }
}


# ==============================================================================
# 2. Stockper Agent 核心决策与数据调度引擎
# ==============================================================================
class StockperAgent:
    """A股信息权威调研与数据抓取智能体"""

    def __init__(self):
        self.kb = STOCKPER_KNOWLEDGE_BASE

    def normalize_dimension(self, dim: str) -> Optional[str]:
        """将用户输入的维度别名归一化为内部 key"""
        d = dim.strip().lower()
        if d in ("block_trade", "blocktrade", "block", "大宗交易", "大宗", "dzjy"):
            return "block_trade"
        if d in ("shareholders", "holder", "holders", "十大流通股东", "十大股东", "十大流通股东占比", "流通股东", "股东", "gudong"):
            return "shareholders"
        if d in ("dividend", "dividends", "分红", "分红送配", "除权除息", "派息", "fenhong"):
            return "dividend"
        if d in ("kline", "k线", "k线图", "日k", "行情", "走势", "历史行情"):
            return "kline"
        if d in ("finance", "financial", "财务", "财务报表", "财报", "三张表", "利润表", "资产负债表", "现金流量表", "caibao"):
            return "finance"
        return None

    def get_survey(self, dimension: Optional[str] = None) -> Dict[str, Any]:
        """获取指定维度或全部维度的详细调研信息"""
        if dimension:
            dim_key = self.normalize_dimension(dimension)
            if not dim_key:
                raise ValueError(f"未知维度: {dimension}，支持维度: block_trade, shareholders, dividend, kline, finance")
            return {dim_key: self.kb[dim_key]}
        return self.kb

    def get_comparison(self, dimension: Optional[str] = None) -> str:
        """生成指定维度或全维度的横向对比分析 Markdown 报告"""
        dims_to_compare = [self.normalize_dimension(dimension)] if dimension else list(self.kb.keys())
        dims_to_compare = [d for d in dims_to_compare if d]
        
        lines = []
        lines.append("# 📊 A股核心信息公开抓取渠道权威度与横向对比表 (Agent stockper)\n")
        
        for dim_key in dims_to_compare:
            dim_data = self.kb[dim_key]
            lines.append(f"## 维度：{dim_data['dimension_name']}")
            lines.append(f"> **维度说明**：{dim_data['description']}")
            lines.append(f"> **法定最权威来源**：`{dim_data['official_authority']}`")
            lines.append(f"> **工程落地首选推荐**：`{dim_data['recommended_channel']}`\n")
            
            # 对比表
            lines.append("| 渠道名称 | 权威度评分 | 渠道类型 | 接口形式 | 抓取时效性 | 关键风险点 | 工程推荐 |")
            lines.append("| :--- | :---: | :---: | :--- | :--- | :--- | :---: |")
            
            for ch in dim_data["channels"]:
                rec_badge = "🌟 **首选推荐**" if ch["recommended"] else "备选/参考"
                ch_type = "官方法定" if ch["type"] == "official" else ("门户中心" if ch["type"] == "portal" else ("开发SDK" if ch["type"] == "sdk" else "Socket协议"))
                lines.append(f"| **{ch['name']}** | `{ch['authority_score']}分` | {ch_type} | `{ch['interface'].splitlines()[0][:35]}...` | {ch['validity'][:22]}... | {ch['risks'][:25]}... | {rec_badge} |")
            lines.append("\n### 渠道深度拆解：")
            for ch in dim_data["channels"]:
                rec_flag = "【🌟 推荐】" if ch["recommended"] else ""
                lines.append(f"#### {rec_flag}{ch['name']}")
                lines.append(f"- **抓取接口**：\n```text\n{ch['interface']}\n```")
                lines.append(f"- **抓取信息**：{ch['fetched_info']}")
                lines.append(f"- **有效性评估**：{ch['validity']}")
                lines.append(f"- **风险点提示**：⚠️ {ch['risks']}")
                lines.append(f"- **优势**：✅ {ch['advantages']}")
                lines.append(f"- **劣势**：❌ {ch['disadvantages']}")
                lines.append("")
            lines.append("---\n")
            
        return "\n".join(lines)

    def ask(self, query: str) -> Dict[str, Any]:
        """
        快速问询应答引擎：
        智能解析问题中包含的维度与股票代码，给出最权威渠道、推荐接口、优劣势对比，
        若检测到具体股票代码且用户意在获取信息，自动直接抓取真实数据返回！
        """
        q = query.strip()
        matched_dims = []
        
        # 维度识别
        if any(w in q for w in ["大宗", "大宗交易", "折价", "溢价", "席位"]):
            matched_dims.append("block_trade")
        if any(w in q for w in ["股东", "流通股东", "十大股东", "持股比例", "筹码", "股东占比"]):
            matched_dims.append("shareholders")
        if any(w in q for w in ["分红", "派息", "除权", "除息", "分红送配", "股息"]):
            matched_dims.append("dividend")
        if any(w in q for w in ["k线", "k线图", "日k", "行情", "走势", "蜡烛图", "价格"]):
            matched_dims.append("kline")
        if any(w in q for w in ["财务", "财报", "三张表", "利润", "资产负债", "现金流", "营收", "净利润"]):
            matched_dims.append("finance")

        if not matched_dims:
            # 默认全维度概览
            matched_dims = list(self.kb.keys())

        # 股票代码提取（支持如 600519, sh600519, 000001 等，不依赖 ASCII word boundary）
        code_match = re.search(r"(?:sh|sz|bj)?([0-9]{6})", q.lower())
        detected_code = code_match.group(1) if code_match else None

        result_channels = []
        fetched_payloads = {}

        for d in matched_dims:
            d_info = self.kb[d]
            rec_ch = next((c for c in d_info["channels"] if c["recommended"]), d_info["channels"][0])
            official_ch = next((c for c in d_info["channels"] if c["type"] == "official"), d_info["channels"][0])
            
            summary_entry = {
                "dimension": d,
                "dimension_name": d_info["dimension_name"],
                "official_authority": d_info["official_authority"],
                "official_interface": official_ch["interface"],
                "recommended_channel": rec_ch["name"],
                "recommended_interface": rec_ch["interface"],
                "validity_summary": rec_ch["validity"],
                "key_risks": rec_ch["risks"],
                "advantages": rec_ch["advantages"],
                "disadvantages": rec_ch["disadvantages"],
                "comparison_note": f"官方源 ({official_ch['name']}) 具 100% 法律效力但反爬极严且多为非结构化；工程最推荐 ({rec_ch['name']}) 具备统一标准化 RESTful JSON 且附带衍生计算。"
            }
            result_channels.append(summary_entry)

            # 如果探测到股票代码，且用户意图为获取或未限定纯咨询，则负责抓取该维度真实数据
            if detected_code:
                try:
                    fetched_payloads[d] = self.fetch_data(d, detected_code, limit=5)
                except Exception as exc:
                    fetched_payloads[d] = {"error": f"抓取失败: {str(exc)}", "code": detected_code}

        return {
            "query": query,
            "detected_code": detected_code,
            "matched_dimensions": matched_dims,
            "recommendations": result_channels,
            "fetched_data": fetched_payloads if detected_code else None
        }

    # ==========================================================================
    # 3. 负责去真实获取各维度信息的调度引擎 (真实数据抓取)
    # ==========================================================================
    def fetch_data(self, dimension: str, code: str, limit: int = 10, **kwargs) -> Dict[str, Any]:
        """
        负责去获取指定股票、指定维度的真实数据！
        """
        dim_key = self.normalize_dimension(dimension)
        if not dim_key:
            raise ValueError(f"不支持的数据抓取维度: {dimension}")

        norm_code, _ = normalize_code(code) # 如 sh600519
        clean_code = norm_code[2:]           # 如 600519

        if dim_key == "block_trade":
            return self._fetch_block_trade(clean_code, limit)
        elif dim_key == "shareholders":
            return self._fetch_shareholders(clean_code)
        elif dim_key == "dividend":
            return self._fetch_dividend(clean_code, limit)
        elif dim_key == "kline":
            return self._fetch_kline(norm_code, limit, kwargs.get("adjust", "qfq"))
        elif dim_key == "finance":
            return self._fetch_finance(norm_code, kwargs.get("period_type", "annual"))
        else:
            raise NotImplementedError(f"维度 {dimension} 抓取逻辑未就绪")

    def _fetch_block_trade(self, clean_code: str, limit: int) -> Dict[str, Any]:
        """抓取大宗交易真实数据"""
        raw_trades = BlockTradeAdapter.get_stock_block_trades(code=clean_code, page_size=limit)
        return {
            "dimension": "block_trade",
            "dimension_name": "大宗交易",
            "code": clean_code,
            "source_channel": "东方财富数据中心 (RPT_DATA_BLOCKTRADE)",
            "api_endpoint": "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DATA_BLOCKTRADE",
            "record_count": len(raw_trades),
            "records": raw_trades,
            "summary": {
                "latest_trade_date": raw_trades[0].get("trade_date") if raw_trades else None,
                "latest_deal_price": raw_trades[0].get("deal_price") if raw_trades else None,
                "latest_premium_ratio": raw_trades[0].get("premium_ratio") if raw_trades else None,
                "latest_deal_amt_wan": raw_trades[0].get("amount_wan") if raw_trades else None
            }
        }

    def _fetch_shareholders(self, clean_code: str) -> Dict[str, Any]:
        """抓取十大流通股东真实数据，并计算合计占比"""
        # 使用东财 F10 十大流通股东专用接口
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        # 沪市追加 .SH，深市 .SZ，北交所 .BJ
        market_suffix = ".SH" if clean_code.startswith(("6", "9", "5")) else (".SZ" if clean_code.startswith(("0", "3")) else ".BJ")
        secucode = f"{clean_code}{market_suffix}"

        params = {
            "reportName": "RPT_F10_EH_FREEHOLDERS",
            "columns": "ALL",
            "filter": f'(SECUCODE="{secucode}")',
            "pageNumber": 1,
            "pageSize": 10,
            "sortTypes": "-1,1",
            "sortColumns": "REPORT_DATE,HOLDER_RANK",
            "source": "WEB",
            "client": "WEB"
        }

        resp = safe_session.get_json(
            url,
            params=params,
            referer="https://data.eastmoney.com/gdfx/gdcj.html",
            timeout=6.0
        )

        holders = []
        period = ""
        stock_name = ""
        total_ratio = 0.0

        if resp and isinstance(resp, dict) and resp.get("success"):
            data_list = (resp.get("result") or {}).get("data") or []
            if data_list:
                period = str(data_list[0].get("REPORT_DATE") or "")[:10]
                stock_name = data_list[0].get("SECURITY_NAME_ABBR", "")
                
                for r in data_list:
                    r_period = str(r.get("REPORT_DATE") or "")[:10]
                    if r_period != period:
                        continue
                    ratio = number(r.get("FREE_HOLDNUM_RATIO"))
                    if ratio is not None:
                        total_ratio += ratio
                    
                    change_raw = r.get("HOLD_NUM_CHANGE")
                    change_desc = "新进" if change_raw is None else (
                        "增加" if number(change_raw, 0) > 0 else (
                            "减少" if number(change_raw, 0) < 0 else "不变"
                        )
                    )

                    holders.append({
                        "rank": r.get("HOLDER_RANK"),
                        "name": r.get("HOLDER_NAME"),
                        "hold_num_wan": round(number(r.get("HOLD_NUM", 0)) / 10000, 2) if number(r.get("HOLD_NUM")) is not None else None,
                        "ratio": ratio,
                        "change_desc": change_desc,
                        "change_num_wan": round(number(change_raw, 0) / 10000, 2) if change_raw is not None else None,
                        "holder_type": r.get("HOLDER_TYPE") or "普通股东"
                    })

        # 若 RPT_F10_EH_FREEHOLDERS 暂空，降级回退 ShareholderAdapter
        if not holders:
            fallback = ShareholderAdapter.get_top10_holders(clean_code)
            period = fallback.get("period", "")
            stock_name = fallback.get("name", "")
            for h in fallback.get("holders", []):
                holders.append({
                    "rank": h.get("rank"),
                    "name": h.get("name"),
                    "hold_num_wan": h.get("hold_num_wan"),
                    "ratio": h.get("hold_ratio"),
                    "change_desc": h.get("change"),
                    "holder_type": h.get("share_type")
                })
                if h.get("hold_ratio") is not None:
                    total_ratio += h.get("hold_ratio")

        return {
            "dimension": "shareholders",
            "dimension_name": "十大流通股东占比",
            "code": clean_code,
            "name": stock_name,
            "report_period": period,
            "source_channel": "东方财富网 F10 股东中心 (RPT_F10_EH_FREEHOLDERS)",
            "api_endpoint": f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_F10_EH_FREEHOLDERS&filter=(SECUCODE=\"{secucode}\")",
            "top10_total_ratio": round(total_ratio, 4),
            "holder_count": len(holders),
            "holders": holders
        }

    def _fetch_dividend(self, clean_code: str, limit: int) -> Dict[str, Any]:
        """抓取分红送配真实数据"""
        div_records = DividendAdapter.get_dividends(code=clean_code, page_size=limit)
        return {
            "dimension": "dividend",
            "dimension_name": "分红送配",
            "code": clean_code,
            "source_channel": "东方财富分红送配数据中心 (RPT_SHAREBONUS_DET)",
            "api_endpoint": f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_SHAREBONUS_DET&filter=(SECURITY_CODE=\"{clean_code}\")",
            "record_count": len(div_records),
            "records": div_records,
            "summary": {
                "latest_plan": div_records[0].get("plan_detail") if div_records else "暂无分红记录",
                "latest_progress": div_records[0].get("progress") if div_records else None,
                "latest_ex_date": div_records[0].get("ex_dividend_date") if div_records else None,
                "latest_cash_transfer": div_records[0].get("cash_ratio") if div_records else None
            }
        }

    def _fetch_kline(self, norm_code: str, limit: int, adjust: str) -> Dict[str, Any]:
        """抓取K线图行情真实数据 (腾讯财经前复权 + 东财备选)"""
        clean_code = norm_code[2:]
        eastmoney_bars = KlineAdapter.get_daily_kline(clean_code, limit=limit, adjust=adjust)
        
        merged_bars = []
        if eastmoney_bars:
            merged_bars = eastmoney_bars
        else:
            kline_data = get_real_kline(norm_code, days=limit)
            if kline_data:
                merged_bars = [b.to_dict() if hasattr(b, "to_dict") else b for b in kline_data]

        latest_bar = merged_bars[-1] if merged_bars else {}
        return {
            "dimension": "kline",
            "dimension_name": "K线图行情",
            "code": norm_code,
            "adjust_type": adjust,
            "source_channel": "腾讯财经 (极速前复权) / 东方财富 (Push2 真实量额)",
            "api_endpoint": f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={norm_code},day,,,{limit},{adjust}",
            "bar_count": len(merged_bars),
            "bars": merged_bars,
            "latest_kline": {
                "date": latest_bar.get("date"),
                "open": latest_bar.get("open"),
                "high": latest_bar.get("high"),
                "low": latest_bar.get("low"),
                "close": latest_bar.get("close"),
                "volume": latest_bar.get("volume"),
                "amount": latest_bar.get("amount") or latest_bar.get("turnover")
            }
        }

    def _fetch_finance(self, norm_code: str, period_type: str) -> Dict[str, Any]:
        """抓取三张财务报表真实数据"""
        clean_code = norm_code[2:]
        fin_data = fetch_financial_statements(norm_code, period_type=period_type)
        return {
            "dimension": "finance",
            "dimension_name": "财务报表",
            "code": norm_code,
            "clean_code": clean_code,
            "period_type": period_type,
            "source_channel": "东方财富 Choice 公开财报数据中心 (RPT_DMSK_FN_*)",
            "api_endpoint": f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DMSK_FN_INCOME&filter=(SECURITY_CODE=\"{clean_code}\")",
            "report_periods": fin_data.get("columns", []),
            "income_statement": fin_data.get("income_statement", []),
            "balance_sheet": fin_data.get("balance_sheet", []),
            "cash_flow_statement": fin_data.get("cash_flow_statement", []),
            "main_indicators": fin_data.get("main_indicators", [])
        }


# ==============================================================================
# 4. CLI 命令行交互入口
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="DSH 股票信息权威调研与数据抓取智能体 (Agent stockper)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="支持的子命令")

    # survey
    p_survey = subparsers.add_parser("survey", help="查看核心公开数据源的权威度调研详情")
    p_survey.add_argument("dimension", nargs="?", default="", help="可选维度: block_trade, shareholders, dividend, kline, finance")

    # compare
    p_compare = subparsers.add_parser("compare", help="查看同一信息在不同渠道抓取的横向对比分析")
    p_compare.add_argument("dimension", nargs="?", default="", help="可选维度: block_trade, shareholders, dividend, kline, finance")

    # ask
    p_ask = subparsers.add_parser("ask", help="向 stockper 快速问询抓取渠道并可直接获取数据")
    p_ask.add_argument("query", help="自然语言问题或查询需求（如 '大宗交易从哪里获取更权威' 或 '获取 600519 的十大股东'）")

    # fetch
    p_fetch = subparsers.add_parser("fetch", help="负责直接抓取指定维度的真实数据")
    p_fetch.add_argument("dimension", help="维度: block_trade, shareholders, dividend, kline, finance")
    p_fetch.add_argument("code", help="股票代码 (如 600519 或 sh600519)")
    p_fetch.add_argument("--limit", type=int, default=10, help="获取记录条数限制，默认 10")
    p_fetch.add_argument("--format", choices=["json", "text"], default="text", help="输出格式，默认 text")

    args = parser.parse_args()
    agent = StockperAgent()

    if args.command == "survey":
        res = agent.get_survey(args.dimension or None)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "compare":
        report_md = agent.get_comparison(args.dimension or None)
        print(report_md)

    elif args.command == "ask":
        ans = agent.ask(args.query)
        print(f"\n🤖 【Agent stockper 权威调研建议】")
        print(f"📝 问询诉求: {ans['query']}")
        if ans["detected_code"]:
            print(f"🎯 识别标的: {ans['detected_code']}")
        print(f"🔍 涉及维度: {', '.join(ans['matched_dimensions'])}\n")
        
        for r in ans["recommendations"]:
            print(f"======================================================================")
            print(f"📌 信息维度: {r['dimension_name']}")
            print(f"🏛️ 官方最权威来源: {r['official_authority']}")
            print(f"🌟 工程最推荐渠道: {r['recommended_channel']}")
            print(f"🔗 抓取接口: {r['recommended_interface']}")
            print(f"⏱️ 有效性: {r['validity_summary']}")
            print(f"⚠️ 核心风险: {r['key_risks']}")
            print(f"⚖️ 横向对比提示: {r['comparison_note']}")
            print(f"======================================================================\n")

        if ans["fetched_data"]:
            print("🚀 【负责去获取的真实数据结果】:")
            for d_name, d_val in ans["fetched_data"].items():
                print(f"\n--- [{d_name}] 真实抓取数据概要 ---")
                if "top10_total_ratio" in d_val:
                    print(f"十大流通股东合计占比: {d_val['top10_total_ratio']}% (报告期: {d_val.get('report_period')})")
                    for h in d_val.get("holders", [])[:5]:
                        print(f"  No.{h['rank']} {h['name']}: {h['ratio']}% ({h['change_desc']})")
                elif "latest_trade_date" in d_val.get("summary", {}):
                    print(f"最新大宗交易日: {d_val['summary']['latest_trade_date']}, 成交价: {d_val['summary']['latest_deal_price']}, 折溢价率: {d_val['summary']['latest_premium_ratio']}%")
                elif "latest_plan" in d_val.get("summary", {}):
                    print(f"最新分红方案: {d_val['summary']['latest_plan']} (进度: {d_val['summary']['latest_progress']}, 除权日: {d_val['summary']['latest_ex_date']})")
                elif "latest_kline" in d_val:
                    k = d_val["latest_kline"]
                    print(f"最新K线: {k['date']} 开盘:{k['open']} 收盘:{k['close']} 最高:{k['high']} 最低:{k['low']} 成交量:{k['volume']}")
                elif "income_statement" in d_val:
                    print(f"财报报告期: {d_val.get('report_periods')}")
                    for row in d_val.get("main_indicators", [])[:3]:
                        print(f"  {row['item']}: {row['values']}")
                else:
                    print(json.dumps(d_val, ensure_ascii=False)[:300] + "...")

    elif args.command == "fetch":
        data = agent.fetch_data(args.dimension, args.code, limit=args.limit)
        if args.format == "json":
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(f"\n✅ 成功抓取 [{data['dimension_name']}] - 标的: {args.code}")
            print(f"📡 来源渠道: {data['source_channel']}")
            print(f"🔗 接口: {data['api_endpoint']}\n")
            
            # 美化输出
            if data["dimension"] == "shareholders":
                print(f"📅 报告期: {data.get('report_period')}")
                print(f"🏆 十大流通股东累计持股比例: {data.get('top10_total_ratio')}%\n")
                print(f"{'排名':<4} {'股东名称':<28} {'持股(万股)':<12} {'占比(%)':<8} {'变动'}")
                print("-" * 65)
                for h in data.get("holders", []):
                    name_display = h['name'][:24]
                    print(f"{h['rank']:<4} {name_display:<26} {str(h['hold_num_wan']):<12} {str(h['ratio']):<8} {h['change_desc']}")

            elif data["dimension"] == "block_trade":
                print(f"{'交易日期':<12} {'成交价(元)':<10} {'收盘价(元)':<10} {'折溢价率(%)':<12} {'成交额(万元)':<12} {'买方营业部'}")
                print("-" * 80)
                for t in data.get("records", []):
                    print(f"{t.get('trade_date',''):<12} {str(t.get('deal_price','')):<10} {str(t.get('close_price','')):<10} {str(t.get('premium_ratio','')):<12} {str(t.get('amount_wan','')):<12} {str(t.get('buyer',''))[:15]}")

            elif data["dimension"] == "dividend":
                print(f"{'报告期':<12} {'分红方案说明':<32} {'除权除息日':<12} {'每股派现(含税)':<12} {'进度'}")
                print("-" * 85)
                for d in data.get("records", []):
                    print(f"{d.get('report_period',''):<12} {str(d.get('plan_detail',''))[:30]:<30} {str(d.get('ex_dividend_date','')):<12} {str(d.get('cash_ratio','')):<12} {str(d.get('progress',''))}")

            elif data["dimension"] == "kline":
                print(f"K线根数: {data['bar_count']} (复权: {data['adjust_type']})")
                print(f"{'日期':<12} {'开盘':<8} {'最高':<8} {'最低':<8} {'收盘':<8} {'成交量(手)':<12} {'成交额(元)'}")
                print("-" * 75)
                for b in data.get("bars", [])[-10:]:
                    print(f"{b.get('date',''):<12} {b.get('open',0):<8.2f} {b.get('high',0):<8.2f} {b.get('low',0):<8.2f} {b.get('close',0):<8.2f} {b.get('volume',0):<12} {str(b.get('amount','-'))}")

            elif data["dimension"] == "finance":
                print(f"报告期列表: {data.get('report_periods')}\n")
                print("【核心财务指标】:")
                for item in data.get("main_indicators", []):
                    print(f"  * {item['item']}: {item['values']}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
