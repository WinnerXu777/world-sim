<#
.SYNOPSIS
  Play Eden: start the backend, wait until it is ready, start the Godot 2D client, and stop the backend
  when the client exits (also on Ctrl+C or a client crash).

.DESCRIPTION
  Backend: gameplay profile, village + smith [620,0], lodge [620,400], west cottage [960,160],
  a free port (or -Port), and a data root under .runtime (a new one, or -DataRoot to continue a world).
  Before stopping, the launcher asks the backend to save the active world (best effort).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\play.ps1                       # new world root, free port
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\play.ps1 -DataRoot .runtime\play-20261007-101500   # continue
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\play.ps1 -Port 8014 -Headless -GodotArgs '--quit-after','600' -ClientArgs '--auto-new=Smoke'
#>
[CmdletBinding()]
param(
    [string]$DataRoot = "",          # an existing data root to continue; omit for a fresh one
    [switch]$Fresh,                  # the default; with -DataRoot it is an error (a fresh world needs a new root)
    [int]$Port = 0,                  # 0 = pick a free port
    [switch]$Headless,               # no window (tests)
    [string[]]$GodotArgs = @(),      # extra engine arguments, placed before the -- separator
    [string[]]$ClientArgs = @(),     # extra game arguments, placed after the -- separator
    [int]$ReadySeconds = 120
)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$clientProject = Join-Path $repo 'godot_client_2d'

function Find-Python {
    $venv = Join-Path $repo '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    $found = Get-Command python -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    throw 'No Python found: create the repo .venv or put python on PATH.'
}

function Find-Godot([bool]$console) {
    if ($env:EDEN_GODOT) { return $env:EDEN_GODOT }
    $command = Get-Command godot -ErrorAction SilentlyContinue
    if (-not $command) { throw 'godot was not found on PATH (set EDEN_GODOT to the executable).' }
    $directory = Split-Path $command.Source -Parent
    $exes = @(Get-ChildItem -Path $directory -Filter 'Godot_v*_win64*.exe' -ErrorAction SilentlyContinue)
    $wanted = $exes | Where-Object { ($_.Name -like '*_console.exe') -eq $console } | Select-Object -First 1
    if ($wanted) { return $wanted.FullName }
    return $command.Source
}

function Test-PortFree([int]$candidate) {
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $candidate)
        $listener.Start(); $listener.Stop(); return $true
    } catch { return $false }
}

function Stop-Tree($process) {
    if ($process -and -not $process.HasExited) {
        & taskkill /F /T /PID $process.Id 2>&1 | Out-Null
    }
}

