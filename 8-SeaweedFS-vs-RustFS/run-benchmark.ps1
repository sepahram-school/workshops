# ============================================
# Benchmark Orchestrator for v2
# ============================================
# Starts each cluster, runs benchmarks, collects metrics,
# and generates aggregated results.
#
# Usage:
#   .\run-benchmark.ps1
#   .\run-benchmark.ps1 -Systems seaweedfs,rustfs -Runs 3
# ============================================

param(
    [string]$Systems = "seaweedfs,rustfs,librefs,minio",
    [int]$Runs = 3,
    [int]$Threads = 20,
    [string]$Sizes = "1mb,32mb,128mb",
    [int]$Files = 100,
    [switch]$SkipRead,
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

# 1. Document hardware specs
Write-Host "`n=== Collecting Hardware Specs ===" -ForegroundColor Cyan
$cpuInfo = (Get-CimInstance Win32_Processor).Name
$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$dockerVer = docker --version
Write-Host "  CPU: $cpuInfo"
Write-Host "  RAM: ${ramGB} GB"
Write-Host "  Docker: $dockerVer"

$hwSpec = @"
# Hardware Specifications — v2 Benchmark

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

    # Start cluster
    Write-Host "`n  Starting cluster..."
    docker compose -f $($composite.File) up -d
    Start-Sleep -Seconds 10

    # Start resource monitoring in background
    $metricsJob = Start-Job -ScriptBlock {
        param($prefix, $outDir)
        & powershell -File "collect-metrics.ps1" -ContainerPrefix $prefix -OutputDir $outDir
    } -ArgumentList $composite.Prefix, "results\metrics"

    # Run benchmark
    Write-Host "  Running benchmark..."
    $readFlag = if ($SkipRead) { "--skip-read" } else { "" }
    uv run python benchmark.py --target $sys --threads $Threads --sizes $Sizes --runs $Runs --files $Files $readFlag

    # Stop monitoring
    Stop-Job -Job $metricsJob -ErrorAction SilentlyContinue
    Remove-Job -Job $metricsJob -Force -ErrorAction SilentlyContinue

    # Stop cluster
    Write-Host "`n  Stopping cluster..."
    docker compose -f $($composite.File) down -v

    # Cleanup data directories
    $dataDir = "data-$sys"
    if (Test-Path $dataDir) {
        Remove-Item -Recurse -Force $dataDir -ErrorAction SilentlyContinue
        Write-Host "  Cleaned up $dataDir/"
    }
}

# 4. Report
Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "  BENCHMARK COMPLETE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Results in: results/"
Write-Host "  Summary:    results/summary.json"
Write-Host "  Metrics:    results/metrics/"
