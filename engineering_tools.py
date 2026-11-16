"""
DEERFLOW LITE — Engineering Tools v1.0
Outils de calcul technique Oil & Gas pour l'Agent Raisonneur.
Couverture : Conversions, Pertes de charge, Puissance pompe, Data sheets.
"""
import math
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
#  OUTIL 1 — Conversion d'Unités
# ═══════════════════════════════════════════════════════════

UNIT_TABLE = {
    # Pression
    "bar_to_psi":     lambda x: x * 14.5038,
    "psi_to_bar":     lambda x: x / 14.5038,
    "bar_to_kpa":     lambda x: x * 100,
    "kpa_to_bar":     lambda x: x / 100,
    "bar_to_mpa":     lambda x: x / 10,
    "mpa_to_bar":     lambda x: x * 10,
    "psi_to_kpa":     lambda x: x * 6.89476,
    "kpa_to_psi":     lambda x: x / 6.89476,
    "bar_to_mmhg":    lambda x: x * 750.062,
    "mmhg_to_bar":    lambda x: x / 750.062,
    "bar_to_mbar":    lambda x: x * 1000,
    "mbar_to_bar":    lambda x: x / 1000,
    # Débit volumique
    "m3h_to_gpm":     lambda x: x * 4.40287,
    "gpm_to_m3h":     lambda x: x / 4.40287,
    "m3h_to_ls":      lambda x: x / 3.6,
    "ls_to_m3h":      lambda x: x * 3.6,
    "m3h_to_bbld":    lambda x: x * 150.956,
    "bbld_to_m3h":    lambda x: x / 150.956,
    "m3h_to_m3s":     lambda x: x / 3600,
    "m3s_to_m3h":     lambda x: x * 3600,
    # Température
    "c_to_f":         lambda x: x * 9 / 5 + 32,
    "f_to_c":         lambda x: (x - 32) * 5 / 9,
    "c_to_k":         lambda x: x + 273.15,
    "k_to_c":         lambda x: x - 273.15,
    "f_to_k":         lambda x: (x - 32) * 5 / 9 + 273.15,
    "k_to_f":         lambda x: (x - 273.15) * 9 / 5 + 32,
    # Longueur
    "m_to_ft":        lambda x: x * 3.28084,
    "ft_to_m":        lambda x: x / 3.28084,
    "mm_to_in":       lambda x: x / 25.4,
    "in_to_mm":       lambda x: x * 25.4,
    # Masse
    "kg_to_lb":       lambda x: x * 2.20462,
    "lb_to_kg":       lambda x: x / 2.20462,
    "t_to_lb":        lambda x: x * 2204.62,
    # Puissance
    "kw_to_hp":       lambda x: x * 1.34102,
    "hp_to_kw":       lambda x: x / 1.34102,
    # Viscosité
    "cp_to_pas":      lambda x: x / 1000,
    "pas_to_cp":      lambda x: x * 1000,
}


def tool_convert_units(value: str, from_unit: str, to_unit: str) -> str:
    """
    Convertit une valeur d'une unité vers une autre.
    Exemple: value=100, from_unit=bar, to_unit=psi
    """
    try:
        val = float(value)
        key = f"{from_unit.lower().replace(' ', '').replace('/', '')}_to_{to_unit.lower().replace(' ', '').replace('/', '')}"
        
        if key in UNIT_TABLE:
            result = UNIT_TABLE[key](val)
            return (
                f"Conversion reussie :\n"
                f"  {val} {from_unit} = {result:.4f} {to_unit}\n"
                f"  (Formule: {from_unit} -> {to_unit})"
            )
        else:
            available = sorted(set(k.split("_to_")[0] for k in UNIT_TABLE))
            return (
                f"Conversion '{from_unit}' -> '{to_unit}' non supportee directement.\n"
                f"Unites disponibles comme source : {', '.join(available)}\n"
                f"Essayez de decomposer la conversion en deux etapes si necessaire."
            )
    except Exception as e:
        return f"Erreur de conversion : {e}"


# ═══════════════════════════════════════════════════════════
#  OUTIL 2 — Perte de Charge (Darcy-Weisbach)
# ═══════════════════════════════════════════════════════════

def tool_calculate_pressure_drop(
    flow_rate_m3h: str,
    pipe_diameter_mm: str,
    pipe_length_m: str,
    fluid_density_kg_m3: str,
    fluid_viscosity_cp: str,
    pipe_roughness_mm: str = "0.046"
) -> str:
    """
    Calcule la perte de charge en ligne selon Darcy-Weisbach.
    Inclut le calcul du régime d'écoulement (Reynolds) et du facteur de friction (Colebrook).
    """
    try:
        Q  = float(flow_rate_m3h) / 3600         # m³/s
        D  = float(pipe_diameter_mm) / 1000       # m
        L  = float(pipe_length_m)                 # m
        rho = float(fluid_density_kg_m3)          # kg/m³
        mu  = float(fluid_viscosity_cp) / 1000    # Pa·s
        eps = float(pipe_roughness_mm) / 1000     # m (rugosité acier = 0.046 mm par défaut)

        A = math.pi * D**2 / 4                    # Section [m²]
        V = Q / A                                  # Vitesse [m/s]
        Re = rho * V * D / mu                     # Nombre de Reynolds

        # Régime d'écoulement
        if Re < 2300:
            regime = "Laminaire"
            f = 64 / Re
        else:
            regime = "Turbulent"
            # Colebrook-White (itératif)
            f = 0.02
            for _ in range(50):
                f_new = 1 / (-2 * math.log10(eps / (3.7 * D) + 2.51 / (Re * math.sqrt(f))))**2
                if abs(f_new - f) < 1e-7:
                    break
                f = f_new

        # Perte de charge
        dP_pa  = f * (L / D) * (rho * V**2 / 2)  # Pascal
        dP_bar = dP_pa / 1e5
        dP_mwc = dP_pa / (rho * 9.81)             # mètres de colonne d'eau

        return (
            f"=== PERTE DE CHARGE --- Darcy-Weisbach ===\n\n"
            f"  Debit           : {flow_rate_m3h} m3/h\n"
            f"  Diametre        : {pipe_diameter_mm} mm\n"
            f"  Longueur        : {pipe_length_m} m\n"
            f"  Fluide          : rho={fluid_density_kg_m3} kg/m3, mu={fluid_viscosity_cp} cP\n\n"
            f"  Vitesse         : {V:.3f} m/s\n"
            f"  Reynolds (Re)   : {Re:.0f}\n"
            f"  Regime          : {regime}\n"
            f"  Facteur Darcy   : {f:.5f}\n\n"
            f"  dP (Pertes)     : {dP_bar:.4f} bar\n"
            f"                  = {dP_bar * 14.5038:.3f} psi\n"
            f"                  = {dP_mwc:.3f} m.c.e\n\n"
            f"  Note: Rugosite acier utilisee = {pipe_roughness_mm} mm (carbone/acier).\n"
            f"  Ajouter les pertes singulieres (coudes, vannes) via le coefficient K."
        )
    except Exception as e:
        return f"Erreur de calcul perte de charge : {e}"


# ═══════════════════════════════════════════════════════════
#  OUTIL 3 — Puissance et Point de Fonctionnement Pompe
# ═══════════════════════════════════════════════════════════

