# ============================================
# Benchmark Orchestrator
# ============================================
# Starts each cluster, runs benchmarks, collects metrics,
# and generates aggregated results.
# Cleans up data directories after each mode to save disk space.
#
# Usage:
#   .\run-benchmark.ps1
#   .\run-benchmark.ps1 -Systems seaweedfs,rustfs -Runs 3
# ============================================

param(
    [string]$Systems = "seaweedfs,rustfs,librefs,minio",
    [int]$Runs = 3,
    [int]$Threads = 20,
    [string]$Sizes = "1mb,16mb,32mb",
    [int]$Files = 100,
    [string]$Modes = "write-only,read-only,heavy",
    [switch]$SkipGenerate
)

$ErrorActionPreference = "Stop"
$Composites = @(
    @{ Name = "seaweedfs"; File = "docker-compose-seaweedfs.yml"; Prefix = "seaweedfs" },
    @{ Name = "rustfs";    File = "docker-compose-rustfs.yml";    Prefix = "rustfs" },
    @{ Name = "librefs";   File = "docker-compose-librefs.yml";   Prefix = "librefs" },
    @{ Name = "minio";     File = "docker-compose-minio.yml";     Prefix = "minio" }
)

$SystemsList = $Systems -split ","

function Cleanup-DataDir {
    param([string]$SystemName)
    if ($SystemName -eq "minio") {
        foreach ($n in 1..3) {
            $dataDir = "data-minio$n"
            if (Test-Path $dataDir) {
                Remove-Item -Recurse -Force $dataDir -ErrorAction SilentlyContinue
                Write-Host "  Cleaned up $dataDir/" -ForegroundColor DarkGray
            }
        }
    } else {
        $dataDir = "data-$SystemName"
        if (Test-Path $dataDir) {
            Remove-Item -Recurse -Force $dataDir -ErrorAction SilentlyContinue
            Write-Host "  Cleaned up $dataDir/" -ForegroundColor DarkGray
        }
    }
}

function Cleanup-All-Data {
    $dirs = @("data-seaweedfs", "data-rustfs", "data-librefs",
              "data-minio1", "data-minio2", "data-minio3")
    foreach ($d in $dirs) {
        if (Test-Path $d) {
            Remove-Item -Recurse -Force $d -ErrorAction SilentlyContinue
            Write-Host "  Cleaned up $d/" -ForegroundColor DarkGray
        }
    }
}

# 1. Document hardware specs
Write-Host "`n=== Collecting Hardware Specs ===" -ForegroundColor Cyan
$cpuInfo = (Get-CimInstance Win32_Processor).Name
$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$dockerVer = docker --version
Write-Host "  CPU: $cpuInfo"
Write-Host "  RAM: ${ramGB} GB"
Write-Host "  Docker: $dockerVer"

$hwSpec = @"
# Hardware Specifications — Benchmark

| Spec | Value |
|------|-------|
| OS | $($((Get-CimInstance Win32_OperatingSystem).Caption)) |
| CPU | $cpuInfo |
| RAM | ${ramGB} GB |
| Docker | $dockerVer |
| Date | $(Get-Date -Format "yyyy-MM-dd HH:mm") |
"@
$hwSpec | Out-File -FilePath "hardware-specs.md" -Encoding utf8
Write-Host "  -> hardware-specs.md updated"

# 2. Generate test data if needed
if (-not $SkipGenerate) {
    Write-Host "`n=== Generating Test Data ===" -ForegroundColor Cyan
    if (-not (Test-Path "data")) {
        uv run python generate-data.py --size all --files $Files
    } else {
        Write-Host "  data/ already exists, skipping generation. Use -SkipGenerate to force."
    }
}

# 3. Run benchmarks per system
foreach ($sys in $SystemsList) {
    $composite = $Composites | Where-Object { $_.Name -eq $sys }
    if (-not $composite) {
        Write-Warning "Unknown system: $sys (valid: seaweedfs, rustfs, librefs, minio)"
        continue
    }

    Write-Host "`n============================================" -ForegroundColor Green
    Write-Host "  SYSTEM: $($sys.ToUpper())" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green

    # Ensure only this system's data exists
    Cleanup-All-Data

    # Start cluster
    Write-Host "`n  Starting cluster..."
    docker compose -f $($composite.File) up -d
    Start-Sleep -Seconds 10

    # Run benchmark for each mode
    $ModesList = $Modes -split ","
    foreach ($mode in $ModesList) {
        Write-Host "`n  --- Mode: $mode ---" -ForegroundColor Yellow
        uv run python benchmark.py --target $sys --threads $Threads --sizes $Sizes --runs $Runs --files $Files --mode $mode

        # Cleanup data directories after each mode to save disk space
        Write-Host "  Cleaning up data after $mode..."
        Cleanup-DataDir -SystemName $sys
    }

    # Stop cluster
    Write-Host "`n  Stopping cluster..."
    docker compose -f $($composite.File) down -v

    # Final cleanup after cluster stop
    Cleanup-DataDir -SystemName $sys
}

# 4. Final sweep — ensure no data directories remain
Write-Host "`n=== Final Cleanup ===" -ForegroundColor Cyan
Cleanup-All-Data

# 5. Report
Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "  BENCHMARK COMPLETE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Results in: results/"
