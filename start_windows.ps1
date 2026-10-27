$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv')) {
    Write-Host 'Создаём окружение Python...'
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python не найден. Установи Python 3.11+.' }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Не получилось установить зависимости.' }
if (-not (Test-Path '.env')) {
    Copy-Item .env.example .env
    Write-Host 'Создан .env с безопасным режимом DEMO.'
}
Write-Host 'Запускаем сервер. Если диалог недоступен, установи Ollama и загрузи модель командой ollama pull qwen3:4b.'
& .\.venv\Scripts\python.exe start.py
