"""
arh_pid_topology_engine.py
==========================
Moteur d'Audit Topologique & de Sécurité Procédé P&ID pour ARKAN ARH.
Modélise la connectivité physique des lignes, équipements, instruments et soupapes sous NetworkX.
Exécute les règles déterministes de sûreté intrinsèque (ARH, API 520, API 521, ISO 10418, Décret 21-261).
"""

import re
import logging
from typing import Dict, List, Any, Optional, Tuple, Set
import networkx as nx

logger = logging.getLogger("ARHPidTopologyEngine")

# Marqueur "ouvert/cadenassé" avec bornes : l'ancien motif L\.?O\.? matchait "LOW", "LOCAL", "LOOP"... (faux CSO).
_LOCK_OPEN = r"(?<![A-Z0-9])(?:CSO|L\.O\.|LO|CAR[\s-]*SEAL[\s-]*OPEN|LOCKED[\s-]*OPEN)(?![A-Z0-9])"
# Tags de ligne (10"-P-5001-CS150) : à retirer avant la détection d'équipements, sinon "P-5001" devient une pompe.
_LINE_TAG_RE = re.compile(r"\b\d+(?:\.\d+)?(?:[\"'][-_ ]*|[-_]+)[A-Z][A-Z0-9]{0,3}[-_ ]+\d{3,6}(?:[-_][A-Z0-9]{2,8})*")
# Fenêtre de recherche qui s'arrête au tag suivant (sinon le "CSO" d'une vanne voisine est attribué à la mauvaise).
_WIN = r"(?:(?![A-Z]{1,4}[-\s]?\d{3,4}\b)[^\n]){0,80}"
_BLEED_WORDS = ("DRAIN", "BLEED", "VENT", "PURGE")

