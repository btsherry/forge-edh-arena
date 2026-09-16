#!/usr/bin/env python3
"""Timing statistics for a corpus of Commander pod transcripts (WebVTT captions).

Why: the voice runner paces the table's talk on guessed constants — the gap
between lines, a silence floor, the odds a proposal draws a reply, the odds a
line chains, the odds a line draws a murmur.  This script measures the same
quantities on real four-player casual pods so those guesses can be checked
against priors.  It reads YouTube captions (auto or manual) from a corpus tree

    <corpus>/<source>/<video-id>.<lang>.vtt

and writes one JSON per video plus a markdown summary per source and pooled.

The corpus itself is never committed (forge-arena/research/corpus/ is
gitignored); only this script and the numbers it produces live in the repo.

Usage
    pod_timing.py <corpus-dir> [--out <dir>] [--md <file>] [--quiet]
    pod_timing.py --runner-log <voice-0.jsonl> [<voice-0.jsonl> ...] [--md <file>]

The second form runs the same gap statistics over the arena's own voice log
(`spoke` records, kind "bark", the seats' lines) so the table can be put beside
the pods in one table.

What the captions cannot give us
    Speaker identity.  YouTube auto-captions carry no speaker labels; some
    tracks carry a ">>" speaker-CHANGE marker, which tells us that the voice
    changed, never who is talking or whose turn it is.  So "gaps by active
    player" is not recoverable from this corpus and is reported as null, not
    guessed.  Overlap is likewise a floor: a caption track serialises speech,
    so measured overlap is the small residue the aligner happened to keep.

Stdlib only.  Python 3.9+.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import statistics
import sys
from pathlib import Path

# ---------------------------------------------------------------- constants

UTTERANCE_GAP_S = 0.6      # a silence at least this long ends an utterance
LONG_GAPS_S = (4.0, 15.0, 30.0)
PROPOSAL_WINDOW_S = 8.0    # "what follows a proposal" looks this far ahead
CHAIN_GAP_S = 2.0          # a reply this soon, by a different voice, is a hop

# a word's spoken duration, estimated from its length, so that a gap between
# two word START times can be turned into a gap between speech and speech.
WORD_MIN_S, WORD_MAX_S = 0.12, 0.60


def word_dur(w: str) -> float:
    return min(WORD_MAX_S, max(WORD_MIN_S, 0.085 * len(w) + 0.10))


NONSPEECH = re.compile(r"^\[(music|applause|laughter|laughs|cheering|clapping|"
                       r"sound effect|intro|outro|silence)\]$", re.I)
CENSORED = re.compile(r"^\[\s*__\s*\]$")

BACKCHANNEL = {
    "yeah", "yep", "ok", "okay", "nice", "oof", "ooh", "hmm", "wow", "no",
    "yes", "sure", "right", "damn", "ouch", "whoa", "what", "oh",
}

PROPOSAL_VERBS = re.compile(
    r"\b(hit|hits|hitting|attack|attacks|attacking|kill|kills|killing|"
    r"swing(?:ing)?\s+at|deal|deals|peace|truce|alliance|ally|team\s+up)\b", re.I)
# a target: a pronoun, or a capitalised token that is not the first word of a
# sentence (a name, or a commander's name — we cannot tell which, and for this
# measurement we do not need to).
PRONOUN = re.compile(r"\b(him|her|them|you|your|his|their|us|me)\b", re.I)
NAMEISH = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b")

CUE = re.compile(r"^\s*((?:\d{2,}:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*"
                 r"((?:\d{2,}:)?\d{2}:\d{2}[.,]\d{3})")
INLINE_TS = re.compile(r"<(\d{2,}:\d{2}:\d{2}[.,]\d{3})>")
TAG = re.compile(r"</?c[^>]*>|</?[0-9:.,]+>|<[^>]*>")


def to_seconds(stamp: str) -> float:
    parts = stamp.replace(",", ".").split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return 0.0
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


# ------------------------------------------------------------------ parsing

class Cue:
    __slots__ = ("start", "end", "lines")

    def __init__(self, start: float, end: float, lines):
        self.start, self.end, self.lines = start, end, lines


def read_cues(path: Path):
    """Parse a WebVTT file into cues.  Returns [] for a missing/empty file."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    cues, start, end, buf = [], None, None, []
    for line in raw.splitlines():
        m = CUE.match(line)
        if m:
            if start is not None:
                cues.append(Cue(start, end, buf))
            start, end, buf = to_seconds(m.group(1)), to_seconds(m.group(2)), []
            continue
        if line.strip() == "":
            if start is not None:
                cues.append(Cue(start, end, buf))
                start, end, buf = None, None, []
            continue
        if start is not None:
            buf.append(line)
    if start is not None:
        cues.append(Cue(start, end, buf))
    return cues


