"""Tests for contribution request records."""

from datetime import datetime, timezone
from pathlib import Path

import calkit.contrib
from calkit.models.contrib import (
    ContribRequestRecipient,
    ContribRequestRecord,
    ContribRequestTarget,
    ContribResponseRecord,
)


def test_record_round_trip(tmp_path: Path) -> None:
    now = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    record = ContribRequestRecord(
        id="abc123",
        title="Please review",
        target=ContribRequestTarget(kind="publication", path="paper/main.pdf"),
        document="paper/main-for-review.docx",
        to=ContribRequestRecipient(name="P. I.", email="pi@example.org"),
        created=now,
        created_by="lead@example.org",
        rev="deadbeef",
    )
    rel = calkit.contrib.save(record, wdir=str(tmp_path))
    assert rel == ".calkit/requests/abc123.yaml"
    text = (tmp_path / rel).read_text()
    assert "status: open" in text and "responses: []" in text
    back = calkit.contrib.load("abc123", wdir=str(tmp_path))
    assert back == record
    back.responses.append(
        ContribResponseRecord(path="reviews/x.docx", received=now)
    )
    back.status = "closed"
    calkit.contrib.save(back, wdir=str(tmp_path))
    records = calkit.contrib.list_records(wdir=str(tmp_path))
    assert len(records) == 1
    assert records[0].status == "closed"
    assert records[0].responses[0].path == "reviews/x.docx"
    assert calkit.contrib.list_records(wdir=str(tmp_path / "nope")) == []