def tool_calculate_pump_power(
    flow_rate_m3h: str,
    total_head_m: str,
    fluid_density_kg_m3: str,
    pump_efficiency_pct: str,
    motor_efficiency_pct: str = "95"
) -> str:
    """
    Calcule la puissance hydraulique, absorbée et électrique d'une pompe centrifuge.
    """
    try:
        Q    = float(flow_rate_m3h) / 3600      # m³/s
        H    = float(total_head_m)               # m
        rho  = float(fluid_density_kg_m3)        # kg/m³
        eta_p = float(pump_efficiency_pct) / 100
        eta_m = float(motor_efficiency_pct) / 100
        g    = 9.81

        P_hyd   = rho * g * Q * H               # W — puissance hydraulique
        P_pump  = P_hyd / eta_p                 # W — puissance absorbée par la pompe
        P_motor = P_pump / eta_m                # W — puissance électrique absorbée

        # Conversion en kW et HP
        P_hyd_kw   = P_hyd / 1000
        P_pump_kw  = P_pump / 1000
        P_motor_kw = P_motor / 1000
        P_motor_hp = P_motor_kw * 1.34102

        # NPSH disponible (indicatif, vapeur d'eau à 20°C)
        # NPSH_a = (Pa - Pv) / (rho*g) + Hs
        # On ne peut pas le calculer sans données système — on avertit

        return (
            f"=== PUISSANCE POMPE CENTRIFUGE ===\n\n"
            f"  Debit              : {flow_rate_m3h} m3/h\n"
            f"  Hauteur manom.     : {total_head_m} m\n"
            f"  Densite fluide     : {fluid_density_kg_m3} kg/m3\n"
            f"  Rendement pompe    : {pump_efficiency_pct} %\n"
            f"  Rendement moteur   : {motor_efficiency_pct} %\n\n"
            f"  Puissance hydraulique   : {P_hyd_kw:.2f} kW\n"
            f"  Puissance arbre pompe   : {P_pump_kw:.2f} kW\n"
            f"  -----------------------------------------\n"
            f"  Puissance electrique    : {P_motor_kw:.2f} kW\n"
            f"                          = {P_motor_hp:.2f} HP\n\n"
            f"  [!] NPSH disponible : Non calcule (donnees systeme requises)\n"
            f"      Verifiez le NPSH requis sur la courbe constructeur.\n"
            f"  [!] Marge moteur recommandee : x1.15 a x1.25 -> "
            f"{P_motor_kw*1.15:.1f} a {P_motor_kw*1.25:.1f} kW installes."
        )
    except Exception as e:
        return f"Erreur de calcul puissance pompe : {e}"


# ═══════════════════════════════════════════════════════════
#  OUTIL 4 — Extraction de Data Sheet structurée
# ═══════════════════════════════════════════════════════════

def tool_extract_data_sheet(file_path: str, equipment_tag: str = "") -> str:
    """
    Extrait les paramètres clés d'une data sheet technique (PDF) :
    conditions de service, matériaux, dimensionnement, normes applicables.
    """
    try:
        import pdfplumber
        import re
        from pathlib import Path

        # Résolution du chemin
        path = Path(file_path)
        if not path.is_absolute():
            try:
                from config import DATA_DIR
                matches = list(Path(DATA_DIR).glob(f"**/{file_path}"))
                if matches:
                    path = matches[0]
                else:
                    return f"Fichier '{file_path}' non trouvé dans le dossier data/."
            except Exception:
                pass

        if not path.exists():
            return f"Fichier non trouvé : {file_path}"

        # Patterns de data sheet standard
        FIELD_PATTERNS = {
            "Fluide / Service":   r"(?:fluid|service|fluide)\s*[:\-]?\s*([^\n]{3,60})",
            "Débit":             r"(?:flow rate|debit|débit|flowrate)\s*[:\-]?\s*([^\n]{2,40})",
            "Pression (Design)": r"(?:design pressure|pression de design|pression design)\s*[:\-]?\s*([^\n]{2,30})",
            "Pression (Oper.)":  r"(?:operating pressure|pression operatoire|pression de service)\s*[:\-]?\s*([^\n]{2,30})",
            "Température (Des)": r"(?:design temp|temperature de design|design temperature)\s*[:\-]?\s*([^\n]{2,30})",
            "Température (Op)":  r"(?:operating temp|temperature de service|operating temperature)\s*[:\-]?\s*([^\n]{2,30})",
            "Matériau Corps":    r"(?:body material|materiau|material|matériau)\s*[:\-]?\s*([^\n]{3,40})",
            "Norme/Code":        r"(?:standard|code|norme)\s*[:\-]?\s*([^\n]{3,50})",
            "Classe tuyauterie": r"(?:piping class|classe|rating|class)\s*[:\-]?\s*([^\n]{2,20})",
            "Tag équipement":    r"(?:tag|tag no|equipment no|repere|repère)\s*[:\-]?\s*([A-Z]{1,3}-\d{3,5}[A-Z]?)",
        }

        full_text = ""
        tables_raw = []

        with pdfplumber.open(str(path)) as pdf:
            pages_count = len(pdf.pages)
            for page in pdf.pages:
                text = page.extract_text() or ""
                full_text += text + "\n"
                tables = page.extract_tables()
                for t in tables:
                    clean = [[str(c).strip() if c else "" for c in row] for row in t]
                    if any(any(row) for row in clean):
                        tables_raw.append(clean)

        # Filtrer par tag si spécifié
        if equipment_tag:
            if equipment_tag.upper() not in full_text.upper():
                return f"Tag '{equipment_tag}' non trouvé dans ce document."

        # Extraire les champs
        extracted = {}
        for field, pattern in FIELD_PATTERNS.items():
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                extracted[field] = m.group(1).strip()

        # Construire le rapport
        lines = [
            f"=== DATA SHEET — {path.name} ===\n",
            f"  Pages      : {pages_count}",
            f"  Tableaux   : {len(tables_raw)} détectés",
        ]
        if equipment_tag:
            lines.append(f"  Tag filtré : {equipment_tag}")

        lines.append("\n── Paramètres extraits ──")
        if extracted:
            for k, v in extracted.items():
                lines.append(f"  {k:<22}: {v}")
        else:
            lines.append("  Aucun paramètre standard détecté (structure PDF non conventionnelle).")

        if tables_raw:
            lines.append("\n── Aperçu tableau principal ──")
            t = tables_raw[0]
            for row in t[:6]:
                non_empty = [c for c in row if c]
                if non_empty:
                    lines.append("  | " + " | ".join(non_empty[:5]) + " |")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"tool_extract_data_sheet error: {e}")
        return f"Erreur d'extraction data sheet : {e}"


# ═══════════════════════════════════════════════════════════
#  OUTIL 5 — Dimensionnement tuyauterie (calculate_pipe_sizing)
# ═══════════════════════════════════════════════════════════

