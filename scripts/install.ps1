# Install Calkit with uv (installing the latter if it isn't yet)
#
# Options, passed by running it as a script block, e.g.,
# & ([scriptblock]::Create((irm install-ps1.calkit.org))) --link
#   --link                 Also link this machine to the hub, which connects
#                          its workspaces to the hub
#                          (or set CALKIT_INSTALL_LINK=1, which also works
#                          with `irm ... | iex`)
#   --no-shell-completion  Skip installing shell completion
#   --no-browser           Skip letting the browser extension work with
#                          projects on this machine

# Every statement below is kept on a single line so the script still does the
# right thing when a shell feeds it to `iex` one line at a time, which is what
# happens if the quoting around `irm ... | iex` is lost and the outer shell,
# rather than the inner one, ends up handling the pipe (see issue #1569)

$InstallLink = ($args -contains "--link") -or ($env:CALKIT_INSTALL_LINK -eq "1")
$InstallCompletion = -not ($args -contains "--no-shell-completion")
$InstallBrowser = -not ($args -contains "--no-browser")

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

# uv's tool directory, which UV_TOOL_BIN_DIR can move, may not be on this
# process's PATH yet, and a command that isn't found doesn't set
# $LASTEXITCODE, so this checks Calkit is there
$env:Path = "$(uv tool dir --bin);$env:Path"
if (-not (Get-Command calkit -ErrorAction SilentlyContinue)) { throw "Calkit was installed but isn't on PATH; please check your uv installation" }

# Shell completion goes in the PowerShell profile, which only runs if the
# execution policy lets local scripts run. Typer's --install-completion sets
# it to Unrestricted every time, which is looser than needed and errors under
# this script's process-wide ByPass (issue #1835), so it's only set here, to
# RemoteSigned, when the user's own setting would keep the profile from running.
# Scopes are listed in order of precedence, Process aside.
if ($InstallCompletion) { $policy = "Restricted"; $byGroupPolicy = $false; foreach ($p in Get-ExecutionPolicy -List) { if ("$($p.Scope)" -ne "Process" -and "$($p.ExecutionPolicy)" -ne "Undefined") { $policy = "$($p.ExecutionPolicy)"; $byGroupPolicy = "$($p.Scope)" -like "*Policy"; break } } }

# Setting it succeeds even when the error says this process's ByPass overrides it
if ($InstallCompletion -and $policy -eq "Restricted" -and -not $byGroupPolicy) { Write-Host "Setting your execution policy to RemoteSigned so your PowerShell profile can load shell completion"; try { Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force -ErrorAction Stop; $policy = "RemoteSigned" } catch { if ("$($_.FullyQualifiedErrorId)" -like "ExecutionPolicyOverride*") { $policy = "RemoteSigned" } else { Write-Warning "Failed to set execution policy: $_" } } }

# Per command name, so the `ck` alias gets it too, and only once, so
# installing again doesn't add it again
if ($InstallCompletion) { if ($policy -notin @("RemoteSigned", "Unrestricted", "Bypass")) { Write-Warning "Skipping shell completion, since your execution policy ($policy) won't let your PowerShell profile run" } else { Write-Host "Installing shell completion"; foreach ($cmd in @("calkit", "ck")) { $script = (& $cmd --show-completion powershell) -join "`n"; if ($LASTEXITCODE -ne 0 -or -not $script) { Write-Warning "Failed to get shell completion for '$cmd'" } elseif ((Test-Path $PROFILE) -and (Select-String -Path $PROFILE -SimpleMatch -Pattern "-CommandName $cmd -ScriptBlock" -Quiet)) { Write-Host "Shell completion for '$cmd' is already in $PROFILE" } else { New-Item -ItemType Directory -Force -Path (Split-Path $PROFILE) | Out-Null; Add-Content -Path $PROFILE -Value $script; Write-Host "Installed shell completion for '$cmd' in $PROFILE" } } } }

if ($InstallBrowser) { & calkit browser install; if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to set up Calkit for the browser extension; run 'calkit browser install' to try again" } }

if ($InstallLink) { Write-Host "Linking this machine to the hub"; & calkit hub link install; if ($LASTEXITCODE -ne 0) { throw "Failed to link this machine; run 'calkit hub link install' to try again" } }

Write-Host "Success! Restart your shell to pick up Calkit on your PATH."
