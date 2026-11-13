// Public URL only. NEVER put passwords, broker tokens, or API secrets in VITE_* variables.
export const ROOT = (
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '')
).replace(/\/$/, '')

const OWNER_SESSION = 'tradeverse_owner_session'
export const ownerToken = () => sessionStorage.getItem(OWNER_SESSION) || ''
export const saveOwnerToken = (value: string) => sessionStorage.setItem(OWNER_SESSION, value)
export const forgetOwnerToken = () => sessionStorage.removeItem(OWNER_SESSION)
// Local-only legacy development token. Not used in production.
export const token = () => import.meta.env.DEV ? (localStorage.getItem('personal_algo_app_token') || '') : ''

export async function loginOwner(password: string): Promise<void> {
  if (!ROOT) throw new Error('VITE_API_BASE_URL is missing from the GitHub Pages deployment. Configure the HTTPS Railway backend URL and rebuild.')
  const response = await fetch(`${ROOT}/api/owner/login`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({password}), cache: 'no-store'
  })
  let result: any = null
  try { result = await response.json() } catch { /* show a safe error */ }
  if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : `Owner login failed (HTTP ${response.status})`)
  if (!result?.access_token) throw new Error('Backend did not issue an owner session')
  saveOwnerToken(result.access_token)
}

export async function api<T=any>(path: string, init: RequestInit = {}): Promise<T> {
  if (!ROOT) throw new Error('No production backend URL configured. Set VITE_API_BASE_URL in GitHub Actions and redeploy the frontend.')
  const bearer = import.meta.env.PROD ? ownerToken() : ''
  const headers: Record<string,string> = {
    'Content-Type': 'application/json',
    ...(bearer ? {'Authorization': `Bearer ${bearer}`} : {}),
    ...(token() ? {'X-Local-Token': token()} : {}),
    ...(init.headers as Record<string,string> || {})
  }
  const res = await fetch(`${ROOT}/api${path}`, {...init, headers, cache: 'no-store'})
  let payload: any
  try { payload = await res.json() } catch { throw new Error(`${res.status} - ${res.statusText}`) }
  if (!res.ok) {
    if (res.status === 401 && payload?.detail?.error === 'owner_auth_required') {
      forgetOwnerToken()
      window.dispatchEvent(new Event('tradeverse-owner-session-expired'))
    }
    const detail = payload?.detail
    throw new Error(typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : JSON.stringify(detail || payload))
  }
  return payload as T
}
export const post = <T=any>(path:string,value:unknown) => api<T>(path,{method:'POST',body:JSON.stringify(value)})
export const q = (value:Record<string,unknown>) => new URLSearchParams(Object.entries(value).filter(([,v])=>v!==undefined&&v!==null&&v!=='').map(([k,v])=>[k,String(v)])).toString()
export type Candle={ts:string,open:number,high:number,low:number,close:number,volume:number,oi?:number}
export type Account={id:string,broker:string,display_name:string,user_id:string,connected:boolean,read_only?:boolean}
export type Strategy={id:string,name:string,account:string,exchange:string,symbol:string,segment:string,interval:string,mode:string,active:boolean,definition:Record<string,any>}
export type EventRow={at:string,kind:string,account:string,payload:Record<string,unknown>}
