"""
arh_dimensional_engine.py
=========================
Moteur de Normalisation Dimensionnelle & d'Équivalence Physique Déterministe pour ARKAN ARH.
Garantit l'absence totale de faux positifs de discordance dus aux unités disparates
(bar, barg, psi, MPa, kg/cm², °C, °F, mm, inches, etc.).
"""

import re
import logging
from typing import Tuple, Optional, Dict, Any
import pint

logger = logging.getLogger("ARHDimensionalEngine")

# Initialisation du registre d'unités Pint
ureg = pint.UnitRegistry()

# Définitions additionnelles pour l'ingénierie pétrolière et gazière
try:
    ureg.define('barg = bar')
    ureg.define('bara = bar')
    ureg.define('psig = psi')
    ureg.define('psia = psi')
    ureg.define('kg_cm2 = 0.980665 * bar')
except Exception as e:
    logger.debug(f"Définitions d'unités Pint déjà existantes ou ignorées: {e}")

# Dictionnaires de normalisation des unités textuelles
UNIT_ALIASES = {
    # Pression
    "bar": "bar",
    "barg": "bar",
    "bara": "bar",
    "bars": "bar",
    "psi": "psi",
    "psig": "psi",
    "psia": "psi",
    "mpa": "megapascal",
    "kpa": "kilopascal",
    "pa": "pascal",
    "kg/cm2": "kg_cm2",
    "kg/cm²": "kg_cm2",
    "kgf/cm2": "kg_cm2",
    "kgf/cm²": "kg_cm2",
    
    # Température
    "°c": "degC",
    "deg c": "degC",
    "degc": "degC",
    "c": "degC",
    "°f": "degF",
    "deg f": "degF",
    "degf": "degF",
    "f": "degF",
    "k": "kelvin",
    
    # Longueur & Épaisseur
    "mm": "millimeter",
    "millimetre": "millimeter",
    "millimètre": "millimeter",
    "m": "meter",
    "metre": "meter",
    "mètre": "meter",
    "cm": "centimeter",
    "in": "inch",
    "inch": "inch",
    "inches": "inch",
    '"': "inch",
    "''": "inch",
    
    # Contrainte
    "n/mm2": "megapascal",
    "n/mm²": "megapascal",
    "ksi": "ksi",
}

ATM_BAR = 1.01325  # pression atmosphérique normale (bar)
_GAUGE_UNITS = {"barg", "psig", "mpag", "kpag"}
_ABSOLUTE_UNITS = {"bara", "psia", "mpaa", "kpaa"}


