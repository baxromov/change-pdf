# -------- CONFIG --------
$ServerUser = "bakhromovshb"
$ServerIP   = "172.31.174.11"

# Read PROJECT_NAME from .env
$EnvFile = Join-Path $PSScriptRoot ".env"
$ProjectName = (Get-Content $EnvFile | Where-Object { $_ -match "^PROJECT_NAME\s*=" } | Select-Object -First 1) -replace "^PROJECT_NAME\s*=\s*", "" -replace "\s*#.*", "" -replace '"', '' -replace "'", ""
if (-not $ProjectName) {
    Write-Error ".env faylida PROJECT_NAME topilmadi!"
    exit 1
}

$RemotePath = "/home/$ServerUser/$ProjectName"
$LocalPath  = $PSScriptRoot

Write-Host ">>> Project: $ProjectName  (http://${ServerIP}:8585)"

# -------- DEPLOY --------

Write-Host "=== 1. Stopping containers on server ==="
ssh "${ServerUser}@${ServerIP}" "cd ~/$ProjectName && docker compose down 2>/dev/null; true"

Write-Host "=== 2. Backing up old deploy ==="
ssh "${ServerUser}@${ServerIP}" "[ -d ~/$ProjectName ] && mv ~/$ProjectName ~/${ProjectName}_backup_`$(date +%Y%m%d_%H%M) || true"

Write-Host "=== 3. Uploading project (excluding .venv, __pycache__, data) ==="
# Use rsync if available, otherwise fall back to scp with a tar pipe
$rsyncAvail = ssh "${ServerUser}@${ServerIP}" "command -v rsync && echo yes || echo no"
if ($rsyncAvail -match "yes") {
    rsync -avz --delete `
        --exclude=".venv/" `
        --exclude="__pycache__/" `
        --exclude="*.pyc" `
        --exclude=".git/" `
        --exclude="data/" `
        --exclude="errors.txt" `
        --exclude="uv.lock" `
        "${LocalPath}/" "${ServerUser}@${ServerIP}:~/$ProjectName/"
} else {
    # tar locally, pipe over ssh — skips .venv and __pycache__
    $tarExcludes = "--exclude=./.venv --exclude=./__pycache__ --exclude=./.git --exclude=./data --exclude=./errors.txt --exclude=./uv.lock"
    $tarCmd = "tar czf - $tarExcludes -C `"$LocalPath`" ."
    $sshCmd = "mkdir -p ~/$ProjectName && tar xzf - -C ~/$ProjectName"
    cmd /c "$tarCmd | ssh ${ServerUser}@${ServerIP} `"$sshCmd`""
}

Write-Host "=== 4. Building Docker image on server ==="
ssh "${ServerUser}@${ServerIP}" "cd ~/$ProjectName && docker compose build --no-cache"

Write-Host "=== 5. Starting containers ==="
ssh "${ServerUser}@${ServerIP}" "cd ~/$ProjectName && docker compose up -d"

Write-Host ""
Write-Host "✅ Deployment done: http://${ServerIP}:8585"
