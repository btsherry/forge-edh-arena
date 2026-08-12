# Y'shtola, Night's Blessed — Pilot's Field Guide

**Archetype: Esper draw-go control-combo.** EDHREC's data for this commander (currently its #1 commander, ~50k decks) splits her into Control, Spellslinger, Lifegain/Lifedrain, Burn, and Combo builds; competitive lists play her as a proactive control shell with free-spell triggers, stax bears, and a compact artifact win. **This 100 is that build**: 12 counterspells, 8 silence/stax effects, a taxing draw suite (Rhystic Study, Mystic Remora, Esper Sentinel, Smothering Tithe), and two-card wins in Isochron Scepter + Dramatic Reversal and two extra-turn locks. You are the pod's control deck. Your game shape: cheap draw engines turns 1–3 → draw-go middlegame where every mana value 3+ spell drains the table → one protected combo turn, or an extra-turn/protection lock that ends the game in announced repetitions.

---

## 1. Commander operating manual

Y'shtola: {1}{W}{U}{B}, 2/4 Cat Warlock, vigilance.

**Trigger 1 — the drain:** whenever you cast a noncreature spell with mana value 3+, she deals 2 to *each* opponent and you gain 2. That's a 6-point table swing plus 2 life per qualifying cast in a 4-pod.
- It's a **cast trigger** — the damage and lifegain happen even if the spell gets countered.
- **Mana value never changes with alternative or additional costs.** Force of Will pitched for free is still MV 5 → triggers. Fierce Guardianship and Deadly Rollick cast free (commander on field) → trigger. Force of Negation free on their turn → triggers.
- **Traps that do NOT trigger her:** Cyclonic Rift overloaded (MV 2), Damn overloaded (MV 2), Final Showdown with every spree mode (MV 1), Insatiable Avarice (MV 1), Pact of Negation (MV 0), and all Scepter copies of Dramatic/Narset's Reversal (MV 2).
- **The full qualifying census (25 spells):** Aetherflux Reservoir, Anguished Unmaking, Archenemy's Charm, Archmage's Charm, Deadly Rollick, Farewell, Fell the Profane, Fierce Guardianship, Force of Negation, Force of Will, Hagra Mauling, Necropotence, Panoptic Mirror, Render Silent, Reverse the Polarity, Sea Gate Restoration, Sink into Stupor, Smothering Tithe, Supreme Verdict, The One Ring, Time Warp, Toxic Deluge, Utter End, Yawgmoth's Will, and Explore the Vastlands (Wandering Archaic's back face; the front face is a creature spell and does not trigger).

**Trigger 2 — the ledger:** at the beginning of **each** end step (every turn, not just yours), if **any player — you included** — lost 4+ life that turn, you draw a card. One draw per end step maximum.
- Life lost is **gross**, not net: payments count, lifegain doesn't offset it.
- Guaranteed self-enables: any **two** Trigger-1 casts in one turn (each opponent lost 4); Necropotence paying ≥4; Toxic Deluge X≥4; Ancient Tomb + fetch + a pay-3-life MDFC land add up fast; Anguished Unmaking (3) plus any 1 more.
- Free rider: any combat scrum dealing 4+ to someone on *anyone's* turn draws you a card at that turn's end step. In a bloody pod she's a Phyrexian Arena that costs nothing.
- **Timing rule this hinges on:** the trigger has an intervening "if" (CR 603.4) — the 4-life threshold must already be met when the end step *begins*. Life paid during the end step misses that turn's check. Corollary for Necropotence: **pay Necro in your second main phase**, never in your end step — main-phase payments both satisfy the check and deliver the exiled cards at *this* turn's end step; end-step payments delay delivery a full rotation and miss the draw.

**Deployment:** turn 3–4 normally, turn 2 off Dark Ritual/rocks when the pod is passive. Toughness 4 dodges small sweeps and Orcish Bowmasters pings; vigilance lets her chip for 2 and still block. Don't over-protect her — recasting at 5 then 7 is affordable — but Neurok Stealthsuit's {U}{U} instant-speed attach fizzles targeted removal on her when it matters, and she is the glue for both triggers, so keep her alive on combo-adjacent turns.

