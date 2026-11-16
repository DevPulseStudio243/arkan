"""
pid_viewer.py
=============
PDF vectoriel -> segments / symboles / étiquettes -> CircuitGraph -> viewer HTML autonome
où un clic sur une conduite surligne la ligne (ou tout le circuit).

Usage :  python pid_viewer.py plan.pdf sortie.html [--page N] [--snap 1.0]

Les heuristiques de classification des symboles (vanne = petite forme fermée, flèche = petit triangle,
instrument = cercle, équipement = grand rectangle) sont à régler pour TES plans : voir les paramètres
d'extract_page. Un PDF scanné (sans vecteurs) ne donnera aucun segment : voir le message d'erreur.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import re
import sys
from typing import Any, Dict, List, Tuple

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # message explicite plutot qu'un ModuleNotFoundError brut
    raise SystemExit("pid_viewer necessite PyMuPDF : pip install pymupdf") from exc

try:
    from circuit_graph import CircuitGraph, Symbol
except ImportError as exc:
    raise SystemExit(
        f"pid_viewer necessite circuit_graph.py (numpy, scipy, networkx) et piping_topology_tracer.py : {exc}") from exc

# Les tags reels portent souvent un prefixe de zone (201-HV-003, 201-PP-001/A) : il est accepte, sinon aucune vanne
# ni aucun equipement du plan n'etait reconnu.
_VALVE_TAG = re.compile(r"^(?:\d{2,4}[-_\s])?(HV|XV|SDV|ESDV|BDV|PSV|PRV|PSE|MOV|NRV|CV|PV|LV|FV|TV)[-\s]?\d{2,5}[A-Z]?$", re.I)
_EQUIP_TAG = re.compile(r"^(?:\d{2,4}[-_\s])?[A-Z]{1,3}[-\s]?\d{3,4}[A-Z]?(?:/[A-Z])?$", re.I)


def _bez(p1, c1, c2, p2, n=6):
    pts = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        pts.append((u ** 3 * p1.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t ** 3 * p2.x,
                    u ** 3 * p1.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t ** 3 * p2.y))
    return pts


def extract_page(page: "fitz.Page", sym_max: float = 30.0, equip_min: float = 30.0):
    W = page.rect.width
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    small: List[Dict[str, Any]] = []     # petites formes fermées (vannes, flèches, instruments)
    symbols: List[Symbol] = []

    for d in page.get_drawings():
        items, r = d["items"], d["rect"]
        kinds = {it[0] for it in items}
        if r.width > 0.9 * W:            # cadre / cartouche
            continue
        if kinds <= {"re", "qu"}:
            for it in items:
                rc = it[1] if it[0] == "re" else it[1].rect
                if rc.width >= equip_min and rc.height >= equip_min:
                    symbols.append(Symbol("equipment", (rc.x0 + rc.x1) / 2, (rc.y0 + rc.y1) / 2, rc.width, rc.height))
                else:
                    small.append({"rect": rc, "items": [it]})
            continue
        closed = bool(d.get("closePath")) or d.get("fill") is not None
        if closed and max(r.width, r.height) <= sym_max:
            small.append({"rect": r, "items": items})
            continue
        if closed and kinds == {"l"} and min(r.width, r.height) >= equip_min:
            symbols.append(Symbol("equipment", (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, r.width, r.height))
            continue
        for it in items:
            if it[0] == "l":
                segments.append(((it[1].x, it[1].y), (it[2].x, it[2].y)))
            elif it[0] == "c":
                pts = [(it[1].x, it[1].y)] + _bez(it[1], it[2], it[3], it[4])
                segments.extend((pts[i], pts[i + 1]) for i in range(len(pts) - 1))

    # regroupe les petites formes qui se touchent (nœud papillon = 2 triangles)
    n = len(small)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            a, b = small[i]["rect"], small[j]["rect"]
            if a.x0 - 0.6 <= b.x1 and b.x0 - 0.6 <= a.x1 and a.y0 - 0.6 <= b.y1 and b.y0 - 0.6 <= a.y1:
                parent[find(i)] = find(j)
    clusters: Dict[int, List[Dict[str, Any]]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(small[i])
    for cl in clusters.values():
        x0 = min(c["rect"].x0 for c in cl); y0 = min(c["rect"].y0 for c in cl)
        x1 = max(c["rect"].x1 for c in cl); y1 = max(c["rect"].y1 for c in cl)
        cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
        all_items = [it for c in cl for it in c["items"]]
        n_curves = sum(1 for it in all_items if it[0] == "c")
        if n_curves >= 4 and 0.7 < w / max(h, 1e-6) < 1.4:
            symbols.append(Symbol("instrument", cx, cy, w, h))
        elif len(cl) == 1 and len(all_items) == 3 and all(it[0] == "l" for it in all_items) and max(w, h) <= 14:
            v = [(it[1].x, it[1].y) for it in all_items]
            sides = [(math.dist(v[(k + 1) % 3], v[(k + 2) % 3]), k) for k in range(3)]  # côté opposé au sommet k
            base_k = min(sides)[1]                       # sommet opposé au plus petit côté = pointe
            b1, b2 = v[(base_k + 1) % 3], v[(base_k + 2) % 3]
            mid = ((b1[0] + b2[0]) / 2, (b1[1] + b2[1]) / 2)
            ux, uy = v[base_k][0] - mid[0], v[base_k][1] - mid[1]
            norm = math.hypot(ux, uy) or 1.0
            symbols.append(Symbol("arrow", cx, cy, w, h, ux=ux / norm, uy=uy / norm))
        else:
            symbols.append(Symbol("valve", cx, cy, w, h))

    # texte
    labels: List[Dict[str, Any]] = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            text = "".join(sp["text"] for sp in ln["spans"]).strip()
            if text:
                bx = ln["bbox"]
                labels.append({"text": text, "x": (bx[0] + bx[2]) / 2, "y": (bx[1] + bx[3]) / 2, "bbox": bx})

    # tags des symboles = texte le plus proche du bon type
    for sym in symbols:
        if sym.kind == "valve":
            cands = [l for l in labels if _VALVE_TAG.match(l["text"]) and math.dist((l["x"], l["y"]), (sym.x, sym.y)) <= 35]
        elif sym.kind == "equipment":
            cands = [l for l in labels if _EQUIP_TAG.match(l["text"]) and abs(l["x"] - sym.x) <= sym.w / 2 + 12 and abs(l["y"] - sym.y) <= sym.h / 2 + 12]
        elif sym.kind == "instrument":
            inside = [l for l in labels if abs(l["x"] - sym.x) <= sym.w / 2 and abs(l["y"] - sym.y) <= sym.h / 2]
            sym.tag = "-".join(l["text"] for l in sorted(inside, key=lambda l: l["y"]))
            continue
        else:
            continue
        if cands:
            sym.tag = min(cands, key=lambda l: math.dist((l["x"], l["y"]), (sym.x, sym.y)))["text"].upper().replace(" ", "-")
    return segments, symbols, labels


def best_page(doc: "fitz.Document") -> int:
    return max(range(len(doc)), key=lambda i: len(doc[i].get_drawings()))


def analyse_pdf(path: str, page_no: int | None = None, snap_tol: float = 1.0) -> Tuple["fitz.Page", CircuitGraph]:
    doc = fitz.open(path)
    page = doc[page_no if page_no is not None else best_page(doc)]
    segments, symbols, labels = extract_page(page)
    if not segments:
        raise SystemExit("Aucun segment vectoriel sur cette page : PDF scanné ? Utiliser la détection de lignes par image (OpenCV) à la place.")
    return page, CircuitGraph(segments, symbols, labels, snap_tol=snap_tol)


_HTML = """<!doctype html><html lang="fr"><meta charset="utf-8"><title>P&ID — suivi de circuit</title>
<style>
:root{--bg:#fff;--fg:#1d1d1f;--panel:#f4f5f7;--line:#d0d3d9;--hl:#e8590c;--ci:#1971c2}
@media(prefers-color-scheme:dark){:root{--bg:#16181d;--fg:#e8eaed;--panel:#20232a;--line:#3a3f4a;--hl:#ff922b;--ci:#74c0fc}}
html,body{height:100%;margin:0}body{display:flex;font:14px system-ui,sans-serif;background:var(--bg);color:var(--fg)}
#view{flex:1;overflow:auto;position:relative}#side{width:320px;padding:14px;background:var(--panel);border-left:1px solid var(--line);overflow:auto}
svg{position:absolute;left:0;top:0}.seg{stroke:transparent;stroke-width:12;cursor:pointer}.vis{stroke:none}
.on{stroke:var(--hl)!important;stroke-width:4!important}.ci{stroke:var(--ci)!important;stroke-width:3!important}
h3{margin:.2em 0 .5em}code{background:var(--bg);padding:1px 5px;border-radius:4px}.muted{opacity:.7}ol{padding-left:20px}
</style><body><div id="view"><img id="bg" src="data:image/png;base64,__IMG__"><svg id="ov"></svg></div>
<div id="side"><h3>Suivi de circuit</h3><label><input type="checkbox" id="circ"> Surligner tout le circuit</label>
<p class="muted">Clique sur une conduite du plan.</p><div id="info"></div></div>
<script>
const D=__DATA__,Z=__ZOOM__,ov=document.getElementById('ov'),bg=document.getElementById('bg'),NS='http://www.w3.org/2000/svg';
function build(){ov.setAttribute('width',bg.width);ov.setAttribute('height',bg.height);
D.segments.forEach((s,i)=>{const l=document.createElementNS(NS,'line');
[['x1',s[0]],['y1',s[1]],['x2',s[2]],['y2',s[3]]].forEach(([k,v])=>l.setAttribute(k,v*Z));
l.setAttribute('class','seg');l.dataset.i=i;l.dataset.c=D.chain_of_segment[i];ov.appendChild(l)})}
bg.complete?build():bg.onload=build;
const esc=t=>String(t).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function show(ci){const c=D.chains[ci],all=document.getElementById('circ').checked;
ov.querySelectorAll('line').forEach(l=>{l.classList.remove('on','ci');const k=D.chains[+l.dataset.c];
if(+l.dataset.c===ci)l.classList.add('on');else if(all&&k&&k.circuit===c.circuit)l.classList.add('ci')});
const path=[c.from.tag,...c.components.map(k=>k.tag),c.to.tag].map(t=>'<li><code>'+esc(t)+'</code></li>').join('');
document.getElementById('info').innerHTML='<p><b>'+esc(c.tag||'(ligne sans étiquette)')+'</b></p><ol>'+path+'</ol>'+
'<p>Sens : '+(c.flow_known?'déduit ('+c.flow_basis+')':'<i>indéterminé</i>')+'<br>Confiance : '+c.confidence+'</p>'+
(c.reasons.length?'<ul>'+c.reasons.map(r=>'<li>'+esc(r)+'</li>').join('')+'</ul>':'')}
let cur=-1;ov.addEventListener('click',e=>{if(e.target.dataset&&e.target.dataset.c!==undefined){cur=+e.target.dataset.c;show(cur)}});
document.getElementById('circ').onchange=()=>{if(cur>=0)show(cur)};
</script></body></html>"""


def build_viewer(pdf: str, out_html: str, page_no: int | None = None, snap_tol: float = 1.0, zoom: float = 1.5) -> CircuitGraph:
    page, graph = analyse_pdf(pdf, page_no, snap_tol)
    png = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")
    html = (_HTML.replace("__IMG__", base64.b64encode(png).decode())
                 .replace("__DATA__", json.dumps(graph.to_dict()))
                 .replace("__ZOOM__", str(zoom)))
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    return graph


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf"); ap.add_argument("out_html")
    ap.add_argument("--page", type=int, default=None); ap.add_argument("--snap", type=float, default=1.0)
    a = ap.parse_args()
    g = build_viewer(a.pdf, a.out_html, a.page, a.snap)
    print(f"{len(g.segments)} segments, {len(g.chains)} lignes, {len({c['circuit'] for c in g.chains})} circuits -> {a.out_html}")