def clean(text: str) -> str:
    """Drop caption markup.  ">>" (YouTube's speaker-CHANGE mark) is recorded
    by the caller before it gets here, so it is stripped from the text — left
    in, it would be counted as a word and would hide the first real one."""
    out = html.unescape(TAG.sub("", text)).replace("​", "")
    return out.replace(">>", " ").strip()


def words_from_cues(cues):
    """Word stream [(t, word, speaker_change)] from word-timed auto-captions.

    Auto-captions roll: each cue repeats the previous cue's finished line and
    adds one new line carrying <hh:mm:ss.mmm><c>word</c> timings.  We take the
    timed line only, so nothing is counted twice, and we dedupe on (t, word).
    """
    out, seen = [], set()
    for cue in cues:
        for line in cue.lines:
            if "<" not in line:
                continue                       # carry-over of an earlier cue
            head = line.split("<", 1)[0]
            pending_change = ">>" in html.unescape(head)
            first = clean(head)
            if first:
                for w in first.split():
                    key = (round(cue.start, 2), w)
                    if key not in seen:
                        seen.add(key)
                        out.append((cue.start, w, pending_change))
                        pending_change = False
            marks = list(INLINE_TS.finditer(line))
            for i, m in enumerate(marks):
                t = to_seconds(m.group(1))
                chunk = line[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(line)]
                change = ">>" in html.unescape(chunk)
                txt = clean(chunk)
                for w in txt.split():
                    key = (round(t, 2), w)
                    if key in seen:
                        change = False
                        continue
                    seen.add(key)
                    out.append((t, w, change))
                    change = False
    out.sort(key=lambda r: r[0])
    return out


def words_from_plain_cues(cues):
    """Fallback for caption tracks with no word timings (manual subtitles).

    Consecutive cues whose text is a prefix/suffix of the next are collapsed;
    a cue's words are spread evenly across its own time range.
    """
    kept = []
    for cue in cues:
        raw = html.unescape(" ".join(cue.lines))
        txt = clean(" ".join(cue.lines))
        if not txt:
            continue
        if ">>" in raw:
            txt = " " + txt        # carries the speaker-change mark
        if kept:
            prev = kept[-1][2]
            if txt.startswith(prev) or prev.startswith(txt) or \
               txt.endswith(prev) or prev.endswith(txt):
                if len(txt) > len(prev):       # the longer roll wins
                    kept[-1] = (kept[-1][0], cue.end, txt)
                else:
                    kept[-1] = (kept[-1][0], max(kept[-1][1], cue.end), prev)
                continue
        kept.append((cue.start, cue.end, txt))
    out = []
    for start, end, txt in kept:
        change = txt.startswith(" ")
        ws = txt.lstrip(" ").split()
        if not ws:
            continue
        span = max(0.25, (end - start))
        step = span / len(ws)
        for i, w in enumerate(ws):
            out.append((start + i * step, w, change and i == 0))
    return out


def nonspeech_spans(cues):
    spans = []
    for cue in cues:
        txt = clean(" ".join(cue.lines))
        for tok in re.findall(r"\[[^\]]*\]", txt):
            if NONSPEECH.match(tok.strip()):
                spans.append((cue.start, cue.end))
                break
    merged = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1] + 1.0:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [tuple(x) for x in merged]


# -------------------------------------------------------------- utterances

class Utt:
    __slots__ = ("start", "end", "text", "nwords", "change")

    def __init__(self, start, end, text, nwords, change):
        self.start, self.end = start, end
        self.text, self.nwords, self.change = text, nwords, change

    def as_dict(self):
        return {"start": round(self.start, 3), "end": round(self.end, 3),
                "words": self.nwords, "speaker_change": self.change}


