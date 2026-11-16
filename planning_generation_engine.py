"""
ARKAN — Intelligence EPC & Réglementaire Oil & Gas
Module: planning_generation_engine.py
Moteur de génération de planning, calcul CPM (NetworkX), RAG Hybride (ChromaDB + BM25)
et Guardrails Anti-Hallucination avec modèles Pydantic v2.
"""

import os
import re
import json
import logging
from typing import Dict, List, Any, Optional, Tuple, Set
from pydantic import BaseModel, Field, field_validator
import networkx as nx
from rank_bm25 import BM25Okapi

from planning_knowledge_db import planning_db, PlanningKnowledgeDB

logger = logging.getLogger("arkan.planning_engine")

# ══════════════════════════════════════════════════════════════════════════════
# MODÈLES DE DONNÉES STRICTS PYDANTIC v2 (CONTRAT DE DONNÉES §7)
# ══════════════════════════════════════════════════════════════════════════════

class RendementDetail(BaseModel):
    valeur: float = Field(..., description="Valeur numérique du rendement journalier par équipe")
    unite: str = Field(..., description="Unité de rendement (ex: ml/jour/équipe, m³/jour/équipe)")

class EquipeRole(BaseModel):
    role: str = Field(..., description="Intitulé du rôle ou de la qualification (ex: Soudeur ASME IX 6G)")
    effectif: int = Field(1, description="Nombre d'agents affectés à ce rôle")

class TachePlanning(BaseModel):
    id_tache: str = Field(..., description="Identifiant unique WBS de la tâche (ex: T-010)")
    nom: str = Field(..., description="Libellé clair et actionnable de la tâche")
    description: str = Field("", description="Description technique détaillée")
    phase: str = Field("Construction", description="Phase globale (Ingénierie, Approvisionnement, Préfabrication, Montage, Essais, Mise en service)")
    discipline: str = Field(..., description="Discipline EPC rattachée (01 à 13)")
    unite_oeuvre: str = Field(..., description="Unité de mesure de la quantité (ml, m³, u, t, etc.)")
    quantite_estimee: float = Field(..., description="Quantité estimée métrée")
    rendement: RendementDetail = Field(..., description="Détail du rendement appliqué")
    duree_jours: float = Field(..., description="Durée calendaire calculée en jours ouvrés")
    equipe_type: List[EquipeRole] = Field(default_factory=list, description="Composition de l'équipe type requise")
    predecesseurs: List[Any] = Field(default_factory=list, description="Liste des id_tache prédécesseurs nécessaires ou objets de liaison")
    liaisons_cpm: List[Dict[str, Any]] = Field(default_factory=list, description="Liaisons CPM détaillées (id, type FS/SS/FF, lag_jours)")
    successeurs: List[str] = Field(default_factory=list, description="Liste des id_tache successeurs")
    jalon: bool = Field(False, description="Vrai s'il s'agit d'un jalon contractuel ou de contrôle")
    niveau_confiance: str = Field("Moyenne", description="Niveau de confiance : Haute | Moyenne | Faible")
    sources: List[str] = Field(default_factory=list, description="Références normatives ou lignes du référentiel source")

    # Métadonnées CPM calculées
    date_debut_tot: Optional[float] = Field(0.0, description="Date de début au plus tôt (jours)")
    date_fin_tot: Optional[float] = Field(0.0, description="Date de fin au plus tôt (jours)")
    date_debut_tard: Optional[float] = Field(0.0, description="Date de début au plus tard (jours)")
    date_fin_tard: Optional[float] = Field(0.0, description="Date de fin au plus tard (jours)")
    marge_totale: Optional[float] = Field(0.0, description="Marge totale en jours")
    marge_libre: Optional[float] = Field(0.0, description="Marge libre en jours")
    est_critique: Optional[bool] = Field(False, description="Vrai si la tâche appartient au chemin critique (marge=0)")

