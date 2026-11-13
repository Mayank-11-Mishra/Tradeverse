import test from 'node:test'
import assert from 'node:assert/strict'
import {heikinAshi,renko,pointFigure,mergeLiveMinute,mergeLiveMinutes,DEFAULT_CHART_PARAMETERS} from '../src/chartTransforms.ts'
const bars=[{ts:'2026-11-12T09:15:00+05:30',open:100,high:110,low:90,close:105,volume:10},{ts:'2026-11-12T09:16:00+05:30',open:105,high:120,low:103,close:118,volume:20},{ts:'2026-11-12T09:17:00+05:30',open:118,high:125,low:115,close:124,volume:30}]
test('HA standard first/open formulas and bounds',()=>{const h=heikinAshi(bars);assert.equal(h[0].open,102.5);assert.equal(h[0].close,101.25);assert.equal(h[1].open,(102.5+101.25)/2);assert.ok(h[2].high>=h[2].close)})
test('close Renko creates multiple bricks for same source close',()=>{const r=renko(bars,{...DEFAULT_CHART_PARAMETERS,brickSize:5});assert.equal(r.length,3);assert.ok(r.every(x=>Math.abs(x.open-x.close)===5));assert.ok(new Set(r.map(x=>x.ts)).size===r.length)})
test('P&F reversals need reversal number boxes',()=>{const r=pointFigure([...bars,{...bars[2],ts:'2026-11-12T09:18:00+05:30',close:100}],{...DEFAULT_CHART_PARAMETERS,boxSize:5,reversal:3});assert.equal(r.at(-1)?.direction,'O');assert.ok(r.at(-1)?.boxes.length>=3)})
test('minute merges into 15-minute bucket',()=>{const b=mergeLiveMinute([],bars[1],'15m');assert.equal(new Date(b[0].ts).toISOString(),'2026-11-12T03:45:00.000Z')})

test('live 1m candles aggregate OHLC correctly into a 15m bucket',()=>{
 const make=(minute,open,high,low,close,volume)=>({ts:`2026-11-13T03:${String(minute).padStart(2,'0')}:00.000Z`,open,high,low,close,volume})
 const data=[make(45,100,105,99,103,10),make(46,103,108,102,107,20),make(47,107,109,106,108,30)]
 const result=mergeLiveMinutes([],data,'15m')
 assert.equal(result.length,1)
 assert.equal(result[0].open,100)
 assert.equal(result[0].high,109)
 assert.equal(result[0].low,99)
 assert.equal(result[0].close,108)
 assert.equal(result[0].volume,60)
})

test('live daily candles follow same exchange-local date',()=>{
 const b=[{ts:'2026-11-13T03:46:00Z',open:10,high:12,low:9,close:11,volume:7},
 {ts:'2026-11-13T03:47:00Z',open:11,high:14,low:11,close:13,volume:8}]
 const result=mergeLiveMinutes([],b,'1d')
 assert.equal(result.length,1)
 assert.equal(result[0].high,14)
 assert.equal(result[0].close,13)
})
