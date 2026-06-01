#Requires -Version 5.1
<#
.SYNOPSIS
    validate-sla.ps1 — Validates LoadRunner results against SLA thresholds.

.DESCRIPTION
    Reads summary.json + transactions.json from the results folder and compares
    every metric against thresholds defined in the sla-*.json config file.

    Breach behaviour is controlled by -BreachAction:
      log_only      — Print violations to log; job always exits 0 (test ran to completion)
      warn_and_log  — Print violations; job exits 0 but step is annotated as warning
      fail_job      — Print violations; job exits 1 (fails the GitHub Actions step)

    The test itself is NEVER stopped by this script — it runs post-test on results.
    To stop the LR test mid-run on SLA breach, configure LR Controller SLA actions
    inside the .lrs scenario file (outside scope of this script).
#>

param(
    [Parameter(Mandatory)] [string] $ResultsPath,
    [Parameter(Mandatory)] [string] $SlaConfig,
    [Parameter(Mandatory)] [string] $Protocol,          # API | WEB
    [string] $BreachAction = "log_only"                 # log_only | warn_and_log | fail_job
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── Logging helpers ─────────────────────────────────────────────────────────
function Pass([string]$m)  { Write-Host "  ✅ PASS  $m" -ForegroundColor Green  }
function Warn([string]$m)  { Write-Host "  ⚠️  WARN  $m" -ForegroundColor Yellow }
function Breach([string]$m){ Write-Host "  🚨 BREACH $m" -ForegroundColor Red   }
function Info([string]$m)  { Write-Host "     $m"         -ForegroundColor Gray  }
function Section([string]$m){ Write-Host "`n── $m" -ForegroundColor Cyan }

# ── Load results ────────────────────────────────────────────────────────────
$summaryFile = Join-Path $ResultsPath "summary.json"
if (-not (Test-Path $summaryFile)) {
    Write-Warning "summary.json not found in $ResultsPath — skipping SLA validation"
    exit 0
}
$results = Get-Content $summaryFile -Raw | ConvertFrom-Json

# ── Load SLA config ─────────────────────────────────────────────────────────
if (-not (Test-Path $SlaConfig)) {
    Write-Warning "SLA config not found: $SlaConfig — skipping validation"
    exit 0
}
$sla = Get-Content $SlaConfig -Raw | ConvertFrom-Json

Section "SLA Validation · Protocol: $Protocol · Breach action: $BreachAction"
Info "Results  : $summaryFile"
Info "SLA file : $SlaConfig"

# ── Violation tracking ──────────────────────────────────────────────────────
$breaches  = [System.Collections.Generic.List[string]]::new()
$warnings  = [System.Collections.Generic.List[string]]::new()
$breachLog = [System.Collections.Generic.List[hashtable]]::new()  # for JSON export

function CheckThreshold {
    param(
        [string] $Label,
        [double] $Actual,
        $Threshold,
        [bool]   $LowerIsBetter = $true
    )
    if ($null -eq $Threshold) { return }

    $warnVal = if ($LowerIsBetter) { $Threshold.warn }        else { $Threshold.warn_below }
    $failVal = if ($LowerIsBetter) { $Threshold.fail }        else { $Threshold.fail_below }
    $isBreach = $false; $isWarn = $false

    if ($LowerIsBetter) {
        if ($null -ne $failVal -and $Actual -gt $failVal) { $isBreach = $true }
        elseif ($null -ne $warnVal -and $Actual -gt $warnVal) { $isWarn = $true }
    } else {
        if ($null -ne $failVal -and $Actual -lt $failVal) { $isBreach = $true }
        elseif ($null -ne $warnVal -and $Actual -lt $warnVal) { $isWarn = $true }
    }

    $limit = if ($LowerIsBetter) { $failVal ?? $warnVal } else { $failVal ?? $warnVal }

    if ($isBreach) {
        Breach "$Label = $Actual  (threshold: $limit)"
        $script:breaches.Add("$Label = $Actual (threshold: $limit)")
        $script:breachLog.Add(@{
            metric    = $Label
            actual    = $Actual
            threshold = $limit
            severity  = "BREACH"
            protocol  = $Protocol
        })
    } elseif ($isWarn) {
        Warn "$Label = $Actual  (warn threshold: $warnVal)"
        $script:warnings.Add("$Label = $Actual (warn: $warnVal)")
        $script:breachLog.Add(@{
            metric    = $Label
            actual    = $Actual
            threshold = $warnVal
            severity  = "WARN"
            protocol  = $Protocol
        })
    } else {
        Pass "$Label = $Actual  (limit: $limit)"
    }
}

# ── Global metric checks ────────────────────────────────────────────────────
Section "Global Thresholds"
$t = $sla.thresholds
if ($t) {
    CheckThreshold "Avg Response Time (ms)"  $results.avg_response_time  $t.avg_response_time_ms
    CheckThreshold "P90 Response Time (ms)"  $results.p90_response_time  $t.p90_response_time_ms
    CheckThreshold "P95 Response Time (ms)"  $results.p95_response_time  $t.p95_response_time_ms
    CheckThreshold "P99 Response Time (ms)"  $results.p99_response_time  $t.p99_response_time_ms
    CheckThreshold "Max Response Time (ms)"  $results.max_response_time  $t.max_response_time_ms
    CheckThreshold "Error Rate (%)"          $results.error_rate         $t.error_rate_percent
    CheckThreshold "Throughput (TPS)"        $results.tps                $t.throughput_tps        $false
}

# ── Per-transaction checks ──────────────────────────────────────────────────
$txFile = Join-Path $ResultsPath "transactions.json"
if ($sla.transactions -and (Test-Path $txFile)) {
    Section "Per-Transaction Thresholds"
    $txData = Get-Content $txFile -Raw | ConvertFrom-Json
    foreach ($txSla in $sla.transactions) {
        $txResult = $txData | Where-Object { $_.name -eq $txSla.name }
        if ($txResult) {
            CheckThreshold "[$($txSla.name)] Avg RT (ms)"  $txResult.avg_rt     $txSla.avg_response_time_ms
            CheckThreshold "[$($txSla.name)] P95 RT (ms)"  $txResult.p95_rt     $txSla.p95_response_time_ms
            CheckThreshold "[$($txSla.name)] Error %"      $txResult.error_rate $txSla.error_rate_percent
        } else {
            Write-Warning "Transaction '$($txSla.name)' not found in results"
        }
    }
} elseif ($sla.transactions) {
    Info "transactions.json not found — skipping per-transaction checks"
}

# ── Export breach log as JSON (always — used by dashboard + APM) ────────────
$breachLogPath = Join-Path $ResultsPath "sla-violations.json"
$logObj = @{
    timestamp      = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    protocol       = $Protocol
    breach_action  = $BreachAction
    total_breaches = $breaches.Count
    total_warnings = $warnings.Count
    sla_passed     = ($breaches.Count -eq 0)
    violations     = $breachLog
}
$logObj | ConvertTo-Json -Depth 4 | Set-Content $breachLogPath -Encoding UTF8
Info "Breach log written → $breachLogPath"

# ── Update summary.json with SLA result ────────────────────────────────────
$results.sla_passed         = ($breaches.Count -eq 0)
$results.sla_breach_count   = $breaches.Count
$results.sla_warning_count  = $warnings.Count
$results | ConvertTo-Json -Depth 4 | Set-Content $summaryFile -Encoding UTF8

# ── GitHub Step Summary ─────────────────────────────────────────────────────
$summaryLines = @()
$summaryLines += "## SLA Validation — $Protocol"
$summaryLines += ""
$summaryLines += "| Setting | Value |"
$summaryLines += "|---------|-------|"
$summaryLines += "| Breach Action | ``$BreachAction`` |"
$summaryLines += "| Breaches | $($breaches.Count) |"
$summaryLines += "| Warnings | $($warnings.Count) |"
$summaryLines += "| Result | $(if($breaches.Count -eq 0){'✅ PASS'}else{'🚨 BREACH DETECTED'}) |"
$summaryLines += ""

if ($breaches.Count -gt 0) {
    $summaryLines += "### 🚨 Breached Thresholds"
    $summaryLines += ""
    foreach ($b in $breaches) { $summaryLines += "- $b" }
    $summaryLines += ""
}
if ($warnings.Count -gt 0) {
    $summaryLines += "### ⚠️ Warnings"
    $summaryLines += ""
    foreach ($w in $warnings) { $summaryLines += "- $w" }
    $summaryLines += ""
}

$summaryLines += "> **Breach action:** ``$BreachAction``"
switch ($BreachAction) {
    "log_only"     { $summaryLines += "> Violations logged. Test ran to completion. Job **not** failed." }
    "warn_and_log" { $summaryLines += "> Violations logged as warnings. Job **not** failed." }
    "fail_job"     { $summaryLines += "> Violations detected. Job will be **marked as failed**." }
}

if ($env:GITHUB_STEP_SUMMARY) {
    $summaryLines | Add-Content $env:GITHUB_STEP_SUMMARY
}

# ── Final section ───────────────────────────────────────────────────────────
Section "Result"

if ($breaches.Count -eq 0 -and $warnings.Count -eq 0) {
    Write-Host "  ✅ All SLA thresholds met — no violations" -ForegroundColor Green
    exit 0
}

if ($breaches.Count -gt 0) {
    Write-Host ""
    Write-Host "  🚨 $($breaches.Count) SLA breach(es) detected, $($warnings.Count) warning(s)" -ForegroundColor Red
    Write-Host "  Breach action: $BreachAction" -ForegroundColor DarkGray

    switch ($BreachAction) {
        "log_only" {
            Write-Host "  ℹ️  Violations logged only — job continues (breach action: log_only)" -ForegroundColor Cyan
            exit 0    # ← NEVER fails the job
        }
        "warn_and_log" {
            Write-Host "  ⚠️  Violations logged as warnings — job continues (breach action: warn_and_log)" -ForegroundColor Yellow
            # Emit GitHub warning annotation for each breach
            foreach ($b in $breaches) {
                Write-Host "::warning::SLA breach: $b"
            }
            exit 0    # ← NEVER fails the job
        }
        "fail_job" {
            Write-Host "  ❌ Failing job due to SLA breach (breach action: fail_job)" -ForegroundColor Red
            exit 1    # ← Only mode that fails the job
        }
    }
} else {
    # Only warnings, no breaches
    Write-Host "  ⚠️  $($warnings.Count) warning(s) — no breaches" -ForegroundColor Yellow
    exit 0
}
