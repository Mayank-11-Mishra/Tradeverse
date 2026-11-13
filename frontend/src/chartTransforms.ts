import type {Candle} from './api'

export type ChartKind='candles'|'heikin-ashi'|'renko'|'point-figure'|'line'|'area'|'bars'
export type BrickMode='fixed'|'atr'|'percent'
export type ChartParameters={brickMode:BrickMode,brickSize:number,atrPeriod:number,boxSize:number,reversal:number}
export const DEFAULT_CHART_PARAMETERS:ChartParameters={brickMode:'fixed',brickSize:20,atrPeriod:14,boxSize:20,reversal:3}
export type PFColumn={direction:'X'|'O',boxes:number[],start:number,end:number,forming:boolean}

export function orderedCandles(bars:Candle[]):Candle[]{
 const unique=new Map<number,Candle>()
 for(const c of bars){const t=Date.parse(c.ts);if(Number.isFinite(t)&&[c.open,c.high,c.low,c.close].every(Number.isFinite))unique.set(t,c)}
 return Array.from(unique.entries()).sort((a,b)=>a[0]-b[0]).map(([,v])=>v)
}
export function heikinAshi(raw:Candle[]):Candle[]{
 const data=orderedCandles(raw);let priorOpen=0,priorClose=0
 return data.map((c,i)=>{
  const close=(c.open+c.high+c.low+c.close)/4
  const open=i===0?(c.open+c.close)/2:(priorOpen+priorClose)/2
  priorOpen=open;priorClose=close
  return {...c,open,close,high:Math.max(c.high,open,close),low:Math.min(c.low,open,close)}
 })
}
export function averageTrueRange(raw:Candle[],period:number):number{
 const bars=orderedCandles(raw),n=Math.max(1,Math.floor(period))
 if(!bars.length)return 0
 let sum=0,count=0
 for(let i=Math.max(0,bars.length-n);i<bars.length;i++){
  const c=bars[i],prev=bars[i-1]?.close??c.close
  sum+=Math.max(c.high-c.low,Math.abs(c.high-prev),Math.abs(c.low-prev));count++
 }
 return count?sum/count:0
}
export function brickSizeFor(bars:Candle[],params:ChartParameters):number{
 const last=bars.at(-1)?.close??0
 const n=params.brickMode==='atr'?averageTrueRange(bars,params.atrPeriod):params.brickMode==='percent'?last*params.brickSize/100:params.brickSize
 return Number.isFinite(n)&&n>0?n:0
}
/** Close-only Renko. Uses synthetic monotonically increasing times because more than one brick can form on one tick. */
export function renko(raw:Candle[],params:ChartParameters):Candle[]{
 const bars=orderedCandles(raw),size=brickSizeFor(bars,params)
 if(bars.length<2||!size)return []
 const start=Math.floor(Date.parse(bars[0].ts)/1000)
 let level=bars[0].close,index=0
 const bricks:Candle[]=[]
 for(const c of bars.slice(1)){
  let steps=0
  while(Math.abs(c.close-level)>=size-1e-9&&steps++<2000&&bricks.length<20000){
   const open=level,close=level+Math.sign(c.close-level)*size
   bricks.push({ts:new Date((start+index++*60)*1000).toISOString(),open,close,high:Math.max(open,close),low:Math.min(open,close),volume:0})
   level=close
  }
 }
 return bricks
}
/** Close-based Point & Figure using a fixed price box size and configurable reversal count. */
export function pointFigure(raw:Candle[],params:ChartParameters):PFColumn[]{
 const data=orderedCandles(raw),box=params.boxSize,reversal=Math.max(1,Math.floor(params.reversal))
 if(data.length<2||!(box>0))return []
 const level=(p:number)=>Math.floor(p/box)*box
 const close=data.map(x=>x.close)
 let anchor=level(close[0]),direction:'X'|'O'|null=null
 let extreme=anchor
 const out:PFColumn[]=[]
 for(let i=1;i<close.length;i++){
  const value=level(close[i])
  if(direction===null){
   if(value===anchor)continue
   direction=value>anchor?'X':'O';extreme=anchor
   out.push({direction,boxes:[],start:i,end:i,forming:true})
  }
  const current=out.at(-1)!
  if(direction==='X'){
   while(value>=extreme+box-1e-9){extreme+=box;current.boxes.push(+extreme.toFixed(8))}
   if(value<=extreme-reversal*box+1e-9){direction='O';const column:PFColumn={direction,boxes:[],start:i,end:i,forming:true};out.push(column)
    for(let j=1;j<=reversal;j++){extreme-=box;column.boxes.push(+extreme.toFixed(8))}
    while(value<=extreme-box+1e-9){extreme-=box;column.boxes.push(+extreme.toFixed(8))}
   }
  }else{
   while(value<=extreme-box+1e-9){extreme-=box;current.boxes.push(+extreme.toFixed(8))}
   if(value>=extreme+reversal*box-1e-9){direction='X';const column:PFColumn={direction,boxes:[],start:i,end:i,forming:true};out.push(column)
    for(let j=1;j<=reversal;j++){extreme+=box;column.boxes.push(+extreme.toFixed(8))}
    while(value>=extreme+box-1e-9){extreme+=box;column.boxes.push(+extreme.toFixed(8))}
   }
  }
  out.at(-1)!.end=i
 }
 return out
}