def tool_calculate_pipe_sizing(
    flow_rate_m3h: str,
    fluid_density_kg_m3: str,
    fluid_viscosity_cp: str,
    max_velocity_ms: str = "3.0",
    fluid_type: str = "liquid"
) -> str:
    """Determine le diametre nominal recommande pour une tuyauterie selon le debit et la velocite maximale."""
    try:
        Q   = float(flow_rate_m3h) / 3600
        rho = float(fluid_density_kg_m3)
        mu  = float(fluid_viscosity_cp) / 1000
        Vmax = float(max_velocity_ms)
        ftype = fluid_type.lower()

        # Vitesse recommandee par type de fluide
        vel_guides = {
            "liquid":  (0.5, 3.0, "Liquides generaux"),
            "gas":     (10.0, 25.0, "Gaz / Vapeur"),
            "slurry":  (1.5, 2.5, "Boues / Slurry"),
            "steam":   (20.0, 40.0, "Vapeur haute pression"),
        }
        guide = vel_guides.get(ftype, vel_guides["liquid"])
        V_rec_min, V_rec_max, label = guide
        V_design = min(Vmax, V_rec_max)

        # Diametre theorique
        import math
        D_theorique = math.sqrt(4 * Q / (math.pi * V_design)) * 1000  # mm

        # Table des DN normalises (ASME B36.10)
        DN_TABLE = [
            (15,21.3),(20,26.7),(25,33.4),(32,42.2),(40,48.3),
            (50,60.3),(65,73.0),(80,88.9),(100,114.3),(125,141.3),
            (150,168.3),(200,219.1),(250,273.1),(300,323.9),
            (350,355.6),(400,406.4),(450,457.2),(500,508.0),(600,609.6),
        ]
        # Choisir le DN immediatement superieur
        selected_dn, selected_od = next(
            ((dn, od) for dn, od in DN_TABLE if od >= D_theorique),
            DN_TABLE[-1]
        )

        # Recalculer la vitesse reelle avec le DN choisi
        D_real = selected_od / 1000
        A_real = math.pi * D_real**2 / 4
        V_real = Q / A_real
        Re = rho * V_real * D_real / mu

        # Avertissement vitesse
        warn = ""
        if V_real > V_rec_max:
            warn = f"\n  [!] ATTENTION: Vitesse {V_real:.2f} m/s > max recommande {V_rec_max} m/s pour {label}."
        elif V_real < V_rec_min:
            warn = f"\n  [!] ATTENTION: Vitesse {V_real:.2f} m/s < min recommande {V_rec_min} m/s (risque sedimentation)."

        return (
            f"=== DIMENSIONNEMENT TUYAUTERIE ===\n\n"
            f"  Debit             : {flow_rate_m3h} m3/h\n"
            f"  Type fluide       : {label}\n"
            f"  Velocite max saisie: {Vmax} m/s\n\n"
            f"  Diametre theorique : {D_theorique:.1f} mm\n"
            f"  DN recommande      : DN{selected_dn} (OD = {selected_od} mm)\n"
            f"  Velocite reelle    : {V_real:.2f} m/s\n"
            f"  Reynolds (Re)      : {Re:.0f}\n"
            f"  (Regime: {'Laminaire' if Re < 2300 else 'Turbulent'})"
            f"{warn}"
        )
    except Exception as e:
        return f"Erreur dimensionnement tuyauterie : {e}"


# ═══════════════════════════════════════════════════════════
#  OUTIL 6 — Classe de tuyauterie (find_piping_class)
# ═══════════════════════════════════════════════════════════

# Base de donnees simplifiee des classes de tuyauterie (ASME B16.5)
PIPING_CLASS_DB = [
    {"class": "150#",  "max_bar": 19.6,  "max_temp_c": 454, "services": ["water","steam","air","gas","oil","HC"]},
    {"class": "300#",  "max_bar": 51.1,  "max_temp_c": 454, "services": ["water","steam","gas","oil","HC","acid"]},
    {"class": "600#",  "max_bar": 102.1, "max_temp_c": 454, "services": ["gas","oil","HC","acid","high_pressure"]},
    {"class": "900#",  "max_bar": 153.2, "max_temp_c": 454, "services": ["gas","HC","high_pressure"]},
    {"class": "1500#", "max_bar": 255.3, "max_temp_c": 454, "services": ["gas","HC","high_pressure","wellhead"]},
    {"class": "2500#", "max_bar": 425.5, "max_temp_c": 454, "services": ["wellhead","very_high_pressure"]},
]

MATERIAL_GUIDE = {
    "carbon_steel":    {"max_temp_c": 400, "services": ["water","steam","air","gas","oil","HC"], "spec": "ASTM A106 Gr.B / API 5L"},
    "stainless_316":   {"max_temp_c": 600, "services": ["acid","brine","water","HC"], "spec": "ASTM A312 TP316L"},
    "stainless_304":   {"max_temp_c": 550, "services": ["water","steam","HC"], "spec": "ASTM A312 TP304"},
    "duplex_2205":     {"max_temp_c": 300, "services": ["acid","brine","seawater","H2S"], "spec": "ASTM A790 S31803"},
    "chrome_moly":     {"max_temp_c": 600, "services": ["steam","high_temp","HC"], "spec": "ASTM A335 P11/P22"},
    "inconel_625":     {"max_temp_c": 980, "services": ["very_high_temp","acid","H2S"], "spec": "ASTM B444"},
}

def tool_find_piping_class(
    design_pressure_bar: str,
    design_temp_c: str,
    fluid_service: str = "HC"
) -> str:
    """Identifie la classe de tuyauterie ASME B16.5 et le materiau recommande selon les conditions de service."""
    try:
        P = float(design_pressure_bar)
        T = float(design_temp_c)
        service = fluid_service.lower().replace(" ", "_")

        # Trouver la classe minimale adequate
        adequate = [c for c in PIPING_CLASS_DB if c["max_bar"] >= P and c["max_temp_c"] >= T]
        if not adequate:
            return f"Aucune classe standard ASME B16.5 pour P={P} bar / T={T}C. Consulter un specialiste ou utiliser ASME B16.47."

        selected = adequate[0]

        # Materiau recommande
        mat_recs = [
            (mat, info) for mat, info in MATERIAL_GUIDE.items()
            if info["max_temp_c"] >= T and any(s in service for s in info["services"])
        ]
        mat_lines = "\n".join(
            f"    - {mat.replace('_',' ').title()}: {info['spec']}"
            for mat, info in mat_recs[:3]
        ) or "    - Consulter un metallurgiste pour ce service specifique."

        # Joints recommandes
        if T > 300:
            gasket = "Spirale metallique (SS + graphite) — API 601"
        elif "acid" in service or "H2S" in service:
            gasket = "PTFE plein ou spirale SS/PTFE"
        else:
            gasket = "Spirale metallique ou RTJ pour haute pression"

        return (
            f"=== CLASSE DE TUYAUTERIE ASME B16.5 ===\n\n"
            f"  Pression design  : {P} bar\n"
            f"  Temperature      : {T} C\n"
            f"  Service          : {fluid_service}\n\n"
            f"  Classe recommandee : {selected['class']}\n"
            f"  (Capacite max : {selected['max_bar']} bar a temperature ambiante)\n\n"
            f"  Materiaux recommandes :\n{mat_lines}\n\n"
            f"  Joint d'etancheite : {gasket}\n\n"
            f"  Normes applicables :\n"
            f"    - ASME B16.5 (brides et raccords DN15-DN600)\n"
            f"    - ASME B16.47 (brides DN650+)\n"
            f"    - API 6A (equipements de tete de puits)"
        )
    except Exception as e:
        return f"Erreur identification classe tuyauterie : {e}"


