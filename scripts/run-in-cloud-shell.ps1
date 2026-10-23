<#
.SYNOPSIS
  Runs Atlas in Docker on your Google Cloud Shell and makes it available on this
  machine at http://127.0.0.1:3000 (API on http://127.0.0.1:8000).

.DESCRIPTION
  A stopgap for machines that cannot run Docker or the backend locally. Cloud
  Shell is a free Linux VM that comes with a Google account; it needs no project
  and no billing.

  The script keeps running. It uploads the source, starts `docker compose` on
  the VM, forwards the ports, and reconnects when the connection drops. Stop it
  with Ctrl+C.

  Cloud Shell is temporary: Google recycles the VM when it has been idle, and
  with it the containers and the ingested data. The script then rebuilds the
  stack (about eight minutes) and you ingest again.

  To use the chat page, put a model key in a file named .env in the repo folder
  on this machine (see .env.example): ANTHROPIC_API_KEY, or LLM_PROVIDER=gemini
  with GEMINI_API_KEY. The script copies those settings to the stack on the VM,
  at startup and whenever the file changes, and restarts the API. Nothing else
  from .env is uploaded.

  Requires the gcloud CLI, signed in (`gcloud auth login`), and Windows' OpenSSH
  client.

  The source is uploaded again, and the containers rebuilt, whenever the code on
  this machine differs from the copy on the VM.

.PARAMETER Upload
  Upload the source even if the VM's copy looks current.
#>
param([switch]$Upload)

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot

# --- Local working directory ----------------------------------------------------
# ssh splits option values on spaces, so paths passed to it use the 8.3 short form.
$work = Join-Path $env:LOCALAPPDATA "atlas-cloud-shell"
New-Item -ItemType Directory -Force $work | Out-Null
$work = (New-Object -ComObject Scripting.FileSystemObject).GetFolder($work).ShortPath
if ($work -match "\s") { throw "No space-free path available for $work; enable 8.3 names or set LOCALAPPDATA." }

