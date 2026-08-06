export const meta = {
  name: 'wholedeck-ingestion',
  description: 'Whole-deck synergy discovery (deck-agnostic; args={deck,anchors,shards,cap}). A few Fable shards; EACH shard does BOTH passes in one session — (1) wide scan of its anchors, then (2) deep on its own richest anchors (exhaust the 3-4 card chains) — so no context is reloaded by a separate deep agent. NO adversarial-verify phase: verification is DEFERRED to the compile/goldfish gate (each record\'s engine_test, run by ProgramGate). Pair with gemini_wholedeck.py.',
  phases: [
    { title: 'Discover', detail: 'a few Fable shards; each scans wide then deepens its own richest anchors, serially' },
  ],
}

// Deck-agnostic: pass args = { deck: '<slug>', anchors: [...non-basic names...], shards, cap }.
// Argless defaults use the Selvala deck.
// args may arrive as a parsed object OR a JSON string (workflow-runtime dependent) — handle both.
const ARGS = (typeof args === 'string')
  ? (() => { try { return JSON.parse(args) } catch (e) { return {} } })()
  : (args && typeof args === 'object' ? args : {})
const DECK = ARGS.deck || 'selvala-heart-of-the-wilds'
const DOSSIER = `forge-arena/decks/${DECK}/dossier`
const SELVALA_ANCHORS = ['Allosaurus Shepherd','Ancient Tomb','Arbor Elf','Archdruid\'s Charm','Asceticism','Bala Ged Recovery','Beast Within','Boseiju, Who Endures','Bridgeworks Battle','Castle Garenbrig','Collective Resistance','Concordant Crossroads','Craterhoof Behemoth','Defiler of Vigor','Delighted Halfling','Deserted Temple','Destiny Spinner','Disciple of Freyalise','Dosan the Falling Leaf','Earthcraft','Emerald Medallion','Eternal Witness','Fanatic of Rhonas','Fertile Ground','Finale of Devastation','Frenzied Baloth','Gaea\'s Cradle','Garruk Wildspeaker','Gemstone Caverns','Genesis Hydra','Genesis Wave','Goldvein Hydra','Greater Good','Green Sun\'s Zenith','Heroic Intervention','Hunter\'s Insight','Invasion of Ikoria','Inventors\' Fair','Keen-Eyed Curator','Kenrith\'s Transformation','Khalni Ambush','Kogla, the Titan Ape','Lair of the Hydra','Life\'s Legacy','Lightning Greaves','Lotus Field','Magus of the Candelabra','Managorger Hydra','Momentous Fall','Nature\'s Rhythm','Nykthos, Shrine to Nyx','Nylea, Keen-Eyed','Ojer Kaslem, Deepest Growth','Omnath, Locus of Mana','Overgrowth','Phyrexian Dreadnought','Polukranos, World Eater','Portent Tracker','Reclamation Sage','Return of the Wildspeaker','Rhonas the Indomitable','Sanctum Weaver','Saryth, the Viper\'s Fang','Seedborn Muse','Selvala, Heart of the Wilds','Sheltering Ancient','Shifting Woodland','Silverback Elder','Smuggler\'s Surprise','Sol Ring','Song of the Dryads','Staff of Domination','Surrak and Goreclaw','Swiftfoot Boots','Sylvan Library','Temur Sabertooth','The Great Henge','Turntimber Symbiosis','Umbral Mantle','Utopia Sprawl','Voyaging Satyr','Wild Growth','Wirewood Lodge','Wolfwillow Haven','Yavimaya, Cradle of Growth']
const anchors = (Array.isArray(ARGS.anchors) && ARGS.anchors.length) ? ARGS.anchors : SELVALA_ANCHORS
const NUM_SHARDS = ARGS.shards || 3
const CAP = ARGS.cap || 200
// Fable is the standing default (the strongest tool-using reasoner); override per
// run via args.model (e.g. 'opus' when Fable quota is spent, 'sonnet' to economize).
const AGENT_MODEL = ARGS.model || 'fable'

// The FABLE agents are tool-using: they READ the shared brief + all resources
// themselves. This block names every path (kept in sync with SYNERGY-INGESTION.md).
const INPUTS = `
INPUTS — read these yourself before reasoning (you are a tool-using agent):
- SHARED BRIEF + method + the EXACT compilable output schema + the Forge DSL primer:
  forge-arena/docs/SYNERGY-INGESTION.md  (read this FIRST — it is the contract)
  forge-arena/docs/CANARY-BRIEF-GOLD.md  (the gold brief the contract points to)
- The deck's cards' literal oracle text: ${DOSSIER}/deck-cards.json
- Card-scripts INDEX (name -> absolute .txt path; the fast path, do NOT glob):
  ${DOSSIER}/card-scripts-index.json  — read the actual Forge .txt scripts from these paths
- Deck strategy primer: forge-arena/docs/primers/${DECK}-deckcheck.md
- Rules digest + summary (how Magic actually works):
  forge-arena/docs/research/mtg-rules-digest-conversion.md
  forge-arena/docs/research/mtg-rules-summary.md
- Novelty cross-check (existing combos/synergies — mark novelty against these):
  ${DOSSIER}/{discovered-combos.json, discovered-synergies.json, advisory-combos.json, combos.json}
- External helpers (inference ONLY, never a hard filter): curl EDHREC
  https://json.edhrec.com/pages/cards/<slug>.json and Scryfall
  https://api.scryfall.com/cards/search?q=otag:.../oracle:...
`

