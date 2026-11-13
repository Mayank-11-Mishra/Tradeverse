export type WindowType='chart'|'optionchain'|'watchlist'|'orders'|'tradebook'|'positions'|'funds'|'strategies'|'brokers'|'settings'|'portfolio'
export type Pane={kind:'pane',id:string,type:WindowType,title:string,config:Record<string,any>}
export type Tabs={kind:'tabs',id:string,active:string,panes:Pane[]}
export type Split={kind:'split',id:string,direction:'horizontal'|'vertical',ratio:number,first:WorkspaceNode,second:WorkspaceNode}
export type WorkspaceNode=Pane|Tabs|Split
export type FloatingPane={pane:Pane,x:number,y:number,w:number,h:number}
export type GridPreset='1x1'|'1x2'|'2x1'|'2x2'|'2x3'|'3x2'
export type LayoutDocument={version:2,root:WorkspaceNode|null,floating:FloatingPane[],mode?:'tab'|'tile',tilePreset?:GridPreset,tileOrder?:string[]}
let index=0
const id=()=>`w${Date.now().toString(36)}${(++index).toString(36)}`
export const pane=(type:WindowType,config:Record<string,any>={}):Pane=>({kind:'pane',id:id(),type,title:{chart:'Chart',optionchain:'Option Chain',watchlist:'Watchlist',orders:'Orderbook',tradebook:'Tradebook',positions:'Positions',funds:'Funds & Margin',strategies:'Live Strategies',brokers:'Broker Accounts',settings:'Settings',portfolio:'Portfolio'}[type],config})
export const defaultWorkspace=():LayoutDocument=>({version:2,root:pane('chart',{symbol:'NIFTY',exchange:'NSE',segment:'IDX',interval:'15m',chartKind:'candles'}),floating:[],mode:'tab',tilePreset:'1x1',tileOrder:[]})
export const paneTitle=(item:Pane):string=>item.type==='chart'?String(item.config.name||({'NIFTY':'NIFTY 50','BANKNIFTY':'BANK NIFTY'} as Record<string,string>)[String(item.config.symbol||'').toUpperCase()]||item.config.symbol||'Chart'):item.title
export function traverse(node:WorkspaceNode|null,visit:(p:Pane)=>void):void{if(!node)return;if(node.kind==='pane')visit(node);else if(node.kind==='tabs')node.panes.forEach(visit);else{traverse(node.first,visit);traverse(node.second,visit)}}
export function updatePane(node:WorkspaceNode|null,needle:string,fn:(p:Pane)=>Pane):WorkspaceNode|null{
 if(!node)return null
 if(node.kind==='pane')return node.id===needle?fn(node):node
 if(node.kind==='tabs')return {...node,panes:node.panes.map(p=>p.id===needle?fn(p):p)}
 return {...node,first:updatePane(node.first,needle,fn)!,second:updatePane(node.second,needle,fn)!}
}
export function removePane(node:WorkspaceNode|null,needle:string):WorkspaceNode|null{
 if(!node)return null
 if(node.kind==='pane')return node.id===needle?null:node
 if(node.kind==='tabs'){
  const remaining=node.panes.filter(p=>p.id!==needle)
  if(remaining.length===0)return null
  if(remaining.length===1)return remaining[0]
  return {...node,panes:remaining,active:remaining.some(p=>p.id===node.active)?node.active:remaining[0].id}
 }
 const a=removePane(node.first,needle),b=removePane(node.second,needle)
 return !a?b:!b?a:{...node,first:a,second:b}
}
export type DockSide='left'|'right'|'top'|'bottom'|'center'
export function insertPane(root:WorkspaceNode|null,target:string|undefined,newPane:Pane,side:DockSide='right'):WorkspaceNode{
 if(!root)return newPane
 const insert=(node:WorkspaceNode):WorkspaceNode=>{
  if(node.kind==='split')return {...node,first:insert(node.first),second:insert(node.second)}
  if(node.id!==target&&!(node.kind==='tabs'&&node.panes.some(p=>p.id===target)))return node
  if(side==='center')return node.kind==='tabs'?{...node,panes:[...node.panes,newPane],active:newPane.id}:{kind:'tabs',id:id(),active:newPane.id,panes:[node,newPane]}
  const direction=side==='left'||side==='right'?'horizontal':'vertical'
  return {kind:'split',id:id(),direction,ratio:.5,first:side==='left'||side==='top'?newPane:node,second:side==='left'||side==='top'?node:newPane}
 }
 const next=insert(root)
 // When opening from drawer, append to root as a horizontal split.
 return target?next:{kind:'split',id:id(),direction:'horizontal',ratio:.68,first:root,second:newPane}
}
export function movePane(root:WorkspaceNode|null,source:string,target:string,side:DockSide):WorkspaceNode|null{
 if(!root||source===target)return root
 let moving:Pane|undefined;traverse(root,p=>{if(p.id===source)moving=p})
 if(!moving)return root
 const pruned=removePane(root,source)
 return insertPane(pruned,target,moving,side)
}
export function layoutValid(value:any):value is LayoutDocument{
 if(value?.version!==2||!value?.root||!Array.isArray(value.floating))return false
 let count=0,valid=true
 const inspect=(n:any,depth:number)=>{
  if(depth>25||++count>100){valid=false;return}
  if(n.kind==='pane'){if(typeof n.id!=='string'||typeof n.type!=='string'||!n.config||typeof n.config!=='object')valid=false}
  else if(n.kind==='tabs'){if(!Array.isArray(n.panes)||n.panes.length>30)valid=false;else n.panes.forEach((p:any)=>inspect(p,depth+1))}
  else if(n.kind==='split'){if(!(n.ratio>0&&n.ratio<1))valid=false;inspect(n.first,depth+1);inspect(n.second,depth+1)}
  else valid=false
 }
 inspect(value.root,0)
 return valid&&value.floating.length<=20
}