# ═══════════════════════════════════════════════════════════
#  OUTIL 7 — Verification conformite norme (check_norm_compliance)
# ═══════════════════════════════════════════════════════════

NORM_REQUIREMENTS = {
    "api_610": {
        "name": "API 610 - Pompes centrifuges",
        "checks": [
            ("Vitesse specifique Ns", "Ns doit etre dans la plage 400-3000 tr/min (US units)"),
            ("NPSH requis", "NPSHr doit avoir une marge de 0.6m min par rapport au NPSHd"),
            ("Vibrations", "Niveaux de vibration < 3.0 mm/s RMS en service"),
            ("Paliers", "Duree de vie des paliers L10 >= 25000 heures"),
            ("Garniture", "Double garniture mecanique recommandee pour HCs"),
            ("Materiau", "Acier carbone pour T < 260C, acier allie pour T 260-400C"),
        ]
    },
    "api_6d": {
        "name": "API 6D - Vannes de pipeline",
        "checks": [
            ("Pression de test", "Test hydrostatique corps : 1.5x pression nominale"),
            ("Test etancheite siege", "Test a 1.1x pression nominale, fuite zero toleree"),
            ("Materiau tiges", "Tige en acier inoxydable ou traitee contre la corrosion"),
            ("Protection cathodique", "Requise pour vannes enterrees"),
            ("Marquage", "Marquage permanent : DN, classe, materiau, direction ecoulement"),
        ]
    },
    "api_520": {
        "name": "API 520/521 - Soupapes de securite",
        "checks": [
            ("Pression de tarage", "Pression de tarage <= pression de design de l'equipement protege"),
            ("Surpression accidentelle", "Surpression max autorisee : 10% au-dessus pression design"),
            ("Debit de calcul", "Debit base sur le scenario le plus penalisant (incendie, defaillance reg.)"),
            ("Materiau siege", "Inox ou materiau resistant a la corrosion du fluide"),
            ("Back-pressure", "Back-pressure < 10% pression de tarage pour soupapes conventionnelles"),
        ]
    },
    "iec_61511": {
        "name": "IEC 61511 - Systemes instrumantes de securite (SIS)",
        "checks": [
            ("SIL requis", "Determination du SIL requis par HAZOP / SIL Determination"),
            ("PFD moyen", "SIL1: 0.1>PFD>0.01, SIL2: 0.01>PFD>0.001, SIL3: 0.001>PFD>0.0001"),
            ("Test periodique", "Interval de test base sur le PFD cible et le taux de defaillance"),
            ("Independence", "Independance du SIS par rapport au systeme de controle (DCS)"),
            ("Architecture", "Architecture redondante recommandee pour SIL2+ (1oo2, 2oo3)"),
        ]
    },
    "asme_viii": {
        "name": "ASME VIII Div.1 - Appareils a pression",
        "checks": [
            ("Pression de calcul", "Pression de calcul = pression de service + marge (min 10%)"),
            ("Epaisseur minimale", "e = (P x R) / (S x E - 0.6 x P) + CA (corrosion allowance)"),
            ("Test hydrostatique", "Test eau a 1.3x pression de calcul x coefficient temperature"),
            ("Corrosion allowance", "CA minimum : 1.5mm general, 3mm pour services corrosifs"),
            ("Certification", "Marquage U obligatoire, calculs par ingenieur ASME certifie"),
        ]
    },
}

def tool_check_norm_compliance(norm_code: str, context: str = "") -> str:
    """Liste les exigences cles d'une norme Oil & Gas et verifie les points critiques."""
    try:
        key = norm_code.lower().replace(" ","_").replace("-","_")
        
        # Recherche flexible
        found = None
        for k in NORM_REQUIREMENTS:
            if k in key or key in k:
                found = k
                break
        
        if not found:
            available = ", ".join(NORM_REQUIREMENTS.keys())
            return (
                f"Norme '{norm_code}' non trouvee dans la base locale.\n"
                f"Normes disponibles : {available}\n"
                f"Pour les autres normes, utilisez search_documents pour rechercher dans la base documentaire."
            )
        
        norm = NORM_REQUIREMENTS[found]
        lines = [
            f"=== CONFORMITE NORME : {norm['name']} ===\n",
            f"  Points de verification obligatoires :\n"
        ]
        for i, (titre, detail) in enumerate(norm["checks"], 1):
            lines.append(f"  {i}. {titre}")
            lines.append(f"     -> {detail}")
        
        if context:
            lines.append(f"\n  Contexte fourni : {context[:200]}")
            lines.append("  -> Verifiez les points ci-dessus par rapport a ce contexte.")
        
        lines.append(f"\n  [!] Ces exigences sont indicatives. Consulter le document officiel {norm_code} pour la version en vigueur.")
        return "\n".join(lines)
    except Exception as e:
        return f"Erreur verification norme : {e}"


# ═══════════════════════════════════════════════════════════
#  OUTIL 8 — Extraction liste d'instruments (extract_instrument_list)
# ═══════════════════════════════════════════════════════════

def tool_extract_instrument_list(file_path: str) -> str:
    """Extrait la liste d'instruments depuis un PDF (Instrument Index, P&ID, liste d'instruments)."""
    try:
        import pdfplumber, re
        from pathlib import Path

        path = Path(file_path)
        if not path.is_absolute():
            try:
                from config import DATA_DIR
                matches = list(Path(DATA_DIR).glob(f"**/{file_path}"))
                if matches:
                    path = matches[0]
                else:
                    return f"Fichier '{file_path}' non trouve dans data/."
            except Exception:
                pass

        if not path.exists():
            return f"Fichier non trouve : {file_path}"

        TAG_PATTERN = re.compile(
            r"\b([A-Z]{1,3}[A-Z]?T?-\d{3,5}[A-Z]?)\b"
        )
        INSTRUMENT_TYPES = {
            "PT": "Transmetteur de Pression",
            "PIC": "Controleur Indicateur de Pression",
            "PSV": "Soupape de Surete Pression",
            "PSH": "Pressostat Haut",
            "PSL": "Pressostat Bas",
            "FT": "Transmetteur de Debit",
            "FIC": "Controleur Indicateur de Debit",
            "FCV": "Vanne de Regulation Debit",
            "LT": "Transmetteur de Niveau",
            "LIC": "Controleur Indicateur de Niveau",
            "LCV": "Vanne de Regulation Niveau",
            "LSH": "Interrupteur de Niveau Haut",
            "LSL": "Interrupteur de Niveau Bas",
            "TT": "Transmetteur de Temperature",
            "TIC": "Controleur Indicateur de Temperature",
            "TSH": "Thermostat Haut",
            "XV": "Vanne d'Arret (On/Off)",
            "SDV": "Vanne d'Arret d'Urgence (ESD)",
            "ZT": "Transmetteur de Position",
            "AT": "Analyseur / Transmetteur Analytique",
        }

        full_text = ""
        all_tables = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"
                for t in page.extract_tables():
                    clean = [[str(c).strip() if c else "" for c in row] for row in t]
                    if any(any(r) for r in clean):
                        all_tables.append(clean)

        # Extraire tous les tags
        tags_found = list(set(TAG_PATTERN.findall(full_text)))

        # Classifier par type
        classified = {}
        for tag in sorted(tags_found):
            prefix = re.match(r"([A-Z]+)", tag)
            if prefix:
                p = prefix.group(1)
                type_desc = INSTRUMENT_TYPES.get(p, f"Instrument type {p}")
                classified.setdefault(type_desc, []).append(tag)

        lines = [
            f"=== LISTE D'INSTRUMENTS --- {path.name} ===\n",
            f"  Total tags detectes : {len(tags_found)}\n",
            f"  Tableaux detectes   : {len(all_tables)}\n",
            "--- Instruments par type ---"
        ]

        if classified:
            for type_desc, tags in sorted(classified.items()):
                lines.append(f"\n  [{type_desc}] ({len(tags)} tags)")
                lines.append(f"    {', '.join(tags)}")
        else:
            lines.append("  Aucun tag d'instrument detecte selon les patterns standards.")

        if all_tables:
            lines.append("\n--- Apercu du premier tableau ---")
            for row in all_tables[0][:8]:
                non_empty = [c for c in row if c]
                if non_empty:
                    lines.append("  | " + " | ".join(non_empty[:5]) + " |")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"tool_extract_instrument_list error: {e}")
        return f"Erreur extraction liste instruments : {e}"