def segment(stream):
    """Group the word stream into utterances at silences >= UTTERANCE_GAP_S."""
    utts, cur = [], []
    for i, (t, w, change) in enumerate(stream):
        clean_w = w.strip()
        if CENSORED.match(clean_w):
            clean_w = "[bleep]"
        elif NONSPEECH.match(clean_w):
            continue
        if not clean_w:
            continue
        if cur:
            prev_t, prev_w = cur[-1][0], cur[-1][1]
            prev_end = min(prev_t + word_dur(prev_w), t)
            if t - prev_end >= UTTERANCE_GAP_S or change:
                utts.append(_mk(cur))
                cur = []
        cur.append((t, clean_w, change))
    if cur:
        utts.append(_mk(cur))
    return utts


def _mk(chunk):
    t0, w0, change = chunk[0]
    tN, wN, _ = chunk[-1]
    text = " ".join(w for _, w, _ in chunk)
    return Utt(t0, tN + word_dur(wN), text, len(chunk), bool(change))


def chain_runs(utts):
    """Runs of back-and-forth: an utterance, then another VOICE inside
    CHAIN_GAP_S, and so on.  The runner's chain table models exactly this —
    chain_p is the odds of the first hop, chain_decay the fall-off after it —
    so a run-length histogram gives both numbers at once.  Returns
    (run lengths, the gaps inside runs).
    """
    runs, gaps, cur = [], [], 1
    for a, b in zip(utts, utts[1:]):
        gap = max(0.0, b.start - a.end)
        if b.change and gap <= CHAIN_GAP_S:
            cur += 1
            gaps.append(gap)
        else:
            runs.append(cur)
            cur = 1
    runs.append(cur)
    return runs, gaps


def hop_probs(runs, max_hops=4):
    """P(a run reaches hop k+1 | it reached hop k) for k = 1..max_hops."""
    out = {}
    for k in range(1, max_hops + 1):
        at_k = sum(1 for r in runs if r >= k)
        past = sum(1 for r in runs if r >= k + 1)
        out[f"hop{k}_p"] = round(past / at_k, 3) if at_k else None
    return out


def overlaps(span, spans):
    s, e = span
    for a, b in spans:
        lo, hi = max(s, a), min(e, b)
        if hi > lo and (hi - lo) >= 0.5 * max(0.001, e - s):
            return True
    return False


# ------------------------------------------------------------- measurements

