# Five lenses on the table — round two brief (Project 2 only)

**Date:** 2026-10-16. **Author:** Claude Fable 5.1, for Ben. **Companion:** `ai-native-roles-review-2026-10-16.md`
holds the five analysts' reports verbatim; `ai-native-roles-review-2026-10-16.html` is the readable report with charts.
**Method and source:** `ai-native-roles-2026-09-14.md` (Boris Cherny's five AI-native archetypes, 2026-06-28, and how
they became review lenses). This brief does not repeat that; it sets the scope for the second run.

## What changed since the first round

The first round (2026-09-14) reviewed `experimental/voicework2` at `e517f2eb300`, before the voices shipped. Since then,
on `arena`: the hardening round (9/14–9/16), v4.2 Experimental (9/17, the voices and deals), v4.2.1 (9/30), the game-64
fix set (10/02), the second upstream sync (base `fb4d8091126`, 10/02), v4.3 (10/03, "every target is the seat's"), and
today's cleanup. 445 commits including the upstream merge; head `516794401fa`. Twenty-one games were played and
archived on `arena` code between 2026-09-16 and 2026-10-06. The Jev triage experiment (10/13–10/14) was closed as a
dead end and lives only on an unpushed branch; it is out of scope, including its three archives.

## The lenses this round

The subject is **Project 2: playing voiced Commander at the table with agentic seat brains** — Ben at seat 0 with the
Advisor, three Claude-driven seats, the ElevenLabs voices, the mailbox seam into Forge.

| Lens | What it is asked to weigh |
|---|---|
| Prototyper | The table is v4.3 and, in Ben's words, "very very good". Where is the next step-change toward a *lifelike, agentic* table: brains that remember, deal, bluff and talk about what they are actually doing? Rank cheap experiments by cost. Which of the September bets (`say` key from the brains, intent-grounded talk, binding deals, presence atoms, the parked Advisor-teaches-play idea) still hold and which are dead ends? What would backend diversity (`seatd/backends.py`, the August OpenRouter games) add or cost? |
| Builder | Does v4.3 hold together for one operator and for the light package: the seam (`MailboxController`, 5,141 lines), the persistent seat processes, restarts and timeouts (BL-06, W-5, W-13), the Java↔Python contract and its schemas, the launch and stop scripts, the packaging pipeline (~500 MB with voices), what the second upstream sync cost and risked, and whether the 744 Python tests and 51 interactive Java test classes exercise the live behaviour. |
| Sweeper | Where is complexity not earning its keep in the table stack: three big Python runners (2,365 / 1,749 / 1,265 lines), 53 `ARENA_*` knobs, the `scripts/` directory, the voice stock's long tail (4,336 takes, 517 MB), logic duplicated between the advisor and seat runners, stale doc sections, tests that test the mock. Subtraction proposals must be concrete and sized. Project 1 files are kept by decision and are not candidates. |
| Grower | Does live behaviour match what Ben asked for across games 49–66 (archives 2026-09-16 → 2026-10-06)? What do the archives measure: decisions, latency, punts and stock hand-backs, voice lines per minute, deals, advisor use, game length. Which of Ben's asks in commit messages, BUG-LOG and patch notes landed and were *heard* in later games? What should be iterated next for the human at seat 0? |
| Maintainer | Reliability, observability and efficiency over time: records and provenance (BL-59, the `opus` alias), the timeout seam, the persistent transport, time and token cost per game on the subscription path, upstream drift and the sync procedure (`docs/UPSTREAM-SYNC.md`, HL fences), the gate (494 tests, the stale-jar trap BL-47, the JDK crash W-17), secrets handling (ElevenLabs and OpenRouter keys), the archive corpus (120 archives and growing), test brittleness, and what breaks first when Forge moves. |

**Continuity:** each analyst reads its own lens's section of `docs/research/ai-native-roles-review-2026-09-14.md` and
reports which of those findings landed, which still stand, and which were superseded by events.

## Scope handed to the analysts

- Tree: branch `arena`, head `516794401fa`, working tree clean. Reads of git history are fine (`git log`, `git show`).
- Java (the seam and the GUI side): `src/main/java/forge/arena/interactive/` — 14 files, 9,083 lines
  (`MailboxController` 5,141, `ObserverSnapshot` 922, `AdvisorControllerHuman` 746, `GuiPilotMatch` 374,
  `MailboxProtocol` 349, `GameResultSpool`, `DeckLoadProbe`, `AutopassPolicy`, `SeatAvatars`, `YieldMirror`,
  `ExecutiveSwitch`, `AdvisorFeed`, `MailboxLobbyPlayer`, `AdvisorLobbyPlayer`); `src/main/java/forge/arena/ingest/`
  (decks reach the table through it); the mailbox-side schemas `schemas/arena.mailbox-request.1.schema.json`,
  `arena.events.1.schema.json`, `arena.game-record.1.schema.json`, `arena.advisory-combos.1.schema.json`.
- Python: `runner/seatd/` (`runner.py` 2,365, `brain.py` 758, `rules.py` 641, `backends.py` 453, `protocol.py` 232,
  `record.py` 173, `seat-brief.md`); `runner/advisor_runner.py` 1,749; `runner/voice_runner.py` 1,265;
  `runner/chains.py`; `runner/voice/*.py` and the stock manifests under `runner/voice/stock/` (existence, counts and
  manifests only — do not open or analyse audio bytes); `runner/ratings.py`, `runner/status.py`,
  `runner/seat_runner.py`, `runner/arena-ctl.py`, `runner/run_table.sh`.
