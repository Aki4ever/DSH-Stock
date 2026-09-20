"""R02 回归：所有构造数据仅存在隔离测试，不写入产品库。"""
import json
import math
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from scripts import stock_db, shareholder_engine as se
from scripts.chanlun_analysis import analyze_bars, build_segments, build_pivots, build_divergences
from scripts.company_finance_engine import fetch_financial_statements
from scripts.dashboard_engine import compute_market_overview
from scripts.verified_quotes import clean_legacy_stock, fetch_quotes


def bars(prices):
    return [dict(date=(date(2020,1,1)+timedelta(days=i)).isoformat(),open=p,close=p,high=p+.2,low=p-.2,volume=100) for i,p in enumerate(prices)]


def pen_sequence(points,areas=None):
    return [dict(start_time=f'2020-01-{i+1:02}',end_time=f'2020-01-{i+2:02}',start_index=i,end_index=i+1,
        start_price=a,end_price=b,direction=1 if b>a else -1,high=max(a,b),low=min(a,b),macd_area=(areas or [10]*len(points))[i],status='confirmed') for i,(a,b) in enumerate(zip(points,points[1:]))]


class ChanlunTests(unittest.TestCase):
    def test_five_outputs_flat_series_and_ma_warmup(self):
        r=analyze_bars(bars([10]*40))
        self.assertEqual(set(r['counts']),{'pens','segments','pivots','divergences','ma_entanglements'})
        self.assertEqual([r['counts'][k] for k in ['pens','segments','pivots','divergences']],[0,0,0,0])
        self.assertEqual(r['ma_entanglements'][0]['start_index'],19)
        self.assertEqual(r['ma_entanglements'][0]['bar_count'],21)
        self.assertEqual(r['ma_entanglements'][0]['status'],'provisional')
        self.assertIsNone(r['ma']['20'][18])

    def test_no_false_turns_on_monotonic_prices(self):
        r=analyze_bars(bars([10+i for i in range(50)]),threshold_pct=.01)
        self.assertTrue(all(n==0 for n in r['counts'].values()))
        self.assertEqual(analyze_bars(bars([10]*3))['status'],'insufficient')

    def test_extrema_anchor_to_actual_prices_after_inclusion(self):
        raw=bars([100+8*math.sin(i/4) for i in range(160)])
        raw.insert(8,dict(raw[7],high=raw[7]['high']-.05,low=raw[7]['low']+.05))
        for i,b in enumerate(raw):b['date']=(date(2020,1,1)+timedelta(days=i)).isoformat()
        r=analyze_bars(raw)
        self.assertGreater(len(r['pens']),5)
        for p in r['pens']:
            for end in ('start','end'):
                b=raw[p[end+'_index']]
                self.assertEqual(p[end+'_time'],b['date'])
                self.assertTrue(any(abs(p[end+'_price']-b[k])<.00011 for k in ('high','low')))
        self.assertEqual(r['pens'][-1]['status'],'provisional')

    def test_segment_requires_feature_reversal_not_fixed_three_pens(self):
        sequence=pen_sequence([100,110,104,114,108,112,106,109,102])
        segments=build_segments(sequence)
        self.assertEqual(segments[0]['end_price'],114)
        self.assertEqual(segments[0]['pen_count'],3)
        self.assertEqual(segments[0]['status'],'confirmed')
        self.assertEqual(build_segments(pen_sequence([100,110,105,115,109,119]))[0]['status'],'provisional')
        self.assertEqual(build_segments(sequence[:2]),[])

    def test_gap_requires_confirmation(self):
        seg=build_segments(pen_sequence([100,110,105,130,120,125,115]))
        self.assertEqual(seg[0]['status'],'provisional')
        self.assertIn('缺口',seg[0]['reason'])

    def test_pivot_and_divergence_have_independent_evidence(self):
        seq=pen_sequence([100,110,104,112,106],[20,20,10,10])
        pivots=build_pivots(seq)
        self.assertEqual((pivots[0]['zd'],pivots[0]['zg']),(104,110))
        div=build_divergences(seq)
        self.assertEqual(div[0]['kind'],'顶背离')
        self.assertEqual(div[0]['current_area'],10)
        self.assertEqual(build_divergences(pen_sequence([100,110,104,112],[10,10,20])),[])

    def test_invalid_input_rejected(self):
        for b in [bars([10,10])[::-1],bars([float('nan')]),[dict(bars([10])[0],high=1)]]:
            with self.assertRaises(ValueError):analyze_bars(b)
        with self.assertRaises(ValueError):analyze_bars([],periods=(5,5))


class DataIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.dbpatch=patch.object(stock_db,'DB_PATH',str(Path(self.tmp.name)/'test.db'));self.dbpatch.start()
        stock_db.init_db();se._memo.clear();se._memo_loaded.clear()
    def tearDown(self):self.dbpatch.stop();self.tmp.cleanup()

    def test_completed_refresh_keeps_previously_collected_names(self):
        from scripts.verified_sources import meta
        def snapshot(name, period):
            row=dict(code='sh600519',stock_name='测试',name=name,category='individual',nature='个人',period=period,hold_pct=1,hold_num=100)
            return dict(meta('fixture'),rows=[row],count=1,complete=True,covered_stocks=1,as_of='2026-09-20',pages_completed=[1],provider_pages=1)
        se.get_holder_snapshot(refresh=True,fetcher=lambda:snapshot('旧姓名','2025-12-31'))
        updated=se.get_holder_snapshot(refresh=True,fetcher=lambda:snapshot('新姓名','2026-06-30'))
        self.assertEqual({r['name'] for r in updated['rows']},{'旧姓名','新姓名'})
        self.assertEqual(len(se.aggregate_holders(updated['rows'])),2)
        self.assertTrue(updated['complete'])

    def test_cold_database_and_legacy_contamination(self):
        self.assertEqual(stock_db.load_all_stocks_from_db(),[])
        r=clean_legacy_stock(dict(code='sh600519',price=88,dividend_count=25,listing_years=25,top10_hold_pct=95,is_csi50=True,open_p=90,change_val=99))
        for k in ['price','dividend_count','listing_years','top10_hold_pct','is_csi50','open_p','change_val']:self.assertIsNone(r[k])

    def test_quote_field_mapping_missing_values_and_source(self):
        p=['']*50;p[1]='测试';p[3]='10';p[30]='20260918150000';p[44]='100';p[45]='150'
        with patch('scripts.verified_quotes.robust_fetch',return_value='v_sh600519="'+'~'.join(p)+'";'):
            row=fetch_quotes(['sh600519'])[0]
        self.assertEqual(row['market_cap'],150)
        self.assertEqual(row['circulating_cap'],100)
        self.assertIsNone(row['turnover']);self.assertIsNone(row['pe'])
        self.assertEqual(clean_legacy_stock({'code':'sh600519'})['price'],10)

    def test_no_name_pool_no_800_stock_cap_and_cross_period_names(self):
        rows=[dict(code=f'sz{i:06}',stock_name=f'企业{i}',name=f'个人{i}',category='individual',nature='个人',period='2026-06-30',hold_pct=1,hold_num=1) for i in range(1001)]
        rows += [dict(rows[0],code='sh600519'),dict(rows[1],period='2025-12-31',name='旧期独有姓名'),dict(rows[2])]
        holders=se.aggregate_holders(rows)
        self.assertEqual(len(holders),1002)
        self.assertEqual(next(h for h in holders if h['holder_name']=='个人0')['company_count'],2)
        self.assertEqual(se.Top10ShareholdersEngine.get_shareholders_overview(holders)['individual_holders_count'],1002)

    def test_failed_page_continues_and_repeated_page_never_complete(self):
        def transport(url,params):
            page=params['pageNumber']
            if page==2:raise OSError('offline fixture')
            row=dict(SECURITY_CODE='600519',HOLDER_NAME='姓名'+str(page),END_DATE='2026-06-30',HOLDER_NEWTYPE='个人',RANK=page)
            return {'success':True,'result':{'data':[row],'count':3,'pages':3}}
        r=se.fetch_holder_snapshot(transport=transport,today=date(2026,9,20),max_pages=3)
        self.assertEqual(r['count'],2);self.assertEqual(r['status'],'partial');self.assertEqual(r['failed_pages'][0]['page'],2)
        repeated=lambda url,p:transport(url,dict(p,pageNumber=1))
        self.assertFalse(se.fetch_holder_snapshot(transport=repeated,max_pages=3)['complete'])

    def test_partial_company_disclosure_does_not_imply_zero_individuals(self):
        row=dict(code='sh600519',stock_name='测试',name='机构A',category='institution',nature='法人',period='2026-06-30',notice_date=None,rank=1,hold_pct=50,hold_num=100,change_num=None,change_label='未提供')
        with patch.object(se,'get_holder_snapshot',return_value={'rows':[row],'status':'partial'}):
            r=se.Top10ShareholdersEngine.get_stock_top10_shareholders('sh600519')
        self.assertIsNone(r['total_pct']);self.assertIsNone(r['individual_pct']);self.assertFalse(r['disclosure_complete'])

    def test_financial_quarter_subtracts_cumulative_and_missing_is_none(self):
        def transport(url,p):
            rows=[dict(SECURITY_CODE='600519',REPORT_DATE=d,NOTICE_DATE=d,TOTAL_OPERATE_INCOME=n,TOTAL_ASSETS=4e8) for d,n in [('2026-06-30',3e8),('2026-03-31',1e8)]]
            return {'success':True,'result':{'data':rows}}
        r=fetch_financial_statements('600519',period_type='quarter',transport=transport)
        self.assertEqual(r['income_statement'][0]['values'],[2,1])
        self.assertEqual(r['balance_sheet'][0]['values'],[4,4])
        self.assertEqual(r['income_statement'][1]['values'],[None,None])
        r=fetch_financial_statements('600519',transport=lambda *_:{'success':False})
        self.assertEqual(r['status'],'unavailable');self.assertEqual(r['columns'],[])

    def test_dashboard_unknown_never_becomes_zero_or_synthetic_range(self):
        r=compute_market_overview([dict(price=10,change_pct=1,market_cap=None)])
        self.assertIsNone(r['dimensions']['amplitude']['stats']['mean'])
        self.assertIsNone(r['dimensions']['dividend_count']['stats']['mean'])
        self.assertEqual(sum(r['charts']['market_cap_tiers'].values()),0)
        self.assertEqual(r['charts']['top10_circ_tiers_10']['total_count'],0)
        self.assertEqual(compute_market_overview([dict(price=10,change_pct=1)],'2026-01-01','2026-01-03')['status'],'unavailable')

if __name__=='__main__':unittest.main()

class TimelineIntegrityTests(unittest.TestCase):
    def test_cumulative_source_is_converted_without_fabricated_missing_amount(self):
        from scripts.real_chart_engine import fetch_real_timeline
        source={'data':{'sh600519':{'data':{'date':'20260918','data':['0930 10 100 100000','0931 11 150 155000','0932 12 180','1530 12 180 155000']},'qt':{'sh600519':['','','','','9']}}}}
        with patch('scripts.verified_sources.request_json',return_value=source):r=fetch_real_timeline('sh600519')
        self.assertEqual(len(r['items']),3)
        self.assertEqual(r['items'][1]['volume'],50)
        self.assertAlmostEqual(r['items'][1]['amount_yi'],.00055)
        self.assertIsNone(r['items'][2]['amount_yi']);self.assertIsNone(r['items'][2]['avg_price'])
        with patch('scripts.verified_sources.request_json',side_effect=OSError('test unavailable')):r=fetch_real_timeline('sh600519')
        self.assertEqual(r['status'],'unavailable');self.assertIsNone(r['pre_close']);self.assertEqual(r['items'],[])