---

## 2. Win conditions, ranked

1. **Dramatic Scepter → Aetherflux Reservoir** — same-turn kill, all at instant speed once Reservoir is down.
2. **Dramatic Scepter → The One Ring draw-out → Reservoir** — same kill, one more step.
3. **Isochron Scepter + Narset's Reversal + Time Warp** — repeated-turns lock, needs ~6–7 mana per turn.
4. **Panoptic Mirror + Time Warp** — free repeated turns after 10 mana of setup; fragile to artifact removal.
5. **The One Ring + Meticulous Excavation** — protection lock + attrition; the recast itself clocks the table.
6. **Fair plan:** Urza's Saga Constructs, Consecrated Sphinx, Nezahal beats + drain triggers.

---

## 3. Combo lines — exact execution

### 3.1 Dramatic Reversal + Isochron Scepter (primary; [CSB 4821-5261](https://commanderspellbook.com/combo/4821-5261/))

**Pieces:** Isochron Scepter with Dramatic Reversal imprinted (imprint happens only on Scepter's ETB, exiling from **hand**), plus nonland mana permanents that tap for **3+ total**. Sustaining sets: Mana Vault alone; Sol Ring + any other rock; Arcane Signet + Thought Vessel + a Mox. Treasures from Smothering Tithe **jump-start but don't sustain** — they sacrifice for mana and don't come back; the recurring 3 must come from rocks that stay.

**Loop (all instant speed):** tap rocks floating ≥3 → activate Scepter ({2}, {T}) → on resolution copy Dramatic Reversal and cast the copy free → copy resolves, untapping **all nonland permanents you control** (rocks, Scepter, One Ring, Wishclaw, creatures) → repeat. Net ≥ +1 floating mana and +1 spell cast per iteration. Stay in one phase — floating mana empties between phases.

**Payoff A — Reservoir on battlefield:** each loop cast gains life equal to spells cast this turn, so n iterations from s prior casts gain n·s + n(n+1)/2 life. **Announce: "30 iterations"** — ≥465 life from a cold start. Then activate Aetherflux Reservoir **one at a time**: pay 50 life, 50 damage to an opponent. Three activations clears a standard pod; budget two per opponent sitting above 50 life. Life is banked even if they kill Reservoir between activations, so bank first, then shoot.

**Payoff B — The One Ring on battlefield:** the loop untaps it; between iterations tap it (add a burden counter, draw cards equal to counters). t taps = t(t+1)/2 total cards — **count your library exactly and stop while remaining draws ≤ cards left** (drawing from an empty library loses). Draw into Reservoir, cast it mid-loop (your main phase, stack empty — fine), then Payoff A.
- **Safety check before mass draws:** an opposing Orcish Bowmasters converts every draw into a ping at you — 40 draws is lethal. Kill it first or bank Reservoir life *before* drawing. An opposing Mystic Remora feeds them a card per iteration; usually win through it, but know it's happening.

**Payoff C — neither on board:** the loop still makes unlimited mana. Convert it to a tutor: activate Wishclaw Talisman mid-loop (it untaps every iteration) for Reservoir — giving Wishclaw away is irrelevant mid-win — or cast Demonic Tutor/Insatiable Avarice. With Meticulous Excavation down you get **full library access**: activate Wishclaw, respond with Excavation bouncing it, tutor resolves, opponent-gains-control does nothing (it left the battlefield), recast (fresh 3 counters), loop mana pays for everything. Mind colored costs: lands don't untap in this loop, so {W}/{B} for Excavation/Wishclaw must come from Moxen, Signet, treasures, or lands you left up.

**Interruption map:** killing Scepter or a rock *in response to the activation* still lets that one copy be cast (the imprinted card sits in exile independently), but ends the loop — and **Dramatic Reversal is then gone forever**; Buried Ruin rebuys only the Scepter shell, and the deck has no second copy. Their Tishana's Tidebinder can counter the Scepter activation and permanently blank it. Countering the Dramatic copy (it *is* cast, so it's counterable) halts that iteration. Because of all this: **combo with cover** (Section 5, silence suite) or with 1–2 counters held, and prefer executing when the scariest interaction holder is tapped out. If Reservoir is already down, the entire kill is instant speed — a fine window is the end step of the player right before you.

