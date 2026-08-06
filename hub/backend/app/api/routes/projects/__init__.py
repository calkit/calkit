"""Projects related routes."""

from fastapi import APIRouter

from .core import router as core_router
from .dvc import router as dvc_router
from .fs import router as fs_router

# Re-export all public names (including endpoint functions) from submodules
# for automated frontend client generation
from .core import *  # noqa: F401,F403
from .dvc import *  # noqa: F401,F403
from .fs import *  # noqa: F401,F403

router = APIRouter()
router.include_router(core_router)
router.include_router(dvc_router)
router.include_router(fs_router)
