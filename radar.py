"""A-share companion to the US ETF Momentum Radar; Tonghuashun only."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
import os
import random
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import pandas as pd
import model
import strategy
import trading_calendar
from universe import ASSET_CLASS, CLUSTER_OF, CLUSTERS, CROSS_BORDER, ETF_GROUPS, UNIVERSE_VERSION

ROOT=Path(__file__).resolve().parent
TZ=dt.timezone(dt.timedelta(hours=8))
CACHE=ROOT/'data_cache/hithink_klines.json'
BASE='https://fuyao.aicubes.cn'
BENCHMARK='510300'
# Broad indices shown as market context (not a timing signal: index-trend timing lost money in the backtest).
INDEX_ETFS=[('510050','上证50'),('510300','沪深300'),('510500','中证500'),('512100','中证1000'),('159915','创业板'),('588000','科创50')]
# Percentile scores are only meaningful when nearly the whole universe is ranked together.
MIN_COVERAGE=0.9
AUTH_API_CODES=(2001,2003)

def api_key():
    value=os.environ.get('HITHINK_API_KEY','').strip()
    path=ROOT/'config/hithink_api_key.txt'
    if not value and path.exists():value=path.read_text().strip()
    if not value:raise RuntimeError('缺少 HITHINK_API_KEY；请配置本地文件或 GitHub Actions Secret。')
    return value

def completed_cutoff(now=None):
    now=now or dt.datetime.now(TZ)
    day=now.date()
    if now.time()<dt.time(15,15):day-=dt.timedelta(days=1)
    return trading_calendar.previous_trading_day(day)

class APIError(RuntimeError):
    def __init__(self,code,request_id=None):
        self.code=code
        super().__init__(f'同花顺业务错误 {code}；request_id={request_id or "未提供"}')

class AuthError(RuntimeError):
    """Credential rejected; abort the whole run instead of degrading to cache."""

def thscode_of(code):
    return code+('.SH' if code.startswith('5') else '.SZ')

def api_get(path,params,key,attempts=4):
    """GET with bounded exponential backoff + jitter; auth failures abort immediately."""
    req=urllib.request.Request(BASE+path+'?'+urllib.parse.urlencode(params),headers={'X-api-key':key,'User-Agent':'ETF-Momentum-Radar/1.0'})
    for attempt in range(attempts):
        last=attempt==attempts-1
        try:
            with urllib.request.urlopen(req,timeout=25) as response:p=json.load(response)
            if p.get('code')!=0:raise APIError(p.get('code'),p.get('request_id'))
            return p
        except APIError as exc:
            if exc.code not in (4001,5001,5002,5003) or last:raise
        except urllib.error.HTTPError as exc:
            if exc.code in (401,403):raise AuthError(f'同花顺认证失败 HTTP {exc.code}；请检查 HITHINK_API_KEY。') from None
            if exc.code not in (429,500,502,503,504) or last:raise RuntimeError(f'HTTP {exc.code}') from None
        except json.JSONDecodeError:
            if last:raise RuntimeError('同花顺返回内容无法解析') from None
        except (urllib.error.URLError,TimeoutError):
            if last:raise RuntimeError('同花顺连接超时或网络不可用') from None
        time.sleep(2**attempt+random.uniform(0,.5))
    raise RuntimeError('同花顺请求失败')

def fetch_days():
    """Calendar days of history: 250-session high lookback plus the whole paper track."""
    return min(1820,max(560,(completed_cutoff()-dt.date.fromisoformat(strategy.TRACK_START)).days+560))

def request_history(code,key,days=None,min_bars=121):
    days=days or fetch_days()
    cutoff=completed_cutoff()
    start=dt.datetime.combine(cutoff-dt.timedelta(days=days),dt.time(),TZ)
    end=dt.datetime.combine(cutoff,dt.time(23,59,59),TZ)
    thscode=thscode_of(code)
    p=api_get('/api/fund/market/historical',dict(thscode=thscode,interval='1d',start=int(start.timestamp()*1000),end=int(end.timestamp()*1000)),key)
    data=p.get('data') or {}
    if data.get('thscode')!=thscode:raise ValueError('接口标的与请求不一致')
    rows=normalize(data.get('item') or [],cutoff)
    if len(rows)<min_bars:raise ValueError(f'历史不足{min_bars}根：{len(rows)}')
    return dict(rows=rows,source='同花顺金融API',adjustment='qfq',fetched_at=dt.datetime.now(TZ).isoformat(timespec='seconds'),request_id=p.get('request_id'),cached=False)

def request_nav(code,key):
    """Latest published unit NAV (cross-border NAVs lag the close by 1-2 sessions)."""
    p=api_get('/api/fund/performance/nav',dict(thscode=thscode_of(code),range='month',nav_type='unit'),key)
    items=[i for i in (p.get('data') or {}).get('item') or [] if isinstance(i.get('nav_date'),(int,float)) and isinstance(i.get('unit_nav'),(int,float)) and i['unit_nav']>0]
    if not items:raise ValueError('无净值数据')
    item=max(items,key=lambda i:i['nav_date'])
    return dict(date=dt.datetime.fromtimestamp(item['nav_date']/1000,TZ).date().isoformat(),unit_nav=float(item['unit_nav']))

def normalize(items,cutoff):
    rows={}
    for item in items:
        timestamp=item.get('date_ms')
        if not isinstance(timestamp,(int,float)) or not math.isfinite(timestamp):continue
        day=dt.datetime.fromtimestamp(timestamp/1000,TZ).date()
        if day>cutoff:continue
        r={'date':day.isoformat()}
        for key in ('open','high','low','close'):r[key]=item.get(key+'_price')
        if not all(isinstance(r[k],(int,float)) and math.isfinite(r[k]) and r[k]>0 for k in ('open','high','low','close')):continue
        if r['high']<max(r['close'],r['open'],r['low']) or r['low']>min(r['close'],r['open']):continue
        r.update(volume=item.get('volume'),turnover=item.get('turnover'))
        rows[r['date']]=r
    return [rows[k] for k in sorted(rows)]

def premium(bars,nav):
    """Close on the NAV date over unit NAV. qfq equals the raw close unless a distribution
    happened after that date, which the 1-2 session NAV lag makes negligible."""
    if not nav or not bars:return None
    close=next((b['close'] for b in reversed(bars) if b['date']==nav.get('date')),None)
    return close/nav['unit_nav']-1 if close else None

def _num(v):
    v=float(v)
    return v if math.isfinite(v) else None

def analyze_full(entries):
    """Rows for every universe ETF, the latest session and the market regime.

    The published score is model.PROD (V1 without the overheat penalty, with label
    hysteresis); see model.py and backtest.py for why.
    """
    universe=[(group,code,name) for group,items in ETF_GROUPS.items() for code,name in items]
    benchmark=entries.get(BENCHMARK,{}).get('rows',[])
    latest=benchmark[-1]['date'] if benchmark else None
    panel=model.build_panel(entries,BENCHMARK) if latest else None
    if panel is not None:
        # Production also requires the ETF's own last bar to be the benchmark's session.
        for t,e in entries.items():
            bars=e.get('rows') or []
            if not bars or bars[-1]['date']!=latest:panel['eligible'].loc[latest,t]=False
        prod=model.score_panel(panel,model.PROD,ASSET_CLASS,CLUSTERS)
        absolute=model.absolute_momentum(panel)
        near=strategy.near_high(panel)
        state=model.regime(panel,ASSET_CLASS).loc[latest]
        regime=dict(state=state['state'],breadth60=_num(state['breadth60']),bench_r120=_num(state['bench_r120']),hurdle=float(state['hurdle']),indices=index_overview(panel,latest))
    else:
        regime=None
    rows=[]
    for group,code,name in universe:
        e=entries.get(code,{})
        bars=e.get('rows',[])
        r=dict(ticker=code,name=name,group=group,asset_class=ASSET_CLASS.get(code,'equity'),cluster=CLUSTER_OF.get(code),date=bars[-1]['date'] if bars else None,source=e.get('source','同花顺金融API'),cached=e.get('cached',False),setup='Data unavailable',eligible=False,score=None)
        if code in CROSS_BORDER:
            r['premium']=premium(bars,e.get('nav'));r['nav_date']=(e.get('nav') or {}).get('date')
        if panel is None or code not in panel['eligible'] or not panel['eligible'].at[latest,code]:
            rows.append(r);continue
        g=lambda k:float(panel[k].at[latest,code])
        last,atr,ema20=g('close'),g('atr14'),g('ema20')
        for n in (20,60,120):
            r[f'r{n}']=g(f'r{n}')
            r[f'rs{n}']=r[f'r{n}']-float(panel[f'r{n}'].at[latest,BENCHMARK])
        stop=min(ema20,g('low10'))-.5*atr
        high20=g('high20_prev')
        amounts=pd.to_numeric(pd.Series([b.get('turnover') for b in bars[-20:]]),errors='coerce')
        r.update(close=last,ema20=ema20,sma50=g('sma50'),sma120=g('sma120'),atr14=atr,atr_pct=atr/last,dist_ema_atr=g('dist_ema_atr'),vol20_ann=g('vol20'),from_high120=g('from_high120'),high20_prev=high20,breakout_trigger=high20+.1*atr,pullback_low=ema20-.5*atr,pullback_high=ema20+.5*atr,stop_ref=stop,stop_pct=stop/last-1,adtv20=float(amounts.mean()) if len(amounts)==20 and amounts.notna().all() else None,trend_aligned=bool(panel['trend_aligned'].at[latest,code]),eligible=True,
                 setup=prod['setup'].at[latest,code],score=float(prod['score'].at[latest,code]),
                 abs_momentum=bool(absolute.at[latest,code]),near_high250=_num(near.at[latest,code]),
                 history=[dict(date=b['date'],close=b['close']) for b in bars[-120:]])
        rows.append(r)
    rows.sort(key=lambda r:r['score'] if r['score'] is not None else -math.inf,reverse=True)
    weekly=weekly_summary(panel,latest) if panel is not None else None
    return rows,latest,regime,weekly

def analyze(entries):
    rows,latest,regime,_=analyze_full(entries)
    return rows,latest,regime

def index_overview(panel,latest):
    """Trend context for the broad-index ETFs: distance to the 250-session high and
    position versus the 50/120/250-session averages."""
    close=panel['close'];near=strategy.near_high(panel);sma250=close.rolling(250,min_periods=250).mean()
    out=[]
    for code,name in INDEX_ETFS:
        if code not in close or pd.isna(close.at[latest,code]):continue
        c=float(close.at[latest,code])
        ma={k:_num(v) for k,v in (('50',panel['sma50'].at[latest,code]),('120',panel['sma120'].at[latest,code]),('250',sma250.at[latest,code]))}
        above={k:(v is not None and c>v) for k,v in ma.items()}
        if all(v is not None for v in ma.values()) and c>ma['50']>ma['120'] and c>ma['250']:trend='up'
        elif all(v is not None for v in ma.values()) and c<ma['50']<ma['120'] and c<ma['250']:trend='down'
        else:trend='range'
        out.append(dict(ticker=code,name=name,near_high=_num(near.at[latest,code]),above=above,trend=trend,
                        r20=_num(panel['r20'].at[latest,code]),r60=_num(panel['r60'].at[latest,code])))
    return out

def weekly_summary(panel,latest):
    """Current/previous weekly picks and the out-of-sample paper track (see strategy.py)."""
    cal=list(panel['close'].index)
    ends=strategy.week_ends(cal)
    nh=strategy.near_high(panel)
    if nh.loc[latest].notna().sum()==0:return None
    is_end=latest in ends
    past=[d for d in ends if d<latest]
    reb=latest if is_end else (past[-1] if past else None)
    if reb is None:return None
    prev=[d for d in ends if d<reb]
    def entry(code,near,r60):return dict(ticker=code,near_high=near,r60=r60 if math.isfinite(r60) else None)
    current=[entry(*x) for x in strategy.ranking(panel,ASSET_CLASS,reb)[:strategy.TOP_N]]
    previous=strategy.picks(panel,ASSET_CLASS,prev[-1]) if prev else []
    cur=[x['ticker'] for x in current]
    out=dict(rule=strategy.RULE_VERSION,top_n=strategy.TOP_N,lookback=strategy.LOOKBACK,cost=strategy.COST,
             rebalance_date=reb,holding_from='next' if is_end else 'this',picks=current,previous_date=prev[-1] if prev else None,
             added=[c for c in cur if c not in previous],removed=[c for c in previous if c not in cur],
             provisional=None if is_end else [entry(*x) for x in strategy.ranking(panel,ASSET_CLASS,latest)[:strategy.TOP_N]],
             track_start=strategy.TRACK_START)
    sim=strategy.simulate(panel,ASSET_CLASS,strategy.TRACK_START)
    if len(sim['returns']):
        navs=pd.DataFrame({'s':(1+sim['returns']).cumprod(),'b':(1+sim['benchmark']).cumprod(),'e':(1+sim['equal_weight']).cumprod()})
        out['track']=dict(days=len(navs),weeks=len(sim['holdings']),strategy=strategy.stats(sim['returns']),benchmark=strategy.stats(sim['benchmark']),
                          equal_weight=strategy.stats(sim['equal_weight']),
                          nav=[dict(date=d,s=round(r.s,5),b=round(r.b,5),e=round(r.e,5)) for d,r in navs.iterrows()],
                          holdings=[dict(date=d,picks=c) for d,c in sim['holdings'][-12:]])
    else:
        out['track']=None
    return out

def metrics(entries):
    rows,latest,_=analyze(entries)
    return rows,latest

def snapshot_baseline(payload):
    return {key: payload.get(key) for key in ('asof', 'model', 'provider', 'benchmark', 'universe_version')} | {
        'rows': [{key: row.get(key) for key in ('ticker', 'score', 'setup', 'eligible', 'cached')}
                 for row in payload.get('rows', [])]}


def attach_comparison(payload, previous):
    """Compare published observations; never reconstruct past adjusted prices."""
    payload['comparison'] = None
    baseline = previous if previous and previous.get('asof', '') < payload['asof'] else (
        previous.get('previous_snapshot') if previous and previous.get('asof') == payload['asof'] else None)
    payload['previous_snapshot'] = snapshot_baseline(baseline) if baseline else None
    if not baseline or not baseline.get('asof') or baseline['asof'] >= payload['asof']:
        return
    if any(baseline.get(k) != payload.get(k) for k in ('model', 'provider', 'benchmark', 'universe_version')):
        return
    old = {r['ticker']: r for r in baseline['rows'] if r.get('eligible')}
    new = {r['ticker']: r for r in payload['rows'] if r.get('eligible')}
    if not old or old.keys() != new.keys() or any(r.get('cached') for r in [*old.values(), *new.values()]):
        return
    if any(not isinstance(r.get('score'), (int,float)) or not math.isfinite(r['score']) for r in [*old.values(), *new.values()]):
        return
    def ranks(rows):
        return {t: 1 + sum(r['score'] > row['score'] for r in rows.values()) for t, row in rows.items()}
    before, after = ranks(old), ranks(new)
    strong = {'Momentum', 'Strong / wait pullback'}
    payload['comparison'] = {'asof': baseline['asof'], 'changes': {
        t: {'rank_delta': before[t] - after[t],
            'entered_strong': new[t]['setup'] in strong and old[t]['setup'] not in strong,
            'broken': new[t]['setup'] == 'Avoid / broken' and old[t]['setup'] != 'Avoid / broken'}
        for t in new}}


def published_snapshot():
    from html.parser import HTMLParser
    class DatasetParser(HTMLParser):
        active = False
        parts = None
        def handle_starttag(self, tag, attrs):
            if tag == 'script' and dict(attrs).get('id') == 'dataset':
                self.active = True
                self.parts = []
        def handle_endtag(self, tag):
            if tag == 'script': self.active = False
        def handle_data(self, data):
            if self.active: self.parts.append(data)
    try:
        with urllib.request.urlopen('https://kazenari99.github.io/a-etf-dashboard/', timeout=20) as response:
            page = response.read(5_000_000).decode('utf-8')
        parser = DatasetParser(); parser.feed(page)
        return json.loads(''.join(parser.parts or []))
    except Exception as exc:
        print(f'Previous published snapshot unavailable: {type(exc).__name__}; comparison omitted')
        return None


def publish(payload):
    out=ROOT/'reports';out.mkdir(exist_ok=True)
    encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False)
    template=(ROOT/'dashboard.html').read_text()
    for marker,file in (('__STYLE__','radar.css'),('__SCRIPT__','radar.js')):template=template.replace(marker,(ROOT/file).read_text())
    page=template.replace('__DATA__',encoded.replace('<','\\u003c'))
    (ROOT/'index.html').write_text(page,encoding='utf-8')
    (out/'etf_dashboard.html').write_text(page,encoding='utf-8')
    (out/'etf_data.json').write_text(encoded,encoding='utf-8')
    return out

def check_coverage(rows):
    eligible=sum(r['eligible'] for r in rows)
    if not eligible:raise RuntimeError('无日期对齐且满121根的同花顺数据，保留已发布页面。')
    if eligible<math.ceil(len(rows)*MIN_COVERAGE):
        raise RuntimeError(f'有效样本 {eligible}/{len(rows)} 低于 {MIN_COVERAGE:.0%}，百分位评分口径不可比，保留已发布页面。')

def build(offline=False,render=False):
    cache=json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if render:
        missing=[c for items in ETF_GROUPS.values() for c,_ in items if not cache.get(c,{}).get('rows')]
        if missing:raise RuntimeError(f'缓存缺少 {len(missing)} 只观察池ETF，无法离线重绘，请联网运行。')
        if len(cache.get(BENCHMARK,{}).get('rows',[]))<strategy.LOOKBACK+10:raise RuntimeError('缓存历史不足250个交易日，无法计算周度清单，请联网运行。')
        payload=json.loads((ROOT/'reports/etf_data.json').read_text())
        previous=dict(payload)
        payload['rows'],payload['asof'],payload['regime'],payload['weekly']=analyze_full(cache)
        check_coverage(payload['rows'])
        payload['universe_version']=UNIVERSE_VERSION
        attach_comparison(payload,previous)
        publish(payload);return
    entries={};errors=[];key=None if offline else api_key()
    tasks=[c for items in ETF_GROUPS.values() for c,_ in items]
    for i,code in enumerate(tasks,1):
        old=cache.get(code,{})
        entry=dict(old,cached=True) if old.get('rows') else dict(rows=[],source='同花顺金融API',cached=False)
        if not offline:
            try:
                fresh=request_history(code,key)
                if not old.get('rows') or fresh['rows'][-1]['date']>=old['rows'][-1]['date']:entry=fresh
                else:errors.append(f'{code}：上游日期落后于缓存，保留较新批次。')
            except AuthError:raise
            except APIError as exc:
                if exc.code in AUTH_API_CODES:raise
                errors.append(f'{code}：{exc}')
            except Exception as exc:errors.append(f'{code}：{type(exc).__name__}: {exc}')
            time.sleep(.4)
        entries[code]=entry
        print(f'同花顺 {i}/{len(tasks)} {code} {len(entry["rows"])} bars',flush=True)
    if not offline:
        for code in CROSS_BORDER:
            try:entries[code]['nav']=request_nav(code,key)
            except AuthError:raise
            except Exception as exc:errors.append(f'{code} 净值：{type(exc).__name__}: {exc}；溢价不显示。')
            time.sleep(.4)
    rows,latest,regime,weekly=analyze_full(entries)
    check_coverage(rows)
    now=dt.datetime.now(TZ)
    if not trading_calendar.known(now.year):errors.append(f'trading_calendar.py 未收录{now.year}年休市安排，仅按工作日判断截止日；交易所公布后请补充。')
    payload=dict(rows=rows,asof=latest,generated=now.isoformat(timespec='seconds'),errors=errors,offline=offline,provider='同花顺金融API',benchmark='510300',model=model.PROD.name,regime=regime,weekly=weekly,universe_version=UNIVERSE_VERSION,requested_cutoff=completed_cutoff(now).isoformat())
    attach_comparison(payload, published_snapshot() if not offline else None)
    out=publish(payload)
    if not offline:
        CACHE.parent.mkdir(exist_ok=True);tmp=CACHE.with_suffix('.tmp');tmp.write_text(json.dumps(entries,ensure_ascii=False));tmp.replace(CACHE)
        archive=ROOT/'archive'/now.strftime('%Y-%m-%d')/now.strftime('%H%M%S');archive.mkdir(parents=True,exist_ok=True)
        for name in ('etf_dashboard.html','etf_data.json'):(archive/name).write_bytes((out/name).read_bytes())
    print(json.dumps(dict(asof=latest,total=len(rows),eligible=sum(r['eligible'] for r in rows),cached=sum(r['cached'] for r in rows),errors=len(errors))))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');parser.add_argument('--render',action='store_true');args=parser.parse_args();build(args.offline,args.render)
