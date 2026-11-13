"""Locally hosted trading terminal API. No broker secrets are stored on disk.
Run: python -m uvicorn app.api.server:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations
import asyncio,os,uuid,json,re,secrets,hashlib,logging,time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
from typing import Any
from zoneinfo import ZoneInfo
import pandas as pd
from fastapi import FastAPI,HTTPException,WebSocket,WebSocketDisconnect,Body,Query,Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse,JSONResponse
from urllib.parse import urlparse
from app.brokers.oauth import authorization_url, exchange_code
from pydantic import BaseModel,Field,field_validator
from app.brokers import mock,zerodha,upstox,groww,fyers,flattrade,finvasia   # registration
from app.brokers.base import (Capability,InstrumentKey,OrderRequest,BrokerError,AuthError,
                              UnsupportedCapability,capability_matrix,get_adapter_class)
from app.brokers.common import dt
from app.database import store
from app import core_vault
from app.api import owner_security as OWNER
from app.market_data.hub import MarketHub
from app.market_data.history import fetch_history,sync_history
from app.market_data.backfill import BackfillManager
from app.strategies.rules import RuleStrategy,DEFAULT_RULES,signal_from_frame
from app.backtesting.engine import run_backtest,BacktestConfig
from app.indicators.engine import compute_indicator,REGISTRY
from app.indicators.catalog import inventory,implemented
from app.option_chain.normalize import normalize_chain
from app.option_chain.analytics import Leg,payoff_curve,analyze_payoff,pcr,max_pain
from app.order_execution.executor import OrderExecutor
from app.risk_management.engine import RiskEngine,RiskLimits,OrderIntent

IST=ZoneInfo('Asia/Kolkata')
SESSIONS={}
RISK=RiskEngine(RiskLimits(max_order_qty=10000,max_order_notional=1_000_000,max_daily_loss=10000,
                           max_daily_trades=50,max_open_positions=10,max_capital_allocation=2_000_000))
EXECUTOR=OrderExecutor(RISK)
HUB=MarketHub(SESSIONS)
BACKFILL=BackfillManager(SESSIONS,store)
APP_TOKEN=os.environ.get('APP_LOCAL_TOKEN','')
OAUTH_PENDING:dict[str,dict]={}
LOG=logging.getLogger('tradeverse.oauth')

def _secret_check(value):
    if APP_TOKEN and value!=APP_TOKEN:raise HTTPException(401,'Invalid local application token')

def _account(account):
    if account not in SESSIONS:raise HTTPException(409,'Broker not connected. Sign in first.')
    return SESSIONS[account]

def _key(exchange,symbol,segment='EQ'):return InstrumentKey(exchange,symbol,segment)

def _to_json(value):return jsonable_encoder(value)

def _broker_error(e):
    if isinstance(e,AuthError):return HTTPException(401,str(e))
    if isinstance(e,UnsupportedCapability):return HTTPException(422,str(e))
    if isinstance(e,BrokerError):return HTTPException(502,str(e))
    return HTTPException(400,str(e))

class ConnectIn(BaseModel):
    broker:str
    account_id:str=Field(min_length=1,max_length=80)
    credentials:dict[str,Any]=Field(default_factory=dict)

class AccountVerifyIn(BaseModel):
    account:str=Field(min_length=1,max_length=160)

class OrderIn(BaseModel):
    account:str
    exchange:str
    symbol:str
    segment:str='EQ'
    side:str
    qty:int=Field(gt=0)
    order_type:str='LIMIT'
    product:str='MIS'
    price:float|None=None
    trigger_price:float|None=None
    mode:str='paper'
    client_order_id:str=''
    strategy_id:str='manual'
    is_exit:bool=False
    @field_validator('side')
    @classmethod
    def side_valid(cls,value):
        if value not in ('BUY','SELL'):raise ValueError('Must be BUY or SELL')
        return value

class BacktestIn(BaseModel):
    account:str
    exchange:str
    symbol:str
    segment:str='EQ'
    interval:str='1m'
    definition:dict=Field(default_factory=lambda:dict(DEFAULT_RULES))
    initial_capital:float=Field(default=100000,gt=0)
    slippage_bps:float=Field(default=1,ge=0)
    candles:list[dict]|None=None

class StrategyIn(BaseModel):
    id:str|None=None
    name:str=Field(min_length=1,max_length=120)
    account:str
    exchange:str
    symbol:str
    segment:str='EQ'
    interval:str='1m'
    mode:str='paper'
    definition:dict=Field(default_factory=lambda:dict(DEFAULT_RULES))

@asynccontextmanager
async def lifespan(app):
    OWNER.validate_production_config()
    store.init_db()
    # Restore only sessions that can be verified against the broker. Never restore strategy execution.
    for account,entry in core_vault.read_all().items():
        if not isinstance(entry,dict) or entry.get('broker') not in capability_matrix():continue
        adapter=None
        try:
            adapter=get_adapter_class(entry['broker'])(entry['account_id'])
            await adapter.authenticate(entry['credentials'])
            if await adapter.verify_session():
                if hasattr(adapter,'remember_instruments'):adapter.remember_instruments(store.restore_instruments(account))
                SESSIONS[account]=adapter
            else:
                await adapter.close()
        except Exception:
            if adapter is not None:
                with __import__('contextlib').suppress(Exception):await adapter.close()
    # Never automatically restart live orders after a crash or token expiry.
    for item in store.strategies():
        if item['active']:store.change_strategy(item['id'],False)
    yield
    await BACKFILL.stop_all()
    await HUB.close()
    for session in list(SESSIONS.values()):
        with __import__('contextlib').suppress(Exception):await session.close()

app=FastAPI(title='TradeVerse Pro API',version='0.3.0',lifespan=lifespan,
            docs_url=None if OWNER.production() else '/docs',
            redoc_url=None if OWNER.production() else '/redoc',
            openapi_url=None if OWNER.production() else '/openapi.json')
app.add_middleware(CORSMiddleware,allow_origins=OWNER.allowed_frontend_origins(),allow_credentials=False,
                   allow_methods=['GET','POST','PUT','DELETE','OPTIONS'],
                   allow_headers=['Content-Type','Authorization','X-Local-Token'])

class OwnerLoginIn(BaseModel):
    password:str=Field(min_length=1,max_length=512)

@app.post('/api/owner/login')
def owner_login(body:OwnerLoginIn,request:Request):
    if not OWNER.production():
        raise HTTPException(404,'Owner cloud login is only enabled in production')
    OWNER.check_login_rate(request.client.host if request.client else 'unknown')
    if not OWNER.verify_password(body.password,os.environ['TRADEVERSE_OWNER_PASSWORD_HASH']):
        raise HTTPException(401,'Invalid owner password')
    value,seconds=OWNER.issue_owner_token()
    return {'access_token':value,'token_type':'bearer','expires_in':seconds}

@app.post('/api/owner/logout')
def owner_logout(request:Request):
    OWNER.revoke_owner_token(OWNER.bearer_from_header(request.headers.get('authorization','')))
    return {'signed_out':True}

@app.post('/api/owner/ws-ticket')
def owner_ws_ticket(request:Request):
    owner=OWNER.verify_owner_token(OWNER.bearer_from_header(request.headers.get('authorization','')))
    return {'ticket':OWNER.issue_ws_ticket(owner)}

@app.get('/api/status')
def application_status():
    return {'ok':True,'connected_accounts':len(SESSIONS),'live_trading_enabled':RISK.limits.live_trading_enabled,
            'database':'sqlite' if store.URL.startswith('sqlite') else 'postgresql','version':'0.3.0'}

@app.get('/api/owner/session')
def owner_session():
    # This route is guarded by middleware in production.
    return {'authenticated':True,'owner':'local_owner'}

@app.middleware('http')
async def api_auth_guard(request,call_next):
    path=request.url.path
    if request.method=='OPTIONS':
        return await call_next(request)
    if OWNER.production() and path.startswith('/api/') and path not in ('/api/health','/api/owner/login') and not path.startswith('/api/auth/callback/'):
        try:
            OWNER.verify_owner_token(OWNER.bearer_from_header(request.headers.get('authorization','')))
        except HTTPException as exc:
            return JSONResponse({'detail':exc.detail},status_code=exc.status_code,headers={'Cache-Control':'no-store'})
    elif not OWNER.production() and path.startswith('/api/') and not path.startswith('/api/auth/callback/') and APP_TOKEN and request.headers.get('x-local-token')!=APP_TOKEN:
        return JSONResponse({'detail':'Invalid local application token'},status_code=401)
    response=await call_next(request)
    if path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    if OWNER.production():
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    return response

@app.get('/api/health')
def health():
    if OWNER.production():return {'ok':True,'version':'0.3.0'}
    return {'ok':True,'local_only':True,'connected_accounts':len(SESSIONS),
            'live_trading_enabled':RISK.limits.live_trading_enabled,
            'database':'sqlite' if store.URL.startswith('sqlite') else 'postgresql',
            'version':'0.3.0'}


@app.get('/api/preferences/{kind}')
def get_preference(kind:str):
    if kind not in ('theme','workspace','recent_searches','last_broker'):
        raise HTTPException(404,'Unknown preference')
    return store.get_preference('local_owner',kind) or {'data':{},'revision':0}

@app.put('/api/preferences/{kind}')
def put_preference(kind:str, body:dict=Body(...)):
    if kind not in ('theme','workspace','recent_searches','last_broker'):
        raise HTTPException(404,'Unknown preference')
    if len(__import__('json').dumps(body))>100_000:
        raise HTTPException(413,'Preference exceeds 100 KB')
    return store.put_preference('local_owner',kind,body)

@app.get('/api/accounts/combined')
async def combined_accounts():
    result=[]
    for account,adapter in SESSIONS.items():
        row={'account':account,'broker':adapter.broker_id,'read_only':bool(getattr(adapter,'read_only',False))}
        for name,method,cap in [('funds','get_funds',Capability.FUNDS),('orders','get_orders',Capability.PLACE_ORDER),('positions','get_positions',Capability.POSITIONS)]:
            if not adapter.supports(cap):
                row[name]=[] if name!='funds' else None
                continue
            try:row[name]=_to_json(await getattr(adapter,method)())
            except Exception as ex:row[name+'_error']=type(ex).__name__;row[name]=[] if name!='funds' else None
        result.append(row)
    return result

@app.get('/api/feeds/status')
def feed_status():
    return HUB.status()

@app.get('/api/brokers')
def brokers():return capability_matrix()

@app.get('/api/accounts')
def accounts():
    stored=store.accounts()
    return [{**a,'connected':a['id'] in SESSIONS, 'read_only':bool(getattr(SESSIONS.get(a['id']),'read_only',False))} for a in stored]

@app.post('/api/accounts/connect')
async def connect(request:ConnectIn):
    if request.broker not in capability_matrix():raise HTTPException(404,'Unknown broker')
    if request.broker=='mock' and os.getenv('ALLOW_MOCK_BROKER','yes').lower()!='yes':raise HTTPException(403,'Mock disabled')
    account=f'{request.broker}:{request.account_id}'
    if account in SESSIONS:await disconnect(account)
    adapter=get_adapter_class(request.broker)(request.account_id)
    try:
        profile=await adapter.authenticate(request.credentials)
        # Rehydrate saved broker-specific token mappings without persisting credentials.
        adapter.remember_instruments(store.restore_instruments(account)) if hasattr(adapter,'remember_instruments') else None
        SESSIONS[account]=adapter
        store.store_account(account,request.broker,profile.name,profile.account_id)
        store.log_event('broker_connected',account,{'broker':request.broker})
        try:core_vault.save_session(account,request.broker,request.account_id,request.credentials)
        except Exception:store.log_event('broker_vault_unavailable',account,{'reason':'vault encryption unavailable'})
        return {'account':account,'profile':_to_json(profile),'capabilities':capability_matrix()[request.broker]}
    except Exception as ex:
        if hasattr(adapter,'close'):await adapter.close()
        raise _broker_error(ex)

class OAuthStartIn(BaseModel):
    broker:str
    account_id:str=Field(min_length=1,max_length=80)
    credentials:dict[str,str]

@app.post('/api/auth/start')
async def oauth_start(request:OAuthStartIn, raw:Request):
    if request.broker not in ('finvasia','fyers','flattrade'):raise HTTPException(422,'Unsupported OAuth broker')
    origin=raw.headers.get('origin','' if OWNER.production() else 'http://127.0.0.1:5173')
    if origin not in OWNER.allowed_frontend_origins():
        raise HTTPException(403,'Invalid frontend origin')
    fields={'finvasia':('client_id','secret_key','user_id'),'fyers':('client_id','api_secret'),
            'flattrade':('api_key','api_secret','user_id')}[request.broker]
    if any(not request.credentials.get(k) for k in fields):raise HTTPException(422,'Missing broker API credentials')
    # Shoonya/Flattrade do not document an echo of the state parameter. Only
    # one pending login may exist per provider and it expires after three minutes.
    now=time.monotonic()
    for k,v in list(OAUTH_PENDING.items()):
        if v['expires']<now:OAUTH_PENDING.pop(k,None)
    if any(v['broker']==request.broker for v in OAUTH_PENDING.values()):
        raise HTTPException(409,'Another authorization for this broker is pending; retry after three minutes')
    state=secrets.token_urlsafe(32)
    OAUTH_PENDING[state]={'broker':request.broker,'account_id':request.account_id,
        'credentials':request.credentials.copy(),'origin':origin,'expires':now+180}
    LOG.info('OAuth authorization started broker=%s',request.broker)
    return {'authorization_url':authorization_url(request.broker,request.credentials,state),
            'redirect_uri':f'{OWNER.public_api_url()}/api/auth/callback/{request.broker}'}

def _oauth_popup(origin:str,success:bool,account:str='',message:str='')->HTMLResponse:
    event={'source':'tradeverse-oauth','ok':success,'account':account,'error':message}
    payload=json.dumps(event).replace('<','\\u003c')
    page='''<!doctype html><meta charset="utf-8"><title>Broker authorization</title><body style="font:16px sans-serif;padding:32px"><h3>Authorization {status}</h3><p>You may close this window.</p><script>if(window.opener)window.opener.postMessage({payload},{origin});window.close();</script></body>'''
    return HTMLResponse(page.format(status='completed' if success else 'failed',payload=payload,origin=json.dumps(origin)),status_code=200)

@app.get('/api/auth/callback/{broker}',response_class=HTMLResponse)
async def oauth_callback(broker:str,request:Request,code:str='',auth_code:str='',request_code:str='',state:str=''):
    if broker not in ('finvasia','fyers','flattrade'):raise HTTPException(404,'Unsupported broker')
    if not OWNER.production() and request.client and request.client.host not in ('127.0.0.1','::1','localhost','testclient'):
        raise HTTPException(403,'Callback must be received locally')
    if OWNER.production() and broker=='fyers' and not state:
        raise HTTPException(400,'Missing FYERS OAuth state; restart broker login')
    if state:pending=OAUTH_PENDING.pop(state,None)
    else:
        matches=[(k,v) for k,v in OAUTH_PENDING.items() if v['broker']==broker]
        pending=matches[0][1] if len(matches)==1 else None
        if pending:OAUTH_PENDING.pop(matches[0][0],None)
    if not pending or pending['broker']!=broker or pending['expires']<time.monotonic():
        raise HTTPException(400,'OAuth state missing, expired, or invalid. Restart the broker login.')
    origin=pending['origin']
    broker_code=auth_code if broker=='fyers' else request_code if broker=='flattrade' else code
    if not broker_code:return _oauth_popup(origin,False,message='No authorization code returned; check the broker redirect URL')
    try:
        credentials=await exchange_code(broker,pending['credentials'],broker_code)
        reply=await connect(ConnectIn(broker=broker,account_id=pending['account_id'],credentials=credentials))
        LOG.info('OAuth authorization succeeded broker=%s',broker)
        return _oauth_popup(origin,True,account=reply['account'])
    except Exception as error:
        # Do not interpolate raw broker responses, passwords or tokens into HTML.
        LOG.warning('OAuth login failed broker=%s type=%s',broker,type(error).__name__)
        if isinstance(error,HTTPException):hint=str(error.detail)
        elif isinstance(error,(AuthError,BrokerError)):hint=str(error)
        else:hint='Authorization failed. Check your registered redirect URL, static IP and app permissions.'
        if re.search(r'(?i)(bearer\s|access.?token\s*[=:]|secret\s*[=:]|password\s*[=:]|[A-Za-z0-9_-]{55,})',hint):
            hint='Broker authorization failed (sensitive detail redacted).'
        return _oauth_popup(origin,False,message=hint)

@app.post('/api/accounts/verify')
async def verify_account(request:AccountVerifyIn):
    """Validate a session against the broker before allowing UI entry/resumption."""
    adapter=_account(request.account)
    try:
        if not await adapter.verify_session():
            raise AuthError('Broker session is no longer valid. Please sign in again.')
        return {'account':request.account,'verified':True,'broker':adapter.broker_id}
    except AuthError as ex:
        # Expired broker sessions must not continue streaming or executing strategies.
        await disconnect(request.account)
        raise _broker_error(ex)
    except Exception as ex:
        raise _broker_error(ex)

@app.delete('/api/accounts/{account:path}')
async def disconnect(account:str):
    broker=SESSIONS.pop(account,None)
    if not broker:raise HTTPException(404,'Account not connected')
    await HUB.stop_account(account)
    # Never let disconnected account strategies remain marked live.
    for x in store.strategies():
        if x['account']==account:store.change_strategy(x['id'],False)
    try:await broker.logout()
    finally:
        if hasattr(broker,'close'):await broker.close()
    try:core_vault.forget_session(account)
    except Exception:store.log_event('broker_vault_unavailable',account,{'reason':'could not remove saved token'})
    store.log_event('broker_disconnected',account)
    return {'disconnected':account}

@app.get('/api/instruments')
async def instruments(account:str,query:str='',exchange:str='NSE',refresh:bool=False,limit:int=100,fuzzy:bool=False):
    adapter=_account(account)
    local=store.search_instruments(account,query,limit)
    if local and not refresh and (not query or any(row['symbol'].upper()==query.upper() or row.get('name','').upper()==query.upper() for row in local)):
        return local
    if fuzzy and query and not refresh:
        suggestions=store.fuzzy_instruments(account,query,limit)
        if suggestions:return suggestions
    if not adapter.supports(Capability.INSTRUMENT_MASTER):
        return local
    try:
        if adapter.broker_id in ('flattrade','finvasia','upstox'):
            if not query:return local
            items=await adapter.get_instruments(query=query,exchange=exchange)
        elif adapter.broker_id=='zerodha':items=await adapter.get_instruments(exchange=exchange if refresh else '')
        else:items=await adapter.get_instruments()
        store.save_instruments(account,items)
        found=store.search_instruments(account,query,limit)
        return found or (store.fuzzy_instruments(account,query,limit) if fuzzy else [])
    except Exception as e:
        if local:return local
        raise _broker_error(e)

class BackfillIn(BaseModel):
    account:str
    exchange:str
    symbol:str
    segment:str='EQ'
    interval:str='1m'

@app.post('/api/history/backfill')
async def start_full_history(req:BackfillIn):
    """Start non-blocking retrieval of the oldest API-available broker history.

    The terminal stays usable while pages are fetched. Completed windows and
    candles are persisted; rerunning resumes rather than redownloading.
    """
    adapter=_account(req.account)
    if not adapter.supports(Capability.HISTORICAL_CANDLES):
        raise HTTPException(422,'This broker does not expose historical candles.')
    return BACKFILL.start(req.account,_key(req.exchange,req.symbol,req.segment),req.interval,adapter)

@app.get('/api/history/backfill/status')
async def full_history_status(account:str,exchange:str,symbol:str,segment:str='EQ',interval:str='1m'):
    _account(account)
    return BACKFILL.status(account,_key(exchange,symbol,segment),interval)

@app.get('/api/history')
async def history(account:str,exchange:str,symbol:str,segment:str='EQ',interval:str='1m',
                  start:str|None=None,end:str|None=None,before:str|None=None,
                  refresh:bool=False,limit:int=5000):
    _account(account)
    key=_key(exchange,symbol,segment)
    if limit<1 or limit>50000:raise HTTPException(422,'limit must be between 1 and 50000')
    if before:
        # The chart asks for the next *older* block. Never let newest-50K
        # query limits prevent scrolling back beyond six months.
        if refresh:raise HTTPException(422,'Use normal start/end range for broker refreshes')
        upper=dt(before)-timedelta(microseconds=1)
        return _to_json(store.load_candles(account,key,interval,None,upper,limit))
    end_dt=dt(end) if end else datetime.now(IST)
    start_dt=dt(start) if start else (end_dt-timedelta(days=(365 if interval.endswith(('m','h')) else 3650)) if refresh else None)
    if start_dt is not None and start_dt>=end_dt:raise HTTPException(400,'start must be earlier than end')
    if refresh:
        adapter=_account(account)
        if not adapter.supports(Capability.HISTORICAL_CANDLES):raise HTTPException(422,'Broker has no historical candle API')
        try:await sync_history(adapter,account,key,interval,start_dt,end_dt,store)
        except Exception as e:raise _broker_error(e)
    return _to_json(store.load_candles(account,key,interval,start_dt,end_dt,limit))

@app.post('/api/history/import')
def import_candles(account:str,exchange:str,symbol:str,segment:str='EQ',interval:str='1m',bars:list[dict]=Body(...)):
    _account(account)
    if len(bars)>20000:raise HTTPException(413,'Upload max 20,000 bars per call')
    from app.brokers.common import candles
    normalized=candles(bars)
    store.save_candles(account,_key(exchange,symbol,segment),interval,normalized)
    return {'imported':len(normalized),'source':'user-uploaded; not broker-verified'}

class SnapshotIn(BaseModel):
    account:str
    instruments:list[dict]=Field(min_length=1,max_length=50)

@app.post('/api/quotes/snapshot')
async def quote_snapshot(body:SnapshotIn):
    adapter=_account(body.account)
    if not hasattr(adapter,'get_ltp_quotes'):
        raise HTTPException(422,'Broker does not provide a normalized REST snapshot endpoint')
    keys=[]
    for row in body.instruments:
        exchange=str(row.get('exchange',''))[:20]
        symbol=str(row.get('symbol',''))[:120]
        if not exchange or not symbol:raise HTTPException(422,'Missing exchange or symbol')
        keys.append(_key(exchange,symbol,str(row.get('segment','EQ'))[:20]))
    try:
        return {'quotes':await adapter.get_ltp_quotes(keys),'source':'broker REST snapshot; not a live tick'}
    except Exception as e:raise _broker_error(e)

@app.get('/api/studies/catalog')
def studies_catalog():
    if not SESSIONS:raise HTTPException(409,'Connect a broker before accessing studies')
    return {'inventory':inventory(),'available':implemented()}

@app.get('/api/indicators')
def indicator(account:str,exchange:str,symbol:str,name:str,segment:str='EQ',interval:str='1m',n:int|None=None,inputs:str|None=None):
    _account(account)
    key=_key(exchange,symbol,segment)
    bars=store.load_candles(account,key,interval,limit=10000)
    if len(bars)<3:raise HTTPException(422,'Load candle data first')
    frame=pd.DataFrame([{'open':b.open,'high':b.high,'low':b.low,'close':b.close,'volume':b.volume} for b in bars],
                       index=pd.DatetimeIndex([b.ts for b in bars]))
    try:
        indicator_name=name.lower()
        if indicator_name not in REGISTRY:raise ValueError('Indicator not implemented; choose an available study')
        defaults=REGISTRY[indicator_name][1]
        param=next((x for x in ('length','period') if x in defaults),None)
        params={param:n} if param and n is not None else {}
        if inputs:
            custom=json.loads(inputs)
            if not isinstance(custom,dict) or len(custom)>12:raise ValueError('Invalid indicator input parameters')
            for name_,value_ in custom.items():
                if name_ not in defaults or isinstance(value_,bool) or not isinstance(value_,(int,float)) or not __import__('math').isfinite(value_):
                    raise ValueError(f'Invalid indicator parameter: {name_}')
                if not (-100000 < value_ < 100000):raise ValueError('Indicator parameter outside allowed range')
            params.update(custom)
        values=compute_indicator(indicator_name,frame,**params)
    except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e:raise HTTPException(422,str(e))
    clean=values.replace([float('inf'),float('-inf')],float('nan'))
    # Explicit nulls avoid NaN in JSON; maintain timestamp alignment.
    fields={k:[None if pd.isna(v) else float(v) for v in clean[k]] for k in clean.columns}
    return _to_json({'timestamps':[x.isoformat() for x in frame.index],'values':fields,'name':indicator_name,
                     'note':'Broker-derived historical candles; overlay updates after history refresh'})

@app.post('/api/backtest')
def backtest(body:BacktestIn):
    _account(body.account)
    if body.candles:
        from app.brokers.common import candles
        bars=candles(body.candles)
    else:bars=store.load_candles(body.account,_key(body.exchange,body.symbol,body.segment),body.interval,limit=30000)
    if len(bars)<30:raise HTTPException(422,'Need at least 30 valid candles; fetch history or import CSV first')
    frame=pd.DataFrame([asdict(b) for b in bars]).set_index('ts')
    try:
        r=run_backtest(frame,RuleStrategy(body.definition),BacktestConfig(initial_capital=body.initial_capital,slippage_bps=body.slippage_bps))
    except (ValueError,KeyError,TypeError) as e:raise HTTPException(422,str(e))
    return _to_json({'metrics':r.metrics,'trades':[asdict(t) for t in r.trades],
                     'equity':[{'ts':t.isoformat(),'value':v} for t,v in r.equity.items()],
                     'rejected_orders':len(r.rejected_orders),'data_source':'historical candles supplied to engine; simulated fills'})

@app.get('/api/strategies')
def strategies():
    if not SESSIONS:raise HTTPException(409,'Connect a broker before accessing strategies')
    return store.strategies()

@app.get('/api/strategies/health')
def strategy_health():
    if not SESSIONS:raise HTTPException(409,'Connect broker before checking strategies')
    rows=[]
    for item in store.strategies():
        identity=(item['account'],item['exchange'],item['symbol'],item['segment'])
        task=HUB.tasks.get(identity)
        error=HUB.errors.get(identity)
        rows.append({'id':item['id'],'active':item['active'],'feed_running':bool(task and not task.done()),
                     'feed_age_seconds':HUB.age(item['account'],_key(item['exchange'],item['symbol'],item['segment'])),
                     'feed_error':error,'mode':item['mode']})
    return rows

@app.post('/api/strategies')
def create_strategy(body:StrategyIn):
    _account(body.account)
    if body.mode not in ('paper','live'):raise HTTPException(422,'Mode must be paper or live')
    if body.interval!='1m' and body.mode=='live':raise HTTPException(422,'Live rules currently support only 1m closed bars')
    item={**body.model_dump(),'id':body.id or uuid.uuid4().hex[:16],'active':False}
    store.save_strategy(item)
    return item

@app.post('/api/strategies/{id}/start')
async def start_strategy(id:str):
    item=next((x for x in store.strategies() if x['id']==id),None)
    if not item:raise HTTPException(404,'Strategy not found')
    if item['mode']=='live' and not RISK.limits.live_trading_enabled:
        raise HTTPException(403,'Live trading disabled; enable explicitly after safety checks')
    adapter=_account(item['account'])
    try:
        if not await adapter.verify_session():raise AuthError('Broker session expired')
    except Exception as ex:raise _broker_error(ex)
    if not adapter.supports(Capability.LIVE_STREAM):raise HTTPException(422,'Broker cannot stream live market data for this strategy')
    if item['mode']=='live' and not adapter.supports(Capability.PLACE_ORDER):raise HTTPException(422,'Broker cannot place orders')
    if item['mode']=='live' and item['interval']!='1m':raise HTTPException(422,'Only 1m live rule evaluation supported')
    key=_key(item['exchange'],item['symbol'],item['segment'])
    if item['mode']=='live':
        RISK.bind_strategy(id,adapter.broker_id,item['account'])
    RISK.release_strategy(id)
    store.change_strategy(id,True)
    try:
        await HUB.ensure_strategy_feed(item['account'],key)
    except Exception as ex:
        store.change_strategy(id,False)
        RISK.kill_strategy(id)
        store.log_event('strategy_start_failed',item['account'],{'id':id,'error':type(ex).__name__})
        raise _broker_error(ex)
    store.log_event('strategy_started',item['account'],{'id':id,'mode':item['mode'],'feed_status':'starting'})
    return {'id':id,'active':True,'feed_status':'starting',
            'note':'Broker feed must begin producing ticks before execution is considered healthy'}

@app.post('/api/strategies/{id}/stop')
def stop_strategy(id:str):
    if not store.change_strategy(id,False):raise HTTPException(404,'Strategy not found')
    RISK.kill_strategy(id)
    return {'id':id,'active':False}

@app.post('/api/live/enable')
def enable_live(confirm:str=Body(embed=True)):
    if os.environ.get('ALLOW_LIVE_TRADING','no').lower()!='yes':
        raise HTTPException(403,'Set ALLOW_LIVE_TRADING=yes in backend environment after compliance checks')
    if confirm!='ENABLE LIVE TRADING':raise HTTPException(403,'Exact phrase required')
    RISK.limits.live_trading_enabled=True
    store.log_event('live_trading_enabled')
    return {'enabled':True}

@app.post('/api/live/disable')
def disable_live():
    RISK.limits.live_trading_enabled=False
    RISK.kill_all()
    for item in store.strategies():
        if item['mode']=='live':store.change_strategy(item['id'],False)
    store.log_event('live_trading_disabled')
    return {'enabled':False,'kill_switch':True}

@app.post('/api/live/release-kill-switch')
def release_kill(confirm:str=Body(embed=True)):
    if confirm!='RELEASE KILL SWITCH':raise HTTPException(403,'Confirmation required')
    RISK.release_all()
    return {'released':True}

@app.post('/api/orders')
async def place_order(body:OrderIn):
    adapter=_account(body.account)
    key=_key(body.exchange,body.symbol,body.segment)
    if body.order_type not in ('MARKET','LIMIT','SL','SL_M'):raise HTTPException(422,'Unsupported order type')
    if body.order_type in ('LIMIT','SL') and (body.price is None or body.price<=0):raise HTTPException(422,'Positive limit price required')
    if body.order_type in ('SL','SL_M') and (body.trigger_price is None or body.trigger_price<=0):raise HTTPException(422,'Positive trigger required')
    store.log_event('order_requested',body.account,{'symbol':body.symbol,'exchange':body.exchange,'side':body.side,'qty':body.qty,'mode':body.mode,'order_type':body.order_type})
    if body.mode=='paper':
        symbol=f'{body.exchange}:{body.symbol}'
        # Paper mode checks configured limits, as live does.
        ref=body.price or HUB.latest_price(body.account,key) or 0
        if body.is_exit:
            position_qty=HUB.paper(body.account).qty(symbol)
            RISK.set_position(body.account,body.symbol,position_qty,ref)
        intent=OrderIntent(adapter.broker_id,body.account,body.strategy_id,body.symbol,body.side,body.qty,ref,'paper',body.is_exit)
        decision=RISK.check(intent,datetime.now(IST),HUB.age(body.account,key))
        if not decision.allowed:raise HTTPException(403,{'risk_reasons':decision.reasons})
        o=HUB.paper(body.account).place_order(symbol,body.side,body.qty,body.order_type,body.price,
                     body.trigger_price,body.client_order_id,datetime.now(IST))
        if o.status=='REJECTED':raise HTTPException(422,o.message)
        RISK.record_submitted(intent,datetime.now(IST))
        store.log_event('paper_order',body.account,{'order_id':o.order_id,'symbol':symbol,'status':o.status})
        return _to_json(o)
    if body.mode!='live':raise HTTPException(422,'Mode must be paper or live')
    if not adapter.supports(Capability.PLACE_ORDER):raise HTTPException(422,'Broker does not support order placement')
    # Risk engine requires actual known reference quote, not a nominal price of zero.
    ref=HUB.latest_price(body.account,key) or body.price
    if body.is_exit:
        try:
            positions=await adapter.get_positions()
            actual=next((p for p in positions if p.key.symbol==key.symbol and p.key.exchange==key.exchange),None)
            RISK.set_position(body.account,body.symbol,actual.qty if actual else 0,actual.avg_price if actual else 0)
        except Exception as ex:
            RISK.require_reconciliation(body.account,'Could not verify reduce-only position')
            raise _broker_error(ex)
    request=OrderRequest(key,body.side,body.qty,body.order_type,body.product,body.price,
                         body.trigger_price,client_order_id=body.client_order_id)
    result=await EXECUTOR.submit(adapter,request,body.strategy_id,datetime.now(IST),
        mode='live',is_exit=body.is_exit,feed_age_sec=HUB.age(body.account,key),reference_price=ref,account_scope=body.account)
    store.log_event('live_order_result',body.account,{'status':result.status,'order_id':result.order_id})
    return _to_json(result)


@app.post('/api/orders/modify')
async def modify_order(account:str=Body(...),order_id:str=Body(...),quantity:int|None=Body(None),price:float|None=Body(None),trigger_price:float|None=Body(None)):
    adapter=_account(account)
    if not adapter.supports(Capability.MODIFY_ORDER):raise HTTPException(422,'Broker order modification not supported')
    if not order_id or len(order_id)>100:raise HTTPException(422,'Invalid order ID')
    if quantity is not None and quantity<=0:raise HTTPException(422,'Invalid modified quantity')
    if price is not None and price<=0:raise HTTPException(422,'Invalid modified price')
    store.log_event('order_modify_requested',account,{'order_id':order_id,'quantity':quantity,'price':price})
    try:
        result=await adapter.modify_order(order_id,qty=quantity,price=price,trigger_price=trigger_price)
        store.log_event('order_modify_response',account,{'order_id':order_id,'status':'accepted'})
        return _to_json(result)
    except Exception as ex:
        store.log_event('order_modify_response',account,{'order_id':order_id,'status':'error','type':type(ex).__name__})
        raise _broker_error(ex)

@app.get('/api/paper/{account:path}')
def paper_snapshot(account:str):
    _account(account)
    return HUB.paper(account).snapshot()

@app.get('/api/orders/{account:path}')
async def orders(account:str):
    adapter=_account(account)
    if not adapter.supports(Capability.PLACE_ORDER):raise HTTPException(422,'Unavailable for this broker or data-only session')
    try:return _to_json(await adapter.get_orders())
    except Exception as e:raise _broker_error(e)

@app.get('/api/tradebook/{account:path}')
async def tradebook(account:str):
    adapter=_account(account)
    if not adapter.supports(Capability.TRADEBOOK):
        raise HTTPException(422,'This broker tradebook integration is not yet available')
    try:return _to_json(await adapter.get_tradebook())
    except Exception as e:raise _broker_error(e)

@app.post('/api/orders/cancel')
async def cancel_order(account:str=Body(...),order_id:str=Body(...)):
    adapter=_account(account)
    if not adapter.supports(Capability.CANCEL_ORDER):raise HTTPException(422,'Broker cannot cancel orders')
    if not order_id or len(order_id)>100:raise HTTPException(422,'Invalid broker order ID')
    store.log_event('order_cancel_requested',account,{'order_id':order_id})
    try:
        await adapter.cancel_order(order_id)
        store.log_event('order_cancel_response',account,{'order_id':order_id,'status':'request_accepted'})
        return {'order_id':order_id,'status':'CANCEL_REQUEST_SENT','note':'Refresh orderbook to confirm broker status'}
    except Exception as e:
        store.log_event('order_cancel_response',account,{'order_id':order_id,'status':'error','type':type(e).__name__})
        raise _broker_error(e)

@app.get('/api/positions/{account:path}')
async def positions(account:str):
    adapter=_account(account)
    if not adapter.supports(Capability.POSITIONS):raise HTTPException(422,'Unavailable for this broker or data-only session')
    try:return _to_json(await adapter.get_positions())
    except Exception as e:raise _broker_error(e)

@app.get('/api/holdings/{account:path}')
async def holdings(account:str):
    adapter=_account(account)
    if not adapter.supports(Capability.HOLDINGS):raise HTTPException(422,'Unavailable for this broker or data-only session')
    try:return _to_json(await adapter.get_holdings())
    except Exception as e:raise _broker_error(e)

@app.get('/api/funds/{account:path}')
async def funds(account:str):
    adapter=_account(account)
    if not adapter.supports(Capability.FUNDS):raise HTTPException(422,'Unavailable for this broker or data-only session')
    try:return _to_json(await adapter.get_funds())
    except Exception as e:raise _broker_error(e)

@app.get('/api/options/expiries')
async def option_expiries(account:str,underlying:str):
    adapter=_account(account)
    if not adapter.supports(Capability.OPTION_CHAIN) or not hasattr(adapter,'get_option_expiries'):
        raise HTTPException(422,f'{adapter.broker_id} option-chain expiry discovery not implemented')
    try:
        dates=await adapter.get_option_expiries(underlying)
        return {'broker':adapter.broker_id,'underlying':underlying,'expiries':dates}
    except Exception as e:raise _broker_error(e)

@app.get('/api/options/chain')
async def option_chain(account:str,underlying:str,expiry:str):
    adapter=_account(account)
    if not adapter.supports(Capability.OPTION_CHAIN):
        raise HTTPException(422,f'{adapter.broker_id} option chain not implemented; supported: Upstox, FYERS')
    try:
        raw=await adapter.get_option_chain(underlying,expiry)
        result=normalize_chain(adapter.broker_id,raw,underlying,expiry)
        from app.brokers.base import Instrument
        contracts=[]
        for row in result.get('rows',[]):
            for option_type in ('call','put'):
                leg=row.get(option_type) or {}
                instrument_token=leg.get('instrument_key')
                if not instrument_token:continue
                label=leg.get('symbol') or instrument_token
                leg['symbol']=label
                contracts.append(Instrument(InstrumentKey('NFO',label,'OPT'),instrument_token,
                    strike=row.get('strike'),option_type='CE' if option_type=='call' else 'PE'))
        if contracts and hasattr(adapter,'remember_instruments'):
            adapter.remember_instruments(contracts)
        oi_call={float(x['strike']):float((x.get('call') or {}).get('oi') or 0) for x in result['rows'] if x.get('strike') is not None}
        oi_put={float(x['strike']):float((x.get('put') or {}).get('oi') or 0) for x in result['rows'] if x.get('strike') is not None}
        result['pcr']=pcr(oi_put,oi_call)
        result['max_pain']=max_pain(oi_call,oi_put)
        if adapter.broker_id=='upstox' and isinstance(raw,list) and raw:
            result['spot_price']=raw[0].get('underlying_spot_price')
        elif isinstance(raw,dict):
            result['spot_price']=raw.get('underlying_spot_price') or raw.get('spot_price')
        if not result['count']:raise HTTPException(422,'Broker returned no option strikes for selected underlying/expiry')
        return _to_json(result)
    except HTTPException:raise
    except Exception as e:raise _broker_error(e)

@app.post('/api/options/payoff')
def option_payoff(body:dict=Body(...)):
    try:
        legs=[Leg(str(l['kind']),float(l['strike']),float(l['premium']),float(l['qty'])) for l in body.get('legs',[])]
        if len(legs)<1 or len(legs)>16:raise ValueError('Supply 1-16 option legs')
        summary=analyze_payoff(legs)
        center=float(body.get('spot',max(l.strike for l in legs)))
        curve=payoff_curve(legs,max(0,center*.75),center*1.25,150)
        return _to_json({'summary':asdict(summary),'curve':curve,'estimated':True})
    except (KeyError,ValueError,ZeroDivisionError) as e:raise HTTPException(422,str(e))

@app.get('/api/events')
def events(limit:int=100):
    if not SESSIONS:raise HTTPException(409,'Connect a broker before accessing activity')
    return store.events(limit)


@app.websocket('/ws/quotes/{account:path}')
async def ws_quotes(websocket:WebSocket,account:str):
    if websocket.headers.get('origin') not in (OWNER.allowed_frontend_origins() if OWNER.production() else [None,*OWNER.allowed_frontend_origins()]):
        await websocket.close(code=1008);return
    allowed,owner_exp=OWNER.validate_ws_credentials(websocket.headers,websocket.query_params)
    if not allowed or account not in SESSIONS:
        await websocket.close(code=1008);return
    await websocket.accept(subprotocol='tradeverse' if OWNER.production() else None)
    subscriptions={}
    await websocket.send_json({'event':'status','state':'connecting','detail':'Local stream ready; waiting for broker subscriptions'})
    try:
        while True:
            if owner_exp is not None and time.time() >= owner_exp:
                await websocket.close(code=1008);return
            tasks={'receive':asyncio.create_task(websocket.receive_json())}
            for ident,(_,queue) in subscriptions.items():
                tasks[ident]=asyncio.create_task(queue.get())
            try:
                done,pending=await asyncio.wait(tasks.values(),timeout=12,return_when=asyncio.FIRST_COMPLETED)
                for task in pending:task.cancel()
                if pending:await asyncio.gather(*pending,return_exceptions=True)
                if not done:
                    await websocket.send_json({'event':'heartbeat','feed':HUB.status().get(account,{'state':'disconnected'})})
                    continue
                for name,task in tasks.items():
                    if task not in done:continue
                    if name=='receive':
                        message=task.result()
                        if message.get('action')!='subscribe':continue
                        raw=message.get('instruments',[])
                        if not isinstance(raw,list) or len(raw)>75:await websocket.send_json({'event':'error','message':'Subscription limit is 75 instruments'});continue
                        new={}
                        for item in raw:
                            if not isinstance(item,dict):continue
                            ex,sy,seg=str(item.get('exchange',''))[:20],str(item.get('symbol',''))[:120],str(item.get('segment','EQ'))[:20]
                            if not ex or not sy:continue
                            key=_key(ex,sy,seg)
                            new[HUB.identity(account,key)]=key
                        for ident,(key,queue) in list(subscriptions.items()):
                            if ident not in new:
                                await HUB.unlisten(account,key,queue)
                                del subscriptions[ident]
                        for ident,key in new.items():
                            if ident not in subscriptions:
                                subscriptions[ident]=(key,await HUB.listen(account,key))
                        await websocket.send_json({'event':'subscribed','count':len(subscriptions)})
                    else:
                        msg=task.result()
                        await websocket.send_json(_to_json(msg))
            finally:
                for task in tasks.values():
                    if not task.done():task.cancel()
    except (WebSocketDisconnect,asyncio.CancelledError):pass
    except Exception:
        with __import__('contextlib').suppress(Exception):await websocket.close(code=1011)
    finally:
        for key,queue in subscriptions.values():
            await HUB.unlisten(account,key,queue)

@app.websocket('/ws/market/{account:path}')
async def ws_market(websocket:WebSocket,account:str,exchange:str,symbol:str,segment:str='EQ'):
    origin=websocket.headers.get('origin','')
    if origin and origin not in OWNER.allowed_frontend_origins() or (OWNER.production() and not origin):
        await websocket.close(code=1008);return
    allowed,owner_exp=OWNER.validate_ws_credentials(websocket.headers,websocket.query_params)
    if not allowed or account not in SESSIONS:
        await websocket.close(code=1008);return
    await websocket.accept(subprotocol='tradeverse' if OWNER.production() else None)
    key=_key(exchange,symbol,segment)
    try:queue=await HUB.listen(account,key)
    except Exception:
        await websocket.close(code=1011);return
    try:
        while True:
            if owner_exp is not None and time.time() >= owner_exp:
                await websocket.close(code=1008);return
            try:
                message=await asyncio.wait_for(queue.get(),timeout=12)
            except asyncio.TimeoutError:
                continue
            await websocket.send_json(_to_json(message))
    except (WebSocketDisconnect,asyncio.CancelledError):pass
    finally:await HUB.unlisten(account,key,queue)

async def _on_closed_bar(account,key,candle,tick):
    """Paper + live bar-close rule execution. Live is opt-in and risk checked."""
    for item in store.strategies():
        if not(item['active'] and item['account']==account and item['exchange']==key.exchange
               and item['symbol']==key.symbol and item['segment']==key.segment and item['interval']=='1m'):
            continue
        bars=store.load_candles(account,key,'1m',limit=500)
        if len(bars)<30:continue
        df=pd.DataFrame([asdict(b) for b in bars]).set_index('ts')
        adapter=SESSIONS.get(account)
        if not adapter:continue
        if item['mode']=='paper':
            sym=f'{key.exchange}:{key.symbol}'
            account_paper=HUB.paper(account)
            qty=account_paper.qty(sym)
        else:
            try:
                positions=await adapter.get_positions()
                for p in positions:RISK.set_position(account,p.key.symbol,p.qty,p.avg_price)
                qty=next((p.qty for p in positions if p.key.symbol==key.symbol),0)
            except Exception:
                RISK.require_reconciliation(account,'could not retrieve positions')
                store.log_event('strategy_stopped',account,{'id':item['id'],'reason':'positions unavailable'})
                store.change_strategy(item['id'],False)
                continue
        try:signal=signal_from_frame(df,item['definition'],qty)
        except Exception as e:
            store.log_event('strategy_rule_error',account,{'id':item['id'],'error':str(e)[:160]});continue
        if not signal:continue
        n=abs(qty) if signal=='SELL' else int(item['definition'].get('quantity',1))
        if n<=0:continue
        if item['mode']=='paper':
            intent=OrderIntent(adapter.broker_id,account,item['id'],key.symbol,signal,n,tick.ltp,'paper',signal=='SELL')
            if signal=='SELL':RISK.set_position(account,key.symbol,qty)
            decision=RISK.check(intent,datetime.now(IST),HUB.age(account,key))
            if not decision.allowed:
                store.log_event('strategy_risk_block',account,{'id':item['id'],'reasons':decision.reasons});continue
            o=HUB.paper(account).place_order(f'{key.exchange}:{key.symbol}',signal,n,client_order_id=f'{item["id"]}-{int(candle.ts.timestamp())}',ts=tick.ts)
            if o.status!='REJECTED':RISK.record_submitted(intent,datetime.now(IST))
            store.log_event('strategy_paper_order',account,{'id':item['id'],'order_id':o.order_id,'status':o.status})
        else:
            ref=HUB.latest_price(account,key)
            req=OrderRequest(key,signal,n,'LIMIT','MIS',price=round(ref,2) if ref else None,
                             client_order_id=uuid.uuid4().hex[:20])
            result=await EXECUTOR.submit(adapter,req,item['id'],datetime.now(IST),'live',signal=='SELL',
                                        HUB.age(account,key),reference_price=ref,account_scope=account)
            store.log_event('strategy_live_order',account,{'id':item['id'],'status':result.status,'order_id':result.order_id})
            if result.status in ('UNRESOLVED','AUTH_ERROR'):
                store.change_strategy(item['id'],False)

HUB.on_candle=_on_closed_bar
