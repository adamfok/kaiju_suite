<#
Points kaiju_suite-dev (next to the main checkout; the folder Maya loads Kaiju from for
testing) at a git worktree, so a feature can be tried in Maya without copying files.

  .\dev\use-worktree.ps1 feature/my-tool   # link the worktree that has that branch
  .\dev\use-worktree.ps1                   # link the main checkout again
  .\dev\use-worktree.ps1 -Show             # say what's linked now
#>
param(
    [string]$Branch = "main",
    [switch]$Show
)
$ErrorActionPreference = "Stop"

$gitDir = git -C $PSScriptRoot rev-parse --path-format=absolute --git-common-dir
if ($LASTEXITCODE -ne 0) { throw "Not inside a git repository: $PSScriptRoot" }
$repo = Split-Path ([System.IO.Path]::GetFullPath($gitDir))
$link = Join-Path (Split-Path $repo) "kaiju_suite-dev"

if ($Show) {
    $item = Get-Item $link -Force -ErrorAction SilentlyContinue
    if ($null -eq $item) { "Nothing at $link" }
    elseif ($item.LinkType -eq "Junction") { "$link -> $($item.Target)" }
    else { "$link is a plain folder, not a link" }
    return
}

# Find the worktree that has the branch checked out.
$target = $null
$path = $null
foreach ($line in git -C $repo worktree list --porcelain) {
    if ($line -like "worktree *") { $path = $line.Substring(9) }
    if ($line -eq "branch refs/heads/$Branch") { $target = [System.IO.Path]::GetFullPath($path) }
}
if ($null -eq $target) {
    throw "No worktree has '$Branch' checked out. Run 'git worktree list' to see them."
}

# Remove the old link. A plain folder (an old copy) is renamed, never deleted.
$item = Get-Item $link -Force -ErrorAction SilentlyContinue
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

New-Item -ItemType Junction -Path $link -Target $target | Out-Null
"$link -> $target ($Branch)"
"In Maya: Kaiju -> Reload Kaiju Suite (or restart Maya)."