### 3.2 Isochron Scepter + Narset's Reversal + Time Warp ([CSB 11-5261--41](https://commanderspellbook.com/combo/11-5261--41/))

**Setup:** Scepter with **Narset's Reversal** imprinted. Each of your turns, with Time Warp in hand:

1. Main phase: cast Time Warp ({3}{U}{U}; {2}{U}{U} with Baral out).
2. While it's on the stack, activate Scepter ({2}, {T}) → resolution: copy Narset's Reversal, cast the copy targeting your Time Warp.
3. Narset's copy resolves first: puts a **copy** of Time Warp on the stack (this copy is *not cast* — no triggers from it) and returns the original Time Warp **to your hand**.
4. The Time Warp copy resolves: extra turn.

Cost per turn: ~{4}{U}{U} with Baral, {5}{U}{U} without. Time Warp never leaves your hand for long, so artifact removal doesn't cost you the win the way it does with Mirror. Each turn's Time Warp **cast** triggers Y'shtola: 2 to each opponent, 2 to you. Opponents never untap but do get priority every cycle — keep countermagic up during the chain. **Announce: "I repeat this each turn while mana allows; on triggers alone opponents at 40 die in 20 repetitions — with Y'shtola and Construct attacks, roughly 8–12."** Not literally infinite: it's bounded by your mana each turn; state it as a per-turn repeating line.

Off-combo, Narset's-on-Scepter is a {2}-per-turn value engine: copy any opposing instant/sorcery (their tutor, their removal, their extra turn — you may choose new targets) and bounce the original to their hand.

### 3.3 Panoptic Mirror + Time Warp ([CSB 2468-4872](https://commanderspellbook.com/combo/2468-4872/))

**Setup:** cast Mirror ({5}, triggers Y'shtola), then {5}, {T} to imprint Time Warp from hand — an activated ability, usable at instant speed. **Best window: the end step of the opponent right before you**, minimizing the gap before your upkeep. Then every upkeep: Mirror trigger → cast the copy free (MV 5 → Y'shtola trigger) → extra turn, forever, at zero ongoing cost.

**Risks:** if Mirror dies with Warp imprinted — including in response to the imprint activation — **Time Warp is exiled permanently**. The upkeep copy is *cast*, so it's counterable each cycle. Choose Mirror when the table is light on instant-speed artifact removal; choose the 3.2 line into open blue mana. Alternate imprints worth knowing: Supreme Verdict (uncounterable wipe every upkeep = creature lock), Yawgmoth's Will (MV 3 — a graveyard turn every upkeep), Cyclonic Rift (base mode only — a free cast can't also use overload's alternative cost).

### 3.4 The One Ring + Meticulous Excavation ([CSB 1350-3363](https://commanderspellbook.com/combo/1350-3363/))

**Each of your turns for {6}{W}:** activate Excavation ({2}{W}, your turn only) returning The One Ring to hand → recast it ({4}) → its cast trigger gives you **protection from everything until your next turn**, covering the entire table rotation. Bonuses per cycle: burden counters reset (upkeep loss resets to 0, taps draw from 1 again) and the {4} recast **triggers Y'shtola** — the lock itself drains 2/turn per opponent while you sit behind it.

Sequencing inside your turn: the upkeep burden-loss trigger resolves before you can profitably bounce (it uses last-known counters even if you respond by bouncing), so eat it, then bounce+recast in main 1. **What the lock does NOT stop:** protection prevents damage, targeting, and attacks against you — it does **not** stop loss of life (Exsanguinate-style drains), sacrifice/discard edicts, or "wins the game" combos. This is a stall that pairs with attrition, not a win by itself; keep countering actual win attempts through it.

### 3.5 Support lines

