"""Tests for the ``latex`` module."""

from __future__ import annotations

from unittest import mock

import calkit.latex


def test_backend_resolution() -> None:
    # With nothing declared, the order prefers a TeX that's already on the
    # machine and leaves Docker last, since it's the only one needing a
    # daemon
    assert calkit.latex.get_backend_order({}, {}) == [
        "system",
        "tectonic",
        "tinytex",
        "docker",
    ]
    # A project that keeps diffs can't use Tectonic at all: latexdiff is a
    # Perl script Tectonic ships neither of, so the document wouldn't
    # typeset differently, it would fail to build
    diffing = {
        "pipeline": {
            "stages": {
                "paper": {"kind": "latex", "diffs": ["HEAD~1"]},
                "other": {"kind": "python-script"},
            }
        }
    }
    assert calkit.latex.get_backend_order({}, diffing) == [
        "system",
        "tinytex",
        "docker",
    ]
    assert calkit.latex.project_keeps_diffs(diffing)
    # A latex stage without diffs, and a non-latex stage carrying the key,
    # are both just a project that doesn't diff
    for stages in [
        {"paper": {"kind": "latex"}},
        {"paper": {"kind": "latex", "diffs": []}},
        {"x": {"kind": "python-script", "diffs": ["HEAD~1"]}},
    ]:
        assert not calkit.latex.project_keeps_diffs(
            {"pipeline": {"stages": stages}}
        )
    assert not calkit.latex.project_keeps_diffs({})
    # Naming backends is how a project says it has an opinion, so its list
    # is used as given---including one that can't diff
    assert calkit.latex.get_backend_order(
        {"backends": ["tectonic", "docker"]}, diffing
    ) == ["tectonic", "docker"]
    # Capability is a property of the backend, not of what's installed
    assert not calkit.latex.backend_can_diff("tectonic")
    for backend in ["system", "tinytex", "docker"]:
        assert calkit.latex.backend_can_diff(backend)


def test_backend_availability() -> None:
    # A version is read out of whatever prose the tool prints
    with mock.patch("shutil.which", return_value="/usr/bin/tectonic"):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(stdout="Tectonic 0.15.0\n")
            assert calkit.latex.get_backend_version("tectonic") == "0.15.0"
    # A tool that isn't there has no version, and isn't available
    with mock.patch("shutil.which", return_value=None):
        assert calkit.latex.get_backend_version("tectonic") is None
        assert not calkit.latex.backend_is_available("tectonic")
    # An unknown backend is simply absent rather than an error
    assert calkit.latex.get_backend_version("mactex") is None
    # Docker being installed says nothing about the daemon being up, which
    # is the failure people actually hit, so it's checked for real
    with mock.patch("calkit.latex.get_backend_version", return_value="29.7.2"):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            assert calkit.latex.backend_is_available("docker")
            run.return_value = mock.Mock(returncode=1)
            assert not calkit.latex.backend_is_available("docker")

    # TinyTeX without latexmk is a TeX Live that can't build
    def only_tlmgr(backend: str) -> str | None:
        return "2026" if backend == "tinytex" else None

    with mock.patch(
        "calkit.latex.get_backend_version", side_effect=only_tlmgr
    ):
        assert not calkit.latex.backend_is_available("tinytex")
