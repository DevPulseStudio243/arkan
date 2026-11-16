# Rapport de vérification du bundle ARKAN — erreurs décelées et corrigées

Vérifié sur le plan réel `C3421-ROK1-200-PRC-DM-300002_2.dwg` (AC1032, converti en DXF avec LibreDWG) et sur
les échantillons du bundle. Suite de tests : **43 tests Python passent** (9 au départ, dont 1 en échec) + 2 fichiers de tests JavaScript (`tests/js/`).

## Résultat sur le plan réel (avant -> après)

| Mesure | Avant | Après |
|---|---|---|
| Instruments détectés | **0** (134 présents) | 135 |
| Lignes tuyauterie | 71 "lignes" = texte + géométrie voisine, non connectées | 78 runs issus de la géométrie, 70 avec numéro |
| `line_entries` / boucles / avertissements | `[]` / `{}` / `[]` toujours vides | 70 / 29 / 88 |
| Fractions (`3/4"`) | lues `4"` (taille fausse, silencieusement) | `3/4"` |
| Audit topologique | jamais appelé ; vannes `201-HV-xxx` traitées en équipements | 36 constats (à revoir) |
| Équipements sans bloc | 17 "confirmés" automatiquement, bbox de 30 à 100 entités sur 6 calques | tous `to_confirm`, 13 candidats plausibles |

## Erreurs corrigées

