"""OpenAI-compatible HTTP backends for seat brains (OpenRouter et al.).

Opt-in per seat via the model string (plan: ~/Claude/openrouter-backends-plan.md):
  bare name          -> Claude CLI (brain.py, untouched — the default)
  or/<vendor>/<id>   -> OpenRouter chat-completions (API-billed, cost-capped)
  oai/<id>           -> any OpenAI-compatible endpoint at ARENA_OAI_BASE_URL
                        (Ollama/vLLM/LM Studio; keyless endpoints are legal)

Design contract (the no-harm rules):
- Envelopes returned here are structurally compatible with the Claude CLI's
  (result/usage/total_cost_usd/is_error) but NEVER carry a session_id — that
  is what keeps a backend detour from poisoning the Claude --resume path.
- All failures degrade to None -> rules.safe_default(), same as a Claude
  timeout. Reads are wall-clock bounded (chunked, monotonic deadline) so the
  single-threaded seat loop can never wedge on a slow-drip response.
- Latches live on the BRAIN (runner lifetime), not this instance: auth-class
  (401/bare-403) keyed by base URL and never cleared mid-session; model-class
  (init 4xx, caps) keyed by model id and cleared on game reset.
- The API key is read from the environment inside this process only. It must
  never appear in argv, logs, or error text.

Stdlib only (the shipped package installs nothing).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

OR_BASE = "https://openrouter.ai/api/v1"
_PROBE_FILE = Path(__file__).parents[1] / "logs" / "cache" / "or-models.json"  # item 13f

# max_tokens = answer room + effort-derived reasoning headroom (plan F-14).
_ANSWER_TOKENS = 4096
_REASONING_HEADROOM = {"low": 2048, "medium": 8192}          # high+ -> 16384
_DEFAULT_COMPLETION_CAP = 8192                               # unprobed fallback


def parse_model(model) -> tuple[str, str]:
    """Classify a model string -> (kind, model_id); kind in claude|or|oai.
    Anything that isn't an or/ or oai/ prefix stays on the Claude CLI path
    (a bogus string there fails exactly the way it fails today)."""
    if isinstance(model, str) and "/" in model:
        prefix, _, rest = model.partition("/")
        if prefix == "or" and rest:
            return "or", rest
        if prefix == "oai" and rest:
            return "oai", rest
    return "claude", model if isinstance(model, str) else ""


def make(model, seat: int = 0, log=print):
    """Backend instance for a prefixed model string, else None (Claude path)."""
    kind, model_id = parse_model(model)
    if kind == "claude":
        return None
    return OpenAICompatBackend(kind, model_id, seat=seat, log=log)


def probe_meta(model_id: str) -> dict:
    """Best-effort per-model metadata from the launch probe's saved /models
    payload (run_table.sh writes logs/control/or-models.json). Returns
    {} when unprobed. ':suffix' routing shortcuts (:nitro/:floor) fall back
    to the base id — they never appear in the listing (plan F-30)."""
    try:
        data = json.loads(_PROBE_FILE.read_text())
    except (OSError, ValueError):
        return {}
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {}
    want = {model_id, model_id.partition(":")[0]}
    for row in rows:
        if isinstance(row, dict) and row.get("id") in want:
            top = row.get("top_provider") or {}
            return {"context_length": row.get("context_length"),
                    "max_completion_tokens": top.get("max_completion_tokens")}
    return {}


def _est_tokens(text: str) -> int:
    return int(len(text) / 4 * 1.25)  # bytes/4 heuristic, +25% margin (F-15)


class OpenAICompatBackend:
    """One HTTP-backed model transport for one seat.

    Owns the rolling transcript. Per-game counters (cost, attempts, unmetered)
    live in brain.totals so they survive instance swaps from re-dialing; the
    latch maps live on the brain for the same reason (plan F-06/F-09/F-18)."""

    def __init__(self, kind: str, model_id: str, seat: int = 0, log=print):
        self.kind = kind                      # "or" | "oai"
        self.model_id = model_id
        self.seat = seat
        self.log = log
        self.messages: list[dict] = []        # [system(init)] + user/asst pairs
        self.ready = False
        self._meta = None                     # lazy probe_meta
        self._no_cost_streak = 0
        self.cap_unenforceable = False
        self._warned_80pct = False
        self._latch_logged = False
        if kind == "or":
            self.base_url = OR_BASE
            self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        else:
            self.base_url = os.environ.get("ARENA_OAI_BASE_URL", "").rstrip("/")
            self.api_key = os.environ.get("ARENA_OAI_API_KEY", "")

    # ---- config ----------------------------------------------------------

    @staticmethod
    def _env_num(name: str, dflt: float) -> float:
        try:
            return float(os.environ.get(name, "") or dflt)
        except ValueError:
            return dflt

    def _cost_cap(self) -> float:
        return self._env_num("ARENA_MAX_SEAT_COST_USD", 5.0)

    def _call_cap(self) -> int:
        return int(self._env_num("ARENA_MAX_SEAT_CALLS", 250))

    def meta(self) -> dict:
        if self._meta is None:
            self._meta = probe_meta(self.model_id) if self.kind == "or" else {}
            if self.kind == "oai":
                ctx = self._env_num("ARENA_OAI_CTX", 0)
                if ctx > 0:
                    self._meta = {"context_length": int(ctx)}
        return self._meta

    def _max_tokens(self, effort: str) -> int:
        head = _REASONING_HEADROOM.get(effort, 16384)  # high/xhigh/max
        want = _ANSWER_TOKENS + head
        cap = self.meta().get("max_completion_tokens")
        if isinstance(cap, int) and cap > 0:
            want = min(want, cap)
        return max(want, 1024)

    def _history_keep(self, effort: str) -> int:
        keep = int(self._env_num("ARENA_BACKEND_HISTORY", 8))
        ctx = self.meta().get("context_length")
        if isinstance(ctx, int) and ctx > 0 and len(self.messages) > 0:
            init_est = _est_tokens(self.messages[0].get("content", ""))
            snap_est = 8000  # generous full-state decision prompt estimate
            room = ctx - init_est - snap_est - self._max_tokens(effort)
            per_exchange = 9000
            keep = min(keep, max(room // per_exchange, 0))
        return max(min(keep, 24), 2)

    # ---- transcript --------------------------------------------------------

    def _trim(self, keep_exchanges: int) -> None:
        """Keep system(init) + the last N whole user/assistant exchanges."""
        head, tail = self.messages[:1], self.messages[1:]
        if len(tail) > keep_exchanges * 2:
            tail = tail[-keep_exchanges * 2:]
            if tail and tail[0].get("role") == "assistant":
                tail = tail[1:]  # never open on an orphaned assistant turn
        self.messages = head + tail

    def _alternation_ok(self, msgs: list[dict]) -> bool:
        roles = [m["role"] for m in msgs]
        if not roles or roles[0] != "system" or roles[-1] != "user":
            return False
        body = roles[1:]
        return all(r == ("user" if i % 2 == 0 else "assistant")
                   for i, r in enumerate(body))

    def reset(self) -> None:
        self.messages = []
        self.ready = False

    # ---- latches & rails (state lives on the brain) ------------------------

    def _latched(self, brain) -> str | None:
        auth = brain.backend_latches["auth"].get(self.base_url)
        if auth:
            return auth
        return brain.backend_latches["model"].get(self.model_id)

    def _latch_auth(self, brain, why: str) -> None:
        brain.backend_latches["auth"][self.base_url] = why
        self.log(f"[seat {self.seat}] BACKEND LATCHED (auth): {why} — "
                 f"check OPENROUTER_API_KEY and restart the table")

    def _latch_model(self, brain, why: str) -> None:
        brain.backend_latches["model"][self.model_id] = why
        self.log(f"[seat {self.seat}] BACKEND LATCHED ({self.model_id}): {why} "
                 f"— seat falls to safe defaults for the rest of the game")

    def _rails_ok(self, brain) -> bool:
        cap = self._cost_cap()
        spent = brain.totals.get("cost_usd", 0.0)
        if cap > 0 and spent >= cap:
            if "__cost_cap__" not in brain.backend_latches["model"].get(
                    self.model_id, ""):
                self._latch_model(brain, f"__cost_cap__ ${spent:.2f} >= ${cap:.2f}")
            return False
        if cap > 0 and spent >= 0.8 * cap and not self._warned_80pct:
            self._warned_80pct = True
            self.log(f"[seat {self.seat}] backend spend ${spent:.2f} has crossed "
                     f"80% of the ${cap:.2f} cap")
        calls = self._call_cap()
        if calls > 0 and brain.totals.get("backend_attempts", 0) >= calls:
            self._latch_model(brain, f"__call_cap__ {calls} HTTP attempts")
            return False
        return True

    # ---- transport ---------------------------------------------------------

    def _http(self, body: dict, budget: float) -> tuple[int, str]:
        """One bounded HTTP round trip -> (status, decoded body). Raises
        urllib.error.URLError / socket.timeout for transport failures. The
        read is chunked against a monotonic deadline so a slow-drip response
        can never exceed the budget (plan F-07)."""
        t_end = time.monotonic() + budget
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        if self.kind == "or":
            headers["HTTP-Referer"] = "https://github.com/forge-light-llm"
            headers["X-Title"] = "forge-light-llm"
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode("utf-8"), headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=max(budget, 1.0))
        except urllib.error.HTTPError as e:
            raw = e.read(1 << 20) if e.fp else b""
            return e.code, raw.decode("utf-8", errors="replace")
        chunks, status = [], getattr(resp, "status", 200)
        try:
            while True:
                if time.monotonic() >= t_end:
                    raise TimeoutError("body read exceeded deadline")
                chunk = resp.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            resp.close()
        return status, b"".join(chunks).decode("utf-8", errors="replace")

    @staticmethod
    def _error_of(status: int, parsed) -> tuple[int, str, dict] | None:
        """Normalize an error to (code, message, metadata) — checks the BODY
        first, so OpenRouter's 200-with-embedded-error is classified (F-12)."""
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
            err = parsed["error"]
            code = err.get("code") if isinstance(err.get("code"), int) else status
            return (code or status, str(err.get("message", ""))[:200],
                    err.get("metadata") or {})
        if status >= 400:
            return status, "", {}
        return None

    def _envelope(self, parsed: dict) -> dict | None:
        choices = parsed.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        msg = (choices[0] or {}).get("message") or {}
        text = msg.get("content") or ""
        if (choices[0] or {}).get("finish_reason") == "length":
            self.log(f"[seat {self.seat}] backend answer TRUNCATED "
                     f"(finish_reason=length — raise max_tokens or lower effort)")
        usage_in = parsed.get("usage") or {}
        usage = {}
        if isinstance(usage_in.get("prompt_tokens"), (int, float)):
            usage["input_tokens"] = int(usage_in["prompt_tokens"])
        if isinstance(usage_in.get("completion_tokens"), (int, float)):
            usage["output_tokens"] = int(usage_in["completion_tokens"])
        details = usage_in.get("prompt_tokens_details") or {}
        if isinstance(details.get("cached_tokens"), (int, float)):
            usage["cache_read_input_tokens"] = int(details["cached_tokens"])
        env = {"result": text, "usage": usage, "is_error": False}
        cost = usage_in.get("cost")
        if isinstance(cost, (int, float)):
            env["total_cost_usd"] = float(cost)
            self._no_cost_streak = 0
        elif self.kind == "or":
            self._no_cost_streak += 1
            if self._no_cost_streak == 3 and not self.cap_unenforceable:
                self.cap_unenforceable = True
                self.log(f"[seat {self.seat}] cost reporting absent on this "
                         f"route — $ cap NOT enforceable; set a hard limit on "
                         f"the OpenRouter key (call cap still applies)")
        return env

    # ---- the call ----------------------------------------------------------

    def init(self, init_message: str, timeout_s: float, brain) -> dict | None:
        """Load the init payload as the system message and validate the route
        with one real round trip (auth/model/context all fail HERE, where the
        4xx latch is init-classed). The probe exchange is not stored."""
        if self._latched(brain):
            return None
        self.messages = [{"role": "system", "content": init_message}]
        env = self.call("Reply exactly: READY", timeout_s, brain,
                        effort="low", _is_init=True, _record=False)
        self.ready = env is not None
        if not self.ready:
            self.messages = []
        return env

    def call(self, prompt: str, timeout_s: float, brain, effort: str = "low",
             _is_init: bool = False, _record: bool = True) -> dict | None:
        latch = self._latched(brain)
        if latch:
            if not self._latch_logged:
                self._latch_logged = True
                self.log(f"[seat {self.seat}] backend latched ({latch[:80]}) — "
                         f"safe defaults until re-dial or new game")
            return None
        if not self._rails_ok(brain):
            return None
        keep = self._history_keep(effort)
        deadline = time.monotonic() + max(timeout_s, 1.0)
        attempt, dropped_reasoning, shrunk = 0, False, False
        while True:
            attempt += 1
            self._trim(keep)
            msgs = self.messages + [{"role": "user", "content": prompt}]
            if not self._alternation_ok(msgs):
                # Structural bug guard — rebuild to system+current rather than
                # send a request a strict provider will reject (F-29).
                self.log(f"[seat {self.seat}] transcript alternation repair")
                self.messages = self.messages[:1]
                msgs = self.messages + [{"role": "user", "content": prompt}]
            body = {"model": self.model_id, "messages": msgs,
                    "max_tokens": self._max_tokens(effort)}
            if self.kind == "or":
                body["usage"] = {"include": True}
                if not dropped_reasoning:
                    body["reasoning"] = {"effort": effort}
            budget = deadline - time.monotonic()
            if budget < 3.0:
                return None
            t0 = time.monotonic()
            brain.totals["backend_attempts"] = \
                brain.totals.get("backend_attempts", 0) + 1
            try:
                status, raw = self._http(body, budget)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                brain.totals["unmetered_attempts"] = \
                    brain.totals.get("unmetered_attempts", 0) + 1
                brain.totals["unmetered_est_tokens"] = \
                    brain.totals.get("unmetered_est_tokens", 0) \
                    + _est_tokens(json.dumps(body))
                elapsed = time.monotonic() - t0
                self.log(f"[seat {self.seat}] backend transport error "
                         f"({type(e).__name__}) after {elapsed:.0f}s")
                if attempt == 1 and elapsed < 15.0 \
                        and deadline - time.monotonic() >= 20.0:
                    continue
                return None
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = None
            err = self._error_of(status, parsed if parsed is not None else {})
            if err is None and parsed is not None:
                env = self._envelope(parsed)
                if env is not None:
                    if _record:
                        self.messages += [
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": env["result"]}]
                    return env
                err = (status, "no choices in response", {})
            if parsed is None and err is None:
                err = (status, "unparseable response body", {})
            code, message, meta = err
            elapsed = time.monotonic() - t0
            retryable = (attempt == 1 and elapsed < 15.0
                         and deadline - time.monotonic() >= 20.0)
            # --- classification (plan §3.5) ---
            if code == 401:
                self._latch_auth(brain, "401 unauthorized")
                return None
            if code == 403:
                moderation = any(k in meta for k in ("reasons", "flagged_input"))
                if moderation:
                    self._no_cost_streak = 0
                    self._mod_403 = getattr(self, "_mod_403", 0) + 1
                    self.log(f"[seat {self.seat}] moderation-flagged request "
                             f"({str(meta.get('provider_name', ''))[:40]}) — "
                             f"safe default this decision")
                    if self._mod_403 >= 3:
                        self._latch_model(brain, "3 consecutive moderation 403s")
                    return None
                self._latch_auth(brain, "403 forbidden")
                return None
            if code == 402:
                self._latch_model(brain, "402 — out of provider credits")
                return None
            if code == 429:
                if retryable:
                    retry_after = 2.0
                    delay = min(retry_after,
                                deadline - time.monotonic() - 20.0)
                    if delay > 0:
                        time.sleep(delay)
                        continue
                self.log(f"[seat {self.seat}] rate limited (429) — safe default")
                return None
            if code in (408,) or code >= 500:
                self.log(f"[seat {self.seat}] backend {code}: {message}")
                if retryable:
                    continue
                return None
            if 400 <= code < 500:
                lowered = message.lower()
                if not dropped_reasoning and "reasoning" in lowered:
                    dropped_reasoning = True     # F-36 reactive fallback
                    continue
                if any(s in lowered for s in ("context", "token", "length",
                                              "too long", "maximum")) \
                        and not _is_init:
                    if not shrunk and retryable:
                        shrunk = True
                        keep = max(keep // 2, 2)  # F-15 shrink-and-retry
                        self.log(f"[seat {self.seat}] context overflow — "
                                 f"shrinking history to {keep} exchanges")
                        continue
                    self._latch_model(brain, f"{code} context overflow "
                                             f"after shrink")
                    return None
                if _is_init:
                    self._latch_model(brain, f"init {code}: {message[:120]}")
                    return None
                self.log(f"[seat {self.seat}] backend {code}: {message[:120]} "
                         f"— safe default")
                return None
            self.log(f"[seat {self.seat}] backend unexpected status {code}")
            return None
        # unreachable

    def reset_mod_counter(self) -> None:
        self._mod_403 = 0

    def reset_for_new_game(self) -> None:
        self.reset()
        self._no_cost_streak = 0
        self._warned_80pct = False
        self._latch_logged = False
        self._mod_403 = 0