class PlanningResponse(BaseModel):
    projet_contexte: str = Field(..., description="Résumé du projet ou lot de travaux modélisé")
    taches: List[TachePlanning] = Field(default_factory=list, description="Liste ordonnée des tâches")
    chemin_critique: List[str] = Field(default_factory=list, description="Liste ordonnée des id_tache sur le chemin critique")
    duree_totale_jours: float = Field(0.0, description="Durée totale minimale du projet sur chemin critique")
    avertissements: List[str] = Field(default_factory=list, description="Alertes de plausibilité ou remarques techniques")
    confidence_score_moyen: float = Field(85.0, description="Score moyen de confiance global (0-100%)")
    generated_at: str = Field("", description="Date et heure de génération ISO")

class PlanningGenerationRequest(BaseModel):
    prompt: str = Field(..., description="Description libre du projet ou lot de travaux")
    type_projet: Optional[str] = Field(None, description="Type d'installation (Skid, Tuyauterie, Bac, Station pompage, etc.)")
    localisation: Optional[str] = Field("Algérie / Hassi Messaoud", description="Localisation géographique du chantier")
    contraintes: Optional[List[str]] = Field(default_factory=list, description="Contraintes (site actif, zone ATEX, espace confiné)")
    date_demarrage: Optional[str] = Field(None, description="Date de début souhaitée (YYYY-MM-DD)")
    quantites_connues: Optional[Dict[str, float]] = Field(default_factory=dict, description="Quantités spécifiées manuellement")
    wbs_level: Optional[int] = Field(3, description="Niveau de granularité WBS (2=Macro-Lots 5-7 tâches, 3=Standard 10-15 tâches, 4=Détaillé 20-30+ activités)")

class PlanningValidationRequest(BaseModel):
    tache_id_db: Optional[int] = Field(None, description="ID dans taches_referentiel si existant")
    nom_tache: str = Field(..., description="Nom de la tâche validée")
    discipline: str = Field("05_TUYAUTERIE_MONTAGE_SITE", description="Discipline")
    rendement_estime: float = Field(..., description="Rendement estimé initialement")
    rendement_reel: float = Field(..., description="Rendement réel validé par le planificateur")
    projet_id: Optional[str] = Field("PROJET_COURANT", description="Identifiant du projet")
    commentaire: Optional[str] = Field("", description="Notes d'ajustement chantier")


# ══════════════════════════════════════════════════════════════════════════════
# RAG HYBRIDE : BM25 + VECTEURS & CACHE DES RENDEMENTS
# ══════════════════════════════════════════════════════════════════════════════

class PlanningHybridRAG:
    """Moteur RAG Hybride combinant Dense Retrieval et BM25 sur le référentiel des rendements."""

    def __init__(self, db: PlanningKnowledgeDB = planning_db):
        self.db = db
        self.cached_tasks: List[Dict[str, Any]] = []
        self.bm25_corpus: List[List[str]] = []
        self.bm25_model: Optional[BM25Okapi] = None
        self._in_memory_cache: Dict[str, Dict[str, Any]] = {}
        self.refresh_index()

    def refresh_index(self):
        """Met à jour l'index BM25 en mémoire à partir de la base SQLite."""
        self.cached_tasks = self.db.get_all_tasks_for_rag()
        if not self.cached_tasks:
            return

        self.bm25_corpus = [
            self._tokenize(f"{t['nom']} {t['discipline']} {t['unite_oeuvre']} {t['description']} {t['normes_associees']}")
            for t in self.cached_tasks
        ]
        self.bm25_model = BM25Okapi(self.bm25_corpus)
        logger.info(f"[PlanningRAG] Index BM25 initialisé avec {len(self.cached_tasks)} tâches types.")

    def _tokenize(self, text: str) -> List[str]:
        return [w for w in re.findall(r'\w+', text.lower()) if len(w) > 2]

    def search_similar_tasks(self, query: str, top_k: int = 3, discipline: Optional[str] = None, unite: Optional[str] = None) -> List[Dict[str, Any]]:
        """Recherche les tâches types les plus proches dans le référentiel par BM25 et mots-clés."""
        if not self.bm25_model or not self.cached_tasks:
            return []

        tokens = self._tokenize(query)
        if not tokens:
            return []

        scores = list(self.bm25_model.get_scores(tokens))
        for i, task in enumerate(self.cached_tasks):
            if discipline and task.get("discipline") == discipline:
                scores[i] *= 1.3
            if unite and (unite.lower() in task.get("unite_oeuvre", "").lower() or task.get("unite_oeuvre", "").lower() in unite.lower()):
                scores[i] *= 1.6

        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results = []
        for idx in top_indices:
            score = scores[idx]
            if score > 0.3:
                task_copy = dict(self.cached_tasks[idx])
                task_copy["similarity_score"] = float(score)
                results.append(task_copy)

        return results


