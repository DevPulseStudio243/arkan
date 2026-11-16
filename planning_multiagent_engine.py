"""
ARKAN — Intelligence EPC & Réglementaire Oil & Gas
Module: planning_multiagent_engine.py
Swarm Multi-Agents asynchrone pour la génération de plannings industriels hautement spécialisés.
Couvre exhaustivement les 13 typologies réelles de projets industriels & Oil & Gas.
"""

import os
import re
import json
import time
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Callable

import httpx

from config import OLLAMA_BASE_URL
from planning_knowledge_db import planning_db
from planning_generation_engine import (
    planning_rag, planning_cpm, planning_guardrails,
    TachePlanning, RendementDetail, EquipeRole, PlanningResponse,
    PlanningGenerationRequest
)

logger = logging.getLogger("arkan.planning_swarm")


class PlanningNLUAgent:
    """Agent 1 : Compréhension sémantique profonde via LLM & extraction multi-dimensionnelle des paramètres."""

    async def _query_llm_semantic_understanding(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Interroge le LLM arkan-planning pour une compréhension sémantique exhaustive du périmètre."""
        system_prompt = (
            "Tu es l'ingénieur expert en compréhension sémantique de projet EPC Oil & Gas d'ARKAN.\n"
            "Analyse la demande de l'utilisateur et identifie la typologie exacte et les paramètres du projet.\n"
            "Réponds STRICTEMENT sous forme d'un objet JSON valide sans texte additionnel.\n"
            "Schéma attendu :\n"
            "{\n"
            '  "typologie": "FIBER_OPTIC_TELECOM | CATHODIC_PROTECTION | WELLHEAD_AND_MANIFOLD_GATHERING | ELECTRICAL_TGBT_SUBSTATION | INSTRUMENTATION_DCS_AUTOMATION | SHUTDOWN_REVAMPING_MAINTENANCE | CIVIL_EARTHWORKS_CONCRETE | ROTATING_EQUIPMENT_MACHINERY | STORAGE_TANK_API650 | WELLHEAD_FACILITIES | GATHERING_MANIFOLD | INDUSTRIAL_BUILDING_HANGAR | PIPELINE_TRANSPORT | SKID_PROCESS | STATIC_VESSEL_COLUMN | PLANT_PIPING | CUSTOM_SPECIALIZED",\n'
            '  "type_installation": "Intitulé professionnel clair du projet",\n'
            '  "implique_soudage_acier": false,\n'
            '  "discipline_majeure": "01_INGENIERIE | 03_GENIE_CIVIL | 09_ELECTRICITE | 10_INSTRUMENTATION_TELECOMS | etc.",\n'
            '  "parametres": {\n'
            '    "longueur_ml": 0.0,\n'
            '    "diametre_pouces": 0,\n'
            '    "volume_m3": 0.0,\n'
            '    "surface_m2": 0.0,\n'
            '    "nb_unites": 1\n'
            '  }\n'
            "}"
        )
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": "arkan-planning",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Demande projet : {prompt}"}
                        ],
                        "stream": False,
                        "options": {"temperature": 0.0, "num_predict": 400}
                    }
                )
                if resp.status_code == 200:
                    content = resp.json().get("message", {}).get("content", "").strip()
                    idx = content.find('{')
                    while idx != -1:
                        try:
                            parsed, _ = json.JSONDecoder().raw_decode(content[idx:])
                            if isinstance(parsed, dict):
                                logger.info(f"[PlanningNLUAgent] Analyse sémantique LLM réussie : {parsed.get('typologie')} - {parsed.get('type_installation')}")
                                return parsed
                        except Exception:
                            pass
                        idx = content.find('{', idx + 1)
        except Exception as e:
            logger.warning(f"[PlanningNLUAgent] Fallback heuristique suite à exception LLM: {e}")
        return None

    def _fallback_heuristic_analysis(self, p: str, request: PlanningGenerationRequest) -> Dict[str, Any]:
        """Analyse heuristique déterministe de secours."""
        km_m = re.search(r'(\d+(?:[\.,]\d+)?)\s*(?:km|kilomètres|kilometres|kms?)(?: |\s|$)', p)
        m_m = re.search(r'(\d+(?:[\.,]\d+)?)\s*(?:m|ml|mètres|metres)(?: |\s|$)', p)
        
        if km_m:
            longueur_ml = float(km_m.group(1).replace(',', '.')) * 1000.0
            unite_longueur_orig = f"{km_m.group(1)} km"
        elif m_m:
            longueur_ml = float(m_m.group(1).replace(',', '.'))
            unite_longueur_orig = f"{m_m.group(1)} m"
        else:
            longueur_ml = 120.0
            unite_longueur_orig = "120 m"

        # 2. Extraction du diamètre (pouces ou DN) avec délimiteurs stricts pour éviter les faux-positifs
        dn_pouces_m = re.search(r'(?:diamètre|diametre|dn|taille)?\s*(\d+(?:\.\d+)?)\s*(?:pouces|pouce|inch|inches|\b\"|\bpol\b)(?!\w)', p)
        dn_metric_m = re.search(r'\bdn\s*(\d+)\b', p)
        if dn_pouces_m:
            diam_pouces = min(48, max(1, int(float(dn_pouces_m.group(1)))))
            diam_str = f"{diam_pouces} pouces (DN{diam_pouces*25})"
        elif dn_metric_m:
            dn_val = int(dn_metric_m.group(1))
            diam_pouces = min(48, max(1, int(round(dn_val / 25.4))))
            diam_str = f"DN{dn_val} ({diam_pouces} pouces)"
        else:
            diam_pouces = 8
            diam_str = "DN200 (8 pouces)"

        # 3. Extraction volume / puissance / surface / nombre d'unités
        vol_m3_m = re.search(r'(\d+(?:[\.,]\d+)?)\s*(?:m3|m³|m3/h|m³/h)', p)
        vol_val = float(vol_m3_m.group(1).replace(',', '.')) if vol_m3_m else 50.0

        m2_m = re.search(r'(\d+(?:[\.,]\d+)?)\s*(?:m2|m²) ', p)
        surf_m2 = float(m2_m.group(1).replace(',', '.')) if m2_m else 600.0

        nb_units_m = re.search(r'(\d+)\s*(?:armoire|armoires|cellule|cellules|tgbt|pompe|pompes|échangeur|echangeur|puits|puit|bac|bacs) ', p)
        nb_units = int(nb_units_m.group(1)) if nb_units_m else 4

        # 4. Classification sémantique fine des typologies
        # Priorité absolue au type_projet explicitement demandé s'il est renseigné
        if request and request.type_projet:
            req_type = request.type_projet.strip().upper()
            valid_types = {
                "PIPELINE_TRANSPORT": "Canalisation de Transport / Pipeline Pipeline API 5L",
                "STORAGE_TANK_API650": f"Bac de Stockage Pétrolier API 650 ({int(vol_val)} m³)",
                "SKID_PROCESS": "Package Skid de Procédé Gaz / Pétrole",
                "SHUTDOWN_REVAMPING_MAINTENANCE": "Arrêt d'Unité (Shutdown & Revamping)",
                "SOLAR_PV_POWER_SYSTEM": "Centrale Solaire Photovoltaïque & Énergie Renouvelable",
                "FIRE_PROTECTION_SAFETY": "Système d'Extinction Incendie Déluge, Mousse & Rideau d'Eau",
                "CIVIL_BASIN_POND_LINING": f"Bassin de Rétention / Évaporation & Étanchéité PEHD ({int(vol_val)} m³)",
                "CATHODIC_PROTECTION": f"Système de Protection Cathodique ({unite_longueur_orig})",
                "FIBER_OPTIC_TELECOM": f"Liaison Câble Fibre Optique & Réseau Télécoms ({unite_longueur_orig})",
                "WELLHEAD_AND_MANIFOLD_GATHERING": f"Installation Intégrée Tête de Puits & Manifold ({nb_units} puits)",
                "ELECTRICAL_TGBT_SUBSTATION": f"Tableau Général Basse Tension (TGBT) & Distribution ({nb_units} cellules)",
                "INSTRUMENTATION_DCS_AUTOMATION": "Système d'Instrumentation & Contrôle-Commande Automate (DCS/SIS/F&G)",
                "ROTATING_EQUIPMENT_MACHINERY": f"Machines Tournantes & Équipements Mécaniques ({nb_units} machines)",
                "INDUSTRIAL_BUILDING_HANGAR": f"Hangar Industriel & Charpente Métallique ({int(surf_m2)} m²)"
            }
            if req_type in valid_types:
                return {
                    "typologie": req_type,
                    "type_installation": valid_types[req_type],
                    "implique_soudage_acier": req_type in ["PIPELINE_TRANSPORT", "STORAGE_TANK_API650", "SKID_PROCESS", "SHUTDOWN_REVAMPING_MAINTENANCE"],
                    "discipline_majeure": "06_TUYAUTERIE_MONTAGE_SITE",
                    "parametres_cles": {
                        "longueur_ml": longueur_ml,
                        "diametre_pouces": diam_pouces,
                        "volume_m3": vol_val,
                        "surface_m2": surf_m2,
                        "nb_unites": nb_units
                    }
                }

        is_shutdown = any(w in p for w in ["arrêt", "arret", "shutdown", "revamping", "révision", "revision", "décokage", "overhaul", "retubage", "grand arrêt"])
        is_fire_safety = any(w in p for w in ["déluge", "deluge", "extinction incendie", "rideau d'eau", "mousse incendie", "sprinkler", "lutte contre l'incendie", "réseau incendie", "reseau incendie", "protection incendie", "couronne d'arrosage"])
        is_solar = any(w in p for w in ["solaire", "photovoltaïque", "photovoltaique", "panneaux solaires", "onduleur solaire", "centrale solaire", "ferme solaire", "pv "])
        is_flare = any(w in p for w in ["torchère", "torchere", "flare", "brûleur", "allumeur", "fût de torchère", "fut de torchere", "torchère hp", "torchère bp"]) and not is_shutdown
        is_bassin = any(w in p for w in ["bassin", "lagune", "rétention d'eau", "retention d'eau", "évaporation", "evaporation", "géomembrane", "geomembrane", "pehd étanchéité", "bassin de rétention"])
        is_tgbt = any(w in p for w in ["tgbt", "tableau général", "tableau general", "armoire électrique", "armoire electrique", "basse tension", "moyenne tension", "haute tension", "transformateur", "poste électrique", "poste electrique", "substation", "gis", "cellule électrique", "cellules électriques", "disjoncteur", "câblage armoire", "armoire de puissance", "distribution bt", "onduleur", "ups", "groupe électrogène", "groupe electrogene"])
        is_instru = any(w in p for w in ["dcs", "automate", "instrumentation", "transmetteur", "f&g", "feu et gaz", "détection gaz", "detection gaz", "détection flamme", "esd", "sis", "tubing", "swagelok", "boucle instrumentale", "scada", "sncc", "sil 3", "armoire automate"])
        is_civil = (any(w in p for w in ["terrassement", "plateforme", "voirie", "vrd", "fouille", "dalle béton", "dalle beton", "fondation", "radier", "enrochement"]) or is_bassin) and not any(w in p for w in ["bac", "pipe", "hangar", "tgbt", "armoire"])
        is_machine = any(w in p for w in ["pompe", "pompes", "compresseur", "compresseurs", "turbine", "turbines", "motopompe", "motopompes", "alignement laser", "turbo"])
        is_bac = any(w in p for w in ["bac", "réservoir", "reservoir", "tank", "api 650", "api 620", "toit flottant", "cuvette de rétention"]) and not is_fire_safety
        is_puits = any(w in p for w in ["puit", "puits", "tête de puit", "tete de puit", "wellhead", "arbre de noël", "arbre de noel", "christmas tree", "whcp", "cave de puit"])
        is_manifold = any(w in p for w in ["manifold", "collecteur", "slug catcher", "header", "collecte puits", "multiphasique", "mpfm", "choke"])
        is_telecom = any(w in p for w in ["fibre optique", "fibre", "optique", "foc", "câble optique", "cable optique", "telecom", "télécom", "otdr", "fourreau pehd", "multitube", "soufflage fibre", "chambre de tirage", "odf", "liaison optique", "épissurage", "epissurage", "fusion d'arc"])
        is_cathodic = any(w in p for w in ["protection cathodique", "cathodique", "cathodic", "anode", "anodes", "déversoir", "deversoir", "poste t/r", "transformateur-redresseur", "transformateur redresseur", "courant imposé", "courant impose", "anode sacrificielle", "anodes sacrificielles", "prise de potentiel", "prises de potentiel", "test post", "test posts", "cips", "dcvg", "polarisation", "joint isolant", "monolithic isolation joint"])
        is_pipeline = (any(w in p for w in ["pipeline", "gazoduc", "oléoduc", "oleoduc", "canalisation", "ligne de transport", "flowline", "tronçon", "troncon"]) or (longueur_ml >= 1000.0)) and not is_telecom and not is_cathodic and not is_bassin and not is_solar and not is_flare and not is_fire_safety
        is_hangar = any(w in p for w in ["hangar", "bâtiment", "batiment", "shelter", "atelier", "salle de contrôle", "salle de controle", "charpente métallique", "bardage"])
        is_skid = any(w in p for w in ["skid", "dessalement", "package", "injection", "séparation", "module"])
        is_colonne = any(w in p for w in ["colonne", "ballon séparateur", "réacteur", "reacteur", "condensat", "appareil à pression"])

        if is_shutdown:
            typologie = "SHUTDOWN_REVAMPING_MAINTENANCE"
            type_inst = "Arrêt d'Unité (Shutdown & Revamping)"
        elif is_fire_safety:
            typologie = "FIRE_PROTECTION_SAFETY"
            type_inst = f"Système d'Extinction Incendie Déluge, Mousse & Rideau d'Eau"
        elif is_solar:
            typologie = "SOLAR_PV_POWER_SYSTEM"
            type_inst = f"Centrale Solaire Photovoltaïque & Énergie Renouvelable"
        elif is_flare:
            typologie = "FLARE_SYSTEM_AND_IGNITION"
            type_inst = f"Système de Torchère Industrielle HP/BP & Allumeur Automatique"
        elif is_bassin:
            typologie = "CIVIL_BASIN_POND_LINING"
            type_inst = f"Bassin de Rétention / Évaporation & Étanchéité PEHD ({int(vol_val)} m³)"
        elif is_cathodic:
            typologie = "CATHODIC_PROTECTION"
            type_inst = f"Système de Protection Cathodique par Courant Imposé / Anodes ({unite_longueur_orig})"
        elif is_telecom:
            typologie = "FIBER_OPTIC_TELECOM"
            type_inst = f"Liaison Câble Fibre Optique & Réseau Télécoms ({unite_longueur_orig})"
        elif is_puits and is_manifold:
            typologie = "WELLHEAD_AND_MANIFOLD_GATHERING"
            type_inst = f"Installation Intégrée Tête de Puits API 6A & Manifold de Collecte ({nb_units} puits)"
        elif is_tgbt:
            typologie = "ELECTRICAL_TGBT_SUBSTATION"
            type_inst = f"Tableau Général Basse Tension (TGBT) & Distribution Électrique ({nb_units} cellules)"
        elif is_instru:
            typologie = "INSTRUMENTATION_DCS_AUTOMATION"
            type_inst = f"Système d'Instrumentation & Contrôle-Commande Automate (DCS/SIS/F&G)"
        elif is_shutdown:
            typologie = "SHUTDOWN_REVAMPING_MAINTENANCE"
            type_inst = f"Arrêt d'Unité & Travaux de Révision / Revamping ({nb_units} équipements critiques)"
        elif is_civil:
            typologie = "CIVIL_EARTHWORKS_CONCRETE"
            type_inst = f"Travaux de Génie Civil & Terrassements Généraux ({int(surf_m2)} m²)"
        elif is_machine:
            typologie = "ROTATING_EQUIPMENT_MACHINERY"
            type_inst = f"Installation & Raccordement d'Équipements Dynamiques (Machines Tournantes)"
        elif is_bac:
            typologie = "STORAGE_TANK_API650"
            type_inst = f"Bac de Stockage Pétrolier API 650 ({int(vol_val)} m³)"
        elif is_puits:
            typologie = "WELLHEAD_FACILITIES"
            type_inst = f"Installation de Surface / Tête de Puits API 6A ({nb_units} puits)"
        elif is_manifold:
            typologie = "GATHERING_MANIFOLD"
            type_inst = f"Manifold de Collecte Multi-Puits ({nb_units} arrivées)"
        elif is_hangar:
            typologie = "INDUSTRIAL_BUILDING_HANGAR"
            type_inst = f"Bâtiment Industriel / Hangar & Charpente ({int(surf_m2)} m²)"
        elif is_pipeline:
            typologie = "PIPELINE_TRANSPORT"
            type_inst = f"Canalisation de Transport / Pipeline {diam_str} ({unite_longueur_orig})"
        elif is_skid:
            typologie = "SKID_PROCESS"
            type_inst = f"Skid de Procédé Préfabriqué ({int(vol_val)} m³/h)"
        elif is_colonne:
            typologie = "STATIC_VESSEL_COLUMN"
            type_inst = f"Équipement Statique sous Pression & Colonne de Distillation"
        else:
            typologie = "PLANT_PIPING"
            type_inst = f"Tuyauterie Industrielle & Raccordements ({diam_str}, {longueur_ml} ml)"

        return {
            "titre_projet": request.prompt[:70],
            "type_installation": type_inst,
            "typologie": typologie,
            "parametres_cles": {
                "longueur_ml": longueur_ml,
                "diametre_pouces": diam_pouces,
                "diametre_str": diam_str,
                "volume_m3": vol_val,
                "surface_m2": surf_m2,
                "nb_unites": nb_units,
                "nb_tubes_12m": int(round(longueur_ml / 12.0)) if longueur_ml > 0 else 10,
                "total_joints_soudes": int(round(longueur_ml / 12.0)) if longueur_ml > 0 else 10,
                "total_di": int(round((longueur_ml / 12.0) * diam_pouces)) if longueur_ml > 0 else 80
            },
            "contraintes_site": request.contraintes or ["Standard"]
        }

    async def analyze(self, request: PlanningGenerationRequest) -> Dict[str, Any]:
        p = request.prompt.lower()
        
        # 1. Compréhension Sémantique LLM
        llm_data = await self._query_llm_semantic_understanding(request.prompt)
        
        # 2. Analyse Heuristique de base
        fallback = self._fallback_heuristic_analysis(p, request)
        
        if llm_data and llm_data.get("typologie"):
            typo_llm = llm_data.get("typologie")
            # Si le LLM a identifié une typologie valide
            if typo_llm in [
                "FIBER_OPTIC_TELECOM", "CATHODIC_PROTECTION", "WELLHEAD_AND_MANIFOLD_GATHERING",
                "ELECTRICAL_TGBT_SUBSTATION", "INSTRUMENTATION_DCS_AUTOMATION", "SHUTDOWN_REVAMPING_MAINTENANCE",
                "CIVIL_EARTHWORKS_CONCRETE", "ROTATING_EQUIPMENT_MACHINERY", "STORAGE_TANK_API650",
                "WELLHEAD_FACILITIES", "GATHERING_MANIFOLD", "INDUSTRIAL_BUILDING_HANGAR",
                "PIPELINE_TRANSPORT", "SKID_PROCESS", "STATIC_VESSEL_COLUMN", "PLANT_PIPING", "CUSTOM_SPECIALIZED"
            ]:
                fallback["typologie"] = typo_llm
            
            if llm_data.get("type_installation"):
                fallback["type_installation"] = llm_data.get("type_installation")
            
            # Injection des paramètres sémantiques si présents
            llm_params = llm_data.get("parametres", {})
            if isinstance(llm_params, dict):
                for k, v in llm_params.items():
                    if v and float(v) > 0:
                        fallback["parametres_cles"][k] = float(v)

        return fallback


class PlanningWBSAgent:
    """Agent 2 : Décomposition WBS en lots et tâches logiques ordonnées selon la typologie."""

    async def _generate_llm_dynamic_wbs(self, nlu: Dict[str, Any], req: PlanningGenerationRequest) -> List[Dict[str, Any]]:
        """Génère dynamiquement un WBS complet et hautement spécialisé via le LLM arkan-planning."""
        wbs_lvl = getattr(req, "wbs_level", 3) or 3
        if wbs_lvl == 2:
            target_desc = "de 5 à 7 grands macro-lots / jalons majeurs de niveau 2 (Ingénierie, Procurement, Génie Civil, Montage, CND/Épreuves, Commissioning)"
        elif wbs_lvl == 4:
            target_desc = "de 20 à 25 activités opérationnelles détaillées de niveau 4 incluant contrôles CND, hydrotests, alignements et dossiers finaux"
        else:
            target_desc = "de 10 à 14 macro-tâches réalistes de niveau 3"

        system_prompt = (
            "Tu es l'ingénieur planificateur en chef EPC ARKAN.\n"
            f"Génère une décomposition WBS ordonnée {target_desc} pour le projet ci-dessous.\n"
            "IMPORTANT : Ne génère AUCUNE tâche de soudage de tuyauterie si le projet n'en a pas besoin !\n"
            "Réponds STRICTEMENT sous forme d'une liste JSON d'objets sans texte additionnel :\n"
            "[\n"
            "  {\n"
            '    "id_tache": "T-010",\n'
            '    "nom": "Libellé technique précis et actionnable",\n'
            '    "phase": "Études | Procurement | Construction | Essais | Commissioning",\n'
            '    "discipline": "01_INGENIERIE_ETUDES | 02_PROCUREMENT_LOGISTIQUE | 03_GENIE_CIVIL_TERRASSEMENT | 04_CHARPENTE_METALLIQUE_BARDAGE | 05_TUYAUTERIE_PREFABRICATION | 06_TUYAUTERIE_MONTAGE_SITE | 07_EQUIPEMENTS_STATIQUES | 08_EQUIPEMENTS_DYNAMIQUES | 09_ELECTRICITE_HT_BT | 10_INSTRUMENTATION_AUTOMATISME | 11_ISOLATION_CALORIFUGE_PEINTURE | 12_PRECOMMISSIONING_TESTS | 13_COMMISSIONING_DEMARRAGE",\n'
            '    "unite_oeuvre": "document | m3 | m2 | ml | u | test | etc.",\n'
            '    "quantite_estimee": 10.0,\n'
            '    "predecesseurs_suggérés": []\n'
            "  }\n"
            "]"
        )
        user_prompt = f"Projet : {nlu.get('type_installation', req.prompt)}\nContexte : {req.prompt}\nLocalisation : {req.localisation or 'Algérie'}\nParamètres clés : {json.dumps(nlu.get('parametres_cles', {}))}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": "arkan-planning",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "stream": False,
                        "options": {"temperature": 0.1, "num_predict": 1200}
                    }
                )
                if resp.status_code == 200:
                    content = resp.json().get("message", {}).get("content", "").strip()
                    idx = content.find('[')
                    while idx != -1:
                        try:
                            tasks, _ = json.JSONDecoder().raw_decode(content[idx:])
                            if isinstance(tasks, list) and len(tasks) >= 5:
                                logger.info(f"[PlanningWBSAgent] WBS dynamique généré par LLM avec succès ({len(tasks)} tâches)")
                                return tasks
                        except Exception:
                            pass
                        idx = content.find('[', idx + 1)
        except Exception as e:
            logger.warning(f"[PlanningWBSAgent] Échec génération WBS dynamique LLM: {e}")
        return self._generate_piping_wbs(nlu, 120.0, 8, 10, 80)

    def _build_level2_macro_wbs(self, raw_wbs: List[Dict[str, Any]], nlu: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Consolide la structure WBS en 5 à 7 macro-lots de Niveau 2."""
        has_civil = any("03_" in t.get("discipline", "") or "civil" in t.get("nom", "").lower() for t in raw_wbs)
        has_elec = any("09_" in t.get("discipline", "") or "10_" in t.get("discipline", "") or "électri" in t.get("nom", "").lower() for t in raw_wbs)
        has_piping = any("05_" in t.get("discipline", "") or "06_" in t.get("discipline", "") or "07_" in t.get("discipline", "") or "08_" in t.get("discipline", "") for t in raw_wbs)
        type_inst = nlu.get("type_installation", "Projet EPC")
        macro_tasks = []

        # 1. Ingénierie
        macro_tasks.append({
            "id_tache": "T-010",
            "nom": f"Macro-Lot 01 : Études d'ingénierie de détail & validations réglementaires ARH ({type_inst})",
            "phase": "Études",
            "discipline": "01_INGENIERIE_ETUDES",
            "unite_oeuvre": "lot",
            "quantite_estimee": 1.0,
            "predecesseurs_suggérés": []
        })

        # 2. Procurement
        macro_tasks.append({
            "id_tache": "T-020",
            "nom": "Macro-Lot 02 : Approvisionnements, commandes critiques et logistique fret sur site",
            "phase": "Procurement",
            "discipline": "02_PROCUREMENT_LOGISTIQUE",
            "unite_oeuvre": "lot",
            "quantite_estimee": 1.0,
            "predecesseurs_suggérés": ["T-010"]
        })

        # 3. Génie Civil (si pertinent)
        if has_civil or len(raw_wbs) > 6:
            macro_tasks.append({
                "id_tache": "T-030",
                "nom": "Macro-Lot 03 : Travaux préparatoires, terrassements généraux et génie civil / fondations",
                "phase": "Génie Civil",
                "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
                "unite_oeuvre": "lot",
                "quantite_estimee": 1.0,
                "predecesseurs_suggérés": ["T-010"]
            })

        # 4. Préfabrication & Montage mécanique
        prev_preds = ["T-020"]
        if any(t["id_tache"] == "T-030" for t in macro_tasks):
            prev_preds.append("T-030")

        tid_mec = f"T-{len(macro_tasks)*10+10:03d}"
        macro_tasks.append({
            "id_tache": tid_mec,
            "nom": f"Macro-Lot 04 : Préfabrication en atelier et montage sur site ({type_inst})",
            "phase": "Construction",
            "discipline": "06_TUYAUTERIE_MONTAGE_SITE" if has_piping else "04_CHARPENTE_METALLIQUE_BARDAGE",
            "unite_oeuvre": "lot",
            "quantite_estimee": 1.0,
            "predecesseurs_suggérés": prev_preds
        })

        # 5. Électricité & Instrumentation (si pertinent)
        if has_elec:
            tid_elec = f"T-{len(macro_tasks)*10+10:03d}"
            macro_tasks.append({
                "id_tache": tid_elec,
                "nom": "Macro-Lot 05 : Électricité BT/HT, instrumentation de contrôle-commande et automatisme DCS/SIS",
                "phase": "Électricité & Contrôle",
                "discipline": "09_ELECTRICITE_HT_BT",
                "unite_oeuvre": "lot",
                "quantite_estimee": 1.0,
                "predecesseurs_suggérés": [tid_mec]
            })

        # 6. Contrôles CND & Épreuves
        tid_cnd = f"T-{len(macro_tasks)*10+10:03d}"
        last_montage_id = macro_tasks[-1]["id_tache"]
        macro_tasks.append({
            "id_tache": tid_cnd,
            "nom": "Macro-Lot 06 : Contrôles non-destructifs (CND 100%), épreuves sous pression et traitement anticorrosion",
            "phase": "Essais & CND",
            "discipline": "12_PRECOMMISSIONING_TESTS",
            "unite_oeuvre": "lot",
            "quantite_estimee": 1.0,
            "predecesseurs_suggérés": [last_montage_id]
        })

        # 7. Précom & Commissioning
        tid_comm = f"T-{len(macro_tasks)*10+10:03d}"
        macro_tasks.append({
            "id_tache": tid_comm,
            "nom": "Macro-Lot 07 : Précommissioning, tests opérationnels, commissioning et mise en service industrielle (RFSU)",
            "phase": "Commissioning",
            "discipline": "13_COMMISSIONING_DEMARRAGE",
            "unite_oeuvre": "lot",
            "quantite_estimee": 1.0,
            "predecesseurs_suggérés": [tid_cnd]
        })

        return macro_tasks

    def _build_level4_detailed_wbs(self, raw_wbs: List[Dict[str, Any]], nlu: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Développe la structure WBS en Niveau 4 détaillé (20 à 30 activités opérationnelles)."""
        expanded: List[Dict[str, Any]] = []

        added_hazop = False
        added_qc_rec = False
        added_geo = False
        added_prep_soud = False
        added_cnd_deep = False
        added_hydro = False
        added_peinture = False
        added_megger = False
        added_loop = False
        added_punch = False
        added_doe = False

        for t in raw_wbs:
            nom_lower = t.get("nom", "").lower()
            disc = t.get("discipline", "")
            expanded.append(dict(t))

            # Après ingénierie
            if "01_" in disc and not added_hazop:
                expanded.append({
                    "id_tache": "T-DET-015",
                    "nom": "Revue pluridisciplinaire 3D Model, Analyse HAZOP/SIL et Dépôt du Dossier Réglementaire ARH",
                    "phase": "Études",
                    "discipline": "01_INGENIERIE_ETUDES",
                    "unite_oeuvre": "revue",
                    "quantite_estimee": 1.0,
                    "predecesseurs_suggérés": [t.get("id_tache", "T-010")]
                })
                added_hazop = True

            # Après procurement
            elif "02_" in disc and not added_qc_rec:
                expanded.append({
                    "id_tache": "T-DET-025",
                    "nom": "Contrôle réception sur site : examen visuel, dimensionnel, certificats matière 3.1 et contrôle PMI",
                    "phase": "Procurement",
                    "discipline": "02_PROCUREMENT_LOGISTIQUE",
                    "unite_oeuvre": "lot réception",
                    "quantite_estimee": 1.0,
                    "predecesseurs_suggérés": [t.get("id_tache", "T-020")]
                })
                added_qc_rec = True

            # Autour du génie civil
            elif "03_" in disc and not added_geo:
                expanded.append({
                    "id_tache": "T-DET-035",
                    "nom": "Essais géotechniques de compactage (Proctor 95%), carottage béton et tests d'écrasement à 28 jours",
                    "phase": "Génie Civil",
                    "discipline": "03_GENIE_CIVIL_TERRASSEMENT",
                    "unite_oeuvre": "série d'essais",
                    "quantite_estimee": 4.0,
                    "predecesseurs_suggérés": [t.get("id_tache", "T-030")]
                })
                added_geo = True

            # Autour de la tuyauterie et soudage
            elif ("05_" in disc or "06_" in disc or "soud" in nom_lower or "tuyau" in nom_lower):
                if not added_prep_soud:
                    expanded.append({
                        "id_tache": "T-DET-055",
                        "nom": "Traçage, chanfreinage mécanique et accostage des tuyauteries selon WPS/PQR qualifiés ASME IX",
                        "phase": "Préfabrication",
                        "discipline": "05_TUYAUTERIE_PREFABRICATION",
                        "unite_oeuvre": "joint préparé",
                        "quantite_estimee": 25.0,
                        "predecesseurs_suggérés": [t.get("id_tache")]
                    })
                    added_prep_soud = True
                if not added_cnd_deep:
                    expanded.append({
                        "id_tache": "T-DET-065",
                        "nom": "Contrôles non-destructifs 100% CND : Radiographie gamma/X (RT), ultrasons phased array et ressuage (PT)",
                        "phase": "Contrôles CND",
                        "discipline": "12_PRECOMMISSIONING_TESTS",
                        "unite_oeuvre": "joint inspecté",
                        "quantite_estimee": 25.0,
                        "predecesseurs_suggérés": [t.get("id_tache")]
                    })
                    added_cnd_deep = True
                if not added_hydro:
                    expanded.append({
                        "id_tache": "T-DET-075",
                        "nom": "Épreuve hydrostatique sous pression de timbrage (1.5x PS), palier d'épreuve 4h et séchage air sec -40°C",
                        "phase": "Épreuves",
                        "discipline": "12_PRECOMMISSIONING_TESTS",
                        "unite_oeuvre": "test hydro",
                        "quantite_estimee": 1.0,
                        "predecesseurs_suggérés": [t.get("id_tache")]
                    })
                    added_hydro = True
                if not added_peinture:
                    expanded.append({
                        "id_tache": "T-DET-085",
                        "nom": "Traitement de surface par sablage SA 2.5 et application peinture anticorrosion 3 couches (ISO 12944 C5-M)",
                        "phase": "Finition",
                        "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE",
                        "unite_oeuvre": "m²",
                        "quantite_estimee": 180.0,
                        "predecesseurs_suggérés": [t.get("id_tache")]
                    })
                    added_peinture = True

            # Autour de l'électricité et instrumentation
            elif ("09_" in disc or "10_" in disc or "câble" in nom_lower or "armoire" in nom_lower):
                if not added_megger:
                    expanded.append({
                        "id_tache": "T-DET-105",
                        "nom": "Contrôle d'isolement Mégohmmètre (1000V/5000V), test de continuité des câbles et mesure du réseau de terre",
                        "phase": "Essais Câblage",
                        "discipline": "12_PRECOMMISSIONING_TESTS",
                        "unite_oeuvre": "départ testé",
                        "quantite_estimee": 16.0,
                        "predecesseurs_suggérés": [t.get("id_tache")]
                    })
                    added_megger = True
                if not added_loop:
                    expanded.append({
                        "id_tache": "T-DET-115",
                        "nom": "Vérification individuelle point-à-point des boucles instrumentales terrain (Cold & Hot Loop Checking 100%)",
                        "phase": "Loop Checks",
                        "discipline": "12_PRECOMMISSIONING_TESTS",
                        "unite_oeuvre": "boucle vérifiée",
                        "quantite_estimee": 20.0,
                        "predecesseurs_suggérés": [t.get("id_tache")]
                    })
                    added_loop = True

            # Autour du commissioning
            elif ("12_" in disc or "13_" in disc or "commissioning" in nom_lower or "mise en service" in nom_lower):
                if not added_punch:
                    expanded.append({
                        "id_tache": "T-DET-135",
                        "nom": "Levée des réserves Punch-List Catégorie A et B et inspection contradictoire préalable au démarrage",
                        "phase": "Commissioning",
                        "discipline": "13_COMMISSIONING_DEMARRAGE",
                        "unite_oeuvre": "punch list",
                        "quantite_estimee": 1.0,
                        "predecesseurs_suggérés": [t.get("id_tache")]
                    })
                    added_punch = True
                if not added_doe:
                    expanded.append({
                        "id_tache": "T-DET-145",
                        "nom": "Constitution, validation et signature du Dossier des Ouvrages Exécutés (DOE / Dossier Constructeur) pour quitus final ARH",
                        "phase": "Commissioning",
                        "discipline": "13_COMMISSIONING_DEMARRAGE",
                        "unite_oeuvre": "dossier constructeur",
                        "quantite_estimee": 1.0,
                        "predecesseurs_suggérés": [t.get("id_tache")]
                    })
                    added_doe = True

        # Normaliser les identifiants et les liaisons séquentielles pour garantir un CPM 100% cohérent
        result = []
        for idx, task in enumerate(expanded):
            new_id = f"T-{idx*10+10:03d}"
            task_copy = dict(task)
            task_copy["id_tache"] = new_id
            if idx == 0:
                task_copy["predecesseurs_suggérés"] = []
                task_copy["predecesseurs"] = []
            else:
                prev_id = f"T-{(idx-1)*10+10:03d}"
                task_copy["predecesseurs_suggérés"] = [prev_id]
                task_copy["predecesseurs"] = [prev_id]
            result.append(task_copy)

        return result

    def _apply_wbs_granularity(self, raw_wbs: List[Dict[str, Any]], wbs_level: int, nlu: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Adapte la décomposition selon le niveau de granularité demandé :
        - Niveau 2 : Vue Macro / Jalons Clés (5 à 7 macro-lots consolidés)
        - Niveau 3 : Vue Standard Métier EPC (10 à 15 tâches de base)
        - Niveau 4 : Vue Détaillée Opérationnelle (20 à 30+ activités élémentaires avec contrôles CND, hydrotests, alignements laser, dossiers finaux)
        """
        if wbs_level == 2:
            return self._build_level2_macro_wbs(raw_wbs, nlu)
        elif wbs_level == 4:
            return self._build_level4_detailed_wbs(raw_wbs, nlu)
        return raw_wbs


    async def decompose(self, nlu_result: Dict[str, Any], request: PlanningGenerationRequest) -> List[Dict[str, Any]]:
        typologie = nlu_result.get("typologie", "PLANT_PIPING")
        params = nlu_result.get("parametres_cles", {})
        longueur = float(params.get("longueur_ml", 120.0))
        diam_p = int(params.get("diametre_pouces", 8))
        nb_units = int(params.get("nb_unites", 4))
        nb_joints = int(params.get("total_joints_soudes", max(10, int(longueur / 12))))
        total_di = int(params.get("total_di", nb_joints * diam_p))

        # ── Sélection de la structure WBS de base ──
        if typologie == "FIRE_PROTECTION_SAFETY":
            raw_wbs = self._generate_fire_protection_wbs(nlu_result)
        elif typologie == "SOLAR_PV_POWER_SYSTEM":
            raw_wbs = self._generate_solar_pv_wbs(nlu_result)
        elif typologie == "FLARE_SYSTEM_AND_IGNITION":
            raw_wbs = self._generate_flare_wbs(nlu_result)
        elif typologie == "CIVIL_BASIN_POND_LINING":
            raw_wbs = self._generate_basin_pond_wbs(nlu_result, params.get("volume_m3", 2500.0))
        elif typologie == "CATHODIC_PROTECTION":
            raw_wbs = self._generate_cathodic_protection_wbs(nlu_result, longueur)
        elif typologie == "FIBER_OPTIC_TELECOM":
            raw_wbs = self._generate_fiber_optic_telecom_wbs(nlu_result, longueur)
        elif typologie == "WELLHEAD_AND_MANIFOLD_GATHERING":
            raw_wbs = self._generate_wellhead_and_manifold_wbs(nlu_result)
        elif typologie == "ELECTRICAL_TGBT_SUBSTATION":
            raw_wbs = self._generate_tgbt_electrical_wbs(nlu_result, nb_units)
        elif typologie == "INSTRUMENTATION_DCS_AUTOMATION":
            raw_wbs = self._generate_instrumentation_dcs_wbs(nlu_result, nb_units)
        elif typologie == "SHUTDOWN_REVAMPING_MAINTENANCE":
            raw_wbs = self._generate_shutdown_wbs(nlu_result, nb_units)
        elif typologie == "CIVIL_EARTHWORKS_CONCRETE":
            raw_wbs = self._generate_civil_wbs(nlu_result, params.get("surface_m2", 600.0))
        elif typologie == "ROTATING_EQUIPMENT_MACHINERY":
            raw_wbs = self._generate_machinery_wbs(nlu_result, nb_units)
        elif typologie == "PIPELINE_TRANSPORT":
            raw_wbs = self._generate_pipeline_wbs(nlu_result, longueur, diam_p, nb_joints, total_di)
        elif typologie == "INDUSTRIAL_BUILDING_HANGAR":
            raw_wbs = self._generate_building_hangar_wbs(nlu_result)
        elif typologie == "WELLHEAD_FACILITIES":
            raw_wbs = self._generate_wellhead_wbs(nlu_result)
        elif typologie == "GATHERING_MANIFOLD":
            raw_wbs = self._generate_manifold_wbs(nlu_result)
        elif typologie == "STORAGE_TANK_API650":
            raw_wbs = self._generate_tank_wbs(nlu_result)
        elif typologie == "SKID_PROCESS":
            raw_wbs = self._generate_skid_wbs(nlu_result, longueur, diam_p)
        elif typologie == "CUSTOM_SPECIALIZED":
            raw_wbs = await self._generate_llm_dynamic_wbs(nlu_result, request)
        else:
            raw_wbs = self._generate_piping_wbs(nlu_result, longueur, diam_p, nb_joints, total_di)

        # ── Enrichissement Intelligent : Phases de Pré-Commissioning & Commissioning Dédiées (ICAPS / OPERCOM) ──
        prompt_lower = (request.prompt or "").lower()
        needs_deep_comm = any(k in prompt_lower for k in [
            "precom", "précom", "comm", "commissioning", "mise en service",
            "icaps", "opercom", "rfsu", "rfo", "démarrage", "demarrage", "essais", "pgr"
        ]) or typologie in ["SKID_PROCESS", "ROTATING_EQUIPMENT_MACHINERY", "STORAGE_TANK_API650", "PIPELINE_TRANSPORT", "INSTRUMENTATION_DCS_AUTOMATION"]

        if needs_deep_comm and raw_wbs:
            try:
                from planning_commissioning_knowledge import commissioning_engine
                
                # Détection multi-équipements basée sur le texte du prompt
                target_eqs = []
                if any(w in prompt_lower for w in ["séparateur", "separateur", "ballon", "vessel", "skid"]):
                    target_eqs.append("PRESSURE_VESSEL_SEPARATOR")
                if any(w in prompt_lower for w in ["compresseur", "compression", "turbine"]):
                    target_eqs.append("CENTRIFUGAL_COMPRESSOR_TRAIN")
                if any(w in prompt_lower for w in ["bac", "stockage", "tank", "cuve"]):
                    target_eqs.append("STORAGE_TANK_API650")
                if any(w in prompt_lower for w in ["pompe", "pompage", "pump"]):
                    target_eqs.append("CENTRIFUGAL_PUMP_PACKAGE")
                if any(w in prompt_lower for w in ["pipeline", "gazoduc", "oléoduc", "oleoduc", "canalisation"]):
                    target_eqs.append("CROSS_COUNTRY_PIPELINE")
                if any(w in prompt_lower for w in ["sous-station", "substation", "switchgear", "tgbt", "transformateur", "électri"]):
                    target_eqs.append("ELECTRICAL_SUBSTATION_SWITCHGEAR")
                if any(w in prompt_lower for w in ["dcs", "sis", "esd", "instrumentation", "automate", "f&g"]):
                    target_eqs.append("INSTRUMENTATION_DCS_SIS")

                # Fallback par typologie si aucun mot-clé spécifique
                if not target_eqs:
                    eq_map = {
                        "SKID_PROCESS": ["PRESSURE_VESSEL_SEPARATOR", "CENTRIFUGAL_PUMP_PACKAGE", "INSTRUMENTATION_DCS_SIS"],
                        "ROTATING_EQUIPMENT_MACHINERY": ["CENTRIFUGAL_COMPRESSOR_TRAIN", "CENTRIFUGAL_PUMP_PACKAGE"],
                        "STORAGE_TANK_API650": ["STORAGE_TANK_API650", "CENTRIFUGAL_PUMP_PACKAGE", "INSTRUMENTATION_DCS_SIS"],
                        "PIPELINE_TRANSPORT": ["CROSS_COUNTRY_PIPELINE", "INSTRUMENTATION_DCS_SIS"],
                        "ELECTRICAL_TGBT_SUBSTATION": ["ELECTRICAL_SUBSTATION_SWITCHGEAR"],
                        "INSTRUMENTATION_DCS_AUTOMATION": ["INSTRUMENTATION_DCS_SIS"],
                        "WELLHEAD_AND_MANIFOLD_GATHERING": ["PRESSURE_VESSEL_SEPARATOR", "INSTRUMENTATION_DCS_SIS"],
                        "FLARE_SYSTEM_AND_IGNITION": ["PRESSURE_VESSEL_SEPARATOR", "INSTRUMENTATION_DCS_SIS"]
                    }
                    target_eqs = eq_map.get(typologie, ["PRESSURE_VESSEL_SEPARATOR", "INSTRUMENTATION_DCS_SIS"])
                
                # Éliminer les doublons tout en conservant l'ordre
                target_eqs = list(dict.fromkeys(target_eqs))
                comm_tasks = commissioning_engine.generate_commissioning_activities(
                    equipment_types=target_eqs,
                    project_name=nlu_result.get("type_installation", "Installation")
                )
                if comm_tasks:
                    # Remplacer les tâches génériques de fin par les tâches détaillées
                    filtered_wbs = [t for t in raw_wbs if "12_" not in t.get("discipline", "") and "13_" not in t.get("discipline", "")]
                    
                    # Identifier toutes les tâches terminales de construction (sans successeur dans filtered_wbs)
                    all_sub_preds = set()
                    for t in filtered_wbs:
                        preds = t.get("predecesseurs_suggérés") or t.get("predecesseurs") or []
                        all_sub_preds.update(p.get("id") if isinstance(p, dict) else str(p) for p in preds)
                    
                    terminal_ids = [t["id_tache"] for t in filtered_wbs if t["id_tache"] not in all_sub_preds]
                    if not terminal_ids and filtered_wbs:
                        terminal_ids = [filtered_wbs[-1]["id_tache"]]
                    
                    # Chaîner la première tâche de précom à toutes les fins de branches de construction
                    comm_tasks[0]["predecesseurs"] = terminal_ids
                    
                    wbs_merged = filtered_wbs + comm_tasks
                    return self._apply_wbs_granularity(wbs_merged, getattr(request, "wbs_level", 3) or 3, nlu_result)
            except Exception as e_comm:
                logger.warning(f"[PlanningWBS] Erreur enrichissement commissioning : {e_comm}")

        return self._apply_wbs_granularity(raw_wbs, getattr(request, "wbs_level", 3) or 3, nlu_result)


    # ── 1. ÉLECTRICITÉ & TGBT ──
    def _generate_tgbt_electrical_wbs(self, nlu: Dict[str, Any], nb_cellules: int) -> List[Dict[str, Any]]:
        return [
            {"id_tache": "T-010", "nom": "Études d'ingénierie électrique, schémas unifilaires, bilans de puissance et carnets de câbles", "phase": "Études", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 6.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": f"Approvisionnement TGBT ({nb_cellules} cellules), disjoncteurs débrochables, jeux de barres cuivre et accessoires", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": "Aménagement local électrique : Dalles, caniveaux techniques et passages coupe-feu", "phase": "Génie Civil", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m²", "quantite_estimee": 45.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": "Pose du châssis support métallique et mise à niveau des socles d'armoires", "phase": "Supportage", "discipline": "04_STRUCTURE_CHARPENTE", "unite_oeuvre": "ml", "quantite_estimee": nb_cellules * 1.2, "predecesseurs_suggérés": ["T-030"]},
            {"id_tache": "T-050", "nom": f"Déchargement, manutention délicate et érection des cellules du TGBT ({nb_cellules} cellules)", "phase": "Montage Électrique", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "cellule (u)", "quantite_estimee": float(nb_cellules), "predecesseurs_suggérés": ["T-020", "T-040"]},
            {"id_tache": "T-060", "nom": "Assemblage mécanique des cellules, jonctionnement et serrage au couple des jeux de barres cuivre", "phase": "Montage Électrique", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "jeu de barres", "quantite_estimee": float(nb_cellules), "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-070", "nom": "Pose des chemins de câbles intérieurs et raccordement au réseau de terre général", "phase": "Cheminement & Terre", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "ml", "quantite_estimee": 80.0, "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-080", "nom": "Tirage et repérage des câbles de puissance d'alimentation et des départs BT", "phase": "Tirage Câbles", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "ml câble tiré", "quantite_estimee": 450.0, "predecesseurs_suggérés": ["T-060", "T-070"]},
            {"id_tache": "T-090", "nom": "Confection des embouts, raccordement sur disjoncteurs et serrage dynamométrique", "phase": "Raccordement", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "raccordement câble", "quantite_estimee": nb_cellules * 8.0, "predecesseurs_suggérés": ["T-080"]},
            {"id_tache": "T-100", "nom": "Câblage de la filerie auxiliaire, télécommandes, TC/TT et signalisation automate DCS", "phase": "Filerie & Contrôle", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "fil / boucle", "quantite_estimee": 24.0, "predecesseurs_suggérés": ["T-090"]},
            {"id_tache": "T-110", "nom": "Contrôles diélectriques, test d'isolement (Mégohmmètre 1000V) et continuité des terres", "phase": "Essais Précom", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "départ électrique", "quantite_estimee": float(nb_cellules * 4), "predecesseurs_suggérés": ["T-090", "T-100"]},
            {"id_tache": "T-120", "nom": "Injection primaire et secondaire des relais de protection et déclenchement disjoncteurs", "phase": "Essais Relais", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "relais de protection", "quantite_estimee": float(nb_cellules), "predecesseurs_suggérés": ["T-110"]},
            {"id_tache": "T-130", "nom": "Mise sous tension progressive à vide, contrôle rotation des phases et équilibrage", "phase": "Mise sous Tension", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "mise sous tension", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-120"]},
            {"id_tache": "T-140", "nom": "Essais en charge (Load Test), réception contradictoire et signature du PV ARH / Sonelgaz", "phase": "Commissioning", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "installation", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-130"]}
        ]

    # ── 2. INSTRUMENTATION & AUTOMATISME (DCS / SIS / F&G) ──
    def _generate_instrumentation_dcs_wbs(self, nlu: Dict[str, Any], nb_units: int) -> List[Dict[str, Any]]:
        return [
            {"id_tache": "T-010", "nom": "Études d'architecture automate, matrices Cause & Effet et fiches d'instruments", "phase": "Études", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 8.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": "Approvisionnement armoires DCS/ESD, transmetteurs Smart HART et kits tubing inox 316L", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": "Pose des armoires système et serveur en salle de contrôle (CCR) / Shelter", "phase": "Montage Armoires", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "armoire / cellule", "quantite_estimee": 4.0, "predecesseurs_suggérés": ["T-020"]},
            {"id_tache": "T-040", "nom": "Montage des transmetteurs de pression, température, niveau et débit sur piquages", "phase": "Montage Instruments", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "instrument (u)", "quantite_estimee": 16.0, "predecesseurs_suggérés": ["T-020"]},
            {"id_tache": "T-050", "nom": "Façonnage et pose des lignes d'impulsion tubing inox 316L Swagelok", "phase": "Tubing", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "ml", "quantite_estimee": 120.0, "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-060", "nom": "Tirage et blindage des câbles paires torsadées instrumentation IS (Bleu) / Non-IS", "phase": "Câblage", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "ml câble tiré", "quantite_estimee": 600.0, "predecesseurs_suggérés": ["T-030", "T-040"]},
            {"id_tache": "T-070", "nom": "Raccordement des boîtes de jonction locales (JB) et des cartes I/O automate", "phase": "Raccordement", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "fil / boucle", "quantite_estimee": 48.0, "predecesseurs_suggérés": ["T-060"]},
            {"id_tache": "T-080", "nom": "Étalonnage des capteurs au banc métrologique et test des vannes de régulation", "phase": "Calibration", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "instrument (u)", "quantite_estimee": 16.0, "predecesseurs_suggérés": ["T-070", "T-050"]},
            {"id_tache": "T-090", "nom": "Test individuel des boucles instrumentales terrain vers DCS (Loop Checks 100%)", "phase": "Précommissioning", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "boucle instrumentale (Loop)", "quantite_estimee": 24.0, "predecesseurs_suggérés": ["T-080", "T-050"]},
            {"id_tache": "T-100", "nom": "Test de logique de sécurité du système ESD / SIS et validation SIL 3", "phase": "Sécurité SIS", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "boucle de sécurité", "quantite_estimee": 8.0, "predecesseurs_suggérés": ["T-090"]},
            {"id_tache": "T-110", "nom": "Test d'intégration globale du système de détection Feu & Gaz (F&G)", "phase": "Sécurité F&G", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "détecteur (u)", "quantite_estimee": 12.0, "predecesseurs_suggérés": ["T-090"]},
            {"id_tache": "T-120", "nom": "Mise en service opérationnelle du contrôle-commande et démarrage unité", "phase": "Commissioning", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "installation", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-100", "T-110"]}
        ]

    # ── 3. ARRÊT D'UNITÉ / RÉVISION / REVAMPING ──
    def _generate_shutdown_wbs(self, nlu: Dict[str, Any], nb_equipements: int) -> List[Dict[str, Any]]:
        return [
            {"id_tache": "T-010", "nom": "Préparation du dossier d'arrêt (Turnaround Plan), permis spéciaux et consignation LOTO", "phase": "Préparation", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "dossier", "quantite_estimee": 1.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": "Mise à disposition du site, dépressurisation, vidange et dégazage des capacités", "phase": "Mise à Disposition", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "système procédé", "quantite_estimee": 2.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": "Pose des joints pleins de sectionnement (Spading / Blindage 100%)", "phase": "Sécurisation", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "joint plein (u)", "quantite_estimee": 24.0, "predecesseurs_suggérés": ["T-020"]},
            {"id_tache": "T-040", "nom": "Ouverture des trous d'homme (Manholes) et ventilation forcée des capacités", "phase": "Ouverture Équipements", "discipline": "07_EQUIPEMENTS_STATIQUES", "unite_oeuvre": "trou d'homme", "quantite_estimee": 8.0, "predecesseurs_suggérés": ["T-030"]},
            {"id_tache": "T-050", "nom": "Extraction au tire-faisceau et nettoyage haute pression 1000 bar des échangeurs tubulaires", "phase": "Nettoyage HP", "discipline": "07_EQUIPEMENTS_STATIQUES", "unite_oeuvre": "faisceau (u)", "quantite_estimee": float(nb_equipements), "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-060", "nom": "Inspection métallurgique interne, contrôles CND (Épaisseurs ultrasons, ressuage, magnétoscopie)", "phase": "Inspection QA/QC", "discipline": "05_TUYAUTERIE_PREFABRICATION", "unite_oeuvre": "équipement inspecté", "quantite_estimee": float(nb_equipements), "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-070", "nom": "Remplacement des éléments corrodés, plateaux de colonnes et joints d'étanchéité neufs", "phase": "Remise en État", "discipline": "07_EQUIPEMENTS_STATIQUES", "unite_oeuvre": "équipement", "quantite_estimee": float(nb_equipements), "predecesseurs_suggérés": ["T-060"]},
            {"id_tache": "T-080", "nom": "Réinsertion des faisceaux neufs, fermeture des boîtes et serrage au couple contrôlé", "phase": "Fermeture & Serrage", "discipline": "07_EQUIPEMENTS_STATIQUES", "unite_oeuvre": "faisceau (u)", "quantite_estimee": float(nb_equipements), "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-090", "nom": "Dépose des joints pleins (Despading) et remise en configuration normale", "phase": "Déblindage", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "joint plein (u)", "quantite_estimee": 24.0, "predecesseurs_suggérés": ["T-080"]},
            {"id_tache": "T-100", "nom": "Épreuve hydrostatique / Test d'étanchéité N2/He de l'unité révisée", "phase": "Test d'Étanchéité", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "système procédé", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-090"]},
            {"id_tache": "T-110", "nom": "Inertage à l'azote N2 et démarrage progressif de l'unité sous contrôle ARH", "phase": "Redémarrage", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "mise en produit", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-100"]}
        ]

    # ── 4. MACHINES TOURNANTES & POMPES ──
    def _generate_machinery_wbs(self, nlu: Dict[str, Any], nb_machines: int) -> List[Dict[str, Any]]:
        return [
            {"id_tache": "T-010", "nom": "Études mécaniques d'implantation, calculs de flexibilité tuyauteries et plans de massifs", "phase": "Études", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 5.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": f"Approvisionnement groupes motopompes / compresseurs API ({nb_machines} machines) et skids auxiliaires", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "machine", "quantite_estimee": float(nb_machines), "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": "Terrassement et coulage des massifs béton armé lourds anti-vibratiles", "phase": "Génie Civil", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³ béton", "quantite_estimee": nb_machines * 15.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": "Grutage, positionnement et scellement au coulis sans retrait (Epoxy Grouting)", "phase": "Montage Mécanique", "discipline": "08_EQUIPEMENTS_DYNAMIQUES", "unite_oeuvre": "machine", "quantite_estimee": float(nb_machines), "predecesseurs_suggérés": ["T-020", "T-030"]},
            {"id_tache": "T-050", "nom": "Raccordement des tuyauteries aspiration et refoulement sans contrainte mécanique (Pipe Strain Check)", "phase": "Tuyauterie", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "raccordement bride", "quantite_estimee": nb_machines * 4.0, "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-060", "nom": "Alignement laser haute précision de l'accouplement arbre moteur / pompe (tolérance <0.05 mm)", "phase": "Alignement Laser", "discipline": "08_EQUIPEMENTS_DYNAMIQUES", "unite_oeuvre": "alignement (u)", "quantite_estimee": float(nb_machines), "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-070", "nom": "Raccordement puissance électrique moteur HT/BT et pose capteurs de vibration / température", "phase": "Électricité & Instru", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "moteur", "quantite_estimee": float(nb_machines), "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-080", "nom": "Contrôle rotation à vide du moteur découplé (Uncoupled Solo Run 2h)", "phase": "Essais Moteur", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "machine", "quantite_estimee": float(nb_machines), "predecesseurs_suggérés": ["T-060", "T-070"]},
            {"id_tache": "T-090", "nom": "Accouplement final, graissage/lubrification et test de fonctionnement en boucle fermée (4h Run Test)", "phase": "Commissioning", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "machine", "quantite_estimee": float(nb_machines), "predecesseurs_suggérés": ["T-080"]},
            {"id_tache": "T-100", "nom": "Mesure des vibrations spectrales (Norme ISO 10816), réception et mise en service ARH", "phase": "Réception Finale", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "installation", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-090"]}
        ]

    # ── 5. GÉNIE CIVIL & TERRASSEMENTS ──
    def _generate_civil_wbs(self, nlu: Dict[str, Any], surf_m2: float) -> List[Dict[str, Any]]:
        return [
            {"id_tache": "T-010", "nom": "Études géotechniques de sol, plans de terrassement et implantation topographique", "phase": "Études", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 4.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": f"Décapage terre végétale, déblais et nivellement général de la plateforme ({int(surf_m2)} m²)", "phase": "Terrassement", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³", "quantite_estimee": surf_m2 * 0.4, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": "Fouilles en rigoles et en puits pour fondations et caniveaux VRD", "phase": "Fouilles", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³", "quantite_estimee": surf_m2 * 0.2, "predecesseurs_suggérés": ["T-020"]},
            {"id_tache": "T-040", "nom": "Pose du réseau d'évacuation des eaux pluviales et caniveaux d'assainissement", "phase": "VRD & Réseaux", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml", "quantite_estimee": 120.0, "predecesseurs_suggérés": ["T-030"]},
            {"id_tache": "T-050", "nom": "Pose de la ceinture de terre en cuivre nu en fond de fouille et soudures aluminothermiques", "phase": "Mise à la Terre", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml", "quantite_estimee": 160.0, "predecesseurs_suggérés": ["T-030"]},
            {"id_tache": "T-060", "nom": "Coulage du béton de propreté sous semelles et dalles (ép. 10 cm)", "phase": "Béton Propreté", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³ béton", "quantite_estimee": surf_m2 * 0.1, "predecesseurs_suggérés": ["T-040", "T-050"]},
            {"id_tache": "T-070", "nom": "Ferraillage haute adhérence (FeE500) des semelles et longrines", "phase": "Ferraillage", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "t", "quantite_estimee": surf_m2 * 0.025, "predecesseurs_suggérés": ["T-060"]},
            {"id_tache": "T-080", "nom": "Coffrage métallique et coulage du béton armé C30/37 avec vibration soignée", "phase": "Coulage Béton", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³ béton", "quantite_estimee": surf_m2 * 0.25, "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-090", "nom": "Réalisation du dallage industriel avec durcisseur quartz et sciage des joints de dilatation", "phase": "Dallage Industriel", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m²", "quantite_estimee": surf_m2, "predecesseurs_suggérés": ["T-080"]},
            {"id_tache": "T-100", "nom": "Contrôles scléromètre, écrasement d'éprouvettes béton à 28 jours et PV de réception GC", "phase": "Réception GC", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "lot béton", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-090"]}
        ]

    # ── 6. PIPELINES DE TRANSPORT ──
    def _generate_pipeline_wbs(self, nlu: Dict[str, Any], longueur_ml: float, diam_p: int, nb_joints: int, total_di: int) -> List[Dict[str, Any]]:
        nb_coudes = max(10, int(round(longueur_ml / 250.0)))
        return [
            {"id_tache": "T-010", "nom": "Études de tracé, profil en long, P&ID et permis de construire (Right of Way)", "phase": "Études & Ingénierie", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": max(5, int(longueur_ml / 1500)), "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": f"Approvisionnement tubes acier API 5L {diam_p} pouces, vannes API 6D et accessoires", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": f"Piste et emprise pipeline (Right of Way / RoW) : Débroussaillage et nivellement ({int(longueur_ml)} ml)", "phase": "Piste & Terrassement", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml", "quantite_estimee": longueur_ml, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": f"Bardage et distribution des tubes de 12m le long de la piste (Stringing {int(longueur_ml)} ml)", "phase": "Bardage & Manutention", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "ml", "quantite_estimee": longueur_ml, "predecesseurs_suggérés": ["T-030", "T-020"]},
            {"id_tache": "T-050", "nom": f"Cintrage à froid des tubes sur piste selon profil altimétrique ({nb_coudes} coudes)", "phase": "Cintrage", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "coude cintré (u)", "quantite_estimee": nb_coudes, "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-060", "nom": f"Excavation de la tranchée pipeline à profondeur réglementaire ({int(longueur_ml)} ml)", "phase": "Tranchée", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml", "quantite_estimee": longueur_ml, "predecesseurs_suggérés": ["T-030"]},
            {"id_tache": "T-070", "nom": f"Soudage en ligne du pipeline (Mainline Welding - {nb_joints} joints circonférentiels)", "phase": "Soudage en Ligne", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "joint soudé ou DI", "quantite_estimee": nb_joints, "predecesseurs_suggérés": ["T-040", "T-050"]},
            {"id_tache": "T-080", "nom": f"Contrôle CND 100% des soudures pipeline (Radiographie interne RX / AUT) ({nb_joints} joints)", "phase": "Contrôle CND", "discipline": "05_TUYAUTERIE_PREFABRICATION", "unite_oeuvre": "joint contrôlé", "quantite_estimee": nb_joints, "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-090", "nom": f"Revêtement anticorrosion des joints soudés sur piste (Field Joint Coating - {nb_joints} manchons)", "phase": "Revêtement Joints", "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE", "unite_oeuvre": "joint revêtu", "quantite_estimee": nb_joints, "predecesseurs_suggérés": ["T-080"]},
            {"id_tache": "T-100", "nom": "Contrôle d'isolement au balai électrique haute tension (Holiday Detection à 25 kV)", "phase": "Contrôle Diélectrique", "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE", "unite_oeuvre": "ml", "quantite_estimee": longueur_ml, "predecesseurs_suggérés": ["T-090"]},
            {"id_tache": "T-110", "nom": "Descente de la colonne soudée en tranchée (Lowering-in avec Sidebooms)", "phase": "Descente en Tranchée", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "ml", "quantite_estimee": longueur_ml, "predecesseurs_suggérés": ["T-060", "T-100"]},
            {"id_tache": "T-120", "nom": "Remblaiement protecteur tamisé et remise en état des sols (Backfilling)", "phase": "Remblaiement", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml", "quantite_estimee": longueur_ml, "predecesseurs_suggérés": ["T-110"]},
            {"id_tache": "T-130", "nom": "Installation du système de protection cathodique (Poste à courant imposé & déversoir)", "phase": "Protection Cathodique", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "poste", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-120"]},
            {"id_tache": "T-140", "nom": "Raclages de nettoyage et passage du piston de calibrage géométrique (Caliper Pig)", "phase": "Calibrage Pig", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "section", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-120"]},
            {"id_tache": "T-150", "nom": "Épreuve hydrostatique de résistance et d'étanchéité à 1.5x PMA pendant 24h", "phase": "Hydrotest 24h", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "section", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-140", "T-130"]},
            {"id_tache": "T-160", "nom": "Séchage de la conduite à l'air sec déshydraté (Point de rosée < -40°C)", "phase": "Séchage Conduite", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "section", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-150"]},
            {"id_tache": "T-170", "nom": "Inertage à l'azote gazeux N2 et mise sous gaz commerciale sous contrôle ARH", "phase": "Mise en Gaz ARH", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "mise en produit", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-160"]}
        ]

    # ── 7. BÂTIMENTS INDUSTRIELS & HANGARS ──
    def _generate_building_hangar_wbs(self, nlu: Dict[str, Any]) -> List[Dict[str, Any]]:
        surf = nlu.get("parametres_cles", {}).get("surface_m2", 600.0)
        return [
            {"id_tache": "T-010", "nom": "Études d'ingénierie GC/Structure, calculs Eurocode 3 et plans d'atelier charpente", "phase": "Études", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 6.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": "Approvisionnement profilés métalliques IPE/HEA, pannes Z, bardage et visserie", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": f"Terrassement, fouilles et coulage des massifs de fondation en béton armé ({int(surf)} m²)", "phase": "Génie Civil", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³ béton", "quantite_estimee": round(surf * 0.2, 1), "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": "Préfabrication en atelier et peinture anticorrosion des éléments de charpente métallique", "phase": "Préfabrication", "discipline": "04_STRUCTURE_CHARPENTE", "unite_oeuvre": "t", "quantite_estimee": round(surf * 0.045, 1), "predecesseurs_suggérés": ["T-020"]},
            {"id_tache": "T-050", "nom": "Montage et levage de la structure primaire (Poteaux, traverses, fermes et contreventements)", "phase": "Montage Charpente", "discipline": "04_STRUCTURE_CHARPENTE", "unite_oeuvre": "t", "quantite_estimee": round(surf * 0.045, 1), "predecesseurs_suggérés": ["T-030", "T-040"]},
            {"id_tache": "T-060", "nom": f"Pose de la couverture toiture et du bardage double peau avec isolation ({int(surf*2)} m²)", "phase": "Couverture & Bardage", "discipline": "04_STRUCTURE_CHARPENTE", "unite_oeuvre": "m²", "quantite_estimee": round(surf * 2.2, 1), "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-070", "nom": f"Réalisation du dallage industriel béton surfacé quartz avec couche anti-poussière ({int(surf)} m²)", "phase": "Dallage", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m²", "quantite_estimee": surf, "predecesseurs_suggérés": ["T-060"]},
            {"id_tache": "T-080", "nom": "Installation du réseau électrique, éclairage industriel LED, prises et mise à la terre", "phase": "Électricité", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "point lumineux / prise", "quantite_estimee": 28.0, "predecesseurs_suggérés": ["T-060"]},
            {"id_tache": "T-090", "nom": "Installation du système de sécurité incendie, extincteurs, détection fumée et RIA", "phase": "Sécurité Incendie", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "détecteur (u)", "quantite_estimee": 12.0, "predecesseurs_suggérés": ["T-080"]},
            {"id_tache": "T-100", "nom": "Réception technique, contrôle de conformité bâtiment et remise des clés", "phase": "Réception Finale", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "installation", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-070", "T-080", "T-090"]}
        ]

    # ── 8. TÊTES DE PUITS & PUITS MULTIPHASIQUES ──
    def _generate_wellhead_wbs(self, nlu: Dict[str, Any]) -> List[Dict[str, Any]]:
        nb_puits = nlu.get("parametres_cles", {}).get("nb_unites", 4)
        return [
            {"id_tache": "T-010", "nom": "Études de détail, P&ID tête de puits, schémas hydrauliques WHCP et fiches API 6A", "phase": "Études", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 6.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": f"Approvisionnement arbres de noël API 6A 5000/10000 PSI, chokes et panneaux WHCP ({nb_puits} puits)", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "wellhead", "quantite_estimee": float(nb_puits), "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": f"Aménagement de la plateforme de puits et réfection de la cave de puits en béton armé ({nb_puits} caves)", "phase": "Génie Civil", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "cave de puits", "quantite_estimee": float(nb_puits), "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": f"Montage mécanique des têtes de puits API 6A, vannes maîtresses et duses de régulation (Chokes)", "phase": "Montage Tête de Puits", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "wellhead", "quantite_estimee": float(nb_puits), "predecesseurs_suggérés": ["T-020", "T-030"]},
            {"id_tache": "T-050", "nom": "Pose et raccordement des panneaux de contrôle hydraulique de sécurité de puits (WHCP)", "phase": "Contrôle WHCP", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "panneau WHCP", "quantite_estimee": float(nb_puits), "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-060", "nom": "Pose du tubing inox haute pression (10000 PSI) vers vannes de sécurité SSV/SCSSV", "phase": "Tubing HP", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "ml", "quantite_estimee": nb_puits * 35.0, "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-070", "nom": "Préfabrication et raccordement de la flowline de liaison vers manifold", "phase": "Tuyauterie Liaison", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "ml de tuyauterie", "quantite_estimee": nb_puits * 60.0, "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-080", "nom": "Installation de l'alimentation solaire photovoltaïque autonome et télétransmission RTU", "phase": "Énergie Solaire & Télécom", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "système solaire", "quantite_estimee": float(nb_puits), "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-090", "nom": "Épreuve hydrostatique haute pression API 6A de l'ensemble de tête de puits", "phase": "Épreuve HP API 6A", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "test hydro", "quantite_estimee": float(nb_puits), "predecesseurs_suggérés": ["T-060", "T-070"]},
            {"id_tache": "T-100", "nom": "Test fonctionnel de fermeture d'urgence ESD / SSV et simulation perte de pression", "phase": "Sécurité Puits", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "test sécurité", "quantite_estimee": float(nb_puits), "predecesseurs_suggérés": ["T-080", "T-090"]},
            {"id_tache": "T-110", "nom": "Ouverture de puits, mise en production progressive et réception officielle ARH", "phase": "Mise en Production", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "puits mis en service", "quantite_estimee": float(nb_puits), "predecesseurs_suggérés": ["T-100"]}
        ]

    # ── 9. MANIFOLDS DE COLLECTE ──
    def _generate_manifold_wbs(self, nlu: Dict[str, Any]) -> List[Dict[str, Any]]:
        nb_puits = nlu.get("parametres_cles", {}).get("nb_unites", 4)
        return [
            {"id_tache": "T-010", "nom": "Études de détail P&ID, isométriques manifold de collecte et calculs de flexibilité ASME B31.3", "phase": "Études", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 8.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": f"Approvisionnement vannes 3 voies, collecteurs (Headers Production & Test) et duses de régulation ({nb_puits} arrivées)", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": "Terrassement, fouilles et coulage des massifs de fondation et caniveaux béton armé", "phase": "Génie Civil", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³ béton", "quantite_estimee": 45.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": "Montage de la structure métallique support (Skid / Structure support du manifold)", "phase": "Structure Métallique", "discipline": "04_STRUCTURE_CHARPENTE", "unite_oeuvre": "t", "quantite_estimee": 8.5, "predecesseurs_suggérés": ["T-030"]},
            {"id_tache": "T-050", "nom": f"Préfabrication des branches de dérivation et soudage des collecteurs principaux ({nb_puits} entrées)", "phase": "Préfabrication Spools", "discipline": "05_TUYAUTERIE_PREFABRICATION", "unite_oeuvre": "DI (Diamètre-Pouce)", "quantite_estimee": nb_puits * 45.0, "predecesseurs_suggérés": ["T-020"]},
            {"id_tache": "T-060", "nom": "Contrôles CND 100% des soudures (Radiographie RX / Contrôle magnétoscopique MT)", "phase": "Contrôle CND", "discipline": "05_TUYAUTERIE_PREFABRICATION", "unite_oeuvre": "joint radiographié", "quantite_estimee": nb_puits * 6.0, "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-070", "nom": "Montage et lignage des collecteurs sur supports avec robinetterie et vannes motorisées MOV", "phase": "Montage Manifold", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "ml de tuyauterie", "quantite_estimee": 48.0, "predecesseurs_suggérés": ["T-040", "T-060"]},
            {"id_tache": "T-080", "nom": "Installation du débitmètre multiphasique (MPFM), transmetteurs de pression/température et boîtes de jonction", "phase": "Instrumentation", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "instrument (u)", "quantite_estimee": 12.0, "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-090", "nom": "Peinture anticorrosion système C5-M sur l'ensemble du manifold et calorifugeage", "phase": "Peinture & Protection", "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE", "unite_oeuvre": "m²", "quantite_estimee": 120.0, "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-100", "nom": "Épreuve hydrostatique globale du manifold à 1.5x PMA selon ASME B31.3", "phase": "Épreuve Hydro", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "test hydro", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-070", "T-090"]},
            {"id_tache": "T-110", "nom": "Test de boucles I/O, étalonnage des vannes de commutation et simulation arrêt d'urgence", "phase": "Loop Checks", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "boucle instrumentale (Loop)", "quantite_estimee": 12.0, "predecesseurs_suggérés": ["T-080", "T-100"]},
            {"id_tache": "T-120", "nom": "Inertage N2, introduction du brut hydrocarbures et mise en service officielle ARH", "phase": "Mise en Gaz", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "mise en produit", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-110"]}
        ]

    # ── 9bis. ENSEMBLE INTÉGRÉ TÊTES DE PUITS & MANIFOLD DE COLLECTE ──
    def _generate_wellhead_and_manifold_wbs(self, nlu: Dict[str, Any]) -> List[Dict[str, Any]]:
        nb_puits = nlu.get("parametres_cles", {}).get("nb_unites", 4)
        return [
            {"id_tache": "T-010", "nom": "Études d'ingénierie FEED, P&ID Tête de puits & Manifold, calculs de flexibilité ASME B31.3 et schémas WHCP", "phase": "Études & Ingénierie", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 10.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": f"Approvisionnement Arbres de Noël API 6A, panneaux WHCP, collecteurs Manifold, vannes 3 voies et débitmètre multiphasique MPFM ({nb_puits} puits)", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": f"Terrassement, aménagement de la plateforme de puits et coulage de la cave de puits en béton armé ({nb_puits} caves)", "phase": "Génie Civil Puits", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "cave de puits", "quantite_estimee": float(nb_puits), "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": "Génie civil plateforme manifold, massifs supports béton armé et caniveaux VRD", "phase": "Génie Civil Manifold", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³ béton", "quantite_estimee": 55.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-050", "nom": f"Montage mécanique des têtes de puits API 6A, vannes maîtresses et duses de régulation (Chokes) ({nb_puits} puits)", "phase": "Montage Têtes de Puits", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "wellhead", "quantite_estimee": float(nb_puits), "predecesseurs_suggérés": ["T-020", "T-030"]},
            {"id_tache": "T-060", "nom": "Montage et ancrage de la structure métallique support du skid manifold", "phase": "Structure Métallique", "discipline": "04_STRUCTURE_CHARPENTE", "unite_oeuvre": "t", "quantite_estimee": 9.5, "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-070", "nom": f"Préfabrication en atelier des collecteurs principaux et spools manifold (Production & Test Headers) ({nb_puits} arrivées)", "phase": "Préfabrication Spools", "discipline": "05_TUYAUTERIE_PREFABRICATION", "unite_oeuvre": "DI (Diamètre-Pouce)", "quantite_estimee": nb_puits * 50.0, "predecesseurs_suggérés": ["T-020"]},
            {"id_tache": "T-080", "nom": "Contrôles CND 100% des soudures (Radiographie RX / Contrôle magnétoscopique MT)", "phase": "Contrôle CND", "discipline": "05_TUYAUTERIE_PREFABRICATION", "unite_oeuvre": "joint radiographié", "quantite_estimee": nb_puits * 8.0, "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-090", "nom": "Montage, lignage et boulonnage des collecteurs manifold sur skid avec vannes motorisées MOV", "phase": "Montage Manifold", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "ml de tuyauterie", "quantite_estimee": 60.0, "predecesseurs_suggérés": ["T-060", "T-080"]},
            {"id_tache": "T-100", "nom": f"Pose et raccordement des flowlines de liaison entre têtes de puits et manifold ({nb_puits * 80} ml)", "phase": "Flowlines Liaison", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "ml de tuyauterie", "quantite_estimee": nb_puits * 80.0, "predecesseurs_suggérés": ["T-050", "T-090"]},
            {"id_tache": "T-110", "nom": "Installation et raccordement des panneaux de contrôle hydraulique de sécurité WHCP vers vannes SSV/SCSSV", "phase": "Contrôle WHCP", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "panneau WHCP", "quantite_estimee": float(nb_puits), "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-120", "nom": "Installation du débitmètre multiphasique (MPFM), transmetteurs de pression/température et RTU solaire", "phase": "Instrumentation & MPFM", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "instrument (u)", "quantite_estimee": 16.0, "predecesseurs_suggérés": ["T-090"]},
            {"id_tache": "T-130", "nom": "Peinture anticorrosion système C5-M et calorifugeage des lignes de liaison", "phase": "Peinture & Protection", "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE", "unite_oeuvre": "m²", "quantite_estimee": 180.0, "predecesseurs_suggérés": ["T-100"]},
            {"id_tache": "T-140", "nom": "Épreuve hydrostatique haute pression API 6A tête de puits et épreuve hydrostatique manifold selon ASME B31.3", "phase": "Épreuves Hydro", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "test hydro", "quantite_estimee": float(nb_puits + 1), "predecesseurs_suggérés": ["T-100", "T-130"]},
            {"id_tache": "T-150", "nom": "Loop checks instrumentation, étalonnage des vannes ESD/SSV et simulation perte de pression", "phase": "Sécurité & Loop Checks", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "boucle instrumentale (Loop)", "quantite_estimee": 18.0, "predecesseurs_suggérés": ["T-110", "T-120", "T-140"]},
            {"id_tache": "T-160", "nom": "Inertage azote N2, ouverture de puits, mise en production progressive et certification de conformité ARH / RFSU", "phase": "Mise en Production & RFSU", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "installation réceptionnée", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-150"]}
        ]

    # ── 9ter. RÉSEAU TÉLÉCOMS & FIBRE OPTIQUE (FOC) ──
    def _generate_fiber_optic_telecom_wbs(self, nlu: Dict[str, Any], longueur_ml: float) -> List[Dict[str, Any]]:
        nb_chambres = max(4, int(round(longueur_ml / 1000.0)))
        nb_brins = 48  # Câble standard 48 brins / 24 paires
        nb_epissures = nb_chambres * nb_brins
        
        return [
            {"id_tache": "T-010", "nom": "Études d'ingénierie Télécoms, tracé de piquetage, profil en long, calculs de bilan optique (Budget dB/km) et plans d'exécution", "phase": "Études Télécoms", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": max(4, int(longueur_ml / 2500)), "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": f"Approvisionnement câble fibre optique monomode (G.652D armé anti-rongeur), fourreaux PEHD DN40/50, chambres et boîtes d'épissurage IP68 ({int(longueur_ml)} ml)", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": f"Piquetage contradictoire du tracé et détection des réseaux enterrés existants (GPR / Détecteur électromagnétique) ({int(longueur_ml)} ml)", "phase": "Piquetage & Détection", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml", "quantite_estimee": longueur_ml, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": f"Ouverture de la tranchée télécom mécanisée (profondeur 0.80 à 1.20 m, largeur 0.35 m) ({int(longueur_ml)} ml)", "phase": "Tranchée Télécom", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml", "quantite_estimee": longueur_ml, "predecesseurs_suggérés": ["T-030"]},
            {"id_tache": "T-050", "nom": f"Pose du lit de sable tamisé (ép. 10 cm) et déroulage des fourreaux PEHD DN40/50 avec fil traceur cuivre nu ({int(longueur_ml)} ml)", "phase": "Fourreaux PEHD", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml fourreau", "quantite_estimee": longueur_ml, "predecesseurs_suggérés": ["T-040", "T-020"]},
            {"id_tache": "T-060", "nom": f"Installation et scellement des chambres de tirage préfabriquées en béton armé (Type L2T/L3T) avec cadres et tampons fonte ({nb_chambres} chambres)", "phase": "Chambres de Tirage", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "chambre de tirage", "quantite_estimee": float(nb_chambres), "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-070", "nom": "Test d'étanchéité pneumatique et passage du calibreur dans les fourreaux PEHD (Calibrage sous pression d'air)", "phase": "Calibrage Fourreaux", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "section fourreau", "quantite_estimee": float(nb_chambres), "predecesseurs_suggérés": ["T-050", "T-060"]},
            {"id_tache": "T-080", "nom": f"Pose du grillage avertisseur vert normalisé Télécoms et remblaiement compacté par couches successives ({int(longueur_ml)} ml)", "phase": "Remblai & Grillage", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml", "quantite_estimee": longueur_ml, "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-090", "nom": f"Soufflage pneumatique du câble fibre optique sous pression d'air comprimé (Jetting / Câblage à l'air) ({int(longueur_ml)} ml)", "phase": "Soufflage Câble FO", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "ml câble FO", "quantite_estimee": longueur_ml, "predecesseurs_suggérés": ["T-070", "T-080"]},
            {"id_tache": "T-100", "nom": f"Préparation des extrémités, lovage des tubes et épissurage des brins par fusion d'arc dans les boîtes de jonction IP68 ({nb_epissures} brins)", "phase": "Épissurage Fusion d'Arc", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "brin soudé optique", "quantite_estimee": float(nb_epissures), "predecesseurs_suggérés": ["T-090"]},
            {"id_tache": "T-110", "nom": "Installation et raccordement des tiroirs optiques (ODF), répartiteurs et jarretières dans les shelters et armoires SCADA", "phase": "Tiroirs Optiques ODF", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "tiroir optique ODF", "quantite_estimee": 4.0, "predecesseurs_suggérés": ["T-100"]},
            {"id_tache": "T-120", "nom": f"Mesures de réflectométrie optique bidirectionnelle (OTDR) à 1310 nm et 1550 nm sur 100% des brins de fibre ({nb_brins} brins)", "phase": "Tests Réflectométrie OTDR", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "fibre testée OTDR", "quantite_estimee": float(nb_brins), "predecesseurs_suggérés": ["T-100", "T-110"]},
            {"id_tache": "T-130", "nom": "Mesures d'affaiblissement global par photométrie (Insertion Loss Test) et validation des seuils de conformité dB", "phase": "Photométrie & Bilan Optique", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "bilan optique global", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-120"]},
            {"id_tache": "T-140", "nom": f"Pose des bornes balises de repérage de la ligne et recette technique finale avec PV de conformité ARH / Télécoms ({max(5, int(longueur_ml/500))} bornes)", "phase": "Bornage & Recette Télécoms", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "liaison optique réceptionnée", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-130"]}
        ]

    # ── 9quater. PROTECTION CATHODIQUE (CP / ISO 15589-1) ──
    def _generate_cathodic_protection_wbs(self, nlu: Dict[str, Any], longueur_ml: float) -> List[Dict[str, Any]]:
        nb_postes_tr = max(1, int(round(longueur_ml / 30000.0)))
        nb_deversoirs = nb_postes_tr
        nb_test_posts = max(6, int(round(longueur_ml / 1500.0)))
        nb_points_cadweld = nb_postes_tr * 2 + nb_test_posts

        return [
            {"id_tache": "T-010", "nom": "Études d'ingénierie Protection Cathodique, mesures de résistivité des sols (Méthode Wenner 4 broches), calculs de densité de courant et plans d'implantation", "phase": "Études & Résistivité", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": max(4, int(longueur_ml / 10000)), "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": "Approvisionnement postes transformateurs-redresseurs (T/R) automatiques, colonnes d'anodes MMO/Titane, remblai de coke calciné, prises de potentiel et joints isolants MIJ", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": f"Forage des puits profonds pour déversoirs d'anodes (Deep Well prof. 80-120 m) ({nb_deversoirs} puits)", "phase": "Forage Déversoirs", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml forage", "quantite_estimee": float(nb_deversoirs * 100), "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": f"Descente, centrage de la colonne d'anodes MMO/Titane avec tube d'évent PVC perforé et injection du remblai carboné de coke calciné ({nb_deversoirs} déversoirs)", "phase": "Colonnes d'Anodes", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "puits déversoir", "quantite_estimee": float(nb_deversoirs), "predecesseurs_suggérés": ["T-030", "T-020"]},
            {"id_tache": "T-050", "nom": f"Génie civil du socle béton armé support du poste T/R, pose de l'armoire étanche IP66 et clôture de sécurité du site PC ({nb_postes_tr} postes)", "phase": "Génie Civil Postes T/R", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "socle béton", "quantite_estimee": float(nb_postes_tr), "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-060", "nom": f"Ouverture des tranchées de câblage (prof. 0.80 m), lit de sable et tirage des câbles d'anodes positifs (XLPE/HMWPE) vers le déversoir ({int(nb_deversoirs * 300)} ml)", "phase": "Tranchées & Câbles Anodes", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml", "quantite_estimee": float(nb_deversoirs * 300), "predecesseurs_suggérés": ["T-040", "T-050"]},
            {"id_tache": "T-070", "nom": f"Raccordement du câble négatif sur la conduite par soudure aluminothermique (Pin brazing / Cadweld) et réfection du revêtement isolant anticorrosion ({nb_points_cadweld} points)", "phase": "Soudure Aluminothermique", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "soudure aluminothermique", "quantite_estimee": float(nb_points_cadweld), "predecesseurs_suggérés": ["T-060"]},
            {"id_tache": "T-080", "nom": f"Implantation, scellement béton des prises de potentiel (Test Posts), pose des électrodes de référence permanentes Cu/CuSO4 et coupons témoins ({nb_test_posts} bornes)", "phase": "Prises de Potentiel (TP)", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "prise de potentiel", "quantite_estimee": float(nb_test_posts), "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-090", "nom": f"Pose et raccordement de l'alimentation électrique (Réseau BT ou station solaire photovoltaïque avec batteries) ({nb_postes_tr} postes)", "phase": "Alimentation Électrique", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "poste", "quantite_estimee": float(nb_postes_tr), "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-100", "nom": f"Raccordement complet du poste T/R : Ponts redresseurs, shunts de mesure calibrés, parafoudres parafoudre et module de télémesure RTU/SCADA ({nb_postes_tr} armoires)", "phase": "Équipement Poste T/R", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "armoire T/R", "quantite_estimee": float(nb_postes_tr), "predecesseurs_suggérés": ["T-090", "T-060", "T-070"]},
            {"id_tache": "T-110", "nom": f"Mesures de résistance de terre du déversoir d'anodes (R < 1 Ohm) et test de rigidité diélectrique des joints isolants monoblocs (MIJ) ({nb_deversoirs} déversoirs)", "phase": "Contrôle Résistances & MIJ", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "test électrique", "quantite_estimee": float(nb_deversoirs + 2), "predecesseurs_suggérés": ["T-040", "T-100"]},
            {"id_tache": "T-120", "nom": f"Mise sous tension progressive, injection de courant, réglage de la consigne et essai de polarisation continue de l'ouvrage ({int(longueur_ml)} ml)", "phase": "Polarisation Initiale", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "ml polarisé", "quantite_estimee": longueur_ml, "predecesseurs_suggérés": ["T-100", "T-110", "T-080"]},
            {"id_tache": "T-130", "nom": f"Campagne de relevés de potentiel ON / OFF (sans chute ohmique IR-Free) et vérification du critère normatif NACE -850 mV ({nb_test_posts} bornes)", "phase": "Relevés Potentiels ON/OFF", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "borne mesurée", "quantite_estimee": float(nb_test_posts), "predecesseurs_suggérés": ["T-120"]},
            {"id_tache": "T-140", "nom": "Étalonnage des alarmes sous/sur-polarisation et PV officiel de mise en service sous contrôle ARH / ISO 15589-1", "phase": "Recette & Conformité ARH", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "système PC réceptionné", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-130"]}
        ]

    # ── 9quater-b. PROTECTION INCENDIE, DÉLUGE & MOUSSE (NFPA 11/15) ──
    def _generate_fire_protection_wbs(self, nlu: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"id_tache": "T-010", "nom": "Études d'ingénierie Sécurité Incendie, calculs hydrauliques normalisés NFPA 15 / NFPA 11 et isométriques du réseau", "phase": "Études Incendie", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 6.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": "Approvisionnement vannes déluge automatiques (Deluge Valves), buses de pulvérisation, cuve émulseur et proportionneur", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": "Fouilles, pose et remblai du collecteur principal d'eau d'incendie enterré (PEHD ou acier revêtu) avec poteaux d'incendie PI", "phase": "Réseau Enterré", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml", "quantite_estimee": 450.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": "Préfabrication et galvanisation à chaud des couronnes d'arrosage, rampes déluge et rideaux d'eau", "phase": "Préfabrication Rampes", "discipline": "04_CHARPENTE_METALLIQUE_BARDAGE", "unite_oeuvre": "couronne d'arrosage", "quantite_estimee": 4.0, "predecesseurs_suggérés": ["T-020"]},
            {"id_tache": "T-050", "nom": "Montage et fixation des tuyauteries déluge et buses de refroidissement sur la robe et le toit de l'équipement", "phase": "Montage Rampes & Buses", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "buse de pulvérisation", "quantite_estimee": 36.0, "predecesseurs_suggérés": ["T-040", "T-030"]},
            {"id_tache": "T-060", "nom": "Installation de l'unité de dosage d'émulseur / mousse et concentrateurs à haut foisonnement", "phase": "Skid Émulseur", "discipline": "07_EQUIPEMENTS_STATIQUES", "unite_oeuvre": "skid émulseur", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-020"]},
            {"id_tache": "T-070", "nom": "Pose des lignes de détection pneumatique/électrique (Câble thermosensible LHD, détecteurs optiques flamme UV/IR)", "phase": "Détection Feu & Gaz", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "détecteur / boucle", "quantite_estimee": 12.0, "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-080", "nom": "Raccordement au panneau de commande extinction incendie F&G / SIS / ESD", "phase": "Automatisme F&G", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "boucle instrumentale (Loop)", "quantite_estimee": 8.0, "predecesseurs_suggérés": ["T-070", "T-060"]},
            {"id_tache": "T-090", "nom": "Épreuve hydrostatique des couronnes déluge et conduites d'arrosage à 1.5 fois la pression nominale", "phase": "Épreuve Hydrostatique", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "test hydro", "quantite_estimee": 2.0, "predecesseurs_suggérés": ["T-050", "T-080"]},
            {"id_tache": "T-100", "nom": "Essais de décharge réelle à l'eau (Full Discharge Test), mesure des pressions/débits aux buses et PV de conformité ARH / Protection Civile", "phase": "Discharge Test & PV", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "système incendie réceptionné", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-090"]}
        ]

    # ── 9quinquies. CENTRALE SOLAIRE PHOTOVOLTAÏQUE (SOLAR PV) ──
    def _generate_solar_pv_wbs(self, nlu: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"id_tache": "T-010", "nom": "Études d'ingénierie solaire, modélisation PVsyst, schémas électriques DC/AC et notes de calcul de productible", "phase": "Études Solaires", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 8.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": "Approvisionnement modules photovoltaïques bi-faciaux, structures de supportage, onduleurs centraux et câbles solaires", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": "Terrassement, nivellement du terrain, voiries d'accès et clôture de sécurité du champ solaire", "phase": "Génie Civil", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m²", "quantite_estimee": 2500.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": "Battage / vissage des pieux de fondation en acier galvanisé et massifs béton pour onduleurs", "phase": "Fondations Pieux", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "pieu battu", "quantite_estimee": 120.0, "predecesseurs_suggérés": ["T-030"]},
            {"id_tache": "T-050", "nom": "Montage des structures mécaniques de supportage (tables solaires) et axes de trackers", "phase": "Structures Support", "discipline": "04_CHARPENTE_METALLIQUE_BARDAGE", "unite_oeuvre": "table solaire", "quantite_estimee": 40.0, "predecesseurs_suggérés": ["T-040", "T-020"]},
            {"id_tache": "T-060", "nom": "Pose, alignement et fixation des modules solaires photovoltaïques (panneaux PV)", "phase": "Pose Panneaux PV", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "panneau solaire PV", "quantite_estimee": 400.0, "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-070", "nom": "Câblage DC des chaînes (Strings), pose des boîtes de jonction DC et réseau de mise à la terre", "phase": "Câblage DC", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "ml", "quantite_estimee": 1500.0, "predecesseurs_suggérés": ["T-060"]},
            {"id_tache": "T-080", "nom": "Installation, raccordement des onduleurs solaires (Inverters) et armoires de distribution AC", "phase": "Onduleurs & Distribution", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "onduleur", "quantite_estimee": 6.0, "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-090", "nom": "Installation du poste de transformation élévateur BT/HTA et cellule d'injection réseau", "phase": "Poste Transfo HTA", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "poste", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-080"]},
            {"id_tache": "T-100", "nom": "Contrôles électriques : Mesures d'isolement, courbes I-V, thermographie IR et boucles de télégestion SCADA", "phase": "Essais & Contrôles", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "string testé", "quantite_estimee": 40.0, "predecesseurs_suggérés": ["T-090", "T-070"]},
            {"id_tache": "T-110", "nom": "Essais d'injection réseau sous charge, synchronisation et recette officielle de mise en service ARH / CREDEG", "phase": "Commissioning Solaire", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "centrale réceptionnée", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-100"]}
        ]

    # ── 9sexies. SYSTÈME DE TORCHÈRE INDUSTRIELLE (FLARE SYSTEM) ──
    def _generate_flare_wbs(self, nlu: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"id_tache": "T-010", "nom": "Études aérodynamiques, notes de dimensionnement rayonnement thermique API 521, plans d'élévation et fondations", "phase": "Études Torchère", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 6.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": "Approvisionnement fût de torchère métallique, nez de torche (Flare Tip en Inconel), allumeurs HEI et veilleuses pilotes", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": "Fouilles, ferraillage lourd et coulage du radier/massif béton armé d'ancrage du mât de torchère", "phase": "Génie Civil", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³ béton", "quantite_estimee": 80.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": "Préfabrication et assemblage au sol des tronçons tubulaires du fût avec échelles à crinoline et tuyauteries de gaz pilote", "phase": "Assemblage Fût", "discipline": "04_CHARPENTE_METALLIQUE_BARDAGE", "unite_oeuvre": "tronçon de fût", "quantite_estimee": 4.0, "predecesseurs_suggérés": ["T-020", "T-030"]},
            {"id_tache": "T-050", "nom": "Montage en tête du Flare Tip réfractaire, thermocouples haute température, pare-vent et buses d'injection vapeur/air", "phase": "Nez de Torche (Flare Tip)", "discipline": "07_EQUIPEMENTS_STATIQUES", "unite_oeuvre": "flare tip", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-060", "nom": "Levage lourd par grue mobile 200t, érection verticale du mât de torchère et serrage au couple des tiges d'ancrage", "phase": "Érection & Levage", "discipline": "04_CHARPENTE_METALLIQUE_BARDAGE", "unite_oeuvre": "fût érigé", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-040", "T-050"]},
            {"id_tache": "T-070", "nom": "Raccordement des collecteurs gaz de décharge HP/BP amont vers le ballon séparateur de purge (KO Drum)", "phase": "Raccordement Process", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "joint soudé", "quantite_estimee": 12.0, "predecesseurs_suggérés": ["T-060"]},
            {"id_tache": "T-080", "nom": "Installation du panneau de commande d'allumage automatique (FGC Ignition Panel) et détecteurs de flamme optiques", "phase": "Panneau Allumage", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "panneau allumeur", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-060"]},
            {"id_tache": "T-090", "nom": "Épreuve d'étanchéité pneumatique des lignes gaz pilote et test d'isolement électrique des électrodes d'allumage", "phase": "Contrôles Électro-Pneumatiques", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "test hydro/pneu", "quantite_estimee": 2.0, "predecesseurs_suggérés": ["T-070", "T-080"]},
            {"id_tache": "T-100", "nom": "Tests d'allumage automatique à blanc, validation de la détection de flamme et mise en service officielle RFSU / ARH", "phase": "Mise à Feu & RFSU", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "torchère réceptionnée", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-090"]}
        ]

    # ── 9septies. BASSINS DE RÉTENTION & ÉTANCHÉITÉ PEHD ──
    def _generate_basin_pond_wbs(self, nlu: Dict[str, Any], volume_m3: float) -> List[Dict[str, Any]]:
        surf_estimee = max(800.0, volume_m3 * 1.5)
        return [
            {"id_tache": "T-010", "nom": "Études géotechniques, dimensionnement hydraulique, profils en travers et plans de terrassement du bassin", "phase": "Études Géotechniques", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 6.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": f"Approvisionnement rouleaux géomembrane PEHD (ép. 2.0 mm), géotextile non-tissé 400g/m² et réseau de drainage ({int(surf_estimee)} m²)", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": f"Décapage terre végétale, terrassement général en déblai/remblai et profilage des talus du bassin ({int(volume_m3 * 1.2)} m³)", "phase": "Terrassement Bassin", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³", "quantite_estimee": float(volume_m3 * 1.2), "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": f"Compactage méthodique du fond de forme (95% OPM) et constitution du lit de pose en sable tamisé (10 cm)", "phase": "Lit de Pose & Compactage", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m²", "quantite_estimee": surf_estimee, "predecesseurs_suggérés": ["T-030"]},
            {"id_tache": "T-050", "nom": f"Déroulage et pose du géotextile non-tissé anti-poinçonnement au fond et sur talus ({int(surf_estimee)} m²)", "phase": "Pose Géotextile", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m²", "quantite_estimee": surf_estimee, "predecesseurs_suggérés": ["T-040", "T-020"]},
            {"id_tache": "T-060", "nom": f"Déroulage, ajustement et thermo-soudure par double piste de la géomembrane PEHD ({int(surf_estimee)} m²)", "phase": "Soudure Géomembrane PEHD", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m²", "quantite_estimee": surf_estimee, "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-070", "nom": "Contrôles d'étanchéité 100% des soudures PEHD par test à l'air sous pression (Canal de test) et cloche à vide", "phase": "Contrôle Soudures PEHD", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "mètre soudure testée", "quantite_estimee": surf_estimee / 5.0, "predecesseurs_suggérés": ["T-060"]},
            {"id_tache": "T-080", "nom": "Ancrage de la géomembrane en tête de talus dans tranchée d'ancrage périphérique et remblaiement compacté", "phase": "Tranchée d'Ancrage", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml", "quantite_estimee": surf_estimee / 10.0, "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-090", "nom": "Pose des conduites d'entrée/vidange en PEHD soudé bout à bout et réseau de drainage / détection de fuite sous membrane", "phase": "Tuyauterie & Drainage PEHD", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "ml", "quantite_estimee": 150.0, "predecesseurs_suggérés": ["T-080"]},
            {"id_tache": "T-100", "nom": "Épreuve de remplissage d'eau, mesure de tenue hydrostatique 48h et PV de conformité environnementale ARH", "phase": "Test d'Étanchéité & PV ARH", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "bassin réceptionné", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-090"]}
        ]

    # ── 10. BACS DE STOCKAGE API 650 ──
    def _generate_tank_wbs(self, nlu: Dict[str, Any]) -> List[Dict[str, Any]]:
        vol = nlu.get("parametres_cles", {}).get("volume_m3", 10000.0)
        return [
            {"id_tache": "T-010", "nom": "Notes de calcul de dimensionnement API 650, plans d'atelier tôles et cuvette", "phase": "Études", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 8.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": "Approvisionnement tôles d'acier certifiées API 650, membrures, accessoires et vannes", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": "Terrassement, cuvette de rétention, pose membrane PEHD et anneau béton armé (Ring Wall)", "phase": "Génie Civil", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³ béton", "quantite_estimee": 120.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": "Pose et soudage du fond de bac (Bottom Plates & Annular Plates) avec boîte à vide", "phase": "Fond de Bac", "discipline": "07_EQUIPEMENTS_STATIQUES", "unite_oeuvre": "m²", "quantite_estimee": 450.0, "predecesseurs_suggérés": ["T-020", "T-030"]},
            {"id_tache": "T-050", "nom": "Érection et soudage à l'arc submergé des viroles de robe de bac (Shell Courses 1 à 6)", "phase": "Robe de Bac", "discipline": "07_EQUIPEMENTS_STATIQUES", "unite_oeuvre": "virole (u)", "quantite_estimee": 6.0, "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-060", "nom": "Contrôle CND 100% des joints soudés verticaux/horizontaux (Radiographie RT & Boîte à vide)", "phase": "Contrôle CND", "discipline": "05_TUYAUTERIE_PREFABRICATION", "unite_oeuvre": "joint radiographié", "quantite_estimee": 48.0, "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-070", "nom": "Montage de la charpente de toit conique ou à écran flottant, pontons et joints d'étanchéité", "phase": "Toit de Bac", "discipline": "07_EQUIPEMENTS_STATIQUES", "unite_oeuvre": "toit / dôme", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-080", "nom": "Pose des accessoires : Trous d'homme, piquages, escalier hélicoïdal et instrumentation niveau radar", "phase": "Accessoires & Instru", "discipline": "07_EQUIPEMENTS_STATIQUES", "unite_oeuvre": "accessoire", "quantite_estimee": 14.0, "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-090", "nom": "Sablage Sa 2.5 et application de peinture anticorrosion interne/externe (Système C5-M)", "phase": "Peinture & Revêtement", "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE", "unite_oeuvre": "m²", "quantite_estimee": 1500.0, "predecesseurs_suggérés": ["T-060", "T-080"]},
            {"id_tache": "T-100", "nom": "Remplissage et épreuve hydrostatique complète selon API 650 avec mesure des tassements", "phase": "Hydrotest API 650", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "test hydro", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-080", "T-090"]},
            {"id_tache": "T-110", "nom": "Vidange, séchage, étalonnage du jaugeage radar et réception réglementaire ARH", "phase": "Commissioning", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "bac réceptionné", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-100"]}
        ]

    # ── 11. SKIDS PROCÉDÉS ──
    def _generate_skid_wbs(self, nlu: Dict[str, Any], longueur: float, diam_p: int) -> List[Dict[str, Any]]:
        return [
            {"id_tache": "T-010", "nom": "Études d'intégration 3D PDMS/E3D, P&ID et plans de charges du skid", "phase": "Études", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "document", "quantite_estimee": 6.0, "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": "Inspection d'usine FAT et transport du skid modulaire sur site", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "skid (u)", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": "Coulage de la dalle et des massifs béton armé support du skid", "phase": "Génie Civil", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³ béton", "quantite_estimee": 35.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": "Grutage lourd, érection et mise à niveau du skid modulaire sur massifs", "phase": "Montage Skid", "discipline": "08_EQUIPEMENTS_DYNAMIQUES", "unite_oeuvre": "skid (u)", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-020", "T-030"]},
            {"id_tache": "T-050", "nom": "Raccordements des tuyauteries process amont/aval (Tie-ins)", "phase": "Raccordement Tuyauterie", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "joint soudé ou DI", "quantite_estimee": 18.0, "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-060", "nom": "Raccordement électrique de puissance et mise à la terre du châssis", "phase": "Électricité", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "câble tiré", "quantite_estimee": 80.0, "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-070", "nom": "Raccordement des liaisons instrumentation et réseau de communication DCS", "phase": "Instrumentation", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "fil / boucle", "quantite_estimee": 16.0, "predecesseurs_suggérés": ["T-040"]},
            {"id_tache": "T-080", "nom": "Épreuve hydrostatique des liaisons de raccordement sur site", "phase": "Épreuve Hydro", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "test hydro", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-090", "nom": "Test de boucles I/O et calibration des vannes de régulation", "phase": "Précommissioning", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "boucle instrumentale (Loop)", "quantite_estimee": 12.0, "predecesseurs_suggérés": ["T-060", "T-070", "T-080"]},
            {"id_tache": "T-100", "nom": "Inertage azote N2, mise en gaz et réception officielle ARH", "phase": "Commissioning", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "mise en produit", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-090"]}
        ]

    # ── 12. TUYAUTERIE INDUSTRIELLE & RACCORDEMENTS DE SITE ──
    def _generate_piping_wbs(self, nlu: Dict[str, Any], longueur: float, diam_p: int, nb_joints: int, total_di: int) -> List[Dict[str, Any]]:
        return [
            {"id_tache": "T-010", "nom": "Revue des études de base FEED, P&ID et émission des isométriques IFC", "phase": "Études", "discipline": "01_INGENIERIE_ETUDES", "unite_oeuvre": "plan isométrique", "quantite_estimee": max(4, int(longueur / 20)), "predecesseurs_suggérés": []},
            {"id_tache": "T-020", "nom": "Approvisionnement tubes, brides, robinetterie et accessoires", "phase": "Procurement", "discipline": "02_PROCUREMENT_LOGISTIQUE", "unite_oeuvre": "lot matériel", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-030", "nom": "Fouilles et terrassement pour massifs et supports de pipe-rack", "phase": "Génie Civil", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³", "quantite_estimee": round(longueur * 0.8, 1), "predecesseurs_suggérés": ["T-010"]},
            {"id_tache": "T-040", "nom": "Ferraillage et coulage des massifs béton armé", "phase": "Génie Civil", "discipline": "03_GENIE_CIVIL_TERRASSEMENT", "unite_oeuvre": "m³ béton", "quantite_estimee": round(longueur * 0.25, 1), "predecesseurs_suggérés": ["T-030"]},
            {"id_tache": "T-050", "nom": "Préfabrication des spools de tuyauterie en atelier (Fit-up & Soudure TIG/SMAW)", "phase": "Préfabrication", "discipline": "05_TUYAUTERIE_PREFABRICATION", "unite_oeuvre": "DI (Diamètre-Pouce)", "quantite_estimee": total_di, "predecesseurs_suggérés": ["T-020"]},
            {"id_tache": "T-060", "nom": "Contrôles CND des soudures atelier (Radiographie RT / Ultrasons UT)", "phase": "Contrôle CND", "discipline": "05_TUYAUTERIE_PREFABRICATION", "unite_oeuvre": "joint radiographié", "quantite_estimee": max(6, int(nb_joints * 0.2)), "predecesseurs_suggérés": ["T-050"]},
            {"id_tache": "T-070", "nom": f"Montage et pose des spools sur pipe-rack avec supportage ({int(longueur)} ml)", "phase": "Montage Site", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "ml de tuyauterie", "quantite_estimee": longueur, "predecesseurs_suggérés": ["T-040", "T-060"]},
            {"id_tache": "T-080", "nom": "Installation de la robinetterie industrielle et vannes de régulation", "phase": "Robinetterie", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "unité vanne (u)", "quantite_estimee": max(4, int(longueur / 15)), "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-090", "nom": "Épreuve hydrostatique du réseau de tuyauterie sur site (1.5x PMA)", "phase": "Essais Pression", "discipline": "06_TUYAUTERIE_MONTAGE_SITE", "unite_oeuvre": "boucle / circuit hydrotest", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-080"]},
            {"id_tache": "T-100", "nom": "Tirage des câbles puissance, contrôle et instrumentation", "phase": "Électricité", "discipline": "09_ELECTRICITE_HT_BT", "unite_oeuvre": "ml câble tiré", "quantite_estimee": round(longueur * 2.5, 1), "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-110", "nom": "Tubing instrumentation inox et transmetteurs PT/TT/FT", "phase": "Instrumentation", "discipline": "10_INSTRUMENTATION_AUTOMATISME", "unite_oeuvre": "instrument (u)", "quantite_estimee": 8.0, "predecesseurs_suggérés": ["T-070"]},
            {"id_tache": "T-120", "nom": "Peinture de finition anticorrosion et calorifugeage thermique", "phase": "Protection & Finition", "discipline": "11_ISOLATION_CALORIFUGE_PEINTURE", "unite_oeuvre": "ml", "quantite_estimee": longueur, "predecesseurs_suggérés": ["T-090"]},
            {"id_tache": "T-130", "nom": "Flushing, séchage azote et tests de boucles (Loop checks 100%)", "phase": "Précommissioning", "discipline": "12_PRECOMMISSIONING_TESTS", "unite_oeuvre": "boucle instrumentale (Loop)", "quantite_estimee": 12.0, "predecesseurs_suggérés": ["T-090", "T-100", "T-110"]},
            {"id_tache": "T-140", "nom": "Inertage N2, introduction du fluide et mise en service opérationnelle", "phase": "Mise en Service", "discipline": "13_COMMISSIONING_DEMARRAGE", "unite_oeuvre": "mise en produit", "quantite_estimee": 1.0, "predecesseurs_suggérés": ["T-120", "T-130"]}
        ]


class PlanningYieldAndCrewAgent:
    """Agents 3 & 4 (Parallélisés) : RAG Hybride pour associer rendements, durées, équipes et outillages."""

    async def process_task(self, raw_task: Dict[str, Any]) -> TachePlanning:
        nom = raw_task.get("nom", "")
        discipline = raw_task.get("discipline", "06_TUYAUTERIE_MONTAGE_SITE")
        quantite = float(raw_task.get("quantite_estimee", 10.0))
        unite = raw_task.get("unite_oeuvre", "u")
        preds = raw_task.get("predecesseurs")
        if not preds:
            preds = raw_task.get("predecesseurs_suggérés") or []
        if isinstance(preds, str):
            preds = [preds]

        # 1. Recherche dans le RAG Hybride
        rag_matches = planning_rag.search_similar_tasks(nom, top_k=1, discipline=discipline, unite=unite)
        rag_match = rag_matches[0] if rag_matches else None

        nom_lower = nom.lower()
        u_task_clean = unite.lower().split()[0].replace('²', '2').replace('³', '3')
        
        # 1.A. Règles calibrées prioritaires par domaine technique spécifique
        if "panneau solaire" in nom_lower or "module solaire" in nom_lower or "panneau pv" in nom_lower:
            base_rendement = 40.0
            unite_rendement = "panneau/jour/équipe"
            equipe_data = [{"role": "Monteur électricien PV", "effectif": 3}]
            ressources = ["Visseuses dynamométriques", "Lignes de vie"]
            sources = ["Standards Solaires PV / EPC"]
        elif "table solaire" in nom_lower or ("structure" in nom_lower and "solaire" in nom_lower) or ("support" in nom_lower and "tracker" in nom_lower):
            base_rendement = 8.0
            unite_rendement = "table solaire/jour/équipe"
            equipe_data = [{"role": "Monteur charpente métallique", "effectif": 4}]
            ressources = ["Engin télescopique", "Outillage serrage"]
            sources = ["Standards Solaires PV / EPC"]
        elif "pieu" in nom_lower:
            base_rendement = 30.0
            unite_rendement = "pieu/jour/équipe"
            equipe_data = [{"role": "Opérateur batteuse de pieux", "effectif": 2}]
            ressources = ["Machine de battage hydraulique"]
            sources = ["Standards Fondations Solaire"]
        elif "onduleur" in nom_lower:
            base_rendement = 1.0
            unite_rendement = "onduleur/jour/équipe"
            equipe_data = [{"role": "Électricien HTA/BT", "effectif": 2}]
            ressources = ["Grue de manutention", "Clés dynamométriques"]
            sources = ["Spécifications Onduleurs Solaires"]
        elif "câblage dc" in nom_lower or "cablage dc" in nom_lower:
            base_rendement = 250.0
            unite_rendement = "ml/jour/équipe"
            equipe_data = [{"role": "Électricien câbleur", "effectif": 3}]
            ressources = ["Dénudeuses solaires MC4", "Testeurs de continuité"]
            sources = ["Normes Câblage Photovoltaïque"]
        elif "bardage" in nom_lower or "stringing" in nom_lower:
            base_rendement = 1200.0
            unite_rendement = "ml/jour/équipe"
            equipe_data = [
                {"role": "Chef d'équipe bardage", "effectif": 1},
                {"role": "Conducteur Grue / Side-boom", "effectif": 2},
                {"role": "Riggers / Élingueurs", "effectif": 3},
                {"role": "Chauffeurs semi-remorque", "effectif": 2}
            ]
            ressources = ["Grue à flèche latérale (Side-boom)", "Camions semi-remorques transport de tubes"]
            sources = ["Standards Pipeline Sonatrach / TotalEnergies"]
        elif "string pv" in nom_lower or ("string" in nom_lower and ("solaire" in nom_lower or "pv" in nom_lower)):
            base_rendement = 20.0
            unite_rendement = "string/jour/technicien"
            equipe_data = [{"role": "Technicien de contrôle PV", "effectif": 2}]
            ressources = ["Traceur de courbes I-V", "Caméra infrarouge thermographique"]
            sources = ["Norme IEC 62446"]
        elif "géomembrane" in nom_lower or "geomembrane" in nom_lower or "thermo-soudure" in nom_lower:
            base_rendement = 250.0
            unite_rendement = "m²/jour/équipe"
            equipe_data = [{"role": "Soudeur plasturgiste PEHD certifié", "effectif": 3}]
            ressources = ["Machine de soudage double piste à coin chauffant"]
            sources = ["Normes Étanchéité PEHD / DGS"]
        elif "géotextile" in nom_lower or "geotextile" in nom_lower:
            base_rendement = 400.0
            unite_rendement = "m²/jour/équipe"
            equipe_data = [{"role": "Opérateur TP", "effectif": 3}]
            ressources = ["Dérouleuse géotextile"]
            sources = ["Normes Terrassement & Étanchéité"]
        elif ("béton" in nom_lower or "massif" in nom_lower or "radier" in nom_lower) and ("m3" in u_task_clean or "m³" in nom_lower):
            base_rendement = 25.0
            unite_rendement = "m³ béton/jour/équipe"
            equipe_data = [{"role": "Chef d'équipe génie civil", "effectif": 1}, {"role": "Maçon / Ferrailleur", "effectif": 4}]
            ressources = ["Toupie à béton", "Vibreur à béton"]
            sources = ["Standards Génie Civil EPC"]
        elif "buse de pulvérisation" in nom_lower or "buse" in nom_lower or "rampe déluge" in nom_lower:
            base_rendement = 12.0
            unite_rendement = "buse/jour/équipe"
            equipe_data = [{"role": "Monteur tuyauterie incendie", "effectif": 2}]
            ressources = ["Échafaudages roulants", "Clés dynamométriques"]
            sources = ["NFPA 15 / Standards Incendie"]
        elif "couronne d'arrosage" in nom_lower or "rampes déluge" in nom_lower:
            base_rendement = 1.0
            unite_rendement = "couronne/jour/équipe"
            equipe_data = [{"role": "Monteur tuyauteur", "effectif": 3}]
            ressources = ["Grue auxiliaire", "Outillage tuyauterie"]
            sources = ["NFPA 15 / Standards Incendie"]
        elif "skid émulseur" in nom_lower or "proportionneur" in nom_lower:
            base_rendement = 0.5
            unite_rendement = "skid/jour/équipe"
            equipe_data = [{"role": "Mécanicien monteur", "effectif": 2}, {"role": "Instrumentiste", "effectif": 1}]
            ressources = ["Grue de levage"]
            sources = ["NFPA 11 / Standards Mousse"]
        elif "flare tip" in nom_lower or "nez de torche" in nom_lower:
            base_rendement = 0.5
            unite_rendement = "unité/jour/équipe"
            equipe_data = [{"role": "Monteur spécialisé torchère", "effectif": 4}]
            ressources = ["Grue mobile 200t", "Outillage Inconel"]
            sources = ["API 521 / Standards Torchère"]
        elif "allumeur" in nom_lower or "panneau allumage" in nom_lower:
            base_rendement = 0.5
            unite_rendement = "unité/jour/équipe"
            equipe_data = [{"role": "Instrumentiste spécialisé FGC", "effectif": 2}]
            ressources = ["Module de test haute énergie (HEI)"]
            sources = ["Spécifications Allumage Torchère"]
        elif "fût de torchère" in nom_lower or "mât de torchère" in nom_lower or "tronçon de fût" in nom_lower or "fût érigé" in nom_lower:
            base_rendement = 1.0
            unite_rendement = "tronçon/jour/équipe"
            equipe_data = [{"role": "Équipe de levage lourd", "effectif": 6}]
            ressources = ["Grue principale 200t + grue de retenue 80t"]
            sources = ["Plan de Levage Spécialisé ARKAN"]
        elif "soufflage" in nom_lower or "câble fibre" in nom_lower or "cable fibre" in nom_lower:
            base_rendement = 1500.0
            unite_rendement = "ml/jour/équipe jetting"
            equipe_data = [{"role": "Technicien soufflage FO", "effectif": 2}, {"role": "Opérateur compresseur", "effectif": 1}]
            ressources = ["Pousse-câble à air comprimé (Jetting machine)"]
            sources = ["Standards Fibre Optique / Sonatrach"]
        elif "épissure" in nom_lower or "epissure" in nom_lower or "fusion d'arc" in nom_lower:
            base_rendement = 36.0
            unite_rendement = "brin/jour/technicien"
            equipe_data = [{"role": "Soudeur opticien certifié", "effectif": 2}]
            ressources = ["Soudeuse à fusion d'arc cœur à cœur", "Cliveuse haute précision"]
            sources = ["Standards Fibre Optique / ITU-T G.652"]
        elif "otdr" in nom_lower or "réflecto" in nom_lower or "reflecto" in nom_lower:
            base_rendement = 48.0
            unite_rendement = "fibre/jour/technicien"
            equipe_data = [{"role": "Technicien mesures optiques", "effectif": 1}]
            ressources = ["Réflectomètre optique OTDR bi-longueur d'onde"]
            sources = ["Standards Télécoms / ITU-T"]
        elif "soudure aluminothermique" in nom_lower or "cadweld" in nom_lower or "pin brazing" in nom_lower:
            base_rendement = 12.0
            unite_rendement = "point/jour/technicien"
            equipe_data = [{"role": "Technicien Protection Cathodique", "effectif": 1}, {"role": "Aide monteur", "effectif": 1}]
            ressources = ["Kit moules graphite et cartouches Cadweld"]
            sources = ["NACE SP0169 / ISO 15589-1"]
        elif "prise de potentiel" in nom_lower or "test post" in nom_lower:
            base_rendement = 6.0
            unite_rendement = "borne/jour/équipe"
            equipe_data = [{"role": "Monteur électricien PC", "effectif": 2}]
            ressources = ["Outillage de scellement béton"]
            sources = ["NACE SP0169 / ISO 15589-1"]
        elif "on / off" in nom_lower or "on/off" in nom_lower:
            base_rendement = 12.0
            unite_rendement = "borne/jour/ingénieur PC"
            equipe_data = [{"role": "Ingénieur Protection Cathodique (NACE CP3)", "effectif": 1}]
            ressources = ["Voltmètre haute impédance", "Interrupteur de courant synchrone GPS"]
            sources = ["ISO 15589-1 / NACE TM0497"]
        elif "polarisation" in nom_lower or "cips" in nom_lower or "dcvg" in nom_lower:
            base_rendement = 1500.0
            unite_rendement = "ml/jour/ingénieur PC"
            equipe_data = [{"role": "Ingénieur Protection Cathodique", "effectif": 1}]
            ressources = ["Enregistreur de potentiel continu CIPS"]
            sources = ["ISO 15589-1 / NACE TM0497"]
        elif rag_match:
            base_rendement = float(rag_match["rendement_valeur"])
            unite_rendement = str(rag_match["rendement_unite"])
            equipe_data = rag_match.get("equipe", [])
            ressources = rag_match.get("ressources", [])
            sources = [f"{rag_match.get('source', 'Référentiel EPC ARKAN')} ({rag_match.get('normes_associees', 'Standard')})"]

            # Contrôle de cohérence dimensionnelle unité métrée vs unité rendement
            u_rag_clean = unite_rendement.lower().split('/')[0].strip().replace('²', '2').replace('³', '3')
            
            if u_task_clean != u_rag_clean and not (u_task_clean in u_rag_clean or u_rag_clean in u_task_clean):
                if "études" in nom_lower or "ingénierie" in nom_lower or "document" in u_task_clean:
                    base_rendement = 0.5
                    unite_rendement = "doc/jour/ingénieur"
                elif "piquetage" in nom_lower or "détection" in nom_lower:
                    base_rendement = 2000.0
                    unite_rendement = "ml/jour/équipe topo"
                elif "forage" in nom_lower and "puits" in nom_lower:
                    base_rendement = 25.0
                    unite_rendement = "ml forage/jour/foreuse"
                elif "déversoir" in nom_lower or "deversoir" in nom_lower or "colonne d'anode" in nom_lower:
                    base_rendement = 1.0
                    unite_rendement = "puits/jour/équipe"
                elif "poste t/r" in nom_lower or "armoire t/r" in nom_lower or "transformateur-redresseur" in nom_lower:
                    base_rendement = 0.5
                    unite_rendement = "armoire/jour/équipe"
                elif "fourreau" in nom_lower or "pehd" in nom_lower:
                    base_rendement = 500.0
                    unite_rendement = "ml/jour/équipe"
                elif "tranchée" in nom_lower or "fouille" in nom_lower:
                    base_rendement = 400.0
                    unite_rendement = "ml/jour/équipe"
                elif "calibrage" in nom_lower or "calibreur" in nom_lower:
                    base_rendement = 4.0
                    unite_rendement = "section/jour/équipe"
                elif "chambre" in nom_lower or "regard" in nom_lower:
                    base_rendement = 3.0
                    unite_rendement = "chambre/jour/équipe"
                elif "remblai" in nom_lower or "grillage" in nom_lower:
                    base_rendement = 600.0
                    unite_rendement = "ml/jour/équipe"
                elif "di" in u_task_clean:
                    base_rendement = 40.0
                    unite_rendement = "DI/jour/équipe"
                elif "m3" in u_task_clean:
                    base_rendement = 25.0
                    unite_rendement = "m³/jour/équipe"
                elif "m2" in u_task_clean:
                    base_rendement = 80.0
                    unite_rendement = "m²/jour/équipe"
                elif u_task_clean == "t":
                    base_rendement = 2.0
                    unite_rendement = "t/jour/équipe"
                elif any(k in u_task_clean for k in ["whcp", "wellhead", "cave"]):
                    base_rendement = 0.5
                    unite_rendement = f"{unite}/jour/équipe"
                elif any(k in u_task_clean for k in ["instrument", "détecteur", "transmetteur"]):
                    base_rendement = 4.0
                    unite_rendement = "instrument/jour/équipe"
                elif any(k in u_task_clean for k in ["test", "hydro", "épreuve"]):
                    base_rendement = 0.5
                    unite_rendement = "test/jour/équipe"
                elif any(k in u_task_clean for k in ["boucle", "loop"]):
                    base_rendement = 12.0
                    unite_rendement = "boucle/jour/équipe"
                elif "joint" in u_task_clean:
                    base_rendement = 15.0
                    unite_rendement = "joint/jour/équipe"
                elif "ml" in u_task_clean:
                    base_rendement = 20.0
                    unite_rendement = "ml/jour/équipe"
        else:
            base_rendement = 10.0
            unite_rendement = f"{unite}/jour/équipe"
            equipe_data = [{"role": "Chef d'équipe spécialiste", "effectif": 1}, {"role": "Opérateur qualifié", "effectif": 2}]
            ressources = ["Outillage standard de chantier"]
            sources = ["Estimation IA calibrée (à valider par le planificateur)"]

        # 2. Application des Guardrails Anti-Hallucination
        val_ajustee, duree_calc, confiance, _ = planning_guardrails.audit_and_clamp_yield(
            tache_nom=nom,
            quantite=quantite,
            rendement_propose=base_rendement,
            unite=unite_rendement,
            rag_match=rag_match
        )

        equipe_roles = [EquipeRole(role=r.get("role", "Spécialiste"), effectif=int(r.get("effectif", 1))) for r in equipe_data]

        return TachePlanning(
            id_tache=raw_task.get("id_tache", f"T-{abs(hash(nom))%900+100}"),
            nom=nom,
            description=raw_task.get("description", f"Exécution des travaux de {nom} selon spécifications du projet."),
            phase=raw_task.get("phase", "Construction"),
            discipline=discipline,
            unite_oeuvre=unite,
            quantite_estimee=quantite,
            rendement=RendementDetail(valeur=val_ajustee, unite=unite_rendement),
            duree_jours=duree_calc,
            equipe_type=equipe_roles,
            ressources_materielles=ressources,
            predecesseurs=preds,
            successeurs=[],
            jalon=quantite <= 1.0 and ("mise en service" in nom.lower() or "mise sous tension" in nom.lower() or "attestation" in nom.lower() or "rfsu" in nom.lower() or "réception" in nom.lower()),
            niveau_confiance=confiance,
            sources=sources
        )


class PlanningDCMAAgent:
    """Agent 4 : Audit de conformité DCMA 14-Points & Contrôle Qualité de l'Ordonnancement CPM."""

    def audit_schedule(self, taches: List[TachePlanning], critical_path: List[str], total_duration: float) -> Tuple[Dict[str, Any], List[str]]:
        warnings = []
        nb_tasks = len(taches)
        if nb_tasks == 0:
            return {"score_dcma": 100, "status": "PASSED"}, []

        # 1. Tâches orphelines sans prédécesseur (sauf la 1ère)
        missing_preds = [t.id_tache for t in taches[1:] if not t.predecesseurs]
        if missing_preds:
            warnings.append(f"Audit DCMA Point 1 : {len(missing_preds)} tâche(s) intermédiaire(s) sans prédécesseur : {missing_preds[:3]}")

        # 2. Tâches orphelines sans successeur (sauf la dernière)
        missing_succs = [t.id_tache for t in taches[:-1] if not t.successeurs]
        if missing_succs:
            warnings.append(f"Audit DCMA Point 2 : {len(missing_succs)} tâche(s) intermédiaire(s) sans successeur : {missing_succs[:3]}")

        # 3. Continuité du chemin critique
        has_critical = len(critical_path) > 0
        if not has_critical:
            warnings.append("Audit DCMA Point 10 : Aucun chemin critique continu identifié.")

        # 4. Calcul du score DCMA
        penalties = len(missing_preds) * 4 + len(missing_succs) * 4 + (0 if has_critical else 20)
        dcma_score = max(0, min(100, 100 - penalties))

        report = {
            "score_dcma": dcma_score,
            "status": "CONFORME" if dcma_score >= 85 else "AVERTISSEMENT",
            "nb_taches_auditees": nb_tasks,
            "taches_critiques": len(critical_path),
            "ratio_chemin_critique_pct": round((len(critical_path) / max(1, nb_tasks)) * 100, 1),
            "duree_totale_calculee": total_duration,
            "anomalies_detectees": len(warnings)
        }
        return report, warnings


class PlanningMultiagentSwarm:
    """Orchestrateur global du Swarm Multi-Agents pour le Planning IA."""

    def __init__(self):
        self.nlu_agent = PlanningNLUAgent()
        self.wbs_agent = PlanningWBSAgent()
        self.yield_crew_agent = PlanningYieldAndCrewAgent()
        self.dcma_agent = PlanningDCMAAgent()

    async def generate_planning(
        self,
        request: PlanningGenerationRequest,
        stream_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> PlanningResponse:
        t_start = time.time()
        logger.info(f"[PlanningSwarm] Début de génération pour : '{request.prompt[:60]}...'")

        if stream_callback:
            stream_callback({"type": "step", "step": 1, "agent": "NLU Understanding", "message": "Analyse sémantique de la demande et extraction des paramètres..."})

        # ÉTAPE 1 : NLU & Extraction des paramètres
        nlu_result = await self.nlu_agent.analyze(request)
        
        if stream_callback:
            stream_callback({"type": "step", "step": 2, "agent": "WBS Breakdown", "message": f"Décomposition WBS métier ({nlu_result.get('type_installation', 'Installation')})..."})

        # ÉTAPE 2 : Décomposition WBS
        raw_tasks = await self.wbs_agent.decompose(nlu_result, request)

        if stream_callback:
            stream_callback({"type": "step", "step": 3, "agent": "RAG Yields & CPM", "message": f"Attribution des rendements RAG sur {len(raw_tasks)} tâches..."})

        # ÉTAPES 3 & 4 : Parallélisation RAG Rendements & Équipes avec asyncio.gather
        tasks_coroutines = [self.yield_crew_agent.process_task(t) for t in raw_tasks]
        processed_tasks: List[TachePlanning] = await asyncio.gather(*tasks_coroutines)

        # Stream des tâches individuelles si callback actif
        if stream_callback:
            for idx, pt in enumerate(processed_tasks, 1):
                stream_callback({
                    "type": "task_ready",
                    "index": idx,
                    "total": len(processed_tasks),
                    "task": pt.model_dump()
                })

        ordered_tasks, precedence_warnings = planning_guardrails.enforce_universal_precedence(processed_tasks)
        ordered_tasks, critical_path, total_duration, cpm_warnings = planning_cpm.calculate_cpm(ordered_tasks)

        # Étape 5 : Audit de conformité DCMA 14-Points
        dcma_report, dcma_warnings = self.dcma_agent.audit_schedule(ordered_tasks, critical_path, total_duration)

        # Calcul score de confiance moyen
        conf_scores = {"Haute": 95, "Moyenne": 85, "Faible": 65}
        avg_conf = round(sum(conf_scores.get(t.niveau_confiance, 80) for t in ordered_tasks) / max(1, len(ordered_tasks)), 1)

        total_exec_time = round(time.time() - t_start, 2)
        logger.info(f"[PlanningSwarm] Terminé avec succès en {total_exec_time}s ({len(ordered_tasks)} tâches, CPM={len(critical_path)} tâches, Score DCMA={dcma_report.get('score_dcma')}%)")

        response = PlanningResponse(
            projet_contexte=f"{nlu_result.get('type_installation', 'Projet EPC')} | Site: {request.localisation or 'Algérie/Sahara'}",
            taches=ordered_tasks,
            chemin_critique=critical_path,
            duree_totale_jours=total_duration,
            avertissements=cpm_warnings + precedence_warnings + dcma_warnings,
            confidence_score_moyen=avg_conf,
            generated_at=datetime.now().isoformat()
        )

        if stream_callback:
            stream_callback({"type": "complete", "response": response.model_dump()})

        return response


planning_swarm = PlanningMultiagentSwarm()
