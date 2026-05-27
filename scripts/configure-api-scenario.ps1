#Requires -Version 5.1
<#
.SYNOPSIS
    configure-api-scenario.ps1
    Patches a LoadRunner API protocol .lrs scenario file with all runtime
    settings equivalent to what you'd configure manually in:
      - MicroFocus Performance Centre → Scenario Designer
      - LoadRunner Controller → Scenario → Runtime Settings

.DESCRIPTION
    Covers:
      Scenario Scheduling   — real_world / goal_oriented / basic
      Think Time            — as_recorded / ignore / multiply / random_percentage / fixed_seconds
      Iteration Pacing      — immediately / fixed_delay / random_delay / fixed_from_start / random_from_start
      HTTP Connection       — timeout / keep-alive / max connections per host / SSL version
      Logging               — none / errors_only / extended / full
      Error Handling        — continue_iteration / continue_action / stop_vuser / stop_test
      Credential injection  — per-user pool or shared service account
#>

param(
    [Parameter(Mandatory)] [string] $ScenarioFile,
    [Parameter(Mandatory)] [string] $SchedulerMode,
    [Parameter(Mandatory)] [int]    $VUsers,
    [Parameter(Mandatory)] [int]    $RampUpMin,
    [Parameter(Mandatory)] [int]    $SteadyMin,
    [int]    $RampDownMin     = 2,
    [string] $GoalMetric      = "transactions_per_second",
    [string] $GoalValue       = "30",
    [string] $GoalMaxVUsers   = "200",
    [string] $ThinkTimeMode   = "ignore",
    [double] $ThinkTimeValue  = 1.0,
    [int]    $ThinkTimeMinPct = 50,
    [int]    $ThinkTimeMaxPct = 150,
    [string] $PacingMode      = "immediately",
    [int]    $PacingMinSec    = 0,
    [int]    $PacingMaxSec    = 5,
    [int]    $Iterations      = 0,
    [int]    $ConnTimeoutSec  = 30,
    [int]    $ReqTimeoutSec   = 120,
    [int]    $MaxConnections  = 50,
    [bool]   $KeepAlive       = $true,
    [string] $SslVersion      = "auto",
    [string] $LogLevel        = "errors_only",
    [string] $OnError         = "continue_to_next_iteration",
    [Parameter(Mandatory)] [string] $TargetEnv,
    [Parameter(Mandatory)] [string] $LicenseServer,
    [string] $ParameterFile   = "configs\params-api.dat"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Step([string]$msg) { Write-Host "  ➤ $msg" -ForegroundColor Cyan }
function Info([string]$msg) { Write-Host "    $msg"  -ForegroundColor Gray }

function EnsureNode([xml]$doc, $parent, [string]$name) {
    $n = $parent.SelectSingleNode($name)
    if (-not $n) { $n = $doc.CreateElement($name); $parent.AppendChild($n) | Out-Null }
    return $n
}

# ────────────────────────────────────────────────────────────────
# 1. Load .lrs XML
# ────────────────────────────────────────────────────────────────
Step "Loading scenario: $ScenarioFile"
if (-not (Test-Path $ScenarioFile)) { throw "Scenario file not found: $ScenarioFile" }
[xml]$lrs = Get-Content $ScenarioFile -Encoding UTF8

# ────────────────────────────────────────────────────────────────
# 2. SCHEDULER — mirrors PC Scenario Designer
# ────────────────────────────────────────────────────────────────
Step "Scheduler: $SchedulerMode"
$sched = $lrs.SelectSingleNode("//Scheduler")

switch ($SchedulerMode) {
    "real_world" {
        Info "Ramp ${RampUpMin}m | Steady ${SteadyMin}m | RampDown ${RampDownMin}m"
        if ($sched) {
            $sched.SetAttribute("Mode",         "RealWorld")
            $sched.SetAttribute("Duration",     ($SteadyMin   * 60).ToString())
            $sched.SetAttribute("RampUpTime",   ($RampUpMin   * 60).ToString())
            $sched.SetAttribute("RampDownTime", ($RampDownMin * 60).ToString())
        }
        $lrs.SelectNodes("//Group") | ForEach-Object { $_.SetAttribute("VUsers", $VUsers) }
    }
    "goal_oriented" {
        Info "Goal: $GoalValue $GoalMetric (max $GoalMaxVUsers VUsers)"
        if ($sched) {
            $sched.SetAttribute("Mode",       "GoalOriented")
            $sched.SetAttribute("GoalType",   $GoalMetric)
            $sched.SetAttribute("GoalValue",  $GoalValue)
            $sched.SetAttribute("MaxVUsers",  $GoalMaxVUsers)
            $sched.SetAttribute("Duration",   ($SteadyMin * 60).ToString())
            $sched.SetAttribute("RampUpTime", ($RampUpMin * 60).ToString())
        }
        $lrs.SelectNodes("//Group") | ForEach-Object { $_.SetAttribute("VUsers", $GoalMaxVUsers) }
    }
    "basic" {
        Info "$VUsers VUsers for ${SteadyMin}m"
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
# ────────────────────────────────────────────────────────────────
Step "Think time: $ThinkTimeMode"
$rtNode = $lrs.SelectSingleNode("//RuntimeSettings")
if (-not $rtNode) {
    $rtNode = $lrs.CreateElement("RuntimeSettings")
    $lrs.DocumentElement.AppendChild($rtNode) | Out-Null
}
$ttNode = EnsureNode $lrs $rtNode "ThinkTime"

switch ($ThinkTimeMode) {
    "as_recorded"       { $ttNode.SetAttribute("Type","AsRecorded"); $ttNode.SetAttribute("Factor","1.0") }
    "ignore"            { $ttNode.SetAttribute("Type","Ignore") }
    "multiply"          { $ttNode.SetAttribute("Type","Multiply");   $ttNode.SetAttribute("Factor",$ThinkTimeValue.ToString()) }
    "random_percentage" { $ttNode.SetAttribute("Type","Random");     $ttNode.SetAttribute("MinPct",$ThinkTimeMinPct.ToString()); $ttNode.SetAttribute("MaxPct",$ThinkTimeMaxPct.ToString()) }
    "fixed_seconds"     { $ttNode.SetAttribute("Type","Fixed");      $ttNode.SetAttribute("Seconds",$ThinkTimeValue.ToString()) }
}

# ────────────────────────────────────────────────────────────────
# 4. RUNTIME SETTINGS — Iteration Pacing
# ────────────────────────────────────────────────────────────────
Step "Pacing: $PacingMode"
$pacNode = EnsureNode $lrs $rtNode "Pacing"

switch ($PacingMode) {
    "immediately"                 { $pacNode.SetAttribute("Type","Immediately") }
    "fixed_delay"                 { $pacNode.SetAttribute("Type","FixedDelay");    $pacNode.SetAttribute("Seconds",$PacingMinSec.ToString()) }
    "random_delay"                { $pacNode.SetAttribute("Type","RandomDelay");   $pacNode.SetAttribute("MinSec",$PacingMinSec.ToString()); $pacNode.SetAttribute("MaxSec",$PacingMaxSec.ToString()) }
    "fixed_from_iteration_start"  { $pacNode.SetAttribute("Type","FixedFromStart");$pacNode.SetAttribute("Seconds",$PacingMinSec.ToString()) }
    "random_from_iteration_start" { $pacNode.SetAttribute("Type","RandomFromStart");$pacNode.SetAttribute("MinSec",$PacingMinSec.ToString()); $pacNode.SetAttribute("MaxSec",$PacingMaxSec.ToString()) }
}

# ────────────────────────────────────────────────────────────────
# 5. RUNTIME SETTINGS — Iterations
# ────────────────────────────────────────────────────────────────
$iterNode = EnsureNode $lrs $rtNode "Iterations"
if ($Iterations -gt 0) {
    Step "Iterations: $Iterations per VUser"
    $iterNode.SetAttribute("Count","$Iterations"); $iterNode.SetAttribute("Unlimited","false")
} else {
    Step "Iterations: run for full duration"
    $iterNode.SetAttribute("Unlimited","true")
}

# ────────────────────────────────────────────────────────────────
# 6. RUNTIME SETTINGS — HTTP Connection Properties (API-specific)
#    Mirrors: Runtime Settings → Internet Protocol → HTTP Properties
# ────────────────────────────────────────────────────────────────
Step "HTTP: conn=${ConnTimeoutSec}s | req=${ReqTimeoutSec}s | maxConns=$MaxConnections | keepAlive=$KeepAlive | ssl=$SslVersion"
$httpNode = EnsureNode $lrs $rtNode "HttpProperties"
$httpNode.SetAttribute("ConnectionTimeout",     $ConnTimeoutSec.ToString())
$httpNode.SetAttribute("RequestTimeout",        $ReqTimeoutSec.ToString())
$httpNode.SetAttribute("MaxConnectionsPerHost", $MaxConnections.ToString())
$httpNode.SetAttribute("KeepAlive",             $KeepAlive.ToString().ToLower())

$sslMap = @{ "auto" = "0"; "tls1_2" = "3"; "tls1_3" = "4" }
$httpNode.SetAttribute("SslVersion", ($sslMap.ContainsKey($SslVersion) ? $sslMap[$SslVersion] : "0"))

# ────────────────────────────────────────────────────────────────
# 7. RUNTIME SETTINGS — Logging
# ────────────────────────────────────────────────────────────────
Step "Log level: $LogLevel"
$logNode = EnsureNode $lrs $rtNode "Log"
$logMap = @{
    "none"        = @{Enable="false";Send="false";Detail="0"}
    "errors_only" = @{Enable="true"; Send="true"; Detail="1"}
    "extended"    = @{Enable="true"; Send="true"; Detail="2"}
    "full"        = @{Enable="true"; Send="true"; Detail="3"}
}
$l = $logMap[$LogLevel]
$logNode.SetAttribute("Enable",$l.Enable); $logNode.SetAttribute("SendMessages",$l.Send)
$logNode.SetAttribute("DetailLevel",$l.Detail); $logNode.SetAttribute("PrintLogToFile","true")

# ────────────────────────────────────────────────────────────────
# 8. RUNTIME SETTINGS — Error Handling
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
# 9. Target environment URL
# ────────────────────────────────────────────────────────────────
Step "Target: $TargetEnv"
$urlMap = @{ dev=$env:TARGET_URL_DEV; staging=$env:TARGET_URL_STAGING; production=$env:TARGET_URL_PROD }
$baseUrl = $urlMap[$TargetEnv]
if (-not $baseUrl) { throw "Missing secret TARGET_URL_$($TargetEnv.ToUpper())" }
$urlNode = $lrs.SelectSingleNode("//RuntimeSettings/WebUrl")
if ($urlNode) { $urlNode.InnerText = $baseUrl }
Info "Base URL → $baseUrl"

# ────────────────────────────────────────────────────────────────
# 10. License server
# ────────────────────────────────────────────────────────────────
$licNode = $lrs.SelectSingleNode("//LicenseServer")
if ($licNode) { $licNode.InnerText = $LicenseServer }

# ────────────────────────────────────────────────────────────────
# 11. Per-user credential injection
# ────────────────────────────────────────────────────────────────
Step "Injecting credentials"
$credRows = @()
for ($i = 1; $i -le [Math]::Min($VUsers, 100); $i++) {
    $u = [System.Environment]::GetEnvironmentVariable("LR_USER_${i}_USERNAME")
    $p = [System.Environment]::GetEnvironmentVariable("LR_USER_${i}_PASSWORD")
    if ($u -and $p) { $credRows += "$u,$p" }
}
if ($credRows.Count -eq 0) {
    if (-not $env:LR_SCRIPT_USERNAME) { throw "No credentials — set LR_SCRIPT_USERNAME or LR_USER_N_* secrets" }
    Write-Warning "No per-user creds — using shared service account"
    $credRows = @("$env:LR_SCRIPT_USERNAME,$env:LR_SCRIPT_PASSWORD")
}
Info "Credential pool: $($credRows.Count) entries"

$paramDir = Split-Path $ParameterFile -Parent
if (-not (Test-Path $paramDir)) { New-Item -ItemType Directory -Path $paramDir -Force | Out-Null }
"username,password`n" + ($credRows -join "`n") | Set-Content $ParameterFile -Encoding UTF8
$paramFileNode = $lrs.SelectSingleNode("//ParameterFile")
if ($paramFileNode) { $paramFileNode.InnerText = (Resolve-Path $ParameterFile).Path }

# ────────────────────────────────────────────────────────────────
# 12. Save + validate
# ────────────────────────────────────────────────────────────────
$patchedFile = $ScenarioFile -replace '\.lrs$', '_patched.lrs'
$lrs.Save($patchedFile)
Step "Saved → $patchedFile"

$lrBatch = "$env:LR_INSTALL_DIR\bin\lr_batch.exe"
if (Test-Path $lrBatch) {
    Step "Validating..."
    $result = & $lrBatch -Validate -Scenario $patchedFile 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Validation failed:`n$result" }
    Info "✅ Passed"
} else {
    Write-Warning "lr_batch.exe not found — skipping validation"
}

Write-Host "`n✅ API scenario configured" -ForegroundColor Green
Write-Host "── Scheduler: $SchedulerMode | VUsers: $VUsers | Ramp: ${RampUpMin}m | Steady: ${SteadyMin}m | Down: ${RampDownMin}m"
Write-Host "── ThinkTime: $ThinkTimeMode | Pacing: $PacingMode | HTTP keepAlive: $KeepAlive | SSL: $SslVersion"
Write-Host "── Logging: $LogLevel | OnError: $OnError"
