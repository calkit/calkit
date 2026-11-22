"""Tests for ``app.storage``."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app import storage


def test_post_hf_bucket_batch() -> None:
    target = storage.ProjectStorage(
        backend="hf",
        fs=None,
        data_prefix="buckets/ns/bkt",
        resource=SimpleNamespace(bucket="ns/bkt"),  # type: ignore[arg-type]
        token="hf-token",
    )
    ops = [{"type": "addFile", "path": "a", "xetHash": "x"}]

    def respond(status_code: int, body: dict) -> requests.Response:
        resp = requests.Response()
        resp.status_code = status_code
        resp._content = json.dumps(body).encode()
        resp.url = "https://huggingface.co/api/buckets/ns/bkt/batch"
        return resp

    # HF lists the operations that failed in a 200 if only some did, or a 422
    # if all did
    failed = {"failed": [{"path": "a", "error": "Unknown xet hash"}]}
    for status_code in (200, 422):
        with (
            patch.object(
                requests, "post", return_value=respond(status_code, failed)
            ) as post,
            pytest.raises(storage.HfBucketBatchError) as e,
        ):
            storage.post_hf_bucket_batch(target, ops)
        assert e.value.failures == failed["failed"]
        assert "Unknown xet hash" in str(e.value)
    assert post.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer hf-token"
    )
    with patch.object(requests, "post", return_value=respond(200, {})):
        storage.post_hf_bucket_batch(target, ops)
    with (
        patch.object(requests, "post", return_value=respond(500, {})),
        pytest.raises(requests.HTTPError),
    ):
        storage.post_hf_bucket_batch(target, ops)
