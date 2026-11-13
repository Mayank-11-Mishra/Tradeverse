"""Local SQLAlchemy store. Defaults to SQLite for zero-install personal use;
set DATABASE_URL to PostgreSQL (psycopg) if a local PostgreSQL server is desired.
Sessions/tokens are NOT persisted; reconnect after each backend restart.
"""
from __future__ import annotations
import os,json
from pathlib import Path
from datetime import datetime,timezone
from sqlalchemy import create_engine,String,Float,Integer,Text,UniqueConstraint,select,delete,desc,or_,and_
from sqlalchemy.orm import declarative_base,sessionmaker,Mapped,mapped_column
from app.brokers.base import Candle,InstrumentKey,Instrument
from app.brokers.common import dt

ROOT=Path(__file__).resolve().parents[3]
DATA=ROOT/'data';DATA.mkdir(exist_ok=True)

URL = os.environ.get(
    "DATABASE_URL",
    f'sqlite:///{(DATA/"trading.db").as_posix()}'
)

# Convert Railway PostgreSQL URL to SQLAlchemy psycopg format
if URL.startswith("postgres://"):
    URL = URL.replace(
        "postgres://",
        "postgresql+psycopg://",
        1
    )
elif URL.startswith("postgresql://"):
    URL = URL.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1
    )

# Create database connection
engine = create_engine(
    URL,
    connect_args={"check_same_thread": False}
    if URL.startswith("sqlite:")
    else {},
    pool_pre_ping=True
)

Session=sessionmaker(bind=engine,expire_on_commit=False)
Base=declarative_base()

class StoredAccount(Base):
    __tablename__='accounts'
    id: Mapped[str]=mapped_column(String(120),primary_key=True)
    broker: Mapped[str]=mapped_column(String(32),nullable=False)
    display_name: Mapped[str]=mapped_column(String(160),default='')
    user_id: Mapped[str]=mapped_column(String(120),default='')

class StoredInstrument(Base):
    __tablename__='instruments'
    __table_args__=(UniqueConstraint('account','exchange','symbol','segment'),)
    id: Mapped[int]=mapped_column(primary_key=True,autoincrement=True)
    account: Mapped[str]=mapped_column(String(120),index=True)
    exchange: Mapped[str]=mapped_column(String(32))
    symbol: Mapped[str]=mapped_column(String(120))
    segment: Mapped[str]=mapped_column(String(32))
    broker_token: Mapped[str]=mapped_column(String(150))
    name: Mapped[str]=mapped_column(String(120),default='')
    lot_size: Mapped[int]=mapped_column(Integer,default=1)
    tick_size: Mapped[float]=mapped_column(Float,default=.05)
    expiry: Mapped[str]=mapped_column(String(50),default='')
    strike: Mapped[float|None]=mapped_column(Float,nullable=True)
    option_type: Mapped[str|None]=mapped_column(String(8),nullable=True)

class StoredCandle(Base):
    __tablename__='candles'
    __table_args__=(UniqueConstraint('account','exchange','symbol','segment','interval','ts',name='uq_candle_identity'),)
    id:Mapped[int]=mapped_column(primary_key=True,autoincrement=True)
    account:Mapped[str]=mapped_column(String(120),index=True)
    exchange:Mapped[str]=mapped_column(String(32))
    symbol:Mapped[str]=mapped_column(String(120))
    segment:Mapped[str]=mapped_column(String(32))
    interval:Mapped[str]=mapped_column(String(12))
    ts:Mapped[str]=mapped_column(String(40),index=True)    # UTC ISO format, lexical ordering safe
    open:Mapped[float]=mapped_column(Float)
    high:Mapped[float]=mapped_column(Float)
    low:Mapped[float]=mapped_column(Float)
    close:Mapped[float]=mapped_column(Float)
    volume:Mapped[float]=mapped_column(Float,default=0)
    oi:Mapped[float|None]=mapped_column(Float,nullable=True)

