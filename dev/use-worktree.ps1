<#
Points kaiju_suite-dev (next to the main checkout; the folder Maya loads Kaiju from for
testing) at a git worktree, so a feature can be tried in Maya without copying files.

  .\dev\use-worktree.ps1                   # list the worktrees and pick one by number
  .\dev\use-worktree.ps1 feature/my-tool   # link the worktree that has that branch
  .\dev\use-worktree.ps1 main              # link the main checkout again
  .\dev\use-worktree.ps1 -Show             # say what's linked now
#>
param(
    [string]$Branch = "",
    [switch]$Show
)
$ErrorActionPreference = "Stop"

$gitDir = git -C $PSScriptRoot rev-parse --path-format=absolute --git-common-dir
if ($LASTEXITCODE -ne 0) { throw "Not inside a git repository: $PSScriptRoot" }
$repo = Split-Path ([System.IO.Path]::GetFullPath($gitDir))
$link = Join-Path (Split-Path $repo) "kaiju_suite-dev"

$item = Get-Item $link -Force -ErrorAction SilentlyContinue
$current = $null
if ($null -ne $item -and $item.LinkType -eq "Junction") {
    $current = [System.IO.Path]::GetFullPath(@($item.Target)[0]).TrimEnd("\")
}

if ($Show) {
    if ($null -eq $item) { "Nothing at $link" }
    elseif ($null -ne $current) { "$link -> $current" }
    else { "$link is a plain folder, not a link" }
    return
}

# Every worktree with its branch, main checkout first.
$worktrees = @()
foreach ($line in git -C $repo worktree list --porcelain) {
    if ($line -like "worktree *") {
        $worktrees += [pscustomobject]@{
            Path   = [System.IO.Path]::GetFullPath($line.Substring(9)).TrimEnd("\")
            Branch = "(detached)"
        }
    }
    if ($line -like "branch refs/heads/*") { $worktrees[-1].Branch = $line.Substring(18) }
}

if ($Branch -eq "") {
    $width = ($worktrees | ForEach-Object { $_.Branch.Length } | Measure-Object -Maximum).Maximum
    "Worktrees (* = linked now):"
    for ($i = 0; $i -lt $worktrees.Count; $i++) {
        $w = $worktrees[$i]
        $mark = if ($w.Path -eq $current) { "  *" } else { "" }
        "  {0}  {1}  {2}{3}" -f ($i + 1), $w.Branch.PadRight($width), $w.Path, $mark
    }
    $answer = Read-Host "Number to link (Enter to cancel)"
    if ([string]::IsNullOrWhiteSpace($answer)) { "Nothing changed."; return }
    $number = 0
    if (-not [int]::TryParse($answer, [ref]$number) -or $number -lt 1 -or $number -gt $worktrees.Count) {
        throw "'$answer' isn't a number from 1 to $($worktrees.Count)."
    }
    $chosen = $worktrees[$number - 1]
} else {
    $chosen = $worktrees | Where-Object { $_.Branch -eq $Branch } | Select-Object -First 1
    if ($null -eq $chosen) {
        throw "No worktree has '$Branch' checked out. Run 'git worktree list' to see them."
    }
}

# Remove the old link. A plain folder (an old copy) is renamed, never deleted.
if ($null -ne $item) {
    if ($item.LinkType -eq "Junction") {
        # Deletes only the link. Remove-Item -Recurse here could delete the worktree's files.
        [System.IO.Directory]::Delete($link)
    } else {
        $backup = "$link.old-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Rename-Item $link $backup
        "Kept the old copy as $backup"
    }
}

New-Item -ItemType Junction -Path $link -Target $chosen.Path | Out-Null
"$link -> $($chosen.Path) ($($chosen.Branch))"
"In Maya: Kaiju -> Reload Kaiju Suite (or restart Maya)."
