# Sythis, Harvest's Hand — Pilot Primer ("Green White Cushion Castle 25")

## 1. Identity and game plan

- **Sythis** ({G}{W}, 1/1 Legendary Enchantment Creature): *whenever you cast an enchantment spell, gain 1 life and draw a card.* She is the draw engine, not a combo piece. The list is built to feed her: **49 nonland enchantment cards + 2 enchantment lands (Urza's Saga, Valgavoth's Lair) + Katilda's Rising Dawn (disturb)**, 19 non-enchantment spells, 30 lands (+2 MDFC land backs: Bala Ged Sanctuary, Haven of the Harvest).
- **Archetype** (EDHREC for Sythis: Enchantress ≫ Auras > Lifegain > Combo). This build is *Enchantress value → pillow fort → two-card mana combo → convert*, with real subthemes:
  - **Constellation/ETB-copy**: Eidolon of Blossoms, Composer of Spring, Ondu Spiritdancer, Elesh Norn, Springheart Nantuko, Secret Arcade.
  - **Mana loops**: Sanctum Weaver, Gauntlets of Light, Earthcraft, Meticulous Excavation, Concordant Crossroads.
  - **Lifegain → Test of Endurance**: Sythis, Herald of the Pantheon, Daxos, Courser, lifelinkers, Blind Obedience extort.
  - **Aura Voltron** on Sythis/Katilda: Shield of the Oversoul, Strength of the Harvest, Tempest Technique, Nyxborn Hydra, Katilda's Rising Dawn.
  - **Fort/stax-lite**: Sphere of Safety, Solitary Confinement, Blind Obedience, Curse of Exhaustion, Elesh Norn, Arasta.
- **How strong pilots play it**: ramp with 1-mana land auras first, Sythis on turn 2, a second/third enchantress and a cost reducer, then chain cheap enchantments (each draws 2–4). Sanctum Weaver is the best ramp card in the deck. Fort up (Sphere/Confinement) only when the table gets hostile; stay politically quiet until you can win. Tutor the missing combo piece and win at instant speed or behind protection. There are **no counterspells**: you win through protection and timing, not answers.
- **Clock**: fair mode T9–12; combo mode T6–8 with a tutor. Deck-out is a real risk in loops (all enchantress draws are mandatory) — every loop below has a library cap.

## 2. Card roles at a glance

| Role | Cards |
|---|---|
| Draw on enchantment **cast** | Sythis, Argothian Enchantress (shroud), Enchantress's Presence |
| Draw on enchantment **ETB** | Eidolon of Blossoms (constellation), Kenrith's Transformation (cantrip) |
| Cost reducers (generic only) | Herald of the Pantheon (+1 life/cast), Jukai Naturalist (lifelink), Starfield Mystic |
| Land auras (ramp + cast trigger) | Utopia Sprawl (Forest only), Wild Growth, Fertile Ground, Overgrowth, Wolfwillow Haven |
| Big mana | Sanctum Weaver, Serra's Sanctum, Gaea's Cradle, Nykthos, Nyxbloom Ancient, Mirari's Wake, Enduring Vitality, Sol Ring, Thought Vessel, Smothering Tithe, Earthcraft |
| Land velocity | Composer of Spring, Courser of Kruphix, Dryad of the Ilysian Grove, Yavimaya, Shigeki, Windswept Heath |
| Tutors | Enlightened Tutor (top), Idyllic Tutor (hand), Sterling Grove (top, sac), Moon-Blessed Cleric (top), Nature's Rhythm (creature to battlefield), Urza's Saga (→ Sol Ring) |
| Recursion | Replenish, Redress Fate (miracle {3}{W}), Bala Ged Recovery, Hall of Heliod's Generosity, Shigeki channel, Shifting Woodland (delirium copy), Gift of Immortality, Enduring Vitality (self) |
| Combo pieces | Sanctum Weaver, Gauntlets of Light, Earthcraft, Luminarch Ascension, Meticulous Excavation, Concordant Crossroads, Ondu Spiritdancer, Secret Arcade // Dusty Parlor |
| Payoffs / outlets | Luminarch Ascension, Quarantine Field, Destiny Spinner, Nyxborn Hydra, Test of Endurance, Blind Obedience (extort), Daxos (life), Aura Shards, Katilda, Tempest Technique, Strength of the Harvest, Springheart Nantuko, Weaver of Harmony (copier), Wolfwillow Haven |
| Fort | Sphere of Safety, Solitary Confinement, Blind Obedience, Arasta of the Endless Web, Curse of Exhaustion, Elesh Norn |
| Protection | Privileged Position, Sterling Grove, Asceticism, Destiny Spinner (uncounterable), Heroic Intervention, Teferi's Protection, Clever Concealment, Timely Ward, Alseid of Life's Bounty, Shield of the Oversoul, Gift of Immortality |
| Removal | Aura Shards, Grasp of Fate, Banishing Light, Quarantine Field, Song of the Dryads, Kenrith's Transformation, Trickster's Elk (bestow on *their* creature), Eiganjo (channel) |
| Utility lands | Emergence Zone (flash turn), Gemstone Caverns, Reliquary Tower, Hall of Heliod's Generosity, Eiganjo, Nykthos, Shifting Woodland |

