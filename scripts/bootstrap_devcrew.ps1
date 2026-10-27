# Run once in extracted LocalMind project root with Git installed.
$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..'))
if (!(Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git не найден. Установи Git for Windows и повтори.' }
if (!(Test-Path '.git')) {
  git init -b main
  git add .
  git commit -m 'baseline: LocalMind 0.1.2 with DevCrew mission'
  if ($LASTEXITCODE -ne 0) { throw 'Git commit не создан. Настрой git config user.name / user.email и повтори.' }
} else {
  $changes = @(git status --porcelain)
  if ($changes.Count -gt 0) { throw 'Git working tree НЕ чист. Сначала commit/stash своих изменений.' }
}
Write-Host 'Repo готов. Открой DevCrew Studio, выбери эту папку и вставь DEV_CREW_START.txt.' -ForegroundColor Green
