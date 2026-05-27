#Requires -Version 5.1
<#
.SYNOPSIS
    validate-sla.ps1 — Reads summary.json from LR results and compares
    against SLA thresholds defined in a sla-*.json config file.
    Exits with code 1 (fails the GitHub Actions step) if any FAIL threshold
    is breached. Prints warnings for WARN thresholds.
#>

param(
    [Parameter(Mandatory)] [string] $ResultsPath,
    [Parameter(Mandatory)] [string] $SlaConfig,
    [Parameter(Mandatory)] [string] $Protocol    # API | WEB
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Pass([string]$m)  { Write-Host "  ✅ $m" -ForegroundColor Green  }
function Warn([string]$m)  { Write-Host "  ⚠️  $m" -ForegroundColor Yellow }
function Fail([string]$m)  { Write-Host "  ❌ $m" -ForegroundColor Red    }
function Info([string]$m)  { Write-Host "     $m"  -ForegroundColor Gray   }

# ── Load results ───────────────────────────────────────────────
$summaryFile = "$ResultsPath\summary.json"
if (-not (Test-Path $summaryFile)) { throw "summary.json not found in $ResultsPath" }
$results = Get-Content $summaryFile | ConvertFrom-Json

# ── Load SLA config ────────────────────────────────────────────
if (-not (Test-Path $SlaConfig)) {
    Write-Warning "SLA config not found: $SlaConfig — skipping SLA validation"
    exit 0
}
$sla = Get-Content $SlaConfig | ConvertFrom-Json

Write-Host "`n── SLA Validation [$Protocol] ─────────────────────────────────────" -ForegroundColor Cyan
Write-Host "   Results : $summaryFile"
Write-Host "   SLA     : $SlaConfig"
Write-Host ""

$violations = 0
$warnings   = 0

function CheckThreshold([string]$label, [double]$actual, $threshold, [bool]$lowerIsBetter = $true) {
    if ($null -eq $threshold) { return }

    if ($lowerIsBetter) {
        # Warn / fail when actual EXCEEDS threshold
        if ($threshold.PSObject.Properties['fail'] -and $actual -gt $threshold.fail) {
            Fail  "$label = $actual (FAIL threshold: $($threshold.fail))"
            $script:violations++
        } elseif ($threshold.PSObject.Properties['warn'] -and $actual -gt $threshold.warn) {
            Warn  "$label = $actual (WARN threshold: $($threshold.warn))"
            $script:warnings++
        } else {
            Pass  "$label = $actual (limit: $($threshold.fail ?? $threshold.warn))"
        }
    } else {
        # Warn / fail when actual FALLS BELOW threshold (e.g. TPS)
        if ($threshold.PSObject.Properties['fail_below'] -and $actual -lt $threshold.fail_below) {
            Fail  "$label = $actual (FAIL below: $($threshold.fail_below))"
            $script:violations++
        } elseif ($threshold.PSObject.Properties['warn_below'] -and $actual -lt $threshold.warn_below) {
            Warn  "$label = $actual (WARN below: $($threshold.warn_below))"
            $script:warnings++
        } else {
            Pass  "$label = $actual (min: $($threshold.fail_below ?? $threshold.warn_below))"
        }
    }
}

# ── Global thresholds ──────────────────────────────────────────
$t = $sla.thresholds
if ($t) {
    CheckThreshold "Avg Response Time (ms)"  $results.avg_response_time  $t.avg_response_time_ms
    CheckThreshold "P90 Response Time (ms)"  $results.p90_response_time  $t.p90_response_time_ms
    CheckThreshold "P95 Response Time (ms)"  $results.p95_response_time  $t.p95_response_time_ms
    CheckThreshold "P99 Response Time (ms)"  $results.p99_response_time  $t.p99_response_time_ms
    CheckThreshold "Max Response Time (ms)"  $results.max_response_time  $t.max_response_time_ms
    CheckThreshold "Error Rate (%)"          $results.error_rate         $t.error_rate_percent
    CheckThreshold "Throughput (TPS)"        $results.tps                $t.throughput_tps       $false
}

# ── Per-transaction thresholds (if present in SLA config) ──────
if ($sla.transactions) {
    Write-Host "`n   Per-Transaction SLAs:" -ForegroundColor Gray
    # Load per-transaction data if available
    $txFile = "$ResultsPath\transactions.json"
    if (Test-Path $txFile) {
        $txData = Get-Content $txFile | ConvertFrom-Json
        foreach ($txSla in $sla.transactions) {
            $txResult = $txData | Where-Object { $_.name -eq $txSla.name }
            if ($txResult) {
                CheckThreshold "  [$($txSla.name)] Avg RT (ms)" $txResult.avg_rt $txSla.avg_response_time_ms
                CheckThreshold "  [$($txSla.name)] Error %"     $txResult.error_rate $txSla.error_rate_percent
            } else {
                Write-Warning "  Transaction '$($txSla.name)' not found in results"
            }
        }
    } else {
        Info "transactions.json not found — skipping per-transaction SLA checks"
    }
}

# ── Summary ────────────────────────────────────────────────────
Write-Host ""
Write-Host "── SLA Result ──────────────────────────────────────────────────" -ForegroundColor Cyan
if ($violations -gt 0) {
    Fail "$violations FAIL violation(s), $warnings warning(s)"
    Write-Host ""
    # Write to GitHub step summary
    "## ❌ SLA Validation FAILED`n`n$violations threshold(s) breached, $warnings warning(s)" |
        Add-Content $env:GITHUB_STEP_SUMMARY
    exit 1
} elseif ($warnings -gt 0) {
    Warn "$warnings warning(s) — no FAIL violations"
    "## ⚠️ SLA Validation PASSED with $warnings warning(s)" | Add-Content $env:GITHUB_STEP_SUMMARY
    exit 0
} else {
    Pass "All SLA thresholds met"
    "## ✅ SLA Validation PASSED — all thresholds met" | Add-Content $env:GITHUB_STEP_SUMMARY
    exit 0
}
