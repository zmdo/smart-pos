$ErrorActionPreference = 'Continue'
# 部署参数一律从环境变量读，禁止把主机/密码写进仓库
$k = $env:DEPLOY_HOSTKEY
$hostName = $env:DEPLOY_HOST
if (-not $env:DEPLOY_PORT -or $env:DEPLOY_PORT -notmatch "^[0-9]+$" -or [int]$env:DEPLOY_PORT -lt 1 -or [int]$env:DEPLOY_PORT -gt 65535) { throw "请设置有效 DEPLOY_PORT（当前服务器为 44023）" }
$port = [int]$env:DEPLOY_PORT
$plink = 'C:\Program Files\PuTTY\plink.exe'
$pscp = 'C:\Program Files\PuTTY\pscp.exe'
$repo = Split-Path -Parent $PSScriptRoot
$local = Join-Path $repo 'case-studio'
$remote = '/root/apps/case-studio'
if (-not $hostName -or -not $env:DEPLOY_PW) { throw '请先设置 DEPLOY_HOST / DEPLOY_PW / DEPLOY_HOSTKEY 环境变量' }

& $plink -ssh -batch -P $port -hostkey $k -pw $env:DEPLOY_PW $hostName "mkdir -p $remote/static $remote/tests $remote/run $remote/scripts/body_scan_delivery && echo ok" 2>&1 | Out-Null

$files = @('app.py','settings.py','archives.py','preprocess.py','classify.py','facts.py','plan.py',
           'start.sh','supervisord.conf','tests/test_core.py','static/index.html','static/style.css','static/app.js')
foreach ($f in $files) {
  $src = Join-Path $local ($f -replace '/', '\')
  if (Test-Path $src) {
    & $pscp -q -P $port -hostkey $k -pw $env:DEPLOY_PW $src "${hostName}:$remote/$f" 2>&1 | Out-Null
  } else { Write-Output "missing $f" }
}
$delivery = Join-Path $repo 'scripts/body_scan_delivery'
foreach ($f in Get-ChildItem -LiteralPath $delivery -Filter '*.py' -File) {
  & $pscp -q -P $port -hostkey $k -pw $env:DEPLOY_PW $f.FullName "${hostName}:$remote/scripts/body_scan_delivery/$($f.Name)" 2>&1 | Out-Null
}
$cmd = "chmod +x $remote/start.sh; cd $remote && /root/apps/portrait-studio/.venv/bin/pip install -q python-docx pypdf pillow-heif 2>&1 | tail -3; /root/apps/portrait-studio/.venv/bin/python -m pytest tests -q 2>&1 | tail -15"
& $plink -ssh -batch -P $port -hostkey $k -pw $env:DEPLOY_PW $hostName $cmd 2>&1 | Out-String