# ══════════════════════════════════════════════════════════════════════════════
# MOTEUR CPM (CRITICAL PATH METHOD) — RÉSEAU DE TÂCHES NETWORKX
# ══════════════════════════════════════════════════════════════════════════════

class PlanningCPMEngine:
    """Calculateur de chemin critique et ordonnancement logique basé sur NetworkX."""

    @staticmethod
    def calculate_cpm(taches: List[TachePlanning]) -> Tuple[List[TachePlanning], List[str], float, List[str]]:
        """
        Construit le DAG (Graphe Orienté Acyclique), calcule :
        - Date début au plus tôt (Early Start - ES)
        - Date fin au plus tôt (Early Finish - EF)
        - Date fin au plus tard (Late Finish - LF)
        - Date début au plus tard (Late Start - LS)
        - Marge totale (Total Float = LS - ES)
        - Marge libre (Free Float)
        - Identification du chemin critique (Tâches avec marge totale = 0)
        """
        warnings = []
        if not taches:
            return [], [], 0.0, warnings

        # 1. Construction du graphe orienté
        G = nx.DiGraph()
        task_dict: Dict[str, TachePlanning] = {t.id_tache: t for t in taches}

        for t in taches:
            duration = max(0.1, float(t.duree_jours))
            G.add_node(t.id_tache, duration=duration, task=t)

        # 2. Ajout des arcs (dépendances) avec support FS, SS, FF et décalages (lag)
        for t in taches:
            for p in t.predecesseurs:
                if isinstance(p, dict):
                    pid = p.get("id") or p.get("id_tache")
                    rel_type = p.get("type", "FS")
                    lag = float(p.get("lag_jours", 0.0))
                else:
                    pid = str(p)
                    rel_type = "FS"
                    lag = 0.0
                
                if pid in task_dict:
                    G.add_edge(pid, t.id_tache, type=rel_type, lag=lag)
                    t.liaisons_cpm.append({"id": pid, "type": rel_type, "lag_jours": lag})
                else:
                    warnings.append(f"Prédécesseur inconnu '{pid}' pour la tâche '{t.id_tache}' (ignoré).")

        # 3. Vérification de l'acyclicité (pas de boucle infinie)
        if not nx.is_directed_acyclic_graph(G):
            # Détection des cycles pour alerte
            try:
                cycles = list(nx.simple_cycles(G))
                warnings.append(f"⚠️ Boucle de dépendance cyclique détectée : {cycles}. Le graphe a été linéarisé.")
                # Suppression des arcs en boucle
                for cycle in cycles:
                    if len(cycle) >= 2:
                        G.remove_edge(cycle[-1], cycle[0])
            except Exception:
                pass

        # 4. Tri topologique (Ordonnancement logique séquentiel)
        try:
            topo_order = list(nx.topological_sort(G))
        except Exception:
            topo_order = [t.id_tache for t in taches]

        # 5. Passe Avant (Forward Pass) -> ES et EF avec FS/SS/FF et lag
        early_start: Dict[str, float] = {}
        early_finish: Dict[str, float] = {}

        for node in topo_order:
            preds = list(G.predecessors(node))
            dur = G.nodes[node]["duration"]
            if not preds:
                es = 0.0
            else:
                cand_starts = []
                for p in preds:
                    ed = G.get_edge_data(p, node) or {}
                    rtype = ed.get("type", "FS")
                    lag = float(ed.get("lag", 0.0))
                    if rtype == "FS":
                        cand_starts.append(early_finish[p] + lag)
                    elif rtype == "SS":
                        cand_starts.append(early_start[p] + lag)
                    elif rtype == "FF":
                        cand_starts.append(early_finish[p] + lag - dur)
                    else:
                        cand_starts.append(early_finish[p] + lag)
                es = max(0.0, max(cand_starts))
            
            ef = es + dur
            early_start[node] = round(es, 1)
            early_finish[node] = round(ef, 1)

        total_duration = max(early_finish.values()) if early_finish else 0.0

        # 6. Passe Arrière (Backward Pass) -> LF et LS avec FS/SS/FF et lag
        late_start: Dict[str, float] = {}
        late_finish: Dict[str, float] = {}

        for node in reversed(topo_order):
            succs = list(G.successors(node))
            dur = G.nodes[node]["duration"]
            if not succs:
                lf = total_duration
            else:
                cand_finishes = []
                for s in succs:
                    ed = G.get_edge_data(node, s) or {}
                    rtype = ed.get("type", "FS")
                    lag = float(ed.get("lag", 0.0))
                    if rtype == "FS":
                        cand_finishes.append(late_start[s] - lag)
                    elif rtype == "SS":
                        cand_finishes.append(late_start[s] - lag + dur)
                    elif rtype == "FF":
                        cand_finishes.append(late_finish[s] - lag)
                    else:
                        cand_finishes.append(late_start[s] - lag)
                lf = min(cand_finishes)
            
            ls = lf - dur
            late_start[node] = round(ls, 1)
            late_finish[node] = round(lf, 1)

        # 7. Calcul des marges et identification du chemin critique
        critical_path = []
        for t in taches:
            node = t.id_tache
            es = early_start.get(node, 0.0)
            ef = early_finish.get(node, t.duree_jours)
            ls = late_start.get(node, es)
            lf = late_finish.get(node, ef)
            
            total_float = max(0.0, round(ls - es, 1))
            
            succs = list(G.successors(node))
            if succs:
                free_float = max(0.0, round(min(early_start[s] for s in succs) - ef, 1))
            else:
                free_float = max(0.0, round(total_duration - ef, 1))

            is_critical = (total_float <= 0.1)

            t.date_debut_tot = es
            t.date_fin_tot = ef
            t.date_debut_tard = ls
            t.date_fin_tard = lf
            t.marge_totale = total_float
            t.marge_libre = free_float
            t.est_critique = is_critical

            # Mettre à jour les successeurs directs dans l'objet
            t.successeurs = list(G.successors(node))

            if is_critical:
                critical_path.append(node)

        # Ordonner le chemin critique selon l'avancement temporel
        critical_path_sorted = sorted(critical_path, key=lambda nid: early_start.get(nid, 0.0))

        return taches, critical_path_sorted, round(total_duration, 1), warnings