const METHOD = `
You are a Magic: The Gathering rules-lawyer analyst doing WHOLE-DECK synergy discovery for the
Commander deck ${DECK} (its full card list is in deck-cards.json). Match the canary bar:
rules-cited, engine-testable synergies with ZERO hallucinations.

NON-NEGOTIABLE METHOD (same as the canary brief you will read in SYNERGY-INGESTION.md):
- Reason HOLISTICALLY over the WHOLE deck at once; do NOT decompose cards into fixed buckets — MTG
  interactions are text-exact and emergent. Read the real oracle text AND the Forge .txt script.
- The Forge SCRIPT is ground truth, not prose (prose hides interactions the script states exactly,
  e.g. Yavimaya's "AddType$ Forest").
- Find CHAINS (3-4 cards), not just pairs. Follow the interaction wherever it legally leads.
- REJECT false positives by reasoning the rules: does the anchor's ability ACTUALLY profit, and is
  every step legal? A legal-but-worthless interaction is a trap — reject it and say why.
- HARD BAR: every partner card MUST be a real card in deck-cards.json (zero hallucinations). If you
  are unsure a card is in the deck, drop the record.
- OUTPUT the COMPILABLE record shape defined in SYNERGY-INGESTION.md (program_class, shape_is_new,
  pieces[{card,role,forge_cost,target}], loop OR win_plan_steps, preconditions, mechanism, produces,
  magnitude, win_relevance, novelty_vs_dossier, confidence, false_positive_check, engine_test
  {fixture,activate,expect_measurable,reject_if}, compile_rank in [0,1]). We compile these into runner
  program JSON later, so the mechanism + pieces + engine_test must be exact enough to build from.
- Existing runner SHAPES (a combo is DATA over a shape): mana_loop, bounce_recur, cast_recur,
  cast_bounce, pairing, engine, win_plan. If a synergy needs a mechanism NO existing shape covers,
  set shape_is_new:true and DESCRIBE the shape precisely (we will build a runner from that description).
`

const RECORD_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['records', 'coverage_note'],
  properties: {
    coverage_note: { type: 'string', description: 'which anchors were richest, ~how many candidates considered each, any anchor with no real synergy (why)' },
    records: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['anchor', 'partner_cards', 'program_class', 'pieces', 'mechanism', 'engine_test', 'compile_rank'],
        properties: {
          anchor: { type: 'string' },
          partner_cards: { type: 'array', items: { type: 'string' } },
          n_cards: { type: 'integer' },
          program_class: { type: 'string', description: 'mana_loop|bounce_recur|cast_recur|cast_bounce|pairing|engine|win_plan|ramp_sequence|other' },
          shape_is_new: { type: 'boolean' },
          pieces: { type: 'array', items: { type: 'object', additionalProperties: false, properties: {
            card: { type: 'string' }, role: { type: 'string' }, forge_cost: { type: 'string' }, target: { type: 'string' } } } },
          loop: { type: 'object', additionalProperties: true },
          win_plan_steps: { type: 'array', items: { type: 'string' } },
          preconditions: { type: 'array', items: { type: 'object', additionalProperties: true } },
          mechanism: { type: 'string', description: 'one sentence, rules-exact why it works (cite CR when subtle)' },
          produces: { type: 'string' },
          magnitude: { type: 'string' },
          win_relevance: { type: 'string' },
          novelty_vs_dossier: { type: 'string', description: 'new|already-known' },
          confidence: { type: 'string', description: 'high|med|low' },
          false_positive_check: { type: 'string' },
          engine_test: { type: 'object', additionalProperties: true, description: 'fixture[], activate[], expect_measurable, reject_if' },
          compile_rank: { type: 'number' },
        },
      },
    },
  },
}

function shard(list, size) {
  const out = []
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size))
  return out
}
function keyOf(r) {
  const cs = [r.anchor, ...(r.partner_cards || [])].filter(Boolean).map(s => s.trim()).sort()
  return cs.join(' + ')
}
const anchorSet = new Set(anchors)
function collect(results) {
  const seen = new Map()
  let hallucinated = 0
  for (const res of results) {
    for (const r of (res.records || [])) {
      if (!r || !r.anchor || !Array.isArray(r.partner_cards)) continue
      // zero-hallucination bar: every partner must be a known non-basic card (basics allowed as "Forest")
      const bad = r.partner_cards.filter(Boolean).some(p => !anchorSet.has(p) && p !== 'Forest')
      if (bad) { hallucinated++; continue }
      const k = keyOf(r)
      const prev = seen.get(k)
      if (!prev || (r.compile_rank || 0) > (prev.compile_rank || 0)) seen.set(k, r)
    }
  }
  return { records: [...seen.values()], hallucinated }
}
// Bounded so a single shard's JSON output can't truncate (~35 detailed records is safe).
const perShardCap = Math.min(35, Math.ceil(CAP / NUM_SHARDS) + 10)