# ═══════════════════════════════════════════════════════════
#  Registre des outils pour l'Agent
# ═══════════════════════════════════════════════════════════

ENGINEERING_TOOLS = {
    "convert_units": {
        "fn": tool_convert_units,
        "description": "Convertit une valeur entre deux unites techniques. Supporte : pression (bar, psi, kPa, MPa), debit (m3/h, gpm, L/s, bbl/d), temperature (C, F, K), longueur (m, ft, mm, in), masse (kg, lb), puissance (kW, HP). Parametres: value, from_unit, to_unit.",
        "params": ["value", "from_unit", "to_unit"],
    },
    "calculate_pressure_drop": {
        "fn": tool_calculate_pressure_drop,
        "description": "Calcule la perte de charge lineaire (Darcy-Weisbach) avec Reynolds et Colebrook-White. Resultat en bar, psi, m.c.e. Parametres: flow_rate_m3h, pipe_diameter_mm, pipe_length_m, fluid_density_kg_m3, fluid_viscosity_cp, pipe_roughness_mm.",
        "params": ["flow_rate_m3h", "pipe_diameter_mm", "pipe_length_m", "fluid_density_kg_m3", "fluid_viscosity_cp", "pipe_roughness_mm"],
    },
    "calculate_pump_power": {
        "fn": tool_calculate_pump_power,
        "description": "Calcule la puissance hydraulique, absorbee et electrique d'une pompe centrifuge. Resultat en kW et HP avec marge moteur. Parametres: flow_rate_m3h, total_head_m, fluid_density_kg_m3, pump_efficiency_pct, motor_efficiency_pct.",
        "params": ["flow_rate_m3h", "total_head_m", "fluid_density_kg_m3", "pump_efficiency_pct", "motor_efficiency_pct"],
    },
    "extract_data_sheet": {
        "fn": tool_extract_data_sheet,
        "description": "Extrait les parametres cles d'une data sheet PDF : conditions operatoires, fluide, materiaux, normes, classe. Parametres: file_path, equipment_tag (optionnel).",
        "params": ["file_path", "equipment_tag"],
    },
    "calculate_pipe_sizing": {
        "fn": tool_calculate_pipe_sizing,
        "description": "Calcule le DN recommande (ASME B36.10) pour une tuyauterie selon le debit, la densite, la viscosite et le type de fluide (liquid, gas, steam, slurry). Parametres: flow_rate_m3h, fluid_density_kg_m3, fluid_viscosity_cp, max_velocity_ms, fluid_type.",
        "params": ["flow_rate_m3h", "fluid_density_kg_m3", "fluid_viscosity_cp", "max_velocity_ms", "fluid_type"],
    },
    "find_piping_class": {
        "fn": tool_find_piping_class,
        "description": "Identifie la classe de tuyauterie ASME B16.5 (150# a 2500#) et les materiaux recommandes selon la pression design, la temperature et le service (HC, acid, steam, water, H2S...). Parametres: design_pressure_bar, design_temp_c, fluid_service.",
        "params": ["design_pressure_bar", "design_temp_c", "fluid_service"],
    },
    "check_norm_compliance": {
        "fn": tool_check_norm_compliance,
        "description": "Liste les exigences cles d'une norme Oil & Gas : API 610 (pompes), API 6D (vannes), API 520/521 (soupapes), IEC 61511 (SIS/SIL), ASME VIII (appareils a pression). Parametres: norm_code (ex: api_610), context (optionnel).",
        "params": ["norm_code", "context"],
    },
    "extract_instrument_list": {
        "fn": tool_extract_instrument_list,
        "description": "Extrait et classe tous les tags d'instruments (PT, FT, LT, TT, XV, SDV...) depuis un PDF (P&ID, Instrument Index). Retourne la liste groupee par type. Parametre: file_path.",
        "params": ["file_path"],
    },
}


# ═══════════════════════════════════════════════════════════
#  OUTIL 9 — Calcul soupape de securite (API 520)
# ═══════════════════════════════════════════════════════════

def tool_calculate_relief_valve(
    set_pressure_bar: str,
    back_pressure_bar: str,
    fluid_type: str,
    flow_rate_kg_h: str,
    molecular_weight: str = "44",
    temperature_c: str = "100",
    cp_cv_ratio: str = "1.3"
) -> str:
    """Calcule l'orifice requis pour une soupape de securite selon API 520."""
    try:
        import math
        P1 = float(set_pressure_bar) * 1.10
        P2 = float(back_pressure_bar)
        W  = float(flow_rate_kg_h)
        MW = float(molecular_weight)
        T  = float(temperature_c) + 273.15
        k  = float(cp_cv_ratio)
        Kd = 0.975
        ftype = fluid_type.lower()

        if ftype in ("gas", "vapor", "vapeur", "gaz"):
            r_crit = (2 / (k + 1)) ** (k / (k - 1))
            ratio = P2 / P1
            flow_regime = "Critique" if ratio <= r_crit else "Subcritique"
            if ratio <= r_crit:
                C = 520 * math.sqrt(k * (2 / (k + 1)) ** ((k + 1) / (k - 1)))
                Z = 1.0
                A_cm2 = W / (C * Kd * (P1 * 14.5038) * math.sqrt(MW / (T * Z)))
            else:
                F2 = math.sqrt((k / (k - 1)) * (ratio ** (2/k) - ratio ** ((k+1)/k)))
                A_cm2 = W / (735 * F2 * Kd * P1 * math.sqrt(MW / T))
        elif ftype in ("liquid", "liquide"):
            flow_regime = "Liquide"
            Q_ls = W / (1000 * 3.6)
            A_cm2 = Q_ls / (Kd * 0.62 * 11.78 * math.sqrt((P1 - P2) * 10))
        elif ftype in ("steam", "vapeur_eau"):
            flow_regime = "Vapeur d'eau"
            A_cm2 = W / (51.45 * Kd * 1.0 * P1 * 14.5038)
        else:
            return f"Type de fluide '{fluid_type}' non reconnu. Utiliser: gas, liquid, steam."

        A_mm2 = A_cm2 * 100
        API_ORIFICES = [
            ("D",71),("E",126),("F",198),("G",325),("H",506),
            ("J",830),("K",1186),("L",1841),("M",2323),("N",2800),
            ("P",4116),("Q",7129),("R",10323),("T",17355),
        ]
        selected = next(((l, a) for l, a in API_ORIFICES if a >= A_mm2), ("T+", A_mm2))

        return (
            f"=== SOUPAPE DE SECURITE --- API 520 ===\n\n"
            f"  Pression tarage   : {set_pressure_bar} bar\n"
            f"  Back-pressure     : {back_pressure_bar} bar\n"
            f"  Fluide            : {fluid_type} (MW={molecular_weight}, T={temperature_c} C)\n"
            f"  Debit a evacuer   : {flow_rate_kg_h} kg/h\n\n"
            f"  P relieving (P1)  : {P1:.2f} bar (set + 10%)\n"
            f"  Regime            : {flow_regime}\n\n"
            f"  Orifice calcule   : {A_mm2:.1f} mm2\n"
            f"  Lettre API        : {selected[0]} ({selected[1]} mm2)\n\n"
            f"  [!] Verifier le scenario penalisant (API 521).\n"
            f"  [!] Recalcul detaille requis avec donnees exactes (Z, Ksh)."
        )
    except Exception as e:
        return f"Erreur calcul soupape : {e}"


