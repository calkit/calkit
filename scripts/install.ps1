# First, check if uv is installed
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    # Install uv
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
}

# Install Calkit using uv
uv tool install --upgrade calkit-python
