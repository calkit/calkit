from types import SimpleNamespace
from unittest.mock import patch

import yaml


def test_copy_template_dvc_objects(tmp_path) -> None:
    from app.api.routes.projects.core import _copy_template_dvc_objects

    lock = {
        "stages": {
            "analyze": {
                "outs": [
                    {"path": "figures/x.png", "md5": "aa11"},
                    {"path": "data/raw", "md5": "bb22.dir"},
                ]
            }
        }
    }
    (tmp_path / "dvc.lock").write_text(yaml.safe_dump(lock))
    template = SimpleNamespace(owner_account_name="calkit", name="example")
    project = SimpleNamespace(owner_account_name="me", name="mine")
    # What expand_dvc_lock_outs would find: the file, the directory listing
    # object, and a child of the directory
    outs = {
        "figures/x.png": {"path": "figures/x.png", "md5": "aa11"},
        "data/raw": {"path": "data/raw", "md5": "bb22.dir"},
        "data/raw/a.csv": {"path": "data/raw/a.csv", "md5": "cc33"},
        "results/summary.json": {"path": "results/summary.json"},
    }
    existing = {"calkit/example/aa11", "calkit/example/bb22.dir"}
    copied: list[tuple[str, str]] = []

    class FakeFS:
        def exists(self, path):
            return path in existing

        def copy(self, src, dst):
            copied.append((src, dst))
            existing.add(dst)

    def fake_fpath(owner_name, project_name, idx, md5, **kwargs):
        return f"{owner_name}/{project_name}/{idx}{md5}"

    with (
        patch(
            "app.api.routes.projects.core.get_object_fs",
            return_value=FakeFS(),
        ),
        patch(
            "app.api.routes.projects.core.expand_dvc_lock_outs",
            return_value=outs,
        ),
        patch(
            "app.api.routes.projects.core.make_data_fpath",
            side_effect=fake_fpath,
        ),
    ):
        n = _copy_template_dvc_objects(
            repo_dir=str(tmp_path), template_project=template, project=project
        )
    # Only objects the template actually has get copied; a child missing
    # from storage and an entry with no md5 are skipped, not errors
    assert n == 2
    assert sorted(copied) == [
        ("calkit/example/aa11", "me/mine/aa11"),
        ("calkit/example/bb22.dir", "me/mine/bb22.dir"),
    ]
    # A second run copies nothing, since the destinations now exist
    with (
        patch(
            "app.api.routes.projects.core.get_object_fs",
            return_value=FakeFS(),
        ),
        patch(
            "app.api.routes.projects.core.expand_dvc_lock_outs",
            return_value=outs,
        ),
        patch(
            "app.api.routes.projects.core.make_data_fpath",
            side_effect=fake_fpath,
        ),
    ):
        assert (
            _copy_template_dvc_objects(
                repo_dir=str(tmp_path),
                template_project=template,
                project=project,
            )
            == 0
        )
    # No lock file, nothing to do
    assert (
        _copy_template_dvc_objects(
            repo_dir=str(tmp_path / "nope"),
            template_project=template,
            project=project,
        )
        == 0
    )