# ══════════════════════════════════════════════════════════════════════════════
# GUARDRAILS ANTI-HALLUCINATION & RÈGLES MÉTIER UNIVERSELLES
# ══════════════════════════════════════════════════════════════════════════════

# Règles physiques universelles de précédence (non négociables)
UNIVERSAL_PRECEDENCE_RULES = [
    # (Discipline amont, Discipline aval, Description de règle)
    ("03_GENIE_CIVIL_TERRASSEMENT", "04_STRUCTURE_CHARPENTE", "Les massifs de génie civil doivent être coulés et durcis avant l'érection de la charpente"),
    ("04_STRUCTURE_CHARPENTE", "06_TUYAUTERIE_MONTAGE_SITE", "La charpente / pipe-rack doit être montée avant la pose de tuyauterie"),
    ("05_TUYAUTERIE_PREFABRICATION", "06_TUYAUTERIE_MONTAGE_SITE", "Les spools doivent être préfabriqués avant montage sur site"),
    ("05_TUYAUTERIE_PREFABRICATION", "05_TUYAUTERIE_PREFABRICATION", "Les soudures doivent être réalisées avant les contrôles CND"),
    ("06_TUYAUTERIE_MONTAGE_SITE", "06_TUYAUTERIE_MONTAGE_SITE", "L'épreuve hydrostatique doit être réalisée après le soudage et CND"),
    ("06_TUYAUTERIE_MONTAGE_SITE", "11_ISOLATION_CALORIFUGE_PEINTURE", "L'épreuve hydrostatique doit être validée avant calorifugeage des lignes"),
    ("09_ELECTRICITE_HT_BT", "12_PRECOMMISSIONING_TESTS", "Le câblage électrique doit être achevé avant les tests d'isolement et de rotation"),
    ("10_INSTRUMENTATION_AUTOMATISME", "12_PRECOMMISSIONING_TESTS", "Le tubing et câblage instrument doivent être finis avant les loop checks"),
    ("12_PRECOMMISSIONING_TESTS", "13_COMMISSIONING_DEMARRAGE", "Le précommissioning doit être 100% approuvé (RFSU) avant introduction des hydrocarbures")
]

