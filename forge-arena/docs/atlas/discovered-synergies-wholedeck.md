# discovered-synergies-wholedeck

**Schema tag:** `arena.discovered-synergies-wholedeck/1`
**Filename:** `discovered-synergies-wholedeck.json` (in `<deck>/dossier/`)
**Generator:** research subagent (Fable + Gemini, full-context discovery)
**Consumer:** prep `TutorWeights` (discovered-synergy hub fold, file-guarded); the main agent (compile work list)
**Status:** live

## What it is

The **whole-deck discovery corpus** — the exemplary run's output. Every anchor card
is passed (Phase I wide), the richest ~15 are deepened (Phase II), findings are
adversarially verified, and the result is capped at ~200 Fable records plus
Gemini's cross-check set. It is the raw material the **Compile** step triages into
programs / weights / `shape_is_new` backlog, and the file `TutorWeights` folds into
tutor priorities (bounded by `HUB_CAP`). This is the biggest artifact in the
dossier (~800 KB) and the one the whole pipeline exists to produce well.

## Who generates it, and when

**Research subagents**, in the Discover step (§2.2): Fable is primary
(verified + capped 200), Gemini is the independent cross-check. Full deck text, all
scripts, strategy doc, and rules digest in context — **zero hallucinations** is the
bar. Not reproducible (model output); curated and verified, not deterministic.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.discovered-synergies-wholedeck/1"` |
| `deck`, `note` | ✓ | deck id; the run description (anchors, provenance, "DISCOVERY ONLY") |
| `counts` | ✓ | the funnel: `phase1_valid`, `phase2_merged_valid`, `hallucinated_dropped`, `verified`, `refuted_dropped`, `final_capped`, `gemini_valid`, `overlap_fable_gemini`, `gemini_only`, … |
| `top_anchors[]` | ✓ | the Phase-II deep anchors (strings) |
| `shape_is_new_backlog[]` | ✓ | `{key, program_class, mechanism}` — mandatory runner work (completeness bar §4) |
| `fable_catalog[]` | ✓ | ~200 verified records (primary) |
| `gemini_only_candidates[]` | ✓ | Gemini's non-overlapping finds (cross-check) |

### A discovery record (`fable_catalog[]` / `gemini_only_candidates[]`)

`{anchor, partner_cards[], n_cards, program_class, shape_is_new, pieces[{card,role,forge_cost,target}], loop, win_plan_steps[], preconditions[], mechanism, produces, magnitude, win_relevance, novelty_vs_dossier, confidence, false_positive_check, engine_test, compile_rank, _corroborated_by_gemini}`
— the `pieces[].forge_cost` quotes the real script cost (zero-hallucination
evidence); `shape_is_new` flags a record needing a new runner; `compile_rank`
orders the compile queue.

## Canonical example

`decks/selvala-heart-of-the-wilds/dossier/discovered-synergies-wholedeck.json`
(200 fable + 67 gemini-only; 85 anchors):

```json
{
  "schema": "arena.discovered-synergies-wholedeck/1",
  "deck": "selvala-heart-of-the-wilds",
  "counts": { "phase1_valid": 154, "phase2_merged_valid": 207, "hallucinated_dropped": 0, "verified": 48, "refuted_dropped": 2, "final_capped": 200, "gemini_valid": 87, "overlap_fable_gemini": 18, "gemini_only": 67 },
  "top_anchors": ["Temur Sabertooth", "..."],
  "shape_is_new_backlog": [ { "key": "Omnath, Locus of Mana + Seedborn Muse + Wild Growth", "program_class": "engine", "mechanism": "Seedborn's UntapOtherPlayer re-readies every land each opponent's untap; mana abilities usable any priority (CR 605.3a) ..." } ],
  "fable_catalog": [
    { "anchor": "Finale of Devastation", "partner_cards": ["Selvala, Heart of the Wilds", "Umbral Mantle", "Craterhoof Behemoth"], "n_cards": 4, "program_class": "win_plan", "shape_is_new": false,
      "pieces": [ { "card": "Selvala, Heart of the Wilds", "role": "producer", "forge_cost": "{G}, {T}", "target": "" }, { "card": "Umbral Mantle", "role": "untapper", "forge_cost": "{3}, {Q}", "target": "Selvala, Heart of the Wilds" } ],
      "loop": { "activate_cost": "{G}, {T} Selvala for X=greatest power", "...": "..." },
      "confidence": "high", "compile_rank": 0.85, "_corroborated_by_gemini": true }
  ],
  "gemini_only_candidates": [ "..." ]
}
```

## Consumer & invariants

**Prep:** `TutorWeights` folds discovered-synergy hubs into tutor weights, guarded
on this exact filename, capped by `HUB_CAP` (0.5, below the combo band) so
discovery can't dominate the weighting.
**Compile (main agent):** the file is the work list — `compile_rank` orders it,
`shape_is_new` records gate completeness (§4), and each record resolves to a
program / weight / backlog item. Invariants: `counts.hallucinated_dropped` must be
0 (the zero-hallucination bar); `pieces[].card` all in the deck;
`shape_is_new_backlog` is not empty-able by fiat — each entry is a mandatory runner
to build, not a permanent flag.

## Related

- Triaged into: [combo-program](combo-program.md), [tutor-priorities](tutor-priorities.md), [program-backlog](program-backlog.md), [build-manifest](build-manifest.md)
- Human report twin: `discovered-synergies-wholedeck-REPORT.md` (not yet paged)
- The discovery process: working-plan-Aug-3 §2.2, §4, §5; research briefs §8.6
