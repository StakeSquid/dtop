"""Tests for Textual log normalization (worker guards + subprocess behavior)."""
import asyncio
import types
from pathlib import Path

import pytest

from dtop.views import textual_log_view as tlv


REPO_ROOT = Path(__file__).resolve().parent.parent
NORMALIZE_SCRIPT = REPO_ROOT / "dtop" / "utils" / "normalize_logs.py"


def _fake_screen_for_worker():
    applied: list = []

    def _apply(pl):
        applied.append(list(pl))

    screen = types.SimpleNamespace(
        _normalize_latest_id=1,
        raw_logs=["a"],
        normalize_script=str(NORMALIZE_SCRIPT),
        app=types.SimpleNamespace(notify=lambda *a, **k: None),
        _apply_normalized_and_render=_apply,
    )
    return screen, applied


def test_normalize_subprocess_missing_script():
    lines = ["hello"]
    out, warn = tlv._normalize_logs_subprocess(lines, "/nonexistent/normalize_logs.py")
    assert out == lines
    assert warn is not None
    assert "not found" in warn.lower()


def test_normalize_subprocess_json_line():
    if not NORMALIZE_SCRIPT.is_file():
        pytest.skip("normalize_logs.py not in tree")
    raw = (
        '{"severity":"INFO","timestamp":"2024-01-15T12:00:00.000000000Z","message":"ping"}'
    )
    out, warn = tlv._normalize_logs_subprocess([raw], str(NORMALIZE_SCRIPT))
    assert warn is None
    assert len(out) == 1
    assert "INFO" in out[0]
    assert "ping" in out[0]


def test_normalize_subprocess_json_scalar_line():
    """JSON numbers/strings used to crash main() with TypeError on 'in obj'."""
    if not NORMALIZE_SCRIPT.is_file():
        pytest.skip("normalize_logs.py not in tree")
    out, warn = tlv._normalize_logs_subprocess(["42", '"hello"'], str(NORMALIZE_SCRIPT))
    assert warn is None
    assert out == ["42", '"hello"']


def test_normalize_worker_applies_when_id_matches(monkeypatch):
    screen, applied = _fake_screen_for_worker()

    async def fake_to_thread(func, *args, **kwargs):
        return (["NORMALIZED"], None)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    async def _run():
        await tlv.LogViewScreen._normalize_logs_worker(screen, 1)

    asyncio.run(_run())
    assert applied == [["NORMALIZED"]]


def test_normalize_worker_stale_after_subprocess(monkeypatch):
    """Simulates a refresh bumping _normalize_latest_id while normalize is in flight."""
    screen, applied = _fake_screen_for_worker()
    screen.raw_logs = ["x"]

    async def fake_to_thread(func, *args, **kwargs):
        screen._normalize_latest_id = 2
        return (["SHOULD_NOT_APPLY"], None)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    async def _run():
        await tlv.LogViewScreen._normalize_logs_worker(screen, 1)

    asyncio.run(_run())
    assert applied == []


def test_process_and_display_logs_schedules_exclusive_worker():
    calls: list = []

    def fake_run_worker(work, **kwargs):
        calls.append(kwargs)
        return None

    class _LogWidget:
        auto_scroll = True

        def clear(self):
            pass

        def write(self, *a, **k):
            pass

    screen = types.SimpleNamespace(
        normalize_enabled=True,
        _normalize_latest_id=0,
        raw_logs=["line"],
        is_following=True,
        _is_view_at_bottom=lambda: True,
        query_one=lambda *_a, **_k: _LogWidget(),
        run_worker=fake_run_worker,
    )

    tlv.LogViewScreen.process_and_display_logs(screen)
    assert screen._normalize_latest_id == 1
    assert len(calls) == 1
    assert calls[0].get("exclusive") is True
    assert calls[0].get("group") == "log_normalize"
    assert calls[0].get("thread") is False
    assert calls[0].get("exit_on_error") is False
