# Bug log — outstanding items

Opened 2026-09-04 after the full review (`docs/reviews/2026-09-03-full-review.md`), the affirmed interactive plan (`docs/reviews/2026-09-03-interactive-plan.md`, items 1–15 shipped, 16 measuring) and live game 19. Every entry is something NOT yet fixed. Severity: **P0** corrupts state/data or a batch; **P1** wrong behaviour in play or measurement; **P2** minor or latent. Status is the only field that changes; close an entry by moving it to the "Closed" section with the commit.

Conventions still in force: seam fixes are general (mechanics, never card names); regression tests span ≥2 cards; parent-module changes take the FULL gate; capture Maven's exit status, never a filtered tail.

## Interactive (Project 2) — open

| ID | Sev | Area | Item | Evidence | Proposed fix |
|---|---|---|---|---|---|
| BL-01 | P1 | engine payer | **Life-for-mana statics are outside the stock payer's search.** With K'rrik, Son of Yawgmoth out, Mikaeus ({3}{B}{B}{B}) for 3 mana + 6 life is legal; Forge's AI payer spends sources on black pips first, finds nothing for generic, reports unpayable. The arena's affordability guard then refuses a game-winning line. | Game 19, seat 1 t44: `DEVIATION … K'rrik's alternative payment not offered`; `ComputerUtilMana.java:710` (`PayLifeInsteadOf:B` only when `saPayment == null`). | (a) forge-ai payer: when the player has `PayLifeInsteadOf:<c>`, try the permutation "sources on generic/other pips, life on <c>" before declaring unpayable (FULL gate); or (b) offer the seat an explicit cast variant `[pay N life for the {B} pips]` built the way optional-cost variants are. (b) keeps the parent untouched. |
| BL-02 | P1 | mailbox surfaces | **Trigger ordering is decided by stock** for the seat's simultaneous triggers (CR 603.3b gives it to the controller). | Game 19: `orderSimultaneousSa` fired 6× for the sacrifice deck, batches of 2–22. | Open the surface under the existing discipline (genuine choice only, vetted, stock on failure): a `CHOOSE_MODE`-shaped window over the trigger descriptions, answer = order. Add to the request schema. |
| BL-03 | P1 | mailbox surfaces | **Any-color mana picks are decided by stock** (`chooseColor` / `chooseColorAllowColorless`). | Game 19: 27 consultations, the most frequent stock surface. | Cheapest: give seats the advisor's auto-pick rule (mono-colored commander → its color) for 3+-color choices; otherwise mailbox as a small `CHOOSE_MODE`. Note the count is engine consultations, not decisions — de-duplicate per window before sizing the cost. |
| BL-04 | P2 | mailbox surfaces | Combat damage assignment (multi-block splits), convoke/improvise payment, spell-for-effect choice stay on stock. | Game 19: `assignCombatDamage` 1×, convoke 9× (repeated planning consultations per window), spell-for-effect 0×. | Open by evidence after a few more games; convoke needs the payment-context gate (item 10's F2 lesson) so planning scans don't open windows. |
| BL-05 | P2 | mailbox | Mind-slave routing is untested live and the master's brain gets no `state` for its own board while controlling. | `MindSlaveRoutingTest` covers routing only. | Include a compact `controllerBoard` summary in requests carrying `controllingSeat`. Verify in a game with Worst Fears / Mindslaver. |
| BL-06 | P2 | mailbox | Timeout on a silent brain still costs one full wait per decision once (the heartbeat gate only helps when the runner PROCESS is gone). | Design decision (item 12 simplified); item 2 makes wedged models punt on time, so exposure is one window. | Leave unless measured; revisit with the surfaces above. |
| BL-07 | P2 | observer | `ObserverSnapshot` debounce has no trailing edge (last event in a 200 ms burst never written) and `write` is not synchronized. | Review finding. | Schedule one trailing write; `synchronized` on `write`. |
| BL-08 | P2 | runner | `_cycle_rebind` rebinds a recorded cycle answer by card-name prefix; when only one of a card's abilities carries a cost, the prefix can bind a different ability. | Review (C, D12), plausible. | Bind on the option's `type`+cost too, or on the ability description prefix. |
| BL-09 | P2 | runner | `transport-events.jsonl` is archived at teardown while the ratings void check reads it; multi-game sweeps can miss history. | Review (C, D8). | Keep it beside the per-game logs (rotate like `game-<id>.jsonl`). |
| BL-10 | P2 | runner | `status.py`'s fastpath % omits `hold`/`plan`/`cycle`; `usage_report.py` and `replay.py` index keys that pre-backend records lack; `arena-digest.py` drops torn lines. | Review (C, smaller items). | Small edits with tests. |
| BL-11 | P2 | tests | Ten seam tests still pin one card each (Fierce Guardianship, Transmute Artifact, Rings, Scepter, Aura Shards, Sanctum Weaver+Gauntlets, Selvala tax, Arc Trail, the four in `CastPathReachabilityTest`). | Review (D, A.7). | Widen to two cards as each seam is next touched (rule: ≥2 cards). |
| BL-12 | P2 | tests | No test exercises `GuiPilotMatch` (start invariant, roster, advisor wiring) or the human seat (`--human`, autopass modes, advisor-by-default). | Review (D, B9). | A headless harness around `startCommanderMatch`'s deck loop; the human seat needs a GUI-less controller fake. |
| BL-13 | P2 | advisor | `pending_context` is unbounded between admitted calls; the advisor writes its own control file then trusts its own mtime. | Review (C, D10/D11). | Bounded deque; mirror the seat runner's "mtime not recorded on our own write". |
| BL-14 | P2 | ingest | `arena-add-deck.py` regex takes a leading number as quantity ("1996 World Champion"); Moxfield temp file leaks in `PrepMain`; DFC front-face lookup for Scryfall relies on `_front_face`. | Review (Gemini P2; B15/B16). | Anchor the quantity regex; `deleteOnExit`. |
| BL-15 | P2 | packaging | `react-autopass.py` remains in the repo with a stale two-name allowlist and no threat check (no longer shipped or reaped). | Item 13d. | Delete, or make it read-only (log what it would have answered). |
| BL-16 | P2 | docs | `docs/INVENTORY.md` §3 still describes `engine/` as three classes; ~50 files under `docs/` are not inventoried; `AiTabHarness` JUnit conversion noted 8/19 still open. | Review (D). | Refresh §3 and §7 from the tree in one pass. |
| BL-17 | P2 | release | **v3.3.3 not cut.** `PATCH-NOTES.md` "Unreleased — after v3.3.2" is written; the shipped `-latest` on R2 predates every fix in this log's closed section. | — | Standard pipeline when Ben says go: fresh gate → `build-light-package.sh --force` → tar → REST-R2 PUT dated + `-latest` → verify hashes. |

## Interactive — watch items (not bugs yet)

- **W-1** Surface-count instrumentation (`STOCK-SURFACE`) counts engine consultations; convoke and color are consulted many times per window. De-duplicate by (seat, turn, phase, surface) before comparing.
- **W-2** A resumed Claude session hung three times in a row (game 19, seat 1, 72 s each) before the wedge rule fired. Three punts is ~3.6 minutes of stock play at 90 s. If it recurs, lower `WEDGE_FAILS` to 2 or shorten the second attempt.
- **W-3** Ratings void any game with a wedge; with wedges now cheap (item 2), consider voiding only when punts exceed the threshold.
- **W-4** `manaAvailableNow` counts one activation per source; the brain still misjudged Gemstone Caverns once (t42) — confirm the `restricted`/condition flags read right for condition-forked sources.

## Headless harness (Project 1) — deferred by decision 2026-09-03, recorded for reference

Ben removed these from planning. Listed so they are not lost; details and line numbers in `docs/reviews/2026-09-03-full-review.md` and the reviewer reports it cites.

| ID | Sev | Item |
|---|---|---|
| HL-01 | P0 | `EngineFacade` wall-clock timeout calls `setGameOver` from the harness thread while the game thread still runs; the abandoned 64 MB thread writes into a closed recorder for the worker's life. |
| HL-02 | P0 | `ArenaRunner.runOne` lets setup exceptions escape: no `GameRecord`, recorder leaked, worker killed, stride lost after 3 identical retries. |
| HL-03 | P0 | 53 combo programs, 18 pairing programs, 1 engine program are gitignored (`decks/*/`); 25 tests error on a clean checkout, `ProgramSchemaValidationTest` passes vacuously. Track the authored inputs. |
| HL-04 | P0 | Every Java-prepped dossier fails `DossierCheck` (`deck_cards` sha mismatch, caused by `arena-add-deck.py` overwriting). Two ingestion writers → one. |
| HL-05 | P1 | `ComboAwareLobbyPlayer.getAi()` returns a second `AiController`; 62 upstream call sites consult a brain that is not deciding; card memory never reset. |
| HL-06 | P1 | Nine of eleven program-dispatch branches `return first` on a null first step, forfeiting the priority window. |
| HL-07 | P1 | `PairedPlay` decides "land" from an 11-name basic-land list; land wipes score near zero against real manabases. |
| HL-08 | P1 | `PayoffRules` matches Clue reminder text and symmetric draws: Loran, Wojek Investigator, Minas Tirith shipped as draw engines. |
| HL-09 | P1 | `firedShortcuts` doubles as "pool banked" and "combo fired"; `convert()` clears it for every combo on phase change. |
| HL-10 | P1 | `SelvalaManaLoopRunner` embeds ten card names and a Rhonas/Nylea plan; `amplified()`/`perEtbDamage()` parse oracle prose; `PairingRunner` pip check is white-only. |
| HL-11 | P1 | `ExecutorBindings.executorFor` throws out of eight unguarded call sites on a known archetype with a missing param; `BindGen` lints every archetype as `TapForManaUntapLoop`; bindings/route library rewritten non-atomically. |
| HL-12 | P2 | `BatchMain` exits 0 on 100% crashes; stall dumps CWD-relative with 32-bit hash names; dead `chooseCardsForZoneChange` override; `confirmAction` lacks `@Override`; `StallAutopsy` deck gate is a substring test and reads an arbitrary `dump_path`. |

## Closed (this pass, 2026-09-03 → 09-04)

Items 1–15 of the interactive plan, with commits: b0568854eb0 (1), a680583b7f4 (2), bb1917137f2/9dc20db1101 (3, 10), be668e60519 (4, 11c), 7490eb465dc (6), 04a12be8b98 (7), a783291a475 + ec2b1ede0b4 (8), 0597c40f023 (9), cde7095c2dc (11a/b, 12), b66d90ec75a (12 runner), 203d30ffe46 (5), 696c226a86f (13), ecd3bacbfe0 (14), 309bbe6d977 (15), d4e98dab13c (16 instrumentation). Live-found and fixed the same day: `getScryfallCode()` NPE in the resolver; resolver failure misreported as "Forge lacks the card"; MULLIGAN `state.hand` shape drift; eliminated seats read as CARD-VANISH (CR 800.4a).
