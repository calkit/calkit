# Install Calkit with uv (installing the latter if it isn't yet)

# Every statement below is kept on a single line so the script still does the
# right thing when a shell feeds it to `iex` one line at a time, which is what
# happens if the quoting around `irm ... | iex` is lost and the outer shell,
# rather than the inner one, ends up handling the pipe (see issue #1569)

# Check if uv is installed
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Write-Host "Installing uv"; powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" } else { Write-Host "uv is already installed" }

# uv and the tools it installs go in ~\.local\bin, which this process won't
# have on its PATH, since it started before uv put it there
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "Failed to install uv; please install it manually from https://docs.astral.sh/uv/getting-started/installation/" }

# Install Calkit using uv
Write-Host "Installing Calkit"
uv tool install --upgrade calkit-python --python=3.14
if ($LASTEXITCODE -ne 0) { throw "Failed to install Calkit; please check your uv installation" }

# Install shell completion, per command name, so the `ck` alias gets it too
Write-Host "Installing shell completion"
foreach ($cmd in @("calkit", "ck")) { & $cmd --install-completion; if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to install shell completion for '$cmd'; run '$cmd --install-completion' manually" } }

Write-Host "Success! Restart your shell to pick up Calkit on your PATH."
