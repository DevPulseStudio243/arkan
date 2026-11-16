"""
arh_reserve_comparator.py
==========================
Module de Comparaison de Révisions et de Levée de Réserves ARH.

Résout le workflow le plus courant dans le quotidien d'un ingénieur QC chez GCB :
  ► Le dossier ARH Rev 0 a reçu N réserves de l'ARH (ex: Lettre ARH Réf. 1198/ARH/CT/MB-BAH/2025)
  ► Le fournisseur soumet une Rev 1 pour "lever" ces réserves.
  ► L'ingénieur QC doit vérifier point par point que CHAQUE réserve est bien levée.
  ► Ce module automatise cette vérification sémantique.

Ce module :
  1. Charge les réserves ARH stockées pour ce dossier (depuis SQLite arh_dossiers.db).
  2. Analyse le nouveau document Rev 1 pour trouver les preuves de correction.
  3. Classe chaque réserve : LEVÉE / PARTIELLEMENT LEVÉE / NON LEVÉE / NOUVELLE NON-CONFORMITÉ.
  4. Génère un rapport de levée de réserves structuré.

Exemple réel traité :
  Lettre ARH Réf. 1198/ARH/CT/MB-BAH/2025 (dossier LEVEE DE RESERVES ROH1 46Km)
  Réserves :
    - Plaques signalétiques en étiquette → NON LEVÉE
    - Poinçon TPI absent → NON LEVÉE
    - Test hydro sans BV → PARTIELLEMENT LEVÉE (clarification insuffisante)
"""

from __future__ import annotations

import re
import uuid
import json
import sqlite3
import logging
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("ARHReserveComparator")

_ARH_DB_PATH = Path(__file__).parent / "arh_dossiers.db"

# ══════════════════════════════════════════════════════════════════════════════
# STATUTS DE LEVÉE DE RÉSERVE
# ══════════════════════════════════════════════════════════════════════════════

RESERVE_STATUS = {
    "LIFTED":        {"label": "✅ Réserve Levée",                  "code": "LIFTED",       "score_impact": 0},
    "PARTIAL":       {"label": "⚠️ Réserve Partiellement Levée",   "code": "PARTIAL",      "score_impact": -8},
    "NOT_LIFTED":    {"label": "❌ Réserve Non Levée",              "code": "NOT_LIFTED",   "score_impact": -20},
    "NEW_NC":        {"label": "🆕 Nouvelle Non-Conformité Détectée","code": "NEW_NC",       "score_impact": -25},
    "INSUFFICIENT":  {"label": "⚠️ Preuve Insuffisante",            "code": "INSUFFICIENT", "score_impact": -12},
}

# ══════════════════════════════════════════════════════════════════════════════
# RÈGLES DE VÉRIFICATION DE LEVÉE DE RÉSERVES
# (Basées sur les cas réels GCB/ARH extraits des données indexées)
# ══════════════════════════════════════════════════════════════════════════════

# Chaque règle définit :
#   - keywords_reserve : mots indiquant cette réserve dans le document ARH
#   - proof_keywords   : mots qui PROUVENT que la réserve est levée
#   - proof_patterns   : patterns regex de preuve
#   - denial_patterns  : patterns qui RÉFUTENT la preuve (faux positif fournisseur)
#   - min_proof_count  : nb minimum de preuves textuelles pour valider la levée