/** Form the latest requested-timeframe bar from 1-minute broker bars; no invented volume. */
export function mergeLiveMinute(history:Candle[],minute:Candle|null,interval:string):Candle[]{
 const data=orderedCandles(history)
 if(!minute)return data
 const match=/^(\d+)(m|h)$/.exec(interval)
 if(!match){return interval==='1m'?orderedCandles([...data,minute]):data}
 const minutes=Number(match[1])*(match[2]==='h'?60:1)
 const epoch=Date.parse(minute.ts)
 if(!Number.isFinite(epoch))return data
 // NSE cash session anchor: 09:15 Asia/Kolkata. Use stable UTC epoch arithmetic.
 const offset=330*60000,day=Math.floor((epoch+offset)/86400000)*86400000-offset
 const anchor=day+(9*60+15)*60000
 const bucket=anchor+Math.floor((epoch-anchor)/(minutes*60000))*(minutes*60000)
 const ts=new Date(bucket).toISOString()
 const last=data.at(-1)
 if(last&&Date.parse(last.ts)>bucket)return data
 if(last&&Date.parse(last.ts)===bucket){
  // History may already include this minute. Keep recorded open/volume and update high/low/close.
  return [...data.slice(0,-1),{...last,high:Math.max(last.high,minute.high),low:Math.min(last.low,minute.low),close:minute.close,volume:Math.max(last.volume,minute.volume)}]
 }
 return [...data,{...minute,ts}]
}

/** Consolidate individual broker 1m candles into the requested chart timeframe.
 * Historical candles are kept as an OHLC baseline. Volume is conservative when
 * snapshot and live minute candles overlap, to avoid double counting a partial
 * source candle (the feed lacks a snapshot overlap sequence number).
 */
export function mergeLiveMinutes(history:Candle[],liveMinutes:Candle[],interval:string):Candle[]{
 let merged=orderedCandles(history)
 if(!liveMinutes.length)return merged
 const latest=orderedCandles(liveMinutes)
 if(interval==='1d'){
  for(const m of latest){
   const day=new Date(Date.parse(m.ts)+330*60000).toISOString().slice(0,10)
   const existing=merged.findIndex(c=>new Date(Date.parse(c.ts)+330*60000).toISOString().slice(0,10)===day)
   const row=existing>=0?merged[existing]:undefined
   const next=row?{...row,high:Math.max(row.high,m.high),low:Math.min(row.low,m.low),close:m.close,volume:Math.max(row.volume,m.volume)}:{...m,ts:new Date(Date.parse(day+'T00:00:00Z')-330*60000).toISOString()}
   if(existing>=0)merged[existing]=next
   else merged=[...merged,next]
  }
  return orderedCandles(merged)
 }
 const match=/^(\d+)(m|h)$/.exec(interval)
 if(!match)return merged
 const duration=Number(match[1])*(match[2]==='h'?60:1)*60000
 const getBucket=(ts:string)=>{
  const epoch=Date.parse(ts),offset=330*60000
  const day=Math.floor((epoch+offset)/86400000)*86400000-offset
  const anchor=day+(9*60+15)*60000
  return anchor+Math.floor((epoch-anchor)/duration)*duration
 }
 const groups=new Map<number,Candle[]>()
 for(const m of latest){const bucket=getBucket(m.ts);groups.set(bucket,[...(groups.get(bucket)||[]),m])}
 for(const [bucket,source] of [...groups].sort((a,b)=>a[0]-b[0])){
  const index=merged.findIndex(c=>Date.parse(c.ts)===bucket)
  const base=index>=0?merged[index]:undefined
  const extraVolume=source.reduce((sum,c)=>sum+(Number.isFinite(c.volume)?c.volume:0),0)
  const result:Candle={ts:new Date(bucket).toISOString(),
   open:base?.open??source[0].open,high:Math.max(base?.high??-Infinity,...source.map(c=>c.high)),
   low:Math.min(base?.low??Infinity,...source.map(c=>c.low)),close:source[source.length-1].close,
   volume:Math.max(base?.volume||0,extraVolume)}
  if(index>=0)merged[index]=result
  else merged.push(result)
 }
 return orderedCandles(merged)
}
