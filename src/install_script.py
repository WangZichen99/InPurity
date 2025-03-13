import os
import time
import winreg
import random
import ctypes
import logging
import platform
import threading
import subprocess
import win32api
import win32service
import win32security
import win32serviceutil
from i18n import I18n
from key import KeyManager
from log import LogManager
from db_manager import DatabaseManager
from constants import (
    CERTIFICATES_PATH, LOG_PATH, MAIN_SERVICE_NAME, DAEMON_SERVICE_NAME,
    MAIN_SERVICE_PATH, DAEMON_SERVICE_PATH, CONFIG_PATH
)

class CertificateInstaller:
    """证书安装和服务注册管理类"""
    
    def __init__(self):
        """初始化安装程序"""
        # self.logger = self._setup_logger()
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('installer', 'installer') 
        self.db_manager = DatabaseManager()
        self.key_manager = KeyManager()
        self._installation_lock = False
        self.service_handles = []

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
            self.logger.warning(I18n.get('installer_running'))
            return
        try:
            self.logger.info(I18n.get("INSTALL_START"))
            self._installation_lock = True
            self.install_certificate()
            self.add_config_path_to_system_env()
            self.get_user_sid()
            self.setup_or_update_keys()
            for service_name in [DAEMON_SERVICE_NAME, MAIN_SERVICE_NAME]:
                self.remove_service(service_name)
            for serivce_name, service_path in [(DAEMON_SERVICE_NAME, DAEMON_SERVICE_PATH), (MAIN_SERVICE_NAME, MAIN_SERVICE_PATH)]:
                self.service_handles.append(self.register_service(serivce_name, service_path))
            for sname, handle in self.service_handles:
                threading.Thread(target=self.start_service, args=(sname, handle)).start()
        finally:
            self._installation_lock = False
            self.logger.info(I18n.get("INSTALL_END"))

    def install_certificate(self):
        """安装证书"""
        os_type = platform.system()
        if os_type == "Windows":
            self._install_windows_certificate()
        else:
            self.logger.warning(I18n.get("os_not_supported"))

    def _install_windows_certificate(self):
        """安装 Windows 证书"""
        try:
            if not self.is_admin():
                self.logger.error(I18n.get("admin_required"))
                return
            # 检查证书是否已安装
            check_result = subprocess.run(
                ["certutil", "-verify", CERTIFICATES_PATH],
                check=False, capture_output=True, text=True
            )
            if check_result.returncode == 0:
                self.logger.info(I18n.get("cert_installed"))
                return
            # 设置证书控制权限
            self.set_full_control_permissions()
            # 安装证书
            subprocess.run(
                ["certutil", "-addstore", "root", CERTIFICATES_PATH],
                check=True
            )
            self.logger.info(I18n.get("cert_install_success"))
        except subprocess.CalledProcessError as e:
            self.logger.error(I18n.get("cert_install_failed", e))

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
            self.logger.info(I18n.get("permission_set_success", CERTIFICATES_PATH))
        except subprocess.CalledProcessError as e:
            self.logger.error(I18n.get("permission_set_failed", CERTIFICATES_PATH, e))

    def add_config_path_to_system_env(self):
        """将配置路径添加到系统环境变量"""
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                0,
                winreg.KEY_ALL_ACCESS
            ) as key:
                current_path, _name = winreg.QueryValueEx(key, "Path")
                if CONFIG_PATH not in current_path:
                    new_path = f"{current_path};{CONFIG_PATH}"
                    winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
                    self.logger.info(I18n.get("env_path_added", CONFIG_PATH))
                else:
                    self.logger.info(I18n.get("env_path_exists", CONFIG_PATH))
        except Exception as e:
            self.logger.error(I18n.get("env_path_failed", e))

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
            self.logger.exception(I18n.get("get_sid_failed", e))

    def setup_or_update_keys(self):
        """安装或更新密钥"""
        try:
            self.key_manager.generate_key_pair()
            self.logger.info(I18n.get("KEY_GEN_SUCCESS"))
            return True
        except Exception as e:
            self.logger.error(I18n.get("KEY_GEN_FAILED", e))
            return False

    def wait_for_service_stop(self, service_name, sname, timeout=30):
        try:
            # 打开服务控制管理器
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
            service = win32service.OpenService(scm, service_name, win32service.SERVICE_ALL_ACCESS)
            try:
                # 查询服务状态
                status = win32service.QueryServiceStatusEx(service)
                if status['CurrentState'] == win32service.SERVICE_STOPPED:
                    self.logger.info(I18n.get('service_stopped', sname))
                    return True
                # 请求停止服务
                self.logger.info(I18n.get('service_stopping', sname))
                win32service.ControlService(service, win32service.SERVICE_CONTROL_STOP)
                # 等待服务停止
                start_time = time.time()
                old_checkpoint = status['CheckPoint']
                while time.time() - start_time < timeout:
                    status = win32service.QueryServiceStatusEx(service)
                    if status['CurrentState'] == win32service.SERVICE_STOPPED:
                        self.logger.info(I18n.get('service_stopped', sname))
                        return True
                    if status['CurrentState'] == win32service.SERVICE_STOP_PENDING:
                        # 使用 WaitHint 来决定下次检查的时间
                        wait_time = status['CheckPoint'] / 1000.0  # 转换为秒
                        # 等待时间不要太长或太短
                        wait_time = min(max(wait_time / 10.0, 1), 10)
                        # 检查服务是否有进展
                        if status['WaitHint'] > old_checkpoint:
                            old_checkpoint = status['WaitHint']
                        else:
                            # CheckPoint 没有更新，可能表示服务停滞
                            wait_time = min(wait_time, 1)
                        time.sleep(wait_time)
                    else:
                        break
                self.logger.info(I18n.get('service_stop_timeout', sname))
                return False
            finally:
                win32service.CloseServiceHandle(service)
                win32service.CloseServiceHandle(scm)
        except Exception as e:
            if e.args[0] == 1060:  # ERROR_SERVICE_DOES_NOT_EXIST
                self.logger.info(I18n.get('service_not_exist', sname))
                return True
            self.logger.exception(I18n.get('service_stop_error', e))
            return False

    def remove_service(self, service_name):
        sname = I18n.get('main_service') if service_name == MAIN_SERVICE_NAME else I18n.get('daemon_service')
        try:
            # 检查服务是否存在
            if win32serviceutil.QueryServiceStatus(service_name):
                if self.wait_for_service_stop(service_name, sname):
                    self.logger.info(I18n.get('service_removing', sname))
                    win32serviceutil.RemoveService(service_name)
                    self.logger.info(I18n.get('service_remove_success', sname))
                else:
                    self.logger.info(I18n.get('service_stop_timeout', sname))
        except Exception as e:
            self.logger.exception(I18n.get('service_remove_failed', e))

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

    def register_service(self, service_name, service_path):
        sname = I18n.get('main_service') if service_name == MAIN_SERVICE_NAME else I18n.get('daemon_service')
        try:
            # 打开服务控制管理器
            sc_handle = win32service.OpenSCManager(
                None,                   # 本地计算机
                None,                   # ServicesActive 数据库
                win32service.SC_MANAGER_ALL_ACCESS  # 完全访问权限
            )
            try:
                display_name = self._generate_random_service_name()
                service_handle = win32service.CreateService(
                    sc_handle,                               # 服务控制管理器句柄
                    service_name,                            # 服务名称
                    display_name,                            # 显示名称
                    win32service.SERVICE_ALL_ACCESS,         # 访问权限
                    win32service.SERVICE_WIN32_OWN_PROCESS,  # 服务类型
                    win32service.SERVICE_AUTO_START,         # 启动类型
                    win32service.SERVICE_ERROR_NORMAL,       # 错误控制类型
                    service_path,                            # 二进制路径
                    None,                                    # 加载顺序组
                    0,                                       # 标记值
                    None,                                    # 依赖项
                    None,                                    # 服务账户
                    None                                     # 密码
                )
                win32service.ChangeServiceConfig2(
                    service_handle,
                    win32service.SERVICE_CONFIG_DESCRIPTION,
                    display_name
                )
                return sname, service_handle
            finally:
                win32service.CloseServiceHandle(sc_handle)
        except Exception as e:
            self.logger.error(I18n.get('service_register_failed', sname, e))
            raise

    def start_service(self, sname, service_handle):
        """启动服务"""
        try:
            win32service.StartService(service_handle, None)
            # 等待服务启动
            start_time = time.time()
            while time.time() - start_time < 30:
                status = win32service.QueryServiceStatus(service_handle)[1]
                if status == win32service.SERVICE_RUNNING:
                    self.logger.info(I18n.get("service_start_success", sname))
                    break
                time.sleep(1)
            else:
                raise Exception(I18n.get('service_start_timeout', sname))
        finally:
            win32service.CloseServiceHandle(service_handle)

if __name__ == "__main__":
    installer = CertificateInstaller()
    installer.run_installation()