- Operator scripts: `scripts/arena-play.sh`, `arena-stop.sh`, `arena-autostop.sh`, `arena-status.py`,
  `arena-config.py`, `arena-hygiene.py`, `arena-digest.py`, `arena-cardwatch.py`, `arena-public-state.py`,
  `arena-add-deck.py`, `deckcheck-import.py`, `run-pilot-match.sh`, `run-gui.sh`, `observe-play.py`.
- Packaging: `packaging/` (`build-light-package.sh`, `cut-release.sh`, `ship-release-s3.py`, `ship-release.sh`,
  `check-voice-takes.py`, `PATCH-NOTES.md` v4.2 → v4.3, `README.md`).
- Tests: `runner/tests/` (53 files, 744 tests); `src/test/java/forge/arena/interactive/` (51 classes) and
  `src/test/java/forge/arena/ingest/`. Running the Python suite once is allowed
  (`cd forge-arena/runner && python3 -m unittest discover -s tests`); Maven is not.
- Docs: `docs/BUG-LOG.md` — the open table and watch list (lines 7–34) and the closed sections dated 2026-10-02 and
  2026-09-10; `docs/INTERACTIVE-ARENA.md` by section (Architecture, Mailbox protocol, Known limitations, Operational
  learnings & field notes — it is 156 KB, read sections, not the file); `packaging/PATCH-NOTES.md`;
  `docs/UPSTREAM-SYNC.md`; `docs/reviews/2026-09-14-voicework2-hardening-plan.md`,
  `2026-09-16-feature-stack-rank.md`, `2026-09-16-release-features-plan.md`, `2026-09-16-table-deals-plan.md`,
  `2026-09-16-offer-dialog-plan.md`, `2026-09-17-final-hygiene-pass.md`, `2026-09-17-voice-mapping-gemini-review.md`;
  `docs/research/pod-timing-priors.md`; memory of the parked ideas is in the BUG-LOG watch list and the plans above.
- Live evidence: archived games under `runner/logs/archive/` played on `arena` code — the eight `20260916-*-stop`
  runs, four `20260917-*-stop`, two `20260918-*-stop`, `20260926-003649-stop`, `20261002-131143-stop` (game 64, the
  all-AI watch that produced the 10/02 fixes), `20261002-160838-stop` (the sync acceptance game), and
  `20261006-203245-stop` (v4.3 from the package root). Each holds `game.jsonl`, `hygiene.txt`, `launch-config.txt`,
  seat logs and `.err` files, `voice-0.jsonl`, advisor logs where the Advisor ran, `autostop.out`. The August
  OpenRouter games (`20260812-175852` … `20260813-170617`) are optional evidence for backend diversity.

## Out of scope — do not read, do not propose changes to

- **Project 1, the headless batch harness** (parked by decision, files kept): `src/main/java/forge/arena/{combo,prep,
  bindgen,harness}/`, `route-library/`, `bindings/`, `scripts/{batch.sh,prep.sh,canary.sh,smoke.sh,
  capability-prototype.py,fidelity.py,program-fidelity.py,gemini_wholedeck.py,merge_discovery.py,
  build-ingestion-packages.py,sample-decks.py,anchors.py,build_card_scripts_index.py,
  selvala-wholedeck-ingestion-wf_*.js}`, `docs/{working-plan-Aug-3,CANARY-BRIEF-GOLD,runner-cat,SYNERGY-INGESTION,
  SPEC-executable-turn-plans}.md`, the BUG-LOG section "Headless harness (Project 1)", the `headless-scenario` and
  `extended` test groups.
- **Jev** (TypeSafe triage, closed 2026-10-14 as a dead end): the branch `experimental/jev-triage`, the archives
  `20261013-171220-stop`, `20261013-203921-stop`, `20261013-213319-stop`, and any `jev` mention. Ignore it entirely.
- Audio bytes, the 165 MB session transcripts, anything under `~/Claude/hello` or any key or token.

## Rules of engagement

Analyse and report only. No edits, no git writes, no Maven or jar builds, no game launches, no network calls, no
secrets in output (never print the contents of a key file or an `.env`; name the file, not the value). Prefer `grep`
and line ranges over whole-file reads; `MailboxController` is read by section. Soft budget: about 250k tokens per
analyst, 1.5M for the round. Evidence beats opinion: every finding names a file and line or an archive and timestamp.

## Report format (each analyst's final message, reproduced verbatim)

1. One headline sentence after the lens name (the September reports show the shape).
2. *What you read and what shipped, as your lens reads it* — short.
3. *Top findings* — numbered, each with evidence, why it matters, and a direction.
4. *Concerns* · *Bugs and corrections* (mark each confirmed / plausible / hypothesis) · *Feature suggestions* (ranked by
   cost) · *Observability and efficiency* · *Questions for Ben*.
5. *Follow-up on the September report* — which of your lens's findings landed, still stand, were superseded.
6. A final fenced block tagged `json` holding the machine summary used for the charts:
   `{"lens": "...", "findings": [{"id": "P1", "title": "...", "kind": "bug|concern|feature|observability|question",
   "severity": "P0|P1|P2|P3", "confidence": "confirmed|plausible|hypothesis", "area": "java-seam|runner|brain-brief|
   voice|advisor|scripts|packaging|ingest|docs|tests|sync", "effort": "S|M|L", "sources": ["file:line", "archive"]}],
   "metrics": [{"name": "...", "value": 0, "unit": "...", "source": "..."}],
   "september": {"landed": 0, "standing": 0, "superseded": 0}}`
