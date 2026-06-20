"""Tests for the eval harness — the judge's scoring logic and the runner's row assembly.

The model (and the judge model) are stubbed throughout; no `claude` process is spawned.
What's pinned here is the deterministic glue: how a judge result becomes pass/fail, that
the rubric reaches the grader, and that the runner builds the right row in each outcome.
"""

from evals import judge, run
from evals.golden_sessions import GOLDENS_BY_NAME

GOLDEN = GOLDENS_BY_NAME["faded_vo2"]


def _verdict(all_pass=True, overall=5):
    crit = {k: {"pass": all_pass, "note": ""} for k, _ in judge.CRITERIA}
    return {"criteria": crit, "overall": overall, "verdict": "ok"}


# ── judge.passed ──────────────────────────────────────────────────────────────────────

def test_passed_requires_every_criterion_and_the_overall_bar():
    assert judge.passed(_verdict(all_pass=True, overall=4)) is True
    assert judge.passed(_verdict(all_pass=True, overall=5)) is True


def test_passed_fails_if_any_criterion_fails():
    v = _verdict(all_pass=True, overall=5)
    next(iter(v["criteria"].values()))["pass"] = False
    assert judge.passed(v) is False


def test_passed_fails_below_threshold():
    assert judge.passed(_verdict(all_pass=True, overall=3)) is False


def test_passed_handles_missing_or_bad_fields():
    assert judge.passed({}) is False
    assert judge.passed({"criteria": {}, "overall": 5}) is False        # no criteria
    assert judge.passed({"criteria": {"a": {"pass": True}}, "overall": "x"}) is False


# ── judge.build_prompt / parsing ──────────────────────────────────────────────────────

def test_build_prompt_carries_the_rubric_and_the_read():
    prompt = judge.build_prompt(GOLDEN, "the read text here")
    assert GOLDEN["isolates"] in prompt
    assert GOLDEN["must_address"][0] in prompt
    assert GOLDEN["must_not"][0] in prompt
    assert "the read text here" in prompt
    for key, _ in judge.CRITERIA:
        assert key in prompt


def test_parse_json_tolerates_non_objects():
    assert judge._parse_json('{"a": 1}') == {"a": 1}
    assert judge._parse_json("[1, 2]") is None
    assert judge._parse_json("not json") is None


def test_judge_brief_none_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(judge, "call_claude", lambda *a, **k: None)
    assert judge.judge_brief(GOLDEN, "x") is None


def test_judge_brief_none_when_criteria_missing(monkeypatch):
    monkeypatch.setattr(judge, "call_claude", lambda *a, **k: '{"overall": 5}')
    assert judge.judge_brief(GOLDEN, "x") is None


def test_judge_brief_returns_parsed_dict(monkeypatch):
    monkeypatch.setattr(judge, "call_claude",
                        lambda *a, **k: '{"criteria": {"x": {"pass": true}}, "overall": 4}')
    out = judge.judge_brief(GOLDEN, "x")
    assert out and out["overall"] == 4


# ── run.evaluate_one ──────────────────────────────────────────────────────────────────

def test_evaluate_one_error_row_when_no_read(monkeypatch):
    monkeypatch.setattr(run, "interpret", lambda *a, **k: None)
    row = run.evaluate_one(GOLDEN, use_judge=False)
    assert "error" in row and row["name"] == "faded_vo2"


def test_evaluate_one_scores_voice_and_judge(monkeypatch):
    monkeypatch.setattr(run, "interpret", lambda *a, **k: "Your legs tapped out first.")
    monkeypatch.setattr(run.judge_mod, "judge_brief", lambda g, b: _verdict(True, 5))
    row = run.evaluate_one(GOLDEN, use_judge=True)
    assert row["voice_clean"] is True
    assert row["judge_pass"] is True


def test_evaluate_one_flags_voice_leak(monkeypatch):
    monkeypatch.setattr(run, "interpret", lambda *a, **k: "You spent 38% in Z5.")
    row = run.evaluate_one(GOLDEN, use_judge=False)
    assert row["voice_clean"] is False
    assert row["violations"]  # non-empty


def test_evaluate_one_judge_error_row(monkeypatch):
    monkeypatch.setattr(run, "interpret", lambda *a, **k: "A clean coach read.")
    monkeypatch.setattr(run.judge_mod, "judge_brief", lambda g, b: None)
    row = run.evaluate_one(GOLDEN, use_judge=True)
    assert row["judge_error"]
    assert "judge_pass" not in row


# ── run.main (smoke, fully stubbed) ───────────────────────────────────────────────────

def test_main_no_judge_returns_zero_on_clean(monkeypatch):
    monkeypatch.setattr(run, "interpret", lambda *a, **k: "A clean coach read, no leaks.")
    code = run.main(["--no-judge", "--no-save", "--only", "faded_vo2"])
    assert code == 0


def test_main_returns_one_on_voice_leak(monkeypatch):
    monkeypatch.setattr(run, "interpret", lambda *a, **k: "38% in Z5, clear decoupling.")
    code = run.main(["--no-judge", "--no-save", "--only", "faded_vo2"])
    assert code == 1
