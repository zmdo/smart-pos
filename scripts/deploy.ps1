$ErrorActionPreference = 'Continue'
# 部署参数一律从环境变量读，禁止把主机/密码写进仓库
$k = $env:DEPLOY_HOSTKEY
$hostName = $env:DEPLOY_HOST
if (-not $env:DEPLOY_PORT -or $env:DEPLOY_PORT -notmatch "^[0-9]+$" -or [int]$env:DEPLOY_PORT -lt 1 -or [int]$env:DEPLOY_PORT -gt 65535) { throw "请设置有效 DEPLOY_PORT（当前服务器为 44023）" }
$port = [int]$env:DEPLOY_PORT
$plink = 'C:\Program Files\PuTTY\plink.exe'
$pscp = 'C:\Program Files\PuTTY\pscp.exe'
$local = 'E:\code-design\smart-template\portrait-studio'
$remote = '/root/apps/portrait-studio'
if (-not $hostName -or -not $env:DEPLOY_PW) { throw '请先设置 DEPLOY_HOST / DEPLOY_PW / DEPLOY_HOSTKEY 环境变量' }

# Back up the previous release once per deploy
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = "cd /root/apps && tar czf /root/portrait-studio-backup-$stamp.tar.gz --exclude=.venv --exclude=vendor portrait-studio && ls -t /root/portrait-studio-backup-*.tar.gz | head -3"
& $plink -ssh -batch -P $port -hostkey $k -pw $env:DEPLOY_PW $hostName $backup 2>&1 | Out-String

$files = @('engine.py','archives.py','app.py','imaging.py','settings.py','origins.py','face.py','tests/test_core.py','static/app.js','static/style.css','static/index.html','README.md','MODEL_VERSIONS.txt')
foreach ($f in $files) {
  $src = Join-Path $local ($f -replace '/', '\')
  if (Test-Path $src) {
    & $pscp -q -P $port -hostkey $k -pw $env:DEPLOY_PW $src "${hostName}:$remote/$f" 2>&1 | Out-String
  }
}
& $plink -ssh -batch -P $port -hostkey $k -pw $env:DEPLOY_PW $hostName "cd /root/apps/portrait-studio && .venv/bin/python -m pytest tests -q 2>&1 | tail -20" 2>&1 | Out-String
