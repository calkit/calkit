#!/bin/bash
set -e

# Get version from VCS via hatch
VERSION="$(uvx hatch version)"

# Create calk9 directory structure
rm -rf calk9
mkdir -p calk9

# Create pyproject.toml
cat > calk9/pyproject.toml <<EOF
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "calk9"
version = "$VERSION"
description = "Reproducibility simplified."
readme = "README.md"
requires-python = ">=3.10"
dependencies = ["calkit-python==$VERSION"]
authors = [{ name = "Pete Bachant", email = "petebachant@gmail.com" }]
license = { text = "MIT" }

[project.urls]
Homepage = "https://calkit.org"
Repository = "https://github.com/calkit/calkit"

[project.scripts]
calk9 = "calkit.cli:run"
EOF

# Create README.md
cat > calk9/README.md <<EOF
# calk9

Alias package for [calkit-python](https://pypi.org/project/calkit-python/).

This package provides the \`calk9\` command as a shorter alternative to \`calkit\`.

## Installation

\`\`\`sh
pip install calk9
\`\`\`

Or use with uvx without installation:

\`\`\`sh
uvx calk9 --help
\`\`\`

See the [Calkit documentation](https://docs.calkit.org) for more information.
EOF

echo "Created calk9/ package with version $VERSION"
