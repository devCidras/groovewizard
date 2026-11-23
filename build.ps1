# Gera a app (dist\Cratekeeper\) e o instalador (dist\Cratekeeper-<versao>-setup.exe).
# Precisa: Python, e o Inno Setup 6 (https://jrsoftware.org/isinfo.php) para o instalador.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install --quiet pyinstaller==6.22.3 -r requirements.txt
$version = python -c "import organizador; print(organizador.__version__)"

# termos em .txt para o ecra de licenca do instalador (mesmo texto que a app mostra)
New-Item -ItemType Directory -Force installer\build | Out-Null
python -c "from organizador import termos; [open(f'installer/build/termos_{k}.txt','w',encoding='utf-8-sig').write(v) for k,v in termos.TERMS.items()]"

python tests\test_pipeline.py
if ($LASTEXITCODE -ne 0) { exit 1 }

# librosa fica de fora (centenas de MB): no .exe o BPM vem so da tag.
# Modulos Qt que a app nao usa ficam de fora (e alguns, como o VirtualKeyboard, nao sao LGPL).
$excl = "librosa numba scipy sklearn PySide6.QtNetwork PySide6.QtQml PySide6.QtQuick PySide6.QtPdf PySide6.QtOpenGL PySide6.QtVirtualKeyboard".Split(" ") | ForEach-Object { "--exclude-module", $_ }
python -m PyInstaller --noconfirm --clean --windowed --name Cratekeeper --icon organizador\recursos\cratekeeper.ico `
    --add-data "organizador\recursos;organizador\recursos" @excl app.py
if ($LASTEXITCODE -ne 0) { exit 1 }

# o hook do PySide6 copia DLLs do Qt mesmo sem os modulos: tirar as que nao sao usadas
$qt = "dist\Cratekeeper\_internal\PySide6"
$unused = "Qt6VirtualKeyboard.dll Qt6Pdf.dll Qt6Qml.dll Qt6QmlMeta.dll Qt6QmlModels.dll Qt6QmlWorkerScript.dll Qt6Quick.dll Qt6Network.dll Qt6OpenGL.dll QtNetwork.pyd opengl32sw.dll".Split(" ")
foreach ($f in $unused) { if (Test-Path "$qt\$f") { Remove-Item -LiteralPath "$qt\$f" -Force } }
foreach ($d in "plugins\platforminputcontexts", "plugins\networkinformation", "plugins\tls", "qml") {
    if (Test-Path "$qt\$d") { Get-ChildItem -LiteralPath "$qt\$d" -File -Recurse | Remove-Item -Force; Remove-Item -LiteralPath "$qt\$d" -Recurse -Force }
}

# a app empacotada tem de arrancar depois de tirar os modulos
Push-Location $env:TEMP
Start-Process "$PSScriptRoot\dist\Cratekeeper\Cratekeeper.exe" -ArgumentList "--self-test" -Wait
$ok = Select-String -Quiet -Pattern "^self-test ok" -Path "$env:TEMP\cratekeeper-self-test.log"
Remove-Item "$env:TEMP\cratekeeper-self-test.log" -ErrorAction SilentlyContinue
Pop-Location
if (-not $ok) { Write-Error "o .exe nao arranca depois de tirar os modulos Qt"; exit 1 }

# licencas e avisos de terceiros vao com a app
New-Item -ItemType Directory -Force dist\Cratekeeper\licencas | Out-Null
Copy-Item licencas\* dist\Cratekeeper\licencas\ -Force
Copy-Item LICENSE dist\Cratekeeper\LICENSE.txt -Force

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Write-Error "Inno Setup nao encontrado (https://jrsoftware.org/isinfo.php): instalador nao gerado"; exit 1 }
& $iscc "/DAppVersion=$version" installer\Cratekeeper.iss
