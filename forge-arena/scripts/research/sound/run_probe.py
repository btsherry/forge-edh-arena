"""BL-56 (2026-09-17): measure Forge's sound effects through a loopback device.

Records the machine's own output (macOS avfoundation, device by NAME — ARENA_LOOPBACK, default "Cable Creation")
while SoundProbe.java plays the 39 effects through Forge's exact clip path ("clip"), Forge's alternate streaming
path ("alt") or afplay as a CoreAudio baseline ("afplay"); suffix "16" feeds 16-bit ffmpeg decodes, "C16" Forge's
converter asked for 16-bit. SEQ=burst plays seven opening draws at 120 ms three times plus long controls and reports
impulses and held-sample runs per window — the metric that separated the players. Set the system output to the
loopback at about 30 % (the cable clips at 100 %). Needs ffmpeg and a built desktop fat jar.

  cd forge-arena/scripts/research/sound
  JAVA_HOME=$JDK17 SEQ=burst python3 run_probe.py clip afplay          # after the fix: clip should match afplay
  JAVA_HOME=$JDK17 python3 run_probe.py clip                            # the full 39-asset onset/offset pass
Sources for the residual comparison: `java -cp <fat jar> SoundProbe.java dump <res/sound> out/x.jsonl` writes out/src/.
Findings and numbers: forge-arena/docs/BUG-LOG.md BL-56."""
import json, math, os, signal, struct, subprocess, sys, time, wave
S = os.environ.get("PROBE_OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")   # recordings + logs (gitignored)
os.makedirs(S, exist_ok=True)
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))   # the repo root
import glob as _glob
JAR = os.environ.get("PROBE_JAR") or max(_glob.glob(os.path.join(ROOT, "forge-gui-desktop", "target", "forge-gui-desktop-*-jar-with-dependencies.jar")), key=os.path.getmtime)
SND = os.path.join(ROOT, "forge-gui", "res", "sound")
JAVA = os.path.join(os.environ.get("JAVA_HOME", "/usr"), "bin", "java") if os.environ.get("JAVA_HOME") else "java"
DEVICE = os.environ.get("ARENA_LOOPBACK", "Cable Creation")      # the loopback's NAME (its index moves when a phone connects)
PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SoundProbe.java")

