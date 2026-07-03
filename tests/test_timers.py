"""Unit tests for the server-side timer registry (FoodAssistant-y0vh).

The countdown formula is a pure helper, so state is tested by passing explicit
deadline/now values, never by sleeping.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "service"))

from app.services import timers  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    timers.clear_all()
    yield
    timers.clear_all()


# --- pure helper ---------------------------------------------------------


def test_remaining_before_deadline():
    remaining, expired = timers.remaining_from_deadline(deadline=100.0, now=70.0)
    assert remaining == 30.0
    assert expired is False


def test_remaining_at_deadline_is_expired():
    remaining, expired = timers.remaining_from_deadline(deadline=100.0, now=100.0)
    assert remaining == 0.0
    assert expired is True


def test_remaining_past_deadline_clamps_to_zero():
    remaining, expired = timers.remaining_from_deadline(deadline=100.0, now=130.0)
    assert remaining == 0.0          # never negative
    assert expired is True


# --- registry ------------------------------------------------------------


def test_create_timer_shape_and_running():
    t = timers.create_timer("Pasta", 600)
    assert isinstance(t["id"], int)
    assert t["label"] == "Pasta"
    assert t["total_seconds"] == 600
    assert t["running"] is True
    assert t["expired"] is False
    assert 0 < t["remaining_seconds"] <= 600
    # Shareable absolute deadline is present for off-machine surfaces.
    assert t["deadline_epoch"] > t["created_epoch"]


def test_create_timer_blank_label_gets_default():
    t = timers.create_timer("  ", 5)
    assert t["label"].startswith("Timer ")


def test_create_timer_rejects_non_positive():
    with pytest.raises(ValueError):
        timers.create_timer("x", 0)
    with pytest.raises(ValueError):
        timers.create_timer("x", -10)


def test_ids_increment_under_lock():
    a = timers.create_timer("a", 5)
    b = timers.create_timer("b", 5)
    assert b["id"] == a["id"] + 1


def test_list_timers_sorted_oldest_first():
    a = timers.create_timer("a", 5)
    b = timers.create_timer("b", 5)
    listed = timers.list_timers()
    assert [t["id"] for t in listed] == [a["id"], b["id"]]
    assert a["id"] < b["id"]


def test_get_timer_found_and_missing():
    t = timers.create_timer("a", 5)
    assert timers.get_timer(t["id"])["label"] == "a"
    assert timers.get_timer(999) is None


def test_cancel_timer():
    t = timers.create_timer("a", 5)
    assert timers.cancel_timer(t["id"]) is True
    assert timers.get_timer(t["id"]) is None
    assert timers.cancel_timer(t["id"]) is False   # already gone


def test_deadline_epoch_is_satellite_shareable():
    # A surface on another machine reproduces remaining from the epoch deadline
    # and its own time.time(), using the same pure helper.
    t = timers.create_timer("Roast", 1000)
    fake_now = t["deadline_epoch"] - 250.0
    remaining, expired = timers.remaining_from_deadline(t["deadline_epoch"], fake_now)
    assert remaining == 250.0
    assert expired is False


# --- extend (FoodAssistant-xlb3) ------------------------------------------


def test_extend_timer_moves_both_deadlines_and_total():
    t = timers.create_timer("Pasta", 60)
    out = timers.extend_timer(t["id"], 60)
    assert out is not None
    # The shared epoch deadline moved by the extension...
    assert out["deadline_epoch"] == pytest.approx(t["deadline_epoch"] + 60, abs=0.5)
    # ...and so did our own monotonic countdown (remaining grew past the
    # original 60s budget), so both clocks agree.
    assert out["remaining_seconds"] > 60
    assert out["total_seconds"] == 120
    assert out["running"] is True and out["expired"] is False
    # The registry itself was updated, not just the returned snapshot.
    assert timers.get_timer(t["id"])["deadline_epoch"] == out["deadline_epoch"]


def test_extend_timer_missing_returns_none():
    assert timers.extend_timer(999, 60) is None


def test_extend_timer_expired_returns_none():
    import time as _time
    t = timers.create_timer("Eggs", 5)
    # Force expiry without sleeping: move the monotonic deadline into the past.
    with timers._lock:
        timers._timers[t["id"]].deadline_monotonic = _time.monotonic() - 1
    assert timers.extend_timer(t["id"], 60) is None
    # An expired timer stays listed (it is an alert), it just cannot grow.
    assert timers.get_timer(t["id"])["expired"] is True


def test_extend_timer_rejects_non_positive_and_garbage():
    t = timers.create_timer("Rice", 60)
    with pytest.raises(ValueError):
        timers.extend_timer(t["id"], 0)
    with pytest.raises(ValueError):
        timers.extend_timer(t["id"], -30)
    with pytest.raises(ValueError):
        timers.extend_timer(t["id"], "soon")
