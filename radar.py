"""A-share companion to the US ETF Momentum Radar; Tonghuashun only."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import numpy as np
import pandas as pd
from etf_dashboard import ETF_GROUPS

ROOT=Path(__file__).resolve().parent
TZ=dt.timezone(dt.timedelta(hours=8))
CACHE=ROOT/'data_cache/hithink_klines.json'
BASE='https://fuyao.aicubes.cn'
BENCHMARK='510300'

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
    while day.weekday()>4:day-=dt.timedelta(days=1)
    return day

class APIError(RuntimeError):
    def __init__(self,code,request_id=None):
        self.code=code
        super().__init__(f'同花顺业务错误 {code}；request_id={request_id or "未提供"}')

def request_history(code,key):
    cutoff=completed_cutoff()
    start=dt.datetime.combine(cutoff-dt.timedelta(days=370),dt.time(),TZ)
    end=dt.datetime.combine(cutoff,dt.time(23,59,59),TZ)
    thscode=code+('.SH' if code.startswith('5') else '.SZ')
    params=dict(thscode=thscode,interval='1d',start=int(start.timestamp()*1000),end=int(end.timestamp()*1000))
    req=urllib.request.Request(BASE+'/api/fund/market/historical?'+urllib.parse.urlencode(params),headers={'X-api-key':key,'User-Agent':'ETF-Momentum-Radar/1.0'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req,timeout=25) as response:p=json.load(response)
            if p.get('code')!=0:raise APIError(p.get('code'),p.get('request_id'))
            data=p.get('data') or {}
            if data.get('thscode')!=thscode:raise ValueError('接口标的与请求不一致')
            rows=normalize(data.get('item') or [],cutoff)
            if len(rows)<121:raise ValueError(f'历史不足121根：{len(rows)}')
            return dict(rows=rows,source='同花顺金融API',adjustment='qfq',fetched_at=dt.datetime.now(TZ).isoformat(timespec='seconds'),request_id=p.get('request_id'),cached=False)
        except APIError as exc:
            if exc.code not in (4001,5001,5002,5003) or attempt==3:raise
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt==3:raise RuntimeError(f'HTTP {exc.code}') from None
        except (urllib.error.URLError,TimeoutError):
            if attempt==3:raise RuntimeError('同花顺连接超时或网络不可用') from None
        time.sleep(2**attempt)
    raise RuntimeError('同花顺请求失败')

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

def atr14(frame):
    prev=frame['close'].shift(1)
    tr=pd.concat([frame['high']-frame['low'],(frame['high']-prev).abs(),(frame['low']-prev).abs()],axis=1).max(axis=1)
    return tr.rolling(14).mean()

def metrics(entries):
    latest=max((e['rows'][-1]['date'] for e in entries.values() if e.get('rows')),default=None)
    benchmark=entries.get(BENCHMARK,{}).get('rows',[])
    rows=[]
    for group,items in ETF_GROUPS.items():
        for code,name in items:
            e=entries.get(code,{})
            bars=e.get('rows',[])
            r=dict(ticker=code,name=name,group=group,date=bars[-1]['date'] if bars else None,source=e.get('source','同花顺金融API'),cached=e.get('cached',False),setup='Data unavailable',eligible=False,score=None)
            # A score compares the same 121 sessions across the whole universe.
            if len(bars)<121 or len(benchmark)<121 or bars[-1]['date']!=latest or [b['date'] for b in bars[-121:]] != [b['date'] for b in benchmark[-121:]]:
                rows.append(r);continue
            f=pd.DataFrame(bars)
            close=f['close'].astype(float);high=f['high'].astype(float);low=f['low'].astype(float)
            last=float(close.iloc[-1]);atr=float(atr14(f).iloc[-1])
            ema20=float(close.ewm(span=20,adjust=False).mean().iloc[-1]);sma50=float(close.rolling(50).mean().iloc[-1]);sma120=float(close.rolling(120).mean().iloc[-1])
            for n in (20,60,120):
                r[f'r{n}']=last/float(close.iloc[-1-n])-1
                r[f'rs{n}']=r[f'r{n}']-(benchmark[-1]['close']/benchmark[-1-n]['close']-1)
            distance=(last-ema20)/atr if atr else None
            high20=float(high.iloc[-21:-1].max());low10=float(low.iloc[-10:].min());stop=min(ema20,low10)-.5*atr
            amounts=pd.to_numeric(f['turnover'].tail(20),errors='coerce')
            r.update(close=last,ema20=ema20,sma50=sma50,sma120=sma120,atr14=atr,atr_pct=atr/last,dist_ema_atr=distance,vol20_ann=float(close.pct_change().iloc[-20:].std()*math.sqrt(252)),from_high120=last/float(high.iloc[-120:].max())-1,high20_prev=high20,breakout_trigger=high20+.1*atr,pullback_low=ema20-.5*atr,pullback_high=ema20+.5*atr,stop_ref=stop,stop_pct=stop/last-1,adtv20=float(amounts.mean()) if amounts.notna().all() else None,trend_aligned=last>ema20>sma50>sma120,eligible=distance is not None,setup='Avoid / broken',history=[dict(date=b['date'],close=b['close']) for b in bars[-120:]])
            strong=all(r[f'r{n}']>0 for n in (20,60,120)) and r['trend_aligned'] and r['rs60']>0
            if strong:r['setup']='Momentum' if distance<=2.5 else 'Strong / wait pullback'
            elif r['r60']>0 and r['r120']>0 and last>sma50:r['setup']='Pullback watch'
            rows.append(r)
    eligible=[r for r in rows if r['eligible']]
    if eligible:
        df=pd.DataFrame(eligible)
        scores=sum(w*df[f'r{n}'].rank(pct=True) for n,w in ((20,.30),(60,.40),(120,.30)))*100
        scores+=np.where(df['trend_aligned'],5,0)
        scores+=np.where(df['rs60']>0,3,0)
        scores-=np.where(df['dist_ema_atr']>2.5,8,0)
        for r,value in zip(eligible,scores):r['score']=float(value)
    return sorted(rows,key=lambda r:r['score'] if r['score'] is not None else -math.inf,reverse=True),latest

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

def build(offline=False,render=False):
    cache=json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if render:
        payload=json.loads((ROOT/'reports/etf_data.json').read_text())
        payload['rows'],payload['asof']=metrics(cache)
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
            except APIError as exc:
                if exc.code in (2001,2003):raise
                errors.append(f'{code}：{exc}')
            except Exception as exc:errors.append(f'{code}：{type(exc).__name__}: {exc}')
            time.sleep(.4)
        entries[code]=entry
        print(f'同花顺 {i}/{len(tasks)} {code} {len(entry["rows"])} bars',flush=True)
    rows,latest=metrics(entries)
    if not any(r['eligible'] for r in rows):raise RuntimeError('无日期对齐且满121根的同花顺数据，保留已发布页面。')
    now=dt.datetime.now(TZ)
    payload=dict(rows=rows,asof=latest,generated=now.isoformat(timespec='seconds'),errors=errors,offline=offline,provider='同花顺金融API',benchmark='510300',model='us-momentum-v1',requested_cutoff=completed_cutoff(now).isoformat())
    out=publish(payload)
    if not offline:
        CACHE.parent.mkdir(exist_ok=True);tmp=CACHE.with_suffix('.tmp');tmp.write_text(json.dumps(entries,ensure_ascii=False));tmp.replace(CACHE)
        archive=ROOT/'archive'/now.strftime('%Y-%m-%d')/now.strftime('%H%M%S');archive.mkdir(parents=True,exist_ok=True)
        for name in ('etf_dashboard.html','etf_data.json'):(archive/name).write_bytes((out/name).read_bytes())
    print(json.dumps(dict(asof=latest,total=len(rows),eligible=sum(r['eligible'] for r in rows),cached=sum(r['cached'] for r in rows),errors=len(errors))))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');parser.add_argument('--render',action='store_true');args=parser.parse_args();build(args.offline,args.render)
