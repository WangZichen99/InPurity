@echo off
chcp 65001 >nul
echo Starting bat...

if not exist "target\" mkdir "target\"
cd target

echo Deleting dist directory...
if exist dist rd /s /q dist

echo Deleting build directory...
if exist build rd /s /q build

echo Deleting .spec files...
if exist *.spec del /q *.spec

echo Deletion finished

@REM if not exist "icon.ico" copy "..\icon.ico" "icon.ico"
if not exist "setup\" mkdir "setup\"

echo Building main_service.py...
pyinstaller --onedir --icon ..\icon.ico ..\src\main_service.py --noconfirm

echo Building run_mitmdump.py...
pyinstaller --onedir --icon ..\icon.ico ..\src\run_mitmdump.py --noconfirm
copy "..\src\proxy_mitm.py" "dist\run_mitmdump\_internal"

echo Building daemon_service.py...
pyinstaller --onedir --icon ..\icon.ico ..\src\daemon_service.py --noconfirm

echo Building install_script.py...
pyinstaller --onedir --icon ..\icon.ico ..\src\install_script.py --noconfirm

echo Building proxy_config.py...
pyinstaller --onedir --icon ..\icon.ico ..\src\proxy_config.py --noconfirm

echo Building uninstaller.py...
pyinstaller --onedir --icon ..\icon.ico ..\src\uninstaller.py --noconfirm

echo Building gui.py...
pyinstaller --noconsole --onedir --windowed --icon ..\icon.ico ..\src\gui.py --noconfirm

echo Building watchdog.py...
pyinstaller --onedir --icon ..\watchdog.ico ..\src\watchdog.py --noconfirm

set "source=dist\uninstaller"
set "target=setup\uninstaller"

if exist "%target%" rd /s /q "%target%"

echo Copying uninstaller directory...
xcopy "%source%" "%target%" /E /H /C /I /Y
echo Uninstaller directory copied
cd "../"

echo All builds completed！
pause