def pct(values, q):
    if not values:
        return None
    vs = sorted(values)
    if len(vs) == 1:
        return vs[0]
    k = (len(vs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return vs[lo] + (vs[hi] - vs[lo]) * (k - lo)


def is_question(text: str) -> bool:
    return text.rstrip().endswith("?")


def is_backchannel(u: Utt) -> bool:
    """A whole utterance that is nothing but a murmur."""
    ws = [w.strip(".,!?").lower() for w in u.text.split()]
    return 0 < len(ws) <= 2 and all(w in BACKCHANNEL for w in ws)


def opens_with_backchannel(u: Utt) -> bool:
    """A turn that STARTS with a murmur ("Yeah. Yeah, that's easy.").

    Auto-captions rarely keep a bare "Yeah." as its own caption — the same
    speaker keeps talking and the aligner glues it on — so the whole-utterance
    rate above is a severe undercount.  The opening-murmur rate is the honest
    stand-in, and it is also the shape BACKCHANNEL_P models: a murmur riding
    in front of (or under) the line that answers.
    """
    ws = [w.strip(".,!?").lower() for w in u.text.split()]
    if not ws:
        return False
    return ws[0] in BACKCHANNEL


def is_proposal(text: str) -> bool:
    if not PROPOSAL_VERBS.search(text):
        return False
    return bool(PRONOUN.search(text) or NAMEISH.search(text))


def measure(utts, cues, ns_spans, duration_s):
    """Everything the doc's tables need, for one video."""
    res = {"utterances": len(utts)}
    if not utts:
        return res

    span = (utts[-1].end - utts[0].start) or 1.0
    minutes = span / 60.0
    res["span_s"] = round(span, 1)
    res["duration_s"] = round(duration_s, 1)

    gaps, gaps_kept = [], []
    for a, b in zip(utts, utts[1:]):
        g = max(0.0, b.start - a.end)
        gaps.append(g)
        if not overlaps((a.end, b.start), ns_spans):
            gaps_kept.append(g)
    res["gaps_n"] = len(gaps_kept)
    res["gap_median_s"] = round(statistics.median(gaps_kept), 2) if gaps_kept else None
    res["gap_p75_s"] = round(pct(gaps_kept, 0.75), 2) if gaps_kept else None
    res["gap_p90_s"] = round(pct(gaps_kept, 0.90), 2) if gaps_kept else None
    res["gap_p99_s"] = round(pct(gaps_kept, 0.99), 2) if gaps_kept else None
    res["gap_max_s"] = round(max(gaps_kept), 2) if gaps_kept else None
    res["gap_mean_s"] = round(statistics.fmean(gaps_kept), 2) if gaps_kept else None
    total_gap = sum(gaps_kept)
    res["gap_time_share"] = round(total_gap / span, 4)
    for thr in LONG_GAPS_S:
        big = [g for g in gaps_kept if g > thr]
        res[f"gaps_over_{int(thr)}s_n"] = len(big)
        res[f"gaps_over_{int(thr)}s_time_share"] = round(sum(big) / span, 4)
        res[f"gaps_over_{int(thr)}s_per_min"] = round(len(big) / minutes, 3)

    # onset-to-onset interval: how often a NEW line starts.  This, not the
    # silence between lines, is what the runner's min_gap_s actually paces.
    onsets = [b.start - a.start for a, b in zip(utts, utts[1:])]
    res["onset_median_s"] = round(statistics.median(onsets), 2) if onsets else None
    res["onset_p90_s"] = round(pct(onsets, 0.90), 2) if onsets else None

    res["utt_per_min"] = round(len(utts) / minutes, 2)
    res["words_per_utt_median"] = statistics.median(u.nwords for u in utts)
    res["words_per_utt_mean"] = round(statistics.fmean(u.nwords for u in utts), 2)
    res["words_per_min"] = round(sum(u.nwords for u in utts) / minutes, 1)
    res["utt_seconds_median"] = round(statistics.median(u.end - u.start for u in utts), 2)

    # question -> answer
    lat, q_follow, qs = [], 0, 0
    for a, b in zip(utts, utts[1:]):
        if not is_question(a.text):
            continue
        qs += 1
        lat.append(max(0.0, b.start - a.end))
        if is_question(b.text):
            q_follow += 1
    res["questions_n"] = qs
    res["questions_per_min"] = round(qs / minutes, 2)
    res["q_latency_median_s"] = round(statistics.median(lat), 2) if lat else None
    res["q_latency_p75_s"] = round(pct(lat, 0.75), 2) if lat else None
    res["q_latency_p90_s"] = round(pct(lat, 0.90), 2) if lat else None
    res["q_answer_is_question_rate"] = round(q_follow / qs, 3) if qs else None
    res["q_answered_within_2s_rate"] = round(
        sum(1 for x in lat if x <= 2.0) / len(lat), 3) if lat else None

    # proposals
    props = {"n": 0, "reply": 0, "reply_le2s": 0, "reply_2_8s": 0,
             "silence": 0, "nothing": 0,
             "reply_is_backchannel": 0, "reply_is_question": 0,
             "reply_is_speaker_change": 0}
    reply_lat = []
    for i, u in enumerate(utts):
        if not is_proposal(u.text):
            continue
        props["n"] += 1
        if i + 1 >= len(utts):
            props["nothing"] += 1
            continue
        nxt = utts[i + 1]
        d = max(0.0, nxt.start - u.end)
        if d <= PROPOSAL_WINDOW_S:
            props["reply"] += 1
            props["reply_le2s" if d <= 2.0 else "reply_2_8s"] += 1
            reply_lat.append(d)
            if is_backchannel(nxt) or opens_with_backchannel(nxt):
                props["reply_is_backchannel"] += 1
            if is_question(nxt.text):
                props["reply_is_question"] += 1
            if nxt.change:
                props["reply_is_speaker_change"] += 1
        else:
            props["silence"] += 1
    props["reply_rate"] = round(props["reply"] / props["n"], 3) if props["n"] else None
    props["reply_le2s_rate"] = round(props["reply_le2s"] / props["n"], 3) if props["n"] else None
    props["per_min"] = round(props["n"] / minutes, 3)
    props["reply_latency_median_s"] = round(statistics.median(reply_lat), 2) if reply_lat else None
    res["proposals"] = props

    # backchannel: bare murmurs, and turns that open with one
    bc = [u for u in utts if is_backchannel(u)]
    bo = [u for u in utts if opens_with_backchannel(u)]
    res["backchannel_n"] = len(bc)
    res["backchannel_per_min"] = round(len(bc) / minutes, 2)
    res["backchannel_share_of_utts"] = round(len(bc) / len(utts), 3)
    res["backchannel_open_n"] = len(bo)
    res["backchannel_open_per_min"] = round(len(bo) / minutes, 2)
    res["backchannel_open_share_of_utts"] = round(len(bo) / len(utts), 3)
    res["backchannel_note"] = ("a bare murmur is nearly always glued to the "
                               "speaker's next sentence by the aligner, so "
                               "backchannel_per_min is a floor; the opening "
                               "rate is the usable number")

    # chains: how far a back-and-forth runs before it dies
    runs, cgaps = chain_runs(utts)
    ch = {"runs_n": len(runs),
          "mean_len": round(statistics.fmean(runs), 2) if runs else None,
          "median_len": statistics.median(runs) if runs else None,
          "max_len": max(runs) if runs else None,
          "per_min": round(len(runs) / minutes, 2),
          "gap_inside_median_s": round(statistics.median(cgaps), 2) if cgaps else None,
          "gap_inside_p90_s": round(pct(cgaps, 0.90), 2) if cgaps else None}
    ch.update(hop_probs(runs))
    if ch.get("hop1_p") and ch.get("hop2_p"):
        ch["decay_hop2_over_hop1"] = round(ch["hop2_p"] / ch["hop1_p"], 3)
    res["chains"] = ch

    # overlap (a floor — see the module docstring)
    ov = 0
    for a, b in zip(cues, cues[1:]):
        if b.start < a.end - 0.05:
            ov += 1
    res["cue_overlap_rate"] = round(ov / max(1, len(cues) - 1), 4)
    res["cue_overlap_is_floor"] = True

    # speaker-change markers (">>"), when the track carries them
    ch = sum(1 for u in utts if u.change)
    res["speaker_change_marks_n"] = ch
    res["speaker_change_marks_per_min"] = round(ch / minutes, 2)
    res["active_player"] = None
    res["active_player_note"] = ("not recoverable from captions: no speaker "
                                 "labels, and '>>' marks a change of voice, "
                                 "never an identity or a turn")
    return res


# ------------------------------------------------------------------ driving

def analyse_file(path: Path):
    cues = read_cues(path)
    if not cues:
        return {"file": path.name, "error": "no cues (missing or empty)"}, []
    timed = sum(1 for c in cues if any("<" in ln and INLINE_TS.search(ln) for ln in c.lines))
    word_timed = timed >= 0.3 * len(cues)
    stream = words_from_cues(cues) if word_timed else words_from_plain_cues(cues)
    if not stream:
        return {"file": path.name, "error": "no words parsed"}, []
    ns = nonspeech_spans(cues)
    utts = segment(stream)
    duration = max(c.end for c in cues)
    out = measure(utts, cues, ns, duration)
    out["file"] = path.name
    out["video_id"] = path.name.split(".")[0]
    out["caption_track"] = path.name.split(".")[1] if "." in path.name else "?"
    out["caption_kind"] = "auto (word-timed)" if word_timed else "plain cues (no word timings)"
    out["cues"] = len(cues)
    out["nonspeech_spans"] = len(ns)
    out["nonspeech_s"] = round(sum(e - s for s, e in ns), 1)
    return out, utts


def pool(utt_sets, cue_counts):
    """Pool utterances across videos: stats are computed within each video and
    concatenated, so no gap ever straddles two videos."""
    gaps, onsets, all_utts, minutes = [], [], [], 0.0
    qlat, qn, qq, q2 = [], 0, 0, 0
    props = {"n": 0, "reply": 0, "reply_le2s": 0, "silence": 0, "nothing": 0}
    bc, bo, chg = 0, 0, 0
    runs, cgaps = [], []
    for utts in utt_sets:
        if not utts:
            continue
        span = (utts[-1].end - utts[0].start) or 1.0
        minutes += span / 60.0
        all_utts.extend(utts)
        r, g = chain_runs(utts)
        runs.extend(r)
        cgaps.extend(g)
        for a, b in zip(utts, utts[1:]):
            gaps.append(max(0.0, b.start - a.end))
            onsets.append(b.start - a.start)
            if is_question(a.text):
                qn += 1
                lat = max(0.0, b.start - a.end)
                qlat.append(lat)
                if lat <= 2.0:
                    q2 += 1
                if is_question(b.text):
                    qq += 1
        for i, u in enumerate(utts):
            if is_backchannel(u):
                bc += 1
            if opens_with_backchannel(u):
                bo += 1
            if u.change:
                chg += 1
            if is_proposal(u.text):
                props["n"] += 1
                if i + 1 >= len(utts):
                    props["nothing"] += 1
                elif utts[i + 1].start - u.end <= PROPOSAL_WINDOW_S:
                    props["reply"] += 1
                    if utts[i + 1].start - u.end <= 2.0:
                        props["reply_le2s"] += 1
                else:
                    props["silence"] += 1
    if not all_utts:
        return {"utterances": 0}
    total_s = minutes * 60.0
    res = {
        "videos": len([u for u in utt_sets if u]),
        "hours": round(minutes / 60.0, 2),
        "utterances": len(all_utts),
        "gap_median_s": round(statistics.median(gaps), 2) if gaps else None,
        "gap_p75_s": round(pct(gaps, 0.75), 2) if gaps else None,
        "gap_p90_s": round(pct(gaps, 0.90), 2) if gaps else None,
        "gap_p99_s": round(pct(gaps, 0.99), 2) if gaps else None,
        "gap_max_s": round(max(gaps), 2) if gaps else None,
        "gap_mean_s": round(statistics.fmean(gaps), 2) if gaps else None,
        "onset_median_s": round(statistics.median(onsets), 2) if onsets else None,
        "onset_p90_s": round(pct(onsets, 0.90), 2) if onsets else None,
        "utt_per_min": round(len(all_utts) / minutes, 2),
        "words_per_utt_median": statistics.median(u.nwords for u in all_utts),
        "utt_seconds_median": round(statistics.median(u.end - u.start for u in all_utts), 2),
        "questions_n": qn,
        "q_latency_median_s": round(statistics.median(qlat), 2) if qlat else None,
        "q_latency_p90_s": round(pct(qlat, 0.90), 2) if qlat else None,
        "q_answer_is_question_rate": round(qq / qn, 3) if qn else None,
        "q_answered_within_2s_rate": round(q2 / qn, 3) if qn else None,
        "backchannel_per_min": round(bc / minutes, 2),
        "backchannel_share_of_utts": round(bc / len(all_utts), 3),
        "backchannel_open_per_min": round(bo / minutes, 2),
        "backchannel_open_share_of_utts": round(bo / len(all_utts), 3),
        "speaker_change_marks_n": chg,
        "speaker_change_share_of_utts": round(chg / len(all_utts), 3),
        "proposals": dict(props, reply_rate=round(props["reply"] / props["n"], 3)
                          if props["n"] else None,
                          reply_le2s_rate=round(props["reply_le2s"] / props["n"], 3)
                          if props["n"] else None,
                          per_min=round(props["n"] / minutes, 3)),
        "cues": sum(cue_counts),
        "active_player": None,
    }
    res["gap_time_share"] = round(sum(gaps) / total_s, 4)
    res["speech_time_share"] = round(1.0 - res["gap_time_share"], 4)
    ch = {"runs_n": len(runs),
          "mean_len": round(statistics.fmean(runs), 2) if runs else None,
          "median_len": statistics.median(runs) if runs else None,
          "max_len": max(runs) if runs else None,
          "per_min": round(len(runs) / minutes, 2),
          "gap_inside_median_s": round(statistics.median(cgaps), 2) if cgaps else None,
          "gap_inside_p90_s": round(pct(cgaps, 0.90), 2) if cgaps else None}
    ch.update(hop_probs(runs))
    if ch.get("hop1_p") and ch.get("hop2_p"):
        ch["decay_hop2_over_hop1"] = round(ch["hop2_p"] / ch["hop1_p"], 3)
    res["chains"] = ch
    for thr in LONG_GAPS_S:
        big = [g for g in gaps if g > thr]
        res[f"gaps_over_{int(thr)}s_per_min"] = round(len(big) / minutes, 3)
        res[f"gaps_over_{int(thr)}s_time_share"] = round(sum(big) / total_s, 4)
    return res


# -------------------------------------------------------------- runner logs

def analyse_runner_log(path: Path, kinds=("bark",), seats_only=True):
    """The same gap statistics over the arena's own voice log.

    A `spoke` record carries `ts` (when the line started), `seconds` (how long
    it played), `kind` and `stock`.  The seats' lines are kind "bark" with a
    seat; kind "atom" is the murmur layer and is excluded, as are Joshua's
    advice/quip/colour lines, which are not table talk.
    """
    rows = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"file": str(path), "error": "unreadable"}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("event") != "spoke":
            continue
        rows.append(rec)
    if not rows:
        return {"file": str(path), "error": "no spoke records"}
    rows.sort(key=lambda r: r.get("ts", 0.0))
    game_span = (rows[-1].get("ts", 0.0) + float(rows[-1].get("seconds") or 0.0)
                 - rows[0].get("ts", 0.0)) or 1.0

    sel = [r for r in rows if r.get("kind") in kinds
           and (not seats_only or r.get("seat") is not None)]
    out = {"file": str(path), "archive": path.parent.name,
           "spoke_records": len(rows), "selected": len(sel),
           "kinds": sorted({r.get("kind") for r in rows}),
           "game_span_s": round(game_span, 1),
           "game_span_min": round(game_span / 60.0, 1)}
    if len(sel) < 2:
        return out
    gaps = []
    for a, b in zip(sel, sel[1:]):
        gaps.append(max(0.0, b["ts"] - (a["ts"] + float(a.get("seconds") or 0.0))))
    minutes = game_span / 60.0
    out.update({
        "gap_median_s": round(statistics.median(gaps), 2),
        "gap_p75_s": round(pct(gaps, 0.75), 2),
        "gap_p90_s": round(pct(gaps, 0.90), 2),
        "gap_p99_s": round(pct(gaps, 0.99), 2),
        "gap_max_s": round(max(gaps), 2),
        "gap_mean_s": round(statistics.fmean(gaps), 2),
        "utt_per_min": round(len(sel) / minutes, 2),
        "utt_seconds_median": round(statistics.median(
            float(r.get("seconds") or 0.0) for r in sel), 2),
        "speech_time_share": round(sum(float(r.get("seconds") or 0.0)
                                       for r in sel) / game_span, 4),
    })
    for thr in LONG_GAPS_S:
        big = [g for g in gaps if g > thr]
        out[f"gaps_over_{int(thr)}s_n"] = len(big)
        out[f"gaps_over_{int(thr)}s_per_min"] = round(len(big) / minutes, 3)
        out[f"gaps_over_{int(thr)}s_time_share"] = round(sum(big) / game_span, 4)
    # the same chain measure as the corpus: a different SEAT answering inside
    # CHAIN_GAP_S.  Here the speaker is known, so this is the exact quantity
    # chain_p / chain_decay govern.
    pseudo, prev_seat = [], None
    for r in sel:
        t0 = float(r["ts"])
        t1 = t0 + float(r.get("seconds") or 0.0)
        pseudo.append(Utt(t0, t1, str(r.get("stock") or ""), 1,
                          prev_seat is not None and r.get("seat") != prev_seat))
        prev_seat = r.get("seat")
    runs, cgaps = chain_runs(pseudo)
    ch = {"runs_n": len(runs),
          "mean_len": round(statistics.fmean(runs), 2) if runs else None,
          "median_len": statistics.median(runs) if runs else None,
          "max_len": max(runs) if runs else None,
          "per_min": round(len(runs) / minutes, 2),
          "gap_inside_median_s": round(statistics.median(cgaps), 2) if cgaps else None}
    ch.update(hop_probs(runs))
    if ch.get("hop1_p") and ch.get("hop2_p"):
        ch["decay_hop2_over_hop1"] = round(ch["hop2_p"] / ch["hop1_p"], 3)
    out["chains"] = ch

    atoms = [r for r in rows if r.get("kind") == "atom"]
    out["atoms_n"] = len(atoms)
    out["atoms_per_min"] = round(len(atoms) / minutes, 2)
    out["atoms_per_bark"] = round(len(atoms) / len(sel), 3) if sel else None
    by_seat = {}
    for r in sel:
        by_seat[str(r.get("seat"))] = by_seat.get(str(r.get("seat")), 0) + 1
    out["by_seat"] = by_seat
    return out


# ------------------------------------------------------------------ reports

def fmt(v, nd=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def md_row(label, r):
    p = r.get("proposals") or {}
    c = r.get("chains") or {}
    share4 = r.get("gaps_over_4s_time_share")
    return ("| " + " | ".join([
        label,
        fmt(r.get("gap_median_s")), fmt(r.get("gap_p75_s")), fmt(r.get("gap_p90_s")),
        fmt(r.get("gap_p99_s")), fmt(r.get("gap_max_s"), 1),
        fmt(r.get("onset_median_s")),
        fmt(share4 * 100 if share4 is not None else None, 1),
        fmt(r.get("gaps_over_15s_per_min"), 3), fmt(r.get("gaps_over_30s_per_min"), 3),
        fmt(r.get("utt_per_min")), fmt(r.get("words_per_utt_median"), 0),
        fmt(r.get("q_latency_median_s")), fmt(r.get("q_answer_is_question_rate"), 2),
        fmt(p.get("reply_rate"), 2), fmt(p.get("reply_le2s_rate"), 2),
        fmt(r.get("backchannel_open_per_min")),
        fmt(c.get("hop1_p"), 2), fmt(c.get("hop2_p"), 2), fmt(c.get("mean_len")),
    ]) + " |")


MD_HEAD = ("| scope | gap med | p75 | p90 | p99 | max | onset med | % time in >4 s | "
           ">15 s /min | >30 s /min | utt/min | words/utt | Q→A med | Q→Q | "
           "prop reply ≤8 s | ≤2 s | bc-open/min | hop1 | hop2 | chain len |\n"
           + "|---" * 20 + "|")


def render_markdown(per_source, pooled_all):
    lines = ["# Pod timing — measured", "", MD_HEAD]
    for src in sorted(per_source):
        lines.append(md_row(f"**{src}**", per_source[src]["pooled"]))
    lines.append(md_row("**pooled (all sources)**", pooled_all))
    lines.append("")
    lines.append("Per video:")
    lines.append("")
    lines.append(MD_HEAD)
    for src in sorted(per_source):
        for v in per_source[src]["videos"]:
            if "error" in v:
                lines.append(f"| {src}/{v.get('file')} — {v['error']} |" + " — |" * 19)
            else:
                lines.append(md_row(f"{src}/{v['video_id']}", v))
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus", nargs="?", help="corpus dir: <corpus>/<source>/*.vtt")
    ap.add_argument("--runner-log", nargs="*", default=None,
                    help="one or more voice-0.jsonl files to measure instead")
    ap.add_argument("--out", default=None, help="write per-video JSON here")
    ap.add_argument("--md", default=None, help="write the markdown tables here")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.runner_log is not None:
        results = [analyse_runner_log(Path(p)) for p in args.runner_log]
        print(json.dumps(results, indent=1))
        if args.md:
            rows = [MD_HEAD] + [md_row(r.get("archive", r["file"]), r) for r in results]
            Path(args.md).write_text("\n".join(rows) + "\n", encoding="utf-8")
        return 0

    if not args.corpus:
        ap.error("a corpus dir or --runner-log is required")
    root = Path(args.corpus)
    if not root.is_dir():
        print(f"no such corpus dir: {root}", file=sys.stderr)
        return 2
    out_dir = Path(args.out) if args.out else root / "_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    per_source, every_utts, every_cues = {}, [], []
    for src_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        vids, utt_sets, cue_counts = [], [], []
        seen_ids = set()
        for vtt in sorted(src_dir.glob("*.vtt")):
            vid = vtt.name.split(".")[0]
            if vid in seen_ids:            # yt-dlp may write en and en-orig
                continue
            seen_ids.add(vid)
            res, utts = analyse_file(vtt)
            res["source"] = src_dir.name
            vids.append(res)
            utt_sets.append(utts)
            cue_counts.append(res.get("cues", 0))
            if not args.quiet:
                print(f"{src_dir.name}/{vid}: "
                      f"{res.get('utterances', 0)} utterances, "
                      f"gap med {res.get('gap_median_s')}s", file=sys.stderr)
        if not vids:
            continue
        per_source[src_dir.name] = {"videos": vids,
                                    "pooled": pool(utt_sets, cue_counts)}
        every_utts.extend(utt_sets)
        every_cues.extend(cue_counts)

    if not per_source:
        print("corpus is empty — nothing to measure", file=sys.stderr)
        return 1

    pooled_all = pool(every_utts, every_cues)
    payload = {"corpus": str(root), "sources": per_source, "pooled": pooled_all}
    (out_dir / "pod_timing.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    md = render_markdown(per_source, pooled_all)
    (Path(args.md) if args.md else out_dir / "pod_timing.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