class ARHPidTopologyEngine:
    """Moteur de vérification de la topologie procédé et de sécurité P&ID."""

    def __init__(self):
        self.graph = nx.DiGraph()
        self.equipments: Set[str] = set()
        self.valves: Dict[str, Dict[str, Any]] = {}
        self.lines: Dict[str, Dict[str, Any]] = {}

    def reset(self):
        """Réinitialise le graphe topologique."""
        self.graph.clear()
        self.equipments.clear()
        self.valves.clear()
        self.lines.clear()

    def add_equipment(self, tag: str, eq_type: str = "VESSEL", metadata: Optional[Dict[str, Any]] = None):
        """Ajoute un équipement au graphe (ex: V-101, K-101, P-201)."""
        clean_tag = tag.strip().upper()
        self.equipments.add(clean_tag)
        self.graph.add_node(clean_tag, node_type="EQUIPMENT", eq_type=eq_type, metadata=metadata or {})

    def add_valve(self, tag: str, valve_type: str, lock_status: str = "NONE", metadata: Optional[Dict[str, Any]] = None):
        """
        Ajoute une vanne au graphe :
        - valve_type : 'PSV', 'ESDV', 'BDV', 'CONTROL_VALVE', 'CHECK_VALVE', 'MANUAL_VALVE', 'NEEDLE_VALVE', 'DRAIN_VALVE'
        - lock_status : 'CSO' (Car-Seal Open), 'CSC' (Car-Seal Closed), 'LO' (Locked Open), 'LC' (Locked Closed), 'NONE'
        """
        clean_tag = tag.strip().upper()
        v_meta = metadata or {}
        v_meta["lock_status"] = lock_status.strip().upper()
        v_meta["valve_type"] = valve_type.strip().upper()
        self.valves[clean_tag] = v_meta
        self.graph.add_node(clean_tag, node_type="VALVE", **v_meta)

    def add_piping_connection(self, from_node: str, to_node: str, line_tag: str = "", fluid: str = "", rating: str = ""):
        """Ajoute un segment de tuyauterie orienté entre deux éléments."""
        u = from_node.strip().upper()
        v = to_node.strip().upper()
        self.graph.add_edge(u, v, line_tag=line_tag, fluid=fluid, rating=rating)

    def parse_pid_text(self, text: str, source_doc: str = "P&ID", page: str = "") -> None:
        """
        Extrait automatiquement les composants et relations à partir du texte OCR d'un P&ID.
        """
        if not text:
            return
            
        tu = _LINE_TAG_RE.sub(" ", text.upper())
        
        # 1. Détection des équipements majeurs (V-xxx, K-xxx, P-xxx, T-xxx, D-xxx)
        eq_matches = re.findall(r'\b([VKPTD][\s-]?\d{3,4}[A-Z]?)\b', tu)
        for eq in eq_matches:
            clean_eq = re.sub(r'[\s-]+', '-', eq)
            self.add_equipment(clean_eq)
            
        # 2. Détection des soupapes de sûreté (PSV-xxx, PRV-xxx, PSE-xxx)
        psv_matches = re.findall(r'\b(PSV|PRV|PSE)[\s-]?(\d{3,4}[A-Z]?)\b', tu)
        for prefix, num in psv_matches:
            psv_tag = f"{prefix}-{num}"
            # Recherche si mention CSO ou LO à proximité
            window_pattern = rf'{re.escape(psv_tag)}{_WIN}{_LOCK_OPEN}'
            is_cso = bool(re.search(window_pattern, tu))
            lock_status = "CSO" if is_cso else "NONE"
            self.add_valve(psv_tag, "PSV", lock_status=lock_status, metadata={"document": source_doc, "page": page})

        # 3. Détection des vannes ESDV / BDV
        esdv_matches = re.findall(r'\b(ESDV|SDV|BDV)[\s-]?(\d{3,4}[A-Z]?)\b', tu)
        for prefix, num in esdv_matches:
            v_tag = f"{prefix}-{num}"
            v_type = "BDV" if prefix == "BDV" else "ESDV"
            self.add_valve(v_tag, v_type, metadata={"document": source_doc, "page": page})
            
        # 4. Détection des vannes manuelles amont de PSV
        # Format fréquent : HV-101 ou XV-101 en amont de PSV-101
        iso_matches = re.findall(r'\b([HX]V)[\s-]?(\d{3,4}[A-Z]?)\b', tu)
        for prefix, num in iso_matches:
            iso_tag = f"{prefix}-{num}"
            is_cso = bool(re.search(rf'{re.escape(iso_tag)}{_WIN}{_LOCK_OPEN}', tu))
            self.add_valve(iso_tag, "MANUAL_VALVE", lock_status="CSO" if is_cso else "NONE")

    def audit_process_safety_rules(self, source_doc: str = "P&ID", page: str = "") -> List[Dict[str, Any]]:
        """
        Vérifie l'ensemble des règles de sécurité procédé ARH et API 520 / 521 / ISO 10418.
        Génère les réserves critiques ou majeures correspondantes.
        """
        findings: List[Dict[str, Any]] = []

        if self.graph.number_of_edges() == 0:
            # CORRECTIF : avant, un graphe sans arêtes (cas de parse_pid_text seul) déclenchait une réserve
            # « composant isolé » pour CHAQUE nœud. On n'audite pas une topologie qu'on n'a pas construite.
            return [{
                "id": "PID_TOPOLOGY_UNAVAILABLE", "priority": "INFO", "category": "AUDIT NON EXÉCUTÉ",
                "title": "Topologie non reconstruite : règles de connectivité non évaluées",
                "observation": "Aucune connexion de tuyauterie n'a été fournie (utiliser load_from_line_entries ou add_piping_connection).",
                "document_concerned": source_doc, "page": page or "Schéma P&ID",
                "extracted_via": "ARKAN-Topology-P&ID-Engine", "needs_review": True,
            }]

        # ── RÈGLE 1 : Soupapes PSV & Cadenassage (CSO / LO) ──
        for psv_tag, psv_data in self.valves.items():
            if psv_data.get("valve_type") != "PSV":
                continue
                
            # Vérifier les prédécesseurs et successeurs directs dans le graphe
            upstream_nodes = list(self.graph.predecessors(psv_tag))
            downstream_nodes = list(self.graph.successors(psv_tag))
            
            # Analyse des vannes d'isolement amont
            for up in upstream_nodes:
                up_data = self.valves.get(up)
                if up_data and up_data.get("valve_type") in ["MANUAL_VALVE", "ESDV"]:
                    lock = up_data.get("lock_status", "NONE")
                    if lock not in ["CSO", "LO"]:
                        findings.append({
                            "id": f"PID_PSV_NOCSO_{psv_tag}",
                            "discipline": "PROCÉDÉ & SÉCURITÉ INTRINSÈQUE",
                            "agent": "🛡️ Spécialiste Sécurité Procédé & P&ID",
                            "priority": "CRITICAL",
                            "category": "SÉCURITÉ SOUPAPES (API 520 / DÉCRET 21-261)",
                            "title": f"Vanne d'Isolement Amont Non Cadenassée Ouverte sous la Soupape {psv_tag}",
                            "observation": (
                                f"Sur le P&ID '{source_doc}', la vanne d'isolement {up} en amont direct de la soupape de sûreté {psv_tag} "
                                f"n'est pas certifiée cadenassée ouverte (CSO / Locked Open). Tout isolement accidentel de la soupape "
                                f"expose l'équipement protégé à une surpression catastrophique sans échappement."
                            ),
                            "decree_reference": "Décret exécutif n° 21-261 / API 520 Part II Section 6.3 / ISO 10418",
                            "article": "Section 6.3 - Block Valves in Relief Paths",
                            "standard": "API 520 / P-CTE-1",
                            "document_concerned": source_doc,
                            "page": page or "Schéma P&ID",
                            "impact": "Risque majeur de surpression et rupture d'équipement sous pression sans décharge.",
                            "action_required": (
                                f"Modifier le schéma P&ID pour marquer explicitement la vanne {up} comme 'CSO' (Car-Seal Open) "
                                f"ou cadenassée ouverte avec clé prisonnière (interlock) et prévoir la procédure d'exploitation associée."
                            ),
                            "deadline_days": 3,
                            "extracted_via": "ARKAN-Topology-P&ID-Engine"
                        })

        # ── RÈGLE 2 : Double Block and Bleed (DBB) sur sectionnements critiques ──
        # Parcourt les séquences de vannes manuelles en série
        for v1, v1_data in self.valves.items():
            if v1_data.get("valve_type") != "MANUAL_VALVE":
                continue
            successors = list(self.graph.successors(v1))
            for v2 in successors:
                v2_data = self.valves.get(v2)
                if v2_data and v2_data.get("valve_type") == "MANUAL_VALVE":
                    # Deux vannes manuelles en série. Y a-t-il une vanne de purge/évent connectée entre v1 et v2 ?
                    intermediate_bleed = any(
                        n not in (v1, v2) and self._is_bleed(n)
                        for ref in (v1, v2)
                        for n in set(self.graph.successors(ref)) | set(self.graph.predecessors(ref))
                    )
                    if not intermediate_bleed:
                        findings.append({
                            "id": f"PID_DBB_NOBLEED_{v1}_{v2}",
                            "discipline": "PROCÉDÉ & SÉCURITÉ INTRINSÈQUE",
                            "agent": "🛡️ Spécialiste Sécurité Procédé & P&ID",
                            "priority": "MAJOR",
                            "category": "ISOLATION & PURGE (DBB)",
                            "title": f"Absence de Purge / Évent Intermédiaire entre les Vannes de Sectionnement {v1} et {v2}",
                            "observation": (
                                f"Montage de double isolement en série sans vanne d'évent ou de purge intermédiaire (Bleed) identifiée. "
                                f"Le principe Double Block and Bleed (DBB) prescrit par l'API 6D et l'ARH requiert la dépressurisation "
                                f"du tronçon intermédiaire avant toute intervention ou vérification d'étanchéité."
                            ),
                            "decree_reference": "Procédure ARH P-CTE-1 / API Specification 6D / ISO 10418 Section 5",
                            "article": "Section 5 - Safety Isolation Requirements",
                            "standard": "API 6D / ISO 10418",
                            "document_concerned": source_doc,
                            "page": page or "Schéma P&ID",
                            "impact": "Impossibilité de purger la pression résiduelle piégée entre deux vannes fermées lors de la maintenance.",
                            "action_required": "Ajouter un piquage de purge avec vanne à pointeau/boule cadenassée fermée (CSC) entre les deux vannes d'isolement.",
                            "deadline_days": 5,
                            "extracted_via": "ARKAN-Topology-P&ID-Engine"
                        })
        # ── RÈGLE 3 : Connectivité Topologique & Nœuds Déconnectés (Lignes Flottantes) ──
        # Identifie les nœuds isolés ou culs-de-sac non pontés (sans vanne, sans équipement, sans bride pleine)
        isolated_nodes = list(nx.isolates(self.graph))
        for iso in isolated_nodes:
            # Si le nœud est un équipement ou une vanne isolée sans connexion tuyauterie
            node_data = self.graph.nodes[iso]
            if node_data.get("node_type") in ["EQUIPMENT", "VALVE"]:
                findings.append({
                    "id": f"PID_TOPO_DISCONNECTED_{iso}",
                    "discipline": "PROCÉDÉ & SÉCURITÉ INTRINSÈQUE",
                    "agent": "🛡️ Spécialiste Sécurité Procédé & P&ID",
                    "priority": "MAJOR",
                    "category": "CONTINUITÉ TOPOLOGIQUE PIPELINE",
                    "title": f"Discontinuité Topologique : Composant {iso} Isolé sans Connectivité Tuyauterie",
                    "observation": (
                        f"Sur le schéma P&ID '{source_doc}', le composant {iso} ({node_data.get('node_type')}) "
                        f"figure sur le plan mais n'est raccordé à aucune ligne de tuyauterie amont ni aval dans le graphe procédé. "
                        f"Tout composant sous pression doit avoir ses raccordements et limites de batterie formellement définis."
                    ),
                    "decree_reference": "Procédure ARH P-CTE-1 / ASME B31.8 / API 5L",
                    "article": "Section 4 - Traçabilité des Raccordements",
                    "standard": "ASME B31.8 / P-CTE-1",
                    "document_concerned": source_doc,
                    "page": page or "Schéma P&ID",
                    "impact": "Incohérence de conception P&ID empêchant la traçabilité des flux et des bilans de matière.",
                    "action_required": f"Vérifier le tracé de la ligne connectée à {iso} et préciser les brides de raccordement ou la tuyauterie associée.",
                    "deadline_days": 5,
                    "extracted_via": "ARKAN-Topology-P&ID-Engine"
                })

        # ── RÈGLE 4 : Gares de Racleurs (Pig Launcher / Receiver) & Ligne Kicker ──
        for eq in self.equipments:
            if any(k in eq for k in ["PIG", "TRAP", "RACLEUR", "PL-", "PR-"]):
                # Vérifier si la gare a au moins deux lignes connectées : ligne principale + ligne d'impulsion (kicker line)
                in_degree = self.graph.in_degree(eq)
                out_degree = self.graph.out_degree(eq)
                total_conn = in_degree + out_degree
                if total_conn < 2:
                    findings.append({
                        "id": f"PID_PIG_KICKER_MISSING_{eq}",
                        "discipline": "CANALISATIONS & TRANSPORT",
                        "agent": "🛡️ Spécialiste Pipeline & Gares de Racleurs (Décret 21-315)",
                        "priority": "CRITICAL",
                        "category": "SÉCURITÉ DES GARES DE RACLEURS",
                        "title": f"Ligne d'Impulsion (Kicker Line) ou Purge Manquante sur la Gare de Racleur {eq}",
                        "observation": (
                            f"La gare de racleur {eq} (PIG Trap) ne présente pas la double connectivité obligatoire "
                            f"(ligne principale de transport + ligne d'équilibrage / impulsion 'Kicker Line'). "
                            f"L'absence de kicker line empêche la mise sous pression progressive et le lancement sécurisé du racleur instrumenté."
                        ),
                        "decree_reference": "Décret exécutif n° 21-315 Art. 16 / ASME B31.8 § 841.1",
                        "article": "Art. 16 Décret 21-315 - Gares de Racleurs",
                        "standard": "Décret 21-315 / ASME B31.8",
                        "document_concerned": source_doc,
                        "page": page or "Schéma P&ID",
                        "impact": "Danger majeur d'explosion ou d'enclavement du racleur lors des opérations de raclage sous gaz/huile.",
                        "action_required": "Compléter le schéma P&ID avec la ligne d'impulsion (Kicker line), la vanne d'équilibrage et le sas de purge.",
                        "deadline_days": 3,
                        "extracted_via": "ARKAN-Topology-P&ID-Engine"
                    })

        # ── RÈGLE 5 : Vannes de Sectionnement de Ligne (MLV) & Évents de Vidange ──
        for v_tag, v_data in self.valves.items():
            if any(k in v_tag for k in ["MLV", "BSV", "BLOCK-VALVE", "SECTIONNEMENT"]):
                # Une vanne de sectionnement de canalisation doit avoir des prises d'évent/dépressurisation
                has_blowdown = False
                for n in list(self.graph.successors(v_tag)) + list(self.graph.predecessors(v_tag)):
                    if "BDV" in n or "VENT" in n or "PURGE" in n or "DRAIN" in n:
                        has_blowdown = True
                        break
                if not has_blowdown:
                    findings.append({
                        "id": f"PID_MLV_NOVENT_{v_tag}",
                        "discipline": "CANALISATIONS & SÉCURITÉ",
                        "agent": "🛡️ Spécialiste Pipeline (Décret 21-315 / ASME B31.8)",
                        "priority": "MAJOR",
                        "category": "SECTIONNEMENT DE CANALISATION",
                        "title": f"Absence de Prise d'Évent / Dépressurisation au Poste de Sectionnement {v_tag}",
                        "observation": (
                            f"Le poste de vanne de sectionnement {v_tag} (Mainline Block Valve) sur la canalisation "
                            f"ne comporte pas de tuyauterie d'évent ou de torche pour la dépressurisation du tronçon isolé. "
                            f"L'Art. 15 du Décret exécutif n° 21-315 impose des dispositifs d'évacuation sécurisée des hydrocarbures piégés."
                        ),
                        "decree_reference": "Décret exécutif n° 21-315 Art. 15 / ASME B31.8 § 846.1",
                        "article": "Art. 15 Décret 21-315 - Vannes de Sectionnement",
                        "standard": "Décret 21-315",
                        "document_concerned": source_doc,
                        "page": page or "Schéma P&ID",
                        "impact": "Impossibilité de dépressuriser le tronçon de pipeline en cas de fuite ou de rupture sur la canalisation.",
                        "action_required": "Ajouter les piquages d'évent avec vannes de purge amont et aval de la vanne de sectionnement.",
                        "deadline_days": 5,
                        "extracted_via": "ARKAN-Topology-P&ID-Engine"
                    })

        for f in findings:
            f["needs_review"] = True
            f["review_note"] = "Constat automatique d'aide à la revue : à valider par un ingénieur qualifié."
        return findings

    @staticmethod
    def _classify(tag: str) -> Optional[str]:
        t = re.sub(r"^\d{2,4}[-_\s]", "", tag.strip().upper())   # prefixe de zone : 201-HV-003 -> HV-003
        if re.match(r"^(PSV|PRV|PSE)[-\s]?\d", t): return "PSV"
        if re.match(r"^BDV[-\s]?\d", t): return "BDV"
        if re.match(r"^(ESDV|SDV)[-\s]?\d", t): return "ESDV"
        if re.match(r"^(HV|XV)[-\s]?\d", t): return "MANUAL_VALVE"
        if re.match(r"^[A-Z]{1,3}V[-\s]?\d", t): return "VALVE"   # FV, MOV, TSV, PCV... : organes de ligne, pas des equipements
        return None

    def _is_bleed(self, node: str) -> bool:
        data = self.graph.nodes.get(node, {})
        if data.get("valve_type") in ("DRAIN_VALVE", "NEEDLE_VALVE", "BDV"):
            return True
        return any(w in str(node).upper() for w in _BLEED_WORDS)

    def load_from_line_entries(self, entries: List[Dict[str, Any]]) -> None:
        """Construit le graphe orienté à partir de la sortie du tracer (ou de circuit_graph) :
        from_equipment -> composants dans l'ordre -> to_equipment."""
        for e in entries:
            chain = [e.get("from_equipment", "OPEN")] + [c["tag"] for c in e.get("line_components", [])] + [e.get("to_equipment", "OPEN")]
            chain = [c for c in chain if c and c not in ("OPEN", "UNRESOLVED")]
            for tag in chain:
                kind = self._classify(tag)
                if kind:
                    if tag.strip().upper() not in self.valves:
                        self.add_valve(tag, kind, lock_status=e.get("lock_status", {}).get(tag, "NONE") if isinstance(e.get("lock_status"), dict) else "NONE")
                elif tag.strip().upper() not in self.valves:
                    self.add_equipment(tag)
            for u, v in zip(chain, chain[1:]):
                self.add_piping_connection(u, v, line_tag=e.get("line_number", ""), fluid=e.get("fluid", ""))

    @classmethod
    def fresh(cls) -> "ARHPidTopologyEngine":
        """Instance propre : à utiliser par requête. Le singleton ci-dessous partage son état entre requêtes."""
        return cls()

# Singleton exporté
pid_topology_engine = ARHPidTopologyEngine()
