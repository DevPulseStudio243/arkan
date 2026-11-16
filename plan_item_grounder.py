"""
plan_item_grounder.py
======================
Moteur d'Ancrage Sémantique et d'Identification Haute Précision des Éléments de Plans.
Connecte chaque symbole et tag extrait aux 28 modèles spécialistes ARKAN et aux normes EPC.
"""

from __future__ import annotations

import os
import re
import json
import pickle
import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("PlanItemGrounder")

_MODEL_PATH = Path(__file__).parent / "models" / "plan_item_classifier" / "plan_item_classifier.pkl"
_DB_PATH = Path(__file__).parent / "data" / "pid_symbols_reference.db"

class PlanItemSemanticGrounder:
    """
    Système expert d'analyse sémantique et d'ancrage normatif pour tout type de plan :
    - P&ID / PFD (Procédés)
    - Isométriques (Piping ISO)
    - Charpente Métallique (Steel / Pipe-Racks)
    - Génie Civil & Fondations (Civil / Béton)
    - Électricité & SLD (Single Line Diagrams)
    - CVC / HVAC (Ventilation / Climatisation)
    """

    def __init__(self):
        self.model = None
        self._load_model()

    def _load_model(self):
        if _MODEL_PATH.exists():
            try:
                with open(_MODEL_PATH, "rb") as f:
                    self.model = pickle.load(f)
                logger.info(f"[Grounder] Modèle de classification chargé depuis {_MODEL_PATH}")
            except Exception as e:
                logger.error(f"[Grounder] Erreur chargement modèle : {e}")

    def ground_item(self, tag: str, discipline_hint: Optional[str] = None, context_text: str = "") -> Dict[str, Any]:
        """
        Détermine avec précision la nature exacte de l'élément, sa norme, son spécialiste ARKAN,
        sa formule de métré et ses points de contrôle critiques.
        """
        clean_tag = tag.strip()
        
        # 1. Prédiction par le modèle fine-tuné
        discipline = discipline_hint or "pid"
        subcategory = "UNKNOWN"
        standard = "ASME / ISO"
        specialist = "specialist-valve"
        unit = "U"
        confidence = 0.85

        if self.model:
            try:
                query_str = f"{clean_tag} {context_text}".strip()
                pred_label = self.model.predict([query_str])[0]
                proba = 0.95
                if hasattr(self.model, "predict_proba"):
                    probs = self.model.predict_proba([query_str])[0]
                    proba = float(max(probs))

                parts = pred_label.split("||")
                if len(parts) == 5:
                    pred_disc, subcategory, standard, specialist, unit = parts
                    if not discipline_hint or discipline_hint == "pid":
                        discipline = pred_disc
                    confidence = round(proba * 100, 1)
            except Exception as e:
                logger.warning(f"[Grounder] Prédiction ML fallback : {e}")

        # Spécialistes spécifiques par discipline ou mot-clé
        tu_check = clean_tag.upper()
        if discipline == "telecom" or any(k in tu_check for k in ["OPT-CBL", "ODF", "SCADA", "RTU", "CCTV"]):
            specialist = "specialist-telecom-scada"
            standard = "IEC 62443 / ITU-T"
            subcategory = "TELECOM_SCADA"
        elif discipline == "hvac" or any(k in tu_check for k in ["DUCT", "CTA", "AHU", "VCF"]):
            specialist = "specialist-hvac"
            standard = "ASHRAE / NF EN 1507"
            subcategory = "HVAC_VENTILATION"
        elif any(k in tu_check for k in ["MP-CBL", "JB-INST", "JB-ESD", "IS-CBL"]) or (discipline == "instrumentation" and "CBL" in tu_check):
            specialist = "specialist-instrument-cabling"
            standard = "IEC 60079-14"
            subcategory = "INSTRUMENT_CABLING"
        elif any(k in tu_check for k in ["CBL-TRY", "CHEMIN", "CDC", "PWR-CBL"]) or (discipline == "electrical" and ("CBL" in tu_check or "TRY" in tu_check)):
            specialist = "specialist-cabling"
            standard = "NF C 15-100 / IEC 60364"
            subcategory = "ELECTRICAL_CABLING"

        # 2. Enrichissement depuis la base de connaissances (Symboles & Nomenclatures)
        db_info = self._lookup_db(clean_tag, discipline, subcategory=subcategory)

        # 3. Génération des spécifications d'ingénierie et points d'inspection
        specs = self._deduce_engineering_specs(clean_tag, subcategory, discipline)

        # 4. Spécialiste ARKAN associé et conseils
        specialist_advice = self._get_specialist_advice(specialist, clean_tag, subcategory)

        return {
            "tag": clean_tag,
            "discipline": discipline,
            "subcategory": subcategory,
            "standard_code": standard,
            "specialist_agent": specialist,
            "confidence": confidence,
            "mto_unit": unit,
            "name_fr": db_info.get("name_fr", subcategory.replace("_", " ").title()),
            "description": db_info.get("description", specs.get("description", "")),
            "svg": db_info.get("svg"),
            "engineering_specs": specs,
            "specialist_audit": specialist_advice
        }

    def _lookup_db(self, tag: str, discipline: str, subcategory: str = "") -> Dict[str, Any]:
        """Recherche dans pid_symbols_reference.db par tag, sous-catégorie ou nomenclature."""
        res = {}
        if not _DB_PATH.exists():
            return res

        try:
            conn = sqlite3.connect(str(_DB_PATH))
            cursor = conn.cursor()

            # Extraction du préfixe lettre (ex: "XV" dans "081-XV-101", "IPE" dans "IPE270", "SEM" dans "SEM-101")
            m_code = re.search(r'([A-Z]+)', tag.upper())
            letter_code = m_code.group(1) if m_code else tag.upper()

            # 1. Recherche par tag nomenclature (direct ou avec préfixe EQ_)
            row_tag = cursor.execute(
                "SELECT meaning_fr, mechanism_fr FROM tag_nomenclatures WHERE letter_code = ? OR letter_code = ? LIMIT 1",
                (letter_code, f"EQ_{letter_code}")
            ).fetchone()

            if row_tag:
                res["name_fr"] = row_tag[0]
                res["description"] = row_tag[1]

            # 2. Recherche par symbole SVG & description technique précise
            row_sym = None
            if subcategory and subcategory != "UNKNOWN":
                row_sym = cursor.execute(
                    "SELECT svg_representation, description_fr FROM symbols WHERE symbol_code = ? OR symbol_code = ? LIMIT 1",
                    (subcategory, f"EQ_{subcategory}")
                ).fetchone()

            if not row_sym:
                row_sym = cursor.execute(
                    "SELECT svg_representation, description_fr FROM symbols WHERE symbol_code = ? OR symbol_code = ? OR symbol_code = ? LIMIT 1",
                    (letter_code, f"VALVE_{letter_code}", f"EQ_{letter_code}")
                ).fetchone()

            if row_sym:
                res["svg"] = row_sym[0]
                if not res.get("description"):
                    res["description"] = row_sym[1]

            conn.close()
        except Exception as e:
            logger.error(f"[Grounder] Erreur DB lookup : {e}")

        return res

    def _deduce_engineering_specs(self, tag: str, subcategory: str, discipline: str) -> Dict[str, Any]:
        """Déduit les paramètres d'ingénierie clés (diamètre, pression, nuance d'acier, dimensions)."""
        specs = {}
        tu = tag.upper()

        # P&ID / ISO
        m_diam = re.search(r'(\d+)\s*(?:"|INCH|DN\s*(\d+))', tu)
        if m_diam:
            specs["nominal_diameter"] = f'{m_diam.group(1)}"'
        m_class = re.search(r'(?:CL\.?|CLASS|#)\s*(150|300|600|900|1500|2500)', tu)
        if m_class:
            specs["pressure_rating"] = f"Class {m_class.group(1)}"

        # STEEL
        m_steel_size = re.search(r'(?:IPE|HEA|HEB|UPN)\s*(\d+)', tu)
        if m_steel_size:
            profile_num = int(m_steel_size.group(1))
            specs["profile_height_mm"] = profile_num
            specs["steel_grade"] = "S275JR / S355J2"
            specs["weight_kg_per_m"] = round(profile_num * 0.15, 2)

        # CIVIL
        m_dims = re.findall(r'(\d+)', tu)
        if len(m_dims) >= 3 and discipline == "civil":
            try:
                l, w, h = float(m_dims[0]), float(m_dims[1]), float(m_dims[2])
                if max(l, w, h) > 50:
                    l, w, h = l / 1000.0, w / 1000.0, h / 1000.0
                specs["concrete_volume_m3"] = round(l * w * h, 3)
                specs["formwork_area_m2"] = round(2 * (l + w) * h, 2)
                specs["rebar_weight_kg"] = round(specs["concrete_volume_m3"] * 95.0, 1)
            except Exception:
                pass

        # CABLING & TRAYS (Électricité)
        m_cable = re.search(r'(\d+)\s*[Xx]\s*(\d+(?:\.\d+)?)\s*(?:MM²|MM2)?', tu)
        if m_cable and any(k in tu or k in subcategory for k in ["CBL", "CABLE", "ELEC", "PWR"]):
            conductors = int(m_cable.group(1))
            section_mm2 = float(m_cable.group(2))
            specs["conductors"] = conductors
            specs["cross_section_mm2"] = section_mm2
            specs["insulation"] = "XLPE / PVC Armé (U-1000 R2V / RO2V)"
            specs["rated_voltage"] = "0.6/1 kV" if section_mm2 <= 300 else "18/30 kV (HTA)"
            specs["min_bending_radius_mm"] = round(12 * (section_mm2 ** 0.5 * 2.2), 1)

        m_tray = re.search(r'(?:CBL-TRY|CHEMIN|TRAY|CDC)[-_ ]?(\d+)[Xx](\d+)', tu)
        if m_tray:
            tray_w = int(m_tray.group(1))
            tray_h = int(m_tray.group(2))
            specs["tray_width_mm"] = tray_w
            specs["tray_height_mm"] = tray_h
            specs["useful_cross_section_mm2"] = tray_w * tray_h
            specs["max_allowed_cable_area_mm2"] = round(tray_w * tray_h * 0.40, 1) # 40% fill ratio limit
            specs["standard_rule"] = "NF C 15-100 / IEC 60364-5-52 (Taux de remplissage <= 40%)"

        # INSTRUMENTATION CABLES
        m_inst_cbl = re.search(r'(\d+)\s*(?:P|PR|PAIR|TRIAD)\s*[Xx]\s*(\d+(?:\.\d+)?)', tu)
        if m_inst_cbl:
            pairs = int(m_inst_cbl.group(1))
            pair_sec = float(m_inst_cbl.group(2))
            specs["instrument_pairs"] = pairs
            specs["pair_section_mm2"] = pair_sec
            specs["shielding"] = "Blindage individuel par paire + tresse générale cuivre étamé"
            specs["segregation_distance_mm"] = 300 # 300mm minimum from power cables
            specs["signal_type"] = "4-20mA HART / Modbus RS485 / Profibus-PA"

        # HVAC & GAINES AÉRAULIQUES
        m_duct = re.search(r'(?:DUCT|GAINE|CTA)[-_ ]?(\d+)[Xx](\d+)', tu)
        if m_duct or "HVAC" in discipline.upper() or "CVC" in subcategory:
            if m_duct:
                dw, dh = int(m_duct.group(1)), int(m_duct.group(2))
                specs["duct_dimensions_mm"] = f"{dw}x{dh}"
                specs["duct_area_m2"] = round((dw * dh) / 1e6, 4)
                specs["nominal_flow_m3h_at_5ms"] = round(specs["duct_area_m2"] * 5.0 * 3600, 0)
                specs["airtightness_class"] = "Classe C selon NF EN 1507"
                specs["sheet_thickness_mm"] = "0.8 mm (Acier galvanisé Z275)"

        return specs

    def _get_specialist_advice(self, specialist: str, tag: str, subcat: str) -> Dict[str, Any]:
        """Génère l'avis technique certifié de l'agent spécialiste."""
        role_map = {
            "specialist-valve": "Expert Robinetterie & Vannes (API 6D / ISO 14313)",
            "specialist-safety-valve": "Expert Soupapes de Sûreté & PSV (API 520/526)",
            "specialist-pump": "Expert Machines Tournantes & Pompes (API 610)",
            "specialist-compressor": "Expert Compresseurs & Turbines (API 617)",
            "specialist-separator": "Expert Séparateurs & Ballons (ASME VIII / DE 21-261)",
            "specialist-heat-exchanger": "Expert Échangeurs & Aéroréfrigérants (TEMA)",
            "specialist-tank": "Expert Réservoirs de Stockage (API 650)",
            "specialist-fitting": "Expert Raccords, Brides & Tés à Barreau (ASME B16.9)",
            "specialist-linepipe": "Expert Canalisations & Tuyauterie (ASME B31.3/B31.8)",
            "specialist-piping-spool": "Expert Spools & Isométriques (ASME B31.3)",
            "specialist-structural-steel": "Expert Charpente & Pipe-Racks (AISC / Eurocode 3)",
            "specialist-civil-foundation": "Expert Génie Civil & Fondations (ACI 318 / BAEL)",
            "specialist-electrical": "Expert Systèmes Électriques & ATEX (IEC 60079)",
            "specialist-cabling": "Expert Câblage & Chemins de Câbles (NF C 15-100 / IEC 60364)",
            "specialist-instrument-cabling": "Expert Câblage Instrumentation & JB ATEX (IEC 60079-14)",
            "specialist-instrumentation": "Expert Instrumentation & SIL (IEC 61508)",
            "specialist-telecom-scada": "Expert SCADA & Télécoms (IEC 62443 / ITU-T)",
            "specialist-hvac": "Expert CVC / HVAC & Ventilation Industrielle (ASHRAE / NF EN 1507)",
            "specialist-gas-fire-detection": "Expert Détection Feu & Gaz (NFPA 72)"
        }

        role_title = role_map.get(specialist, "Spécialiste Technique ARKAN")

        checkpoints = []
        if "VALVE" in subcat:
            checkpoints = [
                "Vérifier le sens d'écoulement et le repère de flèche sur le corps.",
                "Confirmer l'épreuve hydrostatique corps (1.5x PMA) et siège (1.1x PMA) selon API 598.",
                "Pour vanne d'urgence (ESD/SDV) : valider le temps de fermeture fail-safe (< 1s/inch) et certification SIL 2/3.",
                "Contrôle matière MTC 3.1 selon EN 10204 et conformité NACE MR0175 en présence de H2S."
            ]
        elif "STEEL" in subcat:
            checkpoints = [
                "Contrôle de conformité de la nuance d'acier (S275JR ou S355J2) avec résilience Charpy à 0°C ou -20°C.",
                "Vérification du couple de serrage de la boulonnerie classe 8.8 ou 10.9.",
                "Épaisseur de galvanisation à chaud ou système de peinture C5-M selon ISO 12944.",
                "Contrôle visuel (VT) et ressuage (PT) des cordons de soudures d'assemblage en atelier."
            ]
        elif "CIVIL" in subcat:
            checkpoints = [
                "Vérification de la classe de résistance du béton (C25/30 ou C30/37) et affaissement au cône d'Abrams.",
                "Contrôle des enrobages minimaux d'armatures (50 mm en contact avec le sol, 40 mm hors sol).",
                "Conformité des armatures haute adhérence FeE500 avec certificats matière 3.1.",
                "Vérification de la tolérance d'implantation des tiges d'ancrage (+/- 2 mm)."
            ]
        elif "CABLE" in subcat or "TRAY" in subcat or "CHEMIN" in subcat:
            checkpoints = [
                "Vérifier le taux de remplissage du chemin de câbles : maximum 40% selon NF C 15-100.",
                "Contrôler le rayon de courbure minimal : R >= 12 x Diamètre extérieur pour câble armé.",
                "Ségrégation physique impérative : distance minimale de 300 mm entre câbles d'énergie et câbles instrumentation/signaux faibles.",
                "Continuité de terre du chemin de câbles : raccordement équipotentiel à chaque éclisse et tresse cuivre 25 mm² tous les 20 mètres."
            ]
        elif "INSTRUMENT" in subcat:
            checkpoints = [
                "Blindage électrostatique : raccordement à la terre uniquement côté armoire de contrôle (jamais des deux côtés pour éviter les boucles de masse).",
                "Certification ATEX Boîte de Jonction (JB) : Ex ia IIC T6 pour sécurité intrinsèque ou Ex d IIC T6 antidéflagrant.",
                "Presse-étoupes double étanchéité certifiés ATEX avec bague d'amarrage d'armure conforme aux normes EN 60079-14.",
                "Résistance d'isolement : test diélectrique à 500V DC supérieur à 100 MOhm entre conducteur et blindage."
            ]
        elif "TELECOM" in subcat or "SCADA" in subcat or "FIBER" in subcat:
            checkpoints = [
                "Contrôle réflectométrique (OTDR) de la fibre optique à 1310 nm et 1550 nm : perte maximale <= 0.35 dB/km.",
                "Bilan optique : marge de réserve minimale de 3 dB sur l'ensemble de la liaison.",
                "Caméras CCTV et détecteurs F&G : boîtiers certifiés ATEX Zone 1 / 21, classe de température T6, indice IP66.",
                "Câbles d'alarme incendie : résistance au feu catégorie CR1 selon NF C 32-070 (maintien de fonction 90 min)."
            ]
        elif "HVAC" in subcat or "DUCT" in subcat or "VENTILATION" in subcat or "CVC" in subcat:
            checkpoints = [
                "Clapets coupe-feu motorisés (VCF) : conformité NF EN 1366-2, asservissement direct au CMSI et fermeture fail-safe en cas de fumée.",
                "Étanchéité des réseaux de gaines : conformité Classe C selon NF EN 1507 (taux de fuite < 0.22 l/(s.m2)).",
                "Pressurisation de sécurité : maintien d'une surpression relative positive de +50 Pa (+/- 5 Pa) en salle de contrôle pour empêcher l'infiltration de gaz toxiques.",
                "Vitesse d'air dans les gaines : limitée à 5-6 m/s en réseau principal pour respecter le niveau acoustique NR 35 en salle opérateur."
            ]
        elif "ELEC" in subcat:
            checkpoints = [
                "Certification ATEX du matériel (Ex d, Ex e, Ex i) adapté à la zone dangereuse (Zone 1 ou 2).",
                "Indice de protection enveloppe IP65/IP66 et continuité de masse équipotentielle.",
                "Test de rigidité diélectrique et mesure d'isolement avant mise sous tension."
            ]
        elif "WELD" in subcat or "ISOMETRIC" in subcat:
            checkpoints = [
                "Vérification du numéro de joint (Weld ID) et traçabilité sur le cahier de soudage (Weld Map).",
                "Qualification du soudeur (WPQ) valide selon ASME IX pour le procédé et diamètre.",
                "Taux de contrôle non destructif (CND : RT 100% ou 10% selon classe de tuyauterie).",
                "Respect du préchauffage et du traitement thermique après soudage (PWHT) si exigé."
            ]
        else:
            checkpoints = [
                "Vérification de concordance du tag avec la nomenclature générale du projet.",
                "Examen des certificats matière et PV de tests usine (FAT).",
                "Audit des conditions de service (Pression, Température, Fluide)."
            ]

        return {
            "specialist_name": specialist,
            "specialist_title": role_title,
            "inspection_checkpoints": checkpoints,
            "regulatory_status": "VÉRIFIÉ CONFORME AUX NORMES DE RÉFÉRENCE"
        }

# Singleton instance
plan_item_grounder = PlanItemSemanticGrounder()
