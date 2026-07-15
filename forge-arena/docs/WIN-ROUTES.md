# Win Routes — route definitions & per-deck classification rules (v1)

**Purpose.** The LethalityPlanner converts proven-infinite resources into ended games. This spec defines (a) the closed set of win-conversion routes, each terminating in an **engine-enforced end state**, and (b) deterministic rules that classify a deck's Commander Spellbook `produces` features onto those routes. Classification runs **per deck at preflight** (Gate 3), cache-first against a global feature→route mapping library — never as a global vocabulary sweep. Rules are versioned (`win-routes/1`); unmatched features are flagged `unroutable` and queued for prep-time LLM classification (Gate 3.5 machinery) or human review. The Gate 3.6 stall autopsy feeds observed conversion failures back into this spec.

**Closure property.** A route is only valid if its verification predicate ends the game through one of the terminal states the engine actually enforces (verified in T0):

| Terminal state | Engine source |
|---|---|
| `GameLossReason.LifeReachedZero` | `Player.checkLoseCondition()` |
| `GameLossReason.CommanderDamage` (21) | `Player.java` cmdr-damage map check |
| `GameLossReason.Poisoned` (10) | `Player.checkLoseCondition()` |
| `GameLossReason.Milled` (draw from empty library) | `Player.checkLoseCondition()` |
| `GameLossReason.SpellEffect` / `GameEndReason.WinsGameSpellEffect` | scripted "wins/loses the game" cards |

A "combo" that produces resources but reaches none of these is **not a win** — it is a stall (Gate 3.6) or a lock (timeout risk, below).

## 1. Route definitions

Sketch fields: *converts* (feature classes that trigger consideration), *terminal*, *timing*, *verification predicate* (what forward-sim must prove before the line is attempted), *hazards*.

| Route | Converts | Terminal | Timing | Verification predicate | Hazards |
|---|---|---|---|---|---|
| ORACLE_WIN | self deck-access + Thassa's Oracle / Lab Man class in 99 | WinsGameSpellEffect | this turn | oracle effect castable + library-empty condition reachable | counterspell window on the oracle trigger |
| SPELL_LOSE | "each opponent loses the game" class | SpellEffect | this turn | effect castable with produced resources | hexproof-from-nothing; almost none |
| DIRECT_DAMAGE_LOOP | infinite damage (players), infinite ETB/death/storm/draw triggers + ping payoff in 99 | LifeReachedZero | this turn | payoff on battlefield or castable; "each opponent" or repeatable targeting verified | damage prevention/replacement; protection from color |
| LIFELOSS_DRAIN | infinite death/sac/lifegain triggers + Blood Artist class payoff | LifeReachedZero | this turn | drain payoff present; loop count × drain ≥ table life | non-damage — dodges prevention; very few outs |
| COMBAT_DAMAGE | "infinite combat damage" features | LifeReachedZero | this turn (combat available) | attack step reachable (entry_phase!), unblocked/trample path per opponent | fog effects; entered post-combat = dead line |
| SPREAD_COMBAT | infinite pump/tokens + haste source | LifeReachedZero | this turn | per-opponent damage assignment ≥ life + blocker buffer; haste verified | wraths at instant speed; missing haste = wait a cycle |
| COMMANDER_DMG_SEQUENCE | infinite pump + commander combat-capable | CommanderDamage | one opponent per combat | 21 through blockers per target; survival across table cycle priced | slowest lethal route; removal between combats |
| EXTRA_COMBATS | infinite combat phases/steps | LifeReachedZero | this turn | lethal across N combats, N bounded | preferred over INFINITE_TURNS when both available |
| INFINITE_TURNS | extra-turn loop features | via combat route per turn | K turns | **not shortcut-able** — compress to "lethal within K combats," K ≤ ceil(table life / per-turn damage); each turn physically played | wall-clock cost; loop pieces exposed K turns |
| MILL_OPPONENTS | infinite mill (opponents), "exile each opponent's library" | Milled (theirs) | their next draw | library-empty achievable; survives until their draw step | they must *draw* — mill alone kills nobody; eldrazi shuffle-backs |
| FORCED_DRAW_OUT | infinite card draw / draw triggers *for opponents* | Milled (theirs) | this turn if forced draws, else their turn | forced-draw count ≥ their library | symmetric versions deck yourself (see guards) |
| POISON_LOOP | infect/toxic/poison features + damage loop | Poisoned | this turn | 10 counters per opponent deliverable | cheapest threshold (10, not 40); proliferate accelerates |
| SETUP_LETHAL | "life total becomes 1" class | LifeReachedZero (with any ping) | this turn | any 1-damage follow-up available | none once resolved |
| STATIC_THRESHOLD | Simic Ascendancy / Helix Pinnacle class + infinite counters/mana | WinsGameSpellEffect | your next upkeep | threshold reachable now; survival to upkeep priced | telegraphed; one removal spell undoes it |
| BANK_AND_HOLD | anything (patience gate) | none | n/a | explicit non-route; telemetry records rejected routes + why | holding too long is how stalls happen — Gate 3.6 watches this |