class StoredHistoryCoverage(Base):
    """Completed broker fetch windows; safe to retain even when the broker returns no candles.

    Mark a window only after candles have been committed. Windows touching the current
    trading day are intentionally NOT marked because their contents can still change.
    """
    __tablename__='history_coverage'
    __table_args__=(UniqueConstraint('account','exchange','symbol','segment','interval','start_ts','end_ts',name='uq_history_coverage'),)
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    account:Mapped[str]=mapped_column(String(120),index=True)
    exchange:Mapped[str]=mapped_column(String(32))
    symbol:Mapped[str]=mapped_column(String(120))
    segment:Mapped[str]=mapped_column(String(32))
    interval:Mapped[str]=mapped_column(String(12))
    start_ts:Mapped[str]=mapped_column(String(40))
    end_ts:Mapped[str]=mapped_column(String(40))

class StoredStrategy(Base):
    __tablename__='strategies'
    id:Mapped[str]=mapped_column(String(64),primary_key=True)
    name:Mapped[str]=mapped_column(String(160))
    account:Mapped[str]=mapped_column(String(120))
    exchange:Mapped[str]=mapped_column(String(32))
    symbol:Mapped[str]=mapped_column(String(120))
    segment:Mapped[str]=mapped_column(String(32),default='EQ')
    interval:Mapped[str]=mapped_column(String(12),default='1m')
    mode:Mapped[str]=mapped_column(String(10),default='paper')
    active:Mapped[int]=mapped_column(Integer,default=0)
    definition:Mapped[str]=mapped_column(Text,default='{}')

class StoredPreference(Base):
    __tablename__='preferences'
    owner:Mapped[str]=mapped_column(String(120),primary_key=True)
    key:Mapped[str]=mapped_column(String(60),primary_key=True)
    data:Mapped[str]=mapped_column(Text,default='{}')
    revision:Mapped[int]=mapped_column(Integer,default=1)

class StoredEvent(Base):
    __tablename__='events'
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    at:Mapped[str]=mapped_column(String(40))
    kind:Mapped[str]=mapped_column(String(30))
    account:Mapped[str]=mapped_column(String(120),default='')
    payload:Mapped[str]=mapped_column(Text,default='{}')

def init_db():Base.metadata.create_all(engine)
def iso_utc(t):return dt(t).astimezone(timezone.utc).isoformat()

def store_account(id,broker,name='',user_id=''):
    with Session.begin() as s:s.merge(StoredAccount(id=id,broker=broker,display_name=name,user_id=user_id))

def accounts():
    with Session() as s:return [dict(id=x.id,broker=x.broker,display_name=x.display_name,user_id=x.user_id) for x in s.scalars(select(StoredAccount)).all()]

def save_instruments(account,items:list[Instrument]):
    with Session.begin() as s:
        for obj in items:
            old=s.scalar(select(StoredInstrument).where(StoredInstrument.account==account,StoredInstrument.exchange==obj.key.exchange,
                                                       StoredInstrument.symbol==obj.key.symbol,StoredInstrument.segment==obj.key.segment))
            if old is None:
                old=StoredInstrument(account=account,exchange=obj.key.exchange,symbol=obj.key.symbol,segment=obj.key.segment)
                s.add(old)
            old.broker_token=obj.broker_token;old.name=obj.name;old.lot_size=obj.lot_size;old.tick_size=obj.tick_size
            old.expiry=obj.expiry.isoformat() if obj.expiry else '';old.strike=obj.strike;old.option_type=obj.option_type

def search_instruments(account,query='',limit=100):
    with Session() as s:
        st=select(StoredInstrument).where(StoredInstrument.account==account)
        if query:st=st.where(or_(StoredInstrument.symbol.ilike(f'%{query}%'),StoredInstrument.name.ilike(f'%{query}%')))
        rows=s.scalars(st.limit(min(limit,500))).all()
        return [dict(exchange=x.exchange,symbol=x.symbol,segment=x.segment,broker_token=x.broker_token,
                     name=x.name,lot_size=x.lot_size,tick_size=x.tick_size,expiry=x.expiry,
                     strike=x.strike,option_type=x.option_type) for x in rows]