if ($Fresh -and $DataRoot) { throw '-Fresh and -DataRoot cannot be combined: pass -DataRoot only to continue an existing world.' }
if ($Port -eq 0) {
    $probe = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 0)
    $probe.Start(); $Port = $probe.LocalEndpoint.Port; $probe.Stop()
} elseif (-not (Test-PortFree $Port)) {
    throw "Port $Port is already in use. Pass another -Port or omit it to pick a free one."
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if ($DataRoot) {
    if (-not (Test-Path $DataRoot)) { throw "Data root '$DataRoot' does not exist. Omit -DataRoot for a new world." }
    $DataRoot = (Resolve-Path $DataRoot).Path
} else {
    $DataRoot = Join-Path $repo ".runtime\play-$stamp"
    New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
}
$logs = Join-Path $repo '.runtime\play-logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$backendOut = Join-Path $logs "backend-$Port-$stamp.out.log"
$backendErr = Join-Path $logs "backend-$Port-$stamp.err.log"
$url = "http://127.0.0.1:$Port"

$python = Find-Python
$godot = Find-Godot ([bool]$Headless)
$saved = @{}
foreach ($name in 'EDEN_PROFILE', 'EDEN_PORT', 'EDEN_MAP', 'EDEN_MAP_FILES', 'EDEN_MAP_ORIGINS', 'EDEN_DATA_ROOT') { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
$backend = $null
$client = $null
$exitCode = 0
try {
    $env:EDEN_PROFILE = 'gameplay'
    $env:EDEN_PORT = "$Port"
    $env:EDEN_MAP = 'starter_village'
    $env:EDEN_MAP_FILES = (@('starter_village', 'smith_interior', 'village_lodge_interior', 'west_cottage_interior') | ForEach-Object { Join-Path $repo "world_data\maps2d\$_.json" }) -join [IO.Path]::PathSeparator
    $env:EDEN_MAP_ORIGINS = '{"smith_interior": [620, 0], "village_lodge_interior": [620, 400], "west_cottage_interior": [960, 160]}'
    $env:EDEN_DATA_ROOT = $DataRoot
    Write-Host "Starting the backend on $url (data root $DataRoot)"
    $backend = Start-Process -FilePath $python -ArgumentList @('at_the_beginning\map_test.py') -WorkingDirectory $repo `
        -PassThru -WindowStyle Hidden -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr
    Write-Host "PLAY_PORT=$Port"
    Write-Host "PLAY_DATA_ROOT=$DataRoot"
    Write-Host "PLAY_BACKEND_PID=$($backend.Id)"

    $deadline = (Get-Date).AddSeconds($ReadySeconds)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($backend.HasExited) {
            $tail = (Get-Content $backendErr -Tail 15 -ErrorAction SilentlyContinue) -join "`n"
            throw "The backend exited with code $($backend.ExitCode) before it was ready.`n$tail"
        }
        try {
            $null = Invoke-RestMethod -Uri "$url/status" -TimeoutSec 2
            $ready = $true; break
        } catch { Start-Sleep -Milliseconds 400 }
    }
    if (-not $ready) { throw "The backend did not answer on $url within $ReadySeconds s (see $backendErr)." }
    Write-Host 'Backend ready. Starting the game; close the game window to stop everything.'

    $arguments = @('--path', $clientProject)
    if ($Headless) { $arguments += '--headless' }
    $arguments += $GodotArgs
    $arguments += '--'
    $arguments += "--backend-url=$url"
    $arguments += $ClientArgs
    # Start-Process joins the list with spaces, so quote every argument that contains one.
    $arguments = @($arguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } })
    # The game is the user's interactive window; backend helpers remain hidden.
    $client = Start-Process -FilePath $godot -ArgumentList $arguments -WorkingDirectory $repo -PassThru
    Write-Host "PLAY_CLIENT_PID=$($client.Id)"
    $restartCount = 0
    while (-not $client.HasExited) {
        if ($backend.HasExited -and $restartCount -lt 3) {
            $restartCount += 1
            Write-Warning "The backend stopped unexpectedly. Restarting with the same data root (attempt $restartCount of 3). Continue a saved world in the game; unsaved progress may be lost."
            Start-Sleep -Seconds 1
            if (-not $client.HasExited -and (Test-PortFree $Port)) {
                $restartOut = Join-Path $logs "backend-$Port-$stamp-restart$restartCount.out.log"
                $restartErr = Join-Path $logs "backend-$Port-$stamp-restart$restartCount.err.log"
                $backend = Start-Process -FilePath $python -ArgumentList @('at_the_beginning\map_test.py') -WorkingDirectory $repo `
                    -PassThru -WindowStyle Hidden -RedirectStandardOutput $restartOut -RedirectStandardError $restartErr
                Write-Host "PLAY_RESTART_BACKEND_PID=$($backend.Id)"
            } else {
                $restartCount = 3
            }
            if ($restartCount -eq 3) {
                Write-Warning 'Automatic restart limit reached. The game remains open; close it and relaunch with the printed -DataRoot to Continue.'
            }
        }
        Start-Sleep -Milliseconds 300
    }
    if ($client.HasExited) { $exitCode = [int]$client.ExitCode }
}
finally {
    Write-Host 'Stopping...'
    Stop-Tree $client
    if ($backend -and -not $backend.HasExited) {
        try {   # best effort: keep the world the player was in
            $boot = Invoke-RestMethod -Uri "$url/bootstrap" -TimeoutSec 3
            if ($boot.session.world_loaded) {
                $null = Invoke-RestMethod -Uri "$url/session/save" -Method Post -Headers @{ 'X-Eden-Session' = $boot.session_capability } `
                    -ContentType 'application/json' -Body '{}' -TimeoutSec 20
                Write-Host 'World saved.'
            }
        } catch { Write-Host "Final save skipped: $($_.Exception.Message)" }
    }
    Stop-Tree $backend
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name]) }
    $freed = $false
    for ($i = 0; $i -lt 20; $i++) { if (Test-PortFree $Port) { $freed = $true; break }; Start-Sleep -Milliseconds 250 }
    Write-Host ("PLAY_STOPPED port_free={0}" -f $freed)
}
exit $exitCode
