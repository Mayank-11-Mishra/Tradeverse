import {useState, type FormEvent} from 'react'
import {AlertTriangle,KeyRound,Loader2,ShieldCheck} from 'lucide-react'
import {ROOT, loginOwner} from './api'

export default function OwnerLogin({onAuthenticated}:{onAuthenticated:()=>Promise<void>}) {
  const [password,setPassword] = useState('')
  const [busy,setBusy] = useState(false)
  const [error,setError] = useState('')
  const submit = async (event:FormEvent) => {
    event.preventDefault()
    setBusy(true);setError('')
    try {
      await loginOwner(password)
      setPassword('')
      await onAuthenticated()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Owner authentication failed')
    } finally {setBusy(false)}
  }
  return <main style={{minHeight:'100dvh',display:'grid',placeItems:'center',background:'var(--bg, #0c1120)',color:'var(--text, #eef2ff)',padding:24}}>
    <section style={{width:'min(100%, 430px)',padding:30,borderRadius:20,border:'1px solid #64748b55',background:'var(--panel, #171e30)',boxShadow:'0 20px 80px #0004'}}>
      <div style={{display:'flex',alignItems:'center',gap:12,marginBottom:14}}><ShieldCheck size={29}/><strong style={{fontSize:23}}>TradeVerse Pro</strong></div>
      <h1 style={{fontSize:20,marginBottom:6}}>Owner sign-in</h1>
      <p style={{opacity:.75,lineHeight:1.55,marginBottom:23}}>Sign in to your private trading backend before connecting any brokerage account.</p>
      <form onSubmit={submit}>
        <label style={{display:'grid',gap:8,marginBottom:16}}><span>Owner password</span>
          <input type="password" value={password} autoComplete="current-password" autoFocus
            onChange={e=>setPassword(e.target.value)} required minLength={1}
            placeholder="Enter your owner password"
            style={{padding:13,borderRadius:9,width:'100%',background:'var(--input-bg, #0e172a)',color:'inherit',border:'1px solid #64748b80'}}/>
        </label>
        {error&&<p role="alert" style={{color:'#fb7185',display:'flex',gap:8,alignItems:'center',marginBottom:14}}><AlertTriangle size={16}/>{error}</p>}
        {!ROOT&&<p role="alert" style={{color:'#fb7185',marginBottom:12}}>Railway backend URL is not configured. Set VITE_API_BASE_URL in GitHub Actions and deploy again.</p>}
        <button type="submit" disabled={busy||!ROOT} className="gateway-submit" style={{width:'100%',display:'flex',alignItems:'center',justifyContent:'center',gap:9}}>
          {busy?<Loader2 className="spin" size={17}/>:<KeyRound size={17}/>} Sign in securely
        </button>
      </form>
      <p style={{fontSize:12,opacity:.65,marginTop:20}}>Your password is verified by the backend. Browser sessions expire automatically. Brokerage credentials are never included in the public frontend build.</p>
    </section>
  </main>
}
