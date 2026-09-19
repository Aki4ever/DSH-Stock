import sys, json, os, tempfile, sqlite3, subprocess, threading
from pathlib import Path
from unittest.mock import patch
root=Path('/tmp/dsh-baseline-r01/project-copy');sys.path.insert(0,str(root))
out=root.parent/'evidence';results={}
from scripts import stock_db
with patch.object(threading.Thread,'start',return_value=None):
 from scripts import stock_web_server as web
web.SERVER_STATE='stopped'
# Characterize current behavior using fixture input, not actual company claims.
sample=dict(next(iter(web.DATA_MANAGER.stocks_dict.values())))
sample.update(code='sh600001',raw_code='600001',name='BASELINE_FIXTURE',price=10,pe=20,listing_years=8,market_cap=100,circulating_cap=60,turnover_rate=2,turnover_yi=1.2)
m=web.StockDataManager.__new__(web.StockDataManager)
m._lock=threading.Lock();m.stocks_dict={sample['code']:sample}
left,ls=m.filter_stocks({'filter_date':'2000-01-01'})
right,rs=m.filter_stocks({'filter_date':'2026-09-18'})
results['historical_filter']={'same_codes_prices':[(r['code'],r['price']) for r in left]==[(r['code'],r['price']) for r in right],'requested_dates':[ls['snapshot_date'],rs['snapshot_date']],'fixture_only':True,'explanation':'filter_date changes reported metadata, not historical selection'}
prof,ps=m.filter_stocks({'profit_years':'3'})
results['profit_filter']={'accepted_fixture_without_annual_profit_history':len(prof)==1,'fixture_only':True,'pe':20,'listing_years':8}
from scripts.shareholder_engine import Top10ShareholdersEngine as SH
synthetic=SH.get_stock_top10_shareholders('sh600001',name='BASELINE_FIXTURE',top10_circ_pct=0)
results['shareholder_generation']={'holders_count':len(synthetic['holders']),'first_name':synthetic['holders'][0]['name'],'total_circ_pct':synthetic['total_circ_pct'],'contains_source_field':'source' in synthetic,'is_mock_field':synthetic.get('is_mock'),'network_used':False,'fixture_only':True}
from scripts.company_finance_engine import fetch_company_profile
with patch('urllib.request.urlopen',side_effect=OSError('BASELINE_NETWORK_DISABLED')):
 profile=fetch_company_profile('sh600001','BASELINE_FIXTURE','SH','MAIN')
results['profile_on_network_failure']={'legal_repr':profile.get('legal_repr'),'reg_capital':profile.get('reg_capital'),'source':profile.get('source'),'is_mock':profile.get('is_mock'),'fixture_only':True}
old=stock_db.DB_PATH;old_dir=stock_db.DATA_DIR
cold=Path(tempfile.mkdtemp(prefix='dsh-cold-db-'))
stock_db.DB_PATH=str(cold/'empty.db');stock_db.DATA_DIR=str(cold)
try:
 stock_db.init_db()
 try:
  rows=stock_db.load_all_stocks_from_db();results['fresh_database']={'load_succeeded':True,'rows':len(rows)}
 except Exception as ex:results['fresh_database']={'load_succeeded':False,'error_type':type(ex).__name__,'error':str(ex)}
 with sqlite3.connect(stock_db.DB_PATH) as con:
  columns=[r[1] for r in con.execute('PRAGMA table_info(stocks_master)')]
  results['fresh_database']['missing_query_columns']=[k for k in ['dividend_total_amount','pinyin_abbr'] if k not in columns]
 # Check cache expiry using old same-day update metadata in a disposable database.
 from datetime import datetime
 with sqlite3.connect(stock_db.DB_PATH) as con:
  con.execute('INSERT INTO stock_timeline VALUES (?,?,?,?,?)',('sh600001',datetime.now().strftime('%Y-%m-%d'),10,json.dumps([{'time':'09:30','price':10}]),'2000-01-01 00:00:00'))
  for day in ['2026-09-01','2026-09-02','2026-09-03']:
   con.execute('INSERT INTO stock_daily_kline (code,date,open,close,high,low,volume,amount_yi) VALUES (?,?,?,?,?,?,?,?)',('sh600001',day,10,10,11,9,100,1))
 results['timeline_ttl']={'max_age_seconds':1,'returned_expired_same_day_record':stock_db.load_stock_timeline('sh600001',max_age_seconds=1) is not None,'fixture_only':True}
 results['kline_limit']={'limit':2,'returned_dates':[r['date'] for r in stock_db.load_daily_klines('sh600001',limit=2)],'fixture_only':True}
finally:stock_db.DB_PATH=old;stock_db.DATA_DIR=old_dir
from scripts.chanlun_core import analyze_chanlun_signals
results['chanlun_empty_smoke']={'signals':analyze_chanlun_signals('fixture','fixture',[]),'scope':'Empty-input smoke only; no geometry or strategy correctness acceptance'}
for args,name in [(['--help'],'cli_help'),(['status'],'cli_status'),(['--json','status'],'cli_json_support')]:
 r=subprocess.run([sys.executable,str(root/'scripts/dsh_stock_cli.py'),*args],capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),timeout=10)
 (out/(name+'.log')).write_text(r.stdout+r.stderr)
 results[name]={'exit_code':r.returncode,'log':name+'.log'}
(out/'characterization.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print(json.dumps(results,ensure_ascii=False,indent=2))
