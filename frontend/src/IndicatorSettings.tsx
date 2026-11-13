import {useEffect,useState} from 'react'
import {X} from 'lucide-react'
export type IndicatorPreferences={inputs?:Record<string,number>,color?:string,lineWidth?:number,visible?:boolean,timeframes?:string[]}
type Props={id:string,defaults:Record<string,number>,value:IndicatorPreferences,onApply:(value:IndicatorPreferences)=>void,onClose:()=>void}
const TIMES=['1m','3m','5m','15m','30m','1h','1d']
export default function IndicatorSettings({id,defaults,value,onApply,onClose}:Props){
 const [tab,setTab]=useState<'Inputs'|'Style'|'Visibility'>('Inputs')
 const [draft,setDraft]=useState<IndicatorPreferences>(()=>({...value,inputs:{...defaults,...(value.inputs||{})}}))
 useEffect(()=>{setDraft({...value,inputs:{...defaults,...(value.inputs||{})}})},[id])
 const reset=()=>setDraft({inputs:{...defaults},color:'#a487f6',lineWidth:2,visible:true,timeframes:[]})
 return <div className="indicator-dialog-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}>
  <section className="indicator-dialog" role="dialog" aria-modal="true" aria-label={`${id} indicator settings`}>
   <header><strong>{id.toUpperCase()} settings</strong><button aria-label="Close indicator settings" onClick={onClose}><X size={17}/></button></header>
   <div className="indicator-tabs">{(['Inputs','Style','Visibility'] as const).map(t=><button key={t} className={tab===t?'active':''} onClick={()=>setTab(t)}>{t}</button>)}</div>
   <div className="indicator-dialog-content">
    {tab==='Inputs'&&<>{Object.keys(defaults).length?Object.entries(defaults).map(([key,defaultValue])=><label key={key}>{key}<input type="number" step="any" value={draft.inputs?.[key]??defaultValue} onChange={e=>setDraft(v=>({...v,inputs:{...v.inputs,[key]:Number(e.target.value)}}))}/></label>):<p>This indicator has no configurable numeric inputs.</p>}</>}
    {tab==='Style'&&<><label>Line color<input type="color" value={draft.color||'#a487f6'} onChange={e=>setDraft(v=>({...v,color:e.target.value}))}/></label><label>Line width <select value={draft.lineWidth||2} onChange={e=>setDraft(v=>({...v,lineWidth:Number(e.target.value)}))}>{[1,2,3,4].map(n=><option key={n} value={n}>{n}px</option>)}</select></label></>}
    {tab==='Visibility'&&<><label className="indicator-check"><input type="checkbox" checked={draft.visible!==false} onChange={e=>setDraft(v=>({...v,visible:e.target.checked}))}/> Show indicator</label><p>Timeframes (none selected means all)</p><div className="indicator-timeframes">{TIMES.map(t=><label key={t}><input type="checkbox" checked={(draft.timeframes||[]).includes(t)} onChange={e=>setDraft(v=>{const current=v.timeframes||[];return {...v,timeframes:e.target.checked?[...current,t]:current.filter(x=>x!==t)}})}/>{t}</label>)}</div></>}
   </div>
   <footer><button onClick={reset}>Reset to defaults</button><span/><button onClick={onClose}>Cancel</button><button className="indicator-apply" onClick={()=>onApply(draft)}>Apply</button></footer>
  </section>
 </div>
}
