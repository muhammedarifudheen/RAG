<#
.SYNOPSIS
  Deploys Atlas's server to a Hugging Face Space, for the public website on GitHub Pages.

.DESCRIPTION
  Assembles the Space's files (deploy/server's image plus the API, worker and shared
  packages), creates the Space if it does not exist, sets its secrets and variables,
  and pushes. Hugging Face then builds and starts it, which takes about ten minutes.

  Needs a Hugging Face access token with write permission
  (https://huggingface.co/settings/tokens), passed as -Token or in HF_TOKEN.

.PARAMETER Space
  owner/name of the Space, for example "your-name/atlas-api".

.PARAMETER SiteOrigin
  The website's origin, allowed to call the API: https://<github user>.github.io

.PARAMETER AdminToken
  Password for adding and removing sources. Generated when not given; the
  script prints it once.

.PARAMETER StageOnly
  Only assemble the Space's files into -StageDir; push nothing.
#>
param(
    [Parameter(Mandatory)][string]$Space,
    [string]$Token = $env:HF_TOKEN,
    [string]$SiteOrigin,
    [string]$AdminToken,
    [string]$SeedSources = "https://github.com/pallets/itsdangerous https://en.wikipedia.org/wiki/HMAC https://docs.python.org/3/library/hmac.html",
    [switch]$StageOnly,
    [string]$StageDir = (Join-Path ([IO.Path]::GetTempPath()) "atlas-space")
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

function Read-DotEnv([string]$name) {
    $file = Join-Path $repo ".env"
    if (-not (Test-Path -LiteralPath $file)) { return $null }
    foreach ($line in Get-Content -LiteralPath $file) {
        if ($line -match "^\s*$name\s*=\s*(\S.*)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}

# --- Assemble the Space's files ---------------------------------------------------
if (Test-Path -LiteralPath $StageDir) { Remove-Item -LiteralPath $StageDir -Recurse -Force }
New-Item -ItemType Directory -Path $StageDir | Out-Null
$archive = Join-Path ([IO.Path]::GetTempPath()) "atlas-space.tar"
$excluded = ".venv", "node_modules", "__pycache__", "*.egg-info", "build", ".pytest_cache",
    ".ruff_cache", ".env", "tests"
$tarArguments = @("-cf", $archive, "-C", $repo) + ($excluded | ForEach-Object { "--exclude=$_" }) +
    @("packages/shared", "apps/api", "apps/worker", "deploy/server")
& tar.exe @tarArguments
if ($LASTEXITCODE -ne 0) { throw "Could not package the source." }
& tar.exe -xf $archive -C $StageDir
Remove-Item -LiteralPath $archive -Force

# A Space builds the Dockerfile at its root, with its root as the build context.
$files = @{ "Dockerfile" = "deploy\server\Dockerfile"; "README.md" = "deploy\huggingface\README.md"
    "deploy\server\start.sh" = "deploy\server\start.sh" }
foreach ($entry in $files.GetEnumerator()) {
    # Linux line endings: the Space builds and runs on Linux.
    $text = [IO.File]::ReadAllText((Join-Path $repo $entry.Value)) -replace "`r`n", "`n"
    [IO.File]::WriteAllText((Join-Path $StageDir $entry.Key), $text, (New-Object Text.UTF8Encoding $false))
}
Write-Host "Space files assembled in $StageDir"
if ($StageOnly) { return }

# --- Create the Space and configure it ----------------------------------------------
if (-not $Token) { throw "Pass -Token or set HF_TOKEN (a Hugging Face token with write access)." }
if (-not $SiteOrigin) { throw "Pass -SiteOrigin, the website's address, e.g. https://your-name.github.io" }
$owner, $name = $Space.Split("/", 2)
$headers = @{ Authorization = "Bearer $Token" }
$api = "https://huggingface.co/api"

$create = @{ type = "space"; name = $name; sdk = "docker"; private = $false }
$me = Invoke-RestMethod "$api/whoami-v2" -Headers $headers
if ($owner -ne $me.name) { $create.organization = $owner }
try {
    Invoke-RestMethod "$api/repos/create" -Method Post -Headers $headers -ContentType "application/json" `
        -Body ($create | ConvertTo-Json) | Out-Null
    Write-Host "Created the Space $Space"
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) {
        Write-Host "The Space $Space already exists; updating it"
    } else { throw }
}

if (-not $AdminToken) {
    $bytes = New-Object byte[] 18
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $AdminToken = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
    Write-Host ""
    Write-Host "Admin password (keep it; it is not shown again): $AdminToken"
    Write-Host ""
}

$provider = Read-DotEnv "LLM_PROVIDER"
$secrets = @{ ADMIN_TOKEN = $AdminToken; LLM_PROVIDER = ($provider, "anthropic" | Where-Object { $_ } | Select-Object -First 1) }
foreach ($key in "GEMINI_API_KEY", "ANTHROPIC_API_KEY") {
    $value = Read-DotEnv $key
    if ($value) { $secrets[$key] = $value }
}
foreach ($entry in $secrets.GetEnumerator()) {
    Invoke-RestMethod "$api/spaces/$Space/secrets" -Method Post -Headers $headers -ContentType "application/json" `
        -Body (@{ key = $entry.Key; value = $entry.Value } | ConvertTo-Json) | Out-Null
}
$variables = @{
    CORS_ORIGINS = (ConvertTo-Json @($SiteOrigin.TrimEnd("/")) -Compress)
    SEED_SOURCES = $SeedSources
}
foreach ($entry in $variables.GetEnumerator()) {
    Invoke-RestMethod "$api/spaces/$Space/variables" -Method Post -Headers $headers -ContentType "application/json" `
        -Body (@{ key = $entry.Key; value = $entry.Value } | ConvertTo-Json) | Out-Null
}
Write-Host "Set secrets: $(($secrets.Keys | Sort-Object) -join ', '); variables: $(($variables.Keys | Sort-Object) -join ', ')"

# --- Push ----------------------------------------------------------------------------
Push-Location $StageDir
try {
    git init -q -b main
    git add -A
    git -c user.name="atlas-deploy" -c user.email="atlas-deploy@users.noreply.huggingface.co" commit -q -m "Deploy Atlas API"
    # The token goes in a header for this one command, not into any saved remote.
    git -c "http.extraHeader=Authorization: Bearer $Token" push -q --force "https://huggingface.co/spaces/$Space" main
    if ($LASTEXITCODE -ne 0) { throw "Pushing to the Space failed." }
} finally { Pop-Location }

$host_ = ("$owner-$name".ToLower() -replace "[^a-z0-9-]", "-")
Write-Host ""
Write-Host "Pushed. Hugging Face is now building the Space (about ten minutes):"
Write-Host "  build log: https://huggingface.co/spaces/$Space"
Write-Host "  API:       https://$host_.hf.space"
