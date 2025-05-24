"""Pipeline-related functionality."""

import calkit
from calkit.models.pipeline import Pipeline


def to_dvc(wdir: str | None = None) -> dict:
    """Transpile a Calkit pipeline to a DVC pipeline."""
    ck_info = calkit.load_calkit_info(wdir=wdir)
    if "pipeline" not in ck_info:
        raise ValueError("No pipeline found in calkit.yaml")
    try:
        pipeline = Pipeline.model_validate(ck_info["pipeline"])
    except Exception as e:
        raise ValueError(f"Pipeline is not defined properly: {e}")
    dvc_stages = {}
    # First, create stages for checking all environments
    # TODO
    # Now convert Calkit stages into DVC stages
    for stage_name, stage in pipeline.stages.items():
        dvc_stages[stage_name] = stage.to_dvc()
        # TODO: Add environment lock file to deps
    return dvc_stages
