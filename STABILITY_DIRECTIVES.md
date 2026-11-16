# Charter of Software Stability & Modular Isolation (Arkan EPC Engine)

## 📌 Directives de Stabilité & Isolation des Modules

Afin de garantir la stabilité permanente d'**Arkan — Intelligence EPC**, chaque modification ou évolution future doit strictly respecter la politique d'**Isolation Modulaire** ci-dessous.

---

### 1. Règle d’Isolation Stricte des Volets (Non-Interférence)
- **Volet Audit Planification (Primavera XER)** : Tout changement dans l'analyse DCMA, le Gantt, la Courbe S ou Monte Carlo doit être **strictement confiné** au conteneur `#view-planning`, aux fonctions JS préfixées `planning` / `openTaskDetailsModal` / `openDcmaNonConformityModal`, et au backend `planning_analyzer.py`.
- **Volet Suivi Procurement & Achats** : Tout changement dans la gestion des contrats, des articles ou des réceptions doit être **strictement confiné** au conteneur `#view-procurement`, aux fonctions JS préfixées `procurement`, et au backend `procurement_db.py`.
- **Volet Traçabilité & Isométriques** : Tout changement dans le suivi des spools et des lignes d'isométriques doit être confiné au conteneur `#view-traceability` et à `traceability_db.py`.
- **Volet Lecteur de Plans (IA & P&ID 3D)** : Confiné au conteneur `#view-pid-reader`, à `arkan3d.js` et `pid_analyzer.py`.

---

### 2. Protection des Espaces de Noms & Identifiants Globaux
- **Identifiants uniques de composant** : Interdiction absolue de réutiliser ou de surcharger des IDs HTML existants. Tout nouveau composant doit posséder un identifiant préfixé par son volet (ex: `#planning-modal-...`, `#procurement-modal-...`).
- **Fonctions JS cloisonnées** : Aucune fonction générique ou événement global ne doit être écrasée ou modifiée s'il impacte un autre volet.

---

### 3. Suite Automatisée de Vérification Non-Régression
Pour valider qu'une mise à jour dans un volet n'a en aucun cas affecté les autres volets, la suite de tests Selenium E2E doit être exécutée systématiquement :
1. `verify_procurement_dashboard_active.py` (Achats & Stock)
2. `verify_planning_dashboard_complete.py` (Audit Planification XER)
3. `verify_dcma_nonconformities_modal.py` (Non-conformités DCMA)
4. `verify_modal_traceability_added.py` (Traçabilité & Isométriques)

---
*Document de référence enregistré et appliqué pour l'ensemble des développements d'Arkan.*
