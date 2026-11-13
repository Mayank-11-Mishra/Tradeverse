import test from 'node:test'
import assert from 'node:assert/strict'
import {defaultWorkspace,pane,insertPane,removePane,movePane,traverse,layoutValid} from '../src/workspaceLayout.ts'
test('first layout is chart-only',()=>{const l=defaultWorkspace();const panes=[];traverse(l.root,p=>panes.push(p));assert.deepEqual(panes.map(x=>x.type),['chart']);assert.ok(layoutValid(l))})
test('splits, tab stacks and removals preserve remaining panels',()=>{const l=defaultWorkspace();const a=pane('watchlist'),b=pane('orders');let root=insertPane(l.root,undefined,a);root=insertPane(root,a.id,b,'center');let ps=[];traverse(root,p=>ps.push(p.type));assert.deepEqual(ps,['chart','watchlist','orders']);root=removePane(root,a.id);ps=[];traverse(root,p=>ps.push(p.type));assert.deepEqual(ps,['chart','orders'])})
test('drag tile moves a tab without duplication',()=>{const a=defaultWorkspace();const initial=a.root.id,b=pane('watchlist');let root=insertPane(a.root,undefined,b);root=movePane(root,b.id,initial,'top');const ids=[];traverse(root,p=>ids.push(p.id));assert.equal(new Set(ids).size,2)})

test('tile mode preference is a layout extension and does not rewrite tab/dock tree',()=>{
 const l=defaultWorkspace();const b=pane('watchlist');const c=pane('orders');l.root=insertPane(l.root,undefined,b)
 l.root=insertPane(l.root,b.id,c,'center');const before=JSON.stringify(l.root)
 l.mode='tile';l.tilePreset='2x2';l.tileOrder=[b.id,c.id]
 assert.equal(layoutValid(l),true);assert.equal(l.tilePreset,'2x2')
 l.mode='tab';assert.equal(JSON.stringify(l.root),before)
})
test('new chart has no default EMA series and starts in tab mode',()=>{
 const l=defaultWorkspace();assert.equal(l.mode,'tab')
 assert.equal(l.root.type,'chart');assert.equal(l.root.config.ema9,undefined);assert.equal(l.root.config.ema21,undefined)
})
