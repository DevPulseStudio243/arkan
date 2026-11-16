"""
mto_consolidator.py
===================
Moteur de consolidation MTO multi-plans et exportateur Excel professionnel (openpyxl).
Permet d'agréger plusieurs plans isométriques (DWG/DXF/PDF), de fusionner les articles
identiques (tubes, raccords, brides, robinetterie, boulons, joints, supports),
de calculer les métriques globales et de générer un classeur Excel complet multi-onglets.
"""

from typing import List, Dict, Any, Optional, Tuple
import os
import re
import logging
import math
import unicodedata
from pathlib import Path
from collections import defaultdict
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger("mto_consolidator")


LENGTH_UNITS = {"M", "ML"}


def _parse_number(val: Any) -> Optional[float]:
    """
    Convertit un nombre « propre » en float, sinon None.
    Accepte : 12, "12,5", "1 234,5", "1,234.5", "35 m", "2.5kg".
    Refuse : "3x120" (ancien comportement : 3), "abc", "", None.
    """
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val) if math.isfinite(val) else None
    t = str(val).strip().replace("\u00a0", "").replace(" ", "")
    if not t:
        return None
    if re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+\.\d+", t):         # 1,234.5
        t = t.replace(",", "")
    elif re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3})+,\d+", t):        # 1.234,5
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")                                    # 12,5 -> 12.5
    m = re.fullmatch(r"([-+]?(?:\d+(?:\.\d+)?|\.\d+))[A-Za-zµ²³%/]*", t)
    return float(m.group(1)) if m else None


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convertit en float ; default si la valeur n'est pas un nombre propre."""
    n = _parse_number(val)
    return default if n is None else n


def _parse_confidence(val: Any) -> Optional[float]:
    """Score de confiance en [0, 1], ou None si absent/illisible (= NON ÉVALUÉ, jamais 100 %)."""
    n = _parse_number(val)
    if n is None:
        return None
    if n > 1.0 and n <= 100.0:      # tolère 85 pour 85 %
        n = n / 100.0
    return n if 0.0 <= n <= 1.0 else None


def sanitize_excel_val(val: Any) -> Any:
    """
    Retire les caractères de contrôle XML (qui font échouer openpyxl).
    La neutralisation des formules se fait à l'enregistrement (_neutralize_formulas) :
    plus d'apostrophe littérale affichée dans les cellules.
    """
    if not isinstance(val, str):
        return val
    return re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', val)


_OWN_FORMULA = re.compile(r"^=(?:SUM|SUMIF)\([A-Z0-9$:,]+\)$")


def _neutralize_formulas(wb) -> int:
    """
    Toute cellule « formule » qui n'est pas un de NOS totaux (=SUM / =SUMIF sur plages) est
    convertie en TEXTE (+ quotePrefix) : un texte de plan commençant par '=' ne s'exécute jamais.
    """
    n = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.data_type == "f" and isinstance(c.value, str) and not _OWN_FORMULA.match(c.value):
                    c.data_type = "s"
                    try:
                        c.quotePrefix = True
                    except Exception:
                        pass
                    n += 1
    if n:
        logger.warning("[EXCEL] %d cellule(s) texte commençant par '=' neutralisée(s)", n)
    return n

# Styles ARKAN Engineering pour Excel
FONT_TITLE = Font(name="Segoe UI", size=16, bold=True, color="1E3A8A")
FONT_SUBTITLE = Font(name="Segoe UI", size=10, italic=True, color="475569")
FONT_HEADER = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
FONT_REGULAR = Font(name="Segoe UI", size=9, color="0F172A")
FONT_BOLD = Font(name="Segoe UI", size=9, bold=True, color="0F172A")
FONT_TOTAL = Font(name="Segoe UI", size=10, bold=True, color="1E3A8A")

FILL_HEADER = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")       # Bleu Marine EPC
FILL_CAT_HEADER = PatternFill(start_color="3B82F6", end_color="3B82F6", fill_type="solid")   # Bleu Royal
FILL_ZEBRA = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")        # Gris très clair
FILL_TOTAL = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")        # Gris moyen
FILL_HIGHLIGHT = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")    # Jaune ambre discret

# Styles pour le Tableau Récapitulatif Exécutif
FONT_CARD_TITLE = Font(name="Segoe UI", size=8, bold=True, color="475569")
FONT_CARD_VALUE = Font(name="Segoe UI", size=15, bold=True, color="1E3A8A")
FONT_CARD_SUBTITLE = Font(name="Segoe UI", size=8, italic=True, color="64748B")

FONT_SECTION = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
FILL_SECTION = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
FILL_SUBSECTION = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
FILL_CARD = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

BORDER_THIN = Border(
    left=Side(style="thin", color="CBD5E1"),
    right=Side(style="thin", color="CBD5E1"),
    top=Side(style="thin", color="CBD5E1"),
    bottom=Side(style="thin", color="CBD5E1")
)
BORDER_TOTAL = Border(
    left=Side(style="thin", color="94A3B8"),
    right=Side(style="thin", color="94A3B8"),
    top=Side(style="thin", color="94A3B8"),
    bottom=Side(style="double", color="1E3A8A")
)

ALIGN_LEFT = Alignment(horizontal="left", vertical="center")
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")


# Si True : tout article en mètres sans catégorie reconnue est classé PIPE (ancien comportement).
# Par défaut False : il part en « OTHERS » -> A_VALIDER (un câble d'instrumentation ne devient plus un tube).
LEGACY_UNIT_M_IS_PIPE = False


