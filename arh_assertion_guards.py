"""
arh_assertion_guards.py  (v2 - corrigé)
=======================================
Garde-fous déterministes pour ARKAN ARH : filtrent les réserves hallucinées ou physiquement
impossibles SANS masquer les vraies anomalies du dossier.

Invariants :
  1. Provenance          : toute réserve cite un document ou une page source.
  2. Bornes physiques    : une valeur aberrante n'est écartée que si elle est ABSENTE des documents
                           sources (hallucination). Si elle y figure réellement, la réserve est conservée
                           et marquée `guard_flags=["VALEUR_ABERRANTE_DANS_LE_DOCUMENT"]` (erreur de saisie).
  3. Exclusivité équipement / discipline (mots entiers, périmètre local au constat).
  4. Statut de révision.

Correctifs par rapport à la v1 :
  - « ABSENCE / MANQUANT » ne contourne plus la provenance que si un document est nommé à proximité.
  - L'exclusivité « seamless » ne s'applique plus à tout le dossier dès qu'un mot « seamless » apparaît :
    elle exige une absence de toute trace de soudage dans le dossier, ou une mention locale au constat.
  - Détection par mots entiers (plus de faux positifs sur des sous-chaînes).
  - Bornes d'épaisseur et de température réellement contrôlées ; pressions en psi/MPa converties.
  - Plafond distinct pour les résistances à la traction (Rm).
"""

import re
import logging
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger("ARHAssertionGuards")


def _squash(text: str) -> str:
    """Supprime espaces/séparateurs de milliers pour retrouver un nombre dans un texte source."""
    return re.sub(r"[\s,\u202f\u00a0]", "", text or "")


