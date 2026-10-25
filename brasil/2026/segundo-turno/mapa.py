#!/usr/bin/env python3
"""Mapa ao vivo por município: % de Lula no 2º turno apurado e desvio frente ao 1º turno.

  web/municipios.geojson  malha simplificada (geodata-br, código IBGE em `id`), gerada uma vez
  web/dados.json          por código IBGE: base do 1º turno, % Lula no 2º, % apurado; e a projeção
  web/index.html          Leaflet; recarrega dados.json a cada 60 s

Uso: python3 mapa.py [--loop 60]   e servir web/ com  python3 -m http.server -d web 8765
"""
import argparse, json, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"


def malha():
    destino = WEB / "municipios.geojson"
    if destino.exists():
        return
    import geopandas as gpd
    import pandas as pd
    partes = [gpd.read_file(f) for f in sorted((HERE / "data" / "geo").glob("mun-*.json"))]
    g = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=partes[0].crs)[["id", "name", "geometry"]]
    g["geometry"] = g.geometry.simplify(0.01, preserve_topology=True)
    destino.write_text(g.to_json(drop_id=True, to_wgs84=True))
    print(f"malha: {len(g)} municípios, {destino.stat().st_size / 1e6:.1f} MB")


def dados():
    from modelo import projetar
    cfg = json.loads((HERE / "data" / "municipios.json").read_text())
    ibge = {a["cd"] + x["cd"]: x.get("cdi") for a in cfg["abr"] for x in a["mu"]}
    m, res, tot = projetar(2000)
    out = {}
    for i, r in m.iterrows():
        c = ibge.get(i)
        if not c:
            continue
        v2 = r.lula2 + r.flavio2
        out[c] = {"b": round(r.base, 4), "l2": round(r.lula2 / v2, 4) if v2 else None,
                  "p": round(r.pst2, 3), "v": int(r.validos)}
    resumo = {k: round(float(v), 4) for k, v in (res or {}).items() if k != "margens"} | {k: round(float(v), 4) for k, v in tot.items()}
    resumo["hora"] = time.strftime("%H:%M:%S")
    (WEB / "dados.json").write_text(json.dumps({"resumo": resumo, "mun": out}))


HTML = """<!doctype html><html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>2º turno 2026</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
:root{--bg:#fafaf8;--fg:#1a1a1a;--mut:#6b6b6b;--card:#fff;--line:#ddd}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#eee;--mut:#9a9a9a;--card:#1e1e1e;--line:#333}}
body{margin:0;font:14px/1.4 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:12px 16px;display:flex;flex-wrap:wrap;gap:16px;align-items:baseline}
h1{font-size:18px;margin:0}.big{font-size:22px;font-weight:600}.mut{color:var(--mut)}
#map{height:calc(100vh - 110px);background:var(--bg)}
.tog{display:flex;gap:6px}.tog button{border:1px solid var(--line);background:var(--card);color:var(--fg);padding:4px 10px;border-radius:6px;cursor:pointer}
.tog button.on{border-color:var(--fg);font-weight:600}
.leg{background:var(--card);color:var(--fg);padding:6px 8px;border-radius:6px;font-size:12px}
.leg i{display:inline-block;width:18px;height:10px}
</style></head><body>
<header><h1>2º turno presidencial 2026</h1>
<div><span class="mut">Projeção Lula</span> <span class="big" id="proj">–</span> <span class="mut" id="ic"></span></div>
<div><span class="mut">P(Lula vence)</span> <span class="big" id="pw">–</span></div>
<div class="mut" id="ap"></div>
<div class="tog"><button id="b1" class="on">% Lula apurado</button><button id="b2">Desvio vs 1º turno</button></div></header>
<div id="map"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const map=L.map('map',{zoomSnap:.25}).setView([-14.5,-52],4.25);
let modo='l2',D={mun:{}},layer;
const pct=x=>(100*x).toFixed(1)+'%';
// Divergente: vermelho = Flávio, azul = Lula (centro 50%); desvio em pontos
const C=['#b2182b','#d6604d','#f4a582','#fddbc7','#d1e5f0','#92c5de','#4393c3','#2166ac'];
function cor(d){if(!d||d.l2==null)return '#bbb';
 if(modo==='l2'){const t=[.35,.42,.47,.5,.53,.58,.65];let i=t.findIndex(v=>d.l2<v);return C[i<0?7:i]}
 const s=d.l2-d.b,t=[-.06,-.03,-.01,0,.01,.03,.06];let i=t.findIndex(v=>s<v);return C[i<0?7:i]}
function estilo(f){const d=D.mun[f.properties.id];return{fillColor:cor(d),fillOpacity:d&&d.p>0?.35+.6*d.p:.25,weight:.2,color:'#666'}}
function legenda(){const el=document.getElementById('leg');if(!el)return;
 el.innerHTML=(modo==='l2'?'% Lula no 2º turno (apurado)<br>':'Lula 2º turno − base 1º turno<br>')+
 C.map((c,i)=>'<i style="background:'+c+'"></i>').join('')+'<br><span>'+(modo==='l2'?'35%  ·  50%  ·  65%':'−6 pts  ·  0  ·  +6 pts')+'</span>'}
const lg=L.control({position:'bottomright'});lg.onAdd=()=>{const d=L.DomUtil.create('div','leg');d.id='leg';return d};lg.addTo(map);
fetch('municipios.geojson').then(r=>r.json()).then(g=>{
 layer=L.geoJSON(g,{style:estilo,onEachFeature:(f,l)=>l.on('mouseover',()=>{const d=D.mun[f.properties.id]||{};
  l.bindTooltip('<b>'+f.properties.name+'</b><br>Base 1º turno: '+(d.b!=null?pct(d.b):'–')+'<br>Lula 2º turno: '+(d.l2!=null?pct(d.l2):'–')+'<br>Apurado: '+(d.p!=null?pct(d.p):'–')).openTooltip()})}).addTo(map);
 carregar();setInterval(carregar,60000)});
function carregar(){fetch('dados.json?'+Date.now()).then(r=>r.json()).then(j=>{D=j;const r=j.resumo;
 document.getElementById('proj').textContent=r.final_med!=null?pct(r.final_med):pct(r.lula_atual||0);
 document.getElementById('ic').textContent=r.lo!=null?'(90%: '+pct(r.lo)+'–'+pct(r.hi)+')':'(sem projeção ainda)';
 document.getElementById('pw').textContent=r.p_lula!=null?pct(r.p_lula):'–';
 document.getElementById('ap').textContent='apurado ~'+pct(r.apurado||0)+' · atualizado '+r.hora;
 layer&&layer.setStyle(estilo);legenda()})}
for(const [id,m] of [['b1','l2'],['b2','sw']])document.getElementById(id).onclick=()=>{modo=m;
 document.querySelectorAll('.tog button').forEach(b=>b.classList.toggle('on',b.id===id));layer.setStyle(estilo);legenda()};
</script></body></html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0)
    a = ap.parse_args()
    WEB.mkdir(exist_ok=True)
    malha()
    (WEB / "index.html").write_text(HTML)
    while True:
        dados()
        if not a.loop:
            break
        time.sleep(a.loop)