**Route selection order** is deck-contextual, not global: prefer same-turn terminal routes; among those, fewest additional cards needed, then least interactable (LIFELOSS_DRAIN > DIRECT_DAMAGE > combat routes). INFINITE_TURNS is a route of last resort when a same-turn route exists.

## 2. Feature classification rules (`win-routes/2`)

*v2 amendment (2026-07-15, first Gate 3 feedback-loop entry — flagged `unroutable` by the real Urza dossier): `Prevent all damage that would be dealt to you` → GUARD; `You have protection from everything` (pattern `protection from everything`) → GUARD; the bare feature `Lock` → LOCK_DISRUPTION. Inserted after rule 2; numbering below unchanged for readability. Code form: `RouteRules.java` (kept in lockstep).*

Ordered, first-match-wins, case-insensitive. Applied per deck to the `produces` features of **included** combos only. Categories: `WIN_TRIGGER`, `LETHAL`, `RESOURCE`, `GUARD`, `TABLE_HAZARD`, `BOARD_CONTROL`, `LOCK_DISRUPTION`, `CARD_CLASS`, `UNROUTABLE`.

| # | Pattern (regex, i) | Category | Route / note |
|---|---|---|---|
| 1 | `can't lose the game` | GUARD | enables oracle-free deck draw & symmetric effects |
| 2 | `^draw the game$` | GUARD | intentional-draw escape; never a win |
| 3 | `(damage to all players\|lifeloss for all players\|card draw for all players\|draw triggers for all players\|lifegain for all players)` | TABLE_HAZARD | symmetric — self-lethal without a guard |
| 4 | `self-mill` | RESOURCE | GY fuel; hazard: Milled without GY/oracle payoff |
| 5 | `win(s)? the game` | WIN_TRIGGER | ORACLE_WIN / STATIC_THRESHOLD |
| 6 | `opponent(s)?.* loses the game` | WIN_TRIGGER | SPELL_LOSE |
| 7 | `poison\|infect\|toxic` | LETHAL | POISON_LOOP |
| 8 | `damage to (all\|most\|some )?creatures` | BOARD_CONTROL | removal engine, not player-lethal |
| 9 | `infinite combat damage` | LETHAL | COMBAT_DAMAGE |
| 10 | `infinite damage( to .*(opponent\|player))?$` | LETHAL | DIRECT_DAMAGE_LOOP |
| 11 | `infinite lifeloss` (opponent-scoped) | LETHAL | LIFELOSS_DRAIN |
| 12 | `life total becomes (0\|1)` | LETHAL | SETUP_LETHAL |
| 13 | `(infinite\|near-infinite) mill` (opponent-scoped) | LETHAL | MILL_OPPONENTS |
| 14 | `exile each opponent's library` | LETHAL | MILL_OPPONENTS (hard) |
| 15 | `(card draw\|draw triggers) for .*opponent` | LETHAL | FORCED_DRAW_OUT |
| 16 | `infinite (extra )?turns` | LETHAL | INFINITE_TURNS |
| 17 | `infinite combat (phase\|step)s?` | LETHAL | EXTRA_COMBATS |
| 18 | `infinitely large\|infinite (power\|\+1/\+1 counters)` | RESOURCE | feeds SPREAD_COMBAT / CMDR_DMG_SEQUENCE |
| 19 | `infinite .*(token\|copies)` | RESOURCE | feeds SPREAD_COMBAT (haste check) |
| 20 | `infinite card draw$\|draw (all\|your).*librar\|exile your library.*play` | RESOURCE | DECK_ACCESS; guard: oracle-free = self-mill death |
| 21 | `infinite draw triggers$` | RESOURCE | trigger fuel (Niv-Mizzet class → DIRECT_DAMAGE_LOOP) |
| 22 | `(infinite\|near-infinite) .*mana` | RESOURCE | universal fuel; payoff required |
| 23 | `infinite untap` | RESOURCE | loop enabler |
| 24 | `infinite (ETB\|LTB\|blinking\|flicker)` | RESOURCE | Purphoros/Impact Tremors class → DIRECT_DAMAGE_LOOP |
| 25 | `(death\|sacrifice) triggers` | RESOURCE | Blood Artist class → LIFELOSS_DRAIN |
| 26 | `storm count\|magecraft` | RESOURCE | storm/magecraft payoff required |
| 27 | `infinite lifegain` | RESOURCE | **never a win-trigger**; Aetherflux/Ajani's Pridemate class converts |
| 28 | `infinite (scry\|surveil\|proliferat\|energy\|treasure\|clue\|food\|experience\|charge\|commander casts\|landfall)` | RESOURCE | counter/permanent fuel |
| 29 | `^(destroy\|exile) (all\|any number of\|each\|up to)`, `opponent(s)? sacrifice`, `counter the first\|counter all`, `gain control of` | LOCK_DISRUPTION | lock, not a win — see LOCK_WITHOUT_CLOCK |
| 30 | status == `PU` | CARD_CLASS | variant-generation placeholder, not a runtime result |
| 31 | *(no match)* | UNROUTABLE | Gate 3 flags; queue for LLM/human classification |

