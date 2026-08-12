"""Core functionality that should to into the top-level namespace."""

import csv
import logging
import os
import threading
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import ruamel.yaml
import yaml

try:
    # libyaml-backed loader, several times faster than the pure-Python one.
    from yaml import CSafeLoader as _YamlLoader
except ImportError:  # pragma: no cover - depends on the libyaml build
    from yaml import SafeLoader as _YamlLoader

# NOTE: logging handlers/formatters are configured centrally in app.main.
# Do not call logging.basicConfig() here: app.core is imported before
# app.main configures logging, and basicConfig is a no-op once the root
# logger has a handler, which would silently disable JSON logging (and
# break every Loki `| json` query / Alloy stage.json extraction).
logger = logging.getLogger(__name__)


class _ThreadLocalYAML(threading.local):
    """Holds one configured ruamel ``YAML`` per thread.

    A ``YAML`` instance carries scanner, parser and composer state for the
    duration of a load, so two threads sharing one interleave their parses
    and corrupt each other. Sync endpoints run in a threadpool, so a single
    shared instance here means concurrent requests reading the same file get
    bogus ``ParserError``/``ComposerError`` at random lines, an ``IndexError``
    from the scanner, or an internal ``AttributeError`` that escapes the YAML
    error handling and 500s the request.
    """

    def __init__(self) -> None:
        self.yaml = ruamel.yaml.YAML()
        self.yaml.indent(mapping=2, sequence=4, offset=2)
        self.yaml.preserve_quotes = True
        self.yaml.width = 70


_yaml_local = _ThreadLocalYAML()


class _ThreadLocalYAMLProxy:
    """Forwards to the calling thread's ``YAML``.

    Keeps ``ryaml`` usable as the module-level object it has always been, so
    no call site has to know about any of this.
    """

    def __getattr__(self, name: str) -> Any:
        return getattr(_yaml_local.yaml, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(_yaml_local.yaml, name, value)


ryaml = _ThreadLocalYAMLProxy()


def load_yaml_fast(data: str | bytes) -> Any:
    """Parse YAML we only read from and never write back.

    ``ryaml`` is a ruamel round-trip parser: it preserves comments, quoting
    and key order so a file can be re-serialized faithfully, and pays for
    that in speed. Anything we merely inspect (dvc.lock, dvc.yaml) should
    come through here instead. On a 1.4 MB dvc.lock that is ~0.4s against
    ~3.2s, which is the difference between a page load and a page wait.
    """
    return yaml.load(data, Loader=_YamlLoader)


CATEGORIES_SINGULAR_TO_PLURAL = {
    "figure": "figures",
    "dataset": "datasets",
    "publication": "publications",
    "notebook": "notebooks",
    "environment": "environments",
    "references": "references",
    "software": "software",
}
CATEGORIES_PLURAL_TO_SINGULAR = {
    v: k for k, v in CATEGORIES_SINGULAR_TO_PLURAL.items()
}
# Names no account may take, since they'd collide with app routes or
# product vocabulary at the URL root
INVALID_ACCOUNT_NAMES = [
    "actions",
    "admin",
    "analytics",
    "anonymous",
    # OAuth callbacks live under /auth/{provider} so only this name is taken
    "auth",
    "browse",
    "calcs",
    "calculations",
    "checks",
    "cloud",
    "clouds",
    "create",
    "data",
    "datasets",
    "delete",
    "email",
    "environments",
    "envs",
    "explore",
    "figs",
    "figures",
    "git",
    "github",
    "history",
    "hub",
    "hubs",
    "latex",
    "login",
    "new",
    "notifications",
    "organizations",
    "orgs",
    "pipeline",
    "pipelines",
    "posters",
    "presentations",
    "projects",
    "publications",
    "pubs",
    "references",
    "register",
    "replicate",
    "replications",
    "repro",
    "repros",
    "reproduce",
    "reproductions",
    "research",
    "results",
    "science",
    "search",
    "settings",
    "signup",
    "software",
    "sw",
    "tasks",
    "teams",
    "templates",
    "update",
    "user",
    "users",
    "workflows",
]

# Names reserved for organizations, so a user can't claim the product's
# own name as a personal account while hub operators can still create
# an org under it
ORG_ONLY_ACCOUNT_NAMES = ["calkit"]


def utcnow() -> datetime:
    """Return a timezone-naive timestamp for now in UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


def params_from_url(url: str) -> dict:
    parsed_url = urlparse(url)
    return parse_qs(parsed_url.query)


def read_last_line_from_file(fpath: str) -> str:
    with open(fpath, "rb") as file:
        file.seek(-2, os.SEEK_END)
        while file.read(1) != b"\n":
            file.seek(-2, os.SEEK_CUR)
        last_line = file.readline().decode()
    return last_line


def read_last_line_from_csv(fpath: str) -> list:
    last_line = read_last_line_from_file(fpath)
    row = csv.reader([last_line])
    return list(row)[0]
