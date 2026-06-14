<#
PowerShell helper to stop tracking large files and configure Git LFS on Windows.
Run from the repository root in PowerShell as Administrator if needed.
This script DOES NOT rewrite history. For history cleanup, use the recommended commands printed at the end.
#>

Write-Host "== Clean large files and setup Git LFS helper =="

# verify git is available
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "git not found in PATH. Install Git first: https://git-scm.com/downloads"
    exit 1
}

# stop tracking common large directories (keeps local files)
$pathsToStop = @('dist/', '.venv/', 'resources/models/', 'resources/ffmpeg/')
foreach ($p in $pathsToStop) {
    Write-Host "Removing from index (if present): $p"
    & git rm -r --cached $p 2>$null
}

# add .gitignore and commit
Write-Host "Staging .gitignore and committing removal from index..."
& git add .gitignore
# commit if there is anything to commit
try {
    & git commit -m "Stop tracking build, venv and model binaries; update .gitignore" 2>$null
} catch {
    Write-Host "No commit needed (no changes staged) or commit failed. Check 'git status'."
}

# Git LFS configuration
if (-not (Get-Command git-lfs -ErrorAction SilentlyContinue)) {
    Write-Warning "git-lfs not found. Please install Git LFS from https://git-lfs.github.com/ and rerun this script."
} else {
    Write-Host "Installing and configuring Git LFS..."
    & git lfs install

    # Track common model/binary patterns (customize as needed)
    & git lfs track "resources/models/**"
    & git lfs track "resources/ollama/**"
    & git lfs track "resources/*/*.safetensors"
    & git lfs track "resources/*/*.bin"
    & git lfs track "resources/*/*.nemo"

    Write-Host "Staging .gitattributes and committing LFS tracking rules..."
    & git add .gitattributes
    try {
        & git commit -m "Track large models with Git LFS" 2>$null
    } catch {
        Write-Host "No commit needed for .gitattributes or commit failed. Check 'git status'."
    }

    Write-Host "
To migrate existing large files into LFS (this rewrites history):"
    Write-Host "git lfs migrate import --include=\"resources/models/**\" --include-ref=refs/heads/main --recent"
    Write-Host "# Review with --dry-run first, then push --force if you accept history rewrite."
}

Write-Host "
If you need to purge already-pushed blobs >100MB, consider BFG Repo-Cleaner (mirror clone + bfg + git gc + git push --force)."
Write-Host "Example sequence printed below for convenience. Use with caution."

Write-Host "-- BFG example --"
Write-Host "git clone --mirror https://github.com/<user>/<repo>.git repo.git"
Write-Host "java -jar bfg.jar --strip-blobs-bigger-than 100M repo.git"
Write-Host "cd repo.git"
Write-Host "git reflog expire --expire=now --all && git gc --prune=now --aggressive"
Write-Host "git push --force"

Write-Host "\nDone. Inspect 'git status' and run the migrate/BFG steps if you need to remove blobs from history."
