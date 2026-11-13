import {createContext,useContext,useEffect,useLayoutEffect,useMemo,useState,type ReactNode} from 'react'
import {api} from './api'
export type ThemeSetting='dark'|'light'|'system'
const KEY='tradeverse_theme_v1'
const ThemeContext=createContext<{theme:ThemeSetting,setTheme:(theme:ThemeSetting)=>void}>({theme:'dark',setTheme:()=>{}})
function read(){const x=localStorage.getItem(KEY);return x==='light'||x==='dark'||x==='system'?x:'dark'}
export function initializeTheme(){if(typeof document==='undefined')return
 const preference=read(),dark=preference==='system'?window.matchMedia('(prefers-color-scheme: dark)').matches:preference==='dark'
 document.documentElement.dataset.theme=dark?'dark':'light'
}
export function ThemeProvider({children}:{children:ReactNode}){
 const [theme,setTheme]=useState<ThemeSetting>(read)
 useLayoutEffect(()=>{initializeTheme()},[theme])
 useEffect(()=>{
  const matched=window.matchMedia('(prefers-color-scheme: dark)')
  const listener=()=>{if(theme==='system')initializeTheme()}
  matched.addEventListener('change',listener);return ()=>matched.removeEventListener('change',listener)
 },[theme])
 useEffect(()=>{let active=true;void api<{data:{theme?:ThemeSetting}}>('/preferences/theme').then(r=>{const t=r?.data?.theme;if(active&&(t==='light'||t==='dark'||t==='system')){localStorage.setItem(KEY,t);setTheme(t)}}).catch(()=>{})
  return ()=>{active=false}
 },[])
 const value=useMemo(()=>({theme,setTheme:(next:ThemeSetting)=>{localStorage.setItem(KEY,next);setTheme(next);void api('/preferences/theme',{method:'PUT',body:JSON.stringify({theme:next})}).catch(()=>{})}}),[theme])
 return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
export const useTheme=()=>useContext(ThemeContext)
