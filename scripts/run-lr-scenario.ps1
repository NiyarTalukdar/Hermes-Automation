#Requires -Version 5.1
<#
.SYNOPSIS
    run-lr-scenario.ps1 — Executes a LoadRunner scenario via lr_batch.exe
    and monitors until completion, timeout, or failure.
#>

param(
    [Parameter(Mandatory)] [string] $ScenarioFile,
    [Parameter(Mandatory)] [string] $ResultsPath,
    [int]    $TimeoutMinutes    = 60,
    [bool]   $CaptureScreenshots = $false,
    [switch] $Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Step([string]$m) { Write-Host "  ➤ $m" -ForegroundColor Cyan }
function Info([string]$m) { Write-Host "    $m"  -ForegroundColor Gray }

$lrBin = "$env:LR_INSTALL_DIR\bin"
$lrBatch = "$lrBin\lr_batch.exe"

if (-not (Test-Path $lrBatch)) {
    throw "lr_batch.exe not found at $lrBatch. Set LR_INSTALL_DIR env var on the runner."
}

Step "Preparing results directory: $ResultsPath"
New-Item -ItemType Directory -Path $ResultsPath -Force | Out-Null

# Build lr_batch arguments
# Docs: https://admhelp.microfocus.com/lr/en/latest/help/WebHelp/Content/Controller/lr_batch.htm
$lrArgs = @(
    "-Run",
    "-Scenario",      $ScenarioFile,
    "-ResultsPath",   $ResultsPath,
    "-Timeout",       ($TimeoutMinutes * 60).ToString()
)

if ($CaptureScreenshots) { $lrArgs += "-CaptureScreenshots" }
if ($Verbose)            { $lrArgs += "-Verbose" }

Step "Launching lr_batch.exe..."
Info "Scenario  : $ScenarioFile"
Info "Results   : $ResultsPath"
Info "Timeout   : ${TimeoutMinutes}m"

$startTime = Get-Date
$proc = Start-Process -FilePath $lrBatch -ArgumentList $lrArgs `
        -NoNewWindow -PassThru -RedirectStandardOutput "$ResultsPath\lr_batch_stdout.log" `
        -RedirectStandardError  "$ResultsPath\lr_batch_stderr.log"

# ── Poll until done or timeout ─────────────────────────────────
$timeoutSec = $TimeoutMinutes * 60
$pollInterval = 30

while (-not $proc.HasExited) {
    $elapsed = (Get-Date) - $startTime
    if ($elapsed.TotalSeconds -gt $timeoutSec) {
        $proc.Kill()
        throw "❌ Test timed out after ${TimeoutMinutes}m — scenario killed."
    }
    $elapsedMin = [Math]::Round($elapsed.TotalMinutes, 1)
    Write-Host "    ⏱  Running… ${elapsedMin}m elapsed (timeout: ${TimeoutMinutes}m)" -ForegroundColor DarkGray
    Start-Sleep -Seconds $pollInterval
}

$elapsed = (Get-Date) - $startTime
$exitCode = $proc.ExitCode

Step "lr_batch.exe exited — code $exitCode in $([Math]::Round($elapsed.TotalMinutes,1))m"

# ── Parse exit code ────────────────────────────────────────────
# lr_batch exit codes:
#   0  = Success (all SLAs passed)
#   1  = Run completed but SLA failures detected
#   2  = Run aborted / error
#   3  = Scenario could not be opened
switch ($exitCode) {
    0 { Write-Host "`n✅ Test PASSED — all SLAs met" -ForegroundColor Green }
    1 {
        Write-Host "`n⚠️  Test completed but SLA violations detected" -ForegroundColor Yellow
        # Don't throw — let validate-sla.ps1 handle the detailed SLA check
    }
    2 { throw "❌ lr_batch reported a run error (exit 2). Check $ResultsPath\lr_batch_stderr.log" }
    3 { throw "❌ Scenario file could not be opened (exit 3). Check path: $ScenarioFile" }
    default { throw "❌ Unexpected lr_batch exit code: $exitCode" }
}

# ── Export results to CSV + HTML ───────────────────────────────
Step "Exporting results..."
$analysisExe = "$lrBin\lr_analysis.exe"
if (Test-Path $analysisExe) {
    & $analysisExe `
        -ResultsPath $ResultsPath `
        -ExportCSV   "$ResultsPath\results.csv" `
        -ExportHTML  "$ResultsPath\report.html" `
        -ExportXML   "$ResultsPath\results.xml"
    Info "Exported: results.csv, report.html, results.xml"
} else {
    Write-Warning "lr_analysis.exe not found — raw results only in $ResultsPath"
}

# ── Write summary.json for downstream scripts ─────────────────
Step "Generating summary.json..."
$csvFile = "$ResultsPath\results.csv"
$summary = @{
    run_id              = $env:GITHUB_RUN_ID ?? "local"
    scenario_file       = $ScenarioFile
    duration_minutes    = [Math]::Round($elapsed.TotalMinutes, 2)
    exit_code           = $exitCode
    avg_response_time   = 0
    max_response_time   = 0
    p90_response_time   = 0
    p95_response_time   = 0
    p99_response_time   = 0
    error_count         = 0
    total_transactions  = 0
    tps                 = 0.0
    error_rate          = 0.0
    sla_passed          = ($exitCode -eq 0)
}

if (Test-Path $csvFile) {
    $rows = Import-Csv $csvFile
    if ($rows.Count -gt 0) {
        $times  = $rows | Where-Object { $_.response_time -match '^\d' } | ForEach-Object { [double]$_.response_time }
        $errors = $rows | Where-Object { $_.errors -match '^\d' }        | ForEach-Object { [int]$_.errors }

        if ($times.Count -gt 0) {
            $sorted = $times | Sort-Object
            $summary.avg_response_time  = [Math]::Round(($times | Measure-Object -Average).Average, 2)
            $summary.max_response_time  = ($times | Measure-Object -Maximum).Maximum
            $summary.p90_response_time  = $sorted[[Math]::Floor($sorted.Count * 0.90)]
            $summary.p95_response_time  = $sorted[[Math]::Floor($sorted.Count * 0.95)]
            $summary.p99_response_time  = $sorted[[Math]::Floor($sorted.Count * 0.99)]
        }
        $summary.error_count       = ($errors | Measure-Object -Sum).Sum ?? 0
        $summary.total_transactions = $rows.Count
        $summary.tps                = [Math]::Round($rows.Count / ($elapsed.TotalSeconds), 2)
        if ($rows.Count -gt 0) {
            $summary.error_rate = [Math]::Round($summary.error_count / $rows.Count * 100, 3)
        }
    }
}

$summary | ConvertTo-Json -Depth 3 | Set-Content "$ResultsPath\summary.json" -Encoding UTF8
Info "summary.json written"

Write-Host "`n── Results Summary ──────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "  Avg RT  : $($summary.avg_response_time)ms"
Write-Host "  P95 RT  : $($summary.p95_response_time)ms"
Write-Host "  Errors  : $($summary.error_count) ($($summary.error_rate)%)"
Write-Host "  TPH     : $($summary.tph)"
Write-Host "  TPS     : $($summary.tps)  (= TPH ÷ 3600)"
Write-Host "  SLA     : $($summary.sla_passed ? '✅ PASS' : '⚠️ CHECK')"
Write-Host "────────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