// ---------- DISCOVER: a few Fable shards; each does WIDE then DEEP on its own anchors ----------
// The wide-then-deep passes run SERIALLY inside ONE agent per shard (Ben, 2026-08-03): the agent
// already has the brief + scripts + its anchors loaded and is reasoning about them, so it deepens
// its OWN richest anchors rather than handing off to a fresh agent that reloads everything. No
// separate Phase-II agents, no separate verify — verification is deferred to the goldfish gate.
phase('Discover')
const SHARDS = shard(anchors, Math.ceil(anchors.length / NUM_SHARDS))
log(`Discover: model=${AGENT_MODEL}, deck=${DECK}, ${anchors.length} anchors over ${SHARDS.length} shards (each wide + deep in one session)`)
const results = await parallel(SHARDS.map((batch, i) => () =>
  agent(
    `${METHOD}\n${INPUTS}\n\n===== YOUR ANCHORS (shard ${i + 1}/${SHARDS.length}) =====\n`
    + `Anchor ONLY on these cards (partners may be ANY non-basic deck card):\n`
    + batch.map((a, j) => `${j + 1}. ${a}`).join('\n')
    + `\n\nRead SYNERGY-INGESTION.md + CANARY-BRIEF-GOLD.md, deck-cards.json, the Forge scripts via the`
    + ` index, the primer and rules. Then work in TWO passes over your anchors IN THIS ONE SESSION`
    + ` (you already have everything loaded — do NOT expect a separate agent to deepen your anchors):\n`
    + `  (1) WIDE — scan EVERY one of your anchors for genuine synergies (pairs AND 3-4 card chains).\n`
    + `  (2) DEEP — take the ~3-4 RICHEST anchors from your wide pass and go deeper: exhaust their`
    + ` 3-4 card CHAINS, loop/outlet interactions, and win-con lines. Read every relevant Forge script.\n`
    + `REJECT false positives (say why in false_positive_check); every partner MUST be in`
    + ` deck-cards.json (zero hallucinations); give each record a RUNNABLE engine_test — that test is`
    + ` how we verify it downstream, so make it exact. Return ALL records (wide + deep) in one array:`
    + ` your best ~${perShardCap}, highest compile_rank, quality over quantity, no filler. End with the`
    + ` coverage_note.`,
    { label: `discover:shard${i + 1}`, phase: 'Discover', model: AGENT_MODEL, effort: 'high',
      agentType: 'general-purpose', schema: RECORD_SCHEMA })
)).then(rs => rs.filter(Boolean))

// No silent partials: a dead shard (API error/skip) becomes null and is filtered
// above — say so LOUDLY and surface it in counts so a partial catalog can never
// masquerade as a complete run. Recovery = resume with resumeFromRunId (finished
// shards replay from cache; only dead shards re-run).
const shardsFailed = SHARDS.length - results.length
if (shardsFailed > 0) {
  log(`WARNING: only ${results.length}/${SHARDS.length} shards returned — ${shardsFailed} shard(s) died. PARTIAL catalog; do NOT ship this as the Fable side — resume the run.`)
}

const c = collect(results)
const ranked = c.records.slice().sort((a, b) => (b.compile_rank || 0) - (a.compile_rank || 0))
const capped = ranked.slice(0, CAP)
const dropped_over_cap = Math.max(0, ranked.length - CAP)

const byAnchor = new Map()
for (const r of capped) byAnchor.set(r.anchor, (byAnchor.get(r.anchor) || 0) + (r.compile_rank || 0))
const topAnchors = [...byAnchor.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12).map(e => e[0])
const shapeIsNew = capped.filter(r => r.shape_is_new)
  .map(r => ({ key: keyOf(r), program_class: r.program_class, mechanism: r.mechanism }))

log(`FINAL: ${capped.length} records (cap ${CAP}). hallucinated_dropped=${c.hallucinated}, dropped_over_cap=${dropped_over_cap}, shape_is_new=${shapeIsNew.length}`)
return {
  catalog: capped,
  note: `${SHARDS.length} Fable shards, each wide+deep in one session; no separate deep or verify agents — verification is deferred to the compile/goldfish gate (each record's engine_test, run by ProgramGate).`,
  counts: {
    discovered_valid: c.records.length,
    hallucinated_dropped: c.hallucinated,
    final_capped: capped.length,
    dropped_over_cap,
    shards: SHARDS.length,
    shards_failed: shardsFailed,
  },
  top_anchors: topAnchors,
  shape_is_new_backlog: shapeIsNew,
  coverage_notes: results.map(r => r.coverage_note).filter(Boolean),
}
