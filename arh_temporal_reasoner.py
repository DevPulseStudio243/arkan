"""
arh_temporal_reasoner.py
========================
Module de Raisonnement Temporel pour ARH Management.

Comprend le SENS d'une date dans son contexte réglementaire :
  - Ne se contente PAS de détecter qu'une date existe.
  - CALCULE si la qualification/certification/calibration est encore valide AUJOURD'HUI.
  - Applique les durées de validité réglementaires exactes selon le type de document.

Règles de validité intégrées :
  • ASME IX QW-322       : Qualification soudeur → 6 mois max sans interruption
  • ISO 9606-1           : Qualification soudeur (Europe) → 6 mois sans soudure continue
  • Étalonnage équipements de mesure → 12 mois (standard industriel GCB/Sonatrach)
  • Certificats ATEX / IECEx → 5 ans (renouvellement obligatoire)
  • Certificats EN 10204 3.1 → Sans expiration, mais vérification de la date de coulée
  • Visa Consulaire      → 6 mois max selon les exigences ARH P-CTE-1
  • Décret 21-261 Art.38 → Inspection réglementaire ESP → 36 mois max
  • Décret 21-261 Art.43 → Requalification périodique ESP → 10 ans (fixe) / 5 ans (mobile)
"""

from __future__ import annotations

import re
import uuid
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("ARHTemporalReasoner")

# ══════════════════════════════════════════════════════════════════════════════
# TABLE DE VALIDITÉ RÉGLEMENTAIRE
# ══════════════════════════════════════════════════════════════════════════════

