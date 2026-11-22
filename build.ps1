# Gera a app (dist\Cratekeeper\) e o instalador (dist\Cratekeeper-<versao>-setup.exe).
# Precisa: Python, e o Inno Setup 6 (https://jrsoftware.org/isinfo.php) para o instalador.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install --quiet pyinstaller -r requirements.txt
$version = python -c "import organizador; print(organizador.__version__)"

# termos em .txt para o ecra de licenca do instalador (mesmo texto que a app mostra)
New-Item -ItemType Directory -Force installer\build | Out-Null
python -c "from organizador import termos; [open(f'installer/build/termos_{k}.txt','w',encoding='utf-8-sig').write(v) for k,v in termos.TERMS.items()]"

# librosa fica de fora (centenas de MB): no .exe o BPM vem so da tag
python -m PyInstaller --noconfirm --windowed --name Cratekeeper --exclude-module librosa --exclude-module numba --exclude-module scipy --exclude-module sklearn app.py

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Write-Warning "Inno Setup nao encontrado: so foi gerada a pasta dist\Cratekeeper"; exit 0 }
& $iscc "/DAppVersion=$version" installer\Cratekeeper.iss
