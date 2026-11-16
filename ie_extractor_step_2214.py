# Plan Stratégique : Gestion des Plans Non Cotés & Intégration des Notes de Calcul

## 1. Contexte Normatif & Justification Technique

Dans l'ingénierie industrielle (Oil & Gas, Pétrochimie, Énergie - normes **IEC 60364**, **IEC 60909**, **NF C 15-100**, spécifications type Sonatrach/Total) :

> [!IMPORTANT]
> **OUI, la Note de Calcul Électrique (ou un Carnet de Câbles validé) est obligatoire** lorsque le plan d'implantation n'est pas coté ou n'est pas à l'échelle 1:1.
> Sans la longueur réelle ou forfaitaire issue de la note de calcul, il est techniquement impossible de certifier la section du câble.

### Pourquoi le courant admissible $I_z$ seul ne suffit jamais

Le dimensionnement d'un câble repose sur 4 critères interdépendants dont 3 dépendent directement de la longueur $L$ :

1. **Courant admissible thermique ($I_z \ge I_b$)** : Dépend de la température ambiante, du mode de pose et du groupement (indépendant de $L$).
2. **Chute de tension admissible ($\Delta U \le \Delta U_{max}$)** :
   $$\Delta U = b \cdot \frac{L}{1000} \cdot I_b \cdot \left( R \cdot \cos \varphi + X \cdot \sin \varphi \right)$$
   *Pour un moteur 75 kW alimenté en $3\times 70\text{ mm}^2$, $I_z$ est conforme, mais si $L > 85\text{ m}$, $\Delta U$ dépasse le seuil critique de 5% (ou 3%), imposant un surdimensionnement obligatoire en $3\times 95$ ou $3\times 120\text{ mm}^2$.*
3. **Contrainte thermique de court-circuit ($k^2 S^2 \ge I_{cc}^2 \cdot t$)** : Vérification de la tenue du câble lors d'un défaut franc en tête et en bout de ligne.
4. **Longueur maximale protégée ($L_{max}$)** : En régime TN ou IT, le déclenchement instantané des protections magnétiques contre les contacts indirects impose une longueur maximale de câble :
   $$L_{max} = \frac{0.8 \cdot U_0 \cdot S_{ph}}{1.5 \cdot \rho \cdot (1 + m) \cdot I_a}$$
   *Sans cote sur le plan, le risque de non-déclenchement sur défaut d'isolement en bout de ligne ne peut être vérifié.*

---

## 2. Matrice Décisionnelle ARKAN v3

```mermaid
flowchart TD
    A["Fichier Entrant (DWG/DXF/PDF)"] --> B{"Plan coté ou échelle 1:1 vérifiée ?"}
    B -- OUI --> C["Routage Topologique Dijkstra 3D<br/>L = L_tray + Delta_Z + L_loops"]
    B -- NON --> D{"Note de calcul fournie ?<br/>(Caneco / ETAP / BoQ Câbles)"}
    
    D -- OUI --> E["Ingestion Note de Calcul<br/>Extraction L_note & S_retenue"]
    E --> F["Validation Normative Croisée<br/>Calcul Delta U % & Iz"]
    F --> G["MTO Consolidé : Section Certifiée<br/>(Source = NOTE_DE_CALCUL)"]
    
    D -- NON --> H["Blocage Critique / Réserve CRITICAL<br/>Section non validable en longueur"]
    H --> I["MTO Dégradé : quantity=None<br/>Statut = A_VALIDER (Manque Note de Calcul)"]
```

---

## 3. Architecture d'Intégration dans ARKAN v3

### [Étape 1/4 - ~30 min] Détecteur d'Incertitude Dimensionnelle CAD
- **Module** : `ie_drawing_extractor.py` / `cad_geometry.py`
- **Règle** : Si `$INSUNITS = 0` (non spécifié) et qu'aucune cote géométrique (`DIMENSION`) n'est identifiée, flagger le plan comme `UNSCALED_OR_UNQUOTED`.
- **Comportement** : Interdiction formelle d'inventer une échelle arbitraire. Passage du mode *Extraction géométrique* au mode *Appariement Note de Calcul*.

### [Étape 2/4 - ~45 min] Ingesteur Universel de Notes de Calcul
- **Module à créer** : `calculation_note_parser.py`
- **Formats cibles supportés** :
  - Exports Caneco BT (CSV / Excel format colonnes : Repère, Longueur, Section, Chute de tension %, Calibre Disjoncteur).
  - Exports ETAP / Elec Calc (Excel / CSV).
  - Carnet de câbles d'ingénierie standard (Cable Schedule EPC).
- **Extraction des champs clés** : `cable_tag`, `source_panel`, `target_load`, `calc_length_m`, `design_section`, `voltage_drop_pct`, `protection_rating_a`.

### [Étape 3/4 - ~30 min] Moteur de Réconciliation Croisée Plan $\leftrightarrow$ Note
- **Module** : `cross_discipline_reconciler.py` (Nouvelle règle `CROSS_08_CALC_NOTE_CONSISTENCY`)
  - Contrôle 1 : Rapprochement des TAGs départs SLD avec les câbles de la note de calcul.
  - Contrôle 2 : Si une géométrie approximative existe dans le plan, alerte si écart $> 15\%$ entre $L_{plan}$ et $L_{note}$.
  - Contrôle 3 : Validation que la section du SLD correspond bien à la section requise par la note de calcul.

### [Étape 4/4 - ~30 min] Injection dans le Master Excel & UI
- **Onglet `CARNET_DE_CABLES`** :
  - Colonne `Longueur (m)` : Remplie avec la valeur issue de la note de calcul.
  - Colonne `Origine Longueur` : `NOTE_DE_CALCUL (Caneco v5.8 / ETAP)` au lieu de `CAD_MEASURED`.
  - Colonne `Chute de Tension %` : Reportée directement depuis la note.
- **Tableau de Bord UI (`arkan-ui.html`)** :
  - Ajout d'une zone de dépôt dédiée : *"Déposer la Note de Calcul Électrique (.xlsx / .csv)"* en complément du plan d'implantation.

---

## 4. Recommandations Pratiques pour les Appels d'Offres

1. **Si le client ne fournit aucun plan coté** : Exiger contractuellement la transmission du carnet de câbles (Cable Schedule) ou de la note de calcul BT/HT.
2. **Si seul le schéma unifilaire (SLD) est fourni** : Renseigner uniquement les types et calibres sans métré linéaire, et injecter une réserve systématique dans l'onglet `MATRICE_RESERVES_GLOBALE` (*"Métré câbles exclu - Plan non coté et note de calcul absente"*).
3. **Validation Sécurisée** : Ne jamais commander de tourets de câbles sur la base d'un plan non coté sans recoupement par note de calcul.
