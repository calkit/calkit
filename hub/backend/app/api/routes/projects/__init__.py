"""Projects related routes."""

from fastapi import APIRouter

# Re-export all public names (including endpoint functions) from submodules
# for automated frontend client generation
from .activity import *  # noqa: F401,F403
from .activity import router as activity_router
from .core import *  # noqa: F401,F403
from .core import router as core_router
from .datasets import *  # noqa: F401,F403
from .datasets import router as datasets_router
from .dvc import *  # noqa: F401,F403
from .dvc import router as dvc_router
from .figures import *  # noqa: F401,F403
from .figures import router as figures_router
from .fs import *  # noqa: F401,F403
from .fs import router as fs_router
from .pipeline import *  # noqa: F401,F403
from .pipeline import router as pipeline_router

router = APIRouter()
router.include_router(core_router)
router.include_router(dvc_router)
router.include_router(fs_router)
router.include_router(pipeline_router)
router.include_router(figures_router)
router.include_router(datasets_router)
router.include_router(activity_router)