# ═══════════════════════════════════════════════════════════
#  OUTIL 10 — Analyse boucle de regulation
# ═══════════════════════════════════════════════════════════

LOOP_TYPES = {
    "F": {"name": "Debit (Flow)", "sensor": "FT", "ctrl": "FIC", "valve": "FCV", "unit": "m3/h", "action": "Direct", "pid": "P=0.5-2.0, I=0.1-1.0 min, D=rare"},
    "P": {"name": "Pression", "sensor": "PT", "ctrl": "PIC", "valve": "PCV", "unit": "bar", "action": "Direct ou Reverse", "pid": "P=2-10, I=0.5-5 min"},
    "L": {"name": "Niveau (Level)", "sensor": "LT", "ctrl": "LIC", "valve": "LCV", "unit": "% ou mm", "action": "Direct", "pid": "P=1-5, I=2-20 min"},
    "T": {"name": "Temperature", "sensor": "TT", "ctrl": "TIC", "valve": "TCV", "unit": "C", "action": "Reverse (chauf.)/Direct (refroid.)", "pid": "P=5-20, I=5-30 min, D=0.5-5 min"},
    "A": {"name": "Analytique (pH, O2...)", "sensor": "AT", "ctrl": "AIC", "valve": "Vanne dosage", "unit": "ppm ou pH", "action": "Variable", "pid": "P=1-10, I=5-60 min"},
}

def tool_analyze_control_loop(loop_tag: str, file_path: str = "", context: str = "") -> str:
    """Analyse une boucle de regulation (FIC-101, PIC-202) : instruments, PID, alarmes, logique."""
    try:
        import re
        tag_upper = loop_tag.upper().strip()
        m = re.match(r"([A-Z]+)(?:IC|C|CV|T|E)?-(\d+)", tag_upper)
        if not m:
            return f"Tag '{loop_tag}' non reconnu. Format: FIC-101, PIC-202, LIC-303..."

        vl = m.group(1)[0]
        num = m.group(2)
        info = LOOP_TYPES.get(vl, {
            "name": f"Variable {vl}", "sensor": f"{vl}T", "ctrl": f"{vl}IC",
            "valve": f"{vl}CV", "unit": "?", "action": "A determiner", "pid": "Consulter design basis"
        })

        pdf_ctx = ""
        if file_path:
            try:
                import pdfplumber
                from pathlib import Path
                from config import DATA_DIR
                path = Path(file_path)
                if not path.is_absolute():
                    matches = list(Path(DATA_DIR).glob(f"**/{file_path}"))
                    if matches:
                        path = matches[0]
                if path.exists():
                    with pdfplumber.open(str(path)) as pdf:
                        for page in pdf.pages:
                            text = page.extract_text() or ""
                            if tag_upper in text:
                                lines = [l for l in text.split("\n") if tag_upper in l]
                                pdf_ctx = "\n  ".join(lines[:5])
                                break
            except Exception as pe:
                pdf_ctx = f"(PDF: {pe})"

        return (
            f"=== BOUCLE DE REGULATION : {tag_upper} ===\n\n"
            f"  Variable   : {info['name']} ({info['unit']})\n\n"
            f"  Instruments de la boucle :\n"
            f"    Transmetteur  : {vl}T-{num}  ({info['sensor']})\n"
            f"    Regulateur    : {vl}IC-{num}  (PID - action {info['action']})\n"
            f"    Vanne         : {vl}CV-{num}  ({info['valve']})\n\n"
            f"  Alarmes typiques :\n"
            f"    {vl}AH-{num}  (Alarme Haute)\n"
            f"    {vl}AL-{num}  (Alarme Basse)\n"
            f"    {vl}AHH-{num} (Arret Urgence HH -> ESD)\n\n"
            f"  Parametres PID typiques : {info['pid']}\n"
            f"  Position securite vanne : Voir P&ID (FC=Ferme, FO=Ouvert sur defaut)\n"
            + (f"\n  Extrait PDF ({file_path}) :\n  {pdf_ctx}" if pdf_ctx else "")
            + (f"\n  Contexte : {context[:200]}" if context else "")
            + "\n\n  [!] Verifier la Cause & Effect Matrix pour les actions ESD."
        )
    except Exception as e:
        return f"Erreur analyse boucle : {e}"


# ═══════════════════════════════════════════════════════════
#  OUTIL 11 — Analyse HAZOP
# ═══════════════════════════════════════════════════════════

