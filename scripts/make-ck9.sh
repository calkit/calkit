#!/bin/bash
set -e

# Get version from VCS via hatch
VERSION="$(uvx --with 'virtualenv<20.29.0' hatch version)"

# Create ck9 directory structure
rm -rf ck9
mkdir -p ck9

# Create pyproject.toml
cat > ck9/pyproject.toml <<EOF
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "ck9"
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
ck9 = "calkit.cli:run"
EOF

# Create README.md
cat > ck9/README.md <<EOF
# ck9

Alias package for [calkit-python](https://pypi.org/project/calkit-python/).

This package provides the \`ck9\` command as a shorter alternative to \`calkit\`.

## Installation

\`\`\`sh
pip install ck9
\`\`\`

Or use with uvx without installation:

\`\`\`sh
uvx ck9 --help
\`\`\`

See the [Calkit documentation](https://docs.calkit.org) for more information.
EOF

echo "Created ck9/ package with version $VERSION"