- **Wishclaw without giveaway:** activate Wishclaw ({1}, {T}, counter) → respond with Excavation bouncing it → tutor resolves, control never changes, recast later with 3 fresh counters. A repeatable Demonic Tutor for ~4 mana a turn. Without Excavation, activate Wishclaw **only on the turn you win** (or behind Grand Abolisher, though they still get it for their turns).
- **Narset's from hand on your own Time Warp:** two extra turns from one Warp ({5} + {2}, two Y'shtola triggers) — copy resolves for turn one, original returns to hand, recast next turn for turn two. A strong fair line to find a combo piece.
- **Yawgmoth's Will turn:** MV 3 (triggers her); rebuy Dark Ritual, Demonic Tutor, Swords, counters, even Time Warp from the yard on your win turn. Everything exiles after — spend the yard, don't save it.
- **Scepter re-imprint:** Excavation bounces Scepter on your turn → recast {2} → imprint something new from hand. This is how you pivot a value imprint (Swords/Silence) into Dramatic Reversal later.

---

## 4. Synergy packages (what dictates sequencing)

**Tax-draw suite:** Mystic Remora turn 1 is your best opener — pay upkeep 2–3 times, then either let it go or **Excavation-bounce it on your turn in response to the cumulative upkeep trigger** and recast for {U} with zero age counters. Rhystic Study and Smothering Tithe land best turns 2–4 while opponents can't afford the tax; Tithe's treasures fund Scepter activations, the One Ring lock, and Mirror's imprint. Esper Sentinel taxes their first noncreature spell every turn. The One Ring, Necropotence, Consecrated Sphinx, and Nezahal are your heavy engines — deploy with cover, and note Nezahal protects itself (discard 3 to blink; it dodges **your** wipes too and returns tapped at the next end step). No-max-hand-size (Reliquary Tower, Thought Vessel, Nezahal, Sea Gate Restoration) is what makes Necro piles and Sphinx stacks keepable.

**Silence suite (win-turn cover):** Silence and kicked Orim's Chant (also stops attacks) blank a turn; Abeyance cantrips and also stops non-mana activated abilities; Grand Abolisher is the permanent version and the best combo cover — but all of these except Abeyance/Chant only stop *spells*, and Ranger-Captain's sacrifice stops only *noncreature* spells: none of them stop an opposing flash **creature** like their own Tishana's Tidebinder. Abolisher does stop their artifact/creature/enchantment *activations* on your turn. Any of Silence/Chant/Swords/Swan/Veto/Abeyance/Muddle also make fine interim Scepter imprints — a Silence copy cast in the most dangerous opponent's upkeep for {2} blanks their whole turn, every rotation.

**Tutor web:** Demonic Tutor and Wishclaw get anything; Muddle the Mixture transmutes for **exactly MV 2** — that's *either combo half* (Isochron Scepter, Dramatic Reversal, Narset's Reversal) plus Drannith, Baral, Signet, Vessel, Cyclonic Rift. Ranger-Captain fetches Esper Sentinel or Weathered Wayfarer. Urza's Saga III fetches Sol Ring / Mana Vault / Chrome Mox / Mox Diamond (and its Constructs are your best beaters — they count every rock). Weathered Wayfarer (you're draw-go; you'll qualify) fetches Saga, Ancient Tomb, Bojuka Bog. Scheming Symmetry is a {B} "win-now" tutor: cast it only when you'll win or lock **before the chosen opponent's next draw**. Insatiable Avarice full-spree on yourself = {3}{B}{B}: tutor to hand +2 extra cards, lose 3 (ledger fuel — one more life loss that turn draws you another card).

**Bowmasters web:** flash it in response to their wheels/big draw spells. Your own enablers feed it: Loran's tap (opponent draws → ping + amass, you draw too — and with Consecrated Sphinx out, Loran's gift draws *you* two), Insatiable Avarice pointed at an opponent (3 pings + 3 life loss toward the ledger).

