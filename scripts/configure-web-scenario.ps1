#Requires -Version 5.1
<#
.SYNOPSIS
    configure-web-scenario.ps1
    Patches a LoadRunner Web HTTP/HTML .lrs scenario file with all runtime
    settings equivalent to what you'd configure manually in:
      - MicroFocus Performance Centre → Scenario Designer
      - LoadRunner Controller → Scenario → Runtime Settings

.DESCRIPTION
    Covers:
      Scenario Scheduling   — real_world / goal_oriented / basic
      Think Time            — as_recorded / ignore / multiply / random_percentage / fixed_seconds
      Iteration Pacing      — immediately / fixed_delay / random_delay / fixed_from_start / random_from_start
      Browser Emulation     — chrome / firefox / ie11 / mobile-android / mobile-ios
      Network Simulation    — unlimited / cable / DSL / GPRS / modem
      Cache Simulation      — enabled/disabled
      Non-HTML Resources    — download enabled/disabled
      Logging               — none / errors_only / extended / full
      Error Handling        — continue_iteration / continue_action / stop_vuser / stop_test
      Credential injection  — per-user or shared service account
#>

param(
    [Parameter(Mandatory)] [string] $ScenarioFile,
    [Parameter(Mandatory)] [string] $SchedulerMode,       # real_world | goal_oriented | basic
    [Parameter(Mandatory)] [int]    $VUsers,
    [Parameter(Mandatory)] [int]    $RampUpMin,
    [Parameter(Mandatory)] [int]    $SteadyMin,
    [int]    $RampDownMin      = 2,
    [string] $GoalMetric       = "transactions_per_second",
    [int]    $GoalValue        = 50,
    [int]    $GoalMaxVUsers    = 300,
    [string] $ThinkTimeMode    = "as_recorded",
    [double] $ThinkTimeValue   = 1.0,
    [int]    $ThinkTimeMinPct  = 50,
    [int]    $ThinkTimeMaxPct  = 150,
    [string] $PacingMode       = "immediately",
    [int]    $PacingMinSec     = 0,
    [int]    $PacingMaxSec     = 10,
    [int]    $Iterations       = 0,
    [string] $Browser          = "chrome",
    [string] $NetworkSpeed     = "unlimited",
    [bool]   $SimulateCache    = $true,
    [bool]   $DownloadNonHtml  = $true,
    [string] $LogLevel         = "errors_only",
    [string] $OnError          = "continue_to_next_iteration",
    [Parameter(Mandatory)] [string] $TargetEnv,
    [Parameter(Mandatory)] [string] $LicenseServer,
    [string] $ParameterFile    = "configs\params-web.dat"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Step([string]$msg) { Write-Host "  ➤ $msg" -ForegroundColor Cyan }
function Info([string]$msg) { Write-Host "    $msg"  -ForegroundColor Gray }

# ────────────────────────────────────────────────────────────────
# 1. Load .lrs XML
# ────────────────────────────────────────────────────────────────
Step "Loading scenario: $ScenarioFile"
if (-not (Test-Path $ScenarioFile)) { throw "Scenario file not found: $ScenarioFile" }
[xml]$lrs = Get-Content $ScenarioFile -Encoding UTF8

# ────────────────────────────────────────────────────────────────
# 2. SCHEDULER — mirrors PC Scenario Designer
# ────────────────────────────────────────────────────────────────
Step "Applying scheduler: $SchedulerMode"
$sched = $lrs.SelectSingleNode("//Scheduler")

switch ($SchedulerMode) {

    "real_world" {
        # Three-phase: ramp-up → steady → ramp-down
        # Equivalent to PC "Real World Schedule" with group actions
        Info "Phases: Ramp ${RampUpMin}m | Steady ${SteadyMin}m | RampDown ${RampDownMin}m"
        if ($sched) {
            $sched.SetAttribute("Mode", "RealWorld")
            $sched.SetAttribute("Duration",    ($SteadyMin  * 60).ToString())
            $sched.SetAttribute("RampUpTime",  ($RampUpMin  * 60).ToString())
            $sched.SetAttribute("RampDownTime",($RampDownMin* 60).ToString())
        }
        # Set VUser count on all groups
        $lrs.SelectNodes("//Group") | ForEach-Object { $_.SetAttribute("VUsers", $VUsers) }
    }

    "goal_oriented" {
        # PC "Goal Oriented Scenario" — LR varies VUser count to hit metric target
        Info "Goal: $GoalValue $GoalMetric (max $GoalMaxVUsers VUsers)"
        if ($sched) {
            $sched.SetAttribute("Mode",            "GoalOriented")
            $sched.SetAttribute("GoalType",        $GoalMetric)
            $sched.SetAttribute("GoalValue",       $GoalValue.ToString())
            $sched.SetAttribute("MaxVUsers",       $GoalMaxVUsers.ToString())
            $sched.SetAttribute("Duration",        ($SteadyMin * 60).ToString())
            $sched.SetAttribute("RampUpTime",      ($RampUpMin * 60).ToString())
        }
        # VUser count managed by LR; set ceiling
        $lrs.SelectNodes("//Group") | ForEach-Object { $_.SetAttribute("VUsers", $GoalMaxVUsers) }
    }

    "basic" {
        # Fixed VUsers, fixed duration — simplest mode
        Info "Basic: $VUsers VUsers for ${SteadyMin}m"
        if ($sched) {
            $sched.SetAttribute("Mode",       "Basic")
            $sched.SetAttribute("Duration",   ($SteadyMin * 60).ToString())
            $sched.SetAttribute("RampUpTime", ($RampUpMin * 60).ToString())
        }
        $lrs.SelectNodes("//Group") | ForEach-Object { $_.SetAttribute("VUsers", $VUsers) }
    }
}

# ────────────────────────────────────────────────────────────────
# 3. RUNTIME SETTINGS — Think Time
#    Mirrors: LR Controller → Scenario → Runtime Settings → Think Time
# ────────────────────────────────────────────────────────────────
Step "Think time: $ThinkTimeMode"
$rtNode = $lrs.SelectSingleNode("//RuntimeSettings")

# Helper: ensure a child node exists
function EnsureNode([xml]$doc, $parent, [string]$name) {
    $n = $parent.SelectSingleNode($name)
    if (-not $n) { $n = $doc.CreateElement($name); $parent.AppendChild($n) | Out-Null }
    return $n
}

$ttNode = EnsureNode $lrs $rtNode "ThinkTime"

switch ($ThinkTimeMode) {
    "as_recorded" {
        $ttNode.SetAttribute("Type",   "AsRecorded")
        $ttNode.SetAttribute("Factor", "1.0")
        Info "Using recorded think times exactly"
    }
    "ignore" {
        $ttNode.SetAttribute("Type",   "Ignore")
        Info "Think time disabled (max load / stress mode)"
    }
    "multiply" {
        $ttNode.SetAttribute("Type",   "Multiply")
        $ttNode.SetAttribute("Factor", $ThinkTimeValue.ToString())
        Info "Recorded think time × $ThinkTimeValue"
    }
    "random_percentage" {
        $ttNode.SetAttribute("Type",   "Random")
        $ttNode.SetAttribute("MinPct", $ThinkTimeMinPct.ToString())
        $ttNode.SetAttribute("MaxPct", $ThinkTimeMaxPct.ToString())
        Info "Random $ThinkTimeMinPct%–$ThinkTimeMaxPct% of recorded"
    }
    "fixed_seconds" {
        $ttNode.SetAttribute("Type",    "Fixed")
        $ttNode.SetAttribute("Seconds", $ThinkTimeValue.ToString())
        Info "Fixed ${ThinkTimeValue}s between actions"
    }
}

# ────────────────────────────────────────────────────────────────
# 4. RUNTIME SETTINGS — Iteration Pacing
#    Mirrors: Runtime Settings → Pacing
# ────────────────────────────────────────────────────────────────
Step "Pacing: $PacingMode"
$pacNode = EnsureNode $lrs $rtNode "Pacing"

switch ($PacingMode) {
    "immediately" {
        $pacNode.SetAttribute("Type", "Immediately")
        Info "Next iteration starts immediately after current ends"
    }
    "fixed_delay" {
        $pacNode.SetAttribute("Type",    "FixedDelay")
        $pacNode.SetAttribute("Seconds", $PacingMinSec.ToString())
        Info "Fixed ${PacingMinSec}s delay between iterations"
    }
    "random_delay" {
        $pacNode.SetAttribute("Type",    "RandomDelay")
        $pacNode.SetAttribute("MinSec",  $PacingMinSec.ToString())
        $pacNode.SetAttribute("MaxSec",  $PacingMaxSec.ToString())
        Info "Random ${PacingMinSec}–${PacingMaxSec}s delay between iterations"
    }
    "fixed_from_iteration_start" {
        $pacNode.SetAttribute("Type",    "FixedFromStart")
        $pacNode.SetAttribute("Seconds", $PacingMinSec.ToString())
        Info "Fixed ${PacingMinSec}s from start of previous iteration"
    }
    "random_from_iteration_start" {
        $pacNode.SetAttribute("Type",   "RandomFromStart")
        $pacNode.SetAttribute("MinSec", $PacingMinSec.ToString())
        $pacNode.SetAttribute("MaxSec", $PacingMaxSec.ToString())
        Info "Random ${PacingMinSec}–${PacingMaxSec}s from start of previous iteration"
    }
}

# ────────────────────────────────────────────────────────────────
# 5. RUNTIME SETTINGS — Iterations
# ────────────────────────────────────────────────────────────────
if ($Iterations -gt 0) {
    Step "Iterations: $Iterations per VUser"
    $iterNode = EnsureNode $lrs $rtNode "Iterations"
    $iterNode.SetAttribute("Count",     $Iterations.ToString())
    $iterNode.SetAttribute("Unlimited", "false")
} else {
    Step "Iterations: run for full test duration"
    $iterNode = EnsureNode $lrs $rtNode "Iterations"
    $iterNode.SetAttribute("Unlimited", "true")
}

# ────────────────────────────────────────────────────────────────
# 6. RUNTIME SETTINGS — Browser Emulation
#    Mirrors: Runtime Settings → Browser Emulation
# ────────────────────────────────────────────────────────────────
Step "Browser emulation: $Browser"
$brwNode = EnsureNode $lrs $rtNode "BrowserEmulation"

$browserMap = @{
    "chrome"         = @{ UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"; Type = "Chrome" }
    "firefox"        = @{ UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"; Type = "Firefox" }
    "ie11"           = @{ UA = "Mozilla/5.0 (Windows NT 10.0; Trident/7.0; rv:11.0) like Gecko"; Type = "IE" }
    "mobile-android" = @{ UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36"; Type = "Chrome_Mobile" }
    "mobile-ios"     = @{ UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"; Type = "Safari_Mobile" }
    "none"           = @{ UA = ""; Type = "None" }
}

$bInfo = $browserMap[$Browser]
if ($bInfo) {
    $brwNode.SetAttribute("Type",      $bInfo.Type)
    $brwNode.SetAttribute("UserAgent", $bInfo.UA)
    Info "UA: $($bInfo.UA.Substring(0,[Math]::Min(60,$bInfo.UA.Length)))…"
}

# ────────────────────────────────────────────────────────────────
# 7. RUNTIME SETTINGS — Network Speed Simulation
#    Mirrors: Runtime Settings → Network → Speed Simulation
# ────────────────────────────────────────────────────────────────
Step "Network simulation: $NetworkSpeed"
$netNode = EnsureNode $lrs $rtNode "Network"

$networkMap = @{
    "unlimited"    = @{ Bandwidth = "0";       Name = "Unlimited" }
    "cable_10mbps" = @{ Bandwidth = "10240";   Name = "Cable (10Mbps)" }
    "dsl_2mbps"    = @{ Bandwidth = "2048";    Name = "DSL (2Mbps)" }
    "gprs_56kbps"  = @{ Bandwidth = "56";      Name = "GPRS (56Kbps)" }
    "modem_28kbps" = @{ Bandwidth = "28";      Name = "Modem (28.8Kbps)" }
}

$nInfo = $networkMap[$NetworkSpeed]
if ($nInfo) {
    $netNode.SetAttribute("SpeedSimulation", ($NetworkSpeed -ne "unlimited").ToString().ToLower())
    $netNode.SetAttribute("Bandwidth",       $nInfo.Bandwidth)
    $netNode.SetAttribute("ProfileName",     $nInfo.Name)
    Info "Bandwidth cap: $($nInfo.Name)"
}

# ────────────────────────────────────────────────────────────────
# 8. RUNTIME SETTINGS — Cache & Non-HTML Resources
#    Mirrors: Runtime Settings → Browser Emulation → Options
# ────────────────────────────────────────────────────────────────
Step "Cache: $($SimulateCache ? 'enabled' : 'disabled') | Non-HTML: $($DownloadNonHtml ? 'download' : 'skip')"
$brwNode.SetAttribute("SimulateCache",    $SimulateCache.ToString().ToLower())
$brwNode.SetAttribute("DownloadNonHtml",  $DownloadNonHtml.ToString().ToLower())

# ────────────────────────────────────────────────────────────────
# 9. RUNTIME SETTINGS — Logging
#    Mirrors: Runtime Settings → Log
# ────────────────────────────────────────────────────────────────
Step "Log level: $LogLevel"
$logNode = EnsureNode $lrs $rtNode "Log"

$logMap = @{
    "none"        = @{ Enable = "false"; SendMessages = "false"; DetailLevel = "0" }
    "errors_only" = @{ Enable = "true";  SendMessages = "true";  DetailLevel = "1" }
    "extended"    = @{ Enable = "true";  SendMessages = "true";  DetailLevel = "2" }
    "full"        = @{ Enable = "true";  SendMessages = "true";  DetailLevel = "3" }
}

$lInfo = $logMap[$LogLevel]
if ($lInfo) {
    $logNode.SetAttribute("Enable",          $lInfo.Enable)
    $logNode.SetAttribute("SendMessages",    $lInfo.SendMessages)
    $logNode.SetAttribute("DetailLevel",     $lInfo.DetailLevel)
    $logNode.SetAttribute("PrintLogToFile",  "true")
}

# ────────────────────────────────────────────────────────────────
# 10. RUNTIME SETTINGS — Error Handling
#    Mirrors: Runtime Settings → Miscellaneous → Error Handling
# ────────────────────────────────────────────────────────────────
Step "On error: $OnError"
$errNode = EnsureNode $lrs $rtNode "ErrorHandling"

$errMap = @{
    "continue_to_next_iteration" = "ContinueNextIteration"
    "continue_to_next_action"    = "ContinueNextAction"
    "stop_vuser"                 = "StopVUser"
    "stop_test"                  = "StopTest"
}
$errNode.SetAttribute("OnError", $errMap[$OnError])

# ────────────────────────────────────────────────────────────────
# 11. Target environment URL
# ────────────────────────────────────────────────────────────────
Step "Setting target URL for environment: $TargetEnv"
$urlMap = @{
    dev        = $env:TARGET_URL_DEV
    staging    = $env:TARGET_URL_STAGING
    production = $env:TARGET_URL_PROD
}
$baseUrl = $urlMap[$TargetEnv]
if (-not $baseUrl) { throw "Missing secret TARGET_URL_$($TargetEnv.ToUpper())" }

$urlNode = $lrs.SelectSingleNode("//RuntimeSettings/WebUrl")
if ($urlNode) { $urlNode.InnerText = $baseUrl }
Info "Base URL: $baseUrl"

# ────────────────────────────────────────────────────────────────
# 12. License server
# ────────────────────────────────────────────────────────────────
Step "License server: $LicenseServer"
$licNode = $lrs.SelectSingleNode("//LicenseServer")
if ($licNode) { $licNode.InnerText = $LicenseServer }

# ────────────────────────────────────────────────────────────────
# 13. Per-user credential injection (parameter file)
# ────────────────────────────────────────────────────────────────
Step "Injecting credentials"
$credRows = @()
for ($i = 1; $i -le [Math]::Min($VUsers, 100); $i++) {
    $u = [System.Environment]::GetEnvironmentVariable("LR_USER_${i}_USERNAME")
    $p = [System.Environment]::GetEnvironmentVariable("LR_USER_${i}_PASSWORD")
    if ($u -and $p) { $credRows += "$u,$p" }
}
if ($credRows.Count -eq 0) {
    if (-not $env:LR_SCRIPT_USERNAME) { throw "No credentials: set LR_SCRIPT_USERNAME or LR_USER_N_* secrets" }
    Write-Warning "No per-user creds found — using shared service account"
    $credRows = @("$env:LR_SCRIPT_USERNAME,$env:LR_SCRIPT_PASSWORD")
}
Info "Credential pool: $($credRows.Count) entries"

$paramDir = Split-Path $ParameterFile -Parent
if (-not (Test-Path $paramDir)) { New-Item -ItemType Directory -Path $paramDir -Force | Out-Null }
"username,password`n" + ($credRows -join "`n") | Set-Content $ParameterFile -Encoding UTF8

$paramFileNode = $lrs.SelectSingleNode("//ParameterFile")
if ($paramFileNode) { $paramFileNode.InnerText = (Resolve-Path $ParameterFile).Path }

# ────────────────────────────────────────────────────────────────
# 14. Save patched scenario
# ────────────────────────────────────────────────────────────────
$patchedFile = $ScenarioFile -replace '\.lrs$', '_patched.lrs'
$lrs.Save($patchedFile)
Step "Saved patched scenario → $patchedFile"

# ────────────────────────────────────────────────────────────────
# 15. Validation (optional — needs LR installed)
# ────────────────────────────────────────────────────────────────
$lrBatch = "$env:LR_INSTALL_DIR\bin\lr_batch.exe"
if (Test-Path $lrBatch) {
    Step "Validating patched scenario..."
    $result = & $lrBatch -Validate -Scenario $patchedFile 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Scenario validation failed:`n$result" }
    Info "Validation passed ✅"
} else {
    Write-Warning "lr_batch.exe not found — skipping validation (non-LR runner)"
}

Write-Host "`n✅ Web HTTP scenario configured successfully" -ForegroundColor Green

# Print applied settings summary
Write-Host "`n── Applied Settings ────────────────────────────────" -ForegroundColor DarkGray
Write-Host "  Scheduler : $SchedulerMode | VUsers: $VUsers | Ramp: ${RampUpMin}m | Steady: ${SteadyMin}m | Down: ${RampDownMin}m"
Write-Host "  ThinkTime : $ThinkTimeMode ($ThinkTimeValue)"
Write-Host "  Pacing    : $PacingMode (${PacingMinSec}s–${PacingMaxSec}s)"
Write-Host "  Browser   : $Browser | Network: $NetworkSpeed | Cache: $SimulateCache"
Write-Host "  Logging   : $LogLevel | OnError: $OnError"
Write-Host "────────────────────────────────────────────────────" -ForegroundColor DarkGray
