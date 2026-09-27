<#
install.ps1 - copy the skill-manager toolkit into $CODEX_HOME.

  powershell -ExecutionPolicy Bypass -File .\install.ps1
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -CodexHome D:\codex -Force -NoReindex

Nothing is deleted. Existing files are only overwritten with -Force.
#>
[CmdletBinding()]
param(
  [string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }),
  [switch]$Force,
  [switch]$NoReindex
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

function Install-File {
  param([string]$Source, [string]$Destination)
  if ((Test-Path -LiteralPath $Destination) -and -not $Force) {
    Write-Output "skip (exists, use -Force): $Destination"
    return
  }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
  Copy-Item -LiteralPath $Source -Destination $Destination -Force
  Write-Output "installed: $Destination"
}

Write-Output "codex home: $CodexHome"
New-Item -ItemType Directory -Force -Path $CodexHome | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $CodexHome 'skills-off') | Out-Null

Install-File (Join-Path $root 'skillfind.py') (Join-Path $CodexHome 'skillfind.py')
Install-File (Join-Path $root 'skillctl.ps1') (Join-Path $CodexHome 'skillctl.ps1')
Install-File (Join-Path $root 'config\skill-packs.json') (Join-Path $CodexHome 'skill-packs.json')
Install-File (Join-Path $root 'config\skill-aliases.json') (Join-Path $CodexHome 'skill-aliases.json')

# the skill itself is shipped with a __CODEX_HOME__ placeholder so the repo stays machine independent
$skillSrc = Join-Path $root 'skill\skill-manager\SKILL.md'
$skillDir = Join-Path $CodexHome 'skills\skill-manager'
$skillDst = Join-Path $skillDir 'SKILL.md'
if ((Test-Path -LiteralPath $skillDst) -and -not $Force) {
  Write-Output "skip (exists, use -Force): $skillDst"
} else {
  New-Item -ItemType Directory -Force -Path $skillDir | Out-Null
  $text = [IO.File]::ReadAllText($skillSrc, [Text.Encoding]::UTF8)
  $text = $text.Replace('__CODEX_HOME__', $CodexHome)
  [IO.File]::WriteAllText($skillDst, $text, (New-Object Text.UTF8Encoding($false)))
  Write-Output "installed: $skillDst"
}

if ($NoReindex) {
  Write-Output 'index: skipped (-NoReindex)'
} else {
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    & $python.Source (Join-Path $CodexHome 'skillfind.py') --reindex
  } else {
    Write-Output 'python not found on PATH - run this yourself after installing Python:'
    Write-Output "  python `"$CodexHome\skillfind.py`" --reindex"
  }
}

Write-Output ''
Write-Output 'next steps:'
Write-Output "  python `"$CodexHome\skillfind.py`" `<keywords>` -n 5     # search before starting a task"
Write-Output "  powershell -File `"$CodexHome\skillctl.ps1`" report      # estimate injected catalog size"
