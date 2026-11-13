import {useEffect,useMemo,useState} from 'react'
import {Activity,Check,ChevronDown,Search,X} from 'lucide-react'
import {api} from './api'

export type Study={id:string,params:Record<string,number>,pane:'overlay'|'oscillator'}
type Inventory={name:string,category:string,indicator_id:string|null,implemented:boolean,pane:string}
type Props={selected:string[],onToggle:(id:string)=>void,onClose:()=>void}
export default function StudiesPicker({selected,onToggle,onClose}:Props){
 const [available,setAvailable]=useState<Study[]>([]),[inventory,setInventory]=useState<Inventory[]>([])
 const [query,setQuery]=useState(''),[category,setCategory]=useState('All'),[error,setError]=useState(''),[onlyReady,setOnlyReady]=useState(true)
 useEffect(()=>{let active=true;void api<{inventory:Inventory[],available:Study[]}>('/studies/catalog').then(r=>{
  if(active){setInventory(r.inventory);setAvailable(r.available)}
 }).catch(e=>{if(active)setError(String(e))});return ()=>{active=false}},[])
 const categories=useMemo(()=>['All',...Array.from(new Set(inventory.map(i=>i.category)))], [inventory])
 const filtered=useMemo(()=>inventory.filter(i=>(category==='All'||i.category===category)&&(!onlyReady||i.implemented)&&
  `${i.name} ${i.category}`.toLowerCase().includes(query.toLowerCase())).slice(0,200),[inventory,category,query,onlyReady])
 return <div className="study-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}>
   <section className="study-panel" role="dialog" aria-modal="true" aria-label="Studies and indicators">
    <div className="study-heading"><div><b><Activity size={17}/> Studies & Indicators</b><small>{available.length} calculation engines • {inventory.length} supplied study names</small></div><button aria-label="Close studies" onClick={onClose}><X size={19}/></button></div>
    <div className="study-controls"><label className="study-search"><Search size={15}/><input autoFocus placeholder="Search 469 studies…" value={query} onChange={e=>setQuery(e.target.value)}/></label>
     <label className="study-category"><select aria-label="Study category" value={category} onChange={e=>setCategory(e.target.value)}>{categories.map(c=><option key={c}>{c}</option>)}</select><ChevronDown size={13}/></label>
     <label className="study-only"><input type="checkbox" checked={onlyReady} onChange={e=>setOnlyReady(e.target.checked)}/> Implemented only</label></div>
    {error&&<p className="study-warning">{error}</p>}
    <div className="study-results">{filtered.map((s,i)=><button className={'study-row '+(selected.includes(s.indicator_id||'')?'chosen':'')} key={`${s.category}-${i}-${s.name}`}
      disabled={!s.implemented} title={s.implemented?`Add or remove ${s.name}`:'Formula not yet implemented; not a working overlay'} onClick={()=>{if(s.indicator_id)onToggle(s.indicator_id)}}>
      <span><b>{s.name}</b><small>{s.category} • {s.implemented?s.indicator_id:'Not yet implemented'}</small></span>
      {s.implemented?<span className="study-state">{selected.includes(s.indicator_id||'')?<Check size={16}/>: 'Add'}</span>:<span className="study-pending">Pending</span>}
     </button>)}{!filtered.length&&<p className="study-empty">No matching studies found. Turn off “Implemented only” to browse the full inventory.</p>}</div>
    <footer>Selected: {selected.length} / 6. The original study names are preserved; vendor-specific variants are not silently replaced with unrelated formulas.</footer>
   </section>
 </div>
}
