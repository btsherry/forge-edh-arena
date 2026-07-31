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
- **Why it needs the runner:** stock AI will not assemble a mana-fed blink loop;
  and the loop's PRODUCT (infinite recursion of X, infinite fights, or a draw
  engine) must be measured per cycle and converted.
- **Status: AWAITING RESEARCH** (a Claude subagent is mapping the exact loop
  lines, mana math, win/payoff, and the cleanest shape). Fill this section from
  its report, then spec the runner + gate. Likely the highest-value new work.

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
