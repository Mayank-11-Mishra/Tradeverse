import {useEffect,useState} from 'react'
import {AlertTriangle,X,ShieldCheck} from 'lucide-react'
import {api,post,type Account} from './api'
import type {InstrumentId} from './marketFeed'
export type TicketRequest={instrument:InstrumentId,side:'BUY'|'SELL',lastPrice?:number}
type Props={ticket:TicketRequest,accounts:Account[],onClose:()=>void,onCompleted:()=>void,liveEnabled:boolean}
export default function OrderTicket({ticket,accounts,onClose,onCompleted,liveEnabled}:Props){
 const [margins,setMargins]=useState<Record<string,string>>({})
 const [qty,setQty]=useState('1'),[price,setPrice]=useState(String(ticket.lastPrice||'')),[orderType,setOrderType]=useState<'MARKET'|'LIMIT'>('LIMIT'),[product,setProduct]=useState('MIS'),[mode,setMode]=useState<'paper'|'live'>('paper')
 const connected=accounts.filter(a=>a.connected&&(mode!=='live'||!a.read_only))
 const [selected,setSelected]=useState<string[]>(()=>{const saved=localStorage.getItem('tv_last_order_account')||'';return [connected.find(a=>a.id===saved)?.id||connected[0]?.id||''].filter(Boolean)})
 useEffect(()=>{void api<{data:any}>('/preferences/last_broker').then(res=>{const id=res?.data?.id;if(id&&accounts.some(a=>a.connected&&a.id===id))setSelected([id])}).catch(()=>{})},[])
 useEffect(()=>{if(mode==='live')setSelected(prev=>prev.filter(id=>accounts.some(a=>a.id===id&&a.connected&&!a.read_only)))},[mode])
 const [confirm,setConfirm]=useState(false),[busy,setBusy]=useState(false),[results,setResults]=useState<string[]>([])
 useEffect(()=>{let active=true
  Promise.all(connected.map(async a=>{try{const x:any=await api('/funds/'+encodeURIComponent(a.id));return [a.id,String(x.available??x.equity?.available??x.cash??'Broker-reported')]}catch{return [a.id,'Unavailable']}})).then(v=>{if(active)setMargins(Object.fromEntries(v))})
  return ()=>{active=false}
 },[accounts.map(x=>x.id+':'+x.connected).join(',')])
 const toggle=(id:string)=>setSelected(prev=>prev.includes(id)?prev.filter(x=>x!==id):[...prev,id])
 const valid=selected.length>0&&selected.every(id=>connected.some(a=>a.id===id))&&Number.isSafeInteger(Number(qty))&&Number(qty)>0&&(orderType==='MARKET'||Number(price)>0)&&(!liveEnabled?mode==='paper':true)
 const submit=async()=>{
  if(!valid)return
  setBusy(true);setResults([])
  const output:string[]=[]
  for(const account of selected){
   try{
    const result:any=await post('/orders',{account,exchange:ticket.instrument.exchange,symbol:ticket.instrument.symbol,segment:ticket.instrument.segment,
      side:ticket.side,qty:Number(qty),order_type:orderType,price:orderType==='LIMIT'?Number(price):null,product,mode,
      client_order_id:(globalThis.crypto?.randomUUID?.()||Date.now().toString(36)).replaceAll('-','').slice(0,25),strategy_id:'manual_ticket'})
    output.push(`${account}: ${result.status||result.order_id||'Request accepted'}`)
   }catch(e){output.push(`${account}: ERROR — ${e instanceof Error?e.message:String(e)}`)}
  }
  setResults(output);setBusy(false);setConfirm(false)
  if(selected.length){localStorage.setItem('tv_last_order_account',selected[0]);void api('/preferences/last_broker',{method:'PUT',body:JSON.stringify({id:selected[0]})}).catch(()=>{})}onCompleted()
 }
 useEffect(()=>{const key=(ev:KeyboardEvent)=>{if(ev.key==='Escape')onClose()};window.addEventListener('keydown',key);return ()=>window.removeEventListener('keydown',key)},[onClose])
 return <div className="ticket-backdrop" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><section className="ticket-modal" role="dialog" aria-modal="true" aria-label="Order ticket">
  <header><div><b>{ticket.side} {ticket.instrument.exchange}:{ticket.instrument.symbol}</b><small>Broker-verified order ticket · no order placed until final confirmation</small></div><button title="Close" onClick={onClose}><X size={19}/></button></header>
  <div className="ticket-content"><div className="ticket-account-list"><b>Choose connected execution accounts</b>{connected.length?connected.map(a=><label key={a.id} className="ticket-broker"><input type="checkbox" checked={selected.includes(a.id)} onChange={()=>toggle(a.id)}/><span><b>{a.broker.toUpperCase()} · {a.user_id||a.display_name||a.id}</b><small>Available margin: {margins[a.id]??'Fetching…'}</small></span></label>):<p>{mode==='live'?'No trading-capable broker logged in. Analytics-only sessions cannot execute live orders.':'No connected broker accounts.'}</p>}</div>
   <div className="ticket-fields"><label>Mode<select value={mode} onChange={e=>setMode(e.target.value as 'paper'|'live')}><option value="paper">Paper</option><option value="live" disabled={!liveEnabled}>Live {liveEnabled?'':'(locked)'}</option></select></label><label>Product<select value={product} onChange={e=>setProduct(e.target.value)}><option>MIS</option><option>CNC</option><option>NRML</option></select></label><label>Order type<select value={orderType} onChange={e=>setOrderType(e.target.value as 'MARKET'|'LIMIT')}><option value="LIMIT">Limit</option><option value="MARKET">Market (where supported)</option></select></label><label>Quantity<input type="number" min="1" step="1" value={qty} onChange={e=>setQty(e.target.value)}/></label>{orderType==='LIMIT'&&<label>Limit price<input type="number" min=".01" step=".05" value={price} onChange={e=>setPrice(e.target.value)}/></label>}</div>
   {selected.length>1&&<div className="ticket-warning"><AlertTriangle size={16}/> Separate broker orders may fill differently or partially. No cross-broker atomic execution is possible.</div>}
   {confirm&&<div className="ticket-confirm"><ShieldCheck size={17}/><div><strong>Confirm {mode.toUpperCase()} {ticket.side} on {selected.length} broker account(s)?</strong><p>{qty} × {ticket.instrument.symbol} · {product} · {orderType==='LIMIT'?'₹'+price:'Market price'} · Each order is sent separately and audited by the backend.</p><div className="ticket-actions"><button onClick={()=>setConfirm(false)}>Back</button><button className="ticket-submit" disabled={busy} onClick={()=>void submit()}>{busy?'Sending…':'Confirm & submit order(s)'}</button></div></div></div>}
   {!confirm&&<button className="ticket-submit" disabled={!valid||busy} onClick={()=>setConfirm(true)}>Review {ticket.side} order</button>}
   {results.map((s,i)=><p className="ticket-result" key={i}>{s}</p>)}
  </div></section></div>
}
