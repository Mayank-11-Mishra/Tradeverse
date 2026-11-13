$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
Write-Host 'Personal Algo Terminal — local Windows setup' -ForegroundColor Cyan
Set-Location $Root
if (-not (Get-Command py -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python 3.12+ is required.' }
$Python=if(Get-Command py -ErrorAction SilentlyContinue){'py'}else{'python'}
if (-not(Test-Path '.venv')){& $Python -m venv .venv; if($LASTEXITCODE -ne 0){throw 'Could not create Python environment'}}
$VenvPython=Join-Path $Root '.venv\Scripts\python.exe'
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r backend\requirements.txt
if($LASTEXITCODE -ne 0){throw 'Backend requirements failed to install'}
# FYERS and Groww require incompatible aiohttp versions, so FYERS gets its own venv.
$FyersVenv=Join-Path $Root 'backend\.fyers-venv'
if(-not(Test-Path $FyersVenv)){
    & $VenvPython -m venv $FyersVenv
    if($LASTEXITCODE -ne 0){Write-Warning 'Could not create isolated FYERS environment'}
}
$FyersPython=Join-Path $FyersVenv 'Scripts\python.exe'
if(Test-Path $FyersPython){
    Write-Host 'Installing FYERS live-stream SDK in its isolated Python environment...' -ForegroundColor Cyan
    & $FyersPython -m pip install -r backend\requirements-fyers-worker.txt
    if($LASTEXITCODE -ne 0){
        Write-Warning 'FYERS SDK install failed. FYERS REST login/orders still work; streaming needs its SDK.'
    }
}
& $VenvPython -m pip check
if($LASTEXITCODE -ne 0){throw 'Main Python dependency conflict detected'}
if(-not(Get-Command npm -ErrorAction SilentlyContinue)){throw 'Node.js 20+ and npm must be installed.'}
Push-Location frontend
try{npm install --no-audit --no-fund; if($LASTEXITCODE -ne 0){throw 'Frontend npm installation failed'}}finally{Pop-Location}
New-Item -ItemType Directory -Force data,logs | Out-Null
# There is no database server to install or manually initialize.
# The FastAPI lifespan runs store.init_db() at backend startup and creates
# data/trading.db automatically (SQLite) if it does not already exist.
# Avoid a 'python -c' command here: nested quotes can be mangled by Windows PowerShell.
Write-Host 'SQLite storage will initialize automatically when the backend starts.' -ForegroundColor Cyan
Write-Host 'Setup complete. Double-click scripts\start_application.bat' -ForegroundColor Green
