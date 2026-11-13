import {useEffect,useMemo,useRef} from 'react'
import {createChart,CandlestickSeries,BarSeries,AreaSeries,HistogramSeries,LineSeries,ColorType,type IChartApi,type UTCTimestamp} from 'lightweight-charts'
import type {Candle} from './api'
import {type ChartKind,type ChartParameters,DEFAULT_CHART_PARAMETERS,heikinAshi,renko,pointFigure,mergeLiveMinute,mergeLiveMinutes,orderedCandles} from './chartTransforms'

export type StudyPlot={id:string,pane:'overlay'|'oscillator',timestamps:string[],values:Record<string,(number|null)[]>,color?:string,lineWidth?:number,visible?:boolean}
type Props={candles:Candle[],streamCandle:Candle|null,streamMinutes?:Candle[],interval?:string,ema9?:boolean,ema21?:boolean,studies?:StudyPlot[],kind?:ChartKind,params?:ChartParameters,theme?:'light'|'dark',levels?:number[],onNeedOlder?:()=>void}
const time=(ts:string):UTCTimestamp=>Math.floor(Date.parse(ts)/1000) as UTCTimestamp
const PALETTE=['#a487f6','#15b8a6','#edb956','#e86f91','#81bf72','#6ea5ef']
function ema(data:Candle[],n:number){if(data.length<n)return [];const alpha=2/(n+1);let value=data.slice(0,n).reduce((sum,b)=>sum+b.close,0)/n;return data.slice(n-1).map((b,i)=>{if(i>0)value=b.close*alpha+value*(1-alpha);return {time:time(b.ts),value}})}
function validSeries(timestamps:string[],values:(number|null)[]){
 const data=new Map<number,number>()
 timestamps.forEach((stamp,i)=>{const t=Math.floor(Date.parse(stamp)/1000),v=values[i];if(Number.isFinite(t)&&v!==null&&v!==undefined&&Number.isFinite(v))data.set(t,v)})
 return [...data.entries()].sort((a,b)=>a[0]-b[0]).map(([ts,value])=>({time:ts as UTCTimestamp,value}))
}
function PointFigureView({bars,params}:{bars:Candle[],params:ChartParameters}){
 const columns=useMemo(()=>pointFigure(bars,params),[bars,params]);const all=columns.flatMap(c=>c.boxes)
 if(!all.length)return <div className="chart-empty">Not enough price movement for Point &amp; Figure columns at this box size.</div>
 const min=Math.min(...all),max=Math.max(...all),box=params.boxSize
 const width=Math.max(650,columns.length*27+72),height=Math.max(250,Math.min(1400,((max-min)/box+5)*22))
 const y=(p:number)=>height-30-(p-min)/box*21
 return <div className="pf-scroll" role="img" aria-label={`Point and figure chart: ${columns.length} columns`}><svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
  {Array.from({length:Math.ceil((max-min)/box)+1},(_,i)=>min+i*box).map(p=><g key={p}><line x1={42} x2={width} y1={y(p)} y2={y(p)} stroke="var(--chart-grid)"/><text x={38} y={y(p)+3} fontSize={10} fill="var(--text-muted)" textAnchor="end">{p.toFixed(0)}</text></g>)}
  {columns.map((c,i)=>c.boxes.map((p,j)=><text key={`${i}-${j}`} x={56+i*27} y={y(p)+6} textAnchor="middle" fontSize={20} fontFamily="monospace" fill={c.direction==='X'?'var(--up)':'var(--down)'}>{c.direction}</text>))}
 </svg></div>
}
export default function TradingChart({candles,streamCandle,streamMinutes=[],interval='1m',ema9=false,ema21=false,studies=[],kind='candles',params=DEFAULT_CHART_PARAMETERS,theme='dark',levels=[],onNeedOlder}:Props){
 const host=useRef<HTMLDivElement>(null),chartRef=useRef<IChartApi|null>(null)
 const oldestRef=useRef<number|null>(null),needOlderRef=useRef(onNeedOlder),interacted=useRef(false)
 needOlderRef.current=onNeedOlder
 const viewRef=useRef<any>(null),initialized=useRef(false)
 const seriesRef=useRef<{price:any,volume:any,e9:any,e21:any}|null>(null),studiesRef=useRef<any[]>([])
 const merged=useMemo(()=>streamMinutes.length?mergeLiveMinutes(candles,streamMinutes,interval):mergeLiveMinute(candles,streamCandle,interval),[candles,streamCandle,streamMinutes,interval])
 const seriesData=useMemo(()=>kind==='heikin-ashi'?heikinAshi(merged):kind==='renko'?renko(merged,params):orderedCandles(merged),[merged,kind,params])
 // Lifecycle is independent of studies and live candle updates. No chart remounts on ticks.
 useEffect(()=>{
  if(!host.current||kind==='point-figure')return
  const element=host.current,dark=theme==='dark',grid=dark?'#253345':'#e7eaf2',text=dark?'#9bacc0':'#516277',background=dark?'#131c29':'#ffffff'
  const c=createChart(element,{autoSize:true,layout:{background:{type:ColorType.Solid,color:background},textColor:text},
   grid:{vertLines:{color:grid},horzLines:{color:grid}},rightPriceScale:{borderColor:grid,visible:true},timeScale:{borderColor:grid,timeVisible:true,secondsVisible:false,visible:true}})
  chartRef.current=c
  const price:any=c.addSeries(kind==='line'?LineSeries:kind==='area'?AreaSeries:kind==='bars'?BarSeries:CandlestickSeries,
   kind==='line'?{color:'#6e88e9',lineWidth:2}:kind==='area'?{lineColor:'#6e88e9',topColor:'#6e88e946',bottomColor:'#6e88e900'}:
   kind==='bars'?{upColor:'#15b992',downColor:'#e36570'}:{upColor:'#15b992',downColor:'#e36570',wickUpColor:'#15b992',wickDownColor:'#e36570',borderVisible:false})
  const volume=c.addSeries(HistogramSeries,{priceFormat:{type:'volume'},priceScaleId:'volume'})
  c.priceScale('volume').applyOptions({scaleMargins:{top:.83,bottom:0}})
  const e9=c.addSeries(LineSeries,{color:'#f1bc55',lineWidth:1,priceLineVisible:false,lastValueVisible:false})
  const e21=c.addSeries(LineSeries,{color:'#9e8cf7',lineWidth:1,priceLineVisible:false,lastValueVisible:false})
  seriesRef.current={price,volume,e9,e21}
  if(viewRef.current){try{c.timeScale().setVisibleLogicalRange(viewRef.current)}catch{}}
  const onInteract=()=>{interacted.current=true}
  const loadAtEdge=(range:{from:number,to:number}|null)=>{if(!interacted.current||!range||range.from>80)return;interacted.current=false;needOlderRef.current?.()}
  element.addEventListener('wheel',onInteract,{passive:true});element.addEventListener('pointerdown',onInteract)
  c.timeScale().subscribeVisibleLogicalRangeChange(loadAtEdge)
  // autoSize uses an internal ResizeObserver; an outer observer handles grid/flex transitions.
  const observer=new ResizeObserver(()=>{const w=element.clientWidth,h=element.clientHeight;if(w>0&&h>0)c.resize(w,h)})
  observer.observe(element)
  return ()=>{viewRef.current=c.timeScale().getVisibleLogicalRange();c.timeScale().unsubscribeVisibleLogicalRangeChange(loadAtEdge);element.removeEventListener('wheel',onInteract);element.removeEventListener('pointerdown',onInteract);observer.disconnect();studiesRef.current=[];seriesRef.current=null;c.remove();chartRef.current=null}
 },[kind,theme])
 useEffect(()=>{
  const instance=seriesRef.current,c=chartRef.current;if(!instance||!c||kind==='point-figure')return
  const {price,volume,e9,e21}=instance
  const first=seriesData.length?time(seriesData[0].ts):null
  const addedOlder=first!=null&&oldestRef.current!=null&&first<oldestRef.current
  const visible=addedOlder?c.timeScale().getVisibleRange():null;oldestRef.current=first
  price.setData(seriesData.map(b=>kind==='line'||kind==='area'?{time:time(b.ts),value:b.close}:{time:time(b.ts),open:b.open,high:b.high,low:b.low,close:b.close}))
  volume.setData(kind==='renko'?[]:seriesData.map(b=>({time:time(b.ts),value:b.volume||0,color:b.close>=b.open?'#15b99255':'#e3657055'})))
  e9.setData(ema9&&kind!=='renko'?ema(seriesData,9):[])
  e21.setData(ema21&&kind!=='renko'?ema(seriesData,21):[])
  if(visible){try{c.timeScale().setVisibleRange(visible)}catch{}}
  else if(!initialized.current&&seriesData.length){c.timeScale().fitContent();initialized.current=true}
 },[seriesData,kind,ema9,ema21,theme])
 useEffect(()=>{
  const c=chartRef.current,instance=seriesRef.current;if(!c||!instance)return
  for(const s of studiesRef.current){try{c.removeSeries(s)}catch{}}
  studiesRef.current=[]
  if(kind==='renko'||kind==='point-figure')return
  let palette=0,paneIndex=0
  for(const study of studies){if(study.visible===false)continue
   const slot=study.pane==='oscillator'?++paneIndex:0
   for(const [name,values] of Object.entries(study.values)){
    if(['direction','trend','bullish'].includes(name))continue
    const points=validSeries(study.timestamps,values);if(!points.length)continue
    const series=c.addSeries(LineSeries,{color:study.color||PALETTE[palette++%PALETTE.length],lineWidth:(study.lineWidth||2) as 1|2|3|4,title:`${study.id} ${name}`,priceLineVisible:false,lastValueVisible:study.pane==='overlay'},slot)
    series.setData(points);studiesRef.current.push(series)
   }
  }
  // One pane per oscillator; multi-line outputs share that pane.
  c.panes().forEach((pane,i)=>{if(i>0)pane.setHeight(Math.max(95,Math.round(190/Math.max(1,paneIndex))))})
  const price=instance.price
  for(const l of levels){if(Number.isFinite(l)){const line=price.createPriceLine({price:l,color:theme==='dark'?'#dab7ff':'#6846a4',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'Drawing'});studiesRef.current.push({disposeLine:line})}}
  return ()=>{for(const x of studiesRef.current){if(x.disposeLine){try{price.removePriceLine(x.disposeLine)}catch{}}}studiesRef.current=studiesRef.current.filter(x=>!x.disposeLine)}
 },[studies,kind,levels,theme])
 if(kind==='point-figure')return <PointFigureView bars={merged} params={params}/>
 return <div className="chart-host" ref={host}/>
}
