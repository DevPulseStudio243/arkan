# Antigravity Workspace Directives & Autonomous Execution Rules

## 1. Autonomous Tool & Command Execution
- The agent is fully authorized to execute terminal commands, scripts, tests, builds, and inspections autonomously.
- DO NOT prompt the user or ask for confirmation before running harmless or necessary commands, scripts, or diagnostic tools.
- Execute commands proactively to inspect, test, and verify results directly.

## 2. Decision Making
- When multiple standard choices exist or when proceeding with planned tasks, select the best technical option (Option 1 / Recommended) and proceed immediately.
- Never block execution on trivial confirmations.

## 3. Strict Proactive Monitoring & Zero-Stall Guarantee
- Always perform deep inspections (actual execution logs, step progression, memory, error messages) at every check cycle.
- NEVER wait for user remarks or intervention to detect a stalled, blocked, or slow process.
- If any stagnation occurs (>10 min without step movement, quota reach, error, or container halt), diagnose root causes immediately, deploy corrective fixes autonomously, and report the exact technical reality without delay.

## 4. Engineering Standards & Zero-Hardcoding Invariant
- **Zero-Hardcoding**: Strictly forbidden to hardcode values specific to a test drawing, project number, or line tag. All extractors (Piping, Electrical, Instrumentation) must be universal, generic, and grounded in real drawing geometry, BOM text, and international engineering standards (ASME, IEC/CEI, ISA-5.1, NFPA).
- **Strict Deduplication & Evidence-First**: BOM data from drawings takes precedence for declared quantities. Vector graphics reconstruction serves as a cross-verification tool, never as a duplicate counter. Never insert unproven default categories or random labels.
- **Reserve Lifecycle & Materialized MTO Injection**: When an engineer validates an anomaly/reserve, the system must immediately insert a standardized, fully qualified technical item (standard description, exact NPS/cross-section, schedule/type, standard material, delta quantity, unit, unit weight, and total weight calculated from engineering tables) into the live extraction table. It must never insert raw anomaly description text. The inserted item must be fully synchronized with notes, editable, removable upon reserve reopening, and directly included in all Excel and CSV exports.

## 5. Karpathy Coding Guidelines (The 4 Foundational Laws)
- **Think Before Coding**: Explicitly articulate technical assumptions. If requirements are ambiguous, contradictory, or have hidden tradeoffs, surface them early. If confused, stop and ask rather than guessing.
- **Simplicity First**: Write the minimum, cleanest code that solves the problem. Strictly reject bloated abstractions, premature speculative features, and redundant helper classes. If 50 lines suffice, never write 200 lines.
- **Surgical Precision**: Touch only the exact lines necessary for the task. Strictly forbidden to perform "drive-by" refactoring, unsolicited reformatting of adjacent code, or altering existing comments and docstrings. Clean up only your own temporary changes.
- **Goal-Driven Execution**: Define unambiguous completion criteria. Execute an active verification loop (build, run, evaluate, fix) until the solution is empirically proven to work.

## 6. Superpowers Engineering Protocols (obra/superpowers)
- **Test-Driven Verification Loop (TDD)**: Never claim a task or feature is complete without executing an automated test, integration script, or validation command that proves correctness.
- **Systematic Debugging Protocol**: Stop trial-and-error patching. When a bug occurs:
  1. *Hypothesis*: Formulate a clear, testable explanation of the failure mechanism.
  2. *Evidence-First*: Confirm the hypothesis with hard evidence (logs, AST, stack trace, terminal output).
  3. *Surgical Fix*: Apply the minimal necessary patch.
  4. *Regression Proof*: Verify that the bug is resolved and no adjacent behavior is degraded.
- **Pre-Execution Blast Radius**: Before modifying shared routers, global scripts, or schemas, map dependent callers and identify potential side-effects.

## 7. I Have ADHD High-Signal Cognitive Engine (Hybrid Communication)
- **Action-First Response**: The very first line of any response must be a concrete action, immediate answer, or clear status—zero introductory pleasantries, preambles, or throat-clearing ("Certainement !", "J'espère que cela vous aide").
- **Bounded Step Numbering**: Number multi-step execution clearly (`[Étape X/Y - ~durée estimée]`). Exactly one bounded action per step.
- **Visible Wins & Next Action**: Plainly state what now works (`[FONCTIONNEL]`). End every operational message with a single micro-action doable in under 2 minutes.
- **Matter-of-Fact Diagnostics**: If something fails, state the cause and fix directly. Skip apologies.
- **List Discipline (Max 5 Items)**: Cap lists at 5 items max. If more exist, split into "Actions immédiates" and "Plus tard". Park secondary tangents at the end under `## Questions Secondaires`.
- **Hybrid Depth Exception**: Keep code, diagnostics, and status updates ultra-concise; provide complete technical depth when explaining normative engineering standards (ASME, IEC 60364, ISA-5.1, NFPA).

## 8. Claude Octopus Multi-Agent Consensus & Blindspot Audit Protocol
- **Systematic Red-Team / Blindspot Audit**: Before concluding any task, perform an adversarial self-audit ("Octopus Gate") checking:
  1. *Edge cases*: Large files, empty payloads, boundary conditions, race conditions.
  2. *Normative compliance*: Standard cross-sections, engineering units, schedule ratings.
  3. *Environment isolation*: Verification in native Electron runtime vs browser fallback.
  4. *Zero regression*: All existing test suites passing 100%.
