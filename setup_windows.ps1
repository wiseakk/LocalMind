param([switch]$Voice, [switch]$Dev)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Установи Python 3.11+ с py launcher.' }
}
$requirements = 'requirements.txt'
if ($Voice) { $requirements = 'requirements-voice.txt' }
& .\.venv\Scripts\python.exe -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить зависимости.' }
if ($Dev) {
    & .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить тестовые зависимости.' }
}
if (-not (Test-Path '.env')) { Copy-Item .env.example .env }
Write-Host 'Установка завершена. Запуск без установки: .\start_windows.ps1'
