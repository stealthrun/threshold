"""
Pull executed sessions from intervals.icu and map them into the `session` dicts the
reasoning core consumes — the data layer that lets the engine coach in context instead
of interpreting one run in a vacuum.

This is Layer 2 (see docs/ARCHITECTURE.md): the *only* place intervals.icu's API shape
appears. The core knows nothing about it. Two design choices follow the architecture doc:

  Dependency-light. HTTP is stdlib `urllib`; no `requests`, no SDK. The public core still
  runs cold.

  The credentials seam. Auth hides behind `Credentials` so the fetch logic asks only for
  "who + how to authenticate." Today that is a personal API key from the environment; a
  hosted OAuth backend can replace `Credentials.from_env` later without touching anything
  below it. (Why API key and not OAuth for a local skill: a distributed skill cannot keep
  a client secret — see the doc.)

Credentials (read from the environment, never written to the vault or logged):
  INTERVALS_API_KEY     personal API key from intervals.icu → Settings → Developer
  INTERVALS_ATHLETE_ID  e.g. i12345

Field-name note: the activity-object field names below follow intervals.icu's documented
schema. The mapping is deliberately tolerant (`.get` with fallbacks, like derive_signals)
and the *logic* is pinned by fixture tests, so an unexpected field degrades gracefully
rather than crashing. Confirm names against a live response when wiring a real key.

Scope: this module fetches executed activities. Turning the planned calendar into
`plan_targets` (so vs_plan has real targets) is the next step — it is the lab's hairiest
parser and earns its own module.

    python3 -m ingest.intervals_icu        # demo (needs the env vars above)
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import NamedTuple

BASE_URL = "https://intervals.icu/api/v1"

# A real User-Agent: intervals.icu's Cloudflare edge rejects the default urllib agent.
_USER_AGENT = "threshold/0.1 (+https://github.com/stealthrun/threshold)"


def _ssl_context() -> ssl.SSLContext:
    """A verifying TLS context that actually works on a stock install. Some Pythons (notably
    the python.org macOS build) ship with no CA trust store wired up, so the default context
    fails every HTTPS call with CERTIFICATE_VERIFY_FAILED. `certifi` carries Mozilla's CA
    bundle and is present in virtually any Python that has pip, so we use it when available
    and fall back to the default otherwise — no hard dependency, still verifying."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_SSL_CONTEXT = _ssl_context()

# intervals.icu activity `type` values that are runs (the only modality this engine reads).
RUN_TYPES = frozenset({"Run", "VirtualRun", "TrailRun"})


class IntervalsError(RuntimeError):
    """Any failure talking to intervals.icu (bad credentials, network, HTTP error)."""


# ── The credentials seam ──────────────────────────────────────────────────────────────

class Credentials(NamedTuple):
    """Who to fetch for and how to authenticate. The one place auth is represented, so a
    hosted OAuth token can replace the local API key later without changing the fetch."""

    athlete_id: str
    api_key: str  # SECRET — never log or persist this

    @classmethod
    def from_env(cls) -> "Credentials":
        """Build credentials from INTERVALS_ATHLETE_ID / INTERVALS_API_KEY. Raises a clear
        error naming the missing variable rather than failing deep in an HTTP call."""
        athlete_id = os.getenv("INTERVALS_ATHLETE_ID")
        api_key = os.getenv("INTERVALS_API_KEY")
        missing = [n for n, v in
                   (("INTERVALS_ATHLETE_ID", athlete_id), ("INTERVALS_API_KEY", api_key))
                   if not v]
        if missing:
            raise IntervalsError(f"missing environment variable(s): {', '.join(missing)}")
        return cls(athlete_id=athlete_id, api_key=api_key)

    def _auth_header(self) -> str:
        """intervals.icu Basic auth: username is the literal 'API_KEY', password the key."""
        token = base64.b64encode(f"API_KEY:{self.api_key}".encode()).decode()
        return f"Basic {token}"


# ── HTTP (stdlib only) ────────────────────────────────────────────────────────────────