RESERVE_VERIFICATION_RULES: Dict[str, Dict[str, Any]] = {

    "NAMEPLATE_STICKER": {
        "label": "Plaque Signalétique en Étiquette Adhésive",
        "keywords_reserve": [
            "PLAQUE SIGNALETIQUE", "PLAQUE SIGNALÉTIQUE", "ETIQUETTE", "AUTOCOLLANT",
            "STICKER", "ADHESIVE", "NAMEPLATE"
        ],
        "proof_keywords": [
            "PLAQUE METALIQUE", "PLAQUE METALLIQUE", "METAL NAMEPLATE",
            "STAINLESS STEEL PLATE", "INOX 316", "RIVETED", "RIVETEE",
            "GRAVEE MECANIQUEMENT", "MECHANICALLY ENGRAVED",
            "ACIER INOXYDABLE", "LAITON", "BRASS NAMEPLATE"
        ],
        "proof_patterns": [
            r'plaque\s+(?:en\s+)?(?:acier|inox|métal|metal|laiton)\b',
            r'(?:riveted|rivetée|boulonnée)\s+(?:nameplate|plaque)',
            r'(?:nameplate|plaque\s+signalétique)\s+[^\n]*(?:inox|stainless|316)',
        ],
        "denial_patterns": [
            r'\bétiquette\b',
            r'\bsticker\b',
            r'\badhési[fv]',
        ],
        "min_proof_count": 1,
    },

    "NAMEPLATE_PHOTO": {
        "label": "Photo des Plaques Signalétiques Non Fournie",
        "keywords_reserve": [
            "PHOTOGRAPHIE", "PHOTO", "PHOTOGRAPH", "IMAGE", "PICTURE",
            "JOINT", "JOINDRE", "FOURNIR", "JOINTER"
        ],
        "proof_keywords": [
            "PHOTO", "PHOTOGRAPHIE", "IMAGE", "FIGURE", "ANNEXE PHOTO",
            "SEE ATTACHED", "VOIR ANNEXE", "CI-DESSOUS", "CI-JOINT",
            "ATTACHED HEREWITH", "PIÈCE JOINTE"
        ],
        "proof_patterns": [
            r'(?:photo|image|figure)\s*(?:n°|#|:)?\s*\d+',
            r'(?:voir|see)\s+(?:annexe|attached|figure|photo)',
            r'(?:joint|jointe?s?|attached)\s+(?:en|ci-|herewith)',
        ],
        "denial_patterns": [],
        "min_proof_count": 1,
    },

    "TPI_STAMP_MISSING": {
        "label": "Poinçon de l'Organisme TPI Absent sur la Plaque Signalétique",
        "keywords_reserve": [
            "POINÇON", "POINCON", "STAMP", "CACHET", "TPI", "TIERS HABILITE",
            "TIERS HABILITÉ", "TUV", "BUREAU VERITAS", "SGS", "APAVE"
        ],
        "proof_keywords": [
            "POINÇON TPI", "POINCON TPI", "TPI STAMP", "STAMPED BY TPI",
            "CACHET TPI", "APPOSÉ", "APPOSE", "APPLIED", "AFFIXED"
        ],
        "proof_patterns": [
            r'(?:poinçon|stamp)\s+(?:de\s+la\s+)?(?:TPI|tiers|third)',
            r'(?:TPI|tiers\s+habilité)\s+[^\n]*(?:poinçon|stamp|cachet)',
            r'(?:stamped|poinçonné[e]?)\s+(?:by\s+)?(?:TPI|bureau\s+veritas|tuv)',
        ],
        "denial_patterns": [
            # Si le document parle de l'absence sans la corriger
            r'absence\s+(?:du\s+)?poinçon',
            r'poinçon\s+(?:non|absent|manquant)',
        ],
        "min_proof_count": 1,
    },

    "HYDROTEST_WITHOUT_TPI": {
        "label": "Test Hydrostatique Réalisé sans Présence de l'Organisme TPI Délégué",
        "keywords_reserve": [
            "HYDROSTATIQUE", "HYDROSTATIC", "TEST", "ESSAI", "EPREUVE",
            "BUREAU VERITAS", "TUV", "TPI", "PRESENCE", "DELEGUE", "DÉLÉGUÉ"
        ],
        "proof_keywords": [
            "PROCÈS VERBAL", "PV DE RÉCEPTION", "TEST WITNESSED BY",
            "WITNESSED BY BUREAU VERITAS", "EN PRÉSENCE DE BUREAU VERITAS",
            "CERTIFICATE SIGNED BY TPI", "TPI WITNESS REPORT",
            "RAPPORT DE SURVEILLANCE TPI", "ATTESTATION TPI"
        ],
        "proof_patterns": [
            r'(?:hydrostatic|hydrostatique)\s+test[^\n]*(?:witnessed|en\s+présence)',
            r'(?:bureau\s+veritas|tuv|sgs)\s+[^\n]*(?:witness|témoin|présence)\s+[^\n]*(?:hydro|test)',
            r'witness\s+(?:report|attestation)\s+[^\n]*(?:bureau\s+veritas|tpi)',
        ],
        "denial_patterns": [
            # Cas du dossier ROH1 : le fournisseur donne des coordonnées BV au lieu d'une attestation
            r'(?:adresse|address|website|site\s+web|contact|amersfoort)',
            r'date\s+et\s+lieu\s+de\s+cr[éèe]ation',
            r'lieu\s+de\s+cr[éèe]ation\s+de\s+bureau\s+veritas',
            r"c'est\s+la\s+date",
            r'mentionn[éèe]e\s+.+\s+interieur\s+du\s+cachet',
        ],
        "min_proof_count": 1,
    },

    "CONSULAR_VISA_MISSING": {
        "label": "Légalisation Consulaire des Signatures du Fabricant Manquante",
        "keywords_reserve": [
            "CONSULAT", "CONSULATE", "LÉGALISATION", "LEGALISATION",
            "VISA CONSULAIRE", "CHAMBRE DE COMMERCE", "CHAMBER OF COMMERCE"
        ],
        "proof_keywords": [
            "LÉGALISÉ", "LEGALISE", "VISÉ PAR LE CONSULAT", "CONSULATE VISA",
            "CHAMBRE DE COMMERCE CACHET", "CHAMBRE DE COMMERCE STAMP",
            "LÉGALISATION EFFECTUÉE", "VISA APPOSÉ"
        ],
        "proof_patterns": [
            r'(?:légalisé[e]?|certified)\s+(?:par|by)\s+(?:le\s+)?consulat',
            r'(?:consulat)\s+[^\n]*(?:algér|algeria)',
            r'(?:chambre\s+de\s+commerce)\s+[^\n]*(?:visa|stamp|cachet)',
        ],
        "denial_patterns": [],
        "min_proof_count": 1,
    },

    "ITP_NO_TPI_COLUMN": {
        "label": "Colonne TPI/ARH Absente dans la Matrice ITP",
        "keywords_reserve": [
            "ITP", "PLAN D'INSPECTION", "INSPECTION TEST PLAN",
            "COLONNE TPI", "TPI/ARH", "PARTIES INTERVENANTES"
        ],
        "proof_keywords": [
            "TPI", "ARH", "THIRD PARTY", "TIERS HABILITÉ", "VERITAS", "TUV",
            "COLUMN TPI", "COLONNE TPI", "INTERVENANT TPI"
        ],
        "proof_patterns": [
            r'(?:TPI|tiers\s+habilité|third\s+party)\s*(?:\/|,)?\s*(?:ARH)?',
            r'(?:colonne|column)\s+(?:TPI|tiers)',
            r'(?:GCB|SH|SONATRACH)\s*[,/]\s*(?:TPI|ARH)',
        ],
        "denial_patterns": [],
        "min_proof_count": 1,
    },

    "HYDROTEST_NOT_HOLD_POINT": {
        "label": "Test Hydrostatique Non en Point d'Arrêt (H) pour TPI/ARH",
        "keywords_reserve": [
            "HOLD POINT", "POINT D'ARRET", "POINT D'ARRÊT",
            "HYDROSTATIQUE", "HYDROSTATIC", "TPI/ARH", "H ",
        ],
        "proof_keywords": [
            "HOLD", "H ", "POINT D'ARRÊT H", "HOLD POINT H",
            "HYDROSTATIQUE.*H", "HYDROSTATIC.*HOLD"
        ],
        "proof_patterns": [
            r'(?:hydrostatic|hydro|épreuve)\s+[^\n]*\bH\b',
            r'\bhold\s+point\b\s+[^\n]*(?:hydro|hydrostatic)',
            r"(?:point\s+d.arr.t|hold)\s*:\s*H",
        ],
        "denial_patterns": [
            r'\bW\b\s*(?:witness)',    # W (Witness) est insuffisant
            r'\bR\b\s*(?:review)',    # R (Review) est insuffisant
        ],
        "min_proof_count": 1,
    },

    "WPQ_IN_PRELIMINARY": {
        "label": "WPQ Inclus à Tort dans le Dossier Préliminaire (Doit Être Retiré)",
        "keywords_reserve": [
            "WPQ", "WOPQ", "QUALIFICATION SOUDEUR",
            "RETIRER", "REMOVE", "PRELIMINARY", "PRÉLIMINAIRE"
        ],
        "proof_keywords": [
            "WPQ RETIRÉ", "WPQ REMOVED", "WPQ NOT INCLUDED",
            "DOSSIER PRÉLIMINAIRE SANS WPQ", "PRELIMINARY WITHOUT WPQ"
        ],
        "proof_patterns": [
            r'(?:wopq|wpq)\s+(?:retiré[e]?|removed|not\s+included)',
            r'(?:dossier\s+préliminaire|preliminary\s+file)\s+[^\n]*(?:sans|without)\s+(?:wopq|wpq)',
        ],
        "denial_patterns": [
            r'\bwopq\b',
            r'\bwpq\b',
        ],
        "min_proof_count": 1,
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# ANALYSEUR SÉMANTIQUE DE LEVÉE DE RÉSERVE
# ══════════════════════════════════════════════════════════════════════════════

class ARHReserveSemanticAnalyzer:
    """
    Analyse le texte d'un document Rev 1 pour déterminer si une réserve ARH
    spécifique est levée, en se basant sur des preuves textuelles positives
    ET en vérifiant l'absence de patterns de dénégation.
    """

    def analyze_reserve_in_text(
        self,
        reserve_type: str,
        text: str,
        reserve_description: str,
    ) -> Tuple[str, str, float]:
        """
        Analyse si la réserve identifiée par `reserve_type` est levée dans `text`.

        Returns:
            (status_code, evidence_text, confidence_score)
            - status_code : "LIFTED", "PARTIAL", "NOT_LIFTED", "INSUFFICIENT"
            - evidence_text : Extrait de texte prouvant (ou réfutant) la levée
            - confidence_score : 0.0 à 1.0
        """
        rule = RESERVE_VERIFICATION_RULES.get(reserve_type)
        if not rule:
            # Pas de règle connue → analyse textuelle générique
            return self._generic_analysis(reserve_description, text)

        tu_text = text.upper()
        text_lower = text.lower()

        # Compter les preuves positives
        positive_evidence: List[str] = []
        denial_evidence: List[str] = []

        # Vérifier les mots-clés de preuve
        for kw in rule.get("proof_keywords", []):
            if kw.upper() in tu_text:
                # Extraire le contexte autour du mot-clé
                idx = tu_text.find(kw.upper())
                ctx = text[max(0, idx - 60): idx + len(kw) + 60].strip()
                positive_evidence.append(ctx)

        # Vérifier les patterns de preuve
        for pat in rule.get("proof_patterns", []):
            m = re.search(pat, text_lower, re.IGNORECASE)
            if m:
                start = max(0, m.start() - 40)
                end = min(len(text), m.end() + 80)
                ctx = text[start:end].strip()
                positive_evidence.append(ctx)

        # Vérifier les patterns de dénégation
        for pat in rule.get("denial_patterns", []):
            m = re.search(pat, text_lower, re.IGNORECASE)
            if m:
                start = max(0, m.start() - 30)
                end = min(len(text), m.end() + 60)
                ctx = text[start:end].strip()
                denial_evidence.append(ctx)

        min_proof = rule.get("min_proof_count", 1)
        has_sufficient_proof = len(positive_evidence) >= min_proof
        has_denial = len(denial_evidence) > 0

        if has_sufficient_proof and not has_denial:
            # Réserve bien levée
            evidence_summary = positive_evidence[0][:200] if positive_evidence else ""
            return "LIFTED", evidence_summary, 0.9

        elif has_sufficient_proof and has_denial:
            # Preuve présente mais contredite par un pattern de dénégation
            # → Cas typique du dossier ROH1 : "Bureau Veritas" présent mais expliqué comme coordinées
            evidence_summary = (
                f"PREUVE TROUVÉE : {positive_evidence[0][:100]}\n"
                f"MAIS RÉFUTÉE PAR : {denial_evidence[0][:100]}"
            )
            return "INSUFFICIENT", evidence_summary, 0.3

        elif not has_sufficient_proof and denial_evidence:
            # Aucune preuve + pattern de dénégation → clairement non levée
            evidence_summary = f"INDICATION DE NON-LEVÉE : {denial_evidence[0][:150]}"
            return "NOT_LIFTED", evidence_summary, 0.85

        else:
            # Aucune preuve dans les deux sens → ne peut pas conclure
            return "NOT_LIFTED", "Aucune preuve de correction trouvée dans le document.", 0.6

    def _generic_analysis(
        self, reserve_description: str, text: str
    ) -> Tuple[str, str, float]:
        """Analyse générique pour les réserves sans règle dédiée."""
        tu_text = text.upper()
        desc_upper = reserve_description.upper()

        # Chercher des mentions de la réserve originale
        key_terms = [w for w in desc_upper.split() if len(w) > 4]
        found_terms = sum(1 for t in key_terms if t in tu_text)

        if found_terms == 0:
            return "NOT_LIFTED", "Réserve non mentionnée dans le document de levée.", 0.5

        # Chercher des indicateurs positifs de résolution
        resolution_indicators = [
            "CORRIGÉ", "CORRECTED", "MODIFIÉ", "MODIFIED", "UPDATED", "MIS À JOUR",
            "LEVÉ", "LIFTED", "CLOSED", "RÉVISÉ", "REVISED", "FOURNI", "PROVIDED",
            "AJOUTÉ", "ADDED", "COMPLÉTÉ", "COMPLETED", "RÉSOLU", "RESOLVED"
        ]
        has_resolution = any(ind in tu_text for ind in resolution_indicators)

        if has_resolution and found_terms >= 2:
            return "PARTIAL", "Correction probable mais non vérifiable avec précision.", 0.5
        else:
            return "NOT_LIFTED", "Aucune indication claire de correction.", 0.4


# ══════════════════════════════════════════════════════════════════════════════
# COMPARATEUR PRINCIPAL DE RÉVISIONS ARH
# ══════════════════════════════════════════════════════════════════════════════

class ARHReserveComparator:
    """
    Orchestre le processus complet de vérification de levée de réserves ARH.
    Compare Rev 0 (réserves ARH) avec Rev 1 (dossier corrigé du fournisseur).
    """

    def __init__(self):
        self.name = "Comparateur de Révisions & Levée de Réserves ARH"
        self.discipline = "LEVÉE DE RÉSERVES"
        self.analyzer = ARHReserveSemanticAnalyzer()

    # ─── Interface principale ─────────────────────────────────────────────────

    def compare_revisions(
        self,
        reserves_list: List[Dict[str, Any]],
        new_docs: List[Dict[str, Any]],
        dossier_id: str,
        equipment_tag: str,
    ) -> Dict[str, Any]:
        """
        Compare les réserves ARH avec le nouveau dossier Rev N et génère
        le rapport de levée de réserves.

        Args:
            reserves_list : Liste des réserves ARH [{id, type, description, priority}]
            new_docs      : Documents du dossier Rev N soumis par le fournisseur
            dossier_id    : ID du dossier ARH dans la DB
            equipment_tag : TAG de l'équipement

        Returns:
            Rapport structuré de levée de réserves avec statut par point.
        """
        full_text_rev1 = " ".join([d.get("text", "") for d in new_docs])
        logger.info(f"[ARH-ReserveComparator] Analyse de {len(reserves_list)} réserves pour {equipment_tag}")

        results: List[Dict[str, Any]] = []
        lifted_count = 0
        partial_count = 0
        not_lifted_count = 0
        insufficient_count = 0

        for reserve in reserves_list:
            res_id = reserve.get("id", str(uuid.uuid4()))
            res_type = reserve.get("type", "")
            res_description = reserve.get("description", reserve.get("title", ""))
            res_priority = reserve.get("priority", "MAJOR")
            res_arh_ref = reserve.get("arh_letter_ref", "")

            # Analyser la levée dans le texte de Rev 1
            status_code, evidence, confidence = self.analyzer.analyze_reserve_in_text(
                reserve_type=res_type,
                text=full_text_rev1,
                reserve_description=res_description,
            )

            status_info = RESERVE_STATUS.get(status_code, RESERVE_STATUS["NOT_LIFTED"])

            result_entry = {
                "reserve_id": res_id,
                "reserve_type": res_type,
                "reserve_description": res_description,
                "reserve_priority": res_priority,
                "arh_letter_ref": res_arh_ref,
                "status_code": status_code,
                "status_label": status_info["label"],
                "confidence": round(confidence, 2),
                "evidence_extracted": evidence,
                "score_impact": status_info["score_impact"],
                "finding": None,  # Sera rempli si non levée
            }

            # Comptes
            if status_code == "LIFTED":
                lifted_count += 1
            elif status_code == "PARTIAL":
                partial_count += 1
            elif status_code == "INSUFFICIENT":
                insufficient_count += 1
            else:
                not_lifted_count += 1

            # Générer une remarque ARH si la réserve n'est pas levée
            if status_code in ("NOT_LIFTED", "INSUFFICIENT", "PARTIAL"):
                result_entry["finding"] = self._build_reserve_finding(
                    reserve=reserve,
                    status_code=status_code,
                    evidence=evidence,
                    confidence=confidence,
                )

            results.append(result_entry)

        # Score de levée de réserves (différent du score de conformité global)
        total = len(reserves_list)
        lift_score = round((lifted_count / total) * 100, 1) if total > 0 else 100.0
        base_score = 100.0 + sum(r["score_impact"] for r in results)
        lift_score_weighted = max(0.0, min(100.0, base_score))

        # Décision globale de levée
        if not_lifted_count == 0 and insufficient_count == 0:
            decision = "DOSSIER LEVÉE DE RÉSERVES ACCEPTÉ" if partial_count == 0 else "DOSSIER ACCEPTÉ AVEC RÉSERVES PARTIELLES"
        else:
            decision = f"DOSSIER REJETÉ — {not_lifted_count} Réserve(s) Non Levée(s)"

        report = {
            "dossier_id": dossier_id,
            "equipment_tag": equipment_tag,
            "analysis_date": datetime.date.today().isoformat(),
            "total_reserves": total,
            "lifted": lifted_count,
            "partial": partial_count,
            "insufficient": insufficient_count,
            "not_lifted": not_lifted_count,
            "lift_score_pct": lift_score_weighted,
            "decision": decision,
            "results": results,
            # Listes filtrées pour l'accès rapide
            "open_reserves": [r for r in results if r["status_code"] != "LIFTED"],
            "findings": [r["finding"] for r in results if r["finding"] is not None],
        }

        logger.info(
            f"[ARH-ReserveComparator] Résultat : {lifted_count}✅ {partial_count}⚠️ "
            f"{not_lifted_count}❌ sur {total} réserves. Score levée : {lift_score_weighted}%"
        )
        return report

    # ─── Chargement des réserves depuis la base de données ───────────────────

    def load_reserves_from_db(self, dossier_id: str) -> List[Dict[str, Any]]:
        """
        Charge les réserves ARH d'un dossier depuis la base de données SQLite.
        Les réserves sont stockées dans data_json['findings'] avec status='OPEN'.
        """
        try:
            conn = sqlite3.connect(str(_ARH_DB_PATH), timeout=10)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT data_json FROM arh_dossiers WHERE dossier_id = ?", (dossier_id,)
            ).fetchone()
            conn.close()

            if not row:
                logger.warning(f"[ARH-ReserveComparator] Dossier {dossier_id} non trouvé en DB.")
                return []

            data = json.loads(row["data_json"])
            findings = data.get("findings", [])

            # Filtrer les réserves ouvertes (CRITICAL et MAJOR non levées)
            open_reserves = [
                {
                    "id": f.get("id", str(uuid.uuid4())),
                    "type": self._infer_reserve_type(f),
                    "description": f.get("title", f.get("observation", "")),
                    "priority": f.get("priority", "MAJOR"),
                    "arh_letter_ref": data.get("arh_letter_ref", ""),
                    "category": f.get("category", ""),
                    "action_required": f.get("action_required", ""),
                }
                for f in findings
                if f.get("priority") in ("CRITICAL", "MAJOR")
            ]

            logger.info(f"[ARH-ReserveComparator] {len(open_reserves)} réserves chargées pour dossier {dossier_id}.")
            return open_reserves

        except Exception as e:
            logger.error(f"[ARH-ReserveComparator] Erreur chargement DB : {e}")
            return []

    def load_reserves_from_arh_letter_text(self, arh_letter_text: str, arh_ref: str = "") -> List[Dict[str, Any]]:
        """
        Extrait les réserves ARH directement depuis le texte d'une lettre ARH
        (ex: lettre Réf. 1198/ARH/CT/MB-BAH/2025).

        Supporte le format réel des lettres ARH algériennes :
          "RESERVE ARH : ► Absence du poinçon de l'organisme tiers habilité (TUV)"
        """
        reserves = []
        tu = arh_letter_text.upper()

        # Extraire les blocs de réserves
        # Pattern : RESERVE ARH ou RÉSERVE ARH suivi de puces/tirets/flèches
        reserve_sections = re.findall(
            r'(?:RÉSERVE|RESERVE)\s+ARH\s*:\s*(.*?)(?=(?:RÉSERVE|RESERVE)\s+ARH\s*:|LETTRE\s+ARH|$)',
            tu,
            re.DOTALL
        )

        for section in reserve_sections:
            # Extraire les lignes individuelles (puces ►, -, •, *)
            items = re.findall(r'[►▶\-•\*✓✗]\s*(.+?)(?=\n|[►▶\-•\*]|$)', section.strip())
            for item in items:
                item = item.strip()
                if len(item) < 10:
                    continue
                reserve_type = self._infer_reserve_type({"title": item, "category": "", "observation": item})
                reserves.append({
                    "id": f"ARH_RESERVE_{uuid.uuid4().hex[:6].upper()}",
                    "type": reserve_type,
                    "description": item,
                    "priority": "CRITICAL" if any(k in item for k in ["ABSENT", "MANQUANT", "NON RÉALISÉ", "NON REALISE"]) else "MAJOR",
                    "arh_letter_ref": arh_ref,
                    "category": "RÉSERVE ARH OFFICIELLE",
                })

        logger.info(f"[ARH-ReserveComparator] {len(reserves)} réserves extraites depuis la lettre ARH '{arh_ref}'.")
        return reserves

    # ─── Inférence du type de réserve depuis le texte ────────────────────────

    def _infer_reserve_type(self, finding: Dict[str, Any]) -> str:
        """
        Infère le type de règle de vérification à partir du texte d'une réserve.
        """
        text = (
            finding.get("title", "") + " " +
            finding.get("category", "") + " " +
            finding.get("observation", "")
        ).upper()

        if any(k in text for k in ["ÉTIQUETTE", "STICKER", "ADHÉSIF", "ADHESIF", "AUTOCOLLANT"]):
            return "NAMEPLATE_STICKER"
        if any(k in text for k in ["PHOTO", "PHOTOGRAPHIE", "IMAGE"]):
            return "NAMEPLATE_PHOTO"
        if any(k in text for k in ["POINÇON", "POINCON", "TPI STAMP", "CACHET TPI"]):
            return "TPI_STAMP_MISSING"
        if any(k in text for k in ["HYDROSTATIQUE", "HYDROSTATIC", "BUREAU VERITAS", "TPI"]) and \
           any(k in text for k in ["PRÉSENCE", "PRESENCE", "TÉMOIN", "WITNESS", "DÉLÉGUÉ", "DELEGUE"]):
            return "HYDROTEST_WITHOUT_TPI"
        if any(k in text for k in ["CONSULAT", "LÉGALISATION", "LEGALISATION", "VISA CONSULAIRE"]):
            return "CONSULAR_VISA_MISSING"
        if any(k in text for k in ["ITP", "PLAN D'INSPECTION", "COLONNE TPI"]):
            return "ITP_NO_TPI_COLUMN"
        if any(k in text for k in ["HOLD POINT", "POINT D'ARRÊT", "POINT D'ARRET"]):
            return "HYDROTEST_NOT_HOLD_POINT"
        if any(k in text for k in ["WPQ", "WOPQ"]) and "RETIRER" in text:
            return "WPQ_IN_PRELIMINARY"
        return "GENERIC"

    # ─── Construction d'une remarque normalisée pour une réserve non levée ──

    def _build_reserve_finding(
        self,
        reserve: Dict[str, Any],
        status_code: str,
        evidence: str,
        confidence: float,
    ) -> Dict[str, Any]:
        status_info = RESERVE_STATUS.get(status_code, RESERVE_STATUS["NOT_LIFTED"])
        priority = "CRITICAL" if status_code == "NOT_LIFTED" else "MAJOR"
        arh_ref = reserve.get("arh_letter_ref", "Lettre ARH")

        return {
            "id": f"REM_LIFT_{uuid.uuid4().hex[:6].upper()}",
            "discipline": self.discipline,
            "agent": self.name,
            "priority": priority,
            "category": f"LEVÉE DE RÉSERVES — {status_info['label'].upper()}",
            "title": (
                f"{status_info['label']} : {reserve.get('description', 'Réserve ARH')[:120]}"
            ),
            "observation": (
                f"La réserve ARH '{reserve.get('description', '')}' émise par '{arh_ref}' "
                f"n'a pas été levée de manière satisfaisante dans le dossier Rev soumis.\n"
                f"Analyse sémantique : {status_info['label']} (confiance : {confidence*100:.0f}%).\n"
                f"Éléments analysés : {evidence[:300] if evidence else 'Aucune preuve de correction trouvée.'}"
            ),
            "decree_reference": f"Réserve ARH : {arh_ref}",
            "article": "Levée de Réserves Obligatoire",
            "standard": "Procédure ARH P-CTE-1",
            "document_concerned": "Dossier de Levée de Réserves (Rev soumise)",
            "page": "Document de levée de réserves",
            "impact": (
                "Réserve maintenue par l'ARH. L'équipement ne peut pas recevoir "
                "l'autorisation de mise en produit (Décret 21-257) tant que toutes "
                "les réserves ne sont pas levées."
            ),
            "action_required": reserve.get(
                "action_required",
                "Corriger et soumettre une nouvelle révision du dossier répondant point par point à cette réserve ARH."
            ),
            "deadline_days": 5,
            "extracted_via": "ARHReserveComparator",
            "reserve_metadata": {
                "reserve_id": reserve.get("id"),
                "reserve_type": reserve.get("type"),
                "arh_ref": arh_ref,
                "status_code": status_code,
                "confidence": confidence,
            }
        }


# ══════════════════════════════════════════════════════════════════════════════
# INSTANCE SINGLETON
# ══════════════════════════════════════════════════════════════════════════════

arh_reserve_comparator = ARHReserveComparator()
