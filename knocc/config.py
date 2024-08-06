"""Configuration."""

import os

import yaml


def read() -> dict:
    """Read the config."""
    fpath = os.path.join(
        os.path.expanduser("~"), "." + __package__, "config.yaml"
    )
    with open(fpath) as f:
        return yaml.load(f, Loader=yaml.SafeLoader)
