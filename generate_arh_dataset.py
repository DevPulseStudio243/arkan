"""
generate_arh_dataset.py
=======================
Générateur de Dataset d'Entraînement ARH pour Fine-Tuning de Modèle 7B (Qwen2.5-7B / Mistral-7B).
Génère 1 500 cas d'ingénierie Oil & Gas complets et réalistes au format JSONL Instruct.

Couverture des 6 Piliers Métier :
  1. Appareils à Pression & Cuves (Décret 21-314, ASME VIII Div 1/2, CODAP) - 300 cas
  2. Canalisations & Tuyauteries (Décret 21-315, ASME B31.3, API 5L) - 300 cas
  3. Soudage & Contrôles CND (WPS, PQR, ASME IX, ISO 15614, Art. 16-17) - 300 cas
  4. Métallurgie & Certificats 3.1 (CEV, Pcm, Dureté NACE MR0175, Charpy KV) - 250 cas
  5. Raccords, Tés à Barreaux & Brides (MSS SP-75, ASME B16.9/B16.5) - 200 cas
  6. Administratif & Légalisation (Visas Consulaires, Annexe B, Annexe E, P-CTE-1) - 150 cas
"""

import json
import random
import os
from typing import Dict, List, Any


def generate_1500_dataset(output_path: str = "dataset_arh_1500.jsonl") -> int:
    random.seed(42)
    dataset = []

    # ──────────────────────────────────────────────────────────────────────────
    # BANQUE DE MATÉRIAUX, FLUIDES, DÉCRETS ET NORMES
    # ──────────────────────────────────────────────────────────────────────────
    grades = ["ASTM A350 LF2", "ASTM A105", "ASTM A234 WPB", "API 5L Gr B", "API 5L X52", "API 5L X60", "API 5L X65", "ASTM A333 Gr 6", "ASTM A516 Gr 70"]
    fluids = ["Gaz Naturel Haute Pression (Sour Gas H2S)", "Pétrole Brut Stabilisé", "Condensat C3/C4", "Gaz Combustible (Fuel Gas)", "Eau de Production Salée", "GPL Sous Pression"]
    projects = ["PROJET BOOSTING HASSI R'MEL", "PROJET SEPARATION CPF TOUAT", "CENTRE DE TRAITEMENT RHOURDE NOUSS", "OLEODUC OZ2 28 POUCES", "GAZODUC GK3 48 POUCES", "COMPLEXE GNL SKIKDA"]
    contractors = ["PETROFAC EPC", "JGC CORPORATION", "SAIPEM CONTRACTING", "TECHINT ENGINEERING", "COSIDER CANALISATIONS", "GCB FILIALE SONATRACH"]
    subcontractors = ["BONNEY FORGE ITALY", "FORGITAL GROUP", "TENARIS DALMINE", "VALLOUREC TUBES", "OFFICINE NICOLA GALPERTI", "SUMITOMO METALS"]

    system_instruction = (
        "Tu es l'Inspecteur Virtuel Expert ARH (Autorité de Régulation des Hydrocarbures d'Algérie). "
        "Analyse le dossier technique et identifie avec rigueur toutes les non-conformités réglementaires "
        "selon la procédure P-CTE-1, les décrets exécutifs algériens (21-261, 21-314, 21-315, 24-278, 17-62) "
        "et les codes internationaux (ASME VIII/IX, ASME B31.3, API 5L, MSS SP-75, NACE MR0175, EN 10204 3.1). "
        "Réponds impérativement sous forme d'un objet JSON strict avec la décision ARH, le score et la liste des remarques."
    )

    # ──────────────────────────────────────────────────────────────────────────
    # 1. PILIER 1 : APPAREILS SOUS PRESSION & CUVES (300 CAS)
    # ──────────────────────────────────────────────────────────────────────────
    for i in range(300):
        proj = random.choice(projects)
        tag = f"V-{random.randint(100, 999)}"
        mat = random.choice(["ASTM A516 Gr 70", "ASTM A350 LF2", "SA-516 Gr 60"])
        fluid = random.choice(fluids)
        p_des = random.randint(15, 120)
        t_des = random.randint(50, 150)
        t_min = random.choice([-29, -46, -20, 0])
        
        # Scénario Conforme vs Non Conforme
        is_compliant = (i % 4 == 0)
        
        anomalies = []
        if is_compliant:
            p_hyd = round(p_des * 1.5, 1)
            dur_hyd = 4
            ndt_rate = 100
            ca = 3.0
            input_text = (
                f"AUDIT DOSSIER ARH - APPAREIL À PRESSION (SEPARATEUR / BALLON)\n"
                f"Projet: {proj} | Tag: {tag}\n"
                f"Matériau Enveloppe: {mat} | Fluide: {fluid}\n"
                f"Pression de Design (PMA): {p_des} bar | Température Design: {t_des} °C | Température Minimale (MDMT): {t_min} °C\n"
                f"Surépaisseur Corrosion (C.A.): {ca} mm | Épaisseur Calculée: 22 mm (Fournie: 25 mm)\n"
                f"Pression d'Épreuve Hydrostatique: {p_hyd} bar (Facteur 1.5x) | Durée de Maintien: {dur_hyd} heures avec enregistreur étalonné\n"
                f"Taux CND Radio (RT): {ndt_rate}% des soudures | Note de calcul conforme ASME VIII Div.1\n"
                f"Fiche Annexe E P-CTE-1: Dûment complétée et signée | Visa Organisme Agréé ALGERAC: Présent"
            )
            output_obj = {
                "decision": "CONFORME (APPROUVÉ SANS RÉSERVE)",
                "compliance_score": 100.0,
                "anomalies_count": 0,
                "anomalies": []
            }
        else:
            # Injecter 1 à 3 non-conformités
            errors = []
            if i % 3 == 0:
                p_hyd_err = round(p_des * 1.1, 1)
                errors.append({
                    "priority": "CRITICAL",
                    "category": "ÉPREUVE HYDROSTATIQUE",
                    "title": f"Pression d'Épreuve Hydrostatique Insuffisante ({p_hyd_err} bar vs {p_des * 1.43:.1f} bar Requis)",
                    "article": "Décret exécutif n° 21-314 (Art. 24) / ASME VIII Div.1 UG-99",
                    "action_required": f"Réviser la pression d'épreuve hydrostatique à minimum 1.43 x PMA ({p_des * 1.43:.1f} bar)."
                })
            if i % 2 == 0:
                errors.append({
                    "priority": "MAJOR",
                    "category": "SURÉPAISSEUR DE CORROSION",
                    "title": "Surépaisseur de Corrosion Inférieure aux Exigences Fluide Acide (1.5 mm vs 3.0 mm)",
                    "article": "Spécification Sonatrach P-CTE-1 / ASME Section VIII",
                    "action_required": "Augmenter la surépaisseur de corrosion nominale à 3.0 mm minimum pour service Sour H2S."
                })
            if i % 5 == 0:
                errors.append({
                    "priority": "CRITICAL",
                    "category": "VISA RÉGLEMENTAIRE",
                    "title": "Absence de Visa de l'Organisme de Contrôle Habilité (ALGERAC / Bureau Agréé)",
                    "article": "Décret exécutif n° 24-278 / Décret 21-261 Art. 22",
                    "action_required": "Faire apposer le visa de conformité original par un organisme accrédité ALGERAC."
                })
            
            p_hyd = round(p_des * 1.1 if i % 3 == 0 else p_des * 1.5, 1)
            ca = 1.5 if i % 2 == 0 else 3.0
            input_text = (
                f"AUDIT DOSSIER ARH - APPAREIL À PRESSION (SEPARATEUR / BALLON)\n"
                f"Projet: {proj} | Tag: {tag}\n"
                f"Matériau Enveloppe: {mat} | Fluide: {fluid}\n"
                f"Pression de Design (PMA): {p_des} bar | Température Design: {t_des} °C | Température Minimale (MDMT): {t_min} °C\n"
                f"Surépaisseur Corrosion: {ca} mm | Épaisseur: 20 mm\n"
                f"Pression d'Épreuve Hydrostatique: {p_hyd} bar | Durée: 4h\n"
                f"Taux CND Radio: 100% | Fiche Annexe E: Transmise"
            )
            output_obj = {
                "decision": "NON CONFORME (REJETÉ - RÉSERVES CRITIQUES)",
                "compliance_score": max(20.0, 100.0 - (len(errors) * 30.0)),
                "anomalies_count": len(errors),
                "anomalies": errors
            }

        dataset.append({
            "instruction": system_instruction,
            "input": input_text,
            "output": json.dumps(output_obj, ensure_ascii=False, indent=2)
        })

    # ──────────────────────────────────────────────────────────────────────────
    # 2. PILIER 2 : CANALISATIONS & TUYAUTERIES (300 CAS)
    # ──────────────────────────────────────────────────────────────────────────
    for i in range(300):
        proj = random.choice(projects)
        dn = random.choice([8, 12, 16, 20, 24, 28, 30, 48])
        grade = random.choice(["API 5L Gr B", "API 5L X52", "API 5L X65", "ASTM A333 Gr 6"])
        fluid = random.choice(fluids)
        p_des = random.randint(40, 100)
        is_pipeline = (dn >= 16)
        
        is_compliant = (i % 4 == 0)
        if is_compliant:
            dur_req = 24 if is_pipeline else 4
            input_text = (
                f"DOSSIER CONSTRUCTEUR ARH - TRONÇON DE CANALISATION / TUYAUTERIE\n"
                f"Projet: {proj} | Diamètre Nominal: {dn}\" | Nuance: {grade}\n"
                f"Fluide: {fluid} | Pression de Service Maximale (PMS): {p_des} bar\n"
                f"Pression d'Épreuve Hydrostatique: {p_des * 1.5:.1f} bar | Durée de Maintien Continu: {dur_req} heures\n"
                f"Enregistreur de Pression/Température: Dead Weight Tester & Manomètre étalonnés avec certificat COFRAC/ALGERAC\n"
                f"Revêtement Externe: 3LPE (Épaisseur 3.2 mm conforme) | DFT Peinture Aérienne: 280 µm (Spécifié 260 µm min)\n"
                f"Radiographie 100% Soudures Bout à Bout conforme ASME B31.3 / B31.8"
            )
            output_obj = {
                "decision": "CONFORME (APPROUVÉ)",
                "compliance_score": 100.0,
                "anomalies_count": 0,
                "anomalies": []
            }
        else:
            errors = []
            dur_actual = 4 if is_pipeline else 1
            dur_req = 24 if is_pipeline else 4
            errors.append({
                "priority": "CRITICAL",
                "category": "DURÉE D'ÉPREUVE HYDROSTATIQUE",
                "title": f"Durée d'Épreuve Hydrostatique Non Conforme ({dur_actual}h vs {dur_req}h Exigées)",
                "article": "Décret exécutif n° 21-315 (Art. 26 et 28)",
                "action_required": f"Recommencer l'épreuve hydrostatique avec un maintien continu sous pression de {dur_req}h enregistré par grapheur certifié."
            })
            if i % 2 == 0:
                errors.append({
                    "priority": "MAJOR",
                    "category": "REVÊTEMENT & PROTECTION ANTICORROSION",
                    "title": "Épaisseur Sèche de Peinture (DFT) Insuffisante (180 µm vs 260 µm Requis)",
                    "article": "Spécification Technique Revêtement Sonatrach / Décret 21-315 Art. 30",
                    "action_required": "Appliquer une couche de finition supplémentaire pour atteindre les 260 µm minimaux requis."
                })
            
            input_text = (
                f"DOSSIER CONSTRUCTEUR ARH - TRONÇON DE CANALISATION / TUYAUTERIE\n"
                f"Projet: {proj} | Diamètre Nominal: {dn}\" | Nuance: {grade}\n"
                f"Fluide: {fluid} | Pression de Service (PMS): {p_des} bar\n"
                f"Pression d'Épreuve Hydrostatique: {p_des * 1.5:.1f} bar | Durée de Maintien: {dur_actual} heures\n"
                f"DFT Peinture: 180 µm | Radiographie: 100%"
            )
            output_obj = {
                "decision": "NON CONFORME (REJETÉ)",
                "compliance_score": 35.0,
                "anomalies_count": len(errors),
                "anomalies": errors
            }

        dataset.append({
            "instruction": system_instruction,
            "input": input_text,
            "output": json.dumps(output_obj, ensure_ascii=False, indent=2)
        })

    # ──────────────────────────────────────────────────────────────────────────
    # 3. PILIER 3 : SOUDAGE & CONTRÔLES CND (300 CAS)
    # ──────────────────────────────────────────────────────────────────────────
    for i in range(300):
        proj = random.choice(projects)
        wps_no = f"WPS-{proj[:3]}-SMAW/GMAW-{random.randint(10, 99)}"
        pqr_no = f"PQR-QUALIF-{random.randint(100, 999)}"
        process = random.choice(["GTAW + SMAW", "GMAW + SAW", "SMAW"])
        base_mat = random.choice(grades)
        
        is_compliant = (i % 4 == 0)
        if is_compliant:
            input_text = (
                f"CAHIER DE SOUDAGE ARH - DESCRIPTIF & QUALIFICATION DES MODES OPÉRATOIRES\n"
                f"Projet: {proj} | Procédure: {wps_no} | Procédé de Soudage: {process}\n"
                f"Matériau de Base: {base_mat} (P-Number 1 Group 1/2) | Épaisseurs Qualifiées: 5.0 mm à 32.0 mm\n"
                f"Rapport de Qualification PQR Rattaché: {pqr_no} (Essais Traction Rm=540 MPa, Pliage 180° Conforme, Charpy -46°C=48J)\n"
                f"Homologation Soudeurs (WOPQ / ISO 9606-1): Tous les certificats de qualification à jour de validité (6 mois)\n"
                f"Traitement Thermique Après Soudage (PWHT): Réalisé à 600°C +/- 15°C avec enregistrement thermocouple"
            )
            output_obj = {
                "decision": "CONFORME (SOUDAGE QUALIFIÉ)",
                "compliance_score": 100.0,
                "anomalies_count": 0,
                "anomalies": []
            }
        else:
            errors = []
            if i % 3 == 0:
                errors.append({
                    "priority": "CRITICAL",
                    "category": "QUALIFICATION WPS / PQR",
                    "title": f"Procédure de Soudage {wps_no} transmise SANS Rapport de Qualification PQR correspondant",
                    "article": "Décret exécutif n° 21-261 (Art. 16) / ASME Section IX QW-200.1",
                    "action_required": f"Ajouter le PV d'essais mécaniques PQR homologué couvrant la nuance {base_mat} et le procédé {process}."
                })
            if i % 2 == 0:
                errors.append({
                    "priority": "CRITICAL",
                    "category": "QUALIFICATION SOUDEURS",
                    "title": "Certificats de Qualification Soudeurs (WOPQ) Périmés (> 6 mois sans prolongation)",
                    "article": "ASME IX QW-322 / EN ISO 9606-1 / Décret 21-261 Art. 17",
                    "action_required": "Fournir les attestations de maintien en activité semestrielles visées par le coordinateur soudage."
                })
            
            input_text = (
                f"CAHIER DE SOUDAGE ARH - DESCRIPTIF DES MODES OPÉRATOIRES\n"
                f"Projet: {proj} | Procédure: {wps_no} | Procédé: {process}\n"
                f"Matériau: {base_mat} | PQR: Non joint ou incohérent\n"
                f"Qualifications Soudeurs: Présentes mais dernière signature datant de plus de 9 mois"
            )
            output_obj = {
                "decision": "NON CONFORME (SOUDAGE REJETÉ)",
                "compliance_score": 25.0,
                "anomalies_count": len(errors),
                "anomalies": errors
            }

        dataset.append({
            "instruction": system_instruction,
            "input": input_text,
            "output": json.dumps(output_obj, ensure_ascii=False, indent=2)
        })

    # ──────────────────────────────────────────────────────────────────────────
    # 4. PILIER 4 : MÉTALLURGIE & CERTIFICATS 3.1 & CEV (250 CAS)
    # ──────────────────────────────────────────────────────────────────────────
    for i in range(250):
        proj = random.choice(projects)
        heat = f"H-{random.randint(10000, 99999)}"
        grade = random.choice(["ASTM A350 LF2", "API 5L X52", "ASTM A105", "ASTM A234 WPB"])
        
        # Composition chimique
        c = round(random.uniform(0.14, 0.24), 2)
        mn = round(random.uniform(1.00, 1.45), 2)
        si = round(random.uniform(0.18, 0.32), 2)
        p = round(random.uniform(0.008, 0.020), 3)
        s = round(random.uniform(0.003, 0.015), 3)
        cr = round(random.uniform(0.05, 0.20), 2)
        mo = round(random.uniform(0.02, 0.10), 2)
        ni = round(random.uniform(0.10, 0.30), 2)
        cu = round(random.uniform(0.08, 0.20), 2)
        v = round(random.uniform(0.01, 0.05), 2)

        # Calcul exact CEV IIW
        cev = round(c + (mn / 6.0) + ((cr + mo + v) / 5.0) + ((ni + cu) / 15.0), 3)
        hardness = random.randint(155, 275)

        is_compliant = (cev <= 0.43 and hardness <= 250)

        input_text = (
            f"AUDIT CERTIFICAT MATIÈRE EN 10204 3.1 - ANALYSE MÉTALLURGIQUE\n"
            f"Projet: {proj} | N° de Coulée (Heat Number): {heat} | Nuance: {grade}\n"
            f"Composition Chimique sur Coulée (% en masse) :\n"
            f"  %C = {c} | %Mn = {mn} | %Si = {si} | %P = {p} | %S = {s}\n"
            f"  %Cr = {cr} | %Mo = {mo} | %Ni = {ni} | %Cu = {cu} | %V = {v}\n"
            f"Essais Mécaniques :\n"
            f"  Limite Élastique ReH: 340 MPa | Résistance Traction Rm: 535 MPa | Allongement A%: 28%\n"
            f"  Résilience Charpy V à -46°C: 48 Joules | Dureté Mesurée: {hardness} HV10\n"
            f"Traitement Thermique: Normalisé à 910°C (N)"
        )

        if is_compliant:
            output_obj = {
                "decision": "CONFORME (MÉTALLURGIE VALIDÉE)",
                "compliance_score": 100.0,
                "calculated_cev": cev,
                "anomalies_count": 0,
                "anomalies": []
            }
        else:
            errors = []
            if cev > 0.43:
                errors.append({
                    "priority": "CRITICAL",
                    "category": "CARBONE ÉQUIVALENT (CEV)",
                    "title": f"Carbone Équivalent CEV Supérieur à la Limite Réglementaire ({cev}% > 0.43%)",
                    "article": "ASME B31.3 / API 5L / Décret 21-261 Art. 14",
                    "action_required": f"Rejeter le lot ou exiger une procédure de soudage spéciale avec préchauffage élevé qualifié par PQR."
                })
            if hardness > 250:
                errors.append({
                    "priority": "CRITICAL",
                    "category": "RÉSISTANCE CORROSION SOUR (NACE)",
                    "title": f"Dureté Métallique Non Conforme NACE MR0175 ({hardness} HV10 > 250 HV10)",
                    "article": "NACE MR0175 / ISO 15156-2 / Décret 21-315 Art. 18",
                    "action_required": "Réaliser un traitement thermique de détensionnement (PWHT) pour ramener la dureté sous 250 HV10."
                })

            output_obj = {
                "decision": "NON CONFORME (CERTIFICAT 3.1 REJETÉ)",
                "compliance_score": 30.0,
                "calculated_cev": cev,
                "anomalies_count": len(errors),
                "anomalies": errors
            }

        dataset.append({
            "instruction": system_instruction,
            "input": input_text,
            "output": json.dumps(output_obj, ensure_ascii=False, indent=2)
        })

    # ──────────────────────────────────────────────────────────────────────────
    # 5. PILIER 5 : RACCORDS, TÉS À BARREAUX & BRIDES (200 CAS)
    # ──────────────────────────────────────────────────────────────────────────
    for i in range(200):
        proj = random.choice(projects)
        tag = f"BT-{random.randint(10, 99)}"
        dn = random.choice([20, 24, 28, 30, 48])
        branch_dn = dn
        cls = random.choice([300, 600, 900])
        
        is_compliant = (i % 4 == 0)
        if is_compliant:
            input_text = (
                f"DOSSIER TECHNIQUE ARH - TÉ À BARREAUX (BARRED TEE GA DRAWING)\n"
                f"Projet: {proj} | Repère Équipement: {tag} | Dimension: {dn}\"x{branch_dn}\" Class {cls}\n"
                f"Nuance Corps du Té: ASTM A350 LF2 CL.1 | Nuance Barreaux de Guidage: ASTM A350 LF2 (Compatible)\n"
                f"Espacement Entre Barreaux: 45 mm (Inférieur à 0.4 x ID Racleur conformément aux règles de raclage Sonatrach)\n"
                f"Chanfreinage & Soudure Barreaux: Soudure pleine pénétration avec contrôle ressuage PT 100%\n"
                f"Pression d'Épreuve Corps: 153 bar | Fiche Annexe E: Renseignée avec températures de service (-29°C / +65°C)"
            )
            output_obj = {
                "decision": "CONFORME (APPROUVÉ)",
                "compliance_score": 100.0,
                "anomalies_count": 0,
                "anomalies": []
            }
        else:
            errors = []
            if i % 2 == 0:
                errors.append({
                    "priority": "MAJOR",
                    "category": "PLANS & SPÉCIFICATION MATÉRIAUX",
                    "title": "Nuance et Matériau des Barreaux de Guidage Non Mentionnés sur le Plan d'Ensemble",
                    "article": "MSS SP-75 / Spécification Technique ARH Barred Tee",
                    "action_required": "Indiquer explicitement sur le plan la nuance métallurgique des barreaux (ex: ASTM A350 LF2) compatible avec le corps."
                })
            if i % 3 == 0:
                errors.append({
                    "priority": "CRITICAL",
                    "category": "ÉTAT DESCRIPTIF ANNEXE E",
                    "title": "Températures de Service Minimale & Maximale Non Renseignées sur l'Annexe E",
                    "article": "Procédure ARH P-CTE-1 (Annexe E) / Décret 21-261",
                    "action_required": "Compléter impérativement les plages de température de service et d'épreuve sur la fiche Annexe E."
                })

            input_text = (
                f"DOSSIER TECHNIQUE ARH - TÉ À BARREAUX (BARRED TEE GA DRAWING)\n"
                f"Projet: {proj} | Repère: {tag} | Dimension: {dn}\"x{branch_dn}\" Class {cls}\n"
                f"Matériau Corps: ASTM A350 LF2 | Matériau Barreaux: Non spécifié dans le cartouche\n"
                f"Fiche Annexe E: Transmise mais cases Températures laissées vides\n"
                f"Pression Épreuve: 153 bar"
            )
            output_obj = {
                "decision": "NON CONFORME (RÉSERVES SUR PLAN ET ANNEXE E)",
                "compliance_score": 40.0,
                "anomalies_count": len(errors),
                "anomalies": errors
            }

        dataset.append({
            "instruction": system_instruction,
            "input": input_text,
            "output": json.dumps(output_obj, ensure_ascii=False, indent=2)
        })

    # ──────────────────────────────────────────────────────────────────────────
    # 6. PILIER 6 : ADMINISTRATIF, LÉGALISATION & P-CTE-1 (150 CAS)
    # ──────────────────────────────────────────────────────────────────────────
    for i in range(150):
        proj = random.choice(projects)
        country = random.choice(["Italie", "Allemagne", "France", "Corée du Sud", "Japon", "Émirats Arabes Unis"])
        sub = random.choice(subcontractors)
        
        is_compliant = (i % 4 == 0)
        if is_compliant:
            input_text = (
                f"AUDIT ADMINISTRATIF & LÉGALISATION ARH - CONTRÔLE D'AUTHENTICITÉ\n"
                f"Projet: {proj} | Fabricant Étranger: {sub} ({country})\n"
                f"Lettre de Demande d'Avis de Conformité (Annexe B P-CTE-1): Signée par le Directeur de Projet\n"
                f"Visa Chambre de Commerce Locale ({country}): Apposé avec cachet sec original\n"
                f"Légalisation Consulat Général d'Algérie: Tampon officiel et timbre consulaire présents et authentifiés\n"
                f"Agrément Ministériel du Bureau de Contrôle Tiers: En cours de validité (Décret 24-278)\n"
                f"État Descriptif Annexe E: Signé conjointement par le Fabricant et le Bureau Tiers Habilité"
            )
            output_obj = {
                "decision": "CONFORME (DOSSIER ADMINISTRATIF COMPLET & LÉGALISÉ)",
                "compliance_score": 100.0,
                "anomalies_count": 0,
                "anomalies": []
            }
        else:
            errors = []
            if i % 2 == 0:
                errors.append({
                    "priority": "CRITICAL",
                    "category": "LÉGALISATION CONSULAIRE",
                    "title": f"Défaut de Légalisation par le Consulat d'Algérie ({country}) sur les Certificats d'Origine",
                    "article": "Décret présidentiel & Procédure ARH P-CTE-1 (Exigence Pièces Étrangères)",
                    "action_required": "Faire viser et légaliser l'ensemble des certificats d'usine originaux par le Consulat d'Algérie territorialement compétent."
                })
            if i % 3 == 0:
                errors.append({
                    "priority": "CRITICAL",
                    "category": "DOCUMENTS RÉGLEMENTAIRES OBLIGATOIRES",
                    "title": "Lettre de Demande d'Avis sur la Conformité (Annexe B) Manquante",
                    "article": "Procédure ARH P-CTE-1 (Article 4.1)",
                    "action_required": "Transmettre la lettre officielle de demande d'avis sur la conformité signée par le maître d'ouvrage."
                })

            input_text = (
                f"AUDIT ADMINISTRATIF ARH - CONTRÔLE D'AUTHENTICITÉ\n"
                f"Projet: {proj} | Fabricant: {sub} ({country})\n"
                f"Certificats transmis avec cachet usine uniquement (Absence de visa Consulat d'Algérie)\n"
                f"Lettre Annexe B: Non jointe au dossier préliminaire"
            )
            output_obj = {
                "decision": "NON CONFORME (REJET ADMINISTRATIF IMMÉDIAT)",
                "compliance_score": 20.0,
                "anomalies_count": len(errors),
                "anomalies": errors
            }

        dataset.append({
            "instruction": system_instruction,
            "input": input_text,
            "output": json.dumps(output_obj, ensure_ascii=False, indent=2)
        })

    # Mélanger pour un entraînement homogène
    random.shuffle(dataset)

    # Sauvegarder en JSONL
    with open(output_path, "w", encoding="utf-8") as f:
        for item in dataset:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Dataset de {len(dataset)} cas d'entraînement ARH généré avec succès dans: {output_path}")
    return len(dataset)


if __name__ == "__main__":
    count = generate_1500_dataset("d:/DATA BASE IA/dataset_arh_1500.jsonl")
    print(f"Total exemples générés : {count}")
