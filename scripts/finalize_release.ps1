# Run from a normal PowerShell outside the restricted agent sandbox.
# Creates snapshots and an integration commit; never pushes or deletes files.
$ErrorActionPreference = 'Stop'
$releaseRoot = Split-Path -Parent $PSScriptRoot
$recoveryRoot = Join-Path $releaseRoot 'build/recovery'

function Invoke-ReleaseGit {
    param([string] $Directory, [string[]] $Arguments)
    $result = & git -C $Directory @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Git failed in $Directory. Sources and snapshots remain intact." }
    return $result
}

function Assert-NoStagedChanges([string] $Directory) {
    $staged = Invoke-ReleaseGit $Directory @('diff', '--cached', '--name-only')
    if ($staged) { throw "Pre-existing staged changes in $Directory; review them separately before running this script." }
}

$snapshotBranches = @()
foreach ($number in @(1, 2)) {
    $manifestPath = Join-Path $recoveryRoot "manifest-$number.json"
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $sourceRoot = [string] $manifest.source
    Assert-NoStagedChanges $sourceRoot
    if ((Invoke-ReleaseGit $sourceRoot @('rev-parse', 'HEAD')) -ne $manifest.base) {
        throw "Source worktree $number has a different HEAD. Review before snapshotting."
    }
    $expected = @($manifest.files.PSObject.Properties.Name | Sort-Object)
    $actual = @((Invoke-ReleaseGit $sourceRoot @('diff', '--name-only', 'HEAD'));
                (Invoke-ReleaseGit $sourceRoot @('ls-files', '--others', '--exclude-standard'))) |
                Where-Object { $_ } | Sort-Object -Unique
    if (Compare-Object $expected $actual) { throw "Source worktree $number file list changed. Preserve new work separately." }
    foreach ($entry in $manifest.files.PSObject.Properties) {
        $actualHash = (Get-FileHash -LiteralPath (Join-Path $sourceRoot $entry.Name) -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $entry.Value) { throw "Source file changed after snapshot: $($entry.Name)" }
    }
    $snapshotBranch = "backup/localmind-release-source-$number-20261103"
    Invoke-ReleaseGit $sourceRoot @('switch', '-c', $snapshotBranch) | Out-Host
    Invoke-ReleaseGit $sourceRoot (@('add', '--') + $expected) | Out-Host
    Invoke-ReleaseGit $sourceRoot @('diff', '--cached', '--check') | Out-Host
    Invoke-ReleaseGit $sourceRoot @('diff', '--cached', '--stat') | Out-Host
    Invoke-ReleaseGit $sourceRoot @('commit', '-m', "snapshot: preserve pre-release worktree $number including untracked source") | Out-Host
    $snapshotBranches += $snapshotBranch
}

Assert-NoStagedChanges $releaseRoot
if ((Invoke-ReleaseGit $releaseRoot @('rev-parse', 'HEAD')) -ne '66f6c101b91596936721313840684501c75dad1a') {
    throw 'Integration HEAD changed. Review integration before committing.'
}
$integrationFiles = @(Get-Content -LiteralPath (Join-Path $releaseRoot 'docs/evidence/release-integration-files.json') -Raw -Encoding UTF8 | ConvertFrom-Json)
$currentFiles = @((Invoke-ReleaseGit $releaseRoot @('diff', '--name-only', 'HEAD'));
                  (Invoke-ReleaseGit $releaseRoot @('ls-files', '--others', '--exclude-standard'))) |
                  Where-Object { $_ } | Sort-Object -Unique
if (Compare-Object ($integrationFiles | Sort-Object) $currentFiles) { throw 'Integration file list changed; review it before staging.' }
Invoke-ReleaseGit $releaseRoot @('switch', '-c', 'release/1.0.0-rc1', '66f6c10') | Out-Host
Invoke-ReleaseGit $releaseRoot (@('add', '--') + $integrationFiles) | Out-Host
Invoke-ReleaseGit $releaseRoot @('diff', '--cached', '--check') | Out-Host
Invoke-ReleaseGit $releaseRoot @('diff', '--cached', '--stat') | Out-Host
Invoke-ReleaseGit $releaseRoot @('commit', '-m', 'release: integrate both Alpha hardening snapshots and stabilize 1.0.0-rc1') | Out-Host
Write-Host 'Snapshot branches preserved:' $snapshotBranches
Write-Host 'Integration commit:' (Invoke-ReleaseGit $releaseRoot @('rev-parse', 'HEAD'))
Write-Host 'Run all release checks, then build with x64 CPython 3.11 and Inno Setup 6. No Stable tag has been created.'
