# CHANGELOG des correctifs — ARH Management

Tous les correctifs sont couverts par `tests/test_arh_corrections.py` et `test_modernized_arh_pipeline.py` (25 tests, tous passants).
Lancer : `python -m pytest tests/ test_modernized_arh_pipeline.py -q`

## A. Bugs d'exécution
| # | Fichier | Problème | Correctif |
|---|---------|----------|-----------|
| 1 | arh_multiagent_engine.py | `NameError` (module jamais importé) + attribut inexistant `.standards` : l'agent métallurgie plantait dès qu'une composition chimique était trouvée (CEV et dureté jamais contrôlés) | Helper `_get_standards()` (via `get_engine().std`), repli CEV 0.43 / 22 HRC si `arh_standards.yaml` absent, avertissement journalisé |
| 2 | arh_multiagent_engine.py | `Path` non importé | `from pathlib import Path` |
| 3 | arh_semantic_engine.py | `full_doc_text` inexistant : les garde-fous n'étaient jamais appliqués, erreur masquée en `logger.debug` | `docs_text` ; erreur remontée en `warning` |
| 4 | arh_nuextract_engine.py, arh_document_slicer.py | `Tuple` non importé | import ajouté |
| 5 | arh_regulatory_engine.py | `match_historical_arh_reserves` définie deux fois | doublon supprimé (les deux retournaient `[]`) |
| 6 | arh_document_processor.py | Séquence d'échappement invalide `\s` (SyntaxWarning, futur SyntaxError) | `\\s` |

## B. Bugs de logique
| # | Fichier | Problème | Correctif |
|---|---------|----------|-----------|
| 7 | arh_document_processor.py | Un indice « CODE 02 » ou des réserves BT écrasaient un rejet fondé sur des preuves bloquantes | Les preuves bloquantes (pièces manquantes, sécurité critique, équipement inconnu, rejet explicite) priment toujours |
| 8 | arh_document_processor.py | `if arh_ai_engine.is_loaded or True` (toujours vrai) | `if arh_ai_engine is not None` (comportement identique, intention explicite) |
| 9 | arh_dimensional_engine.py | `barg`/`bara` (et `psig`/`psia`) traités comme identiques : faux écarts de 1,013 bar | Décalage atmosphérique appliqué quand une valeur est relative et l'autre absolue |
| 10 | arh_dimensional_engine.py | Parseur : `"A516 Gr 70 12 mm"` → `(516, 'gr')` | Retient le premier couple nombre/unité à unité reconnue → `(12, mm)` |
| 11 | arh_code_harness.py | Épreuve hydro acceptée avec 0,5 bar sous le minimum légal | Tolérance supprimée (arrondi 0,005 bar seulement) ; paramètre `stress_ratio_test_over_design` pour UG-99 |
| 12 | arh_code_harness.py | UG-27 : circonférentiel seulement, sans domaine de validité | Contrainte longitudinale, `t_governing_mm`, `validity_ok`, `validity_notes` (t ≤ R/2 ; P ≤ 0,385·S·E) |
| 13 | arh_code_harness.py | Sandbox : `timeout_sec` ignoré (`while True` bloquait le serveur), filtre par sous-chaîne contournable | Validation AST, processus séparé, timeout réel. **Ce n'est pas une frontière de sécurité** : ne pas y exécuter de code non fiable |
| 14 | arh_regulatory_engine.py | `verify_hydrotest_pressure` : aucune détection de surpression | Paramètre optionnel `max_test_bar` |
| 15 | arh_regulatory_engine.py | Formule B31.3 présentée comme ASME VIII ; grade inconnu = 138 MPa en silence | Docstring corrigée ; clés `grade_known` et `warnings` |

## C. Garde-fous (arh_assertion_guards.py, réécrit)
| # | Problème | Correctif |
|---|----------|-----------|
| 16 | « seamless » n'importe où dans le dossier supprimait toutes les réserves WPS/PQR | Applicable seulement si le constat le dit ou si le dossier ne contient aucune trace de soudage |
| 17 | « ABSENCE / MANQUANT » contournait la provenance | Exige un nom de pièce à proximité |
| 18 | Valeur aberrante réellement écrite dans le document = réserve supprimée | Conservée et marquée `VALEUR_ABERRANTE_DANS_LE_DOCUMENT` ; supprimée seulement si absente des sources (hallucination) |
| 19 | Rm (traction) traité comme contrainte admissible ; épaisseurs/températures non contrôlées ; psi/MPa ignorés | Plafond distinct, bornes réellement appliquées, conversions |
| 20 | Mots-clés par sous-chaîne | Mots entiers (`\b`) |
| 21 | Pas de trace des rejets | Paramètre `rejected_out` pour le journal d'audit |

## D. Sécurité / portabilité
| # | Fichier | Correctif |
|---|---------|-----------|
| 22 | arh_api_routes.py | Sans `ARKAN_API_KEY`, accès refusé hors machine locale (sauf `ARKAN_ALLOW_REMOTE_NO_AUTH=1`) |
| 23 | processor, deliverables, pdf_annotator, network_manager | Chemins Windows surchargeables : `ARH_UPLOADS_DIR`, `ARH_DELIVERABLES_DIR`, `ARH_MODELS_DIR` (valeurs par défaut inchangées) |

## E. Ajouts
- `arh_deterministic_calcs.py` : UG-27 (c)(1)/(c)(2) avec validité, UG-99, épreuve décret, référentiel gouvernant, Barlow 21-315, CEV/Pcm.
- `tests/test_arh_corrections.py`, `test_modernized_arh_pipeline.py` (ce dernier était cité dans la doc mais absent).

## Non corrigé (décisions de conception, voir documentation)
- `arh_concordance_graph.py` et `arh_model_router.py` ne sont importés par aucun module (code non branché).
- `test_pipeline_connectivity.py` (cité dans la doc) n'est pas fourni : le moteur de connectivité de pipeline n'existe pas dans l'archive.
- `arh_standards.yaml` est absent de l'archive (repli appliqué).
- `arh_document_processor.py` : 7 600 lignes, une fonction de 2 492 lignes ; ~100 `except Exception` ; 166 avertissements pyflakes (imports inutilisés, variables).
- La décision finale s'appuie encore sur des noms de fichiers (« CODE 01/02/03 », « REJET ») et des scores plafonnés ; la logique de verdict reste dupliquée en 5 endroits.
- Contraintes admissibles codées en dur (tables à remplacer par ASME II-D).
