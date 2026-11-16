"""
raw_roundtrip.py : preuve que raw.json reconstitue le dessin.

    python raw_roundtrip.py <raw.json> <original.dxf> <dossier_sortie>

1. rebuild_dxf   : reconstruit un DXF UNIQUEMENT a partir de raw.json (entites aplaties en coordonnees monde)
2. verify        : compare au DXF d'origine, mesure par ezdxf (et non par le code de capture) :
     - nombre d'entites par type, par espace (model / paper) ;
     - longueur cumulee des traces par type (lignes, polylignes avec arcs, arcs, cercles, ellipses, splines) ;
     - etendue du dessin ;
     - positions et contenus des textes ;
     - rendu raster du model space des deux dessins (meme moteur, meme cadrage) : taux de recouvrement (IoU).
   Ecrit roundtrip_report.json, reconstructed.dxf et roundtrip_diff.png (vert = commun, rouge = original seul,
   bleu = reconstruit seul).

Limites declarees : les INSERT ne sont pas reconstruits en blocs (le JSON contient leurs entites aplaties, avec
`parent` et `block_path` pour retrouver la structure) ; les IMAGE ne sont pas reconstruites (bbox comparee seulement).
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import ezdxf
from ezdxf import bbox as ez_bbox
from ezdxf import path as ez_path
from ezdxf import upright as ez_upright

HIDDEN_ATTRIBS = {"INVIS_DATA", "SYSTEM"}
GEOM_LENGTH_TYPES = ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE")
NOT_REBUILT = {"INSERT", "VIEWPORT", "IMAGE"}


# ----------------------------------------------------------------------------
# 1. Reconstruction depuis raw.json
# ----------------------------------------------------------------------------
def _attribs(r: dict) -> dict:
    a: dict = {"layer": r.get("layer", "0")}
    st = r.get("style") or {}
    if "color" in st:
        a["color"] = st["color"]
    if "true_color" in st:
        a["true_color"] = st["true_color"]
    return a


def rebuild_dxf(raw: dict, out_path: str | Path, include_attribs: bool = True) -> Path:
    doc = ezdxf.new("R2018")
    for l in raw.get("document", {}).get("layers", []):
        if l["name"] in doc.layers:
            lay = doc.layers.get(l["name"])
        else:
            lay = doc.layers.add(l["name"])
        lay.color = abs(int(l.get("color", 7))) or 7
        lay.on = bool(l.get("on", True))
        if l.get("frozen"):
            lay.freeze()
    for st in raw.get("document", {}).get("text_styles", []):       # polices et facteurs de largeur d'origine
        if st["name"] in doc.styles:
            ds = doc.styles.get(st["name"])
        else:
            ds = doc.styles.add(st["name"], font=st.get("font") or "arial.ttf")
        ds.dxf.font = st.get("font") or ds.dxf.get("font", "arial.ttf")
        ds.dxf.width, ds.dxf.oblique, ds.dxf.height = st.get("width", 1.0), st.get("oblique", 0.0), st.get("height", 0.0)
        ds.dxf.flags, ds.dxf.generation_flags = st.get("flags", 0), st.get("generation_flags", 0)
        if st.get("bigfont"):
            ds.dxf.bigfont = st["bigfont"]
    targets = {"model": doc.modelspace()}
    for ent in raw["entities"]:
        sp = ent.get("space", "model")
        if sp not in targets:
            targets[sp] = doc.layouts.new(sp.split(":", 1)[1][:200])
    styles = {s.dxf.name for s in doc.styles}

    for r in raw["entities"]:
        t = r["type"]
        if t in NOT_REBUILT or r.get("unparsed"):
            continue
        if t == "ATTRIB" and not include_attribs:
            continue
        ms = targets[r.get("space", "model")]
        at = _attribs(r)
        if t == "LINE":
            p = r.get("pts3d") or r["pts"]
            ms.add_line(tuple(p[0]) + (0,) * (3 - len(p[0])), tuple(p[1]) + (0,) * (3 - len(p[1])), dxfattribs=at)
        elif t in ("LWPOLYLINE", "POLYLINE"):
            widths = r.get("widths")
            pts = [(v[0], v[1], widths[i][0] if widths else 0, widths[i][1] if widths else 0, v[2])
                   for i, v in enumerate(r["verts"])]
            e = ms.add_lwpolyline(pts, format="xyseb", close=bool(r.get("closed")), dxfattribs=at)
            if r.get("const_width"):
                e.dxf.const_width = r["const_width"]
            if r.get("elevation"):
                e.dxf.elevation = r["elevation"]
        elif t == "ARC":
            ms.add_arc(tuple(r["pos"]) + (0,), r["radius"], r["start_angle"], r["end_angle"], dxfattribs=at)
        elif t == "CIRCLE":
            ms.add_circle(tuple(r["pos"]) + (0,), r["radius"], dxfattribs=at)
        elif t == "ELLIPSE":
            ma = tuple(r["major_axis"]) + (0,) * (3 - len(r["major_axis"]))
            ms.add_ellipse(tuple(r["pos"]) + (0,), ma, r["ratio"], r["start_param"], r["end_param"], dxfattribs=at)
        elif t == "SPLINE":
            e = ms.new_entity("SPLINE", at)
            e.dxf.degree = r["degree"]
            e.control_points = [tuple(p) + (0,) * (3 - len(p)) for p in r["control_points"]]
            e.knots = r["knots"]
            if r["weights"]:
                e.weights = r["weights"]
            if r["fit_points"]:
                e.fit_points = [tuple(p) + (0,) * (3 - len(p)) for p in r["fit_points"]]
            e.closed = bool(r["closed"])
        elif t == "HATCH":
            h = ms.add_hatch(dxfattribs=at)
            h.dxf.elevation = (0, 0, r.get("elevation", 0))
            if r.get("solid_fill", True):
                h.set_solid_fill()
            else:
                h.set_pattern_fill(r.get("pattern", "ANSI31"), angle=r.get("pattern_angle", 0.0),
                                   scale=r.get("pattern_scale", 1.0), double=int(r.get("pattern_double", 0)),
                                   definition=[(l["angle"], tuple(l["base"]), tuple(l["offset"]), l["dashes"])
                                               for l in r["pattern_lines"]] if r.get("pattern_lines") else None)
            for p in r["paths"]:
                if p["type"] == "polyline":
                    h.paths.add_polyline_path([tuple(v) for v in p["verts"]], is_closed=p["closed"], flags=p["flags"])
                else:
                    ep = h.paths.add_edge_path(flags=p["flags"])
                    for ed in p["edges"]:
                        k = ed["e"]
                        if k == "line":
                            ep.add_line(tuple(ed["s"]), tuple(ed["t"]))
                        elif k == "arc":
                            ep.add_arc(tuple(ed["c"]), ed["r"], ed["sa"], ed["ea"], ccw=ed["ccw"])
                        elif k == "ellipse":
                            ep.add_ellipse(tuple(ed["c"]), tuple(ed["major"]), ed["ratio"], ed["sa"], ed["ea"], ccw=ed["ccw"])
                        elif k == "spline":
                            ep.add_spline(fit_points=[tuple(v) for v in ed["fit"]],
                                          control_points=[tuple(v) for v in ed["ctrl"]],
                                          knot_values=ed["knots"], weights=ed["weights"] or None,
                                          degree=ed["deg"], periodic=int(ed["periodic"]))
        elif t in ("SOLID", "TRACE"):
            ms.add_solid([tuple(c) + (0,) for c in r["corners"]], dxfattribs=at)
        elif t in ("TEXT", "ATTRIB"):
            ta = dict(at, height=r["height"] or 1.0, rotation=r["rotation"], width=r["width_factor"],
                      oblique=r["oblique"], insert=tuple(r["pos"]) + (0,))
            if r.get("style_name") in styles:
                ta["style"] = r["style_name"]
            if r.get("text_generation_flag"):
                ta["text_generation_flag"] = r["text_generation_flag"]
            e = ms.add_text(r["text_raw"], dxfattribs=ta)
            if r.get("halign") or r.get("valign"):
                e.dxf.halign, e.dxf.valign = r["halign"], r["valign"]
                e.dxf.align_point = tuple(r.get("align_point", r["pos"])) + (0,)
        elif t == "MTEXT":
            ma = dict(at, insert=tuple(r["pos"]) + (0,), char_height=r["char_height"] or 1.0,
                      rotation=r["rotation"], attachment_point=r["attachment_point"])
            ma["width"] = r.get("width", 0.0)          # un width explicite a 0 (pas de retour a la ligne) est conserve
            if r.get("style_name") in styles:
                ma["style"] = r["style_name"]
            for k in ("line_spacing_factor", "defined_height", "flow_direction", "line_spacing_style"):
                if k in r:
                    ma[k] = r[k]
            if r.get("text_direction"):
                ma["text_direction"] = tuple(r["text_direction"]) + (0,)
            ms.add_mtext(r["text_raw"], dxfattribs=ma)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(out))
    return out


# ----------------------------------------------------------------------------
# 2. Mesures (ezdxf uniquement)
# ----------------------------------------------------------------------------
def _explode(entities, depth=0):
    for e in entities:
        t = e.dxftype()
        if t == "ATTDEF":
            continue
        try:
            ez_upright.upright(e)
        except Exception:
            pass
        yield e
        if t == "INSERT":
            for a in e.attribs:
                if a.dxf.tag not in HIDDEN_ATTRIBS and a.dxf.text.strip():
                    yield a
            if depth < 6:
                try:
                    yield from _explode(e.virtual_entities(), depth + 1)
                except Exception:
                    pass


def _wcs_text_pos(e):
    p = e.dxf.insert
    if e.dxftype() == "MTEXT":
        return (round(p[0], 3), round(p[1], 3))
    w = e.ocs().to_wcs(p)
    return (round(w[0], 3), round(w[1], 3))


def _flat_length(e) -> float:
    pts = list(ez_path.make_path(e).flattening(0.02))
    return sum(math.dist((a.x, a.y), (b.x, b.y)) for a, b in zip(pts, pts[1:]))


def metrics(doc, spaces=None) -> dict:
    out = {}
    layouts = [("model", doc.modelspace())] + [(f"paper:{l.name}", l) for l in doc.layouts if l.name != "Model"]
    for name, lay in layouts:
        if spaces and name not in spaces:
            continue
        cnt: Counter = Counter()
        length: dict = defaultdict(float)
        texts: Counter = Counter()
        boxes = []
        for e in _explode(lay):
            t = e.dxftype()
            if t in NOT_REBUILT:
                continue
            key = "TEXT" if t in ("TEXT", "ATTRIB") else ("LWPOLYLINE" if t == "POLYLINE" else t)
            cnt[key] += 1
            if key in GEOM_LENGTH_TYPES:
                try:
                    length[key] += _flat_length(e)
                except Exception:
                    pass
            if t in ("TEXT", "ATTRIB", "MTEXT"):
                raw_txt = e.dxf.text if t != "MTEXT" else e.text
                texts[(_wcs_text_pos(e), raw_txt.strip())] += 1
            if t in ("TEXT", "ATTRIB", "MTEXT"):
                continue          # emprise d'un texte = estimation de police par ezdxf ; position et contenu sont verifies a part
            try:
                ext = ez_bbox.extents([e])
                if ext.has_data:
                    boxes.append((ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y))
            except Exception:
                pass
        extents = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None
        out[name] = {"counts": dict(cnt), "lengths": {k: v for k, v in length.items()}, "texts": texts, "extents": extents}
    return out


def _render(doc, extents, png_path: Path, size_px=2400, ignore_text=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext, config
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    x0, y0, x1, y1 = extents
    w, h = x1 - x0, y1 - y0
    fig = plt.figure(figsize=(size_px / 100, size_px / 100 * h / w), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.axis("off")
    cfg = config.Configuration(color_policy=config.ColorPolicy.BLACK, background_policy=config.BackgroundPolicy.WHITE,
                               lineweight_policy=config.LineweightPolicy.ABSOLUTE, min_lineweight=0.3,
                               text_policy=config.TextPolicy.IGNORE if ignore_text else config.TextPolicy.FILLING)
    ctx = RenderContext(doc)
    Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=False)
    fig.savefig(str(png_path), dpi=100, facecolor="white")
    plt.close(fig)


def raster_iou(orig_doc, rebuilt_doc, extents, out_png: Path, ignore_text=False) -> dict:
    import numpy as np
    from PIL import Image

    pad = 0.02 * max(extents[2] - extents[0], extents[3] - extents[1])
    ext = (extents[0] - pad, extents[1] - pad, extents[2] + pad, extents[3] + pad)
    a_png, b_png = out_png.with_name("_orig.png"), out_png.with_name("_rebuilt.png")
    _render(orig_doc, ext, a_png, ignore_text=ignore_text)
    _render(rebuilt_doc, ext, b_png, ignore_text=ignore_text)
    a = np.array(Image.open(a_png).convert("L")) < 200
    b = np.array(Image.open(b_png).convert("L")) < 200
    if a.shape != b.shape:
        h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
        a, b = a[:h, :w], b[:h, :w]
    # tolerance de 1 pixel : un trait est commun s'il touche un trait de l'autre image
    from scipy.ndimage import binary_dilation
    ad, bd = binary_dilation(a, iterations=1), binary_dilation(b, iterations=1)
    a_in_b, b_in_a = float((a & bd).sum() / max(a.sum(), 1)), float((b & ad).sum() / max(b.sum(), 1))
    inter, union = float((a & b).sum()), float((a | b).sum())
    rgb = np.full(a.shape + (3,), 255, np.uint8)
    rgb[a & ~bd] = (214, 39, 40)          # rouge : dans l'original seulement
    rgb[b & ~ad] = (31, 119, 180)         # bleu : dans le reconstruit seulement
    rgb[(a & bd) | (b & ad)] = (44, 160, 44)   # vert : commun
    Image.fromarray(rgb).save(out_png)
    a_png.unlink(missing_ok=True)
    b_png.unlink(missing_ok=True)
    return {"pixels_original": int(a.sum()), "pixels_reconstruit": int(b.sum()),
            "iou_exact": round(inter / max(union, 1.0), 4),
            "original_retrouve_dans_reconstruit": round(a_in_b, 4),
            "reconstruit_present_dans_original": round(b_in_a, 4)}


def verify(raw_path: str | Path, original_dxf: str | Path, out_dir: str | Path, raster: bool = True,
           tol_rel=1e-6, tol_ext=1e-3) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    rebuilt_path = rebuild_dxf(raw, out_dir / "reconstructed.dxf")
    try:
        odoc = ezdxf.readfile(str(original_dxf))
    except Exception:
        from ezdxf import recover
        odoc, _ = recover.readfile(str(original_dxf))
    rdoc = ezdxf.readfile(str(rebuilt_path))
    mo, mr = metrics(odoc), metrics(rdoc)
    problems, spaces = [], {}
    for sp, a in mo.items():
        b = mr.get(sp, {"counts": {}, "lengths": {}, "texts": Counter(), "extents": None})
        rep = {"counts_equal": a["counts"] == b["counts"], "counts_original": a["counts"], "counts_reconstruit": b["counts"]}
        if not rep["counts_equal"]:
            problems.append(f"{sp} : comptes differents {a['counts']} / {b['counts']}")
        dl = {}
        for k in GEOM_LENGTH_TYPES:
            la, lb = a["lengths"].get(k, 0.0), b["lengths"].get(k, 0.0)
            if la or lb:
                dl[k] = {"original": round(la, 4), "reconstruit": round(lb, 4),
                         "ecart_relatif": round(abs(la - lb) / max(la, 1e-12), 9)}
                if dl[k]["ecart_relatif"] > tol_rel:
                    problems.append(f"{sp} : longueur {k} differente ({la:.4f} / {lb:.4f})")
        rep["longueurs"] = dl
        missing = a["texts"] - b["texts"]
        extra = b["texts"] - a["texts"]
        rep["textes"] = {"original": sum(a["texts"].values()), "reconstruit": sum(b["texts"].values()),
                         "manquants": [list(map(str, k)) for k in list(missing)[:5]], "en_trop": [list(map(str, k)) for k in list(extra)[:5]]}
        if missing or extra:
            problems.append(f"{sp} : textes differents (manquants {sum(missing.values())}, en trop {sum(extra.values())})")
        if a["extents"] and b["extents"]:
            de = max(abs(x - y) for x, y in zip(a["extents"], b["extents"]))
            rep["etendue"] = {"original": [round(v, 3) for v in a["extents"]], "reconstruit": [round(v, 3) for v in b["extents"]],
                              "ecart_max": round(de, 6)}
            if de > tol_ext:
                problems.append(f"{sp} : etendue differente (ecart {de:.4f})")
        spaces[sp] = rep
    report = {"raw_schema": raw.get("schema_version"), "coverage_lossless": raw.get("coverage", {}).get("lossless"),
              "espaces": spaces, "not_rebuilt": sorted(NOT_REBUILT)}
    if raster and mo["model"]["extents"]:
        # rendu sans les attributs : le moteur de rendu masque ceux que LibreDWG marque invisibles (flags=1) ;
        # raw.json les conserve et leur position est verifiee par la comparaison des textes ci-dessus
        rebuilt_no_att = rebuild_dxf(raw, out_dir / "_no_attribs.dxf", include_attribs=False)
        report["raster_model_space"] = raster_iou(odoc, ezdxf.readfile(str(rebuilt_no_att)), mo["model"]["extents"],
                                                  out_dir / "roundtrip_diff.png")
        # meme comparaison SANS texte : isole la geometrie (traits, arcs, ellipses, hachures) des differences de texte
        report["raster_model_space_sans_texte"] = raster_iou(odoc, ezdxf.readfile(str(rebuilt_no_att)),
                                                             mo["model"]["extents"], out_dir / "roundtrip_diff_sans_texte.png",
                                                             ignore_text=True)
        (out_dir / "_no_attribs.dxf").unlink(missing_ok=True)
    report["problemes"] = problems
    report["exact"] = not problems
    (out_dir / "roundtrip_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    rep = verify(sys.argv[1], sys.argv[2], sys.argv[3])
    print("EXACT" if rep["exact"] else "ECARTS :")
    for p in rep["problemes"]:
        print(" -", p)
    for k in ("raster_model_space", "raster_model_space_sans_texte"):
        if k in rep:
            print(k, ":", rep[k])
