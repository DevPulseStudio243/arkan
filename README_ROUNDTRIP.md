# ARKAN — Module Lecteur de Plans (IA) & Convertisseur DWG/DXF

Bienvenue dans le bundle officiel du **Module Lecteur de Plans (IA)** d'ARKAN.
Ce package regroupe l'ensemble des moteurs d'ingestion vectorielle de schémas d'ingénierie et de tuyauterie (P&ID / PFD / Isométriques), la conversion automatique des plans AutoCAD DWG vers DXF, l'extraction vectorielle géométrique et sémantique à deux étages, le clustering spatial des équipements et la génération de schémas simplifiés interactifs enrichis de bulles cliquables.

---

## 1. Inventaire des Fichiers & Rôle de Chaque Composant

| Fichier / Dossier | Rôle & Description Technique |
|---|---|
| `dwg_converter.py` | **Convertisseur multi-moteurs DWG vers DXF** : convertit de manière autonome et résiliente via LibreDWG (embarqué), Acme CAD Converter, AutoCAD `accoreconsole`, ODA File Converter ou automatisation COM. |
| `dxf_pid_parser.py` | **Parseur vectoriel P&ID à 2 étages** : <br>• *Étage 1* : Extraction brute des primitives géométriques (lignes, arcs, textes, blocs, calques, connectivité spatiale).<br>• *Étage 2* : Réconciliation sémantique (lignes de process, instruments, vannes, boucles, cartouche). |
| `pid_equipment_blocks.py` | **Clustering spatial d'équipements & signatures MD5** : Regroupe les géométries libres (lignes, cercles, rectangles) formant un équipement sans bloc nommé, calcule des empreintes MD5 pour la déduplication et l'apprentissage de formes. |
| `pid_schematic.py` | **Générateur de schémas vectoriels simplifiés & bulles interactives** : Reconstruit un rendu SVG/Canvas haute lisibilité avec codes couleurs normalisés par fluide (eau, hydrocarbure, vapeur, gaz...) et bulles de survol dynamiques. |
| `pid_analyzer.py` | **Moteur principal d'analyse P&ID** : Orchestre l'analyse complète, intègre les règles métier de tuyauterie, la détection des diamètres/spécifications et la structuration des nomenclatures (MTO / BOM). |
| `plan_item_grounder.py` | **Moteur d'ancrage sémantique** : Relie chaque symbole ou tag extrait aux référentiels normatifs EPC et aux modèles de classification d'ARKAN. |
| `autocad_worker.py` | **Worker COM AutoCAD direct** : Permet la conversion headless native si AutoCAD est actif sur le poste hôte. |
| `pid_viewer.py` | **Visualiseur de P&ID PDF** (nécessite PyMuPDF, `circuit_graph.py` (fourni) et `piping_topology_tracer.py` (fournis) : Générateur de pages HTML interactives avec surbrillance dynamique de circuits complets au clic. |
| `arh_pid_topology_engine.py` | **Moteur topologique & d'audit de sécurité procédé** : Modélise le graphe orienté sous NetworkX et audite la conformité intrinsèque (normes API 520, API 521, ISO 10418). |
| `dwg_iso_extractor.py` | **Extracteur isométrique DWG** : Spécialisé dans les plans de tuyauterie isométrique (spools, soudures, coudes). |
| `dxf_extractor.py` | **Extracteur DXF de bas niveau** : Parsing direct des primitives géométriques avec `ezdxf`. |
| `arkan-ui.html` | **Interface utilisateur complète** : Intègre l'onglet *Lecteur de Plans (IA)*, le visualiseur vectoriel interactif, la table de nomenclature, le volet des lignes de tuyauterie et les bulles d'analyse. |
| `bin/cad/` | **Binaires autonomes LibreDWG** : Contient `dwg2dxf.exe` et ses dépendances DLL (`libredwg-0.dll`, etc.) pour une conversion DWG sans dépendance externe sous Windows. |
| `tests/` | **Suite de validation automatisée** (`test_dxf_pid_pipeline.py`, `test_pid_schematic.py`, `test_pid_analyzer_dxf_integration.py`). |
| `samples/` | **Jeux d'exemples prêts à l'emploi** : Fichier P&ID DWG réel et fichier DXF synthétique pour tests immédiats. |

---

## 2. Architecture du Flux de Données

```
 ┌───────────────────────┐
 │   Plan DWG (AutoCAD)  │
 └──────────┬────────────┘
            │
            ▼ [dwg_converter.py / bin/cad/dwg2dxf.exe]
 ┌───────────────────────┐
 │       Plan DXF        │
 └──────────┬────────────┘
            │
            ▼ [dxf_pid_parser.py]
    ┌───────┴────────────────────────┐
    │                                │
    ▼ (Étage 1 - Géométrique)        ▼ (Étage 2 - Sémantique)
 ┌─────────────────────┐         ┌────────────────────────┐
 │      raw.json       │         │     semantic.json      │
 │ • Primitives pures  │         │ • Lignes de process    │
 │ • Calques & Textes  │         │ • Vannes & Instruments │
 │ • Boîtes englobantes│         │ • Cartouche / Metadata │
 └──────────┬──────────┘         └───────────┬────────────┘
            │                                │
            └────────────────┬───────────────┘
                             │
     ┌───────────────────────┼────────────────────────┐
     │                       │                        │
     ▼                       ▼                        ▼
[pid_equipment_blocks] [pid_schematic.py] [arh_pid_topology_engine]
Clustering spatial &   Schéma SVG annoté  Audit sécurité procédé
Empreintes MD5 formes  Bulles interactives Graphe NetworkX (API 520)
     │                       │                        │
     └───────────────────────┼────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  arkan-ui.html  │
                    │ Visualiseur IA  │
                    │ & Nomenclature  │
                    └─────────────────┘
```

---

## 3. Installation des Dépendances

Dans un environnement Python 3.10 ou supérieur :

```bash
pip install ezdxf networkx pytest
# optionnels : cairosvg (rendu PNG des planches), pymupdf (extraction PDF / pid_viewer)
```

> `scikit-learn` a ete retire : aucun module ne l'importe.

> **Note Windows :** Le dossier `bin/cad/` contient `dwg2dxf.exe` et ses DLL (Windows uniquement ; hors Windows, installer `dwg2dxf` de LibreDWG et le mettre sur le PATH). Le DXF produit est maintenant **valide** (relu avec ezdxf) avant d'etre accepte, et mis en cache par contenu dans `cad_cache/dxf/` (variable `ARKAN_CAD_CACHE`, timeout `ARKAN_DWG_TIMEOUT`).

---

## 4. Guide d'Exécution Rapide

### 4.1 Convertir un fichier DWG en DXF
```bash
python dwg_converter.py samples/sample_pid.dwg sortie.dxf
```

### 4.2 Analyser un plan DXF ou DWG (Extraction 2 étages)
```bash
python dxf_pid_parser.py samples/synthetic_pid.dxf resultat_pid/
```
Cette commande génère automatiquement dans `resultat_pid/` :
- `raw.json` : entités vectorielles brutes (blocs imbriqués résolus, coordonnées monde).
- `semantic.json` : équipements, vannes, instruments, lignes (runs issus de la géométrie), `line_entries` (format de `arh_pid_topology_engine`), boucles, avertissements.
- `digest.json` : vue compacte pour ARKAN / LLM.

Confirmations humaines des équipements dessinés sans bloc :
```bash
python pid_equipment_blocks.py resultat_pid/ blocs/        # produit blocs/equipment_review.html
# ouvrir equipment_review.html, confirmer / corriger / fusionner, exporter equipment_review.json
python dxf_pid_parser.py plan.dxf resultat_pid/ --equipment-review equipment_review.json
```
Tout équipement non issu d'un bloc reste `review_status: "to_confirm"` (avertissement `EQUIPMENT_TO_CONFIRM`) tant qu'un humain ne l'a pas validé.

### 4.3 Générer un schéma interactif avec bulles
```python
from pid_schematic import render_schematic
from dxf_pid_parser import parse_file

# Parsing
data = parse_file("samples/synthetic_pid.dxf")
# Génération SVG enrichi
svg_output = render_schematic(data["semantic"])
with open("schema_annote.svg", "w", encoding="utf-8") as f:
    f.write(svg_output)
```

### 4.4 Ouvrir l'Interface Utilisateur
L'interface a besoin du backend ARKAN (`API_BASE`, par défaut `http://127.0.0.1:8000` en `file://`) et des 4 fichiers de `static/` (fournis ici : `pdf.min.js`, `pdf.worker.min.js`, `ie_plan_viewer.js`, `ie_triangulation.js`). Ils sont référencés en `/static/...` : servez le dossier à cette adresse (un double-clic en `file://` ne les trouvera pas). Avec le backend :
```bash
python -m http.server 8000
```
Puis accédez à l'onglet "Lecteur de Plans (IA)".

---

## 5. Exécution des Tests de Validation

Pour vérifier l'intégrité de l'ensemble du pipeline :
```bash
pytest tests/ -v
```
Tous les tests doivent afficher `PASSED` (43 tests : convertisseur, parseur, équipements, schémas, moteur topologique, intégration `pid_analyzer`). Ils n'ont besoin d'aucun fichier externe.


Tests JavaScript : voir `tests/js/README.txt` (jsdom).


## raw.json v2 sans perte et preuve d'exactitude

`raw.json` décrit chaque entité par ses paramètres natifs (angles d'arc, bulge, ellipses, splines, hachures, SOLID,
textes, styles, matrices d'insertion) en coordonnées monde, model space **et** paper space (champ `space`), avec un
rapport `coverage`. Pour vérifier qu'il reconstitue le dessin :

```bash
python raw_roundtrip.py resultat_pid/raw.json plan.dxf verification/
# -> EXACT ou la liste des écarts ; écrit reconstructed.dxf, roundtrip_report.json, roundtrip_diff.png
```

Résultat sur le plan réel : `resultats_plan_reel/roundtrip_report.json`. Voir `CORRECTIONS.md` (troisième passe) pour les limites.
