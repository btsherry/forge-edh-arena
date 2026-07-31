# Selvala synergy build targets (from the Phase-2b census shortlist)

Turns the 12-item synergy shortlist (SELVALA-ARC.md §PHASE 2b) into concrete
build targets, ranked by value. Grouped by WHERE the change lives: a new runner
shape, the outlet ladder, runner cost/target intelligence, or the prep/assembly
layer. Item numbers reference the census shortlist. Status as of 2026-07-31.

Already shipped: **#1 Genesis Wave force-cast** (live in SelvalaManaLoopRunner's
sink) and its supporting behaviors (green-mana banking override, draw-engine
exclusion from the flip).

---

## TARGET C (HEADLINE, new shape) — blink/bounce ETB-recursion: Eternal Witness + Kogla + Temur Sabertooth
Census #3 ("Sabertooth/Kogla blink-replay of the biggest body") + Ben's explicit
ask (Eternal Witness & Kogla loops). This is the HELD "Sabertooth blink family,"
now unblocked. It is a NEW runner shape distinct from cast_recur (self-recast +
mana refund) and cast_bounce (Tidespout cast-trigger): **bounce/blink a creature
to RE-FIRE its ETB, funded by Selvala's (near-)infinite mana**, converting mana
into repeated ETB value/recursion.
- **Enablers (verify in the 99):** Temur Sabertooth ({1}{G}: return another
  creature you control to hand), Kogla ({1}{G}, return a Human you control to
  hand: return Kogla to hand), possibly others.
- **Recursion payloads:** Eternal Witness (ETB: return a card from graveyard) —
  loop it to recur a spell every cycle; Selvala herself (blink to re-trigger
  her draw-on-biggest-ETB); Kogla (ETB fight = repeatable removal).
### Research verdict (Claude subagent, 2026-07-31) — these are SINKS on the mana loop, not standalone loops
Neither Eternal Witness nor Kogla self-loops in this 99: both are **mana-NEGATIVE
bounce-recursion engines** (~4-8 mana/cycle) that only go infinite when fed by
Selvala's already-online infinite mana. They are OUTLETS on the mana loop, like
Genesis Wave — not loops in their own right. The only repeatable no-tap bounce
outlets in the deck are **Temur Sabertooth** ({1}{G}: bounce any other creature)
and **Kogla** ({1}{G}: bounce a Human — cannot self-bounce, so Kogla-loops
hard-require Sabertooth). Eternal Witness returns to HAND (not infinite
graveyard); Selvala's own draw never fires off the 2-power Witness; Surrak/Henge
counters land on the bounced Witness and are WASTED — only Defiler accumulates.

**The new shape (one runner covers all variants):** per cycle — (1) activate the
bounce outlet targeting the creature [measure: creature Battlefield->Hand, pool
-{1}{G}]; (2) recast the creature [measure: on stack, pool -cast]; (3) let the
ETB/cast trigger resolve [measure: creature back on battlefield AND the payoff
delta realised, strictly positive]. One action per window, yield, measured
delta. Terminate on mana/cap; guards (library non-empty; legal fight target).
Distinct from cast_recur (mana-refund) and cast_bounce (Tidespout cast-trigger):
the "refund" is EXTERNAL infinite mana and the outlet is an activated bounce on
ANOTHER permanent.

**Flagship targets (build the runner once, swap the measured payoff):**
- **C1 (DIRECT KILL): Eternal Witness + Temur Sabertooth + Defiler of Vigor** —
  Defiler's on-cast trigger puts a +1/+1 counter on EVERY creature you control
  (PutCounterAll), and they stay (not bounced) -> infinite board-wide counters
  -> swing lethal with haste. The Witness loop that actually WINS. Payoff delta =
  total counters on your creatures.
- **C2 (draw the deck): E-Wit + Sabertooth + The Great Henge** — Henge draws per
  creature ETB -> draw the library (stop before decking). Payoff delta = hand+1.
- **C3 (removal, not a kill): Kogla + Temur Sabertooth** — infinite ETB fights ->
  destroy every opponent creature (does NOT hit players; needs a separate swing).
  Payoff delta = opponent creature count -1; guard TargetMin 0 (no target -> stop).
- **C4 (redundancy): Kogla-bounces-Witness / E-Wit + Silverback Elder** — weaker
  outlets/payoffs, same runner.
- **Also #1 (the real win it all rides on): mana_loop -> Finale of Devastation**
  (X>=10: fetch a creature AND +X/+X + haste to your board -> swing) is the
  single cleanest kill; the outlet ladder (T2) should prioritise it.
- **Status: RESEARCHED, spec ready.** Build the runner + C1/C2 programs + gates.

---

## Outlet-ladder enhancements (SelvalaManaLoopRunner.chooseOutlet — small, high value)