## 3. Engines and synergy packages (these dictate sequencing)

### 3.1 Draw engine
- **Cast** triggers (Sythis, Argothian, Presence) fire on casting: a countered enchantment still draws; copies and tokens (Tempest Technique storm copies, Ondu tokens) are not cast → no draw. **ETB** trigger (Eidolon) fires on entering: tokens, Ondu copies, Replenish returns all draw. Every one of these draws is **mandatory** — the number of iterations of any loop is capped by library size (see §4).
- Within a turn: enchantress / cost reducer **first**, then the batch of cheap enchantments (every later spell draws more). Enchantress's Presence before Wild Growth, never after.
- **Secret Arcade** (the {4}{W} door) makes all your nonland permanents and permanent spells enchantments: creatures, Sol Ring, Thought Vessel now draw off Sythis, get cost reduction, are uncounterable under Destiny Spinner, get Dusty Parlor counters, and count for Sanctum Weaver / Serra's Sanctum / Sphere / Katilda / Strength / Destiny Spinner. Arcade + Eidolon = every permanent entering (tokens, Treasures, Angels) is a mandatory draw.
- Redress Fate cannot be tutored (sorcery); if it is the first card you draw in a turn (any draw, including a Sythis draw when the draw step is skipped or already happened... only if genuinely first), the miracle trigger lets you cast it for {3}{W} → all artifacts and enchantments back.
- Reliquary Tower / Thought Vessel: never discard to hand size; always keep one card in hand for Solitary Confinement's upkeep.