VALIDITY_RULES: Dict[str, Dict[str, Any]] = {
    "WELDER_QUALIFICATION": {
        "label": "Qualification Soudeur (WOPQ/WQPQ)",
        "max_days": 183,           # 6 mois ASME IX QW-322
        "warning_days": 150,       # Alerte à 5 mois pour anticiper le renouvellement
        "standard": "ASME Section IX QW-322 / ISO 9606-1",
        "decree": "Décret exécutif n° 21-261 Art. 17",
        "renewal_condition": "Maintien en activité documenté (attestation mensuelle signée par le CWI/CWE)",
        "priority_if_expired": "CRITICAL",
        "priority_if_warning": "MAJOR",
    },
    "CALIBRATION_CERTIFICATE": {
        "label": "Certificat d'Étalonnage des Équipements de Mesure",
        "max_days": 365,           # 12 mois standard Sonatrach / GCB
        "warning_days": 330,
        "standard": "ISO 9001:2015 Clause 7.1.5 / Procédure GCB QC",
        "decree": "Décret exécutif n° 21-261 Art. 19",
        "renewal_condition": "Réétalonnage par laboratoire accrédité ALGERAC",
        "priority_if_expired": "CRITICAL",
        "priority_if_warning": "MAJOR",
    },
    "ATEX_CERTIFICATE": {
        "label": "Certificat ATEX / IECEx (Examen UE de Type)",
        "max_days": 1825,          # 5 ans (directive ATEX 2014/34/UE)
        "warning_days": 1700,
        "standard": "Directive ATEX 2014/34/UE / IEC/EN 60079-0",
        "decree": "Décret exécutif n° 21-257 Art. 14",
        "renewal_condition": "Ré-examen UE de type par organisme notifié (INERIS, LCIE, PTB, Baseefa)",
        "priority_if_expired": "CRITICAL",
        "priority_if_warning": "MAJOR",
    },
    "CONSULAR_VISA": {
        "label": "Visa Consulaire (Légalisation Signatures Fabricant)",
        "max_days": 183,           # 6 mois selon pratique ARH / P-CTE-1
        "warning_days": 150,
        "standard": "Procédure ARH P-CTE-1 Part 2",
        "decree": "Procédure P-CTE-1 / Décret 21-261",
        "renewal_condition": "Nouvelle légalisation consulaire avec date à jour",
        "priority_if_expired": "CRITICAL",
        "priority_if_warning": "MAJOR",
    },
    "ESP_INSPECTION": {
        "label": "Inspection Réglementaire Périodique ESP",
        "max_days": 1095,          # 36 mois (Décret 21-261 Art.38)
        "warning_days": 1000,
        "standard": "Décret exécutif n° 21-261 Art. 38",
        "decree": "Décret exécutif n° 21-261 Art. 38",
        "renewal_condition": "Visite de requalification par organisme accrédité ALGERAC",
        "priority_if_expired": "CRITICAL",
        "priority_if_warning": "MAJOR",
    },
    "ESP_REQUALIFICATION": {
        "label": "Requalification Périodique ESP (Épreuve Hydrostatique)",
        "max_days": 3650,          # 10 ans fixe / 1825 jours mobile (Décret 21-261 Art.43)
        "warning_days": 3500,
        "standard": "Décret exécutif n° 21-261 Art. 43",
        "decree": "Décret exécutif n° 21-261 Art. 43",
        "renewal_condition": "Requalification complète avec épreuve hydrostatique supervisée ARH",
        "priority_if_expired": "CRITICAL",
        "priority_if_warning": "MAJOR",
    },
    "WPS_VALIDITY": {
        "label": "Procédure de Soudage WPS (validité illimitée, mais révision si changement variable essentielle)",
        "max_days": None,          # Pas d'expiration, mais vérifier si le PQR couvre la nuance actuelle
        "warning_days": None,
        "standard": "ASME Section IX QW-200.1",
        "decree": "Décret exécutif n° 21-261 Art. 16",
        "renewal_condition": "Nouvelle qualification PQR si variable essentielle modifiée",
        "priority_if_expired": None,
        "priority_if_warning": None,
    },
    "NACE_COMPLIANCE": {
        "label": "Conformité NACE MR0175 / ISO 15156 (Matériaux Service H2S)",
        "max_days": None,          # Pas d'expiration (propriété intrinsèque du matériau)
        "warning_days": None,
        "standard": "NACE MR0175 / ISO 15156",
        "decree": "Décret exécutif n° 21-261 Art. 6",
        "renewal_condition": "Remplacement de matériau si non conforme",
        "priority_if_expired": None,
        "priority_if_warning": None,
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# PATTERNS DE DÉTECTION DE DATE (TOUTES FORMES DOCUMENTAIRES RÉELLES)
# ══════════════════════════════════════════════════════════════════════════════

# Mois en toutes langues présentes dans les dossiers ARH/GCB
_MONTH_NAMES: Dict[str, int] = {
    # Français
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    # Anglais
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    # Abréviations anglaises (fréquentes dans les carnets soudage)
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

_DATE_PATTERNS: List[Tuple[str, str]] = [
    # DD/MM/YYYY ou DD-MM-YYYY (format français/algérien dominant)
    (r'\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b', "DMY_NUMERIC"),
    # YYYY-MM-DD (format ISO 8601, fréquent dans les rapports FAT anglais)
    (r'\b(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})\b', "YMD_NUMERIC"),
    # DD Month YYYY (ex: "15 January 2025" ou "15 janvier 2025")
    (r'\b(\d{1,2})\s+(' + '|'.join(_MONTH_NAMES.keys()) + r')\s+(\d{4})\b', "DMY_ALPHA"),
    # Month DD, YYYY (format américain ex: "January 15, 2025")
    (r'\b(' + '|'.join(_MONTH_NAMES.keys()) + r')\s+(\d{1,2}),?\s+(\d{4})\b', "MDY_ALPHA"),
    # DD-Mon-YY (format court fréquent dans carnets de soudage ex: "15-Jan-25")
    (r'\b(\d{1,2})-(' + '|'.join(_MONTH_NAMES.keys()) + r')-(\d{2})\b', "DMY_SHORT"),
    # MM/YYYY (seulement mois/année, utilisé pour les qualifications)
    (r'\b(\d{1,2})[/\-](\d{4})\b', "MY_NUMERIC"),
]

# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTEUR DE DATES
# ══════════════════════════════════════════════════════════════════════════════

class ARHDateExtractor:
    """Extrait et parse les dates depuis du texte technique multilingue (FR/EN/mixte)."""

    def extract_dates_from_text(self, text: str) -> List[date]:
        """
        Extrait toutes les dates valides d'un texte.
        Retourne une liste triée des dates trouvées (de la plus récente à la plus ancienne).
        """
        found_dates: List[date] = []
        text_lower = text.lower()

        for pattern, fmt in _DATE_PATTERNS:
            for m in re.finditer(pattern, text_lower, re.IGNORECASE):
                parsed = self._parse_match(m, fmt)
                if parsed and self._is_plausible_date(parsed):
                    found_dates.append(parsed)

        # Dédupliquer et trier
        unique = list({d.isoformat(): d for d in found_dates}.values())
        unique.sort(reverse=True)
        return unique

    def _parse_match(self, m: re.Match, fmt: str) -> Optional[date]:
        try:
            g = m.groups()
            if fmt == "DMY_NUMERIC":
                day, month, year = int(g[0]), int(g[1]), int(g[2])
            elif fmt == "YMD_NUMERIC":
                year, month, day = int(g[0]), int(g[1]), int(g[2])
            elif fmt == "DMY_ALPHA":
                day = int(g[0])
                month = _MONTH_NAMES.get(g[1].lower(), 0)
                year = int(g[2])
            elif fmt == "MDY_ALPHA":
                month = _MONTH_NAMES.get(g[0].lower(), 0)
                day = int(g[1])
                year = int(g[2])
            elif fmt == "DMY_SHORT":
                day = int(g[0])
                month = _MONTH_NAMES.get(g[1].lower(), 0)
                year_short = int(g[2])
                year = 2000 + year_short if year_short < 50 else 1900 + year_short
            elif fmt == "MY_NUMERIC":
                month, year = int(g[0]), int(g[1])
                day = 1  # Premier du mois par convention
            else:
                return None

            if month == 0 or month > 12 or day > 31 or day < 1:
                return None
            return date(year, month, day)
        except (ValueError, IndexError):
            return None

    def _is_plausible_date(self, d: date) -> bool:
        """
        Filtre les dates non plausibles pour un document technique ARH.
        Plage acceptable : 1995 (début des décrets modernes) → aujourd'hui + 1 an (planification).
        """
        today = date.today()
        return date(1995, 1, 1) <= d <= today + timedelta(days=365)

    def extract_most_recent_date_near_keyword(
        self, text: str, keywords: List[str], window_chars: int = 200
    ) -> Optional[date]:
        """
        Extrait la date la plus récente dans une fenêtre de texte autour d'un mot-clé.
        Ex: chercher une date près de "WOPQ" ou "Renewed" ou "Qualifié le".
        """
        text_lower = text.lower()
        for kw in keywords:
            idx = text_lower.find(kw.lower())
            if idx == -1:
                continue
            start = max(0, idx - window_chars)
            end = min(len(text), idx + window_chars)
            window = text[start:end]
            dates = self.extract_dates_from_text(window)
            if dates:
                return dates[0]  # La plus récente dans la fenêtre
        return None


# ══════════════════════════════════════════════════════════════════════════════
# MOTEUR DE RAISONNEMENT TEMPOREL PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class ARHTemporalReasoningAgent:
    """
    Agent de raisonnement temporel : vérifie la validité temporelle de tous
    les documents datés d'un dossier ARH et génère des remarques normalisées.
    """

    def __init__(self):
        self.name = "Auditeur Temporel & Validité des Certifications"
        self.discipline = "TEMPOREL"
        self.date_extractor = ARHDateExtractor()
        self.today = date.today()

    def audit_temporal_validity(
        self, docs: List[Dict[str, Any]], equipment_type: str, dossier_stage: str
    ) -> List[Dict[str, Any]]:
        """
        Analyse temporelle complète du dossier :
          1. Validité des qualifications soudeurs (WOPQ)
          2. Validité des certificats ATEX
          3. Fraîcheur des visas consulaires
          4. Étalonnage des équipements de mesure
        """
        findings: List[Dict[str, Any]] = []
        full_text_all = " ".join([d.get("text", "") for d in docs])

        for doc in docs:
            text = doc.get("text", "")
            fname = doc.get("file_name", "")
            tu = text.upper()

            # ── 1. Qualifications Soudeurs (WOPQ / WPQ / Carnet de soudage) ──
            if equipment_type not in ("ELECTRICAL", "INSTRUMENTATION") and dossier_stage != "PRELIMINARY":
                if any(k in tu for k in ["WOPQ", "WPQ", "WELDER QUALIF", "QUALIFICATION SOUDEUR", "CERTIFICAT SOUDEUR", "WELDER PERFORMANCE"]):
                    findings.extend(self._check_welder_qualifications(text, fname))

            # ── 2. Certificats ATEX / IECEx ──
            if any(k in tu for k in ["ATEX CERTIF", "IECEX CERTIF", "EU-TYPE EXAMINATION",
                                      "ATTESTATION D'EXAMEN UE", "CERTIFICAT DE CONFORMITÉ ATEX"]):
                findings.extend(self._check_atex_certificates(text, fname))

            # ── 3. Visa Consulaire (Part 2 P-CTE-1) ──
            if any(k in tu for k in ["CONSULAT", "CONSULATE", "CHAMBRE DE COMMERCE",
                                      "CHAMBER OF COMMERCE", "LÉGALISATION", "LEGALISATION"]):
                findings.extend(self._check_consular_visa(text, fname))

            # ── 4. Certificats d'Étalonnage ──
            if any(k in tu for k in ["CALIBRATION CERT", "CERTIFICAT D'ETALONNAGE",
                                      "CERTIFICAT DE CALIBRATION", "CALIBRATED ON",
                                      "DATE D'ÉTALONNAGE", "NEXT CALIBRATION"]):
                findings.extend(self._check_calibration_certs(text, fname))

        return findings

    # ──────────────────────────────────────────────────────────────────────────
    # VÉRIFICATION 1 : QUALIFICATIONS SOUDEURS
    # ──────────────────────────────────────────────────────────────────────────

    def _check_welder_qualifications(self, text: str, fname: str) -> List[Dict[str, Any]]:
        findings = []
        rule = VALIDITY_RULES["WELDER_QUALIFICATION"]
        tu = text.upper()

        # Chercher la date de qualification la plus récente
        qual_date = self.date_extractor.extract_most_recent_date_near_keyword(
            text,
            keywords=["WOPQ", "WPQ", "QUALIF", "RENEWED", "DATE OF QUALIFICATION",
                      "DATE DE QUALIFICATION", "QUALIFIÉ LE", "QUALIFIED ON",
                      "QUALIFIED:", "LAST WELDED", "DERNIER SOUDAGE"],
            window_chars=300
        )

        if qual_date is None:
            # Pas de date trouvée alors qu'un document de qualification est présent
            findings.append(self._build_finding(
                rule_key="WELDER_QUALIFICATION",
                fname=fname,
                priority="MAJOR",
                title="Date de Qualification Soudeur Non Identifiable dans le Document",
                observation=(
                    f"Le document '{fname}' contient des références à des qualifications soudeurs "
                    f"(WOPQ/WPQ), mais aucune date de qualification ou de renouvellement n'a pu "
                    f"être extraite. L'agent temporel ne peut pas vérifier la validité ASME IX QW-322."
                ),
                action_required=(
                    "Fournir un document de qualification soudeur avec les dates explicitement "
                    "mentionnées : date de qualification initiale ET dernière date de soudage continu "
                    "documentée (attestation mensuelle du CWI/coordinateur soudage)."
                ),
                days_elapsed=None,
                expiry_date=None,
            ))
            return findings

        days_elapsed = (self.today - qual_date).days

        # Vérifier si la maintenance continue est documentée
        has_continuity_attestation = any(k in tu for k in [
            "MAINTAINED IN SERVICE", "MAINTIEN EN ACTIVITE", "CONTINUITY",
            "ATTESTATION MENSUELLE", "MONTHLY MAINTENANCE", "ACTIVE IN PRODUCTION",
            "EN ACTIVITÉ CONTINUE", "CONTINUED ACTIVITY"
        ])

        if days_elapsed > rule["max_days"] and not has_continuity_attestation:
            # Qualification périmée sans preuve de maintien en activité
            expiry_date = qual_date + timedelta(days=rule["max_days"])
            findings.append(self._build_finding(
                rule_key="WELDER_QUALIFICATION",
                fname=fname,
                priority="CRITICAL",
                title=f"Qualification Soudeur Périmée depuis {days_elapsed - rule['max_days']} Jours (ASME IX QW-322)",
                observation=(
                    f"La qualification soudeur (WOPQ/WPQ) trouvée dans '{fname}' date du "
                    f"{qual_date.strftime('%d/%m/%Y')} ({days_elapsed} jours écoulés). "
                    f"La limite réglementaire ASME Section IX QW-322 est de {rule['max_days']} jours "
                    f"(6 mois) sans interruption de l'activité de soudage. "
                    f"Aucune attestation de maintien en activité continue n'a été détectée dans le dossier. "
                    f"Date d'expiration théorique : {expiry_date.strftime('%d/%m/%Y')}."
                ),
                action_required=(
                    "Fournir soit : (1) une attestation mensuelle de maintien en activité soudage "
                    "signée par le CWI/CWE couvrant la période depuis la qualification, soit "
                    "(2) procéder à une nouvelle qualification soudeur complète avec coupon d'essai "
                    "et rapport PQR selon ASME IX."
                ),
                days_elapsed=days_elapsed,
                expiry_date=expiry_date,
            ))

        elif days_elapsed > rule["warning_days"] and not has_continuity_attestation:
            # Approche de l'expiration
            expiry_date = qual_date + timedelta(days=rule["max_days"])
            days_remaining = rule["max_days"] - days_elapsed
            findings.append(self._build_finding(
                rule_key="WELDER_QUALIFICATION",
                fname=fname,
                priority="MAJOR",
                title=f"Qualification Soudeur Proche de l'Expiration (Expire dans {days_remaining} Jours)",
                observation=(
                    f"La qualification soudeur dans '{fname}' date du {qual_date.strftime('%d/%m/%Y')} "
                    f"({days_elapsed} jours écoulés). Elle expire théoriquement le "
                    f"{expiry_date.strftime('%d/%m/%Y')} dans {days_remaining} jours. "
                    f"Aucune attestation de maintien en activité n'est jointe."
                ),
                action_required=(
                    f"Joindre d'urgence l'attestation de maintien en activité soudage continue "
                    f"signée par le coordinateur soudage pour prolonger la validité de la qualification."
                ),
                days_elapsed=days_elapsed,
                expiry_date=expiry_date,
            ))

        elif days_elapsed > rule["max_days"] and has_continuity_attestation:
            # Périmée mais maintien documenté → MAJOR (à vérifier par inspecteur)
            expiry_date = qual_date + timedelta(days=rule["max_days"])
            findings.append(self._build_finding(
                rule_key="WELDER_QUALIFICATION",
                fname=fname,
                priority="MAJOR",
                title=f"Qualification Soudeur Périmée mais Maintien en Activité Déclaré — À Vérifier",
                observation=(
                    f"La qualification soudeur date du {qual_date.strftime('%d/%m/%Y')} "
                    f"({days_elapsed} jours, limite {rule['max_days']} jours). "
                    f"Une attestation de maintien en activité a été détectée, mais elle doit être "
                    f"examinée par l'inspecteur pour valider la continuité réelle de l'activité soudage."
                ),
                action_required=(
                    "Présenter les attestations mensuelles originales signées couvrant chaque mois "
                    "depuis la qualification initiale, pour validation par l'inspecteur TPI/ARH."
                ),
                days_elapsed=days_elapsed,
                expiry_date=expiry_date,
            ))

        return findings

    # ──────────────────────────────────────────────────────────────────────────
    # VÉRIFICATION 2 : CERTIFICATS ATEX
    # ──────────────────────────────────────────────────────────────────────────

    def _check_atex_certificates(self, text: str, fname: str) -> List[Dict[str, Any]]:
        findings = []
        rule = VALIDITY_RULES["ATEX_CERTIFICATE"]

        atex_date = self.date_extractor.extract_most_recent_date_near_keyword(
            text,
            keywords=["DATE OF ISSUE", "ISSUED ON", "DATE D'ÉMISSION", "DATE D'EMISSION",
                      "ISSUED:", "CERTIFICATE DATE", "DATE DU CERTIFICAT", "VALID UNTIL",
                      "EXPIRE", "VALABLE JUSQU'AU"],
            window_chars=300
        )

        if atex_date is None:
            return findings  # Date non trouvée — le contrôle de présence est fait par l'agent ATEX

        days_elapsed = (self.today - atex_date).days

        if days_elapsed > rule["max_days"]:
            expiry_date = atex_date + timedelta(days=rule["max_days"])
            findings.append(self._build_finding(
                rule_key="ATEX_CERTIFICATE",
                fname=fname,
                priority="CRITICAL",
                title=f"Certificat ATEX/IECEx Expiré depuis le {expiry_date.strftime('%d/%m/%Y')}",
                observation=(
                    f"Le certificat ATEX / IECEx trouvé dans '{fname}' a été émis le "
                    f"{atex_date.strftime('%d/%m/%Y')} ({days_elapsed} jours écoulés). "
                    f"La directive ATEX 2014/34/UE impose un renouvellement tous les 5 ans "
                    f"({rule['max_days']} jours). Ce certificat est expiré depuis le "
                    f"{expiry_date.strftime('%d/%m/%Y')}."
                ),
                action_required=(
                    "Fournir un certificat ATEX / IECEx renouvelé, émis par un organisme notifié "
                    "(INERIS, LCIE, PTB, Baseefa) couvrant le matériel concerné, avec marquage "
                    "Ex valide et date d'émission récente."
                ),
                days_elapsed=days_elapsed,
                expiry_date=expiry_date,
            ))

        elif days_elapsed > rule["warning_days"]:
            expiry_date = atex_date + timedelta(days=rule["max_days"])
            days_remaining = rule["max_days"] - days_elapsed
            findings.append(self._build_finding(
                rule_key="ATEX_CERTIFICATE",
                fname=fname,
                priority="MAJOR",
                title=f"Certificat ATEX/IECEx Proche de l'Expiration (Expire dans {days_remaining} Jours)",
                observation=(
                    f"Le certificat ATEX dans '{fname}' expire le {expiry_date.strftime('%d/%m/%Y')} "
                    f"dans {days_remaining} jours. Il est recommandé d'engager le renouvellement "
                    f"avant la mise en service de l'installation."
                ),
                action_required=(
                    "Engager dès maintenant le processus de renouvellement du certificat ATEX "
                    f"auprès de l'organisme notifié. Délai moyen de renouvellement : 3 à 6 mois."
                ),
                days_elapsed=days_elapsed,
                expiry_date=expiry_date,
            ))

        return findings

    # ──────────────────────────────────────────────────────────────────────────
    # VÉRIFICATION 3 : VISA CONSULAIRE
    # ──────────────────────────────────────────────────────────────────────────

    def _check_consular_visa(self, text: str, fname: str) -> List[Dict[str, Any]]:
        findings = []
        rule = VALIDITY_RULES["CONSULAR_VISA"]

        has_consular_seal = any(k in text.upper() for k in [
            "VU ET LÉGALISÉ", "VU POUR LÉGALISATION", "VISA DU CONSULAT GÉNÉRAL",
            "SEAL OF THE EMBASSY", "SEAL OF THE CONSULATE", "CONSULATE GENERAL OF ALGERIA"
        ])
        if not has_consular_seal:
            return findings  # Absence de visa gérée par l'agent administratif (DOC-02)

        visa_date = self.date_extractor.extract_most_recent_date_near_keyword(
            text,
            keywords=["CONSULAT", "CONSULATE", "LÉGALISÉ LE", "LEGALISE LE",
                      "VISÉ LE", "VISE LE", "DATE DU VISA", "DATE DE LÉGALISATION",
                      "LEGALIZED ON", "CERTIFIED BY CONSULATE"],
            window_chars=250
        )

        if visa_date is None:
            return findings

        days_elapsed = (self.today - visa_date).days

        if days_elapsed > rule["max_days"]:
            expiry_date = visa_date + timedelta(days=rule["max_days"])
            findings.append(self._build_finding(
                rule_key="CONSULAR_VISA",
                fname=fname,
                priority="CRITICAL",
                title=f"Visa Consulaire Périmé — Légalisation Datant de {days_elapsed} Jours (Max 183 Jours P-CTE-1)",
                observation=(
                    f"La légalisation consulaire trouvée dans '{fname}' date du "
                    f"{visa_date.strftime('%d/%m/%Y')} ({days_elapsed} jours écoulés). "
                    f"La procédure ARH P-CTE-1 exige que les légalisations consulaires ne dépassent "
                    f"pas 6 mois (183 jours) avant la soumission du dossier. "
                    f"Ce visa est expiré depuis le {expiry_date.strftime('%d/%m/%Y')}."
                ),
                action_required=(
                    "Obtenir une nouvelle légalisation consulaire avec une date récente. "
                    "Contacter le fabricant pour fournir un certificat de signatures actualisé, "
                    "visé par la Chambre de Commerce locale ET le Consulat d'Algérie dans le pays d'origine."
                ),
                days_elapsed=days_elapsed,
                expiry_date=expiry_date,
            ))

        return findings

    # ──────────────────────────────────────────────────────────────────────────
    # VÉRIFICATION 4 : CERTIFICATS D'ÉTALONNAGE
    # ──────────────────────────────────────────────────────────────────────────

    def _check_calibration_certs(self, text: str, fname: str) -> List[Dict[str, Any]]:
        findings = []
        rule = VALIDITY_RULES["CALIBRATION_CERTIFICATE"]

        # Chercher soit la date d'étalonnage, soit la date "Next calibration due"
        cal_date = self.date_extractor.extract_most_recent_date_near_keyword(
            text,
            keywords=["CALIBRATED ON", "DATE D'ÉTALONNAGE", "DATE D'ETALONNAGE",
                      "CALIBRATION DATE", "DATE DE CALIBRATION", "ÉTALONNAGE RÉALISÉ LE"],
            window_chars=250
        )
        next_cal_date = self.date_extractor.extract_most_recent_date_near_keyword(
            text,
            keywords=["NEXT CALIBRATION", "PROCHAINE CALIBRATION", "PROCHAIN ÉTALONNAGE",
                      "VALID UNTIL", "EXPIRE LE", "DUE DATE"],
            window_chars=250
        )

        if next_cal_date is not None and next_cal_date < self.today:
            # La date de prochaine calibration est DÉJÀ PASSÉE
            days_overdue = (self.today - next_cal_date).days
            findings.append(self._build_finding(
                rule_key="CALIBRATION_CERTIFICATE",
                fname=fname,
                priority="CRITICAL",
                title=f"Équipement de Mesure Non Recalibré — Échéance Dépassée de {days_overdue} Jours",
                observation=(
                    f"Dans '{fname}', la date de prochaine calibration est fixée au "
                    f"{next_cal_date.strftime('%d/%m/%Y')}, soit {days_overdue} jours AVANT la "
                    f"date d'aujourd'hui ({self.today.strftime('%d/%m/%Y')}). "
                    f"L'équipement de mesure est hors étalonnage valide."
                ),
                action_required=(
                    "Présenter un nouveau certificat d'étalonnage émis par un laboratoire "
                    "accrédité ALGERAC ou équivalent (COFRAC, DAkkS), daté postérieurement à "
                    f"la dernière échéance ({next_cal_date.strftime('%d/%m/%Y')})."
                ),
                days_elapsed=days_overdue,
                expiry_date=next_cal_date,
            ))

        elif cal_date is not None:
            days_elapsed = (self.today - cal_date).days
            if days_elapsed > rule["max_days"]:
                expiry_date = cal_date + timedelta(days=rule["max_days"])
                findings.append(self._build_finding(
                    rule_key="CALIBRATION_CERTIFICATE",
                    fname=fname,
                    priority="CRITICAL",
                    title=f"Certificat d'Étalonnage Expiré ({days_elapsed} Jours > 365 Jours Max)",
                    observation=(
                        f"Le certificat d'étalonnage dans '{fname}' date du "
                        f"{cal_date.strftime('%d/%m/%Y')} ({days_elapsed} jours écoulés). "
                        f"La périodicité maximale d'étalonnage des équipements de mesure est de "
                        f"12 mois (365 jours) selon ISO 9001:2015 et les procédures GCB/Sonatrach. "
                        f"Ce certificat est périmé depuis le {expiry_date.strftime('%d/%m/%Y')}."
                    ),
                    action_required=(
                        "Fournir un nouveau certificat d'étalonnage récent émis par un laboratoire "
                        "accrédité ALGERAC ou COFRAC, avec raccordement aux étalons nationaux."
                    ),
                    days_elapsed=days_elapsed,
                    expiry_date=expiry_date,
                ))

        return findings

    # ──────────────────────────────────────────────────────────────────────────
    # UTILITAIRE : CONSTRUCTION D'UNE REMARQUE NORMALISÉE
    # ──────────────────────────────────────────────────────────────────────────

    def _build_finding(
        self,
        rule_key: str,
        fname: str,
        priority: str,
        title: str,
        observation: str,
        action_required: str,
        days_elapsed: Optional[int],
        expiry_date: Optional[date],
    ) -> Dict[str, Any]:
        rule = VALIDITY_RULES[rule_key]
        return {
            "id": f"REM_TEMP_{uuid.uuid4().hex[:6].upper()}",
            "discipline": self.discipline,
            "agent": self.name,
            "priority": priority,
            "category": f"VALIDITÉ TEMPORELLE — {rule['label'].upper()}",
            "title": title,
            "observation": observation,
            "decree_reference": rule["decree"],
            "article": rule.get("article", rule["decree"]),
            "standard": rule["standard"],
            "document_concerned": fname,
            "page": "Document daté",
            "impact": (
                f"Document ou certification hors validité. Impact direct sur l'acceptabilité "
                f"réglementaire du dossier ARH."
            ),
            "action_required": action_required,
            "deadline_days": 3 if priority == "CRITICAL" else 7,
            "extracted_via": "ARHTemporalReasoner",
            "temporal_metadata": {
                "check_date": self.today.isoformat(),
                "days_elapsed": days_elapsed,
                "expiry_date": expiry_date.isoformat() if expiry_date else None,
                "rule_max_days": rule["max_days"],
            }
        }


# ══════════════════════════════════════════════════════════════════════════════
# UTILITAIRE STANDALONE : vérification rapide d'une date unique
# ══════════════════════════════════════════════════════════════════════════════

def check_date_validity(
    date_str: str,
    rule_key: str,
    today: Optional[date] = None
) -> Dict[str, Any]:
    """
    Fonction utilitaire standalone pour vérifier la validité d'une date unique.

    Args:
        date_str : Date sous forme de texte (ex: "15/01/2024", "January 2024")
        rule_key : Clé de la règle de validité (ex: "WELDER_QUALIFICATION")
        today    : Date de référence (défaut : date du jour)

    Returns:
        Dict avec: is_valid, days_elapsed, days_remaining, status, message
    """
    extractor = ARHDateExtractor()
    dates = extractor.extract_dates_from_text(date_str)
    if not dates:
        return {"is_valid": False, "status": "DATE_NOT_PARSEABLE", "message": f"Impossible de parser la date : '{date_str}'"}

    ref_date = today or date.today()
    parsed_date = dates[0]
    rule = VALIDITY_RULES.get(rule_key)
    if not rule or not rule.get("max_days"):
        return {"is_valid": True, "status": "NO_EXPIRY", "message": "Ce type de document n'a pas de durée de validité limitée."}

    days_elapsed = (ref_date - parsed_date).days
    days_remaining = rule["max_days"] - days_elapsed
    is_valid = days_elapsed <= rule["max_days"]

    return {
        "is_valid": is_valid,
        "parsed_date": parsed_date.isoformat(),
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "expiry_date": (parsed_date + timedelta(days=rule["max_days"])).isoformat(),
        "status": "VALID" if is_valid else "EXPIRED",
        "message": (
            f"Valide : {days_remaining} jours restants."
            if is_valid
            else f"EXPIRÉ depuis {-days_remaining} jours."
        ),
        "rule": rule_key,
        "standard": rule["standard"],
    }


# Instance singleton réutilisable
arh_temporal_reasoner = ARHTemporalReasoningAgent()