def _norm_text(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").upper()
    return re.sub(r"\s+", " ", s).strip()


_KW_CACHE: Dict[str, "re.Pattern[str]"] = {}


def _kw_pattern(keyword: str) -> "re.Pattern[str]":
    pat = _KW_CACHE.get(keyword)
    if pat is None:
        words = _norm_text(keyword).split(" ")
        parts = []
        for w in words:
            plural = r"(?:S|ES|X)?" if w[-1:].isalnum() else ""
            parts.append(re.escape(w) + plural)
        core = r"\s+".join(parts)
        tail = r"(?![A-Z0-9])" if _norm_text(keyword)[-1:].isalnum() else ""
        pat = re.compile(r"(?<![A-Z0-9])" + core + tail)
        _KW_CACHE[keyword] = pat
    return pat


def _kw(text: str, keywords: List[str]) -> bool:
    """Mots ENTIERS (pluriel toléré) : 'TEE' ne matche plus 'STEEL', 'SWA' ne matche plus 'SWAGE'."""
    return any(_kw_pattern(k).search(text) for k in keywords)


def classify_item_discipline(item: Dict[str, Any]) -> str:
    """
    Discipline EPC d'un article : DISTRIBUTION_MT_BT, CARNET_DE_CABLES, CHEMINS_ET_CANALISATIONS,
    RESEAU_TERRE_FOUDRE, ECLAIRAGE_ET_PRISES, INSTRUMENTS, ACCESSOIRES_ELEC, GASKET, VALVE, PIPE,
    FLANGE, FITTING, BOLT, SUPPORTS, OTHERS.   La catégorie extracteur prime ; les mots-clés (mots
    entiers, accents ignorés) ne servent que de repli.
    """
    cat = _norm_text(item.get("category"))
    desc = _norm_text(item.get("description") or item.get("designation"))
    unit = _norm_text(item.get("unit"))

    if cat in ("EARTHING", "MALT", "TERRE", "EARTH_ROD") or _kw(desc, [
            "CUIVRE NU", "PIQUET DE TERRE", "REGARD DE TERRE", "BORNE DE COUPURE", "PARATONNERRE", "EQUIPOTENTIEL"]):
        return "RESEAU_TERRE_FOUDRE"

    if cat in ("ACCESSORY_ELEC", "CABLE_GLAND", "LUG") or _kw(desc, [
            "PRESSE-ETOUPE", "PRESSE ETOUPE", "CABLE GLAND", "GLAND", "COSSE", "CABLE LUG", "EMBOUT", "COLLIER",
            "SERRE-CABLE"]):
        return "ACCESSOIRES_ELEC"

    if cat in ("CONDUIT", "PULL_BOX", "FOURREAU", "BUSE") or _kw(desc, [
            "CHAMBRE DE TIRAGE", "BUSE PVC", "FOURREAU PEHD", "TAMPON FONTE"]):
        return "CHEMINS_ET_CANALISATIONS"

    if cat in ("CABLE_TRAY", "CHEMIN_CABLE", "CDC") or _kw(desc, [
            "CHEMIN DE CABLE", "ECHELLE A CABLE", "CDC-"]):
        return "CHEMINS_ET_CANALISATIONS"

    if cat in ("CABLE", "CABLES_LIST", "CABLE_POWER", "CABLE_CONTROL", "CABLE_INSTRUMENT") or _kw(desc, [
            "CABLE", "U-1000", "CU/XLPE", "RV-K", "H07RN", "SWA"]):
        return "CARNET_DE_CABLES"

    if cat in ("SWITCHGEAR_FEEDER", "PANEL", "TGBT", "MCC", "UPS", "CELLULE_MT", "BUSBAR_TRUNKING", "TRANSFORMER") or _kw(desc, [
            "TGBT", "MCC", "UPS", "DISJONCTEUR", "CELLULE 30KV", "CELLULE 5.5KV", "TRANSFO", "TRANSFORMATEUR",
            "TRANSFORMER", "DEPART BASSE TENSION", "CANALISATION"]):
        return "DISTRIBUTION_MT_BT"

    if cat in ("LIGHTING", "ECLAIRAGE", "ECL", "PRISES") or _kw(desc, [
            "PROJECTEUR", "LUMINAIRE", "BAES", "PRISE 16A", "PRISE 32A", "CANDELABRE", "COFFRET PRISES"]):
        return "ECLAIRAGE_ET_PRISES"

    if cat in ("INSTRUMENT", "INSTRUMENTS", "INSTRUMENTATION", "TRANSMITTER", "INDICATOR", "SWITCH",
               "PRIMARY_ELEMENT", "JUNCTION_BOX") or _kw(desc, [
            "TRANSMITTER", "TRANSMETTEUR", "GAUGE", "MANOMETRE", "FLOWMETER", "DEBITMETRE", "INSTRUMENT",
            "THERMOWELL", "DOIGT DE GANT", "PRESSOSTAT", "SONDE", "CAPTEUR", "ORIFICE FLANGE", "ORIFICE PLATE",
            "ROBINET MANOMETRE", "LEVEL GAUGE", "PSV", "BOITE DE JONCTION"]):
        return "INSTRUMENTS"

    if cat in ("GASKET", "JOINT", "JOINTS") or _kw(desc, [
            "GASKET", "JOINT", "SPIRAL WOUND", "RING JOINT", "RTJ", "GARNITURE"]):
        return "GASKET"

    if cat in ("VALVE", "VANNE", "ROBINETTERIE", "CONTROL_VALVE", "SAFETY_VALVE") or _kw(desc, [
            "VALVE", "VANNE", "ROBINET", "CLAPET", "SOUPAPE", "BUTTERFLY", "TSV"]):
        return "VALVE"

    if cat in ("PIPE", "PIPES", "TUYAU", "TUBE") or _kw(desc, ["PIPE", "TUYAU", "TUBE", "SMLS PIPE", "WELDED PIPE"]) \
            or (LEGACY_UNIT_M_IS_PIPE and unit == "M"):
        return "PIPE"

    if cat in ("FLANGE", "FLANGES", "BRIDE", "BRIDES") or _kw(desc, [
            "FLANGE", "BRIDE", "BLIND FLANGE", "SPECTACLE BLIND", "WN FLANGE", "SO FLANGE"]):
        return "FLANGE"

    if cat in ("FITTING", "FITTINGS", "RACCORD", "RACCORDS") or _kw(desc, [
            "ELBOW", "COUDE", "TEE", "REDUCER", "REDUCTION", "CAP", "COUPLING", "NIPPLE", "UNION", "WELDOLET",
            "SOCKOLET", "THREADOLET", "MANCHON"]):
        return "FITTING"

    if cat in ("BOLT", "BOLTS", "BOULON", "BOULONNERIE", "FASTENERS") or _kw(desc, [
            "STUD BOLT", "BOLT", "BOULON", "GOUJON", "TIGE FILETEE", "HEX NUT"]):
        return "BOLT"

    if cat in ("SUPPORT", "SUPPORTS") or _kw(desc, [
            "SUPPORT", "SHOE", "GUIDE", "SPRING", "TRUNNION", "POST TYPE", "BASE CONCRETE", "BRACKET"]):
        return "SUPPORTS"

    return "OTHERS"


def expand_feeders(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sépare chaque « départ TGBT » (appareil + câble confondus dans l'extracteur SLD) en :
      - une ligne APPAREIL  (EA, qté 1, calibre / pôles)             -> DISTRIBUTION_MT_BT
      - une ligne CÂBLE     (m, section, longueur)                   -> CARNET_DE_CABLES
        (ou BUSBAR_TRUNKING pour « CANALISATION » : gaine à barres, pas un câble)
    La longueur n'est jamais présumée fiable : sans `length_source` valant MEASURED / CARNET /
    CALCULATED, la ligne câble est marquée « à valider ». Idempotent (`split_from_feeder`).
    """
    out: List[Dict[str, Any]] = []
    for it in items or []:
        is_feeder = str(it.get("category") or "").upper() == "SWITCHGEAR_FEEDER"
        if not is_feeder or it.get("split_from_feeder") or not (it.get("cable_section") or it.get("calibre_a")):
            out.append(it)
            continue
        tag = str(it.get("tag") or "-")
        cal, poles, icu = it.get("calibre_a"), it.get("poles"), it.get("icu_ka")
        common = {k: it.get(k) for k in ("source_page", "source_drawing", "revision", "confidence_score") if k in it}
        common["split_from_feeder"] = True

        dev_desc = f"Départ protégé {tag}"
        if it.get("designation") and str(it.get("designation")).strip().upper() != "DÉPART TGBT":
            dev_desc += f" — {it.get('designation')}"
        if cal:
            dev_desc += f" — {cal} A"
        if poles:
            dev_desc += f" {poles}"
        if icu:
            dev_desc += f" — Icu {icu} kA"
        out.append({**common, "category": "SWITCHGEAR_FEEDER", "tag": tag, "description": dev_desc,
                    "size": f"{cal} A" if cal else "", "schedule": str(poles or ""), "unit": "EA", "quantity": 1.0,
                    "weight_unit": 0.0, "weight_total": 0.0,
                    "extractor_reasons": list(it.get("extractor_reasons") or [])})

        sec = str(it.get("cable_section") or "").strip()
        if sec:
            reasons = list(it.get("extractor_reasons") or [])
            if str(it.get("length_source") or "").upper() not in ("MEASURED", "CARNET", "CALCULATED", "SLD_TABLE", "ROUTED"):
                reasons.append("longueur de câble non mesurée (valeur par défaut de l'extracteur)")
            busbar = sec.upper() == "CANALISATION"
            ctype = it.get("cable_type") or "Cu/XLPE/PVC"
            out.append({**common, "category": "BUSBAR_TRUNKING" if busbar else "CABLE",
                        "tag": tag if busbar else f"C-{tag}-PWR",
                        "description": (f"Canalisation préfabriquée (gaine à barres) — liaison {tag}" if busbar
                                        else f"Câble {ctype} {sec} — liaison {tag}"),
                        "size": sec, "cable_type": ctype, "unit": it.get("unit") or "m",
                        "quantity": it.get("quantity"), "weight_unit": it.get("weight_unit"),
                        "weight_total": it.get("weight_total"), "length_source": it.get("length_source") or "UNKNOWN",
                        "extractor_reasons": reasons})
    return out


# --- Surfaces tuyauterie : π × OD × L (remplace les ratios inventés 0,35 et 0,25 m²/m) -----------
_NPS_OD_MM = {0.5: 21.3, 0.75: 26.7, 1.0: 33.4, 1.25: 42.2, 1.5: 48.3, 2.0: 60.3, 2.5: 73.0, 3.0: 88.9,
              3.5: 101.6, 4.0: 114.3, 5.0: 141.3, 6.0: 168.3, 8.0: 219.1, 10.0: 273.1, 12.0: 323.9}
_DN_TO_NPS = {15: 0.5, 20: 0.75, 25: 1.0, 32: 1.25, 40: 1.5, 50: 2.0, 65: 2.5, 80: 3.0, 90: 3.5, 100: 4.0,
              125: 5.0, 150: 6.0, 200: 8.0, 250: 10.0, 300: 12.0, 350: 14.0, 400: 16.0, 450: 18.0, 500: 20.0,
              550: 22.0, 600: 24.0, 650: 26.0, 700: 28.0, 750: 30.0, 800: 32.0, 850: 34.0, 900: 36.0,
              1000: 40.0, 1050: 42.0, 1200: 48.0}


def _pipe_od_m(size: Any) -> Optional[float]:
    s = str(size or "").upper().replace('"', " ").replace("''", " ")
    nps: Optional[float] = None
    m = re.search(r"DN\s*(\d+)", s)
    if m:
        nps = _DN_TO_NPS.get(int(m.group(1)))
    else:
        s = re.sub(r"\b(NPS|INCHES|INCH|IN)\b", " ", s)
        m1 = re.search(r"(\d+)[-\s]+(\d+)/(\d+)", s)
        m2 = re.search(r"(\d+)/(\d+)", s)
        m3 = re.search(r"\d+(?:[.,]\d+)?", s)
        if m1:
            nps = int(m1.group(1)) + int(m1.group(2)) / int(m1.group(3))
        elif m2:
            nps = int(m2.group(1)) / int(m2.group(2))
        elif m3:
            nps = float(m3.group(0).replace(",", "."))
    if nps is None or nps <= 0:
        return None
    od_mm = _NPS_OD_MM.get(nps) if nps <= 12 else nps * 25.4
    return od_mm / 1000.0 if od_mm else None


def pipe_surface_stats(consolidated_items: List[Dict[str, Any]], effective_pipe_m: float) -> Dict[str, float]:
    """Surface extérieure des tubes (m²) = Σ π·OD·L ; les longueurs sans diamètre lisible sont rapportées à part."""
    area, resolved_m = 0.0, 0.0
    for it in consolidated_items:
        if str(it.get("category") or "").upper() != "PIPE" or str(it.get("unit") or "").upper() not in LENGTH_UNITS:
            continue
        od = _pipe_od_m(it.get("size"))
        qty = _safe_float(it.get("quantity"))
        if od:
            area += math.pi * od * qty
            resolved_m += qty
    return {"area_m2": round(area, 2), "unresolved_m": round(max(0.0, effective_pipe_m - resolved_m), 2)}


def normalize_item_key(item: Dict[str, Any]) -> Tuple[str, str, str, str, str, str, str]:
    """
    Génère une clé de regroupement normalisée pour fusionner les composants identiques.
    """
    cat = classify_item_discipline(item)
    size = (item.get("size") or "").strip().replace('"', '').upper()
    sch = (item.get("schedule") or "").strip().upper()
    rating = (item.get("rating") or "").strip().upper()
    mat = (item.get("material") or "").strip().upper()
    unit = (item.get("unit") or "EA").strip().upper()
    
    # Normalisation de la description (suppression des espaces multiples)
    desc = (item.get("description") or "").strip()
    desc_clean = re.sub(r'\s+', ' ', desc).upper()
    # E&I : deux départs, câbles ou chambres de même désignation mais de tags différents ne fusionnent JAMAIS
    if cat not in PIPING_DISCS and item.get("tag"):
        desc_clean = f"{str(item['tag']).strip().upper()} | {desc_clean}"

    return (cat, desc_clean, size, sch, rating, mat, unit)


def _quantity_by_unit(items: List[Dict[str, Any]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for it in items:
        u = str(it.get("unit") or "EA").upper().strip()
        out[u] = round(out.get(u, 0.0) + _safe_float(it.get("quantity")), 2)
    return out


def consolidate_mto_items(plans_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Agrège et consolide les données de plusieurs isométriques.
    Retourne :
      - consolidated_items: liste d'articles fusionnés avec quantités cumulées
      - plans_summary: liste récapitulative des plans traités
      - global_stats: totaux métriques (longueur tubes, poids total, nb articles, etc.)
    """
    aggregated: Dict[Tuple, Dict[str, Any]] = {}
    plans_summary: List[Dict[str, Any]] = []
    
    total_pipe_m = 0.0
    total_steel_kg = 0.0
    all_spools_count = 0
    total_shop_welds = 0
    total_field_welds = 0

    for plan in plans_results:
        filename = plan.get("filename", "Inconnu")
        meta = plan.get("metadata", {})
        line_num = meta.get("line_number") or filename
        spec = meta.get("spec_class") or ""
        items = plan.get("mto", [])
        spools = plan.get("spools", [])
        welds = plan.get("welds_summary", [])
        
        # Statistiques du plan
        p_len = plan.get("total_pipe_length_m", 0.0)
        p_wt = plan.get("total_steel_weight_kg", 0.0)
        total_pipe_m += p_len
        total_steel_kg += p_wt
        all_spools_count += len(spools)
        
        # Comptage soudures
        if isinstance(welds, list):
            s_w = len([w for w in welds if (w.get("shop_field") or "").upper() == "SHOP"])
            f_w = len([w for w in welds if (w.get("shop_field") or "").upper() == "FIELD"])
            total_shop_welds += s_w
            total_field_welds += f_w
        elif isinstance(welds, dict):
            total_shop_welds += welds.get("shop_welds", 0)
            total_field_welds += welds.get("field_welds", 0)

        plans_summary.append({
            "filename": filename,
            "line_number": line_num,
            "spec": spec,
            "items_count": len(items),
            "pipe_length_m": p_len,
            "weight_kg": p_wt,
            "spools_count": len(spools),
            "pressure": meta.get("design_pressure_bar") or ""
        })

        # Fusion des articles
        for it in items:
            key = normalize_item_key(it)
            qty = _safe_float(it.get("quantity"), 0.0)
            u_wt = _safe_float(it.get("weight_unit"), 0.0)
            it_tot_wt = _safe_float(it.get("weight_total"), 0.0)
            if it_tot_wt == 0.0 and u_wt > 0 and qty > 0:
                it_tot_wt = u_wt * qty
            
            if key not in aggregated:
                aggregated[key] = {
                    "category": classify_item_discipline(it),
                    "description": it.get("description", ""),
                    "size": it.get("size", ""),
                    "schedule": it.get("schedule", ""),
                    "rating": it.get("rating", ""),
                    "material": it.get("material", ""),
                    "unit": it.get("unit", "EA"),
                    "quantity": 0.0,
                    "weight_unit": u_wt,
                    "weight_total": 0.0,
                    "total_weight_accum": 0.0,
                    "lines_affected": set(),
                    "files_affected": set()
                }

            aggregated[key]["quantity"] += qty
            aggregated[key]["total_weight_accum"] += it_tot_wt
            aggregated[key]["lines_affected"].add(line_num)
            aggregated[key]["files_affected"].add(filename)
            if u_wt > 0 and aggregated[key]["weight_unit"] == 0.0:
                aggregated[key]["weight_unit"] = u_wt

    # Finaliser calculs et tri
    consolidated_list = []
    category_order = {"PIPE": 1, "FITTING": 2, "FLANGE": 3, "VALVE": 4, "BOLT": 5, "GASKET": 6, "SUPPORTS": 7, "INSTRUMENTS": 8}

    for key, data in aggregated.items():
        qty = round(data["quantity"], 2)
        tot_wt = round(data.get("total_weight_accum", 0.0), 2)
        if tot_wt == 0.0 and data["weight_unit"] > 0:
            tot_wt = round(qty * data["weight_unit"], 2)
        u_wt = round(tot_wt / qty, 2) if qty > 0 and tot_wt > 0 else data["weight_unit"]
        data["quantity"] = qty
        data["weight_unit"] = u_wt
        data["weight_total"] = tot_wt
        data["lines_str"] = ", ".join(sorted(data["lines_affected"]))
        data["files_str"] = ", ".join(sorted(data["files_affected"]))
        data["lines_count"] = len(data["lines_affected"])
        data["lines_affected"] = sorted(list(data["lines_affected"]))
        data["files_affected"] = sorted(list(data["files_affected"]))
        data["tag"] = f"{data['category'][:3]}-{len(consolidated_list)+1:02d}"
        data["remarks"] = f"Lignes: {data['lines_str']}"
        consolidated_list.append(data)

    # Tri ordonné par Catégorie puis par Description
    consolidated_list.sort(key=lambda x: (category_order.get(x["category"].upper(), 99), x["description"]))

    # Catégories summary
    cats_summary = defaultdict(int)
    for it in consolidated_list:
        cats_summary[it["category"]] += 1

    tot_valves = sum(it["quantity"] for it in consolidated_list if it["category"] == "VALVE")
    tot_gaskets = sum(it["quantity"] for it in consolidated_list if it["category"] == "GASKET")
    tot_instr = sum(it["quantity"] for it in consolidated_list if it["category"] == "INSTRUMENTS")
    tot_flanges = sum(it["quantity"] for it in consolidated_list if it["category"] == "FLANGE")
    tot_fittings = sum(it["quantity"] for it in consolidated_list if it["category"] == "FITTING")
    tot_bolts = sum(it["quantity"] for it in consolidated_list if it["category"] == "BOLT")
    tot_supports = sum(it["quantity"] for it in consolidated_list if it["category"] == "SUPPORTS")
    pipe_items_m = sum(it["quantity"] for it in consolidated_list if it["category"] == "PIPE" and str(it.get("unit") or "").upper() in LENGTH_UNITS)
    effective_pipe_m = max(round(total_pipe_m, 2), round(pipe_items_m, 2))

    surf = pipe_surface_stats(consolidated_list, effective_pipe_m)
    return {
        "consolidated_items": consolidated_list,
        "plans_summary": plans_summary,
        "global_stats": {
            "total_plans": len(plans_summary),
            # pièces dénombrables uniquement (plus de mètres additionnés aux unités) ; mètres et autres unités à part
            "total_items": int(sum(_safe_float(it.get("quantity")) for it in consolidated_list
                                   if str(it.get("unit") or "EA").upper() in ("EA", "U", "PCS", "NR", "PC", "UN"))),
            "total_lines": len(consolidated_list),
            "quantity_by_unit": _quantity_by_unit(consolidated_list),
            "total_unique_components": len(consolidated_list),
            "unique_items_count": len(consolidated_list),
            "total_pipe_length_m": effective_pipe_m,
            "total_valves_qty": int(tot_valves),
            "total_gaskets_qty": int(tot_gaskets),
            "total_instruments_qty": int(tot_instr),
            "total_flanges_qty": int(tot_flanges),
            "total_fittings_qty": int(tot_fittings),
            "total_bolts_qty": int(tot_bolts),
            "total_supports_qty": int(tot_supports),
            "total_steel_weight_kg": round(total_steel_kg, 2),
            "total_steel_weight_tonnes": round(total_steel_kg / 1000.0, 3),
            "total_spools": all_spools_count,
            "total_shop_welds": total_shop_welds,
            "total_field_welds": total_field_welds,
            "total_paint_m2": surf["area_m2"],                 # Σ π·OD·L (surface extérieure des tubes)
            "total_insulation_m2": surf["area_m2"],            # surface à isoler, hors épaisseur d'isolant
            "paint_unresolved_pipe_m": surf["unresolved_m"],   # longueurs sans diamètre lisible
            "categories_summary": dict(cats_summary)
        }
    }


def generate_consolidated_excel(
    consolidation_data: Dict[str, Any],
    all_plans_raw: List[Dict[str, Any]],
    output_path: str
) -> str:
    """
    Génère un classeur Excel professionnel (.xlsx) haute fidélité avec openpyxl.
    Comprend 5 onglets :
      0. TABLEAU_RECAPITULATIF : Synthèse exécutive, KPI (longueur, vannes, joints, instruments) & ventilations
      1. MTO_GLOBAL_SYNTHESE : BoQ générale avec regroupement et sous-totaux
      2. MTO_PAR_LIGNE : Décomposition détaillée plan par plan
      3. RECAP_PLANS : Tableau de bord de tous les isométriques traités
      4. STATS_METALLURGIE : Tonnage par nuance et métriques de construction
    """
    wb = openpyxl.Workbook()
    # Supprimer la feuille par défaut
    wb.remove(wb.active)

    items = consolidation_data["consolidated_items"]
    plans = consolidation_data["plans_summary"]
    stats = consolidation_data["global_stats"]

    # =========================================================================
    # ONGLET 0 : TABLEAU_RECAPITULATIF (Tableau de Bord Exécutif & Synthèse Clé)
    # =========================================================================
    ws0 = wb.create_sheet(title="TABLEAU_RECAPITULATIF", index=0)
    ws0.views.sheetView[0].showGridLines = True

    # 1. En-tête de page & Titre institutionnel
    ws0["B2"] = "ARKAN EPC INTELLIGENCE — TABLEAU RÉCAPITULATIF EXÉCUTIF DU MTO"
    ws0["B2"].font = FONT_TITLE
    ws0["B3"] = (
        f"Synthèse consolidée • {stats['total_plans']} plans isométriques analysés • "
        f"{stats['unique_items_count']} composants uniques • "
        f"Tonnage total : {stats['total_steel_weight_tonnes']} T ({stats['total_steel_weight_kg']:,.1f} kg) • "
        "Codes ASME B31.3 / ASME B16.5 / ASME B16.34"
    )
    ws0["B3"].font = FONT_SUBTITLE

    # Préparation des données par discipline
    disciplines_data = {
        "PIPE": {"label": "Tuyauterie Droite (Piping)", "norm": "ASME B31.3 / B36.10M / ASTM A106", "unit": "M", "items": [], "qty": 0.0, "weight": 0.0, "sizes": set()},
        "VALVE": {"label": "Robinetterie & Vannes (Valves)", "norm": "ASME B16.34 / API 600 / API 6D", "unit": "U", "items": [], "qty": 0.0, "weight": 0.0, "sizes": set()},
        "GASKET": {"label": "Joints d'Étanchéité (Gaskets)", "norm": "ASME B16.20 / ASME B16.21", "unit": "U", "items": [], "qty": 0.0, "weight": 0.0, "sizes": set()},
        "INSTRUMENTS": {"label": "Instrumentation & Accessoires", "norm": "ISA-5.1 / ASME B40.100 / API RP 551", "unit": "U", "items": [], "qty": 0.0, "weight": 0.0, "sizes": set()},
        "FITTING": {"label": "Raccords de Tuyauterie (Fittings)", "norm": "ASME B16.9 / ASME B16.11 / MSS-SP-97", "unit": "U", "items": [], "qty": 0.0, "weight": 0.0, "sizes": set()},
        "FLANGE": {"label": "Brides de Raccordement (Flanges)", "norm": "ASME B16.5 / ASME B16.47", "unit": "U", "items": [], "qty": 0.0, "weight": 0.0, "sizes": set()},
        "BOLT": {"label": "Boulonnerie & Goujons (Fasteners)", "norm": "ASME B18.2.1 / ASTM A193-B7", "unit": "SET", "items": [], "qty": 0.0, "weight": 0.0, "sizes": set()},
        "SUPPORTS": {"label": "Supports de Tuyauterie (Supports)", "norm": "MSS-SP-58 / Standard EPC Support", "unit": "U", "items": [], "qty": 0.0, "weight": 0.0, "sizes": set()},
    }

    for it in items:
        disc = classify_item_discipline(it)
        if disc not in disciplines_data:
            disciplines_data[disc] = {"label": f"Autres Matériels ({disc})", "norm": "Standard Projet", "unit": it.get("unit", "EA"), "items": [], "qty": 0.0, "weight": 0.0, "sizes": set()}
        
        qty = float(it.get("quantity", 0.0))
        wt = float(it.get("weight_total", 0.0))
        sz = (it.get("size") or "").strip()
        
        disciplines_data[disc]["items"].append(it)
        disciplines_data[disc]["qty"] += qty
        disciplines_data[disc]["weight"] += wt
        if sz:
            disciplines_data[disc]["sizes"].add(sz)

    pipe_disc_qty = disciplines_data["PIPE"]["qty"]
    if stats.get("total_pipe_length_m", 0) > pipe_disc_qty:
        disciplines_data["PIPE"]["qty"] = stats["total_pipe_length_m"]

    tot_pipe_m = disciplines_data["PIPE"]["qty"]
    tot_valves = disciplines_data["VALVE"]["qty"]
    tot_gaskets = disciplines_data["GASKET"]["qty"]
    tot_instr = disciplines_data["INSTRUMENTS"]["qty"]
    tot_flanges = disciplines_data["FLANGE"]["qty"]
    tot_fittings = disciplines_data["FITTING"]["qty"]
    tot_bolts = disciplines_data["BOLT"]["qty"]
    tot_steel_kg = max(stats.get("total_steel_weight_kg", 0.0), sum(d["weight"] for d in disciplines_data.values()))
    tot_steel_t = round(tot_steel_kg / 1000.0, 3)

    # 2. Cartouches d'Indicateurs Clés (KPI Scorecards)
    def _draw_kpi_card(ws, start_col, start_row, width, title, value_str, subtitle):
        for r in range(start_row, start_row + 3):
            for c in range(start_col, start_col + width):
                cell = ws.cell(row=r, column=c)
                cell.fill = FILL_CARD
                cell.border = BORDER_THIN
        for r in range(start_row, start_row + 3):
            ws.cell(row=r, column=start_col).border = Border(
                left=Side(style="medium", color="1E3A8A"),
                top=BORDER_THIN.top, bottom=BORDER_THIN.bottom, right=BORDER_THIN.right
            )
        ws.merge_cells(start_row=start_row, start_column=start_col, end_row=start_row, end_column=start_col + width - 1)
        ws.merge_cells(start_row=start_row + 1, start_column=start_col, end_row=start_row + 1, end_column=start_col + width - 1)
        ws.merge_cells(start_row=start_row + 2, start_column=start_col, end_row=start_row + 2, end_column=start_col + width - 1)

        c_top = ws.cell(row=start_row, column=start_col, value=title)
        c_top.font = FONT_CARD_TITLE
        c_top.alignment = ALIGN_CENTER

        c_mid = ws.cell(row=start_row + 1, column=start_col, value=value_str)
        c_mid.font = FONT_CARD_VALUE
        c_mid.alignment = ALIGN_CENTER

        c_bot = ws.cell(row=start_row + 2, column=start_col, value=subtitle)
        c_bot.font = FONT_CARD_SUBTITLE
        c_bot.alignment = ALIGN_CENTER

    # Ligne 1 de KPI Cards (Rangées 5 à 7)
    _draw_kpi_card(ws0, 2, 5, 2, "LONGUEUR DE TUYAUTERIE", f"{tot_pipe_m:,.2f} m", "Total métrage linéaire")
    _draw_kpi_card(ws0, 4, 5, 2, "NOMBRE TOTAL DE VANNES", f"{int(tot_valves)} U", "Robinetterie industrielle")
    _draw_kpi_card(ws0, 6, 5, 2, "NOMBRE TOTAL DE JOINTS", f"{int(tot_gaskets)} U", "Joints d'étanchéité & RTJ")
    _draw_kpi_card(ws0, 8, 5, 2, "NOMBRE D'INSTRUMENTS", f"{int(tot_instr)} U", "Capteurs, piquages & accessoires")

    # Ligne 2 de KPI Cards (Rangées 9 à 11)
    _draw_kpi_card(ws0, 2, 9, 2, "BRIDES DE RACCORDEMENT", f"{int(tot_flanges)} U", "Brides WN, blind & pleines")
    _draw_kpi_card(ws0, 4, 9, 2, "RACCORDS FORGÉS & BW", f"{int(tot_fittings)} U", "Coudes, tés, réductions")
    _draw_kpi_card(ws0, 6, 9, 2, "BOULONNERIE & GOUJONS", f"{int(tot_bolts)} SET", "Stud bolts ASTM A193 B7")
    _draw_kpi_card(ws0, 8, 9, 2, "TONNAGE TOTAL D'ACIER", f"{tot_steel_t:,.3f} T", f"{tot_steel_kg:,.1f} kg d'acier ASME")

    # 3. Tableau Récapitulatif Synthétique par Discipline
    curr_r = 13
    ws0.merge_cells(start_row=curr_r, start_column=2, end_row=curr_r, end_column=10)
    c_sec = ws0.cell(row=curr_r, column=2, value="1. TABLEAU RÉCAPITULATIF GLOBAL PAR DISCIPLINE & FAMILLE D'ÉQUIPEMENT")
    c_sec.font = FONT_SECTION
    c_sec.fill = FILL_SECTION
    c_sec.alignment = ALIGN_LEFT
    ws0.row_dimensions[curr_r].height = 24

    curr_r += 1
    headers_recap = [
        "N°", "Discipline / Famille d'Équipement", "Norme EPC de Référence", 
        "Quantité Cumulée", "Unité", "Poids Total (kg)", "Part Tonnage (%)",
        "Gamme Diamètres (NPS)", "Nb Références"
    ]
    for idx, h in enumerate(headers_recap, 2):
        cell = ws0.cell(row=curr_r, column=idx, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER if idx not in (3, 4) else ALIGN_LEFT
        cell.border = BORDER_THIN
    ws0.row_dimensions[curr_r].height = 22

    order_keys = ["PIPE", "VALVE", "GASKET", "INSTRUMENTS", "FITTING", "FLANGE", "BOLT", "SUPPORTS"]
    row_num = 1
    for k in order_keys:
        if k not in disciplines_data:
            continue
        d = disciplines_data[k]
        curr_r += 1
        ws0.row_dimensions[curr_r].height = 20
        
        q_val = round(d["qty"], 2)
        w_val = round(d["weight"], 2)
        pct_val = round((w_val / tot_steel_kg * 100.0) if tot_steel_kg > 0 else 0.0, 1)
        sizes_str = ", ".join(sorted(d["sizes"], key=lambda s: str(s))) if d["sizes"] else "Standard"

        row_data = [
            row_num, d["label"], d["norm"], q_val, d["unit"], w_val, pct_val / 100.0, sizes_str, len(d["items"])
        ]
        for idx, v in enumerate(row_data, 2):
            cell = ws0.cell(row=curr_r, column=idx, value=v)
            cell.font = FONT_REGULAR
            cell.border = BORDER_THIN
            if idx in (2, 6):
                cell.alignment = ALIGN_CENTER
            elif idx in (5, 7):
                cell.alignment = ALIGN_RIGHT
                cell.number_format = "#,##0.00"
            elif idx == 8:
                cell.alignment = ALIGN_RIGHT
                cell.number_format = "0.0%"
            elif idx == 10:
                cell.alignment = ALIGN_CENTER
            else:
                cell.alignment = ALIGN_LEFT
        row_num += 1

    # Ligne Total
    curr_r += 1
    ws0.row_dimensions[curr_r].height = 22
    ws0.cell(row=curr_r, column=2, value="TOTAL").alignment = ALIGN_CENTER
    ws0.cell(row=curr_r, column=3, value="TOTAL GÉNÉRAL DU MATÉRIEL MTO CONSOLIDÉ").alignment = ALIGN_LEFT
    ws0.cell(row=curr_r, column=4, value="ASME / ASTM / API / MSS / ISA").alignment = ALIGN_LEFT
    ws0.cell(row=curr_r, column=5, value=sum(d["qty"] for d in disciplines_data.values())).number_format = "#,##0.00"
    ws0.cell(row=curr_r, column=6, value="MIXTE").alignment = ALIGN_CENTER
    ws0.cell(row=curr_r, column=7, value=tot_steel_kg).number_format = "#,##0.00 kg"
    ws0.cell(row=curr_r, column=8, value=1.0).number_format = "0.0%"
    ws0.cell(row=curr_r, column=9, value="").alignment = ALIGN_CENTER
    ws0.cell(row=curr_r, column=10, value=len(items)).alignment = ALIGN_CENTER

    for col_idx in range(2, 11):
        c = ws0.cell(row=curr_r, column=col_idx)
        c.font = FONT_TOTAL
        c.fill = FILL_TOTAL
        c.border = BORDER_TOTAL

    # 4. Sous-Tableaux Spécialisés de Ventilation
    # 4.1 Robinetterie / Vannes
    curr_r += 2
    ws0.merge_cells(start_row=curr_r, start_column=2, end_row=curr_r, end_column=10)
    c_sub1 = ws0.cell(row=curr_r, column=2, value="2. VENTILATION DÉTAILLÉE DE LA ROBINETTERIE & VANNES (VALVES)")
    c_sub1.font = FONT_SECTION
    c_sub1.fill = FILL_SUBSECTION
    c_sub1.alignment = ALIGN_LEFT
    ws0.row_dimensions[curr_r].height = 22

    curr_r += 1
    headers_valves = [
        "N°", "Type de Vanne / Robinet", "Diamètre (NPS)", "Classe / Rating", 
        "Nuance Matière", "Quantité (U)", "Poids Unit. (kg)", "Poids Total (kg)", "Lignes Isométriques"
    ]
    for idx, h in enumerate(headers_valves, 2):
        cell = ws0.cell(row=curr_r, column=idx, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER if idx not in (3, 10) else ALIGN_LEFT
        cell.border = BORDER_THIN
    ws0.row_dimensions[curr_r].height = 20

    valves_items = disciplines_data["VALVE"]["items"]
    if not valves_items:
        curr_r += 1
        ws0.merge_cells(start_row=curr_r, start_column=2, end_row=curr_r, end_column=10)
        c_empty = ws0.cell(row=curr_r, column=2, value="Aucune vanne spécifique répertoriée dans ce lot isométrique (tronçons droits ou spools nus).")
        c_empty.font = FONT_REGULAR
        c_empty.alignment = ALIGN_CENTER
        c_empty.border = BORDER_THIN
    else:
        for v_idx, it in enumerate(valves_items, 1):
            curr_r += 1
            ws0.row_dimensions[curr_r].height = 19
            v_vals = [
                v_idx,
                it.get("description", "Vanne"),
                it.get("size", "-"),
                it.get("rating", "-"),
                it.get("material", "-"),
                it.get("quantity", 1),
                it.get("weight_unit", 0.0),
                it.get("weight_total", 0.0),
                it.get("lines_str", "-")
            ]
            for idx, val in enumerate(v_vals, 2):
                cell = ws0.cell(row=curr_r, column=idx, value=val)
                cell.font = FONT_REGULAR
                cell.border = BORDER_THIN
                if idx in (2, 4, 5):
                    cell.alignment = ALIGN_CENTER
                elif idx in (7, 8, 9):
                    cell.alignment = ALIGN_RIGHT
                    cell.number_format = "#,##0.00" if idx in (8, 9) else "#,##0"
                else:
                    cell.alignment = ALIGN_LEFT

    # 4.2 Joints d'étanchéité
    curr_r += 2
    ws0.merge_cells(start_row=curr_r, start_column=2, end_row=curr_r, end_column=10)
    c_sub2 = ws0.cell(row=curr_r, column=2, value="3. VENTILATION DÉTAILLÉE DES JOINTS D'ÉTANCHÉITÉ (GASKETS)")
    c_sub2.font = FONT_SECTION
    c_sub2.fill = FILL_SUBSECTION
    c_sub2.alignment = ALIGN_LEFT
    ws0.row_dimensions[curr_r].height = 22

    curr_r += 1
    headers_gaskets = [
        "N°", "Désignation Technique du Joint", "Diamètre (NPS)", "Classe / Rating",
        "Garniture / Matière", "Quantité (U)", "Poids Unit. (kg)", "Poids Total (kg)", "Lignes Isométriques"
    ]
    for idx, h in enumerate(headers_gaskets, 2):
        cell = ws0.cell(row=curr_r, column=idx, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER if idx not in (3, 10) else ALIGN_LEFT
        cell.border = BORDER_THIN
    ws0.row_dimensions[curr_r].height = 20

    gasket_items = disciplines_data["GASKET"]["items"]
    if not gasket_items:
        curr_r += 1
        ws0.merge_cells(start_row=curr_r, start_column=2, end_row=curr_r, end_column=10)
        c_empty = ws0.cell(row=curr_r, column=2, value="Aucun joint répertorié dans ce lot.")
        c_empty.font = FONT_REGULAR
        c_empty.alignment = ALIGN_CENTER
        c_empty.border = BORDER_THIN
    else:
        for g_idx, it in enumerate(gasket_items, 1):
            curr_r += 1
            ws0.row_dimensions[curr_r].height = 19
            g_vals = [
                g_idx,
                it.get("description", "Joint"),
                it.get("size", "-"),
                it.get("rating", "-"),
                it.get("material", "-"),
                it.get("quantity", 1),
                it.get("weight_unit", 0.0),
                it.get("weight_total", 0.0),
                it.get("lines_str", "-")
            ]
            for idx, val in enumerate(g_vals, 2):
                cell = ws0.cell(row=curr_r, column=idx, value=val)
                cell.font = FONT_REGULAR
                cell.border = BORDER_THIN
                if idx in (2, 4, 5):
                    cell.alignment = ALIGN_CENTER
                elif idx in (7, 8, 9):
                    cell.alignment = ALIGN_RIGHT
                    cell.number_format = "#,##0.00" if idx in (8, 9) else "#,##0"
                else:
                    cell.alignment = ALIGN_LEFT

    # 4.3 Tuyauterie Linéaire
    curr_r += 2
    ws0.merge_cells(start_row=curr_r, start_column=2, end_row=curr_r, end_column=10)
    c_sub3 = ws0.cell(row=curr_r, column=2, value="4. VENTILATION LINÉAIRE DE LA TUYAUTERIE (PIPING LINEAR SUMMARY)")
    c_sub3.font = FONT_SECTION
    c_sub3.fill = FILL_SUBSECTION
    c_sub3.alignment = ALIGN_LEFT
    ws0.row_dimensions[curr_r].height = 22

    curr_r += 1
    headers_pipes = [
        "N°", "Description Tuyauterie (ASME B36.10M)", "Diamètre (NPS)", "Schedule",
        "Nuance Matière", "Métrage Linéaire (m)", "Poids Unit. (kg/m)", "Poids Total (kg)", "Lignes Isométriques"
    ]
    for idx, h in enumerate(headers_pipes, 2):
        cell = ws0.cell(row=curr_r, column=idx, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER if idx not in (3, 10) else ALIGN_LEFT
        cell.border = BORDER_THIN
    ws0.row_dimensions[curr_r].height = 20

    pipe_items = disciplines_data["PIPE"]["items"]
    if not pipe_items:
        curr_r += 1
        ws0.merge_cells(start_row=curr_r, start_column=2, end_row=curr_r, end_column=10)
        c_empty = ws0.cell(row=curr_r, column=2, value="Métrage estimé globalement sans décomposition unitaire.")
        c_empty.font = FONT_REGULAR
        c_empty.alignment = ALIGN_CENTER
        c_empty.border = BORDER_THIN
    else:
        for p_idx, it in enumerate(pipe_items, 1):
            curr_r += 1
            ws0.row_dimensions[curr_r].height = 19
            p_vals = [
                p_idx,
                it.get("description", "Tube"),
                it.get("size", "-"),
                it.get("schedule", "-"),
                it.get("material", "-"),
                it.get("quantity", 0.0),
                it.get("weight_unit", 0.0),
                it.get("weight_total", 0.0),
                it.get("lines_str", "-")
            ]
            for idx, val in enumerate(p_vals, 2):
                cell = ws0.cell(row=curr_r, column=idx, value=val)
                cell.font = FONT_REGULAR
                cell.border = BORDER_THIN
                if idx in (2, 4, 5):
                    cell.alignment = ALIGN_CENTER
                elif idx in (7, 8, 9):
                    cell.alignment = ALIGN_RIGHT
                    cell.number_format = "#,##0.00"
                else:
                    cell.alignment = ALIGN_LEFT

    # 4.4 Instrumentation & Accessoires
    curr_r += 2
    ws0.merge_cells(start_row=curr_r, start_column=2, end_row=curr_r, end_column=10)
    c_sub4 = ws0.cell(row=curr_r, column=2, value="5. VENTILATION DE L'INSTRUMENTATION & ACCESSOIRES (INSTRUMENTS)")
    c_sub4.font = FONT_SECTION
    c_sub4.fill = FILL_SUBSECTION
    c_sub4.alignment = ALIGN_LEFT
    ws0.row_dimensions[curr_r].height = 22

    curr_r += 1
    headers_instr = [
        "N°", "Désignation Instrument / Piquage", "Diamètre / Raccord", "Classe / Rating",
        "Matière", "Quantité (U)", "Poids Unit. (kg)", "Poids Total (kg)", "Lignes Isométriques"
    ]
    for idx, h in enumerate(headers_instr, 2):
        cell = ws0.cell(row=curr_r, column=idx, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER if idx not in (3, 10) else ALIGN_LEFT
        cell.border = BORDER_THIN
    ws0.row_dimensions[curr_r].height = 20

    instr_items = disciplines_data["INSTRUMENTS"]["items"]
    if not instr_items:
        curr_r += 1
        ws0.merge_cells(start_row=curr_r, start_column=2, end_row=curr_r, end_column=10)
        c_empty = ws0.cell(row=curr_r, column=2, value="Aucun instrument spécifique en ligne répertorié sur ce tronçon.")
        c_empty.font = FONT_REGULAR
        c_empty.alignment = ALIGN_CENTER
        c_empty.border = BORDER_THIN
    else:
        for i_idx, it in enumerate(instr_items, 1):
            curr_r += 1
            ws0.row_dimensions[curr_r].height = 19
            i_vals = [
                i_idx,
                it.get("description", "Instrument"),
                it.get("size", "-"),
                it.get("rating", "-"),
                it.get("material", "-"),
                it.get("quantity", 1),
                it.get("weight_unit", 0.0),
                it.get("weight_total", 0.0),
                it.get("lines_str", "-")
            ]
            for idx, val in enumerate(i_vals, 2):
                cell = ws0.cell(row=curr_r, column=idx, value=val)
                cell.font = FONT_REGULAR
                cell.border = BORDER_THIN
                if idx in (2, 4, 5):
                    cell.alignment = ALIGN_CENTER
                elif idx in (7, 8, 9):
                    cell.alignment = ALIGN_RIGHT
                    cell.number_format = "#,##0.00" if idx in (8, 9) else "#,##0"
                else:
                    cell.alignment = ALIGN_LEFT

    # Ajustement des largeurs de colonnes spécifiques pour ws0
    ws0.column_dimensions["A"].width = 4
    ws0.column_dimensions["B"].width = 7
    ws0.column_dimensions["C"].width = 38
    ws0.column_dimensions["D"].width = 36
    ws0.column_dimensions["E"].width = 16
    ws0.column_dimensions["F"].width = 16
    ws0.column_dimensions["G"].width = 16
    ws0.column_dimensions["H"].width = 16
    ws0.column_dimensions["I"].width = 24
    ws0.column_dimensions["J"].width = 32

    # =========================================================================
    # ONGLET 1 : MTO_GLOBAL_SYNTHESE
    # =========================================================================
    ws1 = wb.create_sheet(title="MTO_GLOBAL_SYNTHESE")
    ws1.views.sheetView[0].showGridLines = True

    # Titre
    ws1["A1"] = "ARKAN EPC INTELLIGENCE — MATERIAL TAKE-OFF (MTO) GLOBAL"
    ws1["A1"].font = FONT_TITLE
    ws1["A2"] = f"Synthèse consolidée multi-isométriques • {stats['total_plans']} plans analysés • {stats['unique_items_count']} composants uniques • Tonnage total : {stats['total_steel_weight_tonnes']} T"
    ws1["A2"].font = FONT_SUBTITLE

    # En-têtes de colonnes
    headers1 = [
        "N°", "Catégorie", "Description Matériel (ASME / ASTM / API)", 
        "Diam. (NPS)", "Schedule", "Rating / Classe", "Nuance Matière",
        "Quantité Cumulée", "Unité", "Poids Unit. (kg)", "Poids Total (kg)",
        "Nb Lignes", "Lignes Isométriques Concernées"
    ]

    row_idx = 4
    for col_idx, h in enumerate(headers1, 1):
        cell = ws1.cell(row=row_idx, column=col_idx, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER if col_idx not in (3, 13) else ALIGN_LEFT
        cell.border = BORDER_THIN

    ws1.row_dimensions[row_idx].height = 26

    # Remplissage des données
    curr_cat = None
    item_num = 1
    total_qty_m = 0.0
    total_wt_all = 0.0

    for it in items:
        cat = it["category"].upper()
        # Séparateur de catégorie élégant
        if cat != curr_cat:
            curr_cat = cat
            row_idx += 1
            ws1.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=len(headers1))
            cat_cell = ws1.cell(row=row_idx, column=1, value=f"DISCIPLINE : {curr_cat}")
            cat_cell.font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
            cat_cell.fill = FILL_CAT_HEADER
            cat_cell.alignment = ALIGN_LEFT
            ws1.row_dimensions[row_idx].height = 20

        row_idx += 1
        ws1.row_dimensions[row_idx].height = 20
        fill = FILL_ZEBRA if item_num % 2 == 0 else PatternFill(fill_type=None)

        vals = [
            item_num,
            it["category"],
            it["description"],
            it["size"],
            it["schedule"],
            it["rating"],
            it["material"],
            it["quantity"],
            it["unit"],
            it["weight_unit"],
            it["weight_total"],
            it["lines_count"],
            it["lines_str"]
        ]

        if it["unit"] == "M":
            total_qty_m += it["quantity"]
        total_wt_all += it["weight_total"]

        for col_idx, v in enumerate(vals, 1):
            cell = ws1.cell(row=row_idx, column=col_idx, value=v)
            cell.font = FONT_REGULAR
            cell.border = BORDER_THIN
            if fill.fill_type:
                cell.fill = fill

            if col_idx in (1, 4, 5, 6, 9, 12):
                cell.alignment = ALIGN_CENTER
            elif col_idx in (8, 10, 11):
                cell.alignment = ALIGN_RIGHT
                cell.number_format = "#,##0.00" if col_idx != 8 or isinstance(v, float) else "#,##0"
            else:
                cell.alignment = ALIGN_LEFT

        item_num += 1

    # Ligne de TOTAL Global
    row_idx += 1
    ws1.row_dimensions[row_idx].height = 24
    for c in range(1, len(headers1) + 1):
        cell = ws1.cell(row=row_idx, column=c)
        cell.fill = FILL_TOTAL
        cell.border = BORDER_TOTAL
        cell.font = FONT_TOTAL

    ws1.cell(row=row_idx, column=2, value="TOTAL CONSOLIDÉ")
    ws1.cell(row=row_idx, column=11, value=round(total_wt_all, 2)).number_format = "#,##0.00 kg"

    # =========================================================================
    # ONGLET 2 : MTO_PAR_LIGNE (Détail unitaire)
    # =========================================================================
    ws2 = wb.create_sheet(title="MTO_PAR_LIGNE")
    ws2.views.sheetView[0].showGridLines = True

    ws2["A1"] = "ARKAN EPC — DÉTAIL MATÉRIEL PAR LIGNE ISOMÉTRIQUE"
    ws2["A1"].font = FONT_TITLE

    headers2 = [
        "Plan Source", "Repère Ligne", "Item N°", "Catégorie", "Description Composant",
        "Diamètre", "Schedule / Rating", "Nuance", "Quantité", "Unité", "Poids Unit. (kg)", "Poids Total (kg)"
    ]

    r2 = 3
    for c_idx, h in enumerate(headers2, 1):
        cell = ws2.cell(row=r2, column=c_idx, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER if c_idx not in (1, 2, 5) else ALIGN_LEFT
        cell.border = BORDER_THIN
    ws2.row_dimensions[r2].height = 24

    for plan in all_plans_raw:
        fname = plan.get("filename", "")
        lnum = (plan.get("metadata") or {}).get("line_number") or fname
        for it in (plan.get("mto") or []):
            r2 += 1
            vals2 = [
                sanitize_excel_val(fname),
                sanitize_excel_val(lnum),
                it.get("item_no", 1),
                sanitize_excel_val(it.get("category", "")),
                sanitize_excel_val(it.get("description", "")),
                sanitize_excel_val(it.get("size", "")),
                sanitize_excel_val(f"{it.get('schedule', '')} {it.get('rating', '')}".strip()),
                sanitize_excel_val(it.get("material", "")),
                _safe_float(it.get("quantity"), 1.0),
                sanitize_excel_val(it.get("unit", "EA")),
                _safe_float(it.get("weight_unit"), 0.0),
                _safe_float(it.get("weight_total"), 0.0)
            ]
            for c_idx, v in enumerate(vals2, 1):
                cell = ws2.cell(row=r2, column=c_idx, value=v)
                cell.font = FONT_REGULAR
                cell.border = BORDER_THIN
                if c_idx in (3, 6, 10):
                    cell.alignment = ALIGN_CENTER
                elif c_idx in (9, 11, 12):
                    cell.alignment = ALIGN_RIGHT
                    cell.number_format = "#,##0.00"
                else:
                    cell.alignment = ALIGN_LEFT

    # =========================================================================
    # ONGLET 3 : RECAP_PLANS (Tableau de bord isométriques)
    # =========================================================================
    ws3 = wb.create_sheet(title="RECAP_PLANS")
    ws3.views.sheetView[0].showGridLines = True

    ws3["A1"] = "ARKAN EPC — INVENTAIRE DES PLANS ISOMÉTRIQUES TRAITÉS"
    ws3["A1"].font = FONT_TITLE

    headers3 = [
        "N°", "Nom du Fichier Plan", "Repère Ligne Tuyauterie", "Classe Spécification",
        "Pression de Calcul", "Nombre d'Articles", "Métrage Tube (m)", "Masse Acier (kg)", "Nb Spools"
    ]

    r3 = 3
    for c_idx, h in enumerate(headers3, 1):
        cell = ws3.cell(row=r3, column=c_idx, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER if c_idx not in (2, 3) else ALIGN_LEFT
        cell.border = BORDER_THIN
    ws3.row_dimensions[r3].height = 24

    for idx_p, p in enumerate(plans, 1):
        r3 += 1
        row_vals = [
            idx_p,
            p["filename"],
            p["line_number"],
            p["spec"],
            p["pressure"],
            p["items_count"],
            p["pipe_length_m"],
            p["weight_kg"],
            p["spools_count"]
        ]
        for c_idx, v in enumerate(row_vals, 1):
            cell = ws3.cell(row=r3, column=c_idx, value=v)
            cell.font = FONT_REGULAR
            cell.border = BORDER_THIN
            if c_idx in (1, 4, 5):
                cell.alignment = ALIGN_CENTER
            elif c_idx in (6, 7, 8, 9):
                cell.alignment = ALIGN_RIGHT
                cell.number_format = "#,##0.00" if c_idx in (7, 8) else "#,##0"
            else:
                cell.alignment = ALIGN_LEFT

    # =========================================================================
    # ONGLET 4 : STATS_METALLURGIE & FABRICATION
    # =========================================================================
    ws4 = wb.create_sheet(title="STATS_METALLURGIE")
    ws4.views.sheetView[0].showGridLines = True

    ws4["A1"] = "ARKAN EPC — STATISTIQUES GLOBALES DE FABRICATION & TRAÇABILITÉ"
    ws4["A1"].font = FONT_TITLE

    kpis = [
        ("Nombre total de plans isométriques analysés", stats["total_plans"], "plans"),
        ("Nombre total d'articles uniques identifiés", stats["unique_items_count"], "articles"),
        ("Longueur totale de tuyauterie (Linéaire)", stats["total_pipe_length_m"], "mètres"),
        ("Masse totale d'acier (kg)", stats["total_steel_weight_kg"], "kg"),
        ("Masse totale d'acier (Tonnes)", stats["total_steel_weight_tonnes"], "Tonnes"),
        ("Nombre total de tronçons préfabriqués (Spools)", stats["total_spools"], "spools"),
        ("Soudures estimées en Atelier (Shop Welds)", stats["total_shop_welds"], "soudures"),
        ("Soudures estimées sur Chantier (Field Welds)", stats["total_field_welds"], "soudures"),
        ("Surface de peinture estimée", round(stats["total_pipe_length_m"] * 0.35, 2), "m²"),
    ]

    r4 = 3
    ws4.cell(row=r4, column=1, value="Métrique de Construction").font = FONT_HEADER
    ws4.cell(row=r4, column=1).fill = FILL_HEADER
    ws4.cell(row=r4, column=2, value="Valeur").font = FONT_HEADER
    ws4.cell(row=r4, column=2).fill = FILL_HEADER
    ws4.cell(row=r4, column=3, value="Unité").font = FONT_HEADER
    ws4.cell(row=r4, column=3).fill = FILL_HEADER
    ws4.row_dimensions[r4].height = 24

    for label, val, unit in kpis:
        r4 += 1
        ws4.row_dimensions[r4].height = 20
        c1 = ws4.cell(row=r4, column=1, value=label)
        c2 = ws4.cell(row=r4, column=2, value=val)
        c3 = ws4.cell(row=r4, column=3, value=unit)
        for c in (c1, c2, c3):
            c.font = FONT_REGULAR
            c.border = BORDER_THIN
        c2.alignment = ALIGN_RIGHT
        c2.font = FONT_BOLD
        c2.number_format = "#,##0.00" if isinstance(val, float) else "#,##0"
        c3.alignment = ALIGN_CENTER

    # =========================================================================
    # ONGLET 5 : VERIFICATION_ANOMALIES (Contrôle Triangulaire Isométrique)
    # =========================================================================
    ws5 = wb.create_sheet(title="VERIFICATION_ANOMALIES")
    ws5.views.sheetView[0].showGridLines = True

    ws5["A1"] = "ARKAN EPC — CONTRÔLE DE COHÉRENCE TRIANGULAIRE (SCHÉMA ↔ CARTOUCHE ↔ NOMENCLATURE)"
    ws5["A1"].font = FONT_TITLE

    headers5 = [
        "N°", "Gravité", "Code Erreur", "Composant / Localisation",
        "Valeur Attendue (Schéma / Norme)", "Valeur Déclarée (Nomenclature / Cartouche)",
        "Titre de l'Anomalie", "Explication Technique & Impact ARH", "Recommandation Corrective"
    ]

    r5 = 3
    for c_idx, h in enumerate(headers5, 1):
        cell = ws5.cell(row=r5, column=c_idx, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER if c_idx in (1, 2, 3) else ALIGN_LEFT
        cell.border = BORDER_THIN
    ws5.row_dimensions[r5].height = 24

    all_anomalies = []
    for plan in all_plans_raw:
        for anom in (plan.get("anomalies") or []):
            all_anomalies.append(anom)

    fill_crit = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
    fill_maj = PatternFill(start_color="FFEDD5", end_color="FFEDD5", fill_type="solid")
    fill_min = PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid")
    fill_qual = PatternFill(start_color="E0F2FE", end_color="E0F2FE", fill_type="solid")

    font_crit = Font(name="Segoe UI", size=9, bold=True, color="991B1B")
    font_maj = Font(name="Segoe UI", size=9, bold=True, color="9A3412")
    font_min = Font(name="Segoe UI", size=9, bold=True, color="854D0E")
    font_qual = Font(name="Segoe UI", size=9, bold=True, color="075985")

    if not all_anomalies:
        r5 += 1
        ws5.merge_cells(start_row=r5, start_column=1, end_row=r5, end_column=9)
        c_ok = ws5.cell(row=r5, column=1, value="Aucune anomalie détectée. Cohérence triangulaire validée à 100% (ASME B16.5 / B31.3 / Cartouche).")
        c_ok.font = Font(name="Segoe UI", size=10, bold=True, color="166534")
        c_ok.fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
        c_ok.alignment = ALIGN_CENTER
        c_ok.border = BORDER_THIN
        ws5.row_dimensions[r5].height = 26
    else:
        for idx_a, a in enumerate(all_anomalies, 1):
            r5 += 1
            ws5.row_dimensions[r5].height = 42
            sev = (a.get("severity") or "").upper()
            row_vals = [
                idx_a,
                a.get("severity_label") or sev,
                a.get("id") or a.get("code") or "-",
                a.get("component") or "-",
                a.get("expected") or "-",
                a.get("found") or "-",
                a.get("title") or "-",
                a.get("description") or "-",
                a.get("recommendation") or "-"
            ]
            for c_idx, val in enumerate(row_vals, 1):
                cell = ws5.cell(row=r5, column=c_idx, value=val)
                cell.font = FONT_REGULAR
                cell.border = BORDER_THIN
                if c_idx == 1:
                    cell.alignment = ALIGN_CENTER
                elif c_idx == 2:
                    cell.alignment = ALIGN_CENTER
                    if sev == "CRITICAL":
                        cell.fill = fill_crit
                        cell.font = font_crit
                    elif sev == "MAJOR":
                        cell.fill = fill_maj
                        cell.font = font_maj
                    elif sev == "MINOR":
                        cell.fill = fill_min
                        cell.font = font_min
                    else:
                        cell.fill = fill_qual
                        cell.font = font_qual
                elif c_idx == 3:
                    cell.alignment = ALIGN_CENTER
                    cell.font = FONT_BOLD
                elif c_idx in (4, 5, 6):
                    cell.alignment = ALIGN_LEFT
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # Ajustement dynamique des largeurs de colonnes sur toutes les feuilles
    for sheet in [ws1, ws2, ws3, ws4, ws5]:
        for col in sheet.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                # Ne pas prendre la ligne 1 & 2 pour la largeur (titres fusionnés ou longs)
                if cell.row in (1, 2):
                    continue
                v_str = str(cell.value or "")
                if len(v_str) > max_len:
                    max_len = len(v_str)
            sheet.column_dimensions[col_letter].width = max(min(max_len + 3, 50), 11)

    # Largeurs sur-mesure pour l'onglet anomalies
    ws5.column_dimensions["A"].width = 6
    ws5.column_dimensions["B"].width = 24
    ws5.column_dimensions["C"].width = 16
    ws5.column_dimensions["D"].width = 26
    ws5.column_dimensions["E"].width = 30
    ws5.column_dimensions["F"].width = 30
    ws5.column_dimensions["G"].width = 36
    ws5.column_dimensions["H"].width = 55
    ws5.column_dimensions["I"].width = 50

    # Définir l'onglet récapitulatif comme onglet actif par défaut à l'ouverture d'Excel
    wb.active = 0

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    try:
        _neutralize_formulas(wb)
        wb.save(output_path)
    except (OSError, PermissionError) as e_save:
        import logging
        logging.getLogger("mto_consolidator").error("[MTO Consolidator] Impossible de sauvegarder le classeur Excel %s: %s", output_path, e_save)
        raise
    return output_path



# ═══════════════════════════════════════════════════════════════════════════════
# ARKAN v3 : GÉNÉRATEUR DU CLASSEUR MAÎTRE PROJET MULTI-DISCIPLINES (9 ONGLETS)
# ═══════════════════════════════════════════════════════════════════════════════

PIPING_DISCS = {"PIPE", "FITTING", "FLANGE", "VALVE", "BOLT", "GASKET", "SUPPORTS"}

MASTER_TABS = ["TUYAUTERIE_MTO", "DISTRIBUTION_MT_BT", "CARNET_DE_CABLES", "CHEMINS_ET_CANALISATIONS",
               "RESEAU_TERRE_FOUDRE", "ECLAIRAGE_ET_PRISES", "INSTRUMENTATION", "ACCESSOIRES_ELEC"]


def _add_reason(reasons: List[str], msg: str) -> None:
    if msg and msg not in reasons:
        reasons.append(msg)


def build_cable_breakdown_summary(cables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ventile et agrège les câbles par section normalisée et type selon la norme CEI 60502-1."""
    from cable_parser import parse_cable
    by_sec = defaultdict(lambda: {
        "count": 0, "net_m": 0.0, "order_m": 0.0, "weight_kg": 0.0,
        "unit_w": 0.0, "type": "", "voltage": "", "family": "POWER"
    })
    for c in cables:
        sec = str(c.get("size") or c.get("cable_section") or "").strip()
        if not sec or sec == "-":
            sec = c.get("section") or "INCONNUE"
        ctype = c.get("cable_type") or c.get("schedule") or ""
        volt = c.get("voltage") or ("0.23 kV" if "2.5" in sec or "1.5" in sec else "0.4 kV")
        q_net = _safe_float(c.get("quantity_net", c.get("quantity")), 0.0)
        q_ord = _safe_float(c.get("quantity_order", c.get("quantity")), q_net)
        wt = _safe_float(c.get("weight_total"), 0.0)
        wu = _safe_float(c.get("weight_unit"), 0.0)

        p = parse_cable(sec)
        norm_sec = (p.get("normalized_spec") if p else sec) or sec
        family = "POWER"
        if p:
            family = p.get("family", "POWER")
            if not wu:
                wu = p.get("linear_weight_kg_m", 1.2)
        if not wt and wu and q_net:
            wt = round(wu * q_net, 2)

        by_sec[norm_sec]["count"] += 1
        by_sec[norm_sec]["net_m"] += q_net
        by_sec[norm_sec]["order_m"] += q_ord
        by_sec[norm_sec]["weight_kg"] += wt
        by_sec[norm_sec]["unit_w"] = wu
        if ctype and not by_sec[norm_sec]["type"]:
            by_sec[norm_sec]["type"] = ctype
        if volt and not by_sec[norm_sec]["voltage"]:
            by_sec[norm_sec]["voltage"] = volt
        by_sec[norm_sec]["family"] = family

    summary = []
    for sec_key, d in sorted(by_sec.items(), key=lambda x: -x[1]["net_m"]):
        summary.append({
            "section": sec_key,
            "cable_type": d["type"] or "CU / XLPE / GSTA / PVC",
            "voltage": d["voltage"] or "0.4 kV",
            "family": d["family"],
            "count": d["count"],
            "net_length_m": round(d["net_m"], 1),
            "order_length_m": round(d["order_m"], 1),
            "weight_unit_kg_m": round(d["unit_w"], 3),
            "total_weight_kg": round(d["weight_kg"], 1)
        })
    return summary


def generate_master_multidiscipline_excel(
    items: List[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]] = None,
    anomalies: Optional[List[Dict[str, Any]]] = None,
    output_path: str = "MTO_GLOBAL_PROJET.xlsx"
) -> str:
    """
    Classeur maître de projet — 11 onglets :
      SYNTHESE_GLOBALE, TUYAUTERIE_MTO, DISTRIBUTION_MT_BT, CARNET_DE_CABLES, CHEMINS_ET_CANALISATIONS,
      RESEAU_TERRE_FOUDRE, ECLAIRAGE_ET_PRISES, INSTRUMENTATION, ACCESSOIRES_ELEC, A_VALIDER,
      MATRICE_RESERVES_GLOBALE.

    Règles (audit ARKAN v3) :
      * totaux de longueur uniquement sur les articles en mètres (plus de chambres comptées en m) ;
      * totaux par UNITÉ dans chaque onglet (SUMIF), plus de somme mixte m + EA ;
      * marge d'achat issue de la config PAR CATÉGORIE ; marge non définie -> ligne « à valider » ;
      * score de confiance absent = NON ÉVALUÉ (jamais 100 %) ; 0 % n'est plus transformé en 100 % ;
      * départs TGBT séparés en appareil + câble ; longueur non mesurée -> « à valider » ;
      * source + empreinte de la configuration imprimées dans la synthèse ;
      * texte commençant par '=' neutralisé à l'enregistrement.
    """
    from config_loader import load_project_config, resolve_margin, apply_margin, get_config_info
    import datetime as _dt

    cfg = load_project_config()
    cfg_info = get_config_info()
    metadata = metadata or {}
    anomalies = anomalies or []
    conf_min = float((cfg.get("thresholds") or {}).get("confidence_min_threshold", 0.85))

    items = expand_feeders(items)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    f_title = Font(name="Segoe UI", size=15, bold=True, color="1E3A8A")
    f_subtitle = Font(name="Segoe UI", size=10, italic=True, color="475569")
    f_header = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    f_bold = Font(name="Segoe UI", size=9, bold=True, color="0F172A")
    f_reg = Font(name="Segoe UI", size=9, color="0F172A")
    f_kpi_val = Font(name="Segoe UI", size=14, bold=True, color="1E3A8A")
    f_alert_val = Font(name="Segoe UI", size=14, bold=True, color="DC2626")

    fill_navy = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    fill_kpi = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    fill_warn = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    fill_reserve = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
    fill_zebra = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    b_thin = Border(left=Side(style="thin", color="CBD5E1"), right=Side(style="thin", color="CBD5E1"),
                    top=Side(style="thin", color="CBD5E1"), bottom=Side(style="thin", color="CBD5E1"))
    b_total = Border(top=Side(style="thin", color="94A3B8"), bottom=Side(style="double", color="1E3A8A"))

    buckets: Dict[str, List[Dict[str, Any]]] = {name: [] for name in MASTER_TABS}
    buckets["A_VALIDER"] = []

    total_weight_steel_kg = 0.0
    total_weight_cable_kg = 0.0
    total_cable_m = total_tray_m = total_earth_m = 0.0
    total_tray_units = total_earth_units = 0.0
    unevaluated = 0

    for it in items:
        disc = classify_item_discipline(it)
        unit = str(it.get("unit") or "EA").upper().strip()
        is_len = unit in LENGTH_UNITS
        reasons: List[str] = []
        for r in it.get("extractor_reasons") or []:
            _add_reason(reasons, str(r))

        raw_q = it.get("quantity")
        if raw_q is None or raw_q == "":
            raw_q = it.get("qty")
        q_opt = _parse_number(raw_q)
        if q_opt is None:
            _add_reason(reasons, "quantité absente ou illisible (0 retenu)")
        q_net = q_opt if q_opt is not None else 0.0

        margin, m_defined = resolve_margin(it.get("category"), discipline=disc, cable_kind=it.get("cable_kind"))
        if not m_defined and disc not in PIPING_DISCS and disc != "OTHERS":
            _add_reason(reasons, "marge d'achat non définie dans la config (0 % appliqué)")
        it["quantity_net"] = q_net
        it["quantity_ordered"] = apply_margin(q_net, margin, unit)
        it["procurement_margin_percent"] = f"{margin * 100:g}%"

        w_tot = _safe_float(it.get("weight_total"), 0.0)
        if not w_tot and it.get("weight_unit"):
            w_tot = round(q_net * _safe_float(it.get("weight_unit")), 2)
            it["weight_total"] = w_tot

        if disc in PIPING_DISCS:
            buckets["TUYAUTERIE_MTO"].append(it)
            total_weight_steel_kg += w_tot
        elif disc == "DISTRIBUTION_MT_BT":
            buckets["DISTRIBUTION_MT_BT"].append(it)
            total_weight_steel_kg += w_tot
        elif disc == "CARNET_DE_CABLES":
            buckets["CARNET_DE_CABLES"].append(it)
            if is_len:
                total_cable_m += q_net
            total_weight_cable_kg += w_tot
        elif disc == "CHEMINS_ET_CANALISATIONS":
            buckets["CHEMINS_ET_CANALISATIONS"].append(it)
            if is_len:
                total_tray_m += q_net
            else:
                total_tray_units += q_net
            total_weight_steel_kg += w_tot
        elif disc == "RESEAU_TERRE_FOUDRE":
            buckets["RESEAU_TERRE_FOUDRE"].append(it)
            if is_len:
                total_earth_m += q_net
            else:
                total_earth_units += q_net
            total_weight_cable_kg += w_tot
        elif disc == "ECLAIRAGE_ET_PRISES":
            buckets["ECLAIRAGE_ET_PRISES"].append(it)
            total_weight_steel_kg += w_tot
        elif disc == "INSTRUMENTS":
            buckets["INSTRUMENTATION"].append(it)
            total_weight_steel_kg += w_tot
        elif disc == "ACCESSOIRES_ELEC":
            buckets["ACCESSOIRES_ELEC"].append(it)
        else:
            _add_reason(reasons, f"article non classé (catégorie « {it.get('category') or '?'} »)")

        conf = _parse_confidence(it.get("confidence_score"))
        it["confidence_value"] = conf
        if conf is None:
            unevaluated += 1
        elif conf < conf_min:
            _add_reason(reasons, f"confiance {conf:.0%} < seuil {conf_min:.0%}")
        if it.get("needs_human_validation"):
            _add_reason(reasons, str(it.get("validation_note") or "validation humaine demandée"))

        it["validation_reasons"] = reasons
        if reasons:
            buckets["A_VALIDER"].append(it)

    # ═══ SYNTHESE_GLOBALE ═══
    ws_syn = wb.create_sheet(title="SYNTHESE_GLOBALE")
    ws_syn.merge_cells("A1:G1")
    ws_syn["A1"] = "ARKAN EPC — CLASSEUR MAÎTRE MTO MULTI-DISCIPLINES DE PROJET"
    ws_syn["A1"].font = f_title

    pm = cfg.get("project_metadata") or {}
    date_txt = metadata.get("date") or _dt.date.today().strftime("%d/%m/%Y")
    ws_syn["A2"] = sanitize_excel_val(
        f"Projet : {pm.get('project_name') or metadata.get('filename') or '—'} | "
        f"Client : {pm.get('client') or '—'} | Date : {date_txt}")
    ws_syn["A2"].font = f_subtitle

    cfg_line = f"Configuration : {cfg_info['source']} | empreinte {cfg_info['sha256'] or '—'} | schéma v{cfg_info['schema_version']}"
    if cfg_info.get("warning"):
        cfg_line += f" | ⚠ {cfg_info['warning']}"
    ws_syn["A3"] = sanitize_excel_val(cfg_line)
    ws_syn["A3"].font = Font(name="Segoe UI", size=9, bold=True, color="DC2626") if cfg_info["source"] == "DEFAULTS" else f_subtitle

    kpis = [
        ("Poids total acier & équipements (kg)", total_weight_steel_kg, '#,##0.0" kg"', False),
        ("Poids total câbles & cuivre nu (kg)", total_weight_cable_kg, '#,##0.0" kg"', False),
        ("Linéaire de câbles — quantité nette (m)", total_cable_m, '#,##0.0" m"', False),
        ("Linéaire de chemins de câbles (m)", total_tray_m, '#,##0.0" m"', False),
        ("Linéaire de cuivre nu — réseau de terre (m)", total_earth_m, '#,##0.0" m"', False),
        ("Chambres, buses & accessoires de cheminement (u)", total_tray_units, '#,##0.##" u"', False),
        ("Piquets, regards & accessoires de terre (u)", total_earth_units, '#,##0.##" u"', False),
        ("Articles à valider (onglet A_VALIDER)", len(buckets["A_VALIDER"]), '0" art."', len(buckets["A_VALIDER"]) > 0),
        ("Lignes sans score de confiance (non évaluées)", unevaluated, '0" lig."', unevaluated > 0),
        ("Réserves & anomalies inter-disciplines", len(anomalies), '0" détectée(s)"', len(anomalies) > 0),
    ]
    ws_syn["A4"] = "INDICATEURS CLÉS DU PROJET (QUANTITÉS NETTES)"
    ws_syn["A4"].font = Font(name="Segoe UI", size=11, bold=True, color="1E3A8A")
    for idx, (lbl, val, fmt, is_alert) in enumerate(kpis):
        r = 5 + idx
        ws_syn.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
        c1 = ws_syn.cell(row=r, column=1, value=lbl)
        c1.font, c1.fill, c1.border = f_bold, fill_kpi, b_thin
        c2 = ws_syn.cell(row=r, column=4, value=float(val))
        c2.number_format = fmt
        c2.font = f_alert_val if is_alert else f_kpi_val
        c2.fill = fill_warn if is_alert else fill_kpi
        c2.alignment = Alignment(horizontal="right", vertical="center")
        c2.border = b_thin

    # Tableau de ventilation normative par section de câble (CEI 60502-1)
    cable_items = buckets.get("CARNET_DE_CABLES", [])
    if cable_items:
        r_cab = 17
        ws_syn.merge_cells(f"A{r_cab}:I{r_cab}")
        ws_syn[f"A{r_cab}"] = "VENTILATION PAR SECTION & TYPE DE CÂBLE (NORME CEI 60502-1)"
        ws_syn[f"A{r_cab}"].font = Font(name="Segoe UI", size=11, bold=True, color="1E3A8A")

        cab_headers = ["N°", "SECTION NORMALISÉE", "TYPOLOGIE / ARMURE", "TENSION", "NBRE CÂBLES",
                       "LINÉAIRE NET (m)", "QTÉ COMMANDE (m)", "POIDS LIN (kg/m)", "POIDS TOTAL (kg)"]
        r_cab += 1
        for col_i, h in enumerate(cab_headers, start=1):
            c = ws_syn.cell(row=r_cab, column=col_i, value=h)
            c.font, c.fill = f_header, fill_navy
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        cab_summary = build_cable_breakdown_summary(cable_items)
        tot_c_net = 0.0
        tot_c_ord = 0.0
        tot_c_w = 0.0
        tot_c_cnt = 0

        for c_idx, cs in enumerate(cab_summary, start=1):
            r_cab += 1
            ws_syn.cell(row=r_cab, column=1, value=c_idx).alignment = Alignment(horizontal="center")
            ws_syn.cell(row=r_cab, column=2, value=sanitize_excel_val(cs["section"])).font = f_bold
            ws_syn.cell(row=r_cab, column=3, value=sanitize_excel_val(cs["cable_type"]))
            ws_syn.cell(row=r_cab, column=4, value=sanitize_excel_val(cs["voltage"])).alignment = Alignment(horizontal="center")
            ws_syn.cell(row=r_cab, column=5, value=cs["count"]).alignment = Alignment(horizontal="center")

            c_net = ws_syn.cell(row=r_cab, column=6, value=cs["net_length_m"])
            c_net.number_format = '#,##0.0" m"'
            c_net.alignment = Alignment(horizontal="right")

            c_ord = ws_syn.cell(row=r_cab, column=7, value=cs["order_length_m"])
            c_ord.number_format = '#,##0.0" m"'
            c_ord.alignment = Alignment(horizontal="right")

            c_wu = ws_syn.cell(row=r_cab, column=8, value=cs["weight_unit_kg_m"])
            c_wu.number_format = '#,##0.000" kg/m"'
            c_wu.alignment = Alignment(horizontal="right")

            c_wt = ws_syn.cell(row=r_cab, column=9, value=cs["total_weight_kg"])
            c_wt.number_format = '#,##0.0" kg"'
            c_wt.alignment = Alignment(horizontal="right")
            c_wt.font = f_bold

            for col_i in range(1, 10):
                ws_syn.cell(row=r_cab, column=col_i).border = b_thin

            tot_c_net += cs["net_length_m"]
            tot_c_ord += cs["order_length_m"]
            tot_c_w += cs["total_weight_kg"]
            tot_c_cnt += cs["count"]

        # Ligne de sous-total général câbles
        r_cab += 1
        ws_syn.merge_cells(start_row=r_cab, start_column=1, end_row=r_cab, end_column=4)
        tot_lbl = ws_syn.cell(row=r_cab, column=1, value="TOTAL GÉNÉRAL CÂBLES RÉCONCILIÉS")
        tot_lbl.font = f_bold
        tot_lbl.alignment = Alignment(horizontal="right", vertical="center")

        c_tot_cnt = ws_syn.cell(row=r_cab, column=5, value=tot_c_cnt)
        c_tot_cnt.font = f_bold
        c_tot_cnt.alignment = Alignment(horizontal="center")

        c_tot_net = ws_syn.cell(row=r_cab, column=6, value=tot_c_net)
        c_tot_net.font = f_bold
        c_tot_net.number_format = '#,##0.0" m"'
        c_tot_net.alignment = Alignment(horizontal="right")

        c_tot_ord = ws_syn.cell(row=r_cab, column=7, value=tot_c_ord)
        c_tot_ord.font = f_bold
        c_tot_ord.number_format = '#,##0.0" m"'
        c_tot_ord.alignment = Alignment(horizontal="right")

        ws_syn.cell(row=r_cab, column=8, value="-").alignment = Alignment(horizontal="center")

        c_tot_w = ws_syn.cell(row=r_cab, column=9, value=tot_c_w)
        c_tot_w.font = f_bold
        c_tot_w.number_format = '#,##0.0" kg"'
        c_tot_w.alignment = Alignment(horizontal="right")

        for col_i in range(1, 10):
            ws_syn.cell(row=r_cab, column=col_i).border = b_total

    # ═══ Onglets matériel ═══
    N_COLS = 17

    def build_standard_tab(ws_name: str, item_list: List[Dict[str, Any]]):
        ws = wb.create_sheet(title=ws_name)
        headers = ["N°", "TAG / REPÈRE", "DÉSIGNATION NORMALISÉE", "DIMENSION / SECTION", "SPÉCIFICATION / NORME",
                   "MATÉRIAU", "QTÉ NETTE (PLAN)", "MARGE ACHAT", "QTÉ À COMMANDER", "UNITÉ", "POIDS UNIT (kg)",
                   "POIDS TOTAL (kg)", "PLAN SOURCE", "RÉV", "CONFIANCE", "STATUT RÉSERVE", "OBSERVATIONS / À VALIDER"]
        for col_i, h in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_i, value=h)
            cell.font, cell.fill = f_header, fill_navy
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        row_i = 2
        for idx, it in enumerate(item_list, start=1):
            is_res = "RÉSERVE" in str(it.get("status", "")).upper() or "RESERVE" in str(it.get("tag", "")).upper()
            row_fill = fill_reserve if is_res else (fill_zebra if idx % 2 == 0 else PatternFill(fill_type=None))
            unit_txt = str(it.get("unit") or "EA").upper().strip()
            conf = it.get("confidence_value")

            ws.cell(row=row_i, column=1, value=idx).alignment = Alignment(horizontal="center")
            ws.cell(row=row_i, column=2, value=sanitize_excel_val(it.get("tag") or "—")).alignment = Alignment(horizontal="center")
            ws.cell(row=row_i, column=3, value=sanitize_excel_val(it.get("description") or it.get("designation") or "—"))
            ws.cell(row=row_i, column=4, value=sanitize_excel_val(it.get("size") or it.get("cable_section") or "—")).alignment = Alignment(horizontal="center")
            ws.cell(row=row_i, column=5, value=sanitize_excel_val(it.get("schedule") or it.get("cable_type") or "—"))
            ws.cell(row=row_i, column=6, value=sanitize_excel_val(it.get("material") or "—"))

            c_qnet = ws.cell(row=row_i, column=7, value=_safe_float(it.get("quantity_net", it.get("quantity"))))
            c_qnet.number_format = "#,##0.00"
            c_qnet.alignment = Alignment(horizontal="right")
            ws.cell(row=row_i, column=8, value=it.get("procurement_margin_percent") or "—").alignment = Alignment(horizontal="center")
            c_qord = ws.cell(row=row_i, column=9, value=_safe_float(it.get("quantity_ordered", it.get("quantity"))))
            c_qord.number_format = "#,##0.00"
            c_qord.alignment = Alignment(horizontal="right")
            ws.cell(row=row_i, column=10, value=sanitize_excel_val(unit_txt)).alignment = Alignment(horizontal="center")

            c_wunit = ws.cell(row=row_i, column=11, value=_safe_float(it.get("weight_unit")))
            c_wunit.number_format = "#,##0.00"
            c_wunit.alignment = Alignment(horizontal="right")
            c_wtot = ws.cell(row=row_i, column=12, value=_safe_float(it.get("weight_total")))
            c_wtot.number_format = "#,##0.00"
            c_wtot.alignment = Alignment(horizontal="right")

            ws.cell(row=row_i, column=13, value=sanitize_excel_val(it.get("source_drawing") or it.get("source_page") or "—"))
            ws.cell(row=row_i, column=14, value=sanitize_excel_val(str(it.get("revision") or "0"))).alignment = Alignment(horizontal="center")
            ws.cell(row=row_i, column=15, value=("non évalué" if conf is None else f"{round(conf * 100)}%")).alignment = Alignment(horizontal="center")
            ws.cell(row=row_i, column=16, value="ISSU DE RÉSERVE" if is_res else "PLAN D'ORIGINE").alignment = Alignment(horizontal="center")
            ws.cell(row=row_i, column=17, value=sanitize_excel_val("; ".join(it.get("validation_reasons") or [])))

            for c_idx in range(1, N_COLS + 1):
                cell_item = ws.cell(row=row_i, column=c_idx)
                cell_item.border = b_thin
                cell_item.font = f_reg
                if row_fill.fill_type:
                    cell_item.fill = row_fill
            if it.get("validation_reasons"):
                ws.cell(row=row_i, column=17).fill = fill_warn
            row_i += 1

        ws.freeze_panes = "A2"
        if item_list:
            first, last = 2, row_i - 1
            ws.auto_filter.ref = f"A1:{get_column_letter(N_COLS)}{last}"
            for u in sorted({str(it.get("unit") or "EA").upper().strip() for it in item_list}):
                ws.merge_cells(start_row=row_i, start_column=1, end_row=row_i, end_column=6)
                lbl = ws.cell(row=row_i, column=1, value=f"TOTAL PAR UNITÉ [{u}]")
                lbl.font = f_bold
                lbl.alignment = Alignment(horizontal="right", vertical="center")
                ws.cell(row=row_i, column=10, value=sanitize_excel_val(u)).alignment = Alignment(horizontal="center")
                for col_letter, col_idx in (("G", 7), ("I", 9)):
                    c = ws.cell(row=row_i, column=col_idx,
                                value=f"=SUMIF($J${first}:$J${last},$J{row_i},{col_letter}${first}:{col_letter}${last})")
                    c.font, c.number_format = f_bold, "#,##0.00"
                    c.alignment = Alignment(horizontal="right")
                for c_idx in range(1, N_COLS + 1):
                    ws.cell(row=row_i, column=c_idx).border = b_total
                row_i += 1
            ws.merge_cells(start_row=row_i, start_column=1, end_row=row_i, end_column=6)
            lbl = ws.cell(row=row_i, column=1, value="POIDS TOTAL (kg)")
            lbl.font = f_bold
            lbl.alignment = Alignment(horizontal="right", vertical="center")
            c = ws.cell(row=row_i, column=12, value=f"=SUM(L{first}:L{last})")
            c.font, c.number_format = f_bold, "#,##0.00"
            c.alignment = Alignment(horizontal="right")
            for c_idx in range(1, N_COLS + 1):
                ws.cell(row=row_i, column=c_idx).border = b_total

    for tab in MASTER_TABS:
        build_standard_tab(tab, buckets[tab])
    build_standard_tab("A_VALIDER", buckets["A_VALIDER"])

    # ═══ MATRICE_RESERVES_GLOBALE ═══
    ws_res = wb.create_sheet(title="MATRICE_RESERVES_GLOBALE")
    res_headers = ["N°", "RÈGLE / ID CONTRÔLE", "SÉVÉRITÉ", "TAG CONCERNÉ", "TITRE DE L'ANOMALIE", "DESCRIPTION TECHNIQUE",
                   "NORME / SOURCE", "ACTION / RECOMMANDATION INGÉNIEUR", "ARTICLE PROPOSÉ EN RÉSERVE", "STATUT"]
    for col_i, h in enumerate(res_headers, start=1):
        c = ws_res.cell(row=1, column=col_i, value=h)
        c.font, c.fill = f_header, fill_navy
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    sev_style = {"CRITICAL": ("FEE2E2", "991B1B"), "MAJOR": ("FEF3C7", "92400E"),
                 "WARNING": ("FEF3C7", "92400E"), "INFO": ("DBEAFE", "1E40AF")}
    r_curr = 2
    for idx, an in enumerate(anomalies, start=1):
        sev = str(an.get("severity") or "WARNING").upper()
        bg, fg = sev_style.get(sev, ("F1F5F9", "334155"))
        ws_res.cell(row=r_curr, column=1, value=idx).alignment = Alignment(horizontal="center")
        ws_res.cell(row=r_curr, column=2, value=sanitize_excel_val(an.get("rule") or an.get("check_id") or "CHECK")).alignment = Alignment(horizontal="center")
        c_sev = ws_res.cell(row=r_curr, column=3, value=sev)
        c_sev.alignment = Alignment(horizontal="center")
        c_sev.font = Font(name="Segoe UI", size=9, bold=True, color=fg)
        c_sev.fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
        ws_res.cell(row=r_curr, column=4, value=sanitize_excel_val(an.get("tag") or "—")).alignment = Alignment(horizontal="center")
        ws_res.cell(row=r_curr, column=5, value=sanitize_excel_val(an.get("title") or "—"))
        ws_res.cell(row=r_curr, column=6, value=sanitize_excel_val(an.get("message") or "—"))
        ws_res.cell(row=r_curr, column=7, value=sanitize_excel_val(an.get("norm_source") or "Spécification projet"))
        ws_res.cell(row=r_curr, column=8, value=sanitize_excel_val(an.get("recommendation") or "—"))
        prop = an.get("item_proposed")
        prop_str = f"{prop.get('description', '')} ({prop.get('quantity', 0)} {prop.get('unit', '')})" if prop else "—"
        ws_res.cell(row=r_curr, column=9, value=sanitize_excel_val(prop_str))
        ws_res.cell(row=r_curr, column=10, value=sanitize_excel_val(an.get("status") or "PROPOSED")).alignment = Alignment(horizontal="center")
        for ci in range(1, 11):
            cell_r = ws_res.cell(row=r_curr, column=ci)
            cell_r.border = b_thin
            if ci != 3:
                cell_r.font = f_reg
        r_curr += 1
    ws_res.freeze_panes = "A2"

    for ws_s in wb.worksheets:
        for col in ws_s.columns:
            max_l = max(len(str(c.value or "")) for c in col[:50])
            ws_s.column_dimensions[get_column_letter(col[0].column)].width = max(min(max_l + 3, 50), 12)
    ws_syn.column_dimensions["A"].width = 30

    wb.active = 0
    _neutralize_formulas(wb)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    wb.save(output_path)
    logger.info("[MASTER_EXCEL] Classeur maître 11 onglets généré : %s", output_path)
    return output_path
