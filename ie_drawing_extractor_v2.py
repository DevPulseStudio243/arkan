# Plan d'Implémentation : Résolution de l'Import Multi-Fichiers & Correction du Quantitatif (Dossier 1 - Projet GCB/Sonatrach C2723)

## [Goal Description]
L'utilisateur a signalé deux dysfonctionnements majeurs lors du test avec le dossier `1` situé sur le Bureau (`C:\Users\MSI\Desktop\1`) :
1. **L'importation de plusieurs fichiers ne fonctionne pas** : Lorsqu'on sélectionne ou glisse-dépose plusieurs fichiers à la fois (ex: plan DWG/DXF, carnet de câbles Excel, note de calcul PDF), seul le premier fichier est pris en compte, les autres sont ignorés.
2. **Le quantitatif est totalement erroné** : Le cheminement de câbles ressort à **196 573 mètres (196 km)** au lieu de **196,5 mètres**, et le carnet de câbles extrait **0 câbles** au lieu des 16 câbles réels du projet.

---

## 1. Diagnostic de Cause Racine (Evidence-First sur le Dossier `1`)

L'analyse technique approfondie des 6 fichiers réels du dossier `C:\Users\MSI\Desktop\1` a isolé 4 causes racines exactes :

### Cause Racine n°1 : Le piège d'échelle AutoCAD ($INSUNITS = 6$ mais dessin en millimètres)
- **Constat** : Le fichier DXF `C2723-GCB-000-ELE-PLA-006 Plan de cheminement.dxf` contient dans son en-tête `$INSUNITS = 6` (code AutoCAD pour Mètres).
- **Réalité du dessin** : Toutes les cotes réelles du plan (`DIMENSION`) mesurent `4500`, `5250`, `4000`, `800`, `100` (dimensions de bâtiments, caniveaux et chemins en millimètres).
- **Erreur ARKAN** : Le code a fait confiance aveuglément à `$INSUNITS = 6` (`scale_to_m = 1.0`), multipliant la longueur brute de 393 146 unités par 1.0 (soit 196 573 m après division par 2 pour double-rail) au lieu d'appliquer `scale_to_m = 0.001` (soit **196,57 m**).
- **Facteur d'erreur** : **Exactement 1000× trop grand.**

### Cause Racine n°2 : Échec d'extraction du Carnet de Câbles (`C2723-GCB-000-ELE-LST-001.xlsx`)
- **Constat** : `CableScheduleParser` inspectait uniquement `wb.active`.
- **Réalité du fichier** : La première feuille active est `COUVERTURE` (page de garde administrative). Les 16 câbles réels du projet (`100-EL-001/L1` à `100-EL-012`, pompes `R01-PM-02A`, etc.) se trouvent sur la feuille `page1`.
- **Ambiguïté d'en-tête** : Dans `page1`, la ligne 8 contient `REPÉRE DU CABLE` (colonne 1), mais aussi `REPÉRE` sous `TENANT` (colonne 3) et `REPÉRE` sous `ABOUTISSANT` (colonne 5). La correspondance naïve associait le tag à la colonne 3 (tag de l'armoire `BUS -TGBT-`) au lieu du câble (`100-EL-001`).

### Cause Racine n°3 : Mono-fichier strict dans l'Interface et l'API
- Dans `arkan-ui.html` :
  - `<input type="file" id="ie-file-input">` ne comporte pas l'attribut `multiple`. La boîte de dialogue Windows interdit donc la sélection multiple.
  - Le drag-and-drop `handleIeFileDrop` ne lisait que `e.dataTransfer.files[0]`, ignorant tous les autres fichiers déposés.
- Dans `routes/ie_mto_router.py` :
  - L'endpoint `/ie-mto/calculate` ne reçoit qu'un seul fichier à la fois.

### Cause Racine n°4 : Hardcoding hérité dans `ie_drawing_extractor.py` (Violation Règle 4)
- Découpage artificiel du métré total en 55% de `CDC-100x50` et 45% de `CDC-200x50`.
- Injection en dur de chambres `300-EL-312` et de 8 piquets de terre issus de l'ancien plan de test ROK1.

---

## 2. Solution d'Ingénierie & Plan d'Action Proposé

```mermaid
flowchart TD
    A["Importation Multi-Fichiers (Dossier 1)"] --> B["Classification Automatique des Rôles"]
    
    B --> C["Plan CAO (DWG / DXF / PDF)<br/>C2723-ELE-PLA-006"]
    B --> D["Carnet de Câbles (Excel)<br/>C2723-ELE-LST-001"]
    B --> E["Note de Calcul (PDF/Word)<br/>C2723-ELE-CAL-001"]
    
    C --> F["Détecteur de Plausibilité d'Échelle CAD<br/>Analyse cotations DIMENSION<br/>Médiane > 50 -> scale_to_m = 0.001"]
    F --> G["Métré Physique Certifié<br/>196.57 m (au lieu de 196 km)"]
    
    D --> H["Scanner Multi-Feuilles & Disambiguïsation<br/>Recherche sur 'page1'<br/>'REPÉRE DU CABLE' = Tag Câble"]
    H --> I["16 Câbles Réels Extraits<br/>(100-EL-001 à 100-EL-012)"]
    
    E --> J["Extracteur Note de Calcul PDF<br/>Sections et Chutes de Tension UTE C 15-105"]
    
    G & I & J --> K["Triangulation Totale E&I Conforme<br/>MTO Réel, Sans Hardcoding, Export Master Excel"]
```

