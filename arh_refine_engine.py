"""
arh_refine_engine.py
====================
Moteur d'Auto-Amélioration & Rétroaction Continue (/refine Loop)
Inspiré du paradigme Prime Agent pour ARKAN -> ARH Management.

Permet:
1. L'ingestion des arbitrages des inspecteurs ARH (validation, rejet de fausse réserve, concession acceptée).
2. L'apprentissage continu des dérogations constructeurs et règles spécifiques au projet.
3. La persistance SQLite (table arh_refine_rules) et la mise à jour du Knowledge Graph.
4. L'application automatique des règles raffinées pour éliminer les faux positifs récurrents.
"""

from __future__ import annotations
import os
import re
import json
import uuid
import sqlite3
import datetime
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger("ARHRefineEngine")

_DB_PATH = Path(r"d:\DATA BASE IA\arh_dossiers.db")

def _init_refine_tables():
    """Initialise les tables SQLite dédiées à la boucle /refine."""
    with sqlite3.connect(str(_DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arh_refine_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id TEXT UNIQUE,
                dossier_id TEXT,
                finding_id TEXT,
                verdict TEXT,
                category TEXT,
                finding_title TEXT,
                inspector_notes TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arh_refine_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id TEXT UNIQUE,
                rule_type TEXT,
                category TEXT,
                keyword_trigger TEXT,
                vendor_name TEXT,
                equipment_type TEXT,
                action TEXT,
                justification TEXT,
                active INTEGER DEFAULT 1,
                created_at TEXT
            )
        """)
        conn.commit()

# Initialiser à l'import
try:
    _init_refine_tables()
except Exception as _e:
    logger.warning("[ARH-Refine] Erreur initialisation tables SQLite: %s", _e)


import unicodedata

def _normalize_text(text: str) -> str:
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(text))
    ascii_text = "".join([c for c in nfkd if not unicodedata.combining(c)])
    normalized = re.sub(r'[^A-Z0-9]', ' ', ascii_text.upper())
    return re.sub(r'\s+', ' ', normalized).strip()


class ARHRefineEngine:
    """
    Gestionnaire de la boucle de raffinement et d'apprentissage continu.
    """

    def record_feedback(
        self,
        dossier_id: str,
        finding_id: str,
        verdict: str,
        inspector_notes: str,
        finding_data: Optional[Dict[str, Any]] = None,
        vendor_name: Optional[str] = None,
        equipment_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Enregistre un retour d'inspecteur ARH et dérive une règle d'amélioration si applicable.
        
        verdict:
            - 'CONFIRMED' : Réserve confirmée valide par l'inspecteur.
            - 'INVALIDATED_FALSE_POSITIVE' : Faux positif détecté par l'IA (règle trop stricte).
            - 'ACCEPTED_CONCESSION' : Dérogation technique contractuelle acceptée pour ce constructeur.
        """
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fid = f"FB_{uuid.uuid4().hex[:8].upper()}"
        f_data = finding_data or {}
        category = f_data.get("category", "GÉNÉRAL")
        title = f_data.get("title", "")

        with sqlite3.connect(str(_DB_PATH)) as conn:
            conn.execute("""
                INSERT INTO arh_refine_feedback 
                (feedback_id, dossier_id, finding_id, verdict, category, finding_title, inspector_notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (fid, dossier_id, finding_id, verdict.upper(), category, title, inspector_notes, now))
            conn.commit()

        created_rule = None
        # Si la réserve est rejetée comme faux positif ou acceptée comme dérogation, créer une règle raffinée
        if verdict.upper() in ("INVALIDATED_FALSE_POSITIVE", "ACCEPTED_CONCESSION"):
            created_rule = self._derive_rule_from_feedback(
                category=category,
                title=title,
                notes=inspector_notes,
                vendor_name=vendor_name,
                equipment_type=equipment_type,
                verdict=verdict.upper()
            )

        try:
            from arh_knowledge_graph import ARHKnowledgeGraph
            kg = ARHKnowledgeGraph()
            node_id = f"FB_{finding_id}"
            kg.add_node(
                node_id=node_id,
                node_type="INSPECTOR_FEEDBACK",
                name=title or finding_id,
                dossier_id=dossier_id,
                properties={"verdict": verdict.upper(), "notes": inspector_notes, "created_at": now}
            )
            if vendor_name:
                v_node = f"VENDOR_{vendor_name.upper()}"
                kg.add_node(v_node, "Fournisseur", vendor_name)
                kg.add_edge(node_id, v_node, "FEEDBACK_TARGET")
        except Exception as e_kg:
            logger.warning("[ARH-Refine] Erreur synchronisation Knowledge Graph: %s", e_kg)

        return {
            "status": "SUCCESS",
            "feedback_id": fid,
            "verdict": verdict.upper(),
            "rule_created": created_rule is not None,
            "rule": created_rule
        }

    def _derive_rule_from_feedback(
        self,
        category: str,
        title: str,
        notes: str,
        vendor_name: Optional[str],
        equipment_type: Optional[str],
        verdict: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extrait dynamiquement un mot-clé ou pattern technique à partir des notes de l'inspecteur.
        """
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rid = f"RULE_{uuid.uuid4().hex[:6].upper()}"

        norm_title = _normalize_text(title)
        words = [w for w in norm_title.split() if len(w) >= 4 and w not in ["DANS", "POUR", "AVEC", "SANS", "CETTE", "SUR", "DELA", "PLUS", "TOUT"]]
        trigger = " ".join(words[:4]) if words else norm_title[:30]

        action = "SUPPRESS" if verdict == "INVALIDATED_FALSE_POSITIVE" else "DOWNGRADE_TO_INFO"

        with sqlite3.connect(str(_DB_PATH)) as conn:
            conn.execute("""
                INSERT INTO arh_refine_rules
                (rule_id, rule_type, category, keyword_trigger, vendor_name, equipment_type, action, justification, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """, (
                rid,
                verdict,
                category,
                trigger,
                (vendor_name or "").upper(),
                (equipment_type or "").upper(),
                action,
                notes,
                now
            ))
            conn.commit()

        logger.info("[ARH-Refine] Nouvelle règle d'amélioration créée : %s [%s] -> %s", rid, trigger, action)
        return {
            "rule_id": rid,
            "rule_type": verdict,
            "category": category,
            "keyword_trigger": trigger,
            "action": action,
            "justification": notes
        }

    def get_active_rules(
        self,
        vendor_name: Optional[str] = None,
        equipment_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retourne la liste des règles de raffinement actives en base."""
        with sqlite3.connect(str(_DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM arh_refine_rules WHERE active = 1").fetchall()
            
        rules = []
        v_upper = (vendor_name or "").strip().upper()
        eq_upper = (equipment_type or "").strip().upper()

        for r in rows:
            rule_v = (r["vendor_name"] or "").strip().upper()
            rule_eq = (r["equipment_type"] or "").strip().upper()

            # Filtrer par vendor si la règle est restreinte à un vendor spécifique
            if rule_v and v_upper and rule_v != v_upper:
                continue
            # Filtrer par type équipement si restreint
            if rule_eq and eq_upper and rule_eq != eq_upper:
                continue

            rules.append(dict(r))
        return rules

    def apply_refine_rules(
        self,
        findings: List[Dict[str, Any]],
        vendor_name: Optional[str] = None,
        equipment_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Applique les règles actives apprises sur une liste de constats pour éliminer les faux positifs récurrents
        ou convertir les anomalies en concessions validées.
        """
        active_rules = self.get_active_rules(vendor_name, equipment_type)
        if not active_rules:
            return findings

        refined = []
        for finding in findings:
            title_u = finding.get("title") or ""
            cat_u = finding.get("category") or ""
            obs_u = finding.get("observation") or ""
            comb_norm = _normalize_text(f"{title_u} {cat_u} {obs_u}")

            matched_rule = None
            for r in active_rules:
                trigger_norm = _normalize_text(r.get("keyword_trigger") or "")
                if not trigger_norm:
                    continue
                if trigger_norm in comb_norm:
                    matched_rule = r
                    break
                t_words = [w for w in trigger_norm.split() if len(w) >= 4]
                if len(t_words) >= 2 and all(w in comb_norm for w in t_words):
                    matched_rule = r
                    break

            if matched_rule:
                if matched_rule["action"] == "SUPPRESS":
                    logger.info("[ARH-Refine] Réserve supprimée par règle %s : '%s'", matched_rule["rule_id"], finding.get("title"))
                    continue
                elif matched_rule["action"] == "DOWNGRADE_TO_INFO":
                    finding["priority"] = "INFO"
                    finding["severity"] = "Info"
                    finding["title"] = f"ℹ️ [Dérogation Validée par Inspecteur] {finding.get('title')}"
                    finding["observation"] += f"\n[Règle ARH Refine {matched_rule['rule_id']}] : {matched_rule['justification']}"
                    refined.append(finding)
            else:
                refined.append(finding)

        return refined

# Instance globale
arh_refine_engine = ARHRefineEngine()
