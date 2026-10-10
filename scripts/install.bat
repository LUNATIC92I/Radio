@echo off
REM Installation de LUNATIC RADIO LAB (Windows)
cd /d "%~dp0\.."
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -m venv --system-site-packages .venv || goto :error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || goto :error
python -m pip install -e . --no-deps
python -m lunatic_radio_lab devices
python -m lunatic_radio_lab selftest
echo Installation terminee. Lancement : scripts\run.bat
exit /b 0
:error
echo Echec de l'installation.
exit /b 1
