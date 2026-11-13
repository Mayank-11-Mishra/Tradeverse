export const ROOT = (
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '')
).replace(/\/$/, '')
export const token=()=>localStorage.getItem('personal_algo_app_token')||''
export async function api<T=any>(path:string,init:RequestInit={}):Promise<T>{
  const res=await fetch(`${ROOT}/api${path}`,{...init,headers:{'Content-Type':'application/json',...(token()?{'X-Local-Token':token()}:{}),...(init.headers||{})}})
  let payload:any;try{payload=await res.json()}catch{throw new Error(`${res.status} - ${res.statusText}`)}
  if(!res.ok)throw new Error(typeof payload.detail==='string'?payload.detail:JSON.stringify(payload.detail||payload))
  return payload as T
}
export const post=<T=any>(path:string,value:unknown)=>api<T>(path,{method:'POST',body:JSON.stringify(value)})
export const q=(value:Record<string,unknown>)=>new URLSearchParams(Object.entries(value).filter(([,v])=>v!==undefined&&v!==null&&v!=='').map(([k,v])=>[k,String(v)])).toString()
export type Candle={ts:string,open:number,high:number,low:number,close:number,volume:number,oi?:number}
export type Account={id:string,broker:string,display_name:string,user_id:string,connected:boolean,read_only?:boolean}
export type Strategy={id:string,name:string,account:string,exchange:string,symbol:string,segment:string,interval:string,mode:string,active:boolean,definition:Record<string,any>}
export type EventRow={at:string,kind:string,account:string,payload:Record<string,unknown>}