def restore_instruments(account):
    from app.brokers.base import Instrument
    rows=search_instruments(account,limit=500000) # API function caps to 500; use separate direct query for full cache
    with Session() as s:
        items=s.scalars(select(StoredInstrument).where(StoredInstrument.account==account)).all()
        return [Instrument(InstrumentKey(x.exchange,x.symbol,x.segment),x.broker_token,x.name,x.lot_size,
                           x.tick_size,dt(x.expiry) if x.expiry else None,x.strike,x.option_type) for x in items]

def save_candles(account,key,interval,data:list[Candle]):
    """Bulk upsert candles; a multi-year 1-minute backfill must not do one SELECT per bar.

    SQLite and PostgreSQL implement native ON CONFLICT upsert. The SQLAlchemy fallback
    is retained for other explicitly configured local databases.
    """
    if not data:return
    rows=[dict(account=account,exchange=key.exchange,symbol=key.symbol,segment=key.segment,
               interval=interval,ts=iso_utc(c.ts),open=c.open,high=c.high,low=c.low,
               close=c.close,volume=c.volume,oi=c.oi) for c in data]
    dialect=engine.dialect.name
    if dialect in ('sqlite','postgresql'):
        if dialect=='sqlite':
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        with Session.begin() as session:
            # Avoid SQLite's maximum number of SQL bind variables on older installs.
            for i in range(0,len(rows),100):
                stmt=insert(StoredCandle).values(rows[i:i+100])
                stmt=stmt.on_conflict_do_update(index_elements=[
                    'account','exchange','symbol','segment','interval','ts'],set_={
                    field:getattr(stmt.excluded,field) for field in ('open','high','low','close','volume','oi')})
                session.execute(stmt)
        return
    with Session.begin() as session:
        for row in rows:
            old=session.scalar(select(StoredCandle).where(*[
                getattr(StoredCandle,k)==row[k] for k in ('account','exchange','symbol','segment','interval','ts')]))
            if old is None:session.add(StoredCandle(**row))
            else:
                for field in ('open','high','low','close','volume','oi'):setattr(old,field,row[field])


def history_coverage(account,key,interval,start,end):
    """Intervals already fetched successfully, clipped by the requested range."""
    with Session() as session:
        stmt=select(StoredHistoryCoverage).where(
            StoredHistoryCoverage.account==account,StoredHistoryCoverage.exchange==key.exchange,
            StoredHistoryCoverage.symbol==key.symbol,StoredHistoryCoverage.segment==key.segment,
            StoredHistoryCoverage.interval==interval,
            StoredHistoryCoverage.end_ts>iso_utc(start),
            StoredHistoryCoverage.start_ts<iso_utc(end))
        return [(dt(x.start_ts),dt(x.end_ts)) for x in session.scalars(stmt).all()]


def mark_history_coverage(account,key,interval,start,end):
    """Record a completed historical request, including an empty broker response."""
    with Session.begin() as session:
        query=select(StoredHistoryCoverage.id).where(
            StoredHistoryCoverage.account==account,StoredHistoryCoverage.exchange==key.exchange,
            StoredHistoryCoverage.symbol==key.symbol,StoredHistoryCoverage.segment==key.segment,
            StoredHistoryCoverage.interval==interval,
            StoredHistoryCoverage.start_ts==iso_utc(start),StoredHistoryCoverage.end_ts==iso_utc(end))
        if session.scalar(query) is None:
            session.add(StoredHistoryCoverage(account=account,exchange=key.exchange,symbol=key.symbol,
                segment=key.segment,interval=interval,start_ts=iso_utc(start),end_ts=iso_utc(end)))

def oldest_candle(account,key,interval):
    """Earliest candle actually stored for an instrument/timeframe; None if empty."""
    with Session() as session:
        stmt=(select(StoredCandle.ts).where(
            StoredCandle.account==account, StoredCandle.exchange==key.exchange,
            StoredCandle.symbol==key.symbol, StoredCandle.segment==key.segment,
            StoredCandle.interval==interval).order_by(StoredCandle.ts.asc()).limit(1))
        return session.scalar(stmt)

