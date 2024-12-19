import os
import platform
import subprocess
import shutil
import logging
import win32api
import win32security
import traceback
from constants import CERTIFICATES_PATH, LOG_PATH
from db_manager import DatabaseManager

class CertificateInstaller:
    def __init__(self):
        self.logger = self._setup_logger()
        self.db_manager = DatabaseManager()
        # self.cert_path_windows = os.path.join(CERTIFICATES_PATH, 'mitmproxy-ca-cert.cer')
        # self.cert_path_others = os.path.join(CERTIFICATES_PATH, 'mitmproxy-ca-cert.pem')

    def _setup_logger(self):
        if not os.path.exists(LOG_PATH):
            os.makedirs(LOG_PATH)
        logger = logging.getLogger('CertificateInstaller')
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(os.path.join(LOG_PATH, 'certificate_installer.log'), encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def install_certificate(self):
        os_type = platform.system()
        install_functions = {
            "Windows": self.install_windows_certificate
            # "Darwin": self.install_macos_certificate,
            # "Linux": self.install_linux_certificate
        }
        install_func = install_functions.get(os_type)
        if install_func:
            install_func()
        else:
            self.logger.warning("不支持自动安装证书的操作系统。")

    def is_admin(self):
        """
        检查当前用户是否具有管理员权限
        """
        try:
            return os.getuid() == 0
        except AttributeError:
            # Windows 上没有 os.getuid()，使用 ctypes 检查管理员权限
            import ctypes
            try:
                return ctypes.windll.shell32.IsUserAnAdmin()
            except:
                return False

    def set_full_control_permissions(self):
        """
        设置文件的完全控制权限。
        """
        try:
            # 使用 icacls 命令为所有用户设置完全控制权限
            subprocess.run(
                ['icacls', CERTIFICATES_PATH, '/grant', '*S-1-1-0:F', '/T', '/C'],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            print(f"设置权限成功: {CERTIFICATES_PATH}")
        except subprocess.CalledProcessError as e:
            print(f"设置权限失败: {CERTIFICATES_PATH}, 错误信息: {e}")
    
    def install_windows_certificate(self):
        try:
            # 确保以管理员权限运行
            if not self.is_admin():
                self.logger.error("需要管理员权限才能安装证书。")
                return
            # 检查证书是否已安装
            check_result = subprocess.run([
                "certutil",
                "-verify",
                CERTIFICATES_PATH
            ], check=False, capture_output=True, text=True)
            if check_result.returncode == 0:
                self.logger.info("证书已安装，无需重复安装。")
                return
            # 设置证书控制权限
            self.set_full_control_permissions()
            # 使用 certutil 命令安装证书到受信任的根证书存储区
            subprocess.run([
                "certutil",
                "-addstore",
                "root",
                CERTIFICATES_PATH
            ], check=True)
            self.logger.info("Windows系统证书安装成功。")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Windows系统证书安装失败: {e}")

    def install_macos_certificate(self):
        try:
            subprocess.run(["security", "add-trusted-cert", "-d", "-r", "trustRoot", "-k", "/Library/Keychains/System.keychain", self.cert_path_others], check=True)
            self.logger.info("macOS系统证书安装成功。")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"macOS系统证书安装失败: {e}")

    def install_linux_certificate(self):
        try:
            dest_path = "/usr/local/share/ca-certificates/mitmproxy-ca-cert.crt"
            shutil.copy(self.cert_path_others, dest_path)
            subprocess.run(["sudo", "update-ca-certificates"], check=True)
            self.logger.info("Linux系统证书安装成功。")
        except (subprocess.CalledProcessError, IOError) as e:
            self.logger.error(f"Linux系统证书安装失败: {e}")

    def get_user_sid(self):
        try:
            # 获取当前登录的用户名
            username = win32api.GetUserName()
            # 获取当前进程的访问令牌
            token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
            # 获取用户SID
            sid_info = win32security.GetTokenInformation(token, win32security.TokenUser)
            sid = sid_info[0]
            # 将 SID 转换为字符串形式
            sid = win32security.ConvertSidToStringSid(sid)
            self.db_manager.update_config("username", username)
            self.db_manager.update_config("sid", sid)
        except Exception as e:
            self.logger.error("Traceback: %s", traceback.format_exc())

if __name__ == "__main__":
    installer = CertificateInstaller()
    installer.install_certificate()
    installer.get_user_sid()
    # db_manager = DatabaseManager()
    # db_manager.initialize_db()
    # db_manager.close_connection()