class PlanningGuardrails:
    """Valide la cohérence logique, les bornes physiques et prévient les hallucinations."""

    @staticmethod
    def audit_and_clamp_yield(tache_nom: str, quantite: float, rendement_propose: float, unite: str, rag_match: Optional[Dict[str, Any]] = None) -> Tuple[float, float, str, List[str]]:
        """
        Vérifie si le rendement proposé est compris dans les bornes plausibles physiques.
        Retourne (rendement_ajusté, durée_calculée, niveau_confiance, avertissements).
        """
        avertissements = []
        confiance = "Moyenne"
        val = max(0.01, float(rendement_propose))

        if rag_match:
            min_p = rag_match.get("min_plausible", val * 0.2)
            max_p = rag_match.get("max_plausible", val * 4.0)
            confiance = rag_match.get("niveau_confiance", "Moyenne")
            source = rag_match.get("source", "Référentiel ARKAN")

            if val < min_p:
                avertissements.append(f"Rendement pour '{tache_nom}' anormalement faible ({val} {unite} < min {min_p}). Ajusté à la borne min.")
                val = min_p
                confiance = "Faible"
            elif val > max_p:
                avertissements.append(f"Rendement pour '{tache_nom}' physiquement excessif ({val} {unite} > max {max_p}). Plafonné à la borne max.")
                val = max_p
                confiance = "Faible"
        else:
            confiance = "Faible"
            avertissements.append(f"Tâche '{tache_nom}' non trouvée dans le référentiel standard — Rendement IA estimé sans historique direct.")

        duree = max(0.5, round(quantite / val, 1)) if val > 0 else 1.0
        return val, duree, confiance, avertissements

    @staticmethod
    def enforce_universal_precedence(taches: List[TachePlanning]) -> Tuple[List[TachePlanning], List[str]]:
        """Applique les contraintes de précédence universelles et corrige les liens manquants sans injecter de cycle."""
        avertissements = []
        discipline_tasks: Dict[str, List[str]] = {}
        task_id_to_idx = {t.id_tache: i for i, t in enumerate(taches)}

        for t in taches:
            discipline_tasks.setdefault(t.discipline, []).append(t.id_tache)

        for disc_amont, disc_aval, description in UNIVERSAL_PRECEDENCE_RULES:
            if disc_amont == disc_aval:
                continue  # Les dépendances intra-discipline sont déjà gérées dans le WBS

            taches_amont = discipline_tasks.get(disc_amont, [])
            taches_aval = discipline_tasks.get(disc_aval, [])

            if taches_amont and taches_aval:
                last_amont = taches_amont[-1]
                first_aval_obj = next((t for t in taches if t.id_tache == taches_aval[0]), None)
                
                if first_aval_obj and last_amont != first_aval_obj.id_tache:
                    idx_amont = task_id_to_idx.get(last_amont, -1)
                    idx_aval = task_id_to_idx.get(first_aval_obj.id_tache, -1)
                    
                    # Règle stricte anti-cycle : l'amont doit obligatoirement précéder l'aval dans la séquence WBS
                    if 0 <= idx_amont < idx_aval:
                        existing_preds = [p.get("id") if isinstance(p, dict) else str(p) for p in first_aval_obj.predecesseurs]
                        if last_amont not in existing_preds:
                            first_aval_obj.predecesseurs.append(last_amont)
                            avertissements.append(f"Lien logique automatique imposé : '{last_amont}' -> '{first_aval_obj.id_tache}' ({description}).")

        return taches, avertissements


# Singletons
planning_rag = PlanningHybridRAG()
planning_cpm = PlanningCPMEngine()
planning_guardrails = PlanningGuardrails()