---

## Proposed Changes

### Composant 1 : Détecteur Intelligent de Plausibilité d'Échelle CAD

#### [MODIFY] `ie_drawing_extractor.py`
- Implémenter l'algorithme **`verify_drawing_scale_plausibility(doc, insunits)`** :
  - Inspecter les entités `DIMENSION` dans le Model Space.
  - Si des cotes existent et que leur médiane dépasse $50$ (ex: cotes de portes à $800-1000$, pièces à $4000-5000$, voiries à $10000-40000$), le dessin est **certainement en millimètres**, même si `$INSUNITS = 6`.
  - Forcer `scale_to_m = 0.001` et consigner un avertissement d'ingénierie : *"Ajustement d'échelle : dessin en millimètres malgré $INSUNITS=6$ (confirmé par cotes réelles : médiane=800mm)"*.
- Éradiquer le hardcoding :
  - Supprimer le split 55%/45% et qualifier le chemin de câbles depuis les calques réels (`cheminement électrique`).
  - Supprimer l'injection en dur des tags `300-EL-312` et des 8 piquets de terre.

---

### Composant 2 : Parser Multi-Feuilles & Disambiguïsation Carnet de Câbles

#### [MODIFY] `cable_schedule_parser.py`
- Modifier `_parse_excel(path)` pour **scanner l'ensemble des feuilles** du classeur (`wb.sheetnames`), et ne pas s'arrêter à `wb.active` / `COUVERTURE`.
- Améliorer `_find_cs_column_mapping` :
  - Donner la priorité absolue à `"repere_du_cable"` ou `"cable_tag"` sur le mot générique `"repere"`.
  - Gérer les sous-colonnes `TENANT` et `ABOUTISSANT` pour mapper correctement la source (`TD-001`, `BUS -TGBT-`) et la destination (`POMPE R01-PM-02A`).

---

### Composant 3 : Ingestion Multi-Fichiers (Batch Upload)

#### [MODIFY] `routes/ie_mto_router.py`
- Ajouter l'endpoint de lot :
  `POST /ie-mto/calculate-batch`
  - Accepte une liste de fichiers (`files: List[UploadFile] = File(...)`) ou un dossier local.
  - Classifie automatiquement chaque fichier :
    - Fichiers `.dwg`, `.dxf`, ou plans `.pdf` $\rightarrow$ Traitement CAD / Routing.
    - Fichiers `.xlsx`, `.csv` contenant des câbles $\rightarrow$ Traitement Carnet de Câbles.
    - Fichiers de calcul `.pdf` / `.xlsx` $\rightarrow$ Traitement Note de Calcul.
  - Lance la triangulation et consolide le MTO dans une réponse unifiée.

#### [MODIFY] `arkan-ui.html`
- Ajouter l'attribut `multiple` sur `<input type="file" id="ie-file-input" multiple ...>`.
- Modifier `handleIeFileDrop(e)` et `handleIeFileSelect(e)` pour boucler sur `files` (tous les fichiers déposés) et appeler `processIeFilesBatch(files)`.
- Afficher la liste des fichiers chargés avec leur rôle détecté (Badge Plan CAO, Badge Carnet Câbles, Badge Note Calcul).

---

## Verification Plan

### Automated Tests
1. **Test unitaire d'échelle sur `C2723-GCB-000-ELE-PLA-006`** :
   - Vérifier que `scale_to_m` est calculé à `0.001`.
   - Vérifier que `cable_tray_linear_m` est d'environ `196.5 m` ($\pm 5\%$) et non `196 573 m`.
2. **Test unitaire sur `C2723-GCB-000-ELE-LST-001.xlsx`** :
   - Vérifier que les 16 câbles sont extraits avec leurs sections et longueurs réelles.
3. **Test d'intégration multi-fichiers** :
   - Tester l'endpoint `/ie-mto/calculate-batch` avec le dossier `C:\Users\MSI\Desktop\1`.
   - Vérifier que la triangulation s'exécute avec les métrés corrigés.
4. **Banc de non-régression global** :
   - `pytest tests/test_ei_triangulation.py`
   - `python tests/run_all_tests.py` (8/8 tests passés).

### Manual Verification
1. Glisser-déposer l'ensemble des fichiers du dossier `1` sur l'interface ARKAN.
2. Vérifier que tous les fichiers sont listés et traités ensemble.
3. Vérifier que le quantitatif des chemins de câbles affiche `~196.5 m` et que les 16 câbles du carnet apparaissent dans la table MTO.