### T1 — Surrak/Concordant-Crossroads: make the Genesis Wave flip win THIS turn (#8)
Today the flip drops ~40 permanents but they're summoning-sick; the win relies
on surviving to the next combat. Surrak and Goreclaw gives the team STANDING
trample (+ hastes each ETB) and Concordant Crossroads gives haste — with either
flipped in, the board can alpha-strike the SAME turn. Build: after the flip
fires, if a haste source is on board (Surrak/Crossroads) and lethal trample
damage is available, the runner should signal "attack now" rather than hand back
(or ensure the deploy/combat path takes the lethal). Verify: gate asserts a
same-turn WIN, not a next-turn one. Effort: small-medium.

### T2 — Finale of Devastation best-value fetch + Craterhoof (#5)
chooseOutlet already tries Finale, but blindly. Finale should FETCH Craterhoof
Behemoth (which supplies the team trample + X/+X the census corrected), and set
X so the fetched-Craterhoof board is lethal. Build: Finale-path picks Craterhoof
as the search target and sizes X to (mana-affordable AND board becomes lethal);
falls through if the board can't be made lethal. Effort: small.

---

## Runner cost/target intelligence (correctness + the sweep)

### T3 — Restricted-mana awareness (#4)
Some green sources can't pay the loop's GENERIC untap costs: Castle Garenbrig
({6} only for creature spells), Delighted Halfling (legendary spells only),
Gemstone Caverns. The runner's priming/affordability check should not count
restricted mana toward the generic untap. Build: filter restricted sources when
computing payable untap mana (canPayCost already prices per-source, so this is
mostly a governor/priming refinement + a precondition). Effort: small; prevents
false "primed" states. Also a correctness fix for real games.

### T4 — Land-untap-target selection (#7) — needed by the Satyr+Cradle sweep combos
When untapping a LAND (Voyaging Satyr's {T}: untap target land), pick the
HIGHEST-YIELD land (Gaea's Cradle = creatures, Nykthos = devotion), never a
Forest. The Satyr+Cradle combos (sweep) depend on this. Build: the untap-step
target resolver ranks candidate lands by mana yield. Effort: small; unblocks
part of the sweep. Ties to task #70.

### T5 — Omnath green-mana retention (#6)
Omnath, Locus of Mana keeps green mana across steps/phases (AI:RemoveDeck:All in
stock). If Omnath is out, the "phase-bound pool empties" assumption relaxes —
green persists, so the loop/bank can span phases. Build: detect Omnath and treat
banked green as persistent. Effort: small; situational.

---

## Prep / assembly-layer awareness (not combo runners)

### T6 — Tutor-routing by target type (#2)
The Staff/Umbral artifacts can ONLY be found by Genesis Hydra (Permanent.nonLand
-> battlefield) or Inventors' Fair (Artifact -> hand). No creature tutor (GSZ,
Finale, Nature's Rhythm) reaches an artifact. Build: TutorWeights / the pilot's
tutor-selection must route by the missing piece's CARD TYPE — never burn a
creature tutor hunting an artifact half. Effort: medium; prep-layer. Improves
assembly rate for the artifact-half combos (527-2645, 527-2816 via Umbral).

### T7 — Equip-target hazard: Swiftfoot Boots not Lightning Greaves on the Umbral target (#10)
Lightning Greaves grants SHROUD, which blocks OUR OWN Umbral Mantle equip onto
the shrouded creature. Use Swiftfoot Boots (hexproof, still equippable by us).
Build: assembly protection-selection avoids granting shroud to a combo host that
still needs to be equipped/targeted by us. Effort: small; assembly correctness.

### T8 — Sac-target discipline (#11)
Greater Good / Life's Legacy / Momentous Fall sacrifice a creature for value —
sac the biggest EXPENDABLE, never Selvala or a live combo piece. Build: sac-
outlet target selection preserves the commander + assembled pieces. Effort:
small; prevents self-sabotage.

### T9 — Dosan / uncounterability green-light (#12) and Smuggler's Surprise flash (#9)
Hold the all-in combo turn until Dosan the Falling Leaf (or another
uncounterability/stax-through) is online; Smuggler's Surprise can flash 2
creatures / protect / dig at instant speed. Both are timing/protection behaviors
for the pilot's "go" decision. Effort: medium; lowest priority (situational).

---

## Suggested build order
1. **Target C** (Eternal Witness / Kogla blink-recursion) — Ben's priority, new
   shape, highest value; spec from the research report.
2. **T1 + T2** (outlet ladder: same-turn lethal via Surrak/haste; Finale->
   Craterhoof) — small, directly increases conversion.
3. **T4 + T3** (land-untap-target selection; restricted-mana) — unblock the
   Satyr+Cradle sweep and fix a correctness edge.
4. **T6** (tutor-routing) — assembly-rate lift.
5. T5, T7, T8, T9 — situational polish.