def record_and_play(mode):
    rec = f"{S}/{mode}.wav"; log = f"{S}/{mode}.jsonl"
    ff = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "avfoundation", "-i", ":" + DEVICE, "-ac", "1", "-ar", "48000", rec])
    t0 = time.time()
    time.sleep(1.5)
    r = subprocess.run([JAVA, "-cp", JAR, PROBE, mode, SND, log] + (["burst"] if os.environ.get("SEQ") == "burst" else []), capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print(mode, "probe failed:", r.stderr[-800:]); ff.send_signal(signal.SIGINT); ff.wait(); return None
    time.sleep(1.0)
    ff.send_signal(signal.SIGINT); ff.wait(timeout=10)
    return rec, log, t0

def load(rec):
    w = wave.open(rec); fr = w.getframerate(); n = w.getnframes(); sw = w.getsampwidth()
    data = w.readframes(n); w.close()
    xs = struct.unpack("<%dh" % (len(data) // 2), data) if sw == 2 else struct.unpack("<%di" % (len(data) // 4), data)
    full = float(2 ** (8 * sw - 1))
    return [x / full for x in xs], fr

def clicks(x, fr, a, b):
    """Discontinuities inside [a, b) seconds: a step between neighbouring samples far above the window's typical step."""
    i0, i1 = max(1, int(a * fr)), min(len(x), int(b * fr))
    if i1 - i0 < 100: return 0, 0.0, 0.0
    diffs = [abs(x[i] - x[i - 1]) for i in range(i0, i1)]
    med = sorted(diffs)[len(diffs) // 2]
    thr = max(0.06, 12 * med)
    n = 0; last = -10; worst = 0.0
    for k, d in enumerate(diffs):
        if d > thr and k - last > int(0.003 * fr):
            n += 1; last = k; worst = max(worst, d)
    peak = max(abs(v) for v in x[i0:i1])
    return n, worst, peak

def onset(x, fr, a, b):
    """Where the sound starts inside the window (first sample above -40 dBFS), and how hard: the level 1 ms in."""
    i0, i1 = int(a * fr), min(len(x), int(b * fr))
    for i in range(i0, i1):
        if abs(x[i]) > 0.01:
            return i / fr, abs(x[i])
    return None, 0.0

SRC = "src"
def src_wave(name):
    w = wave.open(f"{S}/{SRC}/{name}.wav"); n = w.getnframes(); sw = w.getsampwidth(); fr = w.getframerate(); data = w.readframes(n); w.close()
    if sw == 1: xs = [(b - 128) / 128.0 for b in data]
    else: xs = [v / 32768.0 for v in struct.unpack("<%dh" % n, data)]
    return xs, fr

def env(x, fr, a, b, step_ms=2.0):
    """RMS envelope in step_ms slices over [a, b) seconds."""
    i0, i1 = max(0, int(a * fr)), min(len(x), int(b * fr)); w = max(1, int(step_ms / 1000 * fr)); out = []
    for i in range(i0, i1, w):
        seg = x[i:i + w]; out.append(math.sqrt(sum(v * v for v in seg) / len(seg)) if seg else 0.0)
    return out

def bounds(x, fr, a=0.0, b=None, thr=0.01):
    """First and last sample above thr inside [a, b), in seconds; None when silent."""
    i0, i1 = int(a * fr), (len(x) if b is None else min(len(x), int(b * fr)))
    first = next((i for i in range(i0, i1) if abs(x[i]) > thr), None)
    if first is None: return None, None
    last = next((i for i in range(i1 - 1, first, -1) if abs(x[i]) > thr), first)
    return first / fr, last / fr

def window_metrics(x, fr, a, b):
    e = env(x, fr, a, b, 2.0)
    med = sorted(e)[len(e) // 2]; spikes = sum(1 for i in range(1, len(e) - 1) if e[i] > 4 * max(med, 0.01) and e[i] > 3 * max(e[i-1], e[i+1], 0.005))
    i0, i1 = int(a * fr), min(len(x), int(b * fr)); flats = 0; i = i0 + 1
    while i < i1:
        j = i
        while j < i1 and abs(x[j] - x[j-1]) < 1e-4 and abs(x[j]) < 0.98: j += 1
        if j - i >= int(0.0015 * fr) and max(abs(v) for v in x[max(i0, i-int(0.02*fr)):min(i1, j+int(0.02*fr))]) > 0.05: flats += 1
        i = j + 1
    return dict(spikes=spikes, flats=flats, peak=round(max(abs(v) for v in x[i0:i1]), 3))

def analyse_burst(mode, rec, log, t0):
    x, fr = load(rec)
    plays = [json.loads(l) for l in open(log)]
    first = plays[0]["t_ms"] / 1000 - t0
    on, _ = onset(x, fr, max(0, first - 0.5), first + 2.0)
    shift = (on - first) if on is not None else 0.0
    out = {}
    for b in range(3):
        ds = [p for p in plays if p["name"] == "draw" and p["rep"] // 10 == b]
        a = ds[0]["t_ms"] / 1000 - t0 + shift - 0.05; e = ds[-1]["t_ms"] / 1000 - t0 + shift + 0.6
        out[f"draw-burst-{b+1}"] = window_metrics(x, fr, a, e)
    for name, dur in (("nighttime", 3.3), ("mana_burn", 1.7), ("shuffle", 0.7)):
        p = next(p for p in plays if p["name"] == name and p["rep"] == 0)
        a = p["t_ms"] / 1000 - t0 + shift - 0.05
        out[name] = window_metrics(x, fr, a, a + dur + 0.1)
    return out, shift

def analyse(mode, rec, log, t0):
    x, fr = load(rec)
    plays = [json.loads(l) for l in open(log)]
    first = plays[0]["t_ms"] / 1000 - t0
    on, _ = onset(x, fr, max(0, first - 0.5), first + 2.0)
    shift = (on - first) if on is not None else 0.0
    rows = []
    burst = None
    for k, p in enumerate(plays):
        t = p["t_ms"] / 1000 - t0 + shift
        sx, sfr = src_wave(p["name"])
        s_on, s_end = bounds(sx, sfr)
        if s_on is None: continue
        if p["name"] == "draw" and p["rep"] > 0:      # the opening seven draws overlap: judged as one burst below
            continue
        r_on, _ = bounds(x, fr, t - 0.03, t + 0.4)
        if r_on is None:
            rows.append((p["name"], p["rep"], None, None, None, None, 0)); continue
        span = s_end - s_on
        rec_on = max(env(x, fr, r_on, r_on + 0.003, 1.0) or [0]); src_on = max(env(sx, sfr, s_on, s_on + 0.003, 1.0) or [0])
        rec_off = max(env(x, fr, r_on + span + 0.002, r_on + span + 0.010, 1.0) or [0]); src_off = max(env(sx, sfr, s_end + 0.002, min(len(sx)/sfr, s_end + 0.010), 1.0) or [0])
        seg = x[int((r_on - 0.005) * fr):int((r_on + span + 0.02) * fr)]
        clip = sum(1 for v in seg if abs(v) >= 0.98)
        rows.append((p["name"], p["rep"], round(rec_on, 3), round(src_on, 3), round(rec_off, 3), round(src_off, 3), clip))
    # the burst: seven draws at 120 ms — count impulses above the local envelope and flat (dropout) runs
    draws = [p for p in plays if p["name"] == "draw"]
    if draws:
        a = draws[0]["t_ms"] / 1000 - t0 + shift - 0.05; b = draws[-1]["t_ms"] / 1000 - t0 + shift + 0.6
        e = env(x, fr, a, b, 2.0)
        med = sorted(e)[len(e) // 2]; spikes = sum(1 for i in range(1, len(e) - 1) if e[i] > 4 * max(med, 0.01) and e[i] > 3 * max(e[i-1], e[i+1], 0.005))
        i0, i1 = int(a * fr), int(b * fr); flats = 0; i = i0 + 1
        while i < i1:
            j = i
            while j < i1 and abs(x[j] - x[j-1]) < 1e-4 and abs(x[j]) < 0.98: j += 1
            if j - i >= int(0.0015 * fr) and max(abs(v) for v in x[max(i0, i-int(0.02*fr)):min(i1, j+int(0.02*fr))]) > 0.05: flats += 1
            i = j + 1
        burst = dict(spikes=spikes, flats=flats, peak=round(max(abs(v) for v in x[i0:i1]), 3))
    return rows, shift, burst

if __name__ == "__main__":
    modes = sys.argv[1:] or ["clip", "alt", "afplay"]
    results = {}
    if os.environ.get("SEQ") == "burst":
        for m in modes:
            got = record_and_play(m)
            if not got: continue
            out, shift = analyse_burst(m, *got)
            xx, _fr = load(got[0]); pk = round(max(abs(v) for v in xx), 3)
            print(f"== {m} (align {shift:+.2f}s, recording peak {pk}{' — NO SIGNAL' if pk < 0.1 else ''}):", json.dumps(out))
        sys.exit(0)
    for m in modes:
        got = record_and_play(m)
        if not got: continue
        rows, shift, burst = analyse(m, *got)
        results[m] = {"rows": rows, "burst": burst}
        ok = [r for r in rows if r[2] is not None]
        pops_on = [r for r in ok if r[2] > 2.5 * max(0.02, r[3])]
        pops_off = [r for r in ok if r[4] > 2.5 * max(0.02, r[5])]
        print(f"== {m}: {len(ok)} plays judged, clipped {sum(r[6] for r in ok)}, align {shift:+.2f}s")
        print(f"   onset pops (first 3 ms > 2.5x source): {len(pops_on)} {[(r[0], r[2], r[3]) for r in pops_on[:6]]}")
        print(f"   offset pops (2-10 ms after end > 2.5x source): {len(pops_off)} {[(r[0], r[4], r[5]) for r in pops_off[:6]]}")
        print(f"   shuffle x3 (rec_on, src_on): {[(r[2], r[3]) for r in ok if r[0]=='shuffle'][:3]}   opening-draw burst: {burst}")
    json.dump(results, open(f"{S}/probe-results.json", "w"))