class ARHDimensionalEngine:
    """Moteur de conversion et vérification physique déterministe."""

    @staticmethod
    def clean_unit_str(unit_str: str) -> str:
        """Nettoie et normalise la chaîne d'unité."""
        if not unit_str:
            return ""
        u = unit_str.strip().lower()
        u = re.sub(r'[\s\.\-_]+', '', u)
        return UNIT_ALIASES.get(u, u)

    @classmethod
    def parse_value_with_unit(cls, text_fragment: str) -> Optional[Tuple[float, str]]:
        """
        Extrait une valeur numérique et son unité à partir d'un fragment de texte.
        Ex: '19.6 barg' -> (19.6, 'bar')
            '284.27 psi' -> (284.27, 'psi')
            '12.5 mm' -> (12.5, 'millimeter')
        """
        if not text_fragment:
            return None
            
        pattern = r'([-+]?\d+(?:[.,]\d+)?)\s*([°a-zA-Z/²"\'_]+)'
        known_units = set(UNIT_ALIASES.values())
        first = None
        # Correctif : on parcourt tous les couples nombre/unité et on retient le premier dont l'unité est
        # reconnue (ex. « A516 Gr 70 12 mm » -> 12 mm, et non 516 « gr »).
        for match in re.finditer(pattern, text_fragment.strip()):
            try:
                val = float(match.group(1).replace(',', '.'))
            except Exception:
                continue
            norm_unit = cls.clean_unit_str(match.group(2))
            cand = (val, norm_unit)
            if first is None:
                first = cand
            if norm_unit in known_units:
                return cand
        return first

    @classmethod
    def convert_to_standard(cls, val: float, unit_str: str, dimension_type: str = "pressure") -> Optional[Tuple[float, str]]:
        """
        Convertit une valeur vers l'unité standard ARH :
        - pressure -> bar
        - temperature -> degC
        - length / thickness -> mm
        - stress -> megapascal
        """
        try:
            norm_u = cls.clean_unit_str(unit_str)
            if not norm_u:
                return None
                
            q = ureg.Quantity(val, norm_u)
            
            if dimension_type == "pressure":
                target = q.to('bar')
                return round(float(target.magnitude), 3), "bar"
            elif dimension_type == "temperature":
                target = q.to('degC')
                return round(float(target.magnitude), 2), "degC"
            elif dimension_type in ["length", "thickness"]:
                target = q.to('millimeter')
                return round(float(target.magnitude), 2), "mm"
            elif dimension_type == "stress":
                target = q.to('megapascal')
                return round(float(target.magnitude), 2), "MPa"
            else:
                return float(q.magnitude), norm_u
        except Exception as e:
            logger.debug(f"[DimensionalEngine] Erreur conversion {val} {unit_str}: {e}")
            return None

    @staticmethod
    def pressure_reference(unit_str: str) -> Optional[str]:
        """'gauge' (relative), 'absolute' ou None si non précisé (bar, MPa, psi...)."""
        u = re.sub(r"[\s\.\-_]+", "", (unit_str or "").lower())
        if u in _GAUGE_UNITS:
            return "gauge"
        if u in _ABSOLUTE_UNITS:
            return "absolute"
        return None

    @classmethod
    def physically_concordant(
        cls, 
        val1: float, 
        unit1: str, 
        val2: float, 
        unit2: str, 
        dimension_type: str = "pressure",
        tol_pct: float = 2.0
    ) -> Tuple[bool, str]:
        """
        Vérifie si deux valeurs exprimées en unités potentiellement différentes sont physiquement concordantes.
        Tolérance par défaut : 2.0%.
        Retourne (is_concordant, explanation_str).
        """
        res1 = cls.convert_to_standard(val1, unit1, dimension_type)
        res2 = cls.convert_to_standard(val2, unit2, dimension_type)
        
        if not res1 or not res2:
            # Si échec de conversion dimensionnelle, comparaison directe brute si mêmes unités
            if unit1.strip().lower() == unit2.strip().lower():
                diff_pct = abs(val1 - val2) / max(abs(val1), 1e-6) * 100.0
                if diff_pct <= tol_pct:
                    return True, f"Concordant ({val1} vs {val2} {unit1}, écart={diff_pct:.1f}%)"
                return False, f"Divergence ({val1} != {val2} {unit1}, écart={diff_pct:.1f}%)"
            return False, f"Unités incompatibles ou non reconnues ({unit1} vs {unit2})"
            
        std_val1, std_unit = res1
        std_val2, _ = res2

        # Correctif : barg (relatif) vs bara (absolu) diffèrent de 1,01325 bar. L'écart n'est corrigé que
        # lorsque les deux références sont explicitement opposées (sinon on ne présume rien).
        if dimension_type == "pressure":
            ref1, ref2 = cls.pressure_reference(unit1), cls.pressure_reference(unit2)
            if ref1 == "gauge" and ref2 == "absolute":
                std_val1 = round(std_val1 + ATM_BAR, 3)
            elif ref1 == "absolute" and ref2 == "gauge":
                std_val2 = round(std_val2 + ATM_BAR, 3)
        
        diff = abs(std_val1 - std_val2)
        denom = max(abs(std_val1), abs(std_val2), 1e-6)
        diff_pct = (diff / denom) * 100.0
        
        if diff_pct <= tol_pct:
            return True, f"Concordance physique ({val1} {unit1} ~= {val2} {unit2} -> {std_val1} vs {std_val2} {std_unit}, ecart={diff_pct:.1f}%)"
        else:
            return False, f"Discordance physique ({val1} {unit1} != {val2} {unit2} -> {std_val1} vs {std_val2} {std_unit}, ecart={diff_pct:.1f}%)"

# Instance singleton accessible partout
dimensional_engine = ARHDimensionalEngine()