class ARHAssertionGuard:
    """Moteur d'évaluation et de filtrage d'assertions réglementaires et physiques."""

    # Bornes physiques strictes d'ingénierie pétrolière
    MIN_ALLOWABLE_STRESS_MPA = 20.0
    MAX_ALLOWABLE_STRESS_MPA = 1000.0
    MAX_TENSILE_MPA = 2500.0
    MIN_PRESSURE_BAR = 0.01
    MAX_PRESSURE_BAR = 2500.0
    MIN_THICKNESS_MM = 0.2
    MAX_THICKNESS_MM = 500.0
    MIN_TEMP_C = -196.0
    MAX_TEMP_C = 950.0

    _MISSING_RE = re.compile(r"MANQUANT|NON FOURNI|NON TRANSMIS|ABSENT|ABSENCE", re.I)
    _DOCWORD_RE = re.compile(
        r"DOCUMENT|PI[EÈ]CE|CERTIFICAT|\bPLAN\b|\bNOTE\b|\bWPS\b|\bPQR\b|QMOS|\bITP\b|\bPCI\b|DOSSIER|"
        r"PROC[ÉE]DURE|ATTESTATION|AGR[ÉE]MENT|\bFICHE\b|ANNEXE|\bPV\b|RAPPORT", re.I)

    _UNKNOWN = ("UNKNOWN", "N/A", "NONE")

    # --- Exclusivité : motifs à mots entiers --------------------------------------------------
    _SIL_ATEX_PATTERNS = [r"\bSIL\s?[1-4]?\b", r"\bATEX\b", r"\bZONE\s?[012]\b", r"\bFGS\b", r"\bSIF\b",
                          r"SAFETY INTEGRITY LEVEL"]
    _SEAMLESS_RE = re.compile(r"SANS SOUDURE|SEAMLESS|\bSMLS\b|WELDING:\s*NONE|NON SOUD[ÉE]", re.I)
    _WELD_EVIDENCE_RE = re.compile(
        r"\bWPS\b|\bPQR\b|\bQMOS\b|WELDING PROCEDURE|PROC[ÉE]DURE DE SOUDAGE|WELD MAP|CAHIER DE SOUDAGE|"
        r"SOUDURE|SOUDAGE|\bWELD(?:ED|ING|S)?\b|CORDON", re.I)
    _WELD_KEYWORDS = [r"WELD MAP", r"\bPQR\b", r"\bWPS\b", r"QUALIFICATION DE SOUDEUR", r"\bWPQ\b",
                      r"CAHIER DE SOUDAGE"]
    _EXPLICIT_MISSING_WELD = ["MANQUE LA WPS", "MANQUE LES WPS", "FOURNITURE OBLIGATOIRE DES WPS",
                              "WPS ET PQR APPLIQUER", "SPECIFICATION DE PROCEDURES DE SOUDAGE", "ABSENCE DE WPS"]

    # ------------------------------------------------------------------------------------------
    @classmethod
    def _is_completeness_finding(cls, text: str) -> bool:
        """Vrai si « absent / manquant » est mentionné à proximité immédiate d'un nom de pièce."""
        for m in cls._MISSING_RE.finditer(text or ""):
            window = text[max(0, m.start() - 80): m.end() + 80]
            if cls._DOCWORD_RE.search(window):
                return True
        return False

    @classmethod
    def assert_provenance(cls, finding: Dict[str, Any]) -> Tuple[bool, str]:
        """Invariant de Provenance : document ou page source obligatoire (sauf pièce manifestement manquante)."""
        doc = finding.get("document_concerned") or finding.get("document") or ""
        page = finding.get("page") or ""
        text = f"{finding.get('title') or ''} {finding.get('observation') or ''}"

        has_doc = bool(doc and str(doc).strip() and str(doc).upper() not in cls._UNKNOWN)
        has_page = bool(page and str(page).strip() and str(page).upper() not in cls._UNKNOWN)
        if has_doc or has_page:
            return True, "Provenance validée"
        if cls._is_completeness_finding(text):
            return True, "Validé : absence formelle d'une pièce nommée (réserve de complétude)"
        return False, "Rejeté : absence de document ou de page source (provenance non prouvée)"

    # ------------------------------------------------------------------------------------------
    @staticmethod
    def _to_float(tok: str) -> float:
        return float(tok.replace(",", "."))

    @classmethod
    def _violations(cls, text: str) -> List[Tuple[str, str]]:
        """Retourne la liste (jeton_numérique_brut, message) des valeurs hors bornes physiques."""
        out: List[Tuple[str, str]] = []
        num = r"(-?\d+(?:[.,]\d+)?)"

        for m in re.finditer(num + r"\s*(?:MPa|N/mm²|N/mm2)", text, re.I):
            val = cls._to_float(m.group(1))
            before = text[max(0, m.start() - 40): m.start()]
            if re.search(r"pression|pressure|\bPMA\b|\bPS\b|design|[ée]preuve|\btest\b", before, re.I):
                if val * 10.0 > cls.MAX_PRESSURE_BAR:
                    out.append((m.group(1), f"Pression aberrante ({val} MPa)"))
            elif re.search(r"\bRm\b|traction|tensile|\bUTS\b|rupture", before, re.I):
                if val > cls.MAX_TENSILE_MPA:
                    out.append((m.group(1), f"Résistance à la traction aberrante ({val} MPa)"))
            elif val > cls.MAX_ALLOWABLE_STRESS_MPA:
                out.append((m.group(1), f"Contrainte admissible aberrante ({val} MPa > {cls.MAX_ALLOWABLE_STRESS_MPA} MPa)"))

        for m in re.finditer(num + r"\s*(?:barg|bara|bar)\b", text, re.I):
            val = cls._to_float(m.group(1))
            if val > cls.MAX_PRESSURE_BAR:
                out.append((m.group(1), f"Pression aberrante ({val} bar > {cls.MAX_PRESSURE_BAR} bar)"))

        for m in re.finditer(num + r"\s*(?:psig|psia|psi)\b", text, re.I):
            val = cls._to_float(m.group(1)) * 0.0689476
            if val > cls.MAX_PRESSURE_BAR:
                out.append((m.group(1), f"Pression aberrante ({m.group(1)} psi ≈ {val:.0f} bar)"))

        for m in re.finditer(num + r"\s*mm\b", text, re.I):
            before = text[max(0, m.start() - 40): m.start()]
            if re.search(r"[ée]paisseur|thickness|\bt\s*=|[ée]p\.", before, re.I):
                val = cls._to_float(m.group(1))
                if val < cls.MIN_THICKNESS_MM or val > cls.MAX_THICKNESS_MM:
                    out.append((m.group(1), f"Épaisseur aberrante ({val} mm)"))

        for m in re.finditer(num + r"\s*°\s*C\b", text, re.I):
            val = cls._to_float(m.group(1))
            if val < cls.MIN_TEMP_C or val > cls.MAX_TEMP_C:
                out.append((m.group(1), f"Température aberrante ({val} °C)"))
        return out

    @classmethod
    def assert_physical_bounds(cls, finding: Dict[str, Any], full_context_text: str = "") -> Tuple[bool, str]:
        """
        Invariant des Bornes Physiques.
        - Valeur aberrante ABSENTE des documents sources  -> hallucination : rejet.
        - Valeur aberrante PRÉSENTE dans les documents    -> vraie anomalie documentaire : conservée + marquée.
        """
        text = f"{finding.get('observation') or ''} {finding.get('title') or ''}"
        squashed_ctx = _squash(full_context_text)
        for token, msg in cls._violations(text):
            if full_context_text and _squash(token) in squashed_ctx:
                flags = finding.setdefault("guard_flags", [])
                if "VALEUR_ABERRANTE_DANS_LE_DOCUMENT" not in flags:
                    flags.append("VALEUR_ABERRANTE_DANS_LE_DOCUMENT")
                continue
            return False, f"Rejeté : {msg} (absente des documents sources)"
        return True, "Bornes physiques respectées"

    # ------------------------------------------------------------------------------------------
    @classmethod
    def assert_equipment_exclusivity(cls, finding: Dict[str, Any], equipment_type: str,
                                     full_context_text: str = "") -> Tuple[bool, str]:
        """
        Invariant d'Exclusivité Équipement & Discipline :
        - Bouteilles / extincteurs : rejet des réserves SIL/ATEX/électriques.
        - Équipement sans soudure : rejet des réserves WPS/PQR/WELD MAP, UNIQUEMENT si le constat lui-même
          mentionne « sans soudure » OU si le dossier entier ne contient aucune trace de soudage.
        - Robinetterie : rejet des réserves de fond bombé UG-32.
        """
        eq = (equipment_type or "").upper()
        title = (finding.get("title") or "").upper()
        obs = (finding.get("observation") or "").upper()
        cat = (finding.get("category") or "").upper()
        combined = f"{title} {obs} {cat}"

        if eq in ("FIRE_EXTINGUISHER", "CYLINDER", "BOUTEILLE"):
            for pat in cls._SIL_ATEX_PATTERNS:
                m = re.search(pat, combined)
                if m:
                    return False, f"Rejeté : réserve « {m.group(0).strip()} » non applicable aux bouteilles/extincteurs (équipement mécanique passif)"

        ctx = full_context_text or ""
        local_seamless = bool(cls._SEAMLESS_RE.search(combined))
        ctx_wo_seamless = cls._SEAMLESS_RE.sub(" ", ctx)
        global_seamless = bool(cls._SEAMLESS_RE.search(ctx)) and not cls._WELD_EVIDENCE_RE.search(ctx_wo_seamless)
        if local_seamless or global_seamless:
            if not any(k in combined for k in cls._EXPLICIT_MISSING_WELD) and "NON APPLICABLE" not in combined:
                for pat in cls._WELD_KEYWORDS:
                    m = re.search(pat, combined)
                    if m:
                        return False, f"Rejeté : exigence de soudage ({m.group(0)}) sur matériel sans soudure"

        if "VALVE" in eq or "ROBINETTERIE" in eq:
            if "EPAISSEUR DE FOND BOMBE" in combined or "UG-32" in combined:
                return False, "Rejeté : les fonds bombés UG-32 ne concernent pas la robinetterie industrielle (ASME B16.34)"

        return True, "Exclusivité équipement validée"

    # ------------------------------------------------------------------------------------------
    @classmethod
    def assert_revision_status(cls, finding: Dict[str, Any], is_resolved_revision: bool) -> Tuple[bool, str]:
        """Invariant de Statut de Révision : pas de réserve préliminaire sur une révision approuvée."""
        if not is_resolved_revision:
            return True, "Statut préliminaire standard"
        cat = (finding.get("category") or "").upper()
        title = (finding.get("title") or "").upper()
        if "PRÉLIMINAIRE" in cat or "PRÉVISIONNEL" in title or "VALEUR ANTICIPÉE" in title:
            return False, "Rejeté : réserve préliminaire non applicable à une révision finale approuvée"
        return True, "Statut de révision conforme"

    # ------------------------------------------------------------------------------------------
    @classmethod
    def validate_and_sanitize_findings(
        cls,
        findings: List[Dict[str, Any]],
        equipment_type: str = "",
        full_context_text: str = "",
        is_resolved_revision: bool = False,
        rejected_out: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Filtre la liste de réserves. `rejected_out` (optionnel) reçoit {finding, raison} pour l'audit."""
        sanitized: List[Dict[str, Any]] = []
        for f in findings:
            checks = (
                cls.assert_provenance(f),
                cls.assert_physical_bounds(f, full_context_text),
                cls.assert_equipment_exclusivity(f, equipment_type, full_context_text),
                cls.assert_revision_status(f, is_resolved_revision),
            )
            failed = next((msg for ok, msg in checks if not ok), None)
            if failed:
                logger.info(f"[AssertionGuard] {failed} -> {f.get('title')}")
                if rejected_out is not None:
                    rejected_out.append({"finding": f, "reason": failed})
                continue
            sanitized.append(f)
        dropped = len(findings) - len(sanitized)
        if dropped:
            logger.info(f"[AssertionGuard] {dropped} réserve(s) écartée(s), {len(sanitized)} conservée(s).")
        return sanitized


# Singleton exporté
assertion_guard = ARHAssertionGuard()