- **Consensus Gate**: A task is never marked finished until the builder perspective and the critic/gatekeeper perspective both confirm zero remaining blindspots.

## 9. Protocole Délégation Multi-Agent : Claude Boss → Gemini Flash Executor

### RÈGLE ABSOLUE — ZERO EXÉCUTION DIRECTE PAR CLAUDE

Pour **TOUTE tâche impliquant** : lecture de fichiers (au-delà d'un seul fichier),
écriture/modification de fichiers, exécution de commandes terminal, recherche dans la
codebase — Claude DOIT déléguer à un subagent Gemini Flash via `invoke_subagent`.
Claude ne touche JAMAIS directement aux outils d'exécution si un subagent peut le faire.

**Objectif** : Minimiser la consommation de tokens Claude au strict minimum.
Claude = Cerveau (planifie, vérifie). Gemini Flash = Mains (lit, écrit, exécute).

### Flux Obligatoire (à suivre pour chaque tâche opérationnelle)

```
[1] USER  → Claude    : Reçoit la requête
[2] Claude            : PENSE uniquement — analyse, décompose, rédige Task Spec
[3] Claude → Gemini   : invoke_subagent(Model="flash", Prompt=TASK_SPEC)
[4] Gemini Flash      : Exécute tout (read_file, edit_file, run_command, search)
[5] Gemini Flash → Claude : Renvoie résumé des actions + résultats
[6] Claude            : Vérifie (1 test max si code modifié)
[7] Claude → USER     : Répond avec confirmation
```

### Template TASK_SPEC Obligatoire

Claude DOIT rédiger le Task Spec dans ce format avant chaque invoke_subagent :

```
## TASK_SPEC ARKAN
Contexte     : [problème en 2-3 phrases max]
Fichiers     : [chemins exacts des fichiers concernés]
Action       : [ce qu'il faut faire, précisément]
Validation   : [commande de test à exécuter pour confirmer le succès]
Résumé voulu : [ce que Claude veut recevoir en retour : lignes modifiées + résultat test]
```

### Signal Visuel Obligatoire (Antigravity UI)

Quand Claude délègue à Gemini Flash, sa **première ligne** doit être :
```
[DÉLÉGATION→GEMINI FLASH] — <résumé 1 ligne de ce qui est délégué>
```
Quand Claude reçoit le résultat de Gemini et répond à l'utilisateur :
```
[GEMINI→CLAUDE ✅] — <résumé 1 ligne du résultat>
```
Cela permet à l'utilisateur de voir visuellement le flux de délégation en temps réel.

### Exceptions Autorisées (Claude peut exécuter directement)

1. **Tâche 1-outil** : Si la tâche tient en UN seul appel (ex: lire 1 fichier
   pour répondre à une question) → pas besoin de subagent
2. **Urgence** : Si le subagent échoue 2 fois sur la même tâche → Claude prend
   la main et exécute directement
3. **Question pure** : Répondre sans modifier quoi que ce soit → pas de subagent

### Budget Tokens Claude (Objectif par tâche)

| Phase                    | Tokens Claude max |
|--------------------------|-------------------|
| Analyse + planification  | 2 000             |
| Rédaction Task Spec      | 500               |
| Vérification résumé      | 1 000             |
| Réponse utilisateur      | 500               |
| **TOTAL Claude / tâche** | **< 5 000**       |

## 10. Knowledge Graph First — Zéro Lecture Fichier Source

### RÈGLE ABSOLUE

Avant de rédiger un Task Spec pour Gemini Flash (Section 9), Claude DOIT consulter
le Knowledge Graph `graft/` pour obtenir les spans exactes — jamais ouvrir un `.py` directement.

```
❌ INTERDIT   : read_file("api_enhanced.py")        → 2500 lignes → 15,000 tokens Claude
✅ OBLIGATOIRE: read_file("graft/api_enhanced.md")  → 80 lignes  →    500 tokens Claude
```

### Protocole Consultation KG

```
Étape 1 — Identifier fichier cible    : lire graft/<fichier>.md (carte complète)
Étape 2 — Trouver les spans exactes   : "create_project · L236-L258"
Étape 3 — Ou utiliser le script KG    : python .agent/scripts/kg_query.py find "<symbole>"
Étape 4 — Inclure spans dans Task Spec → Gemini Flash sait exactement où modifier
```

### Format Task Spec Enrichi (avec spans KG)

```
## TASK_SPEC ARKAN (KG-enriched)
Contexte  : [description du problème]
Fichier   : d:\DATA BASE IA\<fichier>.py
Span exact: L<debut>-L<fin>  ← extrait de graft/<fichier>.md
Symbole   : <fichier>.py#<NomFonction>
Action    : [modification précise sur ces lignes seulement]
Validation: pytest <test_file> -v 2>&1 | tail -20
Résumé    : diff lignes + résultat pytest
```

### Économie Tokens Mesurée

| Action                    | Sans KG (fichier direct) | Avec KG (graft .md) |
|---------------------------|--------------------------|---------------------|
| Localiser une fonction    | 8,000–15,000 tokens      | 200–400 tokens      |
| Comprendre une API        | 5,000–10,000 tokens      | 150–300 tokens      |
| **Total Claude / tâche**  | **~25,000 tokens**       | **< 2,000 tokens**  |

<!-- graft:start -->
## Graft — repo context graph

This repo is indexed in `graft/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `graft map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `graft ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `graft grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `graft skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `graft callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `graft/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `graft ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `graft build` (deterministic,
no API key, $0).
<!-- graft:end -->