HAZOP_DB = {
    "no_flow":           [("Cause","Vanne fermee, pompe en panne, bouchage"),("Consequence","Arret procede, surchauffe echangeur"),("Protection","Alarme FAL, detection position vanne"),("Action","Verifier FT et alarme FAL. Installer by-pass si critique.")],
    "more_flow":         [("Cause","FCV defaillante (full open), debit pompe excessif"),("Consequence","Debordement aval, surpression, erosion"),("Protection","Alarme FAH, limiteur debit, PSV aval"),("Action","Verifier FCV et FIC. Valider range FT.")],
    "less_flow":         [("Cause","Filtre encrase, cavitation pompe, vanne partielle"),("Consequence","Sous-alimentation, surchauffe pompe"),("Protection","Alarme FAL, dP filtre, NPSH survey"),("Action","Nettoyer filtres. Verifier NPSH.")],
    "more_pressure":     [("Cause","Blocage aval, fermeture soudaine, chaleur externe"),("Consequence","Rupture tuyauterie, fuite, explosion"),("Protection","PSV, alarme PAH, ESD"),("Action","Confirmer debit PSV (API 521). Verifier temps ESD.")],
    "less_pressure":     [("Cause","Vide partiel, perte de charge, ecoulement inverse"),("Consequence","Implosion, rentree air, ebullition"),("Protection","Anti-retour, rupture disque vacuum, alarme PAL"),("Action","Verifier vacuum rating. Installer clapet anti-retour.")],
    "more_temperature":  [("Cause","Perte refroidissement, reaction exothermique"),("Consequence","Degradation fluide, surpression vapeur, incendie"),("Protection","Alarme TAH, arret TAHH, monitoring CW"),("Action","Verifier systeme refroidissement. Calculer P vapeur au TAHH.")],
    "less_temperature":  [("Cause","Perte chauffage, basse temperature ambiante"),("Consequence","Solidification, fragilisation acier, bouchage"),("Protection","Alarme TAL, heat tracing, isolation thermique"),("Action","Verifier heat tracing. Materiaux basse temperature.")],
    "reverse_flow":      [("Cause","Arret pompe, defaillance clapet anti-retour"),("Consequence","Contamination source, coup de belier"),("Protection","Clapet anti-retour, SDV avec interlock"),("Action","Verifier clapet. Analyser coup de belier.")],
    "more_level":        [("Cause","Vanne sortie fermee, debit entree excessif"),("Consequence","Debordement, entrainement liquide compresseur"),("Protection","Alarme LAH, arret LAHH, LCV sur sortie"),("Action","Verifier LCV. LAHH independant DCS (SIS).")],
    "less_level":        [("Cause","Vide bac, fuite, pompe sans alimentation"),("Consequence","Cavitation pompe, perte garde hydraulique"),("Protection","Alarme LAL, arret LALL, niveau minimum"),("Action","Verifier interlock LALL-pompe.")],
}

GUIDE_DEFS = {
    "no": "Absence totale du parametre",
    "more": "Augmentation au-dela de la valeur normale",
    "less": "Diminution en-dessous de la valeur normale",
    "reverse": "Inversion du sens ou de la direction",
    "other_than": "Presence d'un composant ou etat non prevu",
}

