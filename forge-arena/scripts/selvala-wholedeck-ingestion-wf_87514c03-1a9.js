export const meta = {
  name: 'wholedeck-ingestion',
  description: 'Whole-deck synergy discovery (deck-agnostic; pass args={deck,anchors}): Phase I wide (sharded) -> evaluate richest anchors -> Phase II deep -> adversarial verify -> validate/dedup -> cap 200 compilable records. DISCOVERY ONLY, no compile/no code. Argless defaults reproduce the Selvala gold run.',
  phases: [
    { title: 'PhaseI-Wide', detail: '10 Fable shards over all 85 anchors' },
    { title: 'PhaseII-Deep', detail: 'deeper re-run of the richest ~12 anchors' },
    { title: 'Verify', detail: 'adversarially verify + validate the top records' },
  ],
}

// Deck-agnostic: pass args = { deck: '<slug>', anchors: [...non-basic card names...] }.
// The Selvala defaults below reproduce the gold run when called with no args.
const DECK = (typeof args === 'object' && args && args.deck) || 'selvala-heart-of-the-wilds'
const DOSSIER = `forge-arena/decks/${DECK}/dossier`
const SELVALA_ANCHORS = ['Allosaurus Shepherd','Ancient Tomb','Arbor Elf','Archdruid\'s Charm','Asceticism','Bala Ged Recovery','Beast Within','Boseiju, Who Endures','Bridgeworks Battle','Castle Garenbrig','Collective Resistance','Concordant Crossroads','Craterhoof Behemoth','Defiler of Vigor','Delighted Halfling','Deserted Temple','Destiny Spinner','Disciple of Freyalise','Dosan the Falling Leaf','Earthcraft','Emerald Medallion','Eternal Witness','Fanatic of Rhonas','Fertile Ground','Finale of Devastation','Frenzied Baloth','Gaea\'s Cradle','Garruk Wildspeaker','Gemstone Caverns','Genesis Hydra','Genesis Wave','Goldvein Hydra','Greater Good','Green Sun\'s Zenith','Heroic Intervention','Hunter\'s Insight','Invasion of Ikoria','Inventors\' Fair','Keen-Eyed Curator','Kenrith\'s Transformation','Khalni Ambush','Kogla, the Titan Ape','Lair of the Hydra','Life\'s Legacy','Lightning Greaves','Lotus Field','Magus of the Candelabra','Managorger Hydra','Momentous Fall','Nature\'s Rhythm','Nykthos, Shrine to Nyx','Nylea, Keen-Eyed','Ojer Kaslem, Deepest Growth','Omnath, Locus of Mana','Overgrowth','Phyrexian Dreadnought','Polukranos, World Eater','Portent Tracker','Reclamation Sage','Return of the Wildspeaker','Rhonas the Indomitable','Sanctum Weaver','Saryth, the Viper\'s Fang','Seedborn Muse','Selvala, Heart of the Wilds','Sheltering Ancient','Shifting Woodland','Silverback Elder','Smuggler\'s Surprise','Sol Ring','Song of the Dryads','Staff of Domination','Surrak and Goreclaw','Swiftfoot Boots','Sylvan Library','Temur Sabertooth','The Great Henge','Turntimber Symbiosis','Umbral Mantle','Utopia Sprawl','Voyaging Satyr','Wild Growth','Wirewood Lodge','Wolfwillow Haven','Yavimaya, Cradle of Growth']
const anchors = (typeof args === 'object' && args && Array.isArray(args.anchors) && args.anchors.length)
  ? args.anchors : SELVALA_ANCHORS

