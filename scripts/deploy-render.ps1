<#
.SYNOPSIS
  Deploys Atlas's server to Render's free plan, for the public website on GitHub Pages.

.DESCRIPTION
  Creates (or updates) a Render web service that builds deploy/server/Dockerfile
  from the public GitHub repository, sets its settings, and starts a deploy. The
  same service is described in render.yaml, for creating it from Render's
  dashboard instead.

  Needs a Render API key (https://dashboard.render.com/u/settings#api-keys),
  passed as -ApiKey or in RENDER_API_KEY. The model keys (GEMINI_API_KEY,
  ANTHROPIC_API_KEY and every other AI service's key listed in .env.example) and
  LLM_PROVIDER are read from the repository's .env.

.PARAMETER SiteOrigin
  The website's origin, allowed to call the API: https://<github user>.github.io

.PARAMETER AdminToken
  Password for adding and removing sources. Generated when not given; the
  script prints it once. Left unchanged when updating an existing service.
#>
param(
    [string]$ApiKey = $env:RENDER_API_KEY,
    [string]$Name = "atlas-api",
    [string]$Repo = "https://github.com/muhammedarifudheen/RAG",
    [string]$Branch = "main",
    [string]$Region = "oregon",
    [Parameter(Mandatory)][string]$SiteOrigin,
    [string]$AdminToken,
    [string]$SeedSources = "https://en.wikipedia.org/wiki/HMAC https://docs.python.org/3/library/hmac.html https://github.com/pallets/itsdangerous"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $ApiKey) { throw "Pass -ApiKey or set RENDER_API_KEY (a Render API key)." }
$headers = @{ Authorization = "Bearer $ApiKey"; Accept = "application/json" }
$api = "https://api.render.com/v1"

function Read-DotEnv([string]$key) {
    $file = Join-Path $repoRoot ".env"
    if (-not (Test-Path -LiteralPath $file)) { return $null }
    foreach ($line in Get-Content -LiteralPath $file) {
        if ($line -match "^\s*$key\s*=\s*(\S.*)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}

function Invoke-Render([string]$method, [string]$path, $body) {
    $arguments = @{ Uri = "$api$path"; Method = $method; Headers = $headers }
    if ($null -ne $body) {
        $arguments.ContentType = "application/json"
        $arguments.Body = ($body | ConvertTo-Json -Depth 8)
    }
    Invoke-RestMethod @arguments
}

# --- Settings ------------------------------------------------------------------------
$provider = Read-DotEnv "LLM_PROVIDER"
if (-not $provider) { $provider = "gemini" }
$settings = [ordered]@{
    LLM_PROVIDER = $provider
    CORS_ORIGINS = (ConvertTo-Json @($SiteOrigin.TrimEnd("/")) -Compress)
    SEED_SOURCES = $SeedSources
}
foreach ($key in "GEMINI_API_KEY", "GEMINI_MODELS", "ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "MISTRAL_API_KEY",
    "CEREBRAS_API_KEY", "GITHUB_MODELS_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "HUGGINGFACE_API_KEY", "SAMBANOVA_API_KEY", "NVIDIA_API_KEY", "DEEPSEEK_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "COHERE_API_KEY", "TOGETHER_API_KEY", "HORDE_API_KEY", "GEMINI_IMAGES") {
    $value = Read-DotEnv $key
    if ($value) { $settings[$key] = $value }
}

# --- Find or create the service ------------------------------------------------------
$owner = (Invoke-Render GET "/owners?limit=20" $null | Select-Object -First 1).owner
$existing = Invoke-Render GET "/services?name=$Name&ownerId=$($owner.id)&limit=20" $null |
    ForEach-Object { $_.service } | Where-Object { $_.name -eq $Name } | Select-Object -First 1

if ($existing) {
    Write-Host "Updating the existing Render service $Name"
    # Keep the admin password unless a new one was given.
    $current = Invoke-Render GET "/services/$($existing.id)/env-vars?limit=100" $null | ForEach-Object { $_.envVar }
    $kept = $current | Where-Object { $_.key -eq "ADMIN_TOKEN" } | Select-Object -First 1
    $settings.ADMIN_TOKEN = if ($AdminToken) { $AdminToken } elseif ($kept) { $kept.value } else { $null }
}
if (-not $settings.ADMIN_TOKEN) {
    if (-not $AdminToken) {
        $bytes = New-Object byte[] 18
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $AdminToken = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
        Write-Host ""
        Write-Host "Admin password (keep it; it is also in the service's Environment tab): $AdminToken"
        Write-Host ""
    }
    $settings.ADMIN_TOKEN = $AdminToken
}
$envVars = @($settings.GetEnumerator() | ForEach-Object { @{ key = $_.Key; value = $_.Value } })

if ($existing) {
    $service = $existing
    Invoke-Render PUT "/services/$($service.id)/env-vars" $envVars | Out-Null
    Invoke-Render POST "/services/$($service.id)/deploys" @{ clearCache = "do_not_clear" } | Out-Null
} else {
    $service = Invoke-Render POST "/services" @{
        type = "web_service"
        name = $Name
        ownerId = $owner.id
        repo = $Repo
        branch = $Branch
        autoDeploy = "yes"
        envVars = $envVars
        serviceDetails = @{
            runtime = "docker"
            plan = "free"
            region = $Region
            healthCheckPath = "/healthz"
            envSpecificDetails = @{ dockerContext = "."; dockerfilePath = "./deploy/server/Dockerfile" }
        }
    }
    if ($service.service) { $service = $service.service }
    Write-Host "Created the Render service $Name"
}

$url = (Invoke-Render GET "/services/$($service.id)" $null).serviceDetails.url
Write-Host "Set: $(($settings.Keys | Sort-Object) -join ', ')"
Write-Host ""
Write-Host "Render is now building the server (about ten minutes):"
Write-Host "  dashboard: https://dashboard.render.com/web/$($service.id)"
Write-Host "  API:       $url"
Write-Host ""
Write-Host "Set the GitHub repository variable PUBLIC_API_URL to $url"