**Stax aiming guide:** Drannith Magistrate does the most **early, before commanders land** — it stops commander casts from the zone, graveyard casts, cascade and impulse-exile casts. Nevermore names an opposing commander *still in the command zone* or a known win piece (Thassa's Oracle, Underworld Breach). Curse of Exhaustion goes on the storm/combo player — one spell a turn strangles them (abilities still work). Wandering Archaic taxes every opposing instant/sorcery {2} or you copy it. Remember their Drannith blocks *your* commander from the zone: Final Showdown mode 1 or removal clears the path.

**Mana notes:** Boseiju makes your Time Warp / Yawgmoth's Will uncounterable on the win turn; Mistrise Village covers **any** spell type (Scepter, Reservoir, One Ring) but always enters tapped here — play it a turn ahead. Gemstone Caverns only matters when you're not the starting player. Ancient Tomb, fetches, and pay-3-life MDFC lands all feed the ledger. Bojuka Bog enters tapped — deploy it the turn *before* the graveyard deck goes off, not the turn of.

---

## 5. Interaction guide

- **Hold free interaction once Y'shtola is out:** Fierce Guardianship and Deadly Rollick cost nothing and *trigger her*. Force of Negation is free only on their turns. Pact of Negation's bill is due at your **next upkeep — which arrives immediately during your own extra-turn chains**; keep {3}{U}{U}.
- **Tishana's Tidebinder is your premium flex answer:** counter a fetchland activation, a planeswalker activation, Urza's Saga III, an opposing One Ring tap — or a **Thassa's Oracle ETB trigger** (the trigger, not the spell) — and it permanently blanks artifact/creature/planeswalker sources.
- **Reverse the Polarity mode 1 counters ALL other spells** — including yours below it. It's not protection for your own spell; it's the counter-war nuke when everything else on the stack is theirs (their win attempt plus their protection pile).
- **Uncounterable removal** (Void Rend) and **Dovin's Veto/Supreme Verdict** win counter-wars by fiat. Mana Drain ramps your next main into One Ring/Mirror/Reservoir. Archmage's Charm mode 3 steals their Sol Ring, Esper Sentinel, or Mystic Remora.
- **Wipe selection:** Supreme Verdict into open blue; Toxic Deluge X=3 clears most boards **while sparing your 2/4 commander** (X≥4 also buys the end-step draw if you need the card more than her); Damn overloaded at 4; Farewell surgically — never exile artifacts while your own rocks matter; Final Showdown can blank abilities *and* save Y'shtola *and* wipe in one modular cast; Cyclonic Rift overloaded the end step before your win or wipe turn.
- **Don't wipe to parity** — your board is usually just Y'shtola and Constructs; wipe to stop lethal or when you're the clear beneficiary.

---

## 6. Mulligans

Keep hands with: **2–3 lands (or 1–2 plus a rock/Dark Ritual) + one engine + one cheap interaction.**
- Snap keeps: turn-1 Mystic Remora with lands; Dark Ritual + Necropotence + a land + a white/blue source; Esper Sentinel + Rhystic Study curve-outs; Urza's Saga counts as ramp *and* a tutor.
- Combo pieces in the opener are **not** keep criteria — Muddle/Demonic/Wishclaw find them later; engines can't be tutored efficiently and must be drawn.
- Ship: engine-less goodstuff piles; hands whose first play is turn 3+; all-interaction hands with no card-advantage source (you'll trade down and run dry); 2 lands + a fistful of 4-drops.
- Gemstone Caverns is only a card when you're not going first — if it's your keep's ramp and you're first, count it as a colorless land, not acceleration.

---

## 7. Threat assessment

Default archenemy ladder: **fast combo** (they race your slow drain — counter their tutors and win attempts) → **heavy stax** (Winter Orb-style lockouts cripple a draw-go deck — remove the lock pieces, not their creatures) → **go-wide aggro** (you hold four wipes and Rift; manageable, just don't fall below wipe mana) → **lifegain/pillow** decks last (your combos ignore life totals; only Reservoir cares — budget two 50-damage shots for anyone above 50).

Counter-budget rule: from turn 4 onward reserve one counter (the free ones make this cheap) for **opposing win attempts first, opposing bomb engines second, protecting your own combo third** — and invert that order on your win turn. Expect mild archenemy treatment once Y'shtola has ticked three or four triggers; her lifegain, vigilance, and toughness 4 keep you stable, and the One Ring lock or a wipe resets aggression pointed your way.

---

## 8. Sequencing and posture

- **Default posture from turn 3 on is draw-go:** untapped mana, act at end of turn. Tap out only for engine turns (Necro, One Ring, Tithe, Sphinx), ideally with Abolisher down, a counter up, or a reactive-light pod.
- Typical opening: T1 land + Remora/Sentinel/Sol Ring; T2 rocks/Baral/Drannith; T3–4 Y'shtola or a taxing enchantment plus held interaction.
- **Pair your MV 3+ casts:** two in one turn guarantees the end-step draw. When two answers are otherwise equal and mana is free, prefer the MV 3+ one — each is 6 table damage, 2 life, and ledger progress.
- Scepter cast on empty value (imprinting Swords/Swan/Silence/Chant) is fine mid-game; Excavation re-imprints it later. Imprinting your **only** Dramatic Reversal telegraphs the win and stakes it on the Scepter's survival — do it the turn you go off, or behind cover, whenever possible.
- Track every player's gross life loss every turn — end-of-turn draws are free wins you can miss by simply not counting.

**Win-turn checklist:**
1. Count total mana including treasures; confirm the loop's *sustaining* rocks make 3+.
2. Cover: Silence-effect cast, Abolisher already down, or 2 counters held. Remember none of these stop flash creatures.
3. Payoff on board or reachable (Reservoir / One Ring / Wishclaw-Excavation access).
4. Check for opposing Bowmasters before any mass-draw line.
5. Keep one answer specifically for the kill-Scepter-in-response play — it's their best out.
6. Turns route: Mirror into a removal-light table, Narset's-Scepter into a counter-light one.

**Protection priorities, ranked:** (1) the win attempt on the stack; (2) Isochron Scepter with Dramatic imprinted — the deck's single Dramatic Reversal is unrecoverable if the Scepter dies with it exiled; (3) Y'shtola — engine glue, but recastable; (4) Necro/One Ring/Tithe — Hall of Heliod's Generosity rebuys the enchantments, Buried Ruin rebuys artifacts.

---

## 9. Rules corner (only what lines hinge on)

- Y'shtola's end-step trigger has an intervening "if" (CR 603.4): the 4-life condition is checked when the end step begins — end-step life payments miss it.
- Mana value ignores how the spell was paid for: pitch spells trigger her; overload/spree casts don't gain MV.
- Scepter and Mirror **copies are cast** — they're counterable and they count for Aetherflux and (if MV 3+) Y'shtola. A copy that Narset's Reversal *creates of its target* is put on the stack, not cast — no triggers.
- Destroying Scepter/Mirror with its ability or trigger already on the stack doesn't stop that iteration (the imprinted card is still in exile) — but the imprinted card is lost with the artifact from then on.
- Additional costs (kicker) may be paid on free casts: a Scepter copy of Orim's Chant can be kicked for {W}.
- Wishclaw's "an opponent gains control" does nothing if Wishclaw left the battlefield before the ability resolved; counters reset when it's recast.
- The One Ring's protection trigger requires *casting* it (Excavation recast qualifies); its upkeep loss uses last-known counters even if it leaves in response.
- Final Showdown's ability-stripping mode locks in the affected creatures at resolution (CR 611.2c) — it cannot pre-blank a creature still on the stack; answer a Thassa's Oracle with a counterspell or Tidebinder on the trigger.
- "Protection from everything" for you as a player stops damage, targeting, and attacks — not loss of life, sacrifice, discard, or alternate win conditions.

---

**Sources:** [EDHREC — Y'shtola, Night's Blessed](https://edhrec.com/commanders/yshtola-nights-blessed) (theme/deck-count data), [EDHREC cEDH filter](https://edhrec.com/commanders/yshtola-nights-blessed/cedh), [Draftsim deck guide](https://draftsim.com/yshtola-edh-deck/), [Scryfall card page](https://scryfall.com/card/fic/7/yshtola-nights-blessed), [Moxfield cEDH primer](https://moxfield.com/decks/gY3V4PwjgECmUgvrX1vvrQ/primer), plus the CommanderSpellbook combo pages linked inline.
