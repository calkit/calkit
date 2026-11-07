import json
import subprocess
import tempfile
from pathlib import Path

ENVIRONMENT_YML = """
name: graphviz-env
channels:
  - conda-forge
dependencies:
  - python
  - graphviz
  - pip
  - pip:
      - graphviz
"""


def on_pre_build(config):
    project_dir = Path(config.config_file_path).parent
    env_name = "graphviz-env"

    # Check whether the environment exists
    result = subprocess.run(
        ["conda", "env", "list", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )

    env_paths = json.loads(result.stdout)["envs"]
    env_exists = any(Path(p).name == env_name for p in env_paths)

    if not env_exists:
        # Write environment definition to a temporary YAML file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yml",
            encoding="utf-8",
        ) as f:
            f.write(ENVIRONMENT_YML)
            f.flush()

            subprocess.run(
                ["conda", "env", "create", "-f", f.name],
                cwd=project_dir,
                check=True,
            )

    # Generate SVG
    subprocess.run(
        [
            "conda",
            "run",
            "--no-capture-output",
            "-n",
            env_name,
            "python",
            str(project_dir / "scripts/generate_version_control_diagram.py"),
        ],
        cwd=project_dir,
        check=True,
    )
