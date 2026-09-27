<#
skillctl - toggle Codex skills on/off to control the injected skill catalog size.

Why: Codex injects the name+description of every SKILL.md under $CODEX_HOME/skills
into the model context on every turn. There is no config switch for that; the only
lever is whether the skill directory sits inside skills/ or outside of it.
This script moves directories. Nothing is deleted; every action is reversible.

Usage:
  skillctl list                 list enabled skills
  skillctl list -Off            list disabled skills
  skillctl off <name|pattern>   disable (wildcards allowed)
  skillctl on  <name|pattern>   enable
  skillctl on-all               re-enable everything
  skillctl packs                show packs and match counts
  skillctl off-pack <pack>      disable a pack
  skillctl on-pack  <pack>      re-enable a pack
  skillctl keep-only <pack>     keep only these packs, disable the rest
  skillctl report               estimate injected catalog size
  skillctl measure              measure the real catalog size via the codex CLI
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)][string]$Command = 'list',
  [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Names,
  [switch]$Off,
  [switch]$All
)

$ErrorActionPreference = 'Stop'

$CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$OnDir    = Join-Path $CodexHome 'skills'
$OffDir   = Join-Path $CodexHome 'skills-off'
$PackFile = Join-Path $CodexHome 'skill-packs.json'
$Budget   = 82500   # measured ceiling of the injected catalog, in characters

if (-not (Test-Path $OffDir)) { New-Item -ItemType Directory -Force -Path $OffDir | Out-Null }

function Get-EnabledSkills {
  Get-ChildItem -LiteralPath $OnDir -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne '.system' -and (Test-Path (Join-Path $_.FullName 'SKILL.md')) } |
    Select-Object -ExpandProperty Name
}

function Get-DisabledSkills {
  Get-ChildItem -LiteralPath $OffDir -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName 'SKILL.md') } |
    Select-Object -ExpandProperty Name
}

function Get-Packs {
  $result = @{}
  if (-not (Test-Path $PackFile)) { return $result }
  $json = [IO.File]::ReadAllText($PackFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
  foreach ($property in $json.packs.PSObject.Properties) {
    $result[$property.Name] = @($property.Value)
  }
  return $result
}

function Resolve-Patterns {
  param([string[]]$Patterns, [string[]]$Pool)
  $hits = @()
  foreach ($pattern in $Patterns) {
    $hits += $Pool | Where-Object { $_ -like $pattern -or $_ -eq $pattern }
  }
  return @($hits | Sort-Object -Unique)
}

function Move-Skill {
  param([string[]]$Targets, [bool]$Disable)
  if (-not $Targets -or $Targets.Count -eq 0) { Write-Output 'no matching skill.'; return }
  $fromDir = if ($Disable) { $OnDir } else { $OffDir }
  $toDir   = if ($Disable) { $OffDir } else { $OnDir }
  foreach ($name in $Targets) {
    $from = Join-Path $fromDir $name
    $to   = Join-Path $toDir $name
    if (-not (Test-Path -LiteralPath $from)) { Write-Output "skip (missing): $name"; continue }
    if (Test-Path -LiteralPath $to) { Write-Output "skip (target exists): $name"; continue }
    Move-Item -LiteralPath $from -Destination $to
    $verb = if ($Disable) { 'off' } else { 'on ' }
    Write-Output "$verb $name"
  }
}

function Show-Report {
  $enabled = @(Get-EnabledSkills)
  $natural = 0
  foreach ($name in $enabled) {
    $text = [IO.File]::ReadAllText((Join-Path $OnDir "$name\SKILL.md"), [Text.Encoding]::UTF8)
    $fm = [regex]::Match($text, '(?s)^---\s*(.*?)\s*---')
    if ($fm.Success) { $natural += $fm.Groups[1].Value.Length }
  }
  $estimate = [Math]::Min($natural, $Budget)
  Write-Output ("enabled skills        : {0}" -f $enabled.Count)
  Write-Output ("disabled skills       : {0}" -f @(Get-DisabledSkills).Count)
  Write-Output ("frontmatter chars     : {0}" -f $natural)
  Write-Output ("estimated catalog     : {0} chars (ceiling {1}) ~ {2} tokens" -f $estimate, $Budget, [Math]::Round($estimate / 4))
  if ($natural -gt $Budget) {
    Write-Output "NOTE: over the ceiling, so every description gets truncated. To actually save context"
    Write-Output ("      the total has to drop below {0} chars, i.e. keep only a few dozen skills." -f $Budget)
  }
}

function Invoke-Measure {
  $bin = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
  $exe = Get-ChildItem $bin -Recurse -Filter 'codex.exe' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $exe) { Write-Output 'codex.exe not found; skipped.'; return }
  $json = & $exe.FullName debug prompt-input 'hi' 2>&1 | Out-String
  $block = [regex]::Match($json, '(?s)<skills_instructions>.*?</skills_instructions>').Value
  $entries = ([regex]::Matches($block, '\(file: ')).Count
  Write-Output ("measured catalog : {0} chars ~ {1} tokens, {2} entries" -f $block.Length, [Math]::Round($block.Length / 4), $entries)
}

