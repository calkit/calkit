from typing import TYPE_CHECKING

from .core import *  # noqa: F403

# Loaded when used, since most commands don't need it, as with calkit's own
# submodules
if TYPE_CHECKING:
    from . import link  # noqa: F401
