"""Deprecated alias for :mod:`calkit.hub`.

The hub API client moved when "cloud" was retired as vocabulary; a hub is
any Calkit instance, whether hosted or self-run. Importing
``calkit.cloud`` returns the ``calkit.hub`` module itself, so existing
imports and monkeypatches keep working.
"""

import sys

from calkit import hub

sys.modules[__name__] = hub
