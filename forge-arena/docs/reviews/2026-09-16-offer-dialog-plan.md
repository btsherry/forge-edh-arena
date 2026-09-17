# The offer pane — a Yes / No dialogue when a seat offers the player a deal

**Date:** 2026-09-16 (evening, after game 53). **Status:** BUILT the same evening on Ben's "yes to items 1-4, Go!" — Counter… button in, assessment shown, bottom-right, on the experimental branch (whether the release cut includes it is decided at the cut). Not yet seen live: needs a game where a seat offers Ben. Ben: "consider a yes/no dialogue for
the player when being presented with an offer instead of buttons in the Adviser window… plan and discuss don't execute."
Supersedes stack-rank item 13 (buttons in the Advisor panel).

## 1. What exists (game 53 proved it)

A seat's brain proposes (`deal.propose`); the advisor prints `[Purphoros] offers you alliance until turn 10 — "…"
(@purphoros accept/no)`, remembers the offer as `proposed`, assesses it in Joshua's voice at once, and lapses it at the
end of the following turn. The player answers by typing `@purphoros accept` or `@purphoros no` in the Advisor chat; the
advisor writes `logs/control/deal/<ts>-accept|refuse.json`; the voice runner strikes or refuses and the seat answers
aloud. Executive on: the seat-0 runner answers the note itself and the advisor prints "the Executive answers for you".

The GUI side already has every primitive: the Advisor panel polls files on a 1 s Swing timer (`VAdvisor.poll`), writes
control files through `AiControlFile` (asks, mute, advisor on/off, Executive), and the desktop `FDialog` takes a
`modal` flag, so a non-modal skinned window is native.

## 2. The design

**A question file, written by the advisor.** When a seat's offer reaches the player (and Executive is off), the advisor
writes `logs/control/deal/questions/<offer_id>.json`:
`{"offer_id", "seat", "who": "Purphoros", "handle": "purphoros", "terms": "alliance until turn 10", "text": "Urza is the
threat", "turn": 7, "lapses_after_turn": 8, "assessment": null, "ts"}`. After Joshua's assessment lands, the file is
rewritten with `assessment` filled. The advisor deletes the file when the offer is answered (typed or from the pane),
lapses, or the game ends. One file per open offer; two seats may offer at once.

**A pane, owned by the Advisor panel.** `VAdvisor.poll` (already 1 s) lists that directory. A file with no pane opens
`VDealOffer`, a NON-modal `FDialog` owned by the match frame, `setFocusableWindowState(false)` so it never takes a
keystroke from the game, placed bottom-right over the match view next to the Advisor dock. Contents: one line
"Purphoros offers you an alliance until turn 10", the seat's words in quotes, Joshua's assessment in the advisor's
colour when present, "lapses at the end of turn 8", and three controls:

- **Accept** → `AiControlFile.askAdvisor("@purphoros accept")`. The exact file the chat writes; zero new Python on the
  answer path. The pane greys its buttons ("Sending…") and closes when the question file vanishes.
- **Refuse** → `askAdvisor("@purphoros no")`, same.
- **Counter…** (optional) → closes the pane and puts `@purphoros ` in the chat field with focus, so the player types
  terms. The typed grammar already parses a counter as a fresh offer to that seat.
- The title-bar **X** = "later": the pane closes, the offer stays open in the panel for a typed answer, and nothing is
  sent. (A silent close is not a refusal — the seat should not hear "no" because the player dismissed a window.)

The pane closes itself when its file disappears for any reason (answered, lapsed, Executive turned on, game over), so
runner restarts and the lapse need no extra wiring. Several files → one pane at a time, oldest first.

**Never modal.** Forge's own confirms block because the engine is waiting on the player; an offer arrives on a seat's
turn, often while the player is mid-combat or mid-targeting. A modal window over the targeting UI would steal the
click. Nothing in the pane touches the engine or its input queue — files only — so it can never wedge a decision.

**Executive on:** the advisor writes no question file; nothing appears. **Advisor off / not attached:** no advisor
means no relay and no file; the pane never appears. **Tab follow:** the offer line is meaningful, so the tabs already
flip to the offering seat's board as the pane appears, which is the right context.

## 3. The work

| Piece | Where | Size |
|---|---|---|
| Question file: write on offer, rewrite with the assessment, delete on answer / lapse / Executive / game over | `runner/advisor_runner.py` (`_on_seat_offer`, `_answer_counter`, `_deal_tick`, `_assess_deal`, teardown) | ~50 lines |
| Python tests: file lifecycle for each exit | `runner/tests/test_deals_advisor.py` | ~60 lines |
| `AiControlFile.dealQuestions()` (list + parse) and `askAdvisor` reuse | `forge-gui-desktop/…/arena/interactive/AiControlFile.java` | ~40 lines |
| `VDealOffer` pane (non-modal FDialog, three buttons, self-closing) | new `forge-gui-desktop/…/arena/interactive/VDealOffer.java` | ~150 lines |
| Hook in `VAdvisor.poll` (open / refresh / close panes) | `VAdvisor.java` | ~25 lines |
| Java tests: parser, oldest-first, the answer text, no pane without a file | new `DealQuestionTest` | ~60 lines |
| Gate + live game | FULL Maven gate (~6 min) after teardown; one game where a seat offers Ben | — |

No upstream file changes: the pane and parser are new files in the arena's desktop package; `VAdvisor` is ours.

## 4. Risks and the answers

- **Focus.** A Swing window that takes focus swallows the game's keys. `setFocusableWindowState(false)` plus
  `VAdvisor.releaseFocus()` after a click; the chat field already solves the same problem.
- **Appears during the player's own action.** Non-modal, no input-queue contact: the player finishes the action and
  clicks the pane after. Acceptable; a "later" X exists.
- **Two offers at once.** Directory, oldest first; the second pane opens when the first closes.
- **A stale file after a crash.** The advisor clears the directory at start and at game over; the pane closes on a
  missing file; `arena-stop.sh` removes the directory.
- **Java gate cost.** One FULL gate and a rebuilt jar set; the branch's Java is otherwise at rest, so this is the one
  Java change between now and the release cut — or the first of the next one.

## 5. Decisions for Ben

1. Accept / Refuse only, or the third **Counter…** button too?
2. Should the pane show Joshua's assessment (it arrives a few seconds after the offer), or stay a bare question?
3. Placement: bottom-right over the match view, or docked beside the Advisor tab?
4. Ship it in the experimental release (one gate, one more game) or first in the release after?