Validation snapshot (2026-07-15, full Spellbook vocabulary, 1,246 features — scratchpad exercise, not a workflow step): 9 WIN_TRIGGER, 48 LETHAL, 539 RESOURCE, 126 LOCK_DISRUPTION, 14 TABLE_HAZARD, ~30% long-tail UNROUTABLE (mostly H-status stax/prison helpers and C-status cast-from-zone effects — the per-deck + LLM-fallback path exists precisely for this tail).

## 3. Guards & anti-catalog (the planner must refuse these)

- **DRAW_DECK without oracle:** infinite self-draw with no Thassa's Oracle/Lab Man class in the 99 and no "can't lose" guard = self-mill death. Route rejected at validation, logged `route_rejected: oracle_guard`.
- **Infinite lifegain is not a win.** Ever. It's survivability and payoff fuel only.
- **"Near-infinite X"** = large bounded quantity, not a proof; validate with the actual bound.
- **Symmetric effects** (TABLE_HAZARD) require a guard ("can't lose", protection, or winning the race deterministically) before any route may use them.
- **LOCK_WITHOUT_CLOCK:** LOCK_DISRUPTION features with no lethal route in the same deck = the game ends in `timeout_draw`, not a win. Route-coverage flags decks whose only "win" is a lock; the report says so explicitly rather than letting batch stats silently punish the archetype.
- **Turn-cycle routes** (MILL_OPPONENTS via their draw, COMMANDER_DMG_SEQUENCE, STATIC_THRESHOLD) inherit removal/wipe exposure priced via the patience knob; the planner must compare against any same-turn route first.

## 4. Worked example — Selvala, Heart of the Wilds (deck `d7498c0379debdfa`)

All **11 included combos are resource-only** (mana/untap/ETB/storm/draw — zero LETHAL or WIN_TRIGGER features). The Spellbook list does **not** convert cleanly into win conditions; the deck's actual wins are staged lines (author-confirmed, 2026-07-15):

- **Sabertooth engine (draw + mana):** Temur Sabertooth repeatedly bounces and recasts the most powerful creature you control — each re-entry retriggers Selvala's draw, so you draw as much of the rest of the deck as you want; Selvala activations between untaps (haste via Concordant Crossroads or Lightning Greaves for recast-tap loops) generate the mana. Resources produced: DECK_ACCESS + infinite green mana. Still zero damage on its own.
- **The actual win line:** with **Concordant Crossroads** on the battlefield, convert infinite mana by deploying a pile of large creatures from the drawn deck **plus Craterhoof Behemoth**, then alpha strike the same turn — everything has haste from the Crossroads static. That is SPREAD_COMBAT with a **DEPLOY stage in front of it**: the predicate must count creatures deployed *this turn* with haste granted by a battlefield static, and the line must begin in MAIN1 so combat is still available (v3.1 staged-executor requirement, reconfirmed).
- **Staff of Domination** packages both loops itself (mana + card draw under the right power conditions) → same DEPLOY_WIN ending: MANA_LOOP → DRAW_LOOP → deploy + Craterhoof/Crossroads → alpha. Oracle guard N/A — Staff draw stops at will, the deck never force-decks itself.
- Secondary conversions: **Finale of Devastation** (X = huge, fetches + pumps + grants haste itself), **Lair of the Hydra / Goldvein Hydra / Polukranos** as mana sinks → SPREAD_COMBAT or CMDR_DMG_SEQUENCE fallback.

Planner implications confirmed by this example: (1) the LethalityPlanner *is* the win condition — detection + shortcut alone yields infinite mana and a stalled, drawn game; (2) routes are **compositions**: RESOURCE features chain through a DEPLOY stage into a terminal route, so executor bindings need payoff/deploy metadata, not just loop parameters; (3) haste-source *type* matters to the predicate (a static like Crossroads covers everything deployed this turn; per-creature grants like Greaves do not scale to an alpha). This is the empirical justification for route-coverage being a blocking preflight check.

## 5. Maintenance

- Rules bump = `win-routes/N+1`; run manifests pin the version (reproducibility).
- New features encountered per deck: classified once, cached in the global mapping library keyed `(feature_id, win-routes version)`.
- UNROUTABLE features → Gate 3.5-style LLM classification at prep (schema-validated, human-reviewable), never at runtime.
- Gate 3.6 stall autopsies that reveal a *route* gap (not a binding gap) amend §1/§3 here, in the same PR as the fix.
