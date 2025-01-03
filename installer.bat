@echo off
chcp 65001 >nul
echo 自动化构建开始...

echo 构建 main_service.py...
pyinstaller --onedir src\main_service.py --noconfirm

echo 构建 run_mitmdump.py...
pyinstaller --onedir src\run_mitmdump.py --add-data "src\proxy_mitm.py;." --noconfirm

echo 构建 daemon_service.py...
pyinstaller --onedir src\daemon_service.py --noconfirm

echo 构建 install_script.py...
pyinstaller --onedir src\install_script.py --noconfirm

echo 构建 proxy_config.py...
pyinstaller --onedir src\proxy_config.py --noconfirm

echo 所有构建完成！
pause
