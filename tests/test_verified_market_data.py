"""隔离数据库与确定性来源样例；不触及工作区行情库，不调用外网。"""
import copy
import importlib
import json
import tempfile
import threading
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import stock_db
from scripts.market_history import fetch_daily_history, canonical_code
from scripts import history_service, shareholder_actions


def bar(day, price=10):
    return [day, str(price), str(price + 1), str(price + 2), str(price - 1), '1234']


def pages(code, values):
    data = iter(values)
    return lambda url: {'code': 0, 'data': {code: {'day': next(data)}}}


def history(code, price=10):
    return fetch_daily_history(code, transport=pages(code, [[bar('2026-09-18', price)], []]), today=date(2026, 9, 19))


class HistoryTests(unittest.TestCase):
    def test_paging_and_more_than_5000_bars(self):
        begin = date(1990, 1, 1)
        raw = [bar((begin + timedelta(days=i)).isoformat()) for i in range(6001)]
        chunks = [raw[max(0, end-640):end] for end in range(len(raw), 0, -640)] + [[]]
        value = fetch_daily_history('sh600519', transport=pages('sh600519', chunks), today=date(2026, 9, 19))
        self.assertEqual(len(value['bars']), 6001)
        self.assertTrue(value['provider_history_complete'])
        self.assertEqual(value['bars'][0]['date'], '1990-01-01')
        self.assertIsNone(value['bars'][0]['amount_yi'])

    def test_short_page_does_not_mean_history_complete(self):
        value = fetch_daily_history('sz000001', transport=pages('sz000001', [[bar('2026-09-18')], [bar('1991-04-03')], []]))
        self.assertEqual(value['count'], 2)
        self.assertTrue(value['provider_history_complete'])

    def test_other_security_is_not_accepted(self):
        value = fetch_daily_history('sh600519', transport=pages('sz000001', [[bar('2026-09-18')]]))
        self.assertEqual(value['bars'], [])
        self.assertFalse(value['provider_history_complete'])

    def test_repeated_page_is_partial(self):
        value = fetch_daily_history('sh600519', transport=lambda _: {'data': {'sh600519': {'day': [bar('2026-09-18')]}}})
        self.assertEqual(value['status'], 'partial')
        self.assertEqual(value['count'], 1)

    def test_failure_and_future_invalid_prices(self):
        for raw in (bar('2099-01-01'), ['2026-09-18', '10', '20', '11', '9', '100']):
            self.assertEqual(fetch_daily_history('sh600519', transport=pages('sh600519', [[raw]]))['status'], 'unavailable')
        self.assertEqual(fetch_daily_history('sh600519', transport=lambda _: (_ for _ in ()).throw(OSError('offline')))['bars'], [])

    def test_code_normalization(self):
        self.assertEqual(canonical_code(' SH600519 '), 'sh600519')
        self.assertEqual(canonical_code('000001'), 'sz000001')
        with self.assertRaises(ValueError): canonical_code('../123')

    def test_malformed_source_is_unavailable(self):
        for payload in (None, [], {'data': []}):
            self.assertEqual(fetch_daily_history('sh600519', transport=lambda _: payload)['status'], 'unavailable')


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(stock_db, 'DB_PATH', str(Path(self.tmp.name)/'stock.db')), patch.object(stock_db, 'DATA_DIR', self.tmp.name)]
        for p in self.patches:p.start()
        stock_db.init_db()
        history_service._failures.clear()
        shareholder_actions._memo.clear()

    def tearDown(self):
        for p in self.patches:p.stop()
        self.tmp.cleanup()

    def test_legacy_pollution_never_rendered_and_symbols_isolated(self):
        stock_db.save_daily_klines('sh600519', [{'date':'2026-08-01','open':3.5,'close':3.6,'high':4,'low':3,'volume':100}])
        a=history_service.get_daily_history('sh600519', fetcher=lambda c: history(c,1000))
        b=history_service.get_daily_history('sz000001', fetcher=lambda c: history(c,10))
        self.assertEqual(a['bars'][0]['close'],1001)
        self.assertEqual(b['bars'][0]['close'],11)
        self.assertEqual(history_service.get_daily_history('sh600519',fetcher=lambda _: self.fail('cache not used'))['count'],1)

    def test_refresh_failure_keeps_complete_cache_with_stale_label(self):
        history_service.get_daily_history('sh600519',fetcher=history)
        failed=lambda c: dict(history(c),bars=[],count=0,provider_history_complete=False,status='unavailable',error='offline')
        value=history_service.get_daily_history('sh600519',refresh=True,fetcher=failed)
        self.assertEqual(value['status'],'stale')
        self.assertEqual(value['count'],1)

    def test_concurrent_first_load_only_fetches_once(self):
        called=[]
        def fetch(c):called.append(c);time.sleep(.03);return history(c)
        threads=[threading.Thread(target=history_service.get_daily_history,args=('sh600519',),kwargs={'fetcher':fetch}) for _ in range(5)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(called,['sh600519'])

    def test_recent_limit_and_unbounded_legacy_reader(self):
        stock_db.save_daily_klines('sz000001',[{'date':f'2026-09-{i:02}','open':10,'close':10,'high':11,'low':9,'volume':100} for i in range(1,5)])
        self.assertEqual([b['date'] for b in stock_db.load_daily_klines('sz000001',2)],['2026-09-03','2026-09-04'])
        self.assertEqual(len(stock_db.load_daily_klines('sz000001')),4)


def action(name='测试机构',direction='增持',code='600519',notice='2026-09-18',quantity=1):
    return dict(HOLDER_NAME=name,DIRECTION=direction,SECURITY_CODE=code,NOTICE_DATE=notice,CHANGE_NUM=quantity,END_DATE='2026-09-17',START_DATE='2026-09-16')


def snapshot(items):
    return shareholder_actions.fetch_actions(365,today=date(2026,9,19),transport=lambda _:{'success':True,'result':{'data':items,'count':len(items),'pages':1}})


class HolderTests(unittest.TestCase):
    def test_dual_behavior_dedup_and_same_source(self):
        value=snapshot([action(),action(),action('测试个人','减持')])
        stock=shareholder_actions.enrich_actions({'code':'sh600519'},value)
        self.assertEqual(stock['increase_holders'],['测试机构'])
        self.assertEqual(stock['decrease_holders'],['测试个人'])
        self.assertEqual(len(stock['shareholder_actions']),2)
        self.assertEqual(stock['shareholder_action_meta']['window_start'],'2025-09-20')

    def test_unknown_is_different_from_no_record(self):
        empty=snapshot([])
        failed=shareholder_actions.fetch_actions(365,transport=lambda _: {'success':False})
        self.assertEqual(empty['status'],'available')
        self.assertEqual(failed['status'],'unavailable')

    def test_future_zero_and_outside_window_excluded(self):
        value=snapshot([action(notice='2099-01-01'),action(quantity=0),action(notice='2025-01-01')])
        self.assertEqual(value['count'],0)

    def test_partial_page_not_reported_complete(self):
        value=shareholder_actions.fetch_actions(365,transport=lambda _:{'success':True,'result':{'data':[action()],'count':2,'pages':1}})
        self.assertFalse(value['complete'])

    def test_filter_before_pagination_and_and_combination(self):
        with patch.object(stock_db,'init_db'),patch.object(stock_db,'load_all_stocks_from_db',return_value=[]),patch.object(threading.Thread,'start'):
            server=importlib.import_module('scripts.stock_web_server')
        manager=server.StockDataManager.__new__(server.StockDataManager)
        manager._lock=threading.Lock()
        def stock(code,market,cap):
            return dict(code=code,raw_code=code[2:],name=code,market_code=market,board_code='main',is_csi50=False,is_csi100=False,price=10,change_pct=1,market_cap=cap,circulating_cap=cap,pe=10,top10_hold_pct=30,top10_circ_hold_pct=20,listing_years=10,dividend_count=1)
        manager.stocks_dict={s['code']:s for s in [stock('sh600519','sh',100),stock('sz000001','sz',90),stock('sh601288','sh',80)]}
        value=snapshot([action(code='601288'),action(code='601288',direction='减持'),action(code='000001')])
        with patch.object(server,'get_actions',return_value=value),patch('scripts.shareholder_engine.Top10ShareholdersEngine.enrich_stock_holder_metrics'):
            for direction in ('increase','decrease','both'):
                rows,stats=manager.filter_stocks({'shareholder_action':direction,'market':'sh','page_size':1})
                self.assertEqual(stats['matched_count'],1)
                self.assertEqual(rows[0]['code'],'sh601288')
            rows,stats=manager.filter_stocks({'shareholder_action':'all','page_size':1})
            self.assertEqual(stats['matched_count'],3)
            self.assertEqual(rows[0]['code'],'sh600519')


if __name__=='__main__':unittest.main()
