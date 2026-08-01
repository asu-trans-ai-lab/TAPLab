"""TAPView: a TAP-specific interactive network viewer.

`taplab view <instance>` writes a single self-contained HTML file (no server,
no external libraries) with:

  Network layers   - physical links, centroid connectors, centroid nodes,
                     physical nodes (each toggleable)
  Assignment layers- link volume (width), volume/capacity ratio, congested
                     travel time ratio tt/fftt, capacity, free-flow time
  Difference layers- solver A vs solver B flow difference (diverging ramp)
                     with an adjustable threshold that hides agreeing links
  Inspection       - click any link for its attributes plus volume and travel
                     time per solver, with absolute and percentage differences

Solvers are discovered from results/<instance>/<solver>/link_performance.csv;
the instance's reference/ solution appears as pseudo-solver "reference".
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path


def _load_solver_flows(res_dir: Path, instance):
    out = {}
    ref = instance.path / "reference" / "link_performance.csv"
    if ref.exists():
        out["reference"] = _read_lp(ref)
    if res_dir.exists():
        for d in sorted(res_dir.iterdir()):
            lp = d / "link_performance.csv"
            if d.is_dir() and lp.exists():
                out[d.name] = _read_lp(lp)
    return out


def _read_lp(path: Path):
    m = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        try:
            k = f'{int(float(r["from_node_id"]))}-{int(float(r["to_node_id"]))}'
            tt = r.get("travel_time")
            m[k] = [round(float(r["volume"]), 2),
                    round(float(tt), 4) if tt not in (None, "", "None") else None]
        except (ValueError, KeyError):
            pass
    return m


def build_view(instance, res_dir: Path, out: Path):
    nodes = {}
    for n in instance.nodes:
        nid = int(float(n["node_id"]))
        nodes[nid] = [float(n["x_coord"]), float(n["y_coord"]),
                      1 if (n.get("node_type") or "").strip() == "centroid"
                      or (n.get("zone_id") and float(n["zone_id"] or 0) > 0) else 0]

    # planar projection: equirectangular correction if coords look like lon/lat
    xs = [v[0] for v in nodes.values()]
    ys = [v[1] for v in nodes.values()]
    if xs and -180 <= min(xs) <= max(xs) <= 180 and -90 <= min(ys) <= max(ys) <= 90:
        klon = math.cos(math.radians(sum(ys) / len(ys)))
        for v in nodes.values():
            v[0] *= klon

    links = []
    for r in instance.links:
        a, b = instance.link_key(r)
        if a not in nodes or b not in nodes:
            continue
        fs = float(r.get("free_speed") or 30) or 30
        fftt = float(r.get("vdf_fftt") or 0) or (float(r["length"]) / fs * 60.0
                                                 if float(r.get("length") or 0) > 0 else 0)
        links.append(dict(
            id=r.get("link_id", ""), a=a, b=b,
            t=1 if (r.get("link_type") or "").strip() == "centroid_connector" else 0,
            cap=float(r.get("capacity") or 0), fftt=round(fftt, 4),
            al=float(r.get("vdf_alpha") or 0.15), be=float(r.get("vdf_beta") or 4.0),
            ln=float(r.get("length") or 0)))

    solvers = _load_solver_flows(res_dir, instance)
    payload = json.dumps(dict(name=instance.path.name, nodes=nodes,
                              links=links, solvers=solvers),
                         separators=(",", ":"))

    html = _TEMPLATE.replace("__PAYLOAD__", payload) \
                    .replace("__NAME__", instance.path.name)
    out.write_text(html, encoding="utf-8")
    return out


_TEMPLATE = r"""<!doctype html><meta charset="utf-8">
<title>TAPView — __NAME__</title>
<style>
 body{margin:0;font-family:Segoe UI,system-ui,sans-serif;display:flex;height:100vh;color:#1c1c1c}
 #panel{width:250px;min-width:250px;padding:12px;border-right:1px solid #ddd;overflow-y:auto;background:#f4f5f7}
 #panel h1{font-size:15px;margin:0 0 2px;color:#245a8d}
 #panel h2{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#666;margin:14px 0 4px}
 #panel label{display:block;font-size:13px;margin:2px 0}
 #panel select,#panel input[type=range]{width:100%}
 #map{flex:1;background:#fff;cursor:grab}
 #info{position:fixed;right:12px;top:12px;max-width:330px;background:#fff;border:1px solid #bbb;border-radius:8px;
   box-shadow:0 2px 10px rgba(0,0,0,.15);padding:10px 12px;font-size:12px;display:none;max-height:85vh;overflow:auto}
 #info table{border-collapse:collapse;margin-top:4px}
 #info td,#info th{border:1px solid #ccc;padding:2px 6px;text-align:right}
 #info td:first-child,#info th:first-child{text-align:left}
 #legend{position:fixed;left:262px;bottom:10px;background:#fff;border:1px solid #ccc;border-radius:6px;padding:6px 10px;font-size:11px}
 .sub{font-size:11px;color:#666}
</style>
<div id="panel">
 <h1>TAPView</h1><div class="sub">__NAME__ &middot; TAPLab</div>
 <h2>Network layers</h2>
 <label><input type="checkbox" id="Lphys" checked> physical links</label>
 <label><input type="checkbox" id="Lconn" checked> centroid connectors</label>
 <label><input type="checkbox" id="Lcent" checked> centroid nodes</label>
 <label><input type="checkbox" id="Lnode"> physical nodes</label>
 <h2>Assignment layer</h2>
 <label>solver A <select id="solA"></select></label>
 <label>metric <select id="metric">
   <option value="vc">volume / capacity</option>
   <option value="vol">volume</option>
   <option value="ttr">congestion tt / fftt</option>
   <option value="cap">capacity</option>
   <option value="diff">difference A − B</option>
 </select></label>
 <label id="rowB" style="display:none">solver B <select id="solB"></select></label>
 <label id="rowThr" style="display:none">|difference| ≥ <span id="thrv">0</span>
   <input type="range" id="thr" min="0" max="100" value="0"></label>
 <label><input type="checkbox" id="widthByVol" checked> width by volume</label>
 <h2>Hint</h2>
 <div class="sub">drag to pan, wheel to zoom, click a link to inspect it.</div>
</div>
<svg id="map"></svg>
<div id="legend"></div>
<div id="info"></div>
<script>
const D=__PAYLOAD__;
const svg=document.getElementById('map'),info=document.getElementById('info'),legend=document.getElementById('legend');
const solNames=Object.keys(D.solvers);
for(const id of['solA','solB']){const s=document.getElementById(id);
  solNames.forEach(n=>{const o=document.createElement('option');o.value=o.textContent=n;s.appendChild(o)});
  if(!solNames.length){const o=document.createElement('option');o.value='';o.textContent='(none)';s.appendChild(o)}}
if(solNames.length>1)document.getElementById('solB').value=solNames[1];

// fit view
let xs=Object.values(D.nodes).map(n=>n[0]),ys=Object.values(D.nodes).map(n=>n[1]);
let x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
let W=svg.clientWidth||900,H=svg.clientHeight||700,pad=30;
let sc=Math.min((W-2*pad)/((x1-x0)||1),(H-2*pad)/((y1-y0)||1));
const X=x=>(x-x0)*sc+pad, Y=y=>H-((y-y0)*sc+pad);
let vb={x:0,y:0,w:W,h:H};
function setVB(){svg.setAttribute('viewBox',`${vb.x} ${vb.y} ${vb.w} ${vb.h}`)}
setVB();

const gL=document.createElementNS('http://www.w3.org/2000/svg','g');
const gN=document.createElementNS('http://www.w3.org/2000/svg','g');
svg.appendChild(gL);svg.appendChild(gN);
const lines=[];
for(const l of D.links){
  const e=document.createElementNS('http://www.w3.org/2000/svg','line');
  const A=D.nodes[l.a],B=D.nodes[l.b];
  e.setAttribute('x1',X(A[0]));e.setAttribute('y1',Y(A[1]));
  e.setAttribute('x2',X(B[0]));e.setAttribute('y2',Y(B[1]));
  e.style.cursor='pointer';
  e.addEventListener('click',ev=>{ev.stopPropagation();inspect(l)});
  gL.appendChild(e);lines.push(e);
}
const dots=[];
for(const[id,n]of Object.entries(D.nodes)){
  const c=document.createElementNS('http://www.w3.org/2000/svg','circle');
  c.setAttribute('cx',X(n[0]));c.setAttribute('cy',Y(n[1]));
  c.setAttribute('r',n[2]?3:1.4);
  c.setAttribute('fill',n[2]?'#245a8d':'#999');
  c.dataset.cent=n[2];gN.appendChild(c);dots.push(c);
}

function rampVC(v){ // 0 green -> 1 red -> 1.5+ purple
  if(v==null)return '#ccc';
  if(v<=0.5)return `rgb(${Math.round(60+270*v)},170,60)`;
  if(v<=1.0)return `rgb(220,${Math.round(170-260*(v-0.5))},40)`;
  return v<=1.5?`rgb(${Math.round(220-160*(v-1))},40,${Math.round(40+300*(v-1))})`:'#8e44ad';
}
function rampDiv(v,m){ // diverging blue-white-red
  if(v==null||!m)return '#ccc';
  const t=Math.max(-1,Math.min(1,v/m));
  return t>=0?`rgb(220,${Math.round(220-180*t)},${Math.round(220-200*t)})`
             :`rgb(${Math.round(220+200*t)},${Math.round(220+180*t)},220)`;
}
function flow(sol,l){const s=D.solvers[sol];if(!s)return null;const r=s[l.a+'-'+l.b];return r?r[0]:null}
function ttime(sol,l){const s=D.solvers[sol];if(!s)return null;const r=s[l.a+'-'+l.b];return r?r[1]:null}
function bpr(l,v){return l.cap>0?l.fftt*(1+l.al*Math.pow(v/l.cap,l.be)):l.fftt}

let maxVol=1,maxCap=1,maxDiff=1;
function render(){
  const A=document.getElementById('solA').value,B=document.getElementById('solB').value;
  const metric=document.getElementById('metric').value;
  const wByV=document.getElementById('widthByVol').checked;
  document.getElementById('rowB').style.display=metric==='diff'?'block':'none';
  document.getElementById('rowThr').style.display=metric==='diff'?'block':'none';
  const showP=document.getElementById('Lphys').checked,showC=document.getElementById('Lconn').checked;
  maxVol=1;maxDiff=0;maxCap=1;
  for(const l of D.links){const v=flow(A,l);if(v!=null)maxVol=Math.max(maxVol,v);maxCap=Math.max(maxCap,l.cap);
    if(metric==='diff'){const w=flow(B,l);if(v!=null&&w!=null)maxDiff=Math.max(maxDiff,Math.abs(v-w))}}
  const thr=(+document.getElementById('thr').value/100)*maxDiff;
  document.getElementById('thrv').textContent=Math.round(thr).toLocaleString();
  D.links.forEach((l,i)=>{
    const e=lines[i];
    if((l.t&&!showC)||(!l.t&&!showP)){e.setAttribute('display','none');return}
    let col='#bbb',w=1,vis=true;
    const v=flow(A,l);
    if(metric==='vc')col=rampVC(v!=null&&l.cap>0?v/l.cap:null);
    else if(metric==='vol')col=v!=null?rampVC(0.999*v/maxVol):'#ccc';
    else if(metric==='ttr'){const t=ttime(A,l)??(v!=null?bpr(l,v):null);
      col=t!=null&&l.fftt>0?rampVC((t/l.fftt-1)):'#ccc'}
    else if(metric==='cap')col=rampVC(0.999*l.cap/maxCap);
    else if(metric==='diff'){const u=flow(B,l);
      if(v==null||u==null){col='#eee'}else{const d=v-u;col=rampDiv(d,maxDiff);vis=Math.abs(d)>=thr;}}
    if(l.t){e.setAttribute('stroke-dasharray','3,3');}else e.removeAttribute('stroke-dasharray');
    if(wByV&&v!=null)w=0.6+3.4*Math.sqrt(v/maxVol);
    e.setAttribute('stroke',vis?col:'#f2f2f2');
    e.setAttribute('stroke-width',w*(vb.w/W));
    e.removeAttribute('display');
  });
  dots.forEach(c=>{c.setAttribute('display',
     (c.dataset.cent==='1'?document.getElementById('Lcent'):document.getElementById('Lnode')).checked?'':'none');
     c.setAttribute('r',(c.dataset.cent==='1'?3:1.4)*(vb.w/W));});
  const names={vc:'v/c ratio: 0 <span style="color:#3caa3c">green</span> · 1 <span style="color:#dc2828">red</span> · ≥1.5 <span style="color:#8e44ad">purple</span>',
    vol:'volume (share of max)',ttr:'congestion: tt/fftt − 1',cap:'capacity (share of max)',
    diff:`flow difference: <span style="color:#1464dc">B higher</span> · <span style="color:#dc3c28">A higher</span> · max |Δ| ${Math.round(maxDiff).toLocaleString()}`};
  legend.innerHTML=names[metric]+(solNames.length?`<br>solver A: <b>${A}</b>`+(metric==='diff'?` · B: <b>${B}</b>`:''):'<br><i>no solver results found</i>');
}
function inspect(l){
  const rows=solNames.map(s=>{const v=flow(s,l),t=ttime(s,l)??(v!=null?bpr(l,v):null);
    return `<tr><td>${s}</td><td>${v==null?'—':v.toLocaleString()}</td><td>${t==null?'—':t.toFixed(3)}</td></tr>`}).join('');
  let d='';
  if(solNames.length>=2){const v=flow(solNames[0],l),u=flow(solNames[1],l);
    if(v!=null&&u!=null)d=`<tr><th>Δ ${solNames[0]}−${solNames[1]}</th><td>${(v-u).toFixed(1)}</td><td>${u?(100*(v-u)/u).toFixed(2)+'%':'—'}</td></tr>`}
  info.innerHTML=`<b>link ${l.id}</b> (${l.a} → ${l.b}) ${l.t?'— centroid connector':''}
   <table><tr><th>capacity</th><td colspan=2>${l.cap.toLocaleString()}</td></tr>
   <tr><th>length</th><td colspan=2>${l.ln}</td></tr>
   <tr><th>fftt (min)</th><td colspan=2>${l.fftt}</td></tr>
   <tr><th>BPR α, β</th><td colspan=2>${l.al}, ${l.be}</td></tr>
   <tr><th>v/c (A)</th><td colspan=2>${(()=>{const v=flow(document.getElementById('solA').value,l);
       return v!=null&&l.cap>0?(v/l.cap).toFixed(3):'—'})()}</td></tr>
   <tr><th>solver</th><th>volume</th><th>time</th></tr>${rows}${d}</table>
   <div class="sub" style="margin-top:4px">click map background to close</div>`;
  info.style.display='block';
}
svg.addEventListener('click',()=>info.style.display='none');

// pan / zoom
let drag=null;
svg.addEventListener('mousedown',e=>{drag={x:e.clientX,y:e.clientY,vx:vb.x,vy:vb.y};svg.style.cursor='grabbing'});
window.addEventListener('mouseup',()=>{drag=null;svg.style.cursor='grab'});
window.addEventListener('mousemove',e=>{if(!drag)return;
  vb.x=drag.vx-(e.clientX-drag.x)*(vb.w/W);vb.y=drag.vy-(e.clientY-drag.y)*(vb.h/H);setVB()});
svg.addEventListener('wheel',e=>{e.preventDefault();
  const k=e.deltaY>0?1.2:1/1.2;const r=svg.getBoundingClientRect();
  const mx=vb.x+(e.clientX-r.left)/r.width*vb.w,my=vb.y+(e.clientY-r.top)/r.height*vb.h;
  vb={x:mx-(mx-vb.x)*k,y:my-(my-vb.y)*k,w:vb.w*k,h:vb.h*k};setVB();render()},{passive:false});

['Lphys','Lconn','Lcent','Lnode','solA','solB','metric','thr','widthByVol']
 .forEach(id=>document.getElementById(id).addEventListener('input',render));
render();
</script>
"""