switch ($Command.ToLower()) {
  'list' {
    if ($Off) { Get-DisabledSkills } else { Get-EnabledSkills }
  }
  'off' {
    if ($All) { Move-Skill -Targets @(Get-EnabledSkills) -Disable $true }
    else { Move-Skill -Targets (Resolve-Patterns -Patterns $Names -Pool @(Get-EnabledSkills)) -Disable $true }
  }
  'on' {
    if ($All) { Move-Skill -Targets @(Get-DisabledSkills) -Disable $false }
    else { Move-Skill -Targets (Resolve-Patterns -Patterns $Names -Pool @(Get-DisabledSkills)) -Disable $false }
  }
  'on-all' { Move-Skill -Targets @(Get-DisabledSkills) -Disable $false }
  'packs' {
    $packs = Get-Packs
    if ($packs.Count -eq 0) { Write-Output "not found: $PackFile"; break }
    foreach ($key in ($packs.Keys | Sort-Object)) {
      $members = Resolve-Patterns -Patterns $packs[$key] -Pool @(Get-EnabledSkills)
      Write-Output ("{0,-16} rules={1,-3} matches_enabled={2}" -f $key, $packs[$key].Count, $members.Count)
    }
  }
  'off-pack' {
    $packs = Get-Packs
    foreach ($pack in $Names) {
      if (-not $packs.ContainsKey($pack)) { Write-Output "unknown pack: $pack"; continue }
      Move-Skill -Targets (Resolve-Patterns -Patterns $packs[$pack] -Pool @(Get-EnabledSkills)) -Disable $true
    }
  }
  'on-pack' {
    $packs = Get-Packs
    foreach ($pack in $Names) {
      if (-not $packs.ContainsKey($pack)) { Write-Output "unknown pack: $pack"; continue }
      Move-Skill -Targets (Resolve-Patterns -Patterns $packs[$pack] -Pool @(Get-DisabledSkills)) -Disable $false
    }
  }
  'keep-only' {
    $packs = Get-Packs
    $keep = @()
    foreach ($pack in $Names) {
      if (-not $packs.ContainsKey($pack)) { Write-Output "unknown pack: $pack"; continue }
      $keep += Resolve-Patterns -Patterns $packs[$pack] -Pool @(Get-EnabledSkills)
    }
    $keep = @($keep | Sort-Object -Unique)
    $drop = @(Get-EnabledSkills) | Where-Object { $keep -notcontains $_ }
    Move-Skill -Targets $drop -Disable $true
    Write-Output ("kept {0}, disabled {1}" -f $keep.Count, $drop.Count)
  }
  'report'  { Show-Report }
  'measure' { Invoke-Measure }
  default   { Write-Output "unknown command: $Command (list/off/on/on-all/packs/off-pack/on-pack/keep-only/report/measure)" }
}