// The FABLE agents are tool-using: they READ the shared brief + all resources
// themselves. This block names every path (kept in sync with SYNERGY-INGESTION.md).
const INPUTS = `
INPUTS — read these yourself before reasoning (you are a tool-using agent):
- SHARED BRIEF + method + the EXACT compilable output schema + the Forge DSL primer:
  forge-arena/docs/SYNERGY-INGESTION.md  (read this FIRST — it is the contract)
- All 88 cards' literal oracle text: ${DOSSIER}/deck-cards.json
- Card-scripts INDEX (name -> absolute .txt path; the fast path, do NOT glob):
  ${DOSSIER}/card-scripts-index.json  — read the actual Forge .txt scripts from these paths
- Deck strategy primer: forge-arena/docs/primers/selvala-heart-of-the-wilds-deckcheck.md
- Rules digest + summary (how Magic actually works):
  forge-arena/docs/research/mtg-rules-digest-conversion.md
  forge-arena/docs/research/mtg-rules-summary.md
- Novelty cross-check (existing combos/synergies — mark novelty against these):
  ${DOSSIER}/{discovered-combos.json, discovered-synergies-fable.json, advisory-combos.json, combos.json}
- External helpers (inference ONLY, never a hard filter): curl EDHREC
  https://json.edhrec.com/pages/cards/<slug>.json and Scryfall
  https://api.scryfall.com/cards/search?q=otag:.../oracle:...
`

