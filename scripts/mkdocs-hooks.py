import subprocess
from pathlib import Path


def on_pre_build(config):
    project_dir = Path(config.config_file_path).parent
    subprocess.run(
        # [
        #     "calkit",
        #     "run",
        #     "version-control-diagram-docs"
        # ],
        [
            "pixi",
            "run",
            "--manifest-path",
            "docs/dev/pixi.toml",
            "-e",
            "graphviz-env",
            "python",
            "scripts/generate-version-control-diagram.py",
        ],
        cwd=project_dir,
        check=True,
    )
