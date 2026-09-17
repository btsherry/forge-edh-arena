"""Historical harness (round 31, 2026-09-14): game 47, seat 1 (Urza), turn 20 — the
Hullbreaker + Mana Vault + Aetherflux Reservoir turn: 138 decisions, of which the live
runner replayed 63 from one brain-declared cycle and asked the brain 67 times, 28 of them
hand-played loop rounds after Ben's Khalni Ambush interrupted the cycle.

The fixture is the seat's own decision tape (tests/fixtures/game47-seat1-turn20.jsonl).
Each row becomes a request (its option labels, stack, lives, pool); a scripted brain
answers exactly what the real brain answered, and — policy "accept" — takes a LOOP OFFER
by declaring repeat_cycle 8 with until life >= 180, the goal the real brain stated in its
own reasons. We check that every replayed answer matches the recorded one and count the
model calls saved against the "decline" policy. Assumption: stack objects on this turn
were the seat's own (the tape carries no owners; the live request does)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cycle_replay import make_runner  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "game47-seat1-turn20.jsonl"
SEAT = 1


def load_tape():
    return [json.loads(l) for l in FIX.read_text().splitlines() if l.strip()]


def reconstruct_options(tape):
    """The live runner logs option lists only for brain-answered windows; a window it replayed
    itself (source cycle/memo/yield) is given the options of the most recent brain-answered
    window of the same type and stack — which is what a replayed window IS (the cycle engine
    only replays into an identical window)."""
    last = {}
    out = {}
    for row in tape:
        key = (row["type"], tuple(sorted((row.get("board") or {}).get("stack") or [])))
        if row.get("options"):
            last[key] = row["options"]
            out[row["seq"]] = row["options"]
        else:
            out[row["seq"]] = last.get(key) or ["Pass (do nothing)", "(recorded window)"]
    return out


OPTIONS = None


def request_of(row: dict) -> dict:
    global OPTIONS
    if OPTIONS is None:
        OPTIONS = reconstruct_options(load_tape())
    labels = OPTIONS.get(row["seq"]) or ["Pass (do nothing)", "(recorded window)"]

    def cost_of(lab):                                   # "Mana Vault  {1} — Mana Vault" -> "{1}"; a real request carries cost/type fields
        parts = lab.split("  ", 1)
        return parts[1].split(" — ")[0].strip() if len(parts) > 1 else None
    options = [{"id": i, "label": lab, "cost": cost_of(lab)} for i, lab in enumerate(labels)]
    ans = row.get("answer") or {}
    cid = ans.get("chosenId")
    if isinstance(cid, int) and cid not in {o["id"] for o in options}:
        # entity/card ids are object ids, not indices, and a window the live runner replayed itself may have had
        # one option more than the brain-answered window its list was borrowed from: keep the recorded choice legal
        options.append({"id": cid, "label": f"(recorded option {cid})", "cost": None})
    b = row.get("board") or {}
    lives = {int(k): v for k, v in (b.get("lives") or {}).items()}
    stack = list(b.get("stack") or [])
    state = {"stack": stack, "stackOwners": [SEAT] * len(stack), "manaPool": b.get("pool") or 0,
             "life": lives.get(SEAT, 40), "opponents": [{"seat": s, "life": l} for s, l in lives.items() if s != SEAT],
             "untappedManaSourceCount": b.get("untappedSrc") or 0}
    if isinstance(ans.get("chosen"), list):
        state["min"] = state["max"] = len(ans["chosen"])
    return {"seq": row["seq"], "turn": row["turn"], "phase": row.get("phase"), "decisionType": row["type"],
            "prompt": "recorded", "state": state, "options": options, "min": state.get("min"), "max": state.get("max")}


class TapeBrain:
    """Answers each window with what the real brain answered; may accept an offer."""
    effort = "high"
    model = "opus"

    def __init__(self, tape, accept: bool):
        self.by_seq = {r["seq"]: r for r in tape}
        self.accept = accept
        self.calls = 0
        self.offers = 0
        self.accepted = 0
        self.prompts = []

    def decide(self, prompt, timeout_s=None, effort=None, deadline=None):
        self.calls += 1
        self.prompts.append(prompt)
        seq = int(prompt.split("seq=")[1].split()[0])
        out = dict((self.by_seq[seq].get("answer") or {"chosenId": 0}))
        if "LOOP OFFER" in prompt:
            self.offers += 1
            if self.accept:
                self.accepted += 1
                out["repeat_cycle"] = 8
                # the target the real brain would name: its own reason for this window says what the loop is for
                why = (self.by_seq[seq].get("why") or "").lower()
                if "life" in why or "reservoir" in why:
                    out["until"] = {"life": ">=180"}
        out["why"] = self.by_seq[seq].get("why") or "recorded"
        return out, {"latency_s": 0.01, "usage": None, "cache_read": 1, "raw": json.dumps(out)}

    def reset(self):
        pass


def run(policy_accept: bool):
    tape = load_tape()
    r = make_runner()
    r.seat = SEAT
    r.brain = TapeBrain(tape, policy_accept)
    r.rotate_hard = 0
    r.rotate_at = 0
    sources = {}
    mism = []
    for row in tape:
        req = request_of(row)
        before = len(r.mb.responses)
        r.handle(req)
        seq, answer = r.mb.responses[-1]
        assert len(r.mb.responses) == before + 1
        src = "model" if r.brain.calls > sources.get("_calls", 0) else "runner"
        sources["_calls"] = r.brain.calls
        sources[src] = sources.get(src, 0) + 1
        rec = row.get("answer") or {}
        if src == "runner" and row.get("source") == "model" and answer != rec:
            mism.append((seq, row["type"], answer, rec, (row.get("why") or "")[:60]))
    return r, sources, mism


class Game47Turn20(unittest.TestCase):
    def test_fixture_is_the_real_turn(self):
        tape = load_tape()
        self.assertEqual(len(tape), 138)
        self.assertEqual({s: sum(1 for t in tape if t["source"] == s) for s in ("model", "cycle", "memo", "yield")}, {"model": 67, "cycle": 63, "memo": 7, "yield": 1})

    def test_offers_accepted_with_a_stop_condition_cut_the_brain_calls_and_replay_what_the_brain_chose(self):
        r_dec, src_dec, _ = run(policy_accept=False)
        r_acc, src_acc, mism = run(policy_accept=True)
        calls_dec, calls_acc = r_dec.brain.calls, r_acc.brain.calls
        log = "\n".join(l for l in r_acc.log_lines if "CYCLE" in l or "LOOP" in l)
        msg = (f"\nDECLINE: brain calls {calls_dec} (runner {src_dec.get('runner', 0)}) | offers seen {r_dec.brain.offers}"
               f"\nACCEPT : brain calls {calls_acc} (runner {src_acc.get('runner', 0)}) | offers {r_acc.brain.offers}, accepted {r_acc.brain.accepted}"
               f"\nreplayed answers that differ from the recorded brain answer: {len(mism)} -> {mism[:6]}\n{log}")
        print(msg)
        self.assertGreaterEqual(r_acc.brain.offers, 1, "the tape shows a repeating loop: at least one offer" + msg)
        self.assertLess(calls_acc, calls_dec, "accepting the offers must save brain calls" + msg)
        self.assertTrue(any("CYCLE armed" in l for l in r_acc.log_lines), msg)
        self.assertGreaterEqual(calls_dec - calls_acc, 20, "the offer in the 20:39 mana loop replays the rounds the live brain declared by hand" + msg)
        # every replayed answer must be what the brain actually chose in that window: a divergence here is a real bug
        self.assertEqual(mism, [], msg)

    def test_the_hand_played_reservoir_rounds_were_not_a_clean_repetition(self):
        """The honest negative: after Ben's Ambush the brain resumed the loop by hand for six rounds but
        interleaved extra value actions (floating Vault's mana, tapping Sol Ring before its bounce) every other
        round, so no two consecutive rounds were identical even loosely until the loop's last round — neither
        the offer nor a declaration could have replayed them. What would have: a target declared on the FIRST
        cycle, which parks on the interruption and re-arms when one clean round recurs (tested in
        test_cycle_replay); the tape shows one such round (seq 224-233) before the target was met."""
        r, src, mism = run(policy_accept=True)
        offers_after_ambush = [l for l in r.log_lines if "LOOP OFFER" in l]
        self.assertEqual(len(offers_after_ambush), 1, "one offer, in the 20:39 mana loop; none in the hand-played stretch")


if __name__ == "__main__":
    unittest.main()