def _get(path: str, params: dict, creds: Credentials, timeout: int = 30):
    """GET a JSON endpoint under BASE_URL with Basic auth. Raises IntervalsError on any
    HTTP or network failure, with the API key kept out of the message."""
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": creds._auth_header(),
            "Accept": "application/json",
            # intervals.icu is behind Cloudflare, which blocks the default
            # "Python-urllib/x.y" agent as a bot (Cloudflare error 1010). A normal
            # User-Agent gets the request past the edge so auth can actually be evaluated.
            "User-Agent": _USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        hint = " (check the API key and athlete id)" if e.code in (401, 403) else ""
        raise IntervalsError(f"intervals.icu returned {e.code} for {path}{hint}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise IntervalsError(f"could not reach intervals.icu: {e}") from None


def fetch_activities(creds: Credentials, oldest: str, newest: str) -> list[dict]:
    """Raw activity objects for the inclusive date range [oldest, newest] (ISO dates)."""
    return _get(f"/athlete/{creds.athlete_id}/activities",
                {"oldest": oldest, "newest": newest}, creds) or []


# ── Mapping: an intervals.icu activity → the core's `session` dict ─────────────────────

def _zone_dist(zone_times: list | None) -> dict:
    """HR zone seconds → fractions keyed Z1..Zn. Empty when there is no zone data (then
    derive_signals simply returns None for stimulus_quality — a handled case)."""
    if not zone_times:
        return {}
    total = sum(t or 0 for t in zone_times)
    if not total:
        return {}
    return {f"Z{i + 1}": round((t or 0) / total, 3) for i, t in enumerate(zone_times) if t}


def _classify_run(zone_dist: dict, distance_km: float | None) -> str:
    """Best-effort taxonomy type from where the effort sat. intervals.icu does not label
    runs as easy/tempo/threshold/vo2/long/jog, so this maps by dominant intensity (with
    distance breaking easy vs long). A documented heuristic, replaceable by a richer
    classifier — it only needs to be good enough for the signals to reason."""
    z = zone_dist or {}
    high = z.get("Z5", 0) + z.get("Z6", 0) + z.get("Z7", 0)
    if high >= 0.15:
        return "vo2"
    if z.get("Z4", 0) >= 0.20:
        return "threshold"
    if z.get("Z3", 0) >= 0.30:
        return "tempo"
    if distance_km and distance_km >= 21:
        return "long"
    return "easy"


def activity_to_session(raw: dict, plan_targets: dict | None = None) -> dict:
    """Map one intervals.icu activity to the `session` contract in derive_signals.py.

    Subjective feedback (RPE breath/legs, Achilles, feel) is deliberately left empty: it
    is the athlete's input, supplied by the skill, not something the API holds.
    """
    dist_m = raw.get("distance") or 0
    moving = raw.get("moving_time") or raw.get("elapsed_time") or 0
    zone_dist = _zone_dist(raw.get("icu_hr_zone_times") or raw.get("icu_zone_times"))
    dist_km = round(dist_m / 1000, 2) if dist_m else None
    avg_pace = round(moving / dist_m * 1000) if dist_m and moving else None

    return {
        "source": "intervals_icu",
        "source_id": raw.get("id"),
        "date": (raw.get("start_date_local") or "")[:10],
        "name": raw.get("name"),
        "activity_type": _classify_run(zone_dist, dist_km),
        "distance_km": dist_km,
        "duration_sec": moving or None,
        "avg_pace_sec_per_km": avg_pace,
        "avg_hr": raw.get("average_heartrate"),
        "max_hr": raw.get("max_heartrate"),
        "zone_dist": zone_dist,
        "laps": [],          # per-rep splits land in Step 2b alongside plan targets
        "feedback": {},      # subjective — supplied by the athlete, not the API
        "plan_targets": plan_targets,
    }


def _is_run(raw: dict) -> bool:
    return (raw.get("type") or "") in RUN_TYPES


# ── Recent-week context: the trend that turns a number into a read ─────────────────────

def summarise_weeks(sessions: list[dict], weeks: int = 4,
                    today: date | None = None) -> list[dict]:
    """Bucket mapped sessions into the last `weeks` ISO weeks (newest first) as the
    `recent_weeks` context interpret() expects. Volume and counts only — what the trend
    MEANS is the model's job, not this plumbing's."""
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    buckets: dict[int, list[dict]] = {i: [] for i in range(weeks)}
    for s in sessions:
        try:
            d = date.fromisoformat(s.get("date") or "")
        except ValueError:
            continue
        i = (this_monday - (d - timedelta(days=d.weekday()))).days // 7
        if 0 <= i < weeks:
            buckets[i].append(s)

    out = []
    for i in range(weeks):
        wk = buckets[i]
        out.append({
            "label": "this week" if i == 0 else f"week -{i}",
            "volume_km": round(sum(s.get("distance_km") or 0 for s in wk), 1),
            "sessions": len(wk),
        })
    return out


def fetch_recent(creds: Credentials, weeks: int = 4,
                 today: date | None = None) -> tuple[list[dict], list[dict]]:
    """The convenience the skill calls: pull the last `weeks` weeks of runs and return
    (sessions newest-first, recent_weeks). One round trip; runs only."""
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    oldest = (this_monday - timedelta(weeks=weeks - 1)).isoformat()
    newest = today.isoformat()

    raw = fetch_activities(creds, oldest, newest)
    sessions = [activity_to_session(a) for a in raw if _is_run(a)]
    sessions.sort(key=lambda s: s.get("date") or "", reverse=True)
    return sessions, summarise_weeks(sessions, weeks=weeks, today=today)


# ── Per-rep laps: the work splits a quality read is built on ───────────────────────────
#
# The basic activities response is a summary — no splits. The per-activity intervals
# endpoint carries them, so fetching laps is a second, on-demand call (you don't want one
# per run when summarising weeks; you want it for the session being read closely).
#
# intervals.icu labels each interval WORK / RECOVERY / WARMUP / COOLDOWN — faithful here,
# so derive_signals can count work reps and read the fade. Caveat: on an auto-detected
# (unstructured) run intervals.icu marks every segment WORK; the typing is meaningful for
# structured / planned sessions, which are the ones a quality read cares about.

def _pace_from_speed(speed: float | None) -> int | None:
    """m/s → seconds/km."""
    return round(1000 / speed) if speed else None


def interval_to_lap(iv: dict) -> dict:
    """One intervals.icu interval → the lap shape derive_signals reads."""
    return {
        "lap_type": (iv.get("type") or "work").lower(),
        "distance_m": round(iv["distance"]) if iv.get("distance") else None,
        "duration_sec": iv.get("moving_time") or iv.get("elapsed_time"),
        "avg_hr": iv.get("average_heartrate"),
        "max_hr": iv.get("max_heartrate"),
        "avg_pace_sec_per_km": _pace_from_speed(iv.get("average_speed")),
        "zone": iv.get("zone"),
    }


def intervals_to_laps(raw: dict) -> list[dict]:
    """Map an /activity/{id}/intervals response to a list of laps."""
    return [interval_to_lap(iv) for iv in (raw.get("icu_intervals") or [])]


def fetch_activity_intervals(creds: Credentials, activity_id: str) -> dict:
    """Raw intervals (laps) for one activity."""
    return _get(f"/activity/{activity_id}/intervals", {}, creds) or {}


def attach_laps(creds: Credentials, session: dict) -> dict:
    """Fetch and attach the per-rep laps for one mapped session (by its source_id).
    Mutates and returns the session."""
    sid = session.get("source_id")
    if sid:
        session["laps"] = intervals_to_laps(fetch_activity_intervals(creds, sid))
    return session


def load_session_detail(creds: Credentials, session: dict) -> dict:
    """Everything the close read of one session needs: its laps, then the derived
    metrics (pacing consistency, decoupling) computed from them and folded back in so
    derive_signals picks them up. The one call the skill makes for the focal session."""
    from ingest.metrics import enrich_session  # local import: metrics is the consumer

    attach_laps(creds, session)
    return enrich_session(session)


# ── demo (network-gated) ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        creds = Credentials.from_env()
    except IntervalsError as exc:
        print(f"  {exc}")
        print("  Set INTERVALS_ATHLETE_ID and INTERVALS_API_KEY, then re-run.")
        print("  (Settings → Developer on intervals.icu generates the key.)")
        raise SystemExit(0)

    print(f"Fetching the last 4 weeks for athlete {creds.athlete_id}…")
    sessions, recent = fetch_recent(creds, weeks=4)
    print(f"\n{len(sessions)} run(s):")
    for s in sessions[:12]:
        print(f"  {s['date']}  {s['activity_type']:9} {s['distance_km']}km  "
              f"HR {s['avg_hr'] or '-'}")
    print("\nrecent weeks:")
    for w in recent:
        print(f"  {w['label']}: {w['volume_km']}km, {w['sessions']} sessions")
    print()
