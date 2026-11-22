# Gera dist\OrganizadorMusica.exe (sem precisar de Python no PC de quem usa)
python -m pip install pyinstaller -r requirements.txt
python -m PyInstaller --noconfirm --onefile --windowed --name OrganizadorMusica app.py