def load_candles(account,key,interval,start=None,end=None,limit=10000):
    with Session() as s:
        st=select(StoredCandle).where(StoredCandle.account==account,StoredCandle.exchange==key.exchange,
            StoredCandle.symbol==key.symbol,StoredCandle.segment==key.segment,StoredCandle.interval==interval)
        if start:st=st.where(StoredCandle.ts>=iso_utc(start))
        if end:st=st.where(StoredCandle.ts<=iso_utc(end))
        # Latest N candles, returned chronologically
        rows=list(s.scalars(st.order_by(desc(StoredCandle.ts)).limit(min(limit,50000))).all())
        return [Candle(dt(x.ts),x.open,x.high,x.low,x.close,x.volume,x.oi) for x in reversed(rows)]

def save_strategy(d):
    with Session.begin() as s:
        s.merge(StoredStrategy(id=d['id'],name=d['name'],account=d['account'],exchange=d['exchange'],
            symbol=d['symbol'],segment=d.get('segment','EQ'),interval=d.get('interval','1m'),mode=d.get('mode','paper'),
            active=int(bool(d.get('active'))),definition=json.dumps(d.get('definition',{}))))

def strategies():
    with Session() as s:
        return [dict(id=x.id,name=x.name,account=x.account,exchange=x.exchange,symbol=x.symbol,
            segment=x.segment,interval=x.interval,mode=x.mode,active=bool(x.active),definition=json.loads(x.definition))
                for x in s.scalars(select(StoredStrategy)).all()]

def change_strategy(id,active):
    with Session.begin() as s:
        x=s.get(StoredStrategy,id)
        if x is None:return False
        x.active=int(bool(active));return True

def log_event(kind,account='',payload=None):
    with Session.begin() as s:s.add(StoredEvent(at=datetime.now(timezone.utc).isoformat(),kind=kind,account=account,
                                                 payload=json.dumps(payload or {},default=str)))
def events(limit=100):
    with Session() as s:
        return [dict(at=x.at,kind=x.kind,account=x.account,payload=json.loads(x.payload))
                for x in s.scalars(select(StoredEvent).order_by(desc(StoredEvent.id)).limit(min(limit,500))).all()]


def get_preference(owner:str,key:str):
    with Session() as session:
        row=session.get(StoredPreference,(owner,key))
        return {'data':json.loads(row.data),'revision':row.revision} if row else None

def put_preference(owner:str,key:str,data:dict):
    with Session.begin() as session:
        row=session.get(StoredPreference,(owner,key))
        if row is None:
            row=StoredPreference(owner=owner,key=key,data=json.dumps(data),revision=1)
            session.add(row)
        else:
            row.data=json.dumps(data);row.revision+=1
        session.flush()
        return {'data':json.loads(row.data),'revision':row.revision}


def fuzzy_instruments(account:str,query:str,limit:int=30):
    """Best-effort local instrument suggestions; no network calls or invented instruments."""
    from difflib import SequenceMatcher
    query=query.upper().strip()
    if not query:return []
    with Session() as session:
        rows=list(session.scalars(select(StoredInstrument).where(StoredInstrument.account==account).limit(12000)).all())
    scored=[]
    for x in rows:
        symbol=x.symbol.upper()
        ratio=SequenceMatcher(None,query,symbol).ratio()
        if ratio>=.48 or query in x.name.upper() or symbol.startswith(query[:max(2,len(query)-1)]):
            score=(1 if symbol==query else 0, 1 if symbol.startswith(query) else 0,ratio)
            scored.append((score,x))
    scored.sort(key=lambda x:x[0],reverse=True)
    return [dict(exchange=x.exchange,symbol=x.symbol,segment=x.segment,broker_token=x.broker_token,name=x.name,
                 lot_size=x.lot_size,tick_size=x.tick_size,expiry=x.expiry,strike=x.strike,option_type=x.option_type)
            for _,x in scored[:min(limit,100)]]
