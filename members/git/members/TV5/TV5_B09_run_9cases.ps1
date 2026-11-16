
# TV5 B09 - RAN + Core Plan baseline
# Does NOT send Preview or Apply to TV4.

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root

$baseUrl = "http://127.0.0.1:8001"
$outDir = Join-Path $PSScriptRoot "results\saved_tests\B09_RAN_Core"

New-Item -ItemType Directory -Force $outDir | Out-Null

# Confirm FastAPI is running
Invoke-RestMethod "$baseUrl/openapi.json" | Out-Null

$scenarios = @(
    "stable_load",
    "urllc_burst",
    "poor_channel"
)

$schedulers = @(
    "static",
    "qos_heuristic",
    "dqn"
)

$summary = @()

foreach ($scenario in $scenarios) {
    foreach ($scheduler in $schedulers) {

        $name = "${scenario}_${scheduler}_seed42"
        $folder = Join-Path $outDir $name

        New-Item -ItemType Directory -Force $folder | Out-Null

        Write-Host "RUNNING: $name" -ForegroundColor Cyan

        try {
            $body = @{
                scheduler = $scheduler
                scenario = $scenario
                seed = 42
                slots = 500
            } | ConvertTo-Json

            # Create session
            $created = Invoke-RestMethod `
                -Uri "$baseUrl/sessions" `
                -Method Post `
                -ContentType "application/json" `
                -Body $body

            $runId = $created.run_id

            if (-not $runId) {
                throw "Missing run_id"
            }

            # Run RAN until completed
            $null = Invoke-RestMethod `
                -Uri "$baseUrl/sessions/$runId/run-to-end" `
                -Method Post

            # Get RAN metrics and Core Plan
            $metrics = Invoke-RestMethod `
                "$baseUrl/sessions/$runId/metrics"

            $plan = Invoke-RestMethod `
                "$baseUrl/sessions/$runId/core-plan"

            $created | ConvertTo-Json -Depth 30 |
                Set-Content "$folder\01_session.json" -Encoding UTF8

            $metrics | ConvertTo-Json -Depth 30 |
                Set-Content "$folder\02_ran_metrics.json" -Encoding UTF8

            $plan | ConvertTo-Json -Depth 30 |
                Set-Content "$folder\03_core_plan.json" -Encoding UTF8

            # Copy original RAN CSV if present
            $csvPresent = $false

            if ($metrics.result_csv) {
                $src = Join-Path $root $metrics.result_csv

                if (Test-Path $src) {
                    Copy-Item $src "$folder\04_ran_slots.csv" -Force
                    $csvPresent = $true
                }
            }

            # Validate common run identity and constraints
            $valid = (
                $created.run_id -eq $metrics.run_id -and
                $metrics.run_id -eq $plan.run_id -and
                $metrics.scenario_id -eq $plan.scenario_id -and
                $metrics.seed -eq $plan.seed -and
                $metrics.scheduler -eq $plan.scheduler -and
                $metrics.completed_slots -eq 500 -and
                $plan.completed_slots -eq 500 -and
                $metrics.rb_conservation_ok -eq $true -and
                $plan.auto_apply -eq $false -and
                $csvPresent
            )

            $check = @{
                run_id = $runId
                scenario_id = $scenario
                scheduler = $scheduler
                identity_and_rb_checks_passed = $valid
                ran_csv_present = $csvPresent
                core_is_plan_only = $true
            }

            $check | ConvertTo-Json |
                Set-Content "$folder\05_validation.json" -Encoding UTF8

            $summary += [pscustomobject]@{
                scenario_id = $scenario
                scheduler = $scheduler
                seed = 42
                run_id = $runId
                completed_slots = $metrics.completed_slots
                fallback_count = $metrics.fallback_count
                rb_conservation_ok = $metrics.rb_conservation_ok
                plan_validation = $valid
                result_csv_present = $csvPresent
                execution_status = if ($valid) { "PASSED" } else { "CHECK" }
            }

            Write-Host "FINISHED: $name - Valid=$valid" -ForegroundColor Green
        }
        catch {
            $msg = $_.Exception.Message

            $msg | Set-Content "$folder\ERROR.txt" -Encoding UTF8

            $summary += [pscustomobject]@{
                scenario_id = $scenario
                scheduler = $scheduler
                seed = 42
                run_id = ""
                completed_slots = 0
                fallback_count = ""
                rb_conservation_ok = $false
                plan_validation = $false
                result_csv_present = $false
                execution_status = "FAILED"
            }

            Write-Host "FAILED: $name - $msg" -ForegroundColor Red
        }
    }
}

$summary | Export-Csv `
    "$outDir\TV5_B09_02_Summary_9Runs.csv" `
    -NoTypeInformation -Encoding UTF8

$summary | Format-Table -AutoSize

Write-Host "Output: $outDir" -ForegroundColor Yellow
