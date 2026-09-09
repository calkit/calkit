"""Tests for the warm queue."""

import app.tasks


class _Queue:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def enqueue(self, func, *args, **kwargs):
        self.calls.append({"func": func, "args": args, **kwargs})


def test_enqueue_warm_is_optional_and_coalesces(monkeypatch):
    # No queue configured is a supported way to run: nothing is queued, and
    # the caller is told so rather than being handed an error
    monkeypatch.setattr(app.tasks, "get_queue", lambda: None)
    assert app.tasks.enqueue_warm("Owner", "Proj") is False

    queue = _Queue()
    monkeypatch.setattr(app.tasks, "get_queue", lambda: queue)
    assert app.tasks.enqueue_warm("Owner", "Proj") is True
    call = queue.calls[0]
    assert call["func"] == "app.warm.warm_project"
    assert call["args"] == ("Owner", "Proj", False)
    # A push that moved data rather than code runs even at a warm commit
    app.tasks.enqueue_warm("Owner", "Proj", force=True)
    assert queue.calls[1]["args"] == ("Owner", "Proj", True)
    # The id is the project, so a burst of pushes leaves one pending warm
    # rather than one per push, and it survives RQ's rules for an id
    assert call["job_id"] == "warm-owner-proj"
    assert set(call["job_id"]) <= set("abcdefghijklmnopqrstuvwxyz0123456789_-")
    # A slug with characters RQ won't take still produces a usable id
    app.tasks.enqueue_warm("My.Org", "a/b c")
    assert queue.calls[2]["job_id"] == "warm-my-org-a-b-c"

    # A queue that refuses the job doesn't take the request down with it:
    # warming is an optimization
    class _Broken:
        def enqueue(self, *a, **k):
            raise ConnectionError("queue is down")

    monkeypatch.setattr(app.tasks, "get_queue", lambda: _Broken())
    assert app.tasks.enqueue_warm("Owner", "Proj") is False


def test_startup_warms_are_bounded(monkeypatch):
    # Zero means don't, and it's checked before any database work
    monkeypatch.setattr(
        app.tasks,
        "enqueue_warm",
        lambda *a: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    assert app.tasks.enqueue_startup_warms(0) == 0