### 3.2 Mana engine
- Put land auras on **untapped** lands and tap them immediately. Utopia Sprawl needs a Forest: basics, Temple Garden, Savannah, Canopy Vista, Lush Portico, or any land while Yavimaya / Dryad of the Ilysian Grove is out (if Yavimaya/Dryad leaves, a Sprawl on a non-Forest goes to the graveyard — prefer real Forests).
- **Sanctum Weaver** ({T}: X of one color, X = enchantments you control) is summoning-sick on the turn it enters unless Concordant Crossroads is out. With 6+ enchantments it funds an entire turn alone.
- Serra's Sanctum (W per enchantment — Auras, enchantment creatures, Saga/Lair, Sythis all count), Gaea's Cradle (per creature incl. tokens and Spinner-animated lands), Nykthos (devotion; the deck is very green-heavy). **Nyxbloom Ancient** triples every permanent you tap for mana (lands, Sol Ring → CCCCCC, Weaver → 3X, Sanctum, Nykthos, Treasures). Mirari's Wake adds one extra mana per land tap and is an anthem.
- **Earthcraft as fair ramp**: its cost taps any untapped creature you control — summoning-sick creatures and tokens included (the cost is Earthcraft's, not the creature's own {T} ability, so 302.6 doesn't apply). Each creature = one extra untap of an aura'd basic per turn (Overgrowth Plains = +3 mana per creature).
- Cost reducers cut generic in any cost: X spells, disturb ({3}{W}{W} → {W}{W} with three), bestow, Quarantine Field.
- Enduring Vitality: creatures tap for any color (sick ones can't); after dying it returns as a noncreature enchantment and keeps granting.
- Composer of Spring: every enchantment ETB → land from hand tapped; at 6+ enchantments a **creature** from hand tapped instead (Nyxbloom, Elesh Norn, Ondu, Eidolon for free). Courser plays lands off the top; Dryad gives an extra drop; Shigeki digs a land and mills 3 (delirium / Replenish fodder).

### 3.3 Copy package
- **Ondu Spiritdancer** (3/3): whenever an enchantment enters under your control, one token copy — **each Ondu object may do it once per turn** (a token copy of Ondu is a new object with its own once). Without Arcade, best copies: Nyxbloom Ancient (×9 mana), Sanctum Weaver, Grasp of Fate (token ETB exiles again), Banishing Light, Enchantress's Presence / Eidolon, Sphere / Smothering Tithe / Mirari's Wake, Aura Shards, Gauntlets, land auras (a copied Aura enters attached to a legal object of your choice, no targeting), Song of the Dryads (attach the copy to a second opponent's commander), Kenrith's Transformation, Sterling Grove; even Urza's Saga / Valgavoth's Lair entering (free land tokens). Worthless copies — decline: Luminarch (0 counters), Quarantine Field (X=0), any legendary (legend rule). After a chain you have many Ondus: each may copy a *different* enchantment that turn — hold the "may" for the best one.
- **Springheart Nantuko** bestowed ({1}{G}) on a creature: each landfall, pay {1}{G} → token copy of that creature (else a 1/1 Insect). Hosts: Sanctum Weaver, Eidolon, Ondu (each copy is a fresh Ondu), Nyxbloom, Elesh Norn (no — legendary), never Argothian (shroud) or anything under Sterling Grove's shroud. Landfalls per turn: Composer, Dryad, Courser, Windswept Heath (2), Shigeki. Elesh Norn doubles.
- **Weaver of Harmony** (2/2; {G},{T}, needs to be unsick): copy an activated or triggered ability of an enchantment source you control. Mana abilities can't be targeted (Sanctum Weaver, Serra's Sanctum, Nykthos are **not** copyable). Best targets: Sythis's cast trigger (+1 card, +1 life), Grasp / Banishing Light / Quarantine Field ETB (more exiles), Luminarch's Angel activation (2 Angels for {1}{W}{G}), Luminarch's end-step counter trigger (see 3.7), Meticulous Excavation activation (2 bounces), Destiny Spinner (2 lands), Composer, Springheart landfall, Kenrith's draw, Wolfwillow (2 Wolves), Blind Obedience extort trigger, Asceticism regen, Alseid's activation. It also gives other enchantment creatures +1/+1.
- **Elesh Norn, Mother of Machines**: your triggers caused by a permanent entering fire twice — Eidolon, Daxos, Aura Shards, Composer, Grasp/Banishing/Quarantine Field ETB, Kenrith's, Springheart and Courser landfall, Moon-Blessed Cleric (the second search re-shuffles the first pick — net one card on top). Ondu's once-per-turn effect does **not** double. Opponents' ETB/landfall triggers are switched off entirely.
- **Secret Arcade** also makes creature tokens (Angels, Ondu copies, Spiders, Treasures, Constructs) enchantments — Weaver's X, Sanctum, Sphere and Katilda scale with your board; and Sterling Grove then gives your creatures shroud (no more Auras on them).

### 3.4 Fort, protection — and the Sterling Grove trap
- **Sphere of Safety**: X mana per attacker (X = enchantments) — irrelevant under 5, decisive at 10+. **Solitary Confinement**: skip your draw step (Sythis draws instead), discard a card each upkeep or sacrifice it, you have shroud, all damage to you is prevented (commander damage included; life loss/drain is not). **Blind Obedience**: opposing creatures and artifacts (Treasures, rocks) enter tapped — this also blanks the haste Concordant Crossroads gives their creatures; extort every spell you cast. **Arasta**: a 1/2 reach Spider per opposing instant/sorcery. **Curse of Exhaustion**: on the storm/combo or counterspell player. **Elesh Norn**: opponents' ETBs don't trigger.
- **Sterling Grove gives your OTHER enchantments shroud — from you too.** While it is on the battlefield you cannot: cast Gauntlets of Light, Katilda's Rising Dawn, Shield of the Oversoul, Strength of the Harvest, Tempest Technique, Timely Ward, or a bestowed Nyxborn Hydra / Springheart / Trickster's Elk onto Sythis or any enchantment creature (Sanctum Weaver, Eidolon, Courser, Daxos, Weaver of Harmony, Nyxbloom, Katilda's Rising Dawn host…); target them with Meticulous Excavation, Alseid, or Asceticism's regeneration; and under Secret Arcade you can't target *any* of your nonland permanents. It does **not** interfere with Ondu/Arcade, Earthcraft, Luminarch, or Weaver of Harmony (it targets abilities). Treat Grove as an instant-speed tutor that protects until you need to target: **{1}, sacrifice → put the missing piece on top → cast any enchantment → Sythis draws it.** Do this at the end step of the opponent before you, or as the first action of your combo turn (it also frees the shroud in the same motion). Sac it in response to targeted removal on Grove itself.
- **Privileged Position** (hexproof vs opponents only — no downside; with Grove out neither can be targeted). **Asceticism** (creature hexproof; {1}{G}: regenerate vs destroy). **Destiny Spinner** (creature and enchantment spells can't be countered — cast it before Gauntlets/Ondu/Arcade into open blue mana). **Shield of the Oversoul** on Sythis: she is green *and* white → +2/+2, flying, indestructible. **Timely Ward**: flash only if targeting Sythis (respond to destroy effects; not exile/−X/−X). **Gift of Immortality**: when the creature dies it returns and Gift re-attaches at the next end step; on Sythis, **decline the command-zone move (903.9a)** when she dies so Gift returns her tax-free. **Alseid** ({1}, sac: a creature or enchantment you control gains protection from a color): protection from white or green makes your own white/green Auras fall off (704.5m) — Gauntlets, Rising Dawn, Shield, Strength, Tempest, Timely Ward, Gift, Hydra, Springheart, Kenrith's — so versus Swords/Path/Beast Within on an aura'd creature use Heroic Intervention or Timely Ward instead; Alseid is for blue/black/red removal, or for making Sythis unblockable by a color on the kill turn (again: only colors that don't match her Auras).
- **Instants**: Heroic Intervention (destroy-based wipes and any targeted removal on a permanent; not Farewell / mass bounce / edicts), Teferi's Protection (answers everything including lethal alphas; also the Test of Endurance shield), Clever Concealment (convoke with any creatures — summoning-sick and tokens count; phase out the chosen nonland permanents; Grasp/Banishing/Quarantine Field keep their exiles while phased out; lands stay exposed).

### 3.5 Removal usage
- **Aura Shards**: every creature ETB (tokens included) → destroy an artifact or enchantment. Targets are chosen when the trigger goes on the stack; if the only legal targets are yours, pick one and decline the "may" on resolution. Early: their mana rocks; always: combo artifacts/enchantments and enchantment-hate pieces.
- **Grasp of Fate** (best nonland permanent from each opponent), **Banishing Light**, **Quarantine Field** (X scales with Sanctum/Weaver mana; Norn doubles; Weaver of Harmony copies; Excavation can rebuy on your turn but returns the old exiles).
- **Song of the Dryads** answers *any* permanent — an opposing commander becomes a colorless Forest with no command-zone escape; also utility lands, Rhystic-Study-class enchantments, planeswalkers. **Kenrith's Transformation**: creature → vanilla 3/3 Elk plus a draw. **Trickster's Elk** bestowed onto their creature → vanilla 3/3; when it leaves you get a 3/3 Elk. **Eiganjo** channel: 4 damage to an attacker/blocker, {1} cheaper per legendary creature you control (Sythis, Katilda, Shigeki, Arasta, Daxos, Elesh Norn).

### 3.6 Recursion and tutors
- **Replenish** (all enchantment cards; Auras enter attached to legal objects you choose or stay in the graveyard). **Hall of Heliod's Generosity** ({1}{W},{T}: enchantment card to top — draw it with the draw step or a Sythis trigger). **Bala Ged Recovery** (anything to hand, or a land drop). **Shigeki channel** {X}{X}{G}{G} (X nonlegendary cards back). **Shifting Woodland** (delirium — Shigeki mills, fetches and cantrips fill the types): becomes a copy of a permanent card in your graveyard until end of turn — Sanctum Weaver, Serra's Sanctum or Gaea's Cradle (if the original isn't on the battlefield), Nyxbloom Ancient (triple mana this turn), Eidolon.
- Katilda's Rising Dawn is exiled instead of going to the graveyard — cast it via disturb once; it is not Replenish fodder.
- **Nature's Rhythm** X: 2 → Sanctum Weaver / Weaver of Harmony / Destiny Spinner / Springheart / Composer / Shigeki; 3 → Courser / Dryad / Enduring Vitality / Katilda / Moon-Blessed Cleric; 4 → Eidolon / Arasta; 5 → **Ondu** (starts the chain if Arcade is out — it enters, it wasn't cast) / Elesh Norn; 7 → Nyxbloom. Harmonize from the graveyard: tap Katilda (power = enchantments) or Nyxbloom (5) to strip the generic — {G}{G}{G}{G} for a second use.
- **Urza's Saga** chapter III finds only Sol Ring (the only {0}/{1} artifact); chapter II Constructs grow with Treasures/rocks.

### 3.7 Voltron and lifegain
- **Katilda, Dawnhart Martyr** ({1}{W}{W}, flying, lifelink, P/T = Spirits + enchantments you control, counts herself) is routinely 8/8+ on turn 4 — beater, blocker, Test-of-Endurance accelerant. From the graveyard, disturb {3}{W}{W} → **Katilda's Rising Dawn** Aura (+X/+X, flying, lifelink; an enchantment spell → Sythis draws): on Sythis → 21 commander damage in 1–2 hits. Add Shield of the Oversoul, Strength of the Harvest (+1/+1 per creature or enchantment), Tempest Technique (cast it **last** in a chain: k spells before it → k+1 Aura tokens, each +1/+1 per enchantment, and each token raises the enchantment count for everything else), Nyxborn Hydra bestow ({X}{G}{G}: +X/+X, reach, trample; becomes an X/X creature if the host dies). One opponent per combat.
- **Lifegain rates**: +1 (Sythis) +1 (Herald) per enchantment cast; +1 per creature ETB/death (Daxos); +1 per landfall (Courser); lifelink from Jukai/Alseid/Katilda; +1 per opponent per spell via extort. **Test of Endurance**: win at your upkeep with 50+.
- **Luminarch discipline**: at each *opponent's* end step, +1 quest counter if you lost no life during *that opponent's turn* — life paid on **your** turn (Temple Garden shock, Windswept Heath, Bountiful nothing) is irrelevant; never crack Heath, pay life, or take damage on their turns (Sphere/Confinement do this for you). 4 counters normally takes into the second round; with Weaver of Harmony copying the trigger at one end step it is exactly one full round (Luminarch out before the first opponent's end step, Weaver untapped and unsick).

## 4. Combos — execution lines

Conventions: fix the iteration count N *before* starting and stick to it (CR 732.2a — announce a finite loop, stop by your own optional choice); a mana pool must be created and spent inside one step or phase (500.5 — passing priority within the phase is fine, letting the phase end is not); after any opponent leaves, re-derive targets, opponent count and APNAP before the next iteration, and stop when the last opponent is gone.

### 4.1 Sanctum Weaver + Gauntlets of Light → arbitrarily large mana (Spellbook 1355-1995)
- **Prereqs**: Weaver on the battlefield, untapped, not summoning-sick (or Crossroads out); Gauntlets attached (a targeted Aura → Sterling Grove must **not** be out when you cast it; Asceticism/Position hexproof don't interfere); X = enchantments you control ≥ 4 (net +1 per cycle) — realistically ≥ 6.
- **Cycle**: tap Weaver → add X of one color (mana ability, no response window) → activate Gauntlets' "{2}{W}: Untap this creature" from the pool (uses the stack; opponents may respond) → repeat. Net per cycle X−3; after k cycles plus a final tap the pool is **k(X−3)+X**. Keep 1 W spare per cycle; alternate colors as needed. Instant speed.
- **Best window**: the end step of the opponent right before you (Angels/tokens made then can attack on your turn — no haste needed), or your precombat main with Crossroads.
- **Outlets** (same phase):
  - **Luminarch Ascension** (4 counters): {1}{W} per 4/4 flying Angel. Sizing: ceil(sum of opponents' life ÷ 4) + a blocker margin — e.g. 40 Angels = 80 mana ≈ 10 cycles at X=10.
  - **Quarantine Field** X = number of opposing nonland permanents ({2X}{W}{W} minus reducers), sorcery speed → total lock, win over the following turns.
  - **Destiny Spinner**: {3}{G} per **untapped** land → X/X trample haste (X = enchantments): (#lands)×X trample damage split across opponents; e.g. 8 lands × 15 = 120. Keep lands untapped by paying with the Weaver pool; animated lands can die in combat.
  - **Nyxborn Hydra** X (haste with Crossroads) or bestowed onto Sythis/Katilda: one opponent per combat.
  - Extort kill (4.5), Meticulous Excavation rebuys (Grasp / Banishing / Quarantine Field / Ondu / Moon-Blessed Cleric), Shigeki digs (with Crossroads), Weaver of Harmony copies.
- **Protection**: removal aimed at Weaver → Heroic Intervention (hexproof + indestructible), Asceticism regeneration (destroy only), Alseid protection from the removal's color (never white or green while Gauntlets is attached). If Weaver is removed in response to Gauntlets, Gauntlets is countered on resolution (608.2b) and goes to the graveyard — Hall of Heliod / Replenish get it back.

### 4.2 Secret Arcade + Ondu Spiritdancer → N Ondu tokens (Spellbook 3729-6023)
- **Prereqs**: Secret Arcade's {4}{W} door unlocked **first** (cast that half, or cast Dusty Parlor {2}{W} earlier and later pay {4}{W} as a sorcery to unlock — unlocking is not a cast). Then an Ondu must **enter**: cast it ({4}{W} minus reducers — under Arcade it is an enchantment spell, so Sythis draws and Spinner protects it), Composer of Spring at 6+ enchantments, Nature's Rhythm X=5, a Springheart copy, a Gift of Immortality return, or Meticulous Excavation bounce-and-recast if Ondu was already on the battlefield (an Ondu already in play when Arcade lands does **not** start the chain).
- **Chain**: Ondu enters as an enchantment → its own trigger → token copy (also an enchantment via Arcade) → the token's own trigger → next token… Only the newest token's trigger creates anything (each Ondu object once per turn); decline the "may" on the N-th token to stop. Killing the current Ondu in response doesn't stop the pending trigger (the copy uses last-known information); removing Arcade ends the chain after the pending token.
- **Caps**: with Eidolon of Blossoms out each token is a mandatory draw (two with Norn) → N ≤ library − 1 — bounce Eidolon first ({2}{W}, Excavation) if you need more. Tokens are not cast → no Sythis draws.
- **Payoffs per token**: Aura Shards destroy (N covers every opposing artifact/enchantment), Daxos +1 life (+2 with Norn) → Test of Endurance at your next upkeep, Composer land/creature drops, Eidolon draws, Gaea's Cradle +G each, Earthcraft (each untapped token untaps a basic), +1 to Weaver's X / Sanctum / Sphere / Katilda / Strength / Spinner, and combat: 3/3 bodies with haste under Crossroads (4/4 with Mirari's Wake, 5/5 with Weaver of Harmony — they are enchantment creatures). Alternative to Crossroads: sacrifice Emergence Zone at the previous opponent's end step, cast Arcade/Ondu with flash, and the tokens attack on your turn.
- **Kill math**: three opponents at 40 need 24 unblocked 5/5s (8 each); make 40+ when the library allows.

### 4.3 Earthcraft + Luminarch Ascension (4 counters) + a basic that taps for {1}{W}-payable 2+ mana (Spellbook 2597/2757 family)
- **Enablers**: on a basic **Plains** — Wild Growth (W+G), Fertile Ground (W+any), Wolfwillow Haven (W+G), Overgrowth (W+GG, +1 G surplus), Mirari's Wake (WW), Nyxbloom (WWW, +1 W surplus); on a basic **Forest** — Utopia Sprawl choosing white (G+W), Fertile Ground choosing white.
- **Cycle**: tap the basic → {1}{W} → Luminarch → 4/4 Angel (untapped) → Earthcraft: tap the Angel (cost; summoning sickness irrelevant), untap the basic → repeat. Angels end tapped; each cycle's surplus (land output − 2) buys extra Angels that stay untapped. All instant speed → do it at the end step of the opponent right before you: N Angels untap in your untap step and attack. In your own main phase only the surplus Angels can attack (with Crossroads).

### 4.4 Sanctum Weaver + Meticulous Excavation + Concordant Crossroads (Spellbook 1350-1355; the haste enabler is required)
- Your turn only (Excavation), Grove off the battlefield. **Cycle**: tap Weaver (X) → {2}{W}: return Weaver to hand → recast ({1}{G}; {G} with any reducer) → enters with haste. Net X−5 (X−4 with a reducer): X ≥ 6 (5) to profit; at X=5 with a reducer it is mana-neutral but still generates every trigger.
- **Per cycle**: enchantment cast (Sythis draw +1 life, Argothian draw, Presence draw, Herald +1 life, Dusty Parlor 2 counters, storm +1, extort option) + enchantment/creature ETB (Eidolon draw, Daxos +1, Aura Shards, Composer). Draws are mandatory: **k ≤ floor((library − 1) / D)**, D = draws per cycle. Uses: dig D×k cards (find Gauntlets / Arcade / Test / Crossroads), gain up to 6k life → Test of Endurance, drain k per opponent via extort, storm k into Tempest Technique (k+1 Auras), destroy k artifacts/enchantments.
- If Weaver+Gauntlets is already the mana source, any cheap enchantment can be the recast object instead ({2}{W} + its cost per Sythis trigger: Wild Growth {G}, Alseid {W}, Meticulous Excavation itself {W}).

### 4.5 Unbounded extort kill: Weaver+Gauntlets pool + Meticulous Excavation + Blind Obedience + Sol Ring
- Main phase, empty stack: {2}{W}: return Sol Ring → cast Sol Ring ({1}) → extort trigger, pay {W/B} → each opponent loses 1, you gain 3. **5 mana per point; N = highest opponent life.** No draws unless Secret Arcade is out (Sol Ring becomes an enchantment spell → enchantress draws → library cap; bounce Arcade to hand first if so). Substitute rebuy objects: Thought Vessel {2}, Herald {1}{G} (+Daxos), Starfield Mystic {1}{W}, Composer {1}{G}, Katilda {1}{W}{W}, Moon-Blessed Cleric {2}{W} (a top-deck tutor per pass — with a Weaver pool, Cleric + Excavation + one cheap enchantment recast is "tutor any enchantment to hand", e.g. Blind Obedience itself). Never Argothian (shroud).

### 4.6 Test of Endurance
- Reach 50 (Ondu chain + Daxos; 4.4 storm; natural drift), then survive to your upkeep. The trigger has an intervening "if" (603.4): 50+ at trigger **and** at resolution. Pass priority with it on the stack; if an opponent responds with damage or drain, respond with **Teferi's Protection** (life total can't change until your next turn — Test phasing out is irrelevant, the ability on the stack is independent of its source). Solitary Confinement pre-empts damage entirely. Remove "can't gain life"/"can't win" permanents first (Grasp/Banishing/Quarantine Field/Song).

### 4.7 Voltron one-shot
- Sythis + Katilda's Rising Dawn (+X/+X flying lifelink) or Shield of the Oversoul (flying, indestructible) + Strength / Tempest Technique / Nyxborn Hydra → 21+ flying (or trample) commander damage to one player per combat. Impossible under Sterling Grove (shroud) — sac Grove first. Track commander damage per opponent; only combat damage counts.

## 5. Win lines ranked

1. **Weaver + Gauntlets → Luminarch Angels** at the end step before your turn (or main phase + Crossroads). Needs Weaver unsick, Gauntlets, ≥5 enchantments, Luminarch with 4 counters, no Grove. Cleanest and instant-speed.
2. **Ondu + Arcade → N tokens** → Crossroads/Emergence Zone alpha, or Daxos → Test next upkeep, or Aura Shards wipe + Cradle mana into everything in hand.
3. **Earthcraft + Luminarch + aura'd basic** → Angels at the end step before your turn.
4. **Weaver + Gauntlets → Quarantine Field lock / Spinner lands / Hydra one-shot / extort loop (4.5).**
5. **Test of Endurance** by natural drift behind Sphere/Confinement.
6. **Fair**: Katilda / Voltron Sythis, Luminarch one Angel per turn, Springheart copies, Spinner one land per turn, Wolfwillow's Wolf.

Fallbacks: no Weaver → 3, 2, 6; no Luminarch counters → 4, 2; no Arcade → single Ondu copies (Nyxbloom / Grasp / Weaver); board wiped → Replenish / Redress Fate / Hall / Bala Ged / Shigeki channel, recast Sythis (+{2} per cast from the command zone).

## 6. Sequencing

- **T1**: untapped green source (Forest, Temple Garden — shocking on your turn costs nothing for Luminarch, Savannah, Branchloft, Command Tower, Bountiful Promenade) + Utopia Sprawl / Wild Growth, or Sol Ring. Gemstone Caverns starts on the battlefield when you're not first (exile the worst card).
- **T2**: Sythis (with Sol Ring/Sprawl: Sythis + a 1-drop). Only delay her if you'd rather Argothian/Herald into a bigger T3.
- **T3**: second enchantress or reducer, then cheap enchantments; land auras on untapped lands; land drop first (Composer only uses lands from hand — keep one).
- **T4–6**: fort when needed (Sphere at ≥6 enchantments; Confinement when hand ≥3), Position/Asceticism in removal-heavy pods, Luminarch early behind Sphere/Confinement (its clock is slow), Serra's Sanctum turns into X spells / Katilda / Quarantine Field; tutor the missing combo piece.
- **Combo turn**: Grove sac for the last piece at the previous end step; Destiny Spinner down before Gauntlets/Ondu into blue; go off at the end step (Weaver+Gauntlets, Earthcraft) or precombat main (Ondu chain, Spinner, Hydra, Excavation loops). Hold Heroic Intervention / Teferi's Protection mana when the pool allows.
- **In-turn order**: enchantress / reducer → mana auras (then tap) → batch of enchantments → top-deck tutors mid-chain when the next Sythis draw will pull the card → Tempest Technique last → X spells; extort with spare W. Never let a phase end with Weaver mana floating.
- **Weaver of Harmony each turn**: copy Sythis's first trigger unless a bigger ETB (Grasp / Quarantine Field / Composer / Springheart) is coming; while Luminarch is building, save it for an opponent's end step.
- **Excavation on your turn**: dodge exile aimed at Sythis (to hand → recast for {G}{W}, no tax — only if Grove isn't out); rebuy Grasp / Banishing Light / Quarantine Field ETBs.

| Situation | Tutor target (Idyllic / Enlightened / Grove / Cleric) |
|---|---|
| No second draw engine | Enchantress's Presence |
| Engine up, mana short | Sanctum Weaver (then Gauntlets) |
| Weaver + ≥5 enchantments + outlet | Gauntlets of Light |
| Aggro table / need time | Sphere of Safety → Solitary Confinement |
| Ondu in hand or on board | Secret Arcade |
| Wipe colors open, big board | Privileged Position (hold HI in hand) |
| Earthcraft + basics + time | Luminarch Ascension, then a land aura |
| At 45+ life | Test of Endurance |
| Nature's Rhythm | X=2 Weaver · X=5 Ondu (Arcade out) / Elesh Norn · X=7 Nyxbloom |
| Urza's Saga III | Sol Ring |

## 7. Mulligans (multiplayer: first mulligan free; later ones bottom m−1)

- **Keep 7**: 2–4 lands with an untapped green source on T1 and ≥2 plays at ≤2 mana (land aura, enchantress, reducer, Sol Ring, tutor). Ideal: 3 lands, Sprawl/Wild Growth, Argothian/Herald/Presence, one tutor or protection.
- **Free mulligan** on: ≤1 land; ≥5 lands with no ≤2-drop; spells all 4+ (Nyxbloom, Norn, Ondu, Sphere, Redress, Quarantine Field, Test, Curse). When bottoming, drop the most situational (Redress Fate, Test, Curse, Clever Concealment, Song).
- Keep 6 with 2 lands + Sol Ring/Sprawl and a Sythis plan; keep 5 lands + Sythis + one cheap enchantment (Sythis is card flow). Land count is 30 (+2 MDFCs) — never keep 1-landers.

## 8. Threat assessment, interaction, protection triage

- **Existential**: mass enchantment removal — Farewell / Merciless Eviction (exile: only Teferi's Protection or Clever Concealment save you), Bane of Progress / Back to Nature / Tranquility / Austere Command / Cleansing Nova (Heroic Intervention). Read colors: white or green with 4–6 open → keep HI up once you've deployed 6+ enchantments; hold one redundant engine in hand; Replenish/Redress are the rebuild.
- **Serious**: graveyard hate (kills Replenish, Redress, Hall, Shigeki, Katilda disturb, Bala Ged); Rule-of-Law effects (answer with Shards / Grasp / Banishing / Quarantine Field); Aven Mindcensor vs tutors; Blood Moon (fetch basics early; Sprawl on a basic Forest); Torpor-Orb effects (stop Ondu/Aura Shards/Eidolon-on-creatures); counterspells (Spinner first; Curse of Exhaustion the counter player).
- **Removal priority** for Grasp / Banishing / Quarantine Field / Song: (1) the fastest combo's engine or any enchantment/tutor-hate piece; (2) visible wipe enablers; (3) the biggest evasive threat or the commander that pressures you; (4) the leader's mana engines. Aura Shards: their rocks early, combo pieces always.
- **Politics**: don't be the first to threaten; Sphere/Confinement push aggression elsewhere; Song / Kenrith's / Trickster's Elk on the commander that targets you.
- **Protect, in order**: Sanctum Weaver once you have ≥5 enchantments; Luminarch at 3–4 counters; Sythis while she's the only draw engine; Secret Arcade when Ondu is coming; Confinement/Sphere when the table is aggressive. Hold HI vs destroy wipes, Teferi's Protection vs Farewell / lethal alpha / the Test upkeep, Concealment vs exile wipes, Timely Ward (flash) vs targeted destroy on Sythis. Track commander damage against you (Confinement prevents it) and poison.

## 9. Rules gotchas — do-not list

1. Sterling Grove shrouds your other enchantments from **you** — sac it before Gauntlets, Excavation, or any Aura on Sythis/enchantment creatures.
2. Alseid's protection from white or green strips your own Auras (704.5m).
3. Every enchantress / Eidolon draw is mandatory: cap loops at library − 1; Sythis + Arcade makes every permanent spell draw; Arcade + Eidolon makes every permanent entering draw.
4. Weaver mana empties at the end of the step/phase (500.5): generate and spend in one phase; passing priority inside the phase is fine.
5. Ondu's once-per-turn is per Ondu object; the chain needs an Ondu to **enter** while Arcade is active; Norn doesn't double it; copies of Luminarch / Quarantine Field / legendaries are worthless.
6. Test of Endurance is intervening-if: 50+ at trigger and resolution; Teferi's Protection in response locks it.
7. Luminarch checks life loss during each opponent's own turn — pay life only on your turn.
8. Concordant Crossroads is symmetric — deploy it the turn you attack (Blind Obedience blanks their haste by tapping their creatures on entry).
9. Meticulous Excavation only on your turn; Sythis bounced to hand recasts for {G}{W} with no tax.
10. Gift of Immortality on Sythis: decline the command-zone move when she dies.
11. An Aura whose creature is removed in response fizzles to the graveyard (608.2b) — answer the removal with HI before it resolves.
12. Solitary Confinement: your draw step is skipped, you must discard each upkeep, you have shroud.
13. Earthcraft and convoke tap summoning-sick creatures; Sanctum Weaver, Weaver of Harmony, Shigeki, and Enduring Vitality's granted tap do not (302.6) — Crossroads fixes that.
14. Composer's creature mode needs six enchantments; the creature enters tapped.
15. Utopia Sprawl falls off if its land stops being a Forest.
16. Sythis, Katilda, Arasta, Shigeki, Elesh Norn are legendary — token copies die to the legend rule (keep the one with counters/Auras).
17. Storm copies, Tempest Technique copies and Ondu tokens are not cast (no Sythis draw); Tempest copies may only enchant creatures you control.
18. Katilda's Rising Dawn is exiled instead of hitting the graveyard — not Replenish fodder.
19. Redress Fate can't be tutored; miracle only on the first card drawn in a turn.
20. Emergence Zone gives flash to spells only; Excavation's own-turn restriction still applies.