### dwg_converter.py
1. **DXF tronqué accepté** : le succès reposait sur `taille > 100 octets`. Maintenant le DXF est relu avec ezdxf et doit contenir des entités.
2. **Ancien DXF renvoyé après un échec** : un `.dxf` périmé à l'emplacement cible passait pour le résultat. Chaque moteur écrit dans un fichier temporaire, remplacement atomique.
3. **Pas de cache** : reconversion à chaque appel et fichier écrit à côté du DWG. Cache par contenu (md5) : un DWG révisé sous le même nom est reconverti.
4. **Timeout fixe de 60 s** : échec sur les gros plans. Proportionnel à la taille (120 s + 120 s/Mo), surchargeable.
5. **`dwg2dxf.exe` sélectionné hors Windows** (`Permission denied`, le `dwg2dxf` du PATH n'était jamais essayé). `.exe` ignoré hors Windows.
6. Erreurs des moteurs avalées : le message final liste maintenant la raison de chaque moteur.

### dxf_pid_parser.py (étage sémantique réécrit, API conservée)
7. **Instruments absents** : le tag est coupé en deux attributs `INST_TYPE` / `INST_NO`. Recombinés en `FIC-210`.
8. **Fractions MTEXT** (`3#4"`) : `search()` non ancré prenait `4"`. Normalisées en `3/4"`, regex ancrées.
9. **Lignes = texte + géométrie voisine** : aucun raccordement. Maintenant : snapping des extrémités, coupure aux jonctions (y compris T posé au milieu d'un trait), pontage des symboles en ligne, appariement un-à-un numéro/run.
10. **Blocs imbriqués non lus** (un seul niveau de `virtual_entities`). Récursion jusqu'à `max_block_depth`.
11. `line_entries`, `loops`, `warnings` toujours vides -> produits. Le moteur topologique n'avait rien à consommer.
12. **`load_config` mutait `DEFAULT_CONFIG`** (copie superficielle) : fuite d'état entre appels.
13. **`layer_role` par sous-chaîne** (`TB` dans `OUTBOUND`, `DIM`...) : mots courts désormais comparés par jeton.
14. **Attributs "invisibles"** : LibreDWG marque tous les attributs `flags=1`. Le drapeau n'est plus utilisé (liste `hidden_attribs` à la place).
15. **Collisions d'identifiants de lignes** (`L-<handle>` identique pour deux runs d'une même polyligne -> lignes écrasées, crash `max()` vide). Ids uniques et déterministes.
16. `units` figé à `"mm"` -> lu dans le DXF. Numéro de plan : nom du fichier (source indiquée), jamais une valeur inventée.
17. Nouveaux avertissements utiles : `LINE_TAG_CONFLICT`, `LINE_NO_TAG`, `EQUIPMENT_NOT_CONNECTED`, `EQUIPMENT_TO_CONFIRM`, `PROXY_OBJECTS`, `LOOP_INCOMPLETE`.

### pid_equipment_blocks.py
18. **Auto-confirmation** : les symboles "en ligne" étaient marqués `user_decision: confirmed_inline`, confiance 0,95, sans validation humaine. Désormais `None` / `inline_symbol_to_confirm` / 0,5.
19. **Symbole en ligne = tout le voisinage** (30 à 100 entités, 6 calques, jusqu'à 388 unités) : tuyauterie, vannes, instruments, textes et gros traits exclus ; amas trop grand ou trait isolé -> tag orphelin à confirmer.
20. Crash `KeyError: 'inline_equipment'` en ajoutant la revue humaine. Libellé ajouté.
21. **Ajout de `equipment_review.html`** : sélection des traits, confirmation / correction / fusion, export relu par `--equipment-review`.

### arh_pid_topology_engine.py
22. **Tags avec préfixe de zone** (`201-HV-003`) non reconnus : vannes traitées en équipements ("composant isolé"), règles DBB jamais déclenchées. Préfixe retiré avant classification ; `FV`, `MOV`, `TSV`... classés vannes.
23. **Moteur jamais branché** : appelé nulle part. `pid_analyzer.parse_dwg_file` renvoie maintenant `line_entries` et `topology_findings` (tous `needs_review`).

### pid_analyzer.py / dwg_iso_extractor.py
24. DXF voisin repris **par nom de fichier seulement** : une révision du DWG relisait l'ancien DXF. Accepté seulement s'il n'est pas plus ancien que le DWG.
25. `dwg_iso_extractor` : `Path(r"d:\DATA BASE IA\cad_cache\dxf").mkdir(...)` hors `try` -> crash sur tout poste sans lecteur D:. Cache commun de `dwg_converter`.

### pid_schematic.py
26. Valeurs inventées dans le pied de page : plan `DWG-PID-001`, révision `A`, `UNITÉS : mm`, "ASME B31.3". Remplacées par les valeurs lues, ou "non lu".

### Deuxième passe : fichiers reçus ensuite (circuit_graph.py, ie_plan_viewer.js, ie_triangulation.js, pdf.js)
30. **ie_triangulation.js : injection HTML/JS.** Tag, titre, commentaire, sections et notes issus des fichiers importés étaient injectés tels quels dans `innerHTML`, et l'identifiant de fiche dans un `onclick="..."`. Tout est échappé, boutons par délégation d'événements. Vérifié avec un tag `<img onerror>` et un identifiant `x');window.__pwned=1;//` : rien ne s'exécute.
31. **ie_triangulation.js : plantage** (`TypeError`) dès qu'une fiche n'a pas `cad_view`, `cs_view`, `cn_view` ou `proposed_resolution` : accès défensifs.
32. **ie_triangulation.js : accents perdus** (`? VALID & INJECT`, `IGNOR`, `Non mesur`, `Arbitrage enregistr`) : `VALIDÉ & INJECTÉ`, `IGNORÉ`, `Non mesuré`, `Arbitrage enregistré`.
33. **ie_triangulation.js : URL relatives** ignorant `window.API_BASE` (inutilisables en `file://` ou hôte distinct). Message « au moins deux fichiers » mais un seul exigé : deux exigés.
34. **ie_triangulation.js : « Valider & Injecter » sans effet visible** : le code visait `window.ieMtoState` et `renderIeItemsTable`, qui n'existent pas dans l'interface (elle utilise `window.currentIeMtoData` et `renderIeMtoTable`).
35. **arkan-ui.html : le visualiseur corrigé (`ie_plan_viewer.js`) est écrasé** par d'anciennes définitions inline (`initIePlanViewer`, `applyIePlanTransform`, `renderIeMtoResults`), chargées après lui. Conséquence : les boutons de page appelaient le nouveau visualiseur, qui n'avait rien chargé, donc **ne faisaient rien**. `ie_plan_viewer.js` délègue maintenant à l'ancien code tant qu'il n'a pas de plan chargé ; `iePlanLoad(urls)` est exporté pour la migration.
36. **arkan-ui.html : indicateur de zoom jamais mis à jour** (`ie-zoom-indicator` n'existe pas ; l'élément est `ie-zoom-val`).
37. **circuit_graph.py : sens d'écoulement jamais déterminé sur les tags avec zone** (`201-PP-001/A`, `201-TK-001` ne correspondaient pas à `_SOURCE_RE` / `_SINK_RE`) : préfixe de zone retiré.
38. **pid_viewer.py : aucune vanne ni équipement reconnu avec un préfixe de zone** (`201-HV-003`) ; erreurs d'import remplacées par des messages explicites.
39. **static/** : `pdf.min.js`, `pdf.worker.min.js` (reçus sous le nom `pdf_min.js` / `pdf_worker_min.js`, renommés comme l'interface les référence), `ie_plan_viewer.js`, `ie_triangulation.js`. pdf.js 3.11.174 des deux côtés : versions concordantes. Les 4 références `/static/*.js` de l'interface sont couvertes.
40. 7 tests Python (`test_circuit_graph.py`) et 2 fichiers de tests JS (jsdom) ajoutés ; `ie_plan_viewer.js` fourni passe ses tests tel quel (fonctions pures et DOM).

### Troisième passe : raw.json v2 sans perte et vérification par aller-retour (`raw_roundtrip.py`)
Mesuré sur le DXF réel avant correction : 17 % des entités n'étaient pas reprises en géométrie complète et 57 blocs
en miroir donnaient des positions fausses.
41. **Blocs insérés en miroir : positions lues en miroir.** Après éclatement, 27 polylignes, 30 cercles et 4 textes avaient une extrusion (0,0,-1) ; leurs coordonnées (système OCS) étaient lues comme des coordonnées monde. Redressées avec `ezdxf.upright` (arcs, cercles, ellipses, polylignes, hachures, SOLID) et conversion explicite pour TEXT / ATTRIB.
42. **Géométrie perdue sans avertissement** : ELLIPSE (596) et SPLINE : boîte seule ; ARC : pas d'angles ; polylignes : arcs (bulge) aplatis en cordes (58 sommets) ; HATCH (66), SOLID (29) et IMAGE : absents. Tous capturés par leurs paramètres natifs : angles, bulge, paramètres d'ellipse, points de contrôle, nœuds et poids, contours de hachure (lignes, arcs, ellipses, splines), motif de hachure, sommets de SOLID, taille et vecteurs d'image.
43. **Arrondi** : à 6 décimales, une ellipse complète (fin - début = 2π) n'était plus reconnue comme fermée ; angles et paramètres, puis coordonnées, sont maintenant écrits en pleine précision.
44. **Styles de texte** (police, largeur, oblique), propriétés MTEXT (interligne, hauteur définie, direction, largeur), couleur / type / épaisseur de trait, matrice de chaque INSERT (échelle, rotation, réseau) et lien `parent` de chaque entité : conservés.
45. **Paper space ignoré** : le cartouche y est stocké. Capturé (champ `space`), sans polluer la sémantique du model space. Le numéro de plan, la révision, la discipline, le contrat, le titre et l'historique des révisions sont maintenant lus dans les attributs du cartouche. Avant : numéro = nom de fichier, révision `N` (regex erronée) au lieu de `2`.
46. **Note de préfixe de tags** (« TOUS LES TAGS DES VANNES ET INSTRUMENTS SONT PRÉFIXÉS DE 201 ») détectée : `full_tag` = `201-FIC-210` ; `tag` reste celui dessiné.
47. Rapport de couverture dans `raw.json` (`coverage`) : types, nombre dans le DXF, nombre repris, mode ; avertissement `RAW_NOT_LOSSLESS` si quelque chose manque. Blocs sans définition (`*X` : 18 INSERT du paper space) signalés par `BLOCK_DEFINITION_MISSING` au lieu d'être ignorés.
48. `pid_analyzer` : les valeurs lues dans le cartouche l'emportent sur l'heuristique par regex.

**Preuve d'exactitude sur ton plan** (`python raw_roundtrip.py raw.json plan.dxf sortie/`, résultat `EXACT`) :
le DXF reconstruit **uniquement à partir de `raw.json`** est comparé à l'original, avec des mesures prises par ezdxf :

| | model space | paper space |
|---|---|---|
| entités par type | identiques (4 747) | identiques (752) |
| longueur cumulée des tracés par type | écart relatif 0 | écart relatif 0 |
| étendue du dessin | écart 0,000 | écart 0,000 |
| textes (contenu et position) | 830 / 830 | 153 / 153 |

Rendu raster du model space (même moteur, même cadrage), sans texte : 100 % des pixels de l'original retrouvés dans le
reconstruit ; 99,2 % des pixels du reconstruit présents dans l'original ; recouvrement exact (IoU) 0,979. Avec les textes :
97,6 % et 93,9 % (IoU 0,905).

Limites de cette preuve : la vérité de référence est ezdxf, pas AutoCAD ; l'écart de rendu avec texte vient de la façon dont
ezdxf place les MTEXT dans les blocs pivotés ou en miroir (un MTEXT rendu isolément est identique au pixel près dans les deux
dessins) ; les INSERT ne sont pas reconstruits en blocs (leur contenu est aplati, avec `parent`, `block_path` et la matrice
pour retrouver la structure) ; les IMAGE ne sont pas reconstruites ; l'emprise d'un texte est une estimation de police et
n'entre pas dans l'étendue comparée. Le vérificateur détecte une perte : un test supprime volontairement le bulge des
polylignes et exige que la comparaison échoue.

### tests / README
27. `test_parse_dwg_file_with_real_pid_dxf` exigeait `uploads/test_gtp.dxf` (non livré) : échantillon synthétique ou skip explicite.
28. README : "9 tests PASSED" faux ; `scikit-learn` inutile ; `/static/*.js` absents du bundle.
29. 19 tests de non-régression ajoutés (`tests/test_corrections.py`).

## Non corrigé — ce qu'il me manque encore
- **`piping_topology_tracer.py`** : reçu et intégré. `parse_line_tag` donne les mêmes champs que mon parseur sur les numéros de ligne du plan réel (test de recoupement) ; `circuit_graph` et mon parseur s'accordent sur 59 numéros de ligne (70 chez moi, 80 chez lui : `circuit_graph` coupe aux symboles, donc 281 chaînes contre 78 runs). **Non testé** : le chemin PDF de `pid_analyzer` et `pid_viewer` sur un vrai PDF (aucun fourni). `decode_gcb_pipe_spec('1ACX1PN')` renvoie `decoded: False` : la classe de tuyauterie de ce plan n'est pas décodée.
- **Le backend** : aucune route `/ie-mto/triangulate`, `/ie-mto/triangulation/action`, ni génération de `plan_preview_pages` dans le bundle. Les contrats JSON de `ie_triangulation.js` (`discrepancy_cards`, `summary`, `injected_item`...) n'ont pas pu être vérifiés côté serveur.
- **Migration du visualiseur** : l'interface garde son ancien visualiseur inline (rendu PDF par pdf.js dans un canvas, panoramique souris seule, zoom non centré). Basculer sur `ie_plan_viewer.js` (zoom au curseur, pincer, multi-feuillets) demande d'appeler `window.iePlanLoad(urls)` depuis `renderIeMtoResults` et de supprimer le bloc inline ; je ne l'ai pas fait sans pouvoir tester dans un navigateur avec ton backend, car cela retire le rendu PDF côté client.
- **`arkan-ui.html`** : fins de ligne `\r\r\n` (230 833 lignes) ; scripts CDN non épinglés (unpkg, jsdelivr `marked`, `mermaid`, `chart.js`) : j'ai besoin des versions qui fonctionnent chez toi.
- **`bin/cad/dwg2dxf.exe`** : non exécutable ici ; version à me donner (`dwg2dxf.exe --version`).
- **`circuit_graph.py`** : deux segments parallèles reliant les mêmes deux nœuds sont fusionnés en un (graphe simple dans `_order_chain`) ; `to_line_entries` émet `TEE@x,y` comme `from/to_equipment`, que `arh_pid_topology_engine` prend pour des équipements. À traiter quand le traceur complet sera branché.
- **Équipements** : 21 sur 21 restent `to_confirm`, 11 non connectés, 66 lignes sans équipement de départ ou d'arrivée ; les 36 constats topologiques ne sont fiables qu'après confirmation via `equipment_review.html`.
- Références réglementaires du moteur topologique (« Décret 21-315 », « ASME B31.8 », « API 5L ») : non vérifiées.
- Seuils géométriques réglés sur un seul plan : à recontrôler sur d'autres feuilles.