const METHOD = `
You are a Magic: The Gathering rules-lawyer analyst doing WHOLE-DECK synergy discovery for the
Commander deck ${DECK} (its full card list is in deck-cards.json). This matches a validated canary
(the canary found 42 rules-cited, engine-testable synergies with ZERO hallucinations). Match that bar.

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

// ---------- PHASE I: WIDE (all 85 anchors, canary-depth shards) ----------
phase('PhaseI-Wide')
const P1_SHARDS = shard(anchors, 9)   // ~10 shards of <=9 anchors each = canary depth
log(`Phase I: ${anchors.length} anchors over ${P1_SHARDS.length} shards`)
const p1 = await parallel(P1_SHARDS.map((batch, i) => () =>
  agent(
    `${METHOD}\n${INPUTS}\n\n===== YOUR ANCHORS FOR THIS SHARD (${i + 1}/${P1_SHARDS.length}) =====\n`
    + `Anchor ONLY on these cards (partners may be ANY non-basic deck card):\n`
    + batch.map((a, j) => `${j + 1}. ${a}`).join('\n')
    + `\n\nDo the full method: read SYNERGY-INGESTION.md, deck-cards.json, the Forge scripts via the`
    + ` index, the primer and rules. Emit ONE record per genuine synergy your anchors form. Prefer`
    + ` quality over quantity — no filler, no hallucinated partners. End with the coverage_note.`,
    { label: `p1:shard${i + 1}`, phase: 'PhaseI-Wide', model: 'fable', effort: 'high',
      agentType: 'general-purpose', schema: RECORD_SCHEMA })
)).then(rs => rs.filter(Boolean))

// flatten + validate (partner must be a real anchor/card name) + dedup by anchor+sorted-partners
const anchorSet = new Set(anchors)
function keyOf(r) {
  const cs = [r.anchor, ...(r.partner_cards || [])].filter(Boolean).map(s => s.trim()).sort()
  return cs.join(' + ')
}
function collect(results) {
  const seen = new Map()
  let hallucinated = 0
  for (const res of results) {
    for (const r of (res.records || [])) {
      if (!r || !r.anchor || !Array.isArray(r.partner_cards)) continue
      const partners = r.partner_cards.filter(Boolean)
      // zero-hallucination bar: every partner must be a known non-basic card (basics allowed as "Forest")
      const bad = partners.some(p => !anchorSet.has(p) && p !== 'Forest')
      if (bad) { hallucinated++; continue }
      const k = keyOf(r)
      const prev = seen.get(k)
      if (!prev || (r.compile_rank || 0) > (prev.compile_rank || 0)) seen.set(k, r)
    }
  }
  return { records: [...seen.values()], hallucinated }
}
const c1 = collect(p1)
log(`Phase I: ${c1.records.length} unique valid records (${c1.hallucinated} hallucinated-partner records dropped)`)

// evaluate the richest anchors: sum compile_rank per anchor, take top 12
const byAnchor = new Map()
for (const r of c1.records) {
  byAnchor.set(r.anchor, (byAnchor.get(r.anchor) || 0) + (r.compile_rank || 0))
}
const topAnchors = [...byAnchor.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12).map(e => e[0])
log(`Phase II targets (richest anchors): ${topAnchors.join(', ')}`)

// ---------- PHASE II: DEEP (richest anchors, deeper chains) ----------
phase('PhaseII-Deep')
const P2_SHARDS = shard(topAnchors, 3)
const p2 = await parallel(P2_SHARDS.map((batch, i) => () =>
  agent(
    `${METHOD}\n${INPUTS}\n\n===== DEEP PASS — YOUR ANCHORS (${i + 1}/${P2_SHARDS.length}) =====\n`
    + `These anchors were the RICHEST in the wide pass. Go DEEPER: exhaust their 3-4 card CHAINS,`
    + ` their loop/outlet interactions, and any win-con lines. Read every relevant Forge script.\n`
    + batch.map((a, j) => `${j + 1}. ${a}`).join('\n')
    + `\n\nReturn records in the SAME compilable schema. Only genuine, rules-exact, non-hallucinated`
    + ` synergies. Note novelty vs the dossier. End with the coverage_note.`,
    { label: `p2:deep${i + 1}`, phase: 'PhaseII-Deep', model: 'fable', effort: 'high',
      agentType: 'general-purpose', schema: RECORD_SCHEMA })
)).then(rs => rs.filter(Boolean))

// merge Phase II into the pool (dedup keeps the higher compile_rank)
const c2 = collect([...p1, ...p2])
log(`After Phase II merge: ${c2.records.length} unique valid records (${c2.hallucinated} cumulative hallucinated dropped)`)

// ---------- VERIFY: adversarially verify the top records ----------
phase('Verify')
const ranked = c2.records.slice().sort((a, b) => (b.compile_rank || 0) - (a.compile_rank || 0))
const toVerify = ranked.slice(0, Math.min(48, ranked.length))
const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['real', 'reason'],
  properties: {
    real: { type: 'boolean', description: 'true only if the synergy genuinely profits, every step is legal, and every card is really in the deck' },
    reason: { type: 'string' },
    corrected_compile_rank: { type: 'number' },
  },
}
const verified = await parallel(toVerify.map(r => () =>
  agent(
    `${INPUTS}\n\nAdversarially VERIFY this proposed Selvala synergy. Default to real=false unless it`
    + ` genuinely holds. Check: (1) every card in {anchor + partner_cards} is REALLY in deck-cards.json;`
    + ` (2) the mechanism is rules-legal and the anchor ACTUALLY profits (read the Forge scripts);`
    + ` (3) the engine_test would actually confirm it. Record:\n${JSON.stringify(r)}`,
    { label: `verify:${keyOf(r).slice(0, 40)}`, phase: 'Verify', model: 'fable', effort: 'high',
      agentType: 'general-purpose', schema: VERDICT_SCHEMA })
    .then(v => ({ record: r, verdict: v }))
)).then(rs => rs.filter(Boolean))

const verifiedKeys = new Map(verified.map(v => [keyOf(v.record), v.verdict]))
let refuted = 0
const survivors = ranked.filter(r => {
  const v = verifiedKeys.get(keyOf(r))
  if (v && v.real === false) { refuted++; return false }
  if (v && typeof v.corrected_compile_rank === 'number') r.compile_rank = v.corrected_compile_rank
  return true
}).sort((a, b) => (b.compile_rank || 0) - (a.compile_rank || 0))

// ---------- CAP 200 ----------
const capped = survivors.slice(0, 200)
const dropped_over_cap = Math.max(0, survivors.length - 200)
const shapeIsNew = capped.filter(r => r.shape_is_new)
  .map(r => ({ key: keyOf(r), program_class: r.program_class, mechanism: r.mechanism }))

log(`FINAL: ${capped.length} records (cap 200). refuted=${refuted}, dropped_over_cap=${dropped_over_cap}, shape_is_new=${shapeIsNew.length}`)
return {
  catalog: capped,
  counts: {
    phase1_valid: c1.records.length,
    phase2_merged_valid: c2.records.length,
    hallucinated_dropped: c2.hallucinated,
    verified: verified.length,
    refuted_dropped: refuted,
    final_capped: capped.length,
    dropped_over_cap,
  },
  top_anchors: topAnchors,
  shape_is_new_backlog: shapeIsNew,
  coverage_notes: [...p1, ...p2].map(r => r.coverage_note).filter(Boolean),
}
