#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trainer_synthetic.py
====================
Génère des données d'entraînement synthétiques Oil & Gas
pour fine-tuner le reranker, les embeddings et le classifieur.

Produit :
  - training_data/reranker_pairs.jsonl     : paires (query, pos, neg)
  - training_data/embedding_pairs.jsonl    : paires (anchor, positive, negative)
  - training_data/classifier_samples.jsonl : (texte, label_discipline)
  - training_data/qa_pairs.jsonl           : (question, réponse, source)
"""

import json
import random
import re
import time
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich import box


# ╔══════════════════════════════════════════════════════════════╗
# ║              BASE DE CONNAISSANCES OIL & GAS                 ║
# ╚══════════════════════════════════════════════════════════════╝

# Tags équipements réalistes par discipline
EQUIPMENT_TAGS = {
    "process": [
        ("V-101", "Ballon d'aspiration vertical", "vessel"),
        ("V-102", "Ballon de refoulement horizontal", "vessel"),
        ("V-201", "Séparateur triphasique", "vessel"),
        ("V-301", "Knock-out drum torche", "vessel"),
        ("E-101", "Échangeur gaz/gaz", "exchanger"),
        ("E-201", "Refroidisseur de tête", "exchanger"),
        ("E-301", "Préchauffeur de charge", "exchanger"),
        ("C-101", "Colonne de stabilisation", "column"),
    ],
    "mechanical": [
        ("P-101A/B", "Pompe de charge centrifuge", "pump"),
        ("P-201A/B", "Pompe d'injection d'inhibiteur", "pump"),
        ("K-101", "Compresseur de gaz de tête", "compressor"),
        ("K-201", "Compresseur de recycle", "compressor"),
        ("T-101", "Réservoir de stockage GPL", "tank"),
        ("T-201", "Réservoir de méthanol", "tank"),
        ("F-101", "Filtre à cartouche entrée gaz", "filter"),
    ],
    "instrumentation": [
        ("FT-1001", "Transmetteur de débit gaz entrant", "transmitter"),
        ("PT-2001", "Transmetteur de pression HP", "transmitter"),
        ("TT-3001", "Transmetteur de température E-101", "transmitter"),
        ("LT-4001", "Transmetteur de niveau V-201", "transmitter"),
        ("FV-1001", "Vanne de contrôle débit recycle", "control_valve"),
        ("PV-2001", "Vanne de contrôle pression", "control_valve"),
        ("SDV-001", "Vanne d'arrêt d'urgence entrée", "shutdown_valve"),
        ("PSV-101", "Soupape de sécurité V-101", "safety_valve"),
    ],
    "electrical": [
        ("M-101", "Moteur pompe P-101A/B", "motor"),
        ("M-201", "Moteur compresseur K-101", "motor"),
        ("TR-101", "Transformateur principal HTA/BT", "transformer"),
        ("MCC-101", "Armoire de commande moteurs zone A", "mcc"),
        ("UPS-101", "Alimentation sans interruption contrôle", "ups"),
    ],
    "safety": [
        ("PSV-101", "Soupape sécurité V-101 – 28 bar", "psv"),
        ("PSV-201", "Soupape sécurité E-201 – 15 bar", "psv"),
        ("PSV-301", "Soupape sécurité C-101 – 20 bar", "psv"),
        ("BDV-001", "Vanne de dépressurisation urgence", "bdv"),
        ("ESDV-001", "Vanne arrêt d'urgence ligne principale", "esdv"),
    ],
}

# Paramètres process réalistes
PROCESS_PARAMS = {
    "pressions": [
        ("4 barg", "pression d'aspiration"),
        ("28 barg", "pression de refoulement"),
        ("15 barg", "pression de service E-201"),
        ("20 barg", "pression de design C-101"),
        ("50 barg", "pression de test hydrostatique"),
        ("1.5 barg", "pression de la torche"),
        ("3.5 barg", "pression air instrument"),
    ],
    "temperatures": [
        ("45°C", "température d'entrée gaz"),
        ("120°C", "température de sortie E-101"),
        ("-20°C", "température de design basse"),
        ("150°C", "température de design haute"),
        ("200°C", "température maximale admissible C-101"),
        ("38°C", "température ambiante design"),
        ("65°C", "température de service T-101"),
    ],
    "debits": [
        ("2.035 MMSCMD", "débit nominal gaz"),
        ("1.850 MMSCMD", "débit minimum opérationnel"),
        ("2.200 MMSCMD", "débit maximum de design"),
        ("150 m³/h", "débit liquide P-101"),
        ("85 m³/h", "débit condensat V-201"),
        ("500 Nm³/h", "débit air instrument"),
    ],
}

# Normes Oil & Gas
NORMES = [
    ("API 610", "Centrifugal Pumps for Petroleum"),
    ("API 617", "Centrifugal Compressors for Petroleum"),
    ("API 520", "Sizing of Pressure-Relieving Devices"),
    ("API 521", "Pressure-relieving and Depressuring Systems"),
    ("API 650", "Welded Steel Tanks for Oil Storage"),
    ("ASME VIII Div.1", "Pressure Vessels"),
    ("ASME B31.3", "Process Piping"),
    ("IEC 61511", "Safety Instrumented Systems"),
    ("ATEX Directive", "Equipment in explosive atmospheres"),
    ("ISO 10418", "Offshore Production Facilities"),
    ("NFPA 72", "National Fire Alarm and Signaling Code"),
    ("API 5L", "Specification for Line Pipe"),
    ("TEMA Class C/R/B", "Shell and Tube Heat Exchangers"),
]

# Matériaux
MATERIAUX = [
    ("ASTM A106 Gr.B", "acier carbone tuyauterie"),
    ("ASTM A516 Gr.70", "acier carbone vessels"),
    ("ASTM A312 TP316L", "inox austénitique tuyauterie"),
    ("ASTM A240 316L", "inox austénitique plaques"),
    ("Inconel 625", "alliage haute température"),
    ("Duplex 2205", "acier duplex service corrosif"),
    ("CS + 3mm CA", "acier carbone avec surépaisseur corrosion"),
]

# Classes de tuyauterie réalistes
PIPE_CLASSES = [
    ("A1A", "ASTM A106 Gr.B, PN50, CS, service gaz haute pression"),
    ("A2A", "ASTM A106 Gr.B, PN20, CS, service gaz basse pression"),
    ("B1A", "ASTM A312 316L, PN50, SS, service corrosif"),
    ("C1A", "ASTM A106 Gr.B, PN10, CS, service eau"),
]

# Disciplines pour le classifieur
DISCIPLINES = {
    "process": {
        "keywords": ["PFD", "P&ID", "HMB", "bilans matière", "procédé",
                     "conditions opératoires", "débit", "pression de service",
                     "température nominale", "simulation HYSYS", "PROII"],
        "templates": [
            "Le débit nominal de gaz en entrée du séparateur {tag} est de {debit}. "
            "Les conditions opératoires normales sont : pression {pression}, température {temp}.",

            "Selon le P&ID document n° D-{num}-1302-001, le séparateur {tag} "
            "traite un flux gazeux à {pression} et {temp}. La vanne {valve} "
            "contrôle le débit de {debit}.",

            "Le bilan matière (HMB) indique une pression de design de {pression} "
            "et une température de design de {temp} pour l'échangeur {tag}. "
            "Le débit de service est {debit}.",
        ],
    },
    "mechanical": {
        "keywords": ["datasheet", "ASME", "TEMA", "pompe", "compresseur",
                     "échangeur", "ballon", "vessel", "MAWP", "corrosion allowance",
                     "matériau", "nozzle", "flange rating"],
        "templates": [
            "FICHE TECHNIQUE ÉQUIPEMENT\n"
            "Tag: {tag} | Type: {type}\n"
            "Pression de design: {pression} | Température de design: {temp}\n"
            "Matériau: {materiau} | Norme: {norme}\n"
            "Corrosion allowance: 3 mm | MAWP: {pression}",

            "Le compresseur {tag} est conforme à la norme {norme}. "
            "Débit nominal: {debit}. Pression de refoulement: {pression}. "
            "Température de sortie: {temp}. Matériau carter: {materiau}.",

            "Selon la datasheet D-{num}-1201-015, l'échangeur {tag} de type "
            "TEMA Class R est conçu pour une pression de {pression} et "
            "une température de {temp}. Matériau tubes: {materiau}.",
        ],
    },
    "piping": {
        "keywords": ["isométrique", "classe de tuyauterie", "line list",
                     "stress analysis", "CAESAR", "support", "bride", "flange",
                     "vanne", "spécification tuyauterie"],
        "templates": [
            "Ligne {num}\" - {classe} - service gaz haute pression.\n"
            "Matériau: {materiau} conformément à {norme}.\n"
            "Pression de design: {pression} | Température: {temp}\n"
            "Vanne d'isolement: {tag}",

            "L'isométrique ISO-{num} montre la connexion entre {tag1} et {tag2}. "
            "Spécification de tuyauterie: classe {classe}. "
            "Température de design: {temp}, pression: {pression}. "
            "Matériau: {materiau}.",

            "LISTE DES LIGNES (LINE LIST)\n"
            "Ligne: {num}\"-P-{num2}-{classe} | P. design: {pression} | "
            "T. design: {temp} | Fluide: gaz naturel | Classe ISO: {classe}",
        ],
    },
    "instrumentation": {
        "keywords": ["instrument datasheet", "boucle de régulation", "SIL",
                     "DCS", "PLC", "4-20mA", "HART", "Fieldbus", "capteur",
                     "transmetteur", "calibration", "SIS"],
        "templates": [
            "FICHE TECHNIQUE INSTRUMENT\n"
            "Tag: {tag} | Type: Transmetteur de pression\n"
            "Plage de mesure: 0 à {pression} | Signal: 4-20mA HART\n"
            "Classification zone: Zone 1 Gaz IIC T3 | Certification ATEX\n"
            "Connexion process: 1/2\" NPT | Matériau membrane: 316L",

            "La boucle {tag} assure la régulation de pression sur {equip}. "
            "Le transmetteur {tag_t} mesure en plage 0-{pression}, "
            "le signal 4-20mA HART est traité par le DCS. "
            "Vanne de régulation: {tag_v}, Cv calculé: 12.5.",

            "Selon l'étude SIL, la fonction SIF-{num} (vanne {tag}) "
            "requiert un niveau SIL 2. Le PFD visé est 1×10⁻³. "
            "Architecture choisie: 1oo2 avec diagnostics.",
        ],
    },
    "electrical": {
        "keywords": ["SLD", "MCC", "câble", "moteur", "transformateur",
                     "classification de zone", "ATEX", "puissance installée",
                     "chute de tension", "court-circuit"],
        "templates": [
            "Le moteur {tag} d'une puissance de {puissance} kW alimente "
            "la pompe P-101A. Tension d'alimentation: 380V 3ph 50Hz. "
            "Démarrage: démarreur progressif. Câble d'alimentation: "
            "{materiau}, section 35mm², longueur 45m.",

            "SINGLE LINE DIAGRAM — SLD-{num}\n"
            "Transformateur {tag}: {puissance} kVA, 11kV/400V, "
            "groupe Dyn11. MCC associé: {equip}.\n"
            "Puissance installée: {puissance2} kW | Puissance absorbée: {puissance3} kW",

            "Zone ATEX: Zone 1 — gaz IIC T3 — présence gaz explosive possible.\n"
            "Tous les équipements électriques dans cette zone doivent être "
            "certifiés Ex d IIC T3 Gb minimum, conformément à la directive ATEX "
            "et à la norme IEC 60079-1.",
        ],
    },
    "safety": {
        "keywords": ["HAZOP", "HAZID", "LOPA", "SIL", "PSV", "torche",
                     "étude de danger", "scénario accidentel", "barrière",
                     "sécurité incendie", "explosion", "permis de travail"],
        "templates": [
            "HAZOP — Nœud {num}: Ligne d'alimentation {tag}\n"
            "Déviation: Pas de débit | Cause: Vanne {tag2} fermée\n"
            "Conséquence: Surchauffe {equip}, pression > MAWP\n"
            "Barrière existante: {tag3} coupe alimentation à {pression}\n"
            "Recommandation: Ajouter alarme basse pression PT-{num2}",

            "La PSV {tag} est dimensionnée selon API 520/521. "
            "Débit de dimensionnement: 5000 kg/h (cas incendie). "
            "Pression de tarage: {pression}. Contre-pression maxi: 10%.\n"
            "Matériau: {materiau}. Norme: {norme}.",

            "Résultat LOPA — Scénario: débordement réservoir {tag}\n"
            "Fréquence initiateur: 0.1/an\n"
            "IPL1 (Alarme niveau haute): PFD 0.1\n"
            "IPL2 (Vanne {tag2} sur signal niveau TH): PFD 0.01\n"
            "Fréquence résiduelle: 10⁻⁴/an — SIL 1 requis",
        ],
    },
    "planning": {
        "keywords": ["planning", "schedule", "Primavera", "jalons", "milestone",
                     "ingénierie", "approvisionnement", "construction",
                     "mise en service", "démarrage"],
        "templates": [
            "MASTER SCHEDULE — PROJET BOOSTING LDBP5\n"
            "Jalon J1: Approbation FEED — Date: 01/03/2025\n"
            "Jalon J2: Commande équipements longs délais — 15/04/2025\n"
            "Jalon J3: Début travaux terrain — 01/07/2025\n"
            "Jalon J4: Mechanical Completion — 15/12/2025\n"
            "Jalon J5: Démarrage — 01/02/2026\n"
            "Durée totale: 24 mois",

            "Activité A1010: Engineering de base (FEED)\n"
            "Durée: 90 jours | Début: 01/03/2025 | Fin: 30/05/2025\n"
            "Ressources: Chef de projet + 4 ingénieurs disciplines\n"
            "Livrable: Dossier FEED approuvé par SONATRACH",

            "Phase Procurement (Approvisionnement):\n"
            "- Compresseur K-101: délai livraison 14 mois\n"
            "- Échangeurs E-101/201: délai 6 mois\n"
            "- Équipements électriques: délai 4 mois\n"
            "- Tuyauterie et robinetterie: délai 3 mois\n"
            "Date limite commande compresseur: 15/04/2025",
        ],
    },
}

# Questions typiques par type
QUESTION_TEMPLATES = {
    "equipment_spec": [
        "Quelle est la pression de design de {tag} ?",
        "Quelles sont les caractéristiques de {tag} ?",
        "Quel est le matériau de construction de {tag} ?",
        "Quelle norme s'applique à {tag} ?",
        "Donnez les paramètres opératoires de {tag}.",
        "Quelle est la température de service de {tag} ?",
        "Quel est le débit nominal de {tag} ?",
    ],
    "norm_query": [
        "Quelle norme régit les compresseurs centrifuges Oil & Gas ?",
        "Quel code ASME s'applique aux vessels sous pression ?",
        "Quelle est la norme de dimensionnement des PSV ?",
        "Comment sont dimensionnées les soupapes de sécurité selon l'API ?",
    ],
    "process_query": [
        "Quelles sont les conditions opératoires normales ?",
        "Quel est le débit nominal de gaz ?",
        "Quelle est la pression d'aspiration du compresseur ?",
        "Quelle est la température de design maximale ?",
    ],
    "safety_query": [
        "Quelle est la pression de tarage de la PSV {tag} ?",
        "Quels sont les résultats HAZOP pour le nœud {num} ?",
        "Quel niveau SIL est requis pour la fonction {tag} ?",
        "Comment fonctionne le système d'arrêt d'urgence ?",
    ],
}

# Réponses négatives (passages non pertinents)
NEGATIVE_PASSAGES = [
    "Le planning de maintenance préventive est établi selon les recommandations du fabricant.",
    "Le rapport mensuel de production indique un taux d'utilisation de 94.5%.",
    "La réunion de coordination a eu lieu le 15 mars avec 12 participants.",
    "Les procédures HSE doivent être respectées en toutes circonstances sur le chantier.",
    "Le permis de travail doit être signé avant tout début d'intervention.",
    "La liste de matériaux (BOM) est en cours de finalisation par l'équipe engineering.",
    "Le rapport d'avancement hebdomadaire sera transmis chaque vendredi.",
    "La formation sécurité est obligatoire pour tout nouveau personnel entrant sur site.",
    "Les équipements sont soumis à inspection réglementaire tous les 5 ans.",
    "Le contrat EPC prévoit une garantie de 24 mois après réception.",
    "Le plan de communication projet a été approuvé par le client.",
    "Les travaux de génie civil sont planifiés pour le T2 2025.",
    "La revue HAZOP est planifiée pour la semaine du 10 juin.",
    "Le budget révisé a été soumis pour approbation à la direction.",
    "Les normes locales algériennes s'appliquent en complément des normes internationales.",
]


# ╔══════════════════════════════════════════════════════════════╗
# ║                  GÉNÉRATEUR PRINCIPAL                        ║
# ╚══════════════════════════════════════════════════════════════╝

class SyntheticDataGenerator:

    def __init__(self, data_dir: Path, console: Console):
        self.data_dir = data_dir
        self.console  = console
        random.seed(42)

    def _rand_tag(self, discipline=None):
        """Retourne un tag aléatoire."""
        if discipline and discipline in EQUIPMENT_TAGS:
            tags = EQUIPMENT_TAGS[discipline]
        else:
            tags = [t for ts in EQUIPMENT_TAGS.values() for t in ts]
        tag, name, typ = random.choice(tags)
        return tag, name, typ

    def _rand_param(self, param_type):
        """Retourne un paramètre process aléatoire."""
        return random.choice(PROCESS_PARAMS[param_type])[0]

    def _fill_template(self, template: str, discipline: str = None) -> str:
        """Remplace les placeholders dans un template."""
        tag, name, typ = self._rand_tag(discipline)
        tag2, name2, _ = self._rand_tag()
        tag3, name3, _ = self._rand_tag("safety")
        tag_v, _, _ = self._rand_tag("instrumentation")
        tag_t, _, _ = self._rand_tag("instrumentation")
        norme, _ = random.choice(NORMES)
        materiau, _ = random.choice(MATERIAUX)
        classe, _ = random.choice(PIPE_CLASSES)

        replacements = {
            "{tag}": tag, "{tag1}": tag, "{tag2}": tag2, "{tag3}": tag3,
            "{tag_v}": tag_v, "{tag_t}": tag_t,
            "{type}": typ, "{equip}": name, "{name}": name,
            "{pression}": self._rand_param("pressions"),
            "{temp}": self._rand_param("temperatures"),
            "{debit}": self._rand_param("debits"),
            "{norme}": norme,
            "{materiau}": materiau,
            "{classe}": classe,
            "{num}": str(random.randint(100, 999)),
            "{num2}": str(random.randint(1000, 9999)),
            "{valve}": tag_v,
            "{puissance}": str(random.choice([22, 37, 55, 75, 110, 160, 200, 315])),
            "{puissance2}": str(random.randint(500, 2000)),
            "{puissance3}": str(random.randint(300, 1500)),
        }

        result = template
        for key, val in replacements.items():
            result = result.replace(key, val)
        return result

    # ── 1. Données Reranker ───────────────────────────────────

    def generate_reranker_pairs(self, n: int = 800) -> list:
        """
        Génère des triplets (query, positive_passage, negative_passage)
        pour fine-tuner le cross-encoder.
        """
        pairs = []

        for i in range(n):
            # Choisir une discipline aléatoire
            disc = random.choice(list(DISCIPLINES.keys()))
            config = DISCIPLINES[disc]

            # Passage positif : document réel de cette discipline
            pos_template = random.choice(config["templates"])
            positive = self._fill_template(pos_template, disc)

            # Question pertinente
            tag, _, _ = self._rand_tag(disc)
            q_templates = random.choice(list(QUESTION_TEMPLATES.values()))
            q_template = random.choice(q_templates)
            query = q_template.format(
                tag=tag,
                num=str(random.randint(100, 999))
            )

            # Passage négatif : aléatoire d'une autre discipline ou passage générique
            use_other_disc = random.random() > 0.5
            if use_other_disc:
                other_disc = random.choice([d for d in DISCIPLINES if d != disc])
                neg_template = random.choice(DISCIPLINES[other_disc]["templates"])
                negative = self._fill_template(neg_template, other_disc)
            else:
                negative = random.choice(NEGATIVE_PASSAGES)

            pairs.append({
                "query":    query,
                "positive": positive,
                "negative": negative,
                "discipline": disc,
            })

        return pairs

    # ── 2. Données Embeddings ─────────────────────────────────

    def generate_embedding_pairs(self, n: int = 600) -> list:
        """
        Génère des triplets anchor/positive/negative pour contrastive learning.
        """
        pairs = []

        for i in range(n):
            disc = random.choice(list(DISCIPLINES.keys()))
            config = DISCIPLINES[disc]

            # Anchor : une question technique
            tag, _, _ = self._rand_tag(disc)
            q_type = random.choice(list(QUESTION_TEMPLATES.keys()))
            anchor = random.choice(QUESTION_TEMPLATES[q_type]).format(
                tag=tag,
                num=str(random.randint(100, 999))
            )

            # Positive : un passage répondant à cette question
            pos_template = random.choice(config["templates"])
            positive = self._fill_template(pos_template, disc)

            # Hard negative : passage d'une discipline proche
            close_discs = {
                "process":        ["mechanical", "piping"],
                "mechanical":     ["process", "piping"],
                "piping":         ["mechanical", "process"],
                "instrumentation":["electrical", "safety"],
                "electrical":     ["instrumentation", "safety"],
                "safety":         ["process", "instrumentation"],
                "planning":       ["general"],
            }
            close = close_discs.get(disc, list(DISCIPLINES.keys()))
            hard_neg_disc = random.choice(close) if close else disc
            hard_neg_template = random.choice(
                DISCIPLINES.get(hard_neg_disc, DISCIPLINES[disc])["templates"]
            )
            negative = self._fill_template(hard_neg_template, hard_neg_disc)

            pairs.append({
                "anchor":   anchor,
                "positive": positive,
                "negative": negative,
                "discipline": disc,
            })

        return pairs

    # ── 3. Données Classifieur ────────────────────────────────

    def generate_classifier_samples(self, n_per_class: int = 150) -> list:
        """
        Génère des exemples (texte, label_discipline) pour le classifieur.
        """
        samples = []

        for disc, config in DISCIPLINES.items():
            for i in range(n_per_class):
                template = random.choice(config["templates"])
                text = self._fill_template(template, disc)
                # Ajouter quelques mots-clés de la discipline
                extra_kw = random.sample(config["keywords"],
                                         min(3, len(config["keywords"])))
                text = text + " " + " ".join(extra_kw)
                samples.append({"text": text, "label": disc})

        random.shuffle(samples)
        return samples

    # ── 4. Paires Q/R complètes ───────────────────────────────

    def generate_qa_pairs(self, n: int = 300) -> list:
        """
        Génère des paires question/réponse avec référence pour évaluation.
        """
        qa = []

        for i in range(n):
            disc = random.choice(list(DISCIPLINES.keys()))
            config = DISCIPLINES[disc]

            tag, name, typ = self._rand_tag(disc)
            pression = self._rand_param("pressions")
            temp = self._rand_param("temperatures")
            debit = self._rand_param("debits")
            norme, _ = random.choice(NORMES)

            # Créer le contexte
            pos_template = random.choice(config["templates"])
            context = self._fill_template(pos_template, disc)

            # Créer une question et réponse cohérentes
            qa_pairs_for_disc = [
                (
                    f"Quelle est la pression de design de {tag} ?",
                    f"La pression de design de {tag} ({name}) est {pression}.",
                ),
                (
                    f"Quel matériau est utilisé pour {tag} ?",
                    f"Le matériau de construction de {tag} est conforme à la norme {norme}.",
                ),
                (
                    f"Quelle norme s'applique à {tag} de type {typ} ?",
                    f"Pour les équipements de type {typ}, la norme applicable est {norme}.",
                ),
                (
                    f"Quelle est la température de service de {tag} ?",
                    f"La température de service de {tag} est de {temp}.",
                ),
            ]

            q, a = random.choice(qa_pairs_for_disc)
            qa.append({
                "question":   q,
                "answer":     a,
                "context":    context,
                "discipline": disc,
                "source":     f"synthetic_{disc}_{i:04d}.pdf",
                "grounding_ratio": 0.9,
            })

        return qa

    # ── Sauvegarde ────────────────────────────────────────────

    def save_jsonl(self, data: list, filename: str):
        path = self.data_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return path

    def save_json(self, data, filename: str):
        path = self.data_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    # ── Point d'entrée ────────────────────────────────────────

    def run(self):
        self.console.print("\n[bold cyan]═══ Génération de données synthétiques Oil & Gas ═══[/bold cyan]\n")

        stats = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:

            # Reranker pairs
            task1 = progress.add_task("[yellow]Triplets reranker...", total=100)
            data = self.generate_reranker_pairs(n=800)
            path = self.save_jsonl(data, "reranker_pairs.jsonl")
            stats["reranker_pairs"] = len(data)
            progress.update(task1, advance=100)
            self.console.print(f"  ✓ {len(data)} triplets reranker → {path.name}")

            # Embedding pairs
            task2 = progress.add_task("[blue]Paires embeddings...", total=100)
            data = self.generate_embedding_pairs(n=600)
            path = self.save_jsonl(data, "embedding_pairs.jsonl")
            stats["embedding_pairs"] = len(data)
            progress.update(task2, advance=100)
            self.console.print(f"  ✓ {len(data)} paires embeddings → {path.name}")

            # Classifier samples
            task3 = progress.add_task("[green]Exemples classifieur...", total=100)
            data = self.generate_classifier_samples(n_per_class=150)
            path = self.save_jsonl(data, "classifier_samples.jsonl")
            stats["classifier_samples"] = len(data)
            progress.update(task3, advance=100)
            self.console.print(f"  ✓ {len(data)} exemples classifieur → {path.name}")

            # QA pairs
            task4 = progress.add_task("[magenta]Paires Q/R...", total=100)
            data = self.generate_qa_pairs(n=300)
            path = self.save_jsonl(data, "qa_pairs.jsonl")
            stats["qa_pairs"] = len(data)
            progress.update(task4, advance=100)
            self.console.print(f"  ✓ {len(data)} paires Q/R → {path.name}")

        # Résumé
        self.console.print()
        table = Table(title="Données générées", box=box.ROUNDED, border_style="cyan")
        table.add_column("Fichier", style="cyan")
        table.add_column("Exemples", style="bold green", justify="right")
        table.add_column("Usage", style="dim")

        usages = {
            "reranker_pairs": "Fine-tuning cross-encoder",
            "embedding_pairs": "Fine-tuning sentence-transformers",
            "classifier_samples": "Entraînement classifieur sklearn",
            "qa_pairs": "Évaluation et test du système",
        }
        for key, count in stats.items():
            table.add_row(f"{key}.jsonl", str(count), usages.get(key, ""))

        self.console.print(table)
        self.console.print(
            f"\n[green]✓ Données sauvegardées dans : {self.data_dir}[/green]\n"
        )

        # Sauvegarder les méta-données
        meta = {
            "generated_at": datetime.now().isoformat(),
            "stats": stats,
            "disciplines": list(DISCIPLINES.keys()),
            "num_equipment_types": sum(len(v) for v in EQUIPMENT_TAGS.values()),
            "num_norms": len(NORMES),
        }
        self.save_json(meta, "generation_meta.json")

        return stats
