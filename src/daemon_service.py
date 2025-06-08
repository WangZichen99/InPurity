import os
import sys
import time
import winreg
import win32net
import threading
import win32event
import pywintypes
import win32netcon
import win32service
import win32security
import servicemanager
from i18n import I18n
import win32serviceutil
from log import LogManager
from filelock import FileLock
from security import SecurityManager
from db_manager import DatabaseManager
from registry_monitor import RegistryMonitor
from constants import (
    MAIN_SERVICE_NAME, DAEMON_SERVICE_NAME, INTERNET_SUB_KEY, SERVICE_SUB_KEY, TOKEN_PATH,
    DAEMON_THREAD_JOIN_TIMEOUT, DAEMON_SERVICE_CHECK_DELAY, INTERNET_MONITOR_INTERVAL,
    SERVICE_MONITOR_INTERVAL, EXPECTED_VALUES, SERVICE_HOST
)

class DaemonService(win32serviceutil.ServiceFramework):
    _svc_name_ = DAEMON_SERVICE_NAME
    _svc_display_name_ = "Windows Event Notifier"
    _svc_description_ = "Handles system event notifications and forwards critical notifications to registered services for further action. This service is essential for the smooth operation of event-driven components in the system."

    def __init__(self, args):
        """
        初始化守护服务
        
        Args:
            args: 服务框架参数
        """
        self.db_manager = DatabaseManager()
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('DaemonService', 'daemon_service')
        self.security_manager = SecurityManager()
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.service_stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.registry_paths = self.get_users_with_internet_settings()
        self.running = True
        
        # 代理设置监控
        self.monitor_threads = []
        for reg_info in self.registry_paths:
            self.monitor_threads.append({
                "thread": None,
                "monitor": RegistryMonitor(
                    reg_info["reg_key"],
                    reg_info["reg_value"],
                    reg_info["sub_key"],
                    reg_info["callback"],
                    reg_info["interval"],
                    self.logger
                )
            })

    def _start_thread(self, target, name, args=None):
        """
        启动一个新线程
        
        Args:
            target: 线程目标函数
            name: 线程名称
            args: 线程参数，默认为None
            
        Returns:
            thread: 创建的线程对象
        """
        try:
            thread = threading.Thread(
                target=target,
                name=name,
                args=() if args is None else args
            )
            thread.start()
            self.logger.info(I18n.get("thread_started", name))
            return thread
        except Exception as e:
            self.logger.error(I18n.get("daemon_thread_start_error", str(e)))
            return None

    def _safely_stop_thread(self, thread, timeout=DAEMON_THREAD_JOIN_TIMEOUT):
        """
        安全停止线程
        
        Args:
            thread: 要停止的线程
            timeout: 等待线程终止的超时时间（秒）
            
        Returns:
            bool: 线程是否成功停止
        """
        if thread and thread.is_alive():
            try:
                thread.join(timeout=timeout)
                self.logger.info(I18n.get("thread_stopped", thread.name))
                return not thread.is_alive()
            except Exception as e:
                self.logger.error(I18n.get("daemon_thread_stop_error", str(e)))
                return False
        return True

    def _get_config(self, key, default=None):
        """
        获取配置值
        
        Args:
            key: 配置键名
            default: 默认值，如果配置不存在
            
        Returns:
            配置值或默认值
        """
        try:
            return self.db_manager.get_config(key)
        except Exception as e:
            self.logger.error(I18n.get("daemon_config_get_error", str(e)))
            return default

    def SvcStop(self):
        """
        停止服务
        """
        self.logger.info(I18n.get("SVC_STOP_SIGNAL"))
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        
        # 验证卸载标识
        if not self.security_manager.verify_uninstall_token():
            self.logger.warning(I18n.get("ILLEGAL_STOP"))
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            return
            
        self.logger.info(I18n.get("DAEMON_SVC_STOPPING"))
        self.running = False
        
        # 停止监控线程
        for mt in self.monitor_threads:
            mt["monitor"].stop_monitoring()
            self._safely_stop_thread(mt["thread"])
        
        # 清理资源
        self.log_manager.cleanup(script_name="daemon_service")
        win32event.SetEvent(self.service_stop_event)
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def SvcDoRun(self):
        """
        服务主运行方法
        """
        try:
            self.logger.info(I18n.get("DAEMON_SVC_STARTED"))
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            self._initialize_service()
            self._run_main_loop()
        except Exception as e:
            self.logger.exception(I18n.get("daemon_init_error", str(e)))
            self.SvcStop()
            raise
        finally:
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def _initialize_service(self):
        """
        初始化服务
        """
        # 删除token文件
        self.delete_token()
        # 启动监控线程
        for i, mt in enumerate(self.monitor_threads):
            thread_name = "main-reg-monitor" if i == 0 else f"internet-monitor-{i}"
            mt["thread"] = self._start_thread(mt["monitor"].start_monitoring, thread_name)

    def _run_main_loop(self):
        """
        运行服务主循环
        """
        # 等待初始化完成
        time.sleep(DAEMON_SERVICE_CHECK_DELAY)
        while self.running:
            try:
                if not self.security_manager.verify_uninstall_token():
                    # 获取服务状态
                    status = win32serviceutil.QueryServiceStatus(MAIN_SERVICE_NAME)
                    # 检查服务是否停止
                    if status[1] == win32service.SERVICE_STOPPED:
                        self.logger.info(I18n.get("MAIN_SVC_RESTART_ATTEMPT"))
                        # 尝试重新启动服务
                        win32serviceutil.StartService(MAIN_SERVICE_NAME)
                        self.logger.info(I18n.get("MAIN_SVC_RESTARTED"))
                time.sleep(1)
            except pywintypes.error as e:
                # 处理系统正在关机时的错误 (错误码 1115)
                if e.args[0] == 1115:
                    self.logger.warning(I18n.get("SYSTEM_SHUTDOWN_WARNING"))
                    win32event.WaitForSingleObject(self.service_stop_event, win32event.INFINITE)
                    break
                else:
                    # 记录其他异常
                    self.logger.exception(I18n.get("ERROR", str(e)))
            except Exception as e:
                self.logger.exception(I18n.get("daemon_main_loop_error", str(e)))
        
        # 等待停止事件
        win32event.WaitForSingleObject(self.service_stop_event, win32event.INFINITE)

    def delete_token(self):
        """
        删除卸载标记文件
        """
        try:
            if os.path.exists(TOKEN_PATH):
                os.remove(TOKEN_PATH)
                self.logger.info(I18n.get("FILE_DELETED", TOKEN_PATH))
        except Exception as e:
            self.logger.error(I18n.get("FILE_DELETE_ERROR", str(e)))
    
    def get_users_with_internet_settings(self):
        """
        获取系统中所有用户的 SID，检查是否存在对应的 Internet Settings 注册表项，
        并返回格式化的注册表路径列表
        """
        resume_handle = 0
        registry_paths = []
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        registry_paths.append({
            "reg_key": winreg.HKEY_LOCAL_MACHINE,
            "reg_value": f"SYSTEM\\CurrentControlSet\\Services\{MAIN_SERVICE_NAME}",
            "callback": self.service_start_change,
            "sub_key": SERVICE_SUB_KEY,
            "interval": SERVICE_MONITOR_INTERVAL
        })
        
        try:
            # 获取所有普通用户账户
            while True:
                users, _, resume_handle = win32net.NetUserEnum(
                    None,  # 本地计算机
                    0,     # 基本信息
                    win32netcon.FILTER_NORMAL_ACCOUNT,  # 普通账户
                    resume_handle,
                    win32netcon.MAX_PREFERRED_LENGTH
                )
                
                for user in users:
                    username = user['name']
                    try:
                        # 获取用户的 SID
                        sid, _, _ = win32security.LookupAccountName(None, username)
                        sid_string = win32security.ConvertSidToStringSid(sid)
                        # 检查该用户的 Internet Settings 注册表项是否存在
                        try:
                            # 尝试打开注册表项
                            key = winreg.OpenKey(
                                winreg.HKEY_USERS,
                                f"{sid_string}\\{reg_path}",
                                0,
                                winreg.KEY_READ
                            )
                            winreg.CloseKey(key)
                            # 如果成功打开，添加到结果列表
                            registry_paths.append({
                                "reg_key": winreg.HKEY_USERS,
                                "reg_value": f"{sid_string}\\{reg_path}",
                                "callback": self.on_registry_change,
                                "sub_key": INTERNET_SUB_KEY,
                                "interval": INTERNET_MONITOR_INTERVAL
                            })
                        except FileNotFoundError:
                            pass
                        except Exception as e:
                            print(f"检查 SID {sid_string} 的注册表时出错: {e}")
                    except Exception as e:
                        print(f"处理用户 {username} 时出错: {e}")
                if resume_handle == 0:
                    break
        except Exception as e:
            print(f"获取用户列表时出错: {e}")
        finally:
            return registry_paths

    def get_proxy_port(self):
        """
        获取代理端口
        
        Returns:
            int: 代理端口号，如果不存在则返回None
        """
        try:
            result = self.db_manager.fetchone("SELECT value FROM config WHERE key='proxy_port'")
            return int(result[0]) if result else None
        except Exception as e:
            self.logger.error(I18n.get("daemon_config_get_error", str(e)))
            return None
    
    def service_start_change(self, new_values):
        """
        处理服务启动类型变更
        
        Args:
            new_values: 新的注册表值
        """
        try:
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
            service = win32service.OpenService(scm, MAIN_SERVICE_NAME, win32service.SERVICE_ALL_ACCESS)
            if new_values.get("Start", "") != EXPECTED_VALUES["Start"]:
                self.logger.info(I18n.get("SVC_SETTINGS_CHANGED", new_values))
                win32service.ChangeServiceConfig(
                    service, 
                    win32service.SERVICE_NO_CHANGE, 
                    win32service.SERVICE_AUTO_START, 
                    win32service.SERVICE_ERROR_NORMAL, None, None, 0, None, None, None, None)
        except Exception as e:
            self.logger.exception(I18n.get("MAIN_SVC_CONFIG_ERROR", str(e)))
        finally:
            win32service.CloseServiceHandle(service)
            win32service.CloseServiceHandle(scm)

    def on_registry_change(self, new_values):
        """
        当注册表变化时执行的回调函数
        
        Args:
            new_values: 新的注册表值
        """
        self.logger.info(I18n.get("PROXY_SETTINGS_CHANGED", new_values))
        
        # 获取代理端口
        proxy_port = self.get_proxy_port()
        if not proxy_port:
            self.logger.error(I18n.get("daemon_config_get_error", "proxy_port not found"))
            return
            
        # 这里加入修正代理设置的逻辑
        # 如果检测到的值与预期不符，则修正代理设置
        expected_values = {
            "ProxyEnable": 1,  # 期望启用代理
            "ProxyServer": f"{SERVICE_HOST}:{proxy_port}",  # 期望的代理服务器
        }
        
        for key, monitor_values in new_values.items():
            if monitor_values != expected_values.get(key):
                self.logger.info(I18n.get("KEY_TAMPERED", key))
                try:
                    with FileLock(self.registry_paths['internet_value']):
                        with winreg.OpenKey(self.registry_paths['internet_key'], self.registry_paths['internet_value'], 0, winreg.KEY_ALL_ACCESS) as reg_key:
                            winreg.SetValueEx(reg_key, key, 0, winreg.REG_DWORD if key == "ProxyEnable" else winreg.REG_SZ, expected_values.get(key))
                            self.logger.info(I18n.get("KEY_CORRECTED", key))
                except Exception as e:
                    self.logger.exception(I18n.get("PROXY_CORRECTION_ERROR", str(e)))

if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(DaemonService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(DaemonService)

    # daemon_service = DaemonService([DAEMON_SERVICE_NAME])
    # daemon_service.main()
