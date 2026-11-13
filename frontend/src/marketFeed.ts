import {ROOT,token,api,type Candle} from './api'
export type InstrumentId={exchange:string,symbol:string,segment:string}
export type FeedState='connecting'|'connected'|'reconnecting'|'disconnected'|'stale'
export type Quote={ltp:number,previous?:number,change?:number,pct?:number,bid?:number,ask?:number,ts:string,source?:'live'|'snapshot'}
export type MarketEvent={event:string,data?:any,key?:InstrumentId,partial?:boolean,interval?:string,feed?:any,state?:string,message?:string}
export type FeedListener=(event:MarketEvent)=>void
const keyFor=(k:InstrumentId)=>`${k.exchange}|${k.symbol}|${k.segment}`
export class MarketFeedClient{
 readonly account:string
 private ws:WebSocket|null=null
 private requested=new Map<string,{key:InstrumentId,count:number}>()
 private listeners=new Set<FeedListener>()
 private retry=0
 private timer:number|undefined
 private stopped=false
 private state:FeedState='disconnected'
 private lastMessage=0
 private monitor:number|undefined
 constructor(account:string){this.account=account}
 private emit(e:MarketEvent){for(const listener of this.listeners)listener(e)}
 private publish(state:FeedState){this.state=state;this.emit({event:'status',state})}
 subscribe(keys:InstrumentId[],listener:FeedListener){
  this.listeners.add(listener)
  keys.forEach(key=>{const id=keyFor(key),current=this.requested.get(id);this.requested.set(id,{key,count:(current?.count||0)+1})})
  this.stopped=false
  if(!this.ws)this.connect()
  else this.updateSubscriptions()
  listener({event:'status',state:this.state})
  return ()=>{
   this.listeners.delete(listener)
   for(const key of keys){const id=keyFor(key),entry=this.requested.get(id);if(entry){if(entry.count<=1)this.requested.delete(id);else this.requested.set(id,{...entry,count:entry.count-1})}}
   if(!this.listeners.size)this.shutdown()
   else this.updateSubscriptions()
  }
 }
 private connect(){
  if(this.stopped||this.ws||!this.listeners.size)return
  this.publish(this.retry?'reconnecting':'connecting')
  const address=ROOT.replace(/^http/,'ws')+`/ws/quotes/${encodeURIComponent(this.account)}`+
    (import.meta.env.DEV ? `?token=${encodeURIComponent(token())}` : '')
  if(import.meta.env.PROD){
   void api<{ticket:string}>('/owner/ws-ticket',{method:'POST',body:'{}'}).then(({ticket})=>{
    if(this.stopped||this.ws||!this.listeners.size)return
    this.openSocket(address,['tradeverse',`ticket.${ticket}`])
   }).catch(()=>this.scheduleReconnect())
   return
  }
  this.openSocket(address)
 }
 private openSocket(address:string,protocols?:string[]){
  if(this.stopped||this.ws)return
  let socket:WebSocket
  try{socket=new WebSocket(address,protocols)}catch{this.scheduleReconnect();return}
  this.ws=socket
  socket.onopen=()=>{
   this.retry=0;this.lastMessage=Date.now();this.publish('connecting');this.updateSubscriptions()
   if(!this.monitor)this.monitor=window.setInterval(()=>{
    if(this.state==='connected'&&this.lastMessage&&Date.now()-this.lastMessage>40000)this.publish('stale')
   },10000)
  }
  socket.onmessage=ev=>{
   this.lastMessage=Date.now()
   try{const msg=JSON.parse(ev.data) as MarketEvent
    if(msg.event==='error')this.emit(msg)
    else if(msg.event==='heartbeat'){
     if(msg.feed?.state==='reconnecting')this.publish('reconnecting')
     if(msg.feed?.state==='connected'&&msg.feed?.age_seconds>120)this.publish('stale')
     this.emit(msg)
    }else {if(msg.event==='tick'&&this.state!=='connected')this.publish('connected');this.emit(msg)}
   }catch{this.emit({event:'error',message:'Invalid market frame received'})}
  }
  socket.onerror=()=>this.publish('reconnecting')
  socket.onclose=ev=>{if(this.ws===socket)this.ws=null;if(ev.code===1008){this.emit({event:'auth-expired',message:'Broker or local API session rejected; please sign in again'});this.shutdown();return}if(!this.stopped)this.scheduleReconnect()}
 }
 private updateSubscriptions(){if(this.ws?.readyState===WebSocket.OPEN)this.ws.send(JSON.stringify({action:'subscribe',instruments:[...this.requested.values()].map(v=>v.key)}))}
 private scheduleReconnect(){
  if(this.stopped||!this.listeners.size)return
  this.publish('reconnecting')
  const delay=Math.min(30000,750*Math.pow(2,Math.min(this.retry++,6)))+Math.random()*350
  this.timer=window.setTimeout(()=>{this.timer=undefined;this.connect()},delay)
 }
 private shutdown(){
  this.stopped=true
  if(this.timer!==undefined)window.clearTimeout(this.timer)
  if(this.monitor!==undefined)window.clearInterval(this.monitor)
  this.timer=undefined;this.monitor=undefined
  const socket=this.ws;this.ws=null
  socket?.close();this.publish('disconnected')
  clients.delete(this.account)
 }
}
const clients=new Map<string,MarketFeedClient>()
export function getMarketFeed(account:string){let client=clients.get(account);if(!client){client=new MarketFeedClient(account);clients.set(account,client)}return client}

export function quoteFromTick(data:any,previous?:Quote):Quote|null{
 const ltp=Number(data?.ltp)
 if(!Number.isFinite(ltp)||ltp<=0)return null
 const brokerClose=Number(data?.previous_close);const base=brokerClose>0?brokerClose:(previous?.previous&&previous.previous>0?previous.previous:undefined)
 return {ltp,previous:base,change:base===undefined?undefined:ltp-base,pct:base?(ltp-base)/base*100:undefined,
  bid:data.bid==null?undefined:Number(data.bid),ask:data.ask==null?undefined:Number(data.ask),ts:String(data.ts||new Date().toISOString()),source:data.source==='snapshot'?'snapshot':'live'}
}
export function asCandle(data:any):Candle|null{
 if(!data||!data.ts)return null
 const values=['open','high','low','close'].map(k=>Number(data[k]))
 if(values.some(v=>!Number.isFinite(v)))return null
 return {ts:String(data.ts),open:values[0],high:values[1],low:values[2],close:values[3],volume:Number(data.volume||0)}
}