def tool_check_hazop_deviation(parameter: str, guide_word: str, node_description: str = "") -> str:
    """Analyse HAZOP : causes, consequences, protections pour une deviation (MORE FLOW, NO PRESSURE, etc.)."""
    try:
        param_map = {"flow":"flow","debit":"flow","pressure":"pressure","pression":"pressure",
                     "temperature":"temperature","temp":"temperature","level":"level","niveau":"level"}
        gw_map = {"no":"no","aucun":"no","zero":"no","more":"more","plus":"more","high":"more",
                  "haut":"more","less":"less","moins":"less","low":"less","bas":"less",
                  "reverse":"reverse","inverse":"reverse","retour":"reverse"}

        p = next((v for k,v in param_map.items() if k in parameter.lower()), "flow")
        g = next((v for k,v in gw_map.items() if k in guide_word.lower()), "more")
        key = f"{g}_{p}"
        data = HAZOP_DB.get(key)

        gw_def = GUIDE_DEFS.get(g, guide_word)
        lines = [
            f"=== ANALYSE HAZOP ===\n",
            f"  Noeud        : {node_description or 'Non specifie'}",
            f"  Deviation    : {guide_word.upper()} {parameter.upper()}",
            f"  Definition   : {gw_def}\n",
        ]
        if data:
            for label, content in data:
                lines.append(f"  {label:<14}: {content}")
        else:
            lines.append(f"  Deviation '{key}' non trouvee dans la base HAZOP.")
            lines.append(f"  Disponibles: no/more/less/reverse + flow/pressure/temperature/level")
            lines.append(f"  Utilisez search_documents pour chercher dans vos etudes HAZOP.")

        lines += [
            f"\n  Recommandations generales :",
            f"  1. Independance SIS/DCS (IEC 61511)",
            f"  2. SIL requis par HAZOP/SIL determination",
            f"  3. Documenter dans le HAZOP Action Register (HAR)",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Erreur analyse HAZOP : {e}"


# Mise a jour du registre avec les outils avances
ENGINEERING_TOOLS.update({
    "calculate_relief_valve": {
        "fn": tool_calculate_relief_valve,
        "description": "Calcule l'orifice requis pour une soupape de securite selon API 520 (gaz critique/subcritique, liquide, vapeur). Donne la lettre d'orifice API (D a T). Parametres: set_pressure_bar, back_pressure_bar, fluid_type, flow_rate_kg_h, molecular_weight, temperature_c, cp_cv_ratio.",
        "params": ["set_pressure_bar", "back_pressure_bar", "fluid_type", "flow_rate_kg_h", "molecular_weight", "temperature_c", "cp_cv_ratio"],
    },
    "analyze_control_loop": {
        "fn": tool_analyze_control_loop,
        "description": "Analyse une boucle de regulation (FIC-101, PIC-202, LIC-303, TIC-404) : identifie transmetteur, regulateur, vanne, alarmes, parametres PID typiques et logique d'action. Peut extraire depuis un PDF. Parametres: loop_tag, file_path (optionnel), context (optionnel).",
        "params": ["loop_tag", "file_path", "context"],
    },
    "check_hazop_deviation": {
        "fn": tool_check_hazop_deviation,
        "description": "Analyse HAZOP d'une deviation procede : causes, consequences, protections, actions. Mots-guides: no/more/less/reverse. Parametres: parameter (flow/pressure/temperature/level), guide_word, node_description (optionnel).",
        "params": ["parameter", "guide_word", "node_description"],
    },
})

# ═══════════════════════════════════════════════════════════
#  OUTILS V3 — Graph Actif, Audit et SCADA
# ═══════════════════════════════════════════════════════════

def tool_update_knowledge_graph(tag_a: str, tag_b: str, relation: str, source: str) -> str:
    """Insère ou met à jour une connexion entre deux équipements dans Neo4j (GraphRAG actif)."""
    try:
        from knowledge_graph import get_neo4j_kg
        kg = get_neo4j_kg()
        if not kg.disponible():
            return "Neo4j n'est pas disponible pour la mise à jour."
        
        success = kg.ajouter_connexion(tag_a, tag_b, relation, source)
        if success:
            return f"Connexion {tag_a} -[{relation}]-> {tag_b} ajoutée avec succès au Knowledge Graph."
        else:
            return "Échec de l'ajout de la connexion au graphe."
    except Exception as e:
        return f"Erreur lors de la mise à jour du graphe : {e}"

def tool_cross_check_documents(tag: str) -> str:
    """Audite un équipement en croisant les données BM25 (Data Sheets) et Neo4j (P&ID) pour trouver des incohérences."""
    try:
        from retriever import get_retriever
        from knowledge_graph import get_neo4j_kg
        
        kg = get_neo4j_kg()
        kg_info = kg.chercher_equipement(tag) if kg.disponible() else {}
        
        retriever = get_retriever()
        docs = retriever.retrieve(f"{tag} pression temperature")
        
        lines = [f"=== AUDIT DOCUMENTAIRE CROISÉ ({tag}) ==="]
        lines.append(f"  > Données P&ID / GraphRAG :")
        if kg_info:
            lines.append(f"    Pressions: {', '.join(kg_info.get('pressions', []))}")
            lines.append(f"    Normes: {', '.join(kg_info.get('normes', []))}")
        else:
            lines.append("    Aucune donnée GraphRAG trouvée.")
            
        lines.append(f"  > Données Textuelles (Data Sheets, Manuels) :")
        for d in docs[:2]:
            lines.append(f"    [Source: {d.source}] : {d.text[:150]}...")
            
        lines.append("\n  Recommandation : Analysez ces extraits pour identifier d'éventuelles contradictions sur la pression de design ou le dimensionnement.")
        return "\n".join(lines)
    except Exception as e:
        return f"Erreur d'audit croisé : {e}"

ENGINEERING_TOOLS.update({
    "update_knowledge_graph": {
        "fn": tool_update_knowledge_graph,
        "description": "Ajoute ou met à jour une connexion (CONNECTE_A, ALIMENTE, etc.) entre deux équipements directement dans la base de connaissances. Paramètres: tag_a, tag_b, relation, source.",
        "params": ["tag_a", "tag_b", "relation", "source"],
    },
    "cross_check_documents": {
        "fn": tool_cross_check_documents,
        "description": "Audite un équipement en croisant les données graph (P&ID) et texte (Data sheets) pour détecter des incohérences. Paramètre: tag.",
        "params": ["tag"],
    },
})

# ═══════════════════════════════════════════════════════════
#  OUTILS V4 — Rapport, Excel
# ═══════════════════════════════════════════════════════════

def tool_generate_equipment_report(tag: str, format: str = "text") -> str:
    """Génère un rapport technique complet sur un équipement (croise KG, Data Sheets)."""
    try:
        from report_agent import generate_equipment_report
        return generate_equipment_report(tag, output_format=format)
    except Exception as e:
        return f"Erreur génération rapport : {e}"


def tool_import_equipment_list(file_path: str) -> str:
    """
    Importe une liste d'équipements depuis un fichier Excel (.xlsx) ou CSV.
    Colonnes attendues : tag, type, description, pression, temperature, norme.
    """
    try:
        from pathlib import Path
        path = Path(file_path)
        if not path.is_absolute():
            try:
                from config import DATA_DIR
                matches = list(Path(DATA_DIR).glob(f"**/{file_path}"))
                if matches:
                    path = matches[0]
                else:
                    return f"Fichier '{file_path}' non trouvé dans le dossier data/."
            except Exception:
                pass
        
        if not path.exists():
            return f"Fichier non trouvé : {file_path}"
        
        suffix = path.suffix.lower()
        rows = []
        
        if suffix == ".csv":
            import csv
            with open(path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        elif suffix in (".xlsx", ".xls"):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
                ws = wb.active
                headers = [str(c.value or "").strip().lower() for c in next(ws.iter_rows())]
                for row in ws.iter_rows(min_row=2, values_only=True):
                    rows.append(dict(zip(headers, [str(v or "").strip() for v in row])))
                wb.close()
            except ImportError:
                return "Module 'openpyxl' non installé. Lancez : pip install openpyxl"
        else:
            return f"Format '{suffix}' non supporté. Utilisez .csv, .xlsx ou .xls."
        
        if not rows:
            return "Aucune donnée trouvée dans le fichier."
        
        # Importer dans le Knowledge Graph
        imported = 0
        errors = []
        try:
            from knowledge_graph import get_neo4j_kg
            kg = get_neo4j_kg()
            kg_available = kg.disponible()
        except Exception:
            kg_available = False
        
        for row in rows:
            tag = row.get("tag", row.get("Tag", row.get("TAG", ""))).strip()
            if not tag:
                continue
            
            desc = row.get("description", row.get("Description", "")).strip()
            type_eq = row.get("type", row.get("Type", "Inconnu")).strip()
            
            if kg_available:
                try:
                    kg.ajouter_equipement(tag, desc, path.name, type_eq)
                    imported += 1
                except Exception as e:
                    errors.append(f"  - {tag}: {e}")
            else:
                imported += 1  # On compte quand même
        
        result_lines = [
            f"=== IMPORT LISTE ÉQUIPEMENTS ===",
            f"  Fichier       : {path.name}",
            f"  Lignes lues   : {len(rows)}",
            f"  Importés OK   : {imported}",
            f"  Erreurs       : {len(errors)}",
        ]
        if errors:
            result_lines.append("\n  Détail des erreurs :")
            result_lines.extend(errors[:5])
        if not kg_available:
            result_lines.append("\n  [INFO] Neo4j non disponible — données lues mais non persistées dans le graphe.")
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Erreur import liste équipements : {e}"


def tool_get_scada_live_data(tag: str) -> str:
    """Lit les données SCADA temps réel pour un tag spécifique."""
    try:
        from scada_simulator import get_live_tag_data
        data = get_live_tag_data(tag)
        if not data:
            return f"Aucune donnée SCADA trouvée pour le tag {tag}."
        lines = [f"=== DONNÉES SCADA LIVE ({tag}) ==="]
        for k, v in data.items():
            if k not in ("tag",):
                lines.append(f"  - {k}: {v}")
        return "\n".join(lines)
    except Exception as e:
        return f"Erreur de lecture SCADA : {e}"


def tool_analyze_scada_trend(tag: str, metric: str, last_n: str = "20") -> str:
    """Analyse de tendance sur les N dernières valeurs d'une métrique SCADA."""
    try:
        from scada_simulator import get_trend_data
        try:
            n = int(last_n)
        except Exception:
            n = 20
        res = get_trend_data(tag, metric, last_n=n)
        if "error" in res:
            return f"Erreur de tendance : {res['error']}"
        
        lines = [
            f"=== ANALYSE DE TENDANCE SCADA ({tag} - {metric}) ===",
            f"  Nombre d'échantillons : {res.get('samples', 0)}",
            f"  Dernière valeur       : {res.get('latest')}",
            f"  Moyenne               : {res.get('avg')}",
            f"  Min / Max             : {res.get('min')} / {res.get('max')}",
            f"  Tendance              : {res.get('trend', 'INCONNUE')}",
            f"  Dérive                : {res.get('drift_pct', 0.0)}%",
            f"  Statut Alerte         : {res.get('alert', 'Normal')}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Erreur d'analyse de tendance : {e}"


ENGINEERING_TOOLS.update({
    "generate_equipment_report": {
        "fn": tool_generate_equipment_report,
        "description": "Génère un rapport technique complet sur un équipement (Knowledge Graph + Data Sheets). Paramètres: tag (str), format (str: 'text' ou 'docx').",
        "params": ["tag", "format"],
    },
    "import_equipment_list": {
        "fn": tool_import_equipment_list,
        "description": "Importe une liste d'équipements depuis un fichier Excel (.xlsx) ou CSV dans le Knowledge Graph. Colonnes attendues: tag, type, description. Paramètre: file_path (str).",
        "params": ["file_path"],
    },
    "get_scada_live_data": {
        "fn": tool_get_scada_live_data,
        "description": "Lit les données SCADA temps réel pour un équipement (ex: P-101). Retourne la pression, température, vibrations, etc. Paramètre: tag (str).",
        "params": ["tag"],
    },
    "analyze_scada_trend": {
        "fn": tool_analyze_scada_trend,
        "description": "Analyse la tendance et la dérive d'une métrique SCADA (ex: vibration_mm_s) pour un équipement sur les N dernières valeurs. Paramètres: tag (str), metric (str), last_n (str).",
        "params": ["tag", "metric", "last_n"],
    },
})