$gcloud = (Get-Command gcloud.cmd -ErrorAction SilentlyContinue).Source
if (-not $gcloud) { $gcloud = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" }
if (-not (Test-Path $gcloud)) { throw "gcloud was not found. Install the Google Cloud CLI and run 'gcloud auth login'." }

$account = (& $gcloud config get-value account 2>$null | Select-Object -First 1)
if (-not $account) { throw "gcloud is not signed in. Run 'gcloud auth login'." }
# Cloud Shell's user name is the part of the address before the @.
$remote = (($account -replace "@.*$", "") -replace "[^A-Za-z0-9_]", "_") + "@127.0.0.1"

$key = "$work\key"
$knownHosts = "$work\known_hosts"
$script:port = $null
$script:tunnel = $null
$script:attempt = 0
$script:fatal = $false

function Say([string]$message) { Write-Host ("{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $message) }

function Invoke-Bounded([string]$exe, [string[]]$arguments, [int]$seconds) {
    # Runs ssh or scp with a hard time limit. A connection can stall while it is
    # being set up, where ssh's own timeouts do not apply, and wait forever.
    $id = [guid]::NewGuid().ToString("N").Substring(0, 8)
    $out = "$work\call-$id.out"; $err = "$work\call-$id.err"
    $quoted = $arguments | ForEach-Object { if ($_ -match "\s") { '"' + $_ + '"' } else { $_ } }
    $process = Start-Process -FilePath $exe -ArgumentList $quoted -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $process.Handle  # keeps the exit code readable after the process ends
    $finished = $process.WaitForExit($seconds * 1000)
    if (-not $finished) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $null = $process.WaitForExit(5000)
    }
    $text = if (Test-Path -LiteralPath $out) { Get-Content -LiteralPath $out -Raw } else { "" }
    Remove-Item -LiteralPath $out, $err -Force -ErrorAction SilentlyContinue
    [pscustomobject]@{ Ok = ($finished -and $process.ExitCode -eq 0); Output = "$text".Trim() }
}

function SshOptions([string]$hostKeyMode) {
    # The keep-alive settings make ssh exit within a minute of the tunnel dying,
    # instead of waiting on it for as long as the machine stays up.
    @("-i", $key, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=$hostKeyMode",
      "-o", "UserKnownHostsFile=$knownHosts", "-o", "ConnectTimeout=30",
      "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3")
}

# --- Tunnel ---------------------------------------------------------------------
# `gcloud cloud-shell ssh` starts the VM and opens an authenticated tunnel to it on
# a local port. Its own SSH client (PuTTY's plink) then stops at a host-key prompt
# that cannot be answered here; that is harmless and keeps the tunnel open, and
# OpenSSH connects through the same port instead.
function Stop-Tunnel {
    if ($script:tunnel -and -not $script:tunnel.HasExited) { Stop-Process -Id $script:tunnel.Id -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match "cloud-shell ssh" -or ($_.Name -eq "plink.exe" -and $_.CommandLine -match "google-cloud-sdk") } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $script:port = $null
}

function Start-Tunnel {
    Stop-Tunnel
    # A new log file per attempt: the previous tunnel's process can hold its files
    # open for a moment after it is stopped, and deleting them then fails.
    $script:attempt++
    $out = "$work\tunnel-$($script:attempt).out"; $err = "$work\tunnel-$($script:attempt).err"
    Get-ChildItem -LiteralPath $work -Filter "tunnel*" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -ne $out -and $_.FullName -ne $err } |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $knownHosts -Force -ErrorAction SilentlyContinue

    $script:tunnel = Start-Process -FilePath $gcloud -PassThru -WindowStyle Hidden `
        -ArgumentList "cloud-shell", "ssh", "--authorize-session", "--quiet", "--command", '"sleep 43200"' `
        -RedirectStandardOutput $out -RedirectStandardError $err

    foreach ($attempt in 1..90) {
        Start-Sleep -Seconds 2
        $text = (Get-Content $out, $err -ErrorAction SilentlyContinue) -join "`n"
        if ($text -match "Listening on local port \[(\d+)\]") { $script:port = $Matches[1]; break }
        if ($script:tunnel.HasExited) { Say "gcloud exited: $(($text -split "`n")[-1])"; return $false }
    }
    if (-not $script:port) { Say "Timed out waiting for Cloud Shell."; return $false }

    # gcloud creates this key on first use. OpenSSH refuses it with its default
    # permissions, so work from a copy only this user can read.
    $source = "$env:USERPROFILE\.ssh\google_compute_engine"
    if (-not (Test-Path $source)) { Say "gcloud did not create an SSH key."; return $false }
    if (Test-Path -LiteralPath $key) { icacls $key /grant:r "${env:USERDOMAIN}\${env:USERNAME}:(F)" | Out-Null; [IO.File]::Delete($key) }
    Copy-Item -LiteralPath $source -Destination $key
    icacls $key /inheritance:r /grant:r "${env:USERDOMAIN}\${env:USERNAME}:(R)" | Out-Null

    # The tunnel is already authenticated by gcloud, so the VM's host key is
    # accepted on first contact and pinned for the rest of this tunnel's life.
    Start-Sleep -Seconds 2
    $options = SshOptions "accept-new"
    return (Invoke-Bounded "ssh.exe" (@("-p", $script:port) + $options + @($remote, "true")) 45).Ok
}

function Invoke-Remote([string]$name, [string]$body, [string]$argument = "") {
    # Uploads a small shell script and runs it; avoids quoting commands through two shells.
    $local = "$work\$name.sh"
    [IO.File]::WriteAllText($local, ($body -replace "`r`n", "`n"), (New-Object Text.UTF8Encoding $false))
    $options = SshOptions "yes"
    $copy = Invoke-Bounded "scp.exe" (@("-q", "-P", $script:port) + $options + @($local, "${remote}:.atlas-$name.sh")) 60
    if (-not $copy.Ok) { return $null }
    $run = Invoke-Bounded "ssh.exe" (@("-p", $script:port) + $options + @($remote, "bash .atlas-$name.sh $argument".Trim())) 180
    if (-not $run.Ok) { return $null }
    return $run.Output
}

# --- Remote scripts --------------------------------------------------------------
$stateScript = @'
cd ~/atlas 2>/dev/null || { echo MISSING; exit 0; }
[ -f docker-compose.yml ] || { echo MISSING; exit 0; }
if curl -fs -o /dev/null --max-time 5 http://127.0.0.1:3000/api/healthz; then echo READY
elif pgrep -f 'docker compose up' > /dev/null; then echo BUILDING
else echo DOWN; fi
'@

$startScript = @'
set -euo pipefail
mkdir -p ~/atlas
if [ "${1:-}" = "extract" ]; then
  # Replace the source but keep .env, which holds the user's API key.
  find ~/atlas -mindepth 1 -maxdepth 1 ! -name .env -exec rm -rf {} +
  tar -xzf ~/atlas-src.tgz -C ~/atlas
  # Which version of the source this is, so the runner can tell when it is stale.
  echo "${2:-}" > ~/atlas/.source-stamp
fi
cd ~/atlas
nohup docker compose up --build -d > ~/atlas-up.log 2>&1 &
echo STARTED
'@

$stampScript = @'
cat ~/atlas/.source-stamp 2>/dev/null || echo NONE
'@

$logScript = @'
tail -c 4000 ~/atlas-up.log 2>/dev/null | tr '\r' '\n' | grep -v '^\s*$' | tail -n 12
'@

function Get-SourceStamp {
    # A fingerprint of the source: each file's path, size and modification time.
    # git lists the files (tracked, plus new ones it does not ignore), which keeps
    # dependencies, build output and .env out of it. No git: no fingerprint, so
    # the source is uploaded every time.
    $git = (Get-Command git.exe -ErrorAction SilentlyContinue).Source
    if (-not $git) { return $null }
    $files = & $git -C $repo ls-files --cached --others --exclude-standard 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $files) { return $null }
    $lines = foreach ($file in ($files | Sort-Object -Unique)) {
        $item = Get-Item -LiteralPath (Join-Path $repo $file) -ErrorAction SilentlyContinue
        if ($item) { "$file|$($item.Length)|$($item.LastWriteTimeUtc.Ticks)" }
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    $hash = [Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    return ([BitConverter]::ToString($hash) -replace "-", "").Substring(0, 16).ToLower()
}

function Send-Source {
    $archive = "$work\atlas-src.tgz"
    if (Test-Path -LiteralPath $archive) { [IO.File]::Delete($archive) }
    # Dependencies, build output and anything that could hold a secret stay behind.
    $excluded = ".venv", "node_modules", ".next", "__pycache__", "*.egg-info", "build", "test-results",
        "playwright-report", ".terraform", ".pytest_cache", ".ruff_cache", ".git",
        ".env", ".env.local", "*.tfstate", "*.tfstate.*", "terraform.tfvars"
    $tarArguments = @("-czf", $archive, "-C", $repo) + ($excluded | ForEach-Object { "--exclude=$_" }) + @(".")
    & tar.exe @tarArguments
    if ($LASTEXITCODE -ne 0) { return $false }
    $options = SshOptions "yes"
    return (Invoke-Bounded "scp.exe" (@("-q", "-P", $script:port) + $options + @($archive, "${remote}:atlas-src.tgz")) 180).Ok
}

# The only settings copied from the local .env to the VM.
$syncedSettings = "LLM_PROVIDER", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GEMINI_MODELS",
    "GROQ_API_KEY", "OPENROUTER_API_KEY", "MISTRAL_API_KEY", "GITHUB_TOKEN", "CEREBRAS_API_KEY", "GITHUB_MODELS_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "HUGGINGFACE_API_KEY", "SAMBANOVA_API_KEY", "NVIDIA_API_KEY", "DEEPSEEK_API_KEY", "COHERE_API_KEY", "TOGETHER_API_KEY"

$keyScript = @'
set -euo pipefail
mkdir -p ~/atlas
cd ~/atlas
touch .env
grep -v -E '^(LLM_PROVIDER|ANTHROPIC_API_KEY|GEMINI_API_KEY|GEMINI_MODELS|GITHUB_TOKEN|GROQ_API_KEY|OPENROUTER_API_KEY|MISTRAL_API_KEY|CEREBRAS_API_KEY|GITHUB_MODELS_TOKEN|CLOUDFLARE_ACCOUNT_ID|CLOUDFLARE_API_TOKEN|HUGGINGFACE_API_KEY|SAMBANOVA_API_KEY|NVIDIA_API_KEY|DEEPSEEK_API_KEY|COHERE_API_KEY|TOGETHER_API_KEY)=' .env > .env.new || true
cat ~/.atlas-key.env >> .env.new
rm -f ~/.atlas-key.env
if cmp -s .env .env.new; then
  rm .env.new
  echo UNCHANGED
else
  mv .env.new .env
  chmod 600 .env
  # Compose reads .env when it starts, so a build that is about to be started
  # picks the change up by itself; a running stack has to be told.
  if [ "${1:-}" != "norestart" ]; then docker compose up -d > /dev/null 2>&1; fi
  echo APPLIED
fi
'@

function Get-LocalSettings {
    # The model-provider settings present in the local .env, as NAME=value lines.
    $file = Join-Path $repo ".env"
    if (-not (Test-Path -LiteralPath $file)) { return @() }
    $found = [ordered]@{}
    foreach ($line in Get-Content -LiteralPath $file) {
        if ($line -match "^\s*([A-Z_]+)\s*=\s*(\S.*)$" -and $syncedSettings -contains $Matches[1]) {
            $found[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
    @($found.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" })
}

function Test-ChatConfigured {
    @(Get-LocalSettings | Where-Object { $_ -match "^(ANTHROPIC_API_KEY|GEMINI_API_KEY)=" }).Count -gt 0
}

function Sync-ApiKey([switch]$NoRestart) {
    # Copies the model-provider settings from the repo's local .env to the stack on
    # the VM, leaving every other line of the remote .env alone. Returns $true if
    # the settings changed (and, unless -NoRestart, the API was restarted).
    $lines = Get-LocalSettings
    if ($lines.Count -eq 0) { return $false }
    $temp = "$work\key.env"
    [IO.File]::WriteAllText($temp, (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding $false))
    try {
        $options = SshOptions "yes"
        $copy = Invoke-Bounded "scp.exe" (@("-q", "-P", $script:port) + $options + @($temp, "${remote}:.atlas-key.env")) 60
        if (-not $copy.Ok) { return $false }
    }
    finally { [IO.File]::Delete($temp) }
    if ($NoRestart) { return ((Invoke-Remote "key" $keyScript "norestart") -eq "APPLIED") }
    $result = Invoke-Remote "key" $keyScript
    if ($result -eq "APPLIED") { Say "Applied the model settings from .env; the API is restarting."; return $true }
    return $false
}

function Get-LocalEnvStamp {
    $file = Join-Path $repo ".env"
    if (Test-Path -LiteralPath $file) { (Get-Item -LiteralPath $file).LastWriteTimeUtc.Ticks } else { 0 }
}

function Wait-Ready([int]$checks) {
    foreach ($check in 1..$checks) {
        if ((Invoke-Remote "state" $stateScript) -eq "READY") { return $true }
        Start-Sleep -Seconds 5
    }
    return $false
}

function Start-Forward {
    $options = SshOptions "yes"
    $arguments = @("-N", "-p", $script:port) + $options + @(
        "-o", "ExitOnForwardFailure=yes",
        "-L", "127.0.0.1:3000:127.0.0.1:3000",
        "-L", "127.0.0.1:8000:127.0.0.1:8000",
        $remote)
    Start-Process -FilePath "ssh.exe" -ArgumentList $arguments -PassThru -WindowStyle Hidden -RedirectStandardError "$work\forward.err"
}

function Test-Local {
    # curl with a hard time limit. Invoke-WebRequest can wait indefinitely when the
    # forwarded port accepts the connection but the tunnel behind it has died.
    $status = & curl.exe -s -o NUL -m 10 -w "%{http_code}" "http://127.0.0.1:3000/api/healthz" 2>$null
    return ($status -eq "200")
}

# --- Main loop -------------------------------------------------------------------
Say "Cloud Shell account: $account"
$uploadPending = [bool]$Upload
$forward = $null
try {
    while ($true) {
        try {
        Say "Connecting to Cloud Shell (starting the VM can take a minute)..."
        if (-not (Start-Tunnel)) { Say "Could not connect; retrying in 20 seconds."; Start-Sleep -Seconds 20; continue }

        $state = Invoke-Remote "state" $stateScript
        if ($null -eq $state) { Say "Connection dropped; reconnecting."; continue }

        # The VM keeps the source between runs; replace it when the code here changed.
        $sourceStamp = Get-SourceStamp
        if ($state -ne "MISSING" -and -not $uploadPending) {
            $vmStamp = Invoke-Remote "stamp" $stampScript
            if ($null -eq $vmStamp) { Say "Connection dropped; reconnecting."; continue }
            if (-not $sourceStamp -or $vmStamp.Trim() -ne $sourceStamp) {
                Say "The code on this machine differs from the copy on Cloud Shell."
                $uploadPending = $true
            }
        }

        if ($state -eq "MISSING" -or $uploadPending) {
            Say "Uploading the source..."
            if (-not (Send-Source)) { Say "Upload failed; reconnecting."; continue }
            [void](Sync-ApiKey -NoRestart)
            if ($null -eq (Invoke-Remote "start" $startScript ("extract $sourceStamp".Trim()))) { Say "Connection dropped; reconnecting."; continue }
            $uploadPending = $false
            Say "Building and starting the containers. The first build takes about eight minutes."
        }
        elseif ($state -eq "DOWN") {
            Say "The VM was recycled. Rebuilding the containers (about eight minutes); ingested data was lost."
            [void](Sync-ApiKey -NoRestart)
            if ($null -eq (Invoke-Remote "start" $startScript)) { Say "Connection dropped; reconnecting."; continue }
        }

        # Wait for the stack. A dropped connection goes back to the top; the build
        # carries on by itself on the VM.
        $ready = $false; $downChecks = 0
        foreach ($check in 1..90) {
            $state = Invoke-Remote "state" $stateScript
            if ($null -eq $state) { break }
            if ($state -eq "READY") { $ready = $true; break }
            if ($state -eq "DOWN") {
                $downChecks++
                if ($downChecks -ge 6) {
                    Say "The stack did not come up. Last build output:"
                    Write-Host (Invoke-Remote "log" $logScript)
                    $script:fatal = $true  # a broken build will not fix itself by retrying
                    throw "docker compose failed on Cloud Shell."
                }
            }
            Start-Sleep -Seconds 20
        }
        if (-not $ready) { Say "Connection dropped while waiting; reconnecting."; continue }

        $envStamp = Get-LocalEnvStamp
        if (Sync-ApiKey) { [void](Wait-Ready 24) }

        $forward = Start-Forward
        Start-Sleep -Seconds 4
        if (-not (Test-Local)) { Say "Port forward failed; reconnecting."; continue }
        Say "Atlas is running:  http://127.0.0.1:3000   (API: http://127.0.0.1:8000/docs)"
        if (-not (Test-ChatConfigured)) { Say "Chat is off: add a model key to .env in the repo folder (see .env.example)." }
        Say "Leave this window open. Press Ctrl+C to stop."

        $failures = 0
        while ($failures -lt 3) {
            Start-Sleep -Seconds 20
            # Pick up a key added or changed in the local .env while running.
            $stamp = Get-LocalEnvStamp
            if ($stamp -ne $envStamp) {
                $envStamp = $stamp
                if (Sync-ApiKey) { [void](Wait-Ready 24); Say "Chat is ready." }
            }
            if ($forward.HasExited -or -not (Test-Local)) { $failures++ } else { $failures = 0 }
        }
        Say "Connection lost; reconnecting."
        if (-not $forward.HasExited) { Stop-Process -Id $forward.Id -Force -ErrorAction SilentlyContinue }
        }
        catch {
            # Anything unexpected (a locked file, a failed process start) must not end
            # the runner: report it and start the cycle again.
            if ($script:fatal) { throw }
            Say "Unexpected error: $($_.Exception.Message)"
            Say "Retrying in 20 seconds."
            if ($forward -and -not $forward.HasExited) { Stop-Process -Id $forward.Id -Force -ErrorAction SilentlyContinue }
            Start-Sleep -Seconds 20
        }
    }
}
finally {
    if ($forward -and -not $forward.HasExited) { Stop-Process -Id $forward.Id -Force -ErrorAction SilentlyContinue }
    Stop-Tunnel
    Say "Stopped. The containers keep running on Cloud Shell until the VM goes idle."
}
