"""公司资料与三张报表使用公开披露；缺失字段不估算。"""
from datetime import date
import time
from scripts.market_history import canonical_code
from scripts.verified_sources import request_json, dc_page, number, meta, cache_get, cache_put


def fetch_company_profile(code, name='', market='', board=''):
    code=canonical_code(code); key='profile:v1:'+code; cached=cache_get(key)
    if cached and time.time()-cached.get('fetched_epoch',0)<86400:return cached
    out=dict(meta('东方财富公司概况', 'unavailable'),company_name=name,industry=None,legal_repr=None,reg_capital=None,office_addr=None,business_scope=None,company_intro=None)
    url='https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code='+code.upper()
    try:
        d=request_json(url).get('jbzl') or {}
        if isinstance(d,list):d=d[0] if d else {}
        for k,v in {'company_name':'gsmc','industry':'sshy','legal_repr':'frdb','reg_capital':'zczb','office_addr':'bgdz','business_scope':'jyfw','company_intro':'gsjj'}.items():
            if d.get(v):out[k]=d[v]
        out.update(status='available' if d else 'unavailable',source_url=url)
        if d:cache_put(key,out)
    except Exception as exc:out['error']=str(exc)
    return out


def fetch_financial_statements(code, price=0, market_cap=0, pe=0, period_type='annual', *, transport=None):
    if period_type not in ('annual','report','quarter'):raise ValueError('财报周期仅支持annual/report/quarter')
    code=canonical_code(code);key='finance:v1:'+code+':'+period_type;cached=cache_get(key)
    if transport is None and cached and time.time()-cached.get('fetched_epoch',0)<86400:return cached
    mapping={'income_statement':('RPT_DMSK_FN_INCOME',[('营业总收入','TOTAL_OPERATE_INCOME'),('营业成本','OPERATE_COST'),('营业利润','OPERATE_PROFIT'),('利润总额','TOTAL_PROFIT'),('归母净利润','PARENT_NETPROFIT'),('扣非归母净利润','DEDUCT_PARENT_NETPROFIT')]),
             'balance_sheet':('RPT_DMSK_FN_BALANCE',[('资产总计','TOTAL_ASSETS'),('负债合计','TOTAL_LIABILITIES'),('所有者权益合计','TOTAL_EQUITY')]),
             'cash_flow_statement':('RPT_DMSK_FN_CASHFLOW',[('经营活动现金流量净额','NETCASH_OPERATE'),('投资活动现金流量净额','NETCASH_INVEST'),('筹资活动现金流量净额','NETCASH_FINANCE'),('现金及现金等价物净增加额','CCE_ADD')])}
    datasets={};errors=[];today=date.today().isoformat()
    for section,(report,_) in mapping.items():
        try:
            rows=dc_page(report,size=30,sort='REPORT_DATE',filters=f'(SECURITY_CODE="{code[2:]}")',transport=transport).get('data') or []
            datasets[section]={str(r.get('REPORT_DATE',''))[:10]:r for r in rows if r.get('SECURITY_CODE')==code[2:] and str(r.get('REPORT_DATE',''))[:10]<=today and str(r.get('NOTICE_DATE') or '')[:10]<=today}
        except Exception as exc:datasets[section]={};errors.append(str(exc))
    dates=sorted(set(d for ds in datasets.values() for d in ds),reverse=True)
    if period_type=='annual':dates=[d for d in dates if d.endswith('12-31')]
    dates=dates[:5]
    out=dict(meta('东方财富Choice公开财报','partial' if errors and dates else 'unavailable' if not dates else 'available','；'.join(errors) or None),code=code,period_type=period_type,columns=dates,col_type_label='科目 / 报告期',main_indicators=[],units='亿元',derivation='单季度利润/现金流由同年累计值相减；资产负债表为期末值' if period_type=='quarter' else '来源披露累计值')
    for section,(_,fields) in mapping.items():
        out[section]=[]
        for label,field in fields:
            values=[]
            for d in dates:
                val=number(datasets[section].get(d,{}).get(field))
                if period_type=='quarter' and section!='balance_sheet' and not d.endswith('03-31'):
                    prev={'06':'03-31','09':'06-30','12':'09-30'}.get(d[5:7])
                    old=number(datasets[section].get(d[:4]+'-'+str(prev),{}).get(field))
                    val=val-old if val is not None and old is not None else None
                values.append(round(val/1e8,4) if val is not None else None)
            out[section].append({'item':label+' (亿元)','values':values})
    out['main_indicators']=[dict(r,category='真实披露') for r in out['income_statement'] if r['item'].startswith(('营业总收入','归母净利润'))]
    if transport is None and dates:cache_put(key,out)
    return out
