$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv')) {
    throw 'Сначала выполни .\setup_windows.ps1 (однократная установка с сетью).'
}
if (-not (Test-Path '.env')) {
    Copy-Item .env.example .env
    Write-Host 'Создан .env с безопасным режимом DEMO.'
}
Write-Host 'Запускаем сервер. Если диалог недоступен, установи Ollama и загрузи модель командой ollama pull qwen3:4b.'
& .\.venv\Scripts\python.exe start.py
