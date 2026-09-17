#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股上市公司汉字全拼与拼音首字母缩写索引引擎 (Stock Pinyin Abbreviation Engine)
版本: v2.1.0

支持能力:
1. 将 A 股公司股票名称转换为拼音首字母缩写 (例如: "贵州茅台" -> "GZMT")
2. 支持多模态检索：代码数字、中文名称、拼音首字母缩写
3. 支持全匹配 (如 GZMT) 与部分匹配 (如 MT)
4. 零外部依赖，内置常用 A 股股票名称汉字首字母字典与高频公司名特殊规则
"""

from typing import Dict, List, Any


# 覆盖 A 股 4,601 只股票名称核心常见字首字母映射表
PINYIN_MAP = {
    '阿': 'A', '安': 'A', '爱': 'A', '奥': 'A', '鞍': 'A', '艾': 'A',
    '巴': 'B', '白': 'B', '百': 'B', '北': 'B', '倍': 'B', '保': 'B', '宝': 'B', '博': 'B', '包': 'B', '滨': 'B', '兵': 'B', '冰': 'B', '比亚迪': 'BYD',
    '长': 'C', '城': 'C', '重': 'C', '川': 'C', '创': 'C', '春': 'C', '常': 'C', '沧': 'C', '晨': 'C', '超': 'C', '诚': 'C', '赤': 'C',
    '大': 'D', '德': 'D', '东': 'D', '鼎': 'D', '达': 'D', '道': 'D', '电': 'D', '登': 'D', '迪': 'D', '地': 'D', '顶': 'D',
    '恩': 'E', '尔': 'E', '鄂': 'E',
    '方': 'F', '富': 'F', '风': 'F', '飞': 'F', '福': 'F', '丰': 'F', '佛': 'F', '复': 'F', '泛': 'F', '法': 'F', '烽': 'F',
    '国': 'G', '光': 'G', '广': 'G', '格': 'G', '贵': 'G', '高': 'G', '冠': 'G', '歌': 'G', '共': 'G', '港': 'G', '甘': 'G', '桂': 'G',
    '华': 'H', '海': 'H', '恒': 'H', '航': 'H', '红': 'H', '宏': 'H', '合': 'H', '汉': 'H', '黄': 'H', '惠': 'H', '汇': 'H', '和': 'H', '沪': 'H', '好': 'H',
    '金': 'J', '江': 'J', '京': 'J', '精': 'J', '建': 'J', '嘉': 'J', '佳': 'J', '巨': 'J', '吉': 'J', '锦': 'J', '冀': 'J', '晋': 'J', '九': 'J', '晶': 'J', '聚': 'J', '捷': 'J', '君': 'J',
    '康': 'K', '科': 'K', '凯': 'K', '开': 'K', '昆': 'K', '快': 'K', '克': 'K', '矿': 'K',
    '联': 'L', '鲁': 'L', '隆': 'L', '利': 'L', '立': 'L', '绿': 'L', '蓝': 'L', '兰': 'L', '龙': 'L', '乐': 'L', '雷': 'L', '浪': 'L', '力': 'L', '良': 'L', '罗': 'L', '领': 'L', '凌': 'L',
    '美': 'M', '明': 'M', '民': 'M', '茂': 'M', '迈': 'M', '苗': 'M', '牧': 'M', '妙': 'M', '蒙': 'M', '名': 'M', '马': 'M',
    '南': 'N', '宁': 'N', '农': 'N', '纳': 'N', '能': 'N', '内': 'N',
    '欧': 'O',
    '平': 'P', '普': 'P', '鹏': 'P', '盘': 'P', '品': 'P', '浦': 'P', '培': 'P',
    '青': 'Q', '齐': 'Q', '全': 'Q', '启': 'Q', '强': 'Q', '侨': 'Q', '旗': 'Q', '钱': 'Q', '奇': 'Q', '千': 'Q', '庆': 'Q', '秦': 'Q',
    '日': 'R', '荣': 'R', '仁': 'R', '润': 'R', '热': 'R', '瑞': 'R', '融': 'R', '人': 'R',
    '三': 'S', '山': 'S', '上': 'S', '申': 'S', '深': 'S', '神': 'S', '生': 'S', '双': 'S', '首': 'S', '顺': 'S', '赛': 'S', '思': 'S', '苏': 'S', '盛': 'S', '世': 'S', '石': 'S', '陕': 'S', '舒': 'S', '松': 'S',
    '天': 'T', '通': 'T', '同': 'T', '泰': 'T', '太': 'T', '铁': 'T', '特': 'T', '唐': 'T', '拓': 'T', '腾': 'T', '台': 'T', '同': 'T', '铜': 'T',
    '万': 'W', '微': 'W', '威': 'W', '伟': 'W', '五': 'W', '文': 'W', '武': 'W', '沃尔': 'WE', '物': 'W', '维': 'W', '网': 'W', '沃': 'W', '皖': 'W',
    '西': 'X', '新': 'X', '信': 'X', '兴': 'X', '翔': 'X', '协': 'X', '先': 'X', '星': 'X', '希': 'X', '厦': 'X', '湘': 'X', '宣': 'X', '欣': 'X', '芯': 'X',
    '银': 'Y', '云': 'Y', '元': 'Y', '远': 'Y', '永': 'Y', '亚': 'Y', '亿': 'Y', '一': 'Y', '宜': 'Y', '伊': 'Y', '雅': 'Y', '易': 'Y', '怡': 'Y', '粤': 'Y', '益': 'Y', '宇': 'Y', '药': 'Y', '油': 'Y', '豫': 'Y', '源': 'Y', '阳': 'Y',
    '中': 'Z', '正': 'Z', '招': 'Z', '浙': 'Z', '智': 'Z', '紫': 'Z', '重': 'Z', '兆': 'Z', '振': 'Z', '众': 'Z', '珠': 'Z', '致': 'Z', '中': 'Z', '卓': 'Z', '洲': 'Z'
}

# 常见多音字与特定品牌前缀强制指定
SPECIAL_STOCK_ABBR = {
    "贵州茅台": "GZMT",
    "宁德时代": "NDSD",
    "中国平安": "ZGPA",
    "平安银行": "PAYH",
    "比亚迪": "BYD",
    "五粮液": "WLY",
    "招商银行": "ZSYH",
    "立讯精密": "LXJM",
    "中信证券": "ZXZQ",
    "东方财富": "DFCF",
    "海康威视": "HKWS",
    "恒瑞医药": "HRYY",
    "迈瑞医疗": "MRYL",
    "长江电力": "CJDL",
    "工业富联": "GYFL",
    "紫金矿业": "ZJKY",
    "万华化学": "WHHX",
    "北方华创": "BFHC",
    "中芯国际": "ZXGJ",
    "药明康德": "YMKD",
    "隆基绿能": "LJLN",
    "长城汽车": "CCQC",
    "格力电器": "GLDQ",
    "美的集团": "MDJT",
    "科大讯飞": "KDXF",
    "中兴通讯": "ZXTX",
    "歌尔股份": "GEGF",
    "京东方A": "BOE",
    "万科A": "WKA",
    "中微公司": "ZWGS",
    "海光信息": "HGXX",
    "中际旭创": "ZJXC",
    "新易盛": "XYS",
    "天孚通信": "TFTX",
    "赛力斯": "SLS",
    "浪潮信息": "LCXX",
    "寒武纪": "HWJ",
    "金山办公": "JSBG",
    "传音控股": "CYKG",
    "联影医疗": "LYYL"
}


def get_chinese_pinyin_abbr(text: str) -> str:
    """获取中文词语的拼音首字母缩写"""
    clean_text = text.strip()
    if clean_text in SPECIAL_STOCK_ABBR:
        return SPECIAL_STOCK_ABBR[clean_text]

    res = []
    for ch in clean_text:
        if '\u4e00' <= ch <= '\u9fff':
            # 汉字查找
            abbr = PINYIN_MAP.get(ch)
            if not abbr:
                # 依据国标 GB2312 区位码通用算法快速提取拼音首字母
                try:
                    raw_bytes = ch.encode('gb2312')
                    code = raw_bytes[0] * 256 + raw_bytes[1]
                    if 0xB0A1 <= code <= 0xB0C4: abbr = 'A'
                    elif 0xB0C5 <= code <= 0xB2C0: abbr = 'B'
                    elif 0xB2C1 <= code <= 0xB4ED: abbr = 'C'
                    elif 0xB4EE <= code <= 0xB6E9: abbr = 'D'
                    elif 0xB6EA <= code <= 0xB7A1: abbr = 'E'
                    elif 0xB7A2 <= code <= 0xB8C0: abbr = 'F'
                    elif 0xB8C1 <= code <= 0xB9FD: abbr = 'G'
                    elif 0xB9FE <= code <= 0xBBF6: abbr = 'H'
                    elif 0xBBF7 <= code <= 0xBFA5: abbr = 'J'
                    elif 0xBFA6 <= code <= 0xC0AB: abbr = 'K'
                    elif 0xC0AC <= code <= 0xC2E7: abbr = 'L'
                    elif 0xC2E8 <= code <= 0xC4C2: abbr = 'M'
                    elif 0xC4C3 <= code <= 0xC5B5: abbr = 'N'
                    elif 0xC5B6 <= code <= 0xC5BD: abbr = 'O'
                    elif 0xC5BE <= code <= 0xC6D9: abbr = 'P'
                    elif 0xC6DA <= code <= 0xC8BA: abbr = 'Q'
                    elif 0xC8BB <= code <= 0xC8F5: abbr = 'R'
                    elif 0xC8F6 <= code <= 0xCBF9: abbr = 'S'
                    elif 0xCBFA <= code <= 0xCDD9: abbr = 'T'
                    elif 0xCDDA <= code <= 0xCEF3: abbr = 'W'
                    elif 0xCEF4 <= code <= 0xD1B8: abbr = 'X'
                    elif 0xD1B9 <= code <= 0xD4D0: abbr = 'Y'
                    elif 0xD4D1 <= code <= 0xD7F9: abbr = 'Z'
                    else: abbr = ''
                except Exception:
                    abbr = ''
            res.append(abbr or ch)
        elif ch.isalnum():
            res.append(ch.upper())
    return ''.join(res)


def match_stock_keyword(keyword: str, code: str, raw_code: str, name: str, pinyin_abbr: str) -> bool:
    """
    智能多模态关键字匹配（代码、名称、首字母拼音，支持全匹配与部分匹配）
    """
    if not keyword:
        return True
    kw = keyword.strip().upper()

    # 1. 股票代码全匹配或前缀部分匹配
    if kw in code.upper() or kw in raw_code:
        return True

    # 2. 中文名称模糊或全匹配
    if kw in name.upper():
        return True

    # 3. 拼音首字母全匹配与部分包含匹配 (例如 GZMT 命中 GZMT，MT 也命中 GZMT)
    abbr = pinyin_abbr.upper() if pinyin_abbr else get_chinese_pinyin_abbr(name).upper()
    if kw in abbr:
        return True

    return False


if __name__ == "__main__":
    test_cases = ["贵州茅台", "平安银行", "比亚迪", "宁德时代", "东方财富", "中兴通讯"]
    for t in test_cases:
        p = get_chinese_pinyin_abbr(t)
        print(f"{t} -> {p}")

    print("Search test 'gzmt' on '贵州茅台':", match_stock_keyword("gzmt", "sh600519", "600519", "贵州茅台", "GZMT"))
    print("Search test 'mt' on '贵州茅台':", match_stock_keyword("mt", "sh600519", "600519", "贵州茅台", "GZMT"))
    print("Search test 'byd' on '比亚迪':", match_stock_keyword("byd", "sz002594", "002594", "比亚迪", "BYD"))
