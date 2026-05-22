# Detiene procesos Livermore AI en esta maquina (worker, main, uvicorn).
$procs = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" -ErrorAction SilentlyContinue
$stopped = @()

foreach ($p in $procs) {
    $cmd = $p.CommandLine
    if (-not $cmd) { continue }
    $isLivermore = (
        $cmd -match 'worker\.py' -or
        $cmd -match 'railway_entry\.py' -or
        ($cmd -match 'main\.py' -and $cmd -notmatch 'streamlit') -or
        ($cmd -match 'uvicorn' -and $cmd -match 'main:app')
    )
    if ($isLivermore) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        $stopped += $p.ProcessId
    }
}

if ($stopped.Count -gt 0) {
    Write-Host "Livermore local detenido. PIDs: $($stopped -join ', ')"
} else {
    Write-Host "No habia procesos Livermore corriendo en local."
}
