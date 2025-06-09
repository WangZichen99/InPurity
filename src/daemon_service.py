import os
import sys
import time
import winreg
import win32net
import functools
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
    SERVICE_MONITOR_INTERVAL, EXPECTED_VALUES, SERVICE_HOST, DEFAULT_CONFIG
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
        self.running = True
        
        # 初始化线程集合和线程锁
        self.monitor_threads = {}  # 使用字典而不是列表，键为用户SID或特殊标识符
        self.monitor_threads_lock = threading.Lock()  # 添加线程锁保护线程字典
        
        # 添加主服务监控（这个是固定的）
        self._add_service_monitor()
        
        # 用户扫描线程
        self.user_scanner_thread = None

    def _add_service_monitor(self):
        """添加主服务监控（固定的）"""
        service_monitor = RegistryMonitor(
            winreg.HKEY_LOCAL_MACHINE,
            f"SYSTEM\\CurrentControlSet\\Services\{MAIN_SERVICE_NAME}",
            SERVICE_SUB_KEY,
            self.service_start_change,
            SERVICE_MONITOR_INTERVAL,
            self.logger
        )
        
        with self.monitor_threads_lock:
            self.monitor_threads["main_service"] = {
                "thread": None,
                "monitor": service_monitor,
                "sid": "main_service"  # 使用特殊标识符
            }
    
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
            self.logger.exception(I18n.get("daemon_thread_start_error", str(e)))
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
                self.logger.exception(I18n.get("daemon_thread_stop_error", str(e)))
                return False
        return True

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
        
        # 先停止用户扫描线程
        self._safely_stop_thread(self.user_scanner_thread)
        
        # 停止所有监控线程
        with self.monitor_threads_lock:
            for sid, info in list(self.monitor_threads.items()):
                try:
                    info["monitor"].stop_monitoring()
                    self._safely_stop_thread(info["thread"])
                except Exception as e:
                    self.logger.exception(I18n.get("THREAD_STOP_ERROR", sid, str(e)))
            
            # 清空线程字典
            self.monitor_threads.clear()
        
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
        
        # 启动主服务监控线程
        main_monitor = self.monitor_threads.get("main_service")
        if main_monitor:
            main_monitor["thread"] = self._start_thread(
                main_monitor["monitor"].start_monitoring, 
                "main-service-monitor"
            )
        
        # 启动用户扫描线程
        self.user_scanner_thread = self._start_thread(
            self._user_scanner_loop, 
            "user-scanner",
            (8,)  # 8秒扫描间隔
        )

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
            self.logger.exception(I18n.get("FILE_DELETE_ERROR", str(e)))

    def get_proxy_port(self):
        """
        获取代理端口
        
        Returns:
            int: 代理端口号，如果不存在则返回None
        """
        try:
            result = self.db_manager.fetchone("SELECT value FROM config WHERE key='proxy_port'")
            if not result:
                result = DEFAULT_CONFIG["proxy_port"]
            return int(result[0]) 
        except Exception as e:
            self.logger.exception(I18n.get("daemon_config_get_error", str(e)))
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

    def _set_windows_proxy(self, reg_key, reg_value):
        """
        设置指定注册表项的 Windows 代理（ProxyEnable=1, ProxyServer=...）
        Args:
            reg_key: 注册表根键
            reg_value: 注册表路径
        Returns:
            bool: 设置成功返回True，否则False
        """
        proxy_port = self.get_proxy_port()
        if not proxy_port:
            self.logger.error(I18n.get("daemon_config_get_error", "proxy_port not found"))
            return False
        try:
            with FileLock(reg_value):
                with winreg.OpenKey(reg_key, reg_value, 0, winreg.KEY_ALL_ACCESS) as key:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{SERVICE_HOST}:{proxy_port}")
                    self.logger.info(I18n.get("WIN_PROXY_SET", 1, f"{SERVICE_HOST}:{proxy_port}"))
            return True
        except Exception as e:
            self.logger.exception(I18n.get("WIN_PROXY_ERROR", str(e)))
            return False

    def on_registry_change(self, new_values, sid, reg_key, reg_value):
        """
        当注册表变化时执行的回调函数（带用户上下文）
        Args:
            new_values: 新的注册表值
            sid: 用户SID
            reg_key: 注册表根键
            reg_value: 注册表路径
        """
        self.logger.info(I18n.get("PROXY_SETTINGS_CHANGED", f"SID={sid}, {new_values}"))
        expected_values = {
            "ProxyEnable": 1,
            "ProxyServer": f"{SERVICE_HOST}:{self.get_proxy_port()}",
        }

        for key, monitor_value in new_values.items():
            if monitor_value != expected_values.get(key):
                self.logger.info(I18n.get("KEY_TAMPERED", key))
                result = self._set_windows_proxy(reg_key, reg_value)
                if result:
                    self.logger.info(I18n.get("KEY_CORRECTED", key))
                    break

    def _user_scanner_loop(self, interval=8):
        """
        定期扫描用户并管理监控线程
        
        Args:
            interval: 扫描间隔（秒）
        """
        while self.running:
            try:
                # 扫描当前系统中的所有用户注册表项
                current_users = self._scan_users_internet_settings()
                
                # 获取当前SID列表（除了主服务监控）
                with self.monitor_threads_lock:
                    monitored_sids = [
                        info["sid"] for sid, info in self.monitor_threads.items() 
                        if sid != "main_service"
                    ]
                
                # 找出需要添加的新用户
                new_users = [user for user in current_users if user["sid"] not in monitored_sids]
                
                # 找出需要移除的用户
                current_sids = [user["sid"] for user in current_users]
                removed_sids = [sid for sid in monitored_sids if sid not in current_sids]
                
                # 添加新用户的监控
                for user in new_users:
                    self._add_user_monitor(user)
                
                # 移除已删除用户的监控
                for sid in removed_sids:
                    self._remove_user_monitor(sid)
                
                if new_users or removed_sids:
                    # 记录当前监控状态
                    with self.monitor_threads_lock:
                        self.logger.info(I18n.get(
                            "MONITOR_STATUS", 
                            len(self.monitor_threads) - 1,  # 减去主服务监控
                            len(new_users),
                            len(removed_sids)
                        ))
                
            except Exception as e:
                self.logger.exception(I18n.get("USER_SCANNER_ERROR", str(e)))
            
            # 等待下一次扫描
            for _ in range(interval):
                if not self.running:
                    break
                time.sleep(1)
    
    def _scan_users_internet_settings(self):
        """
        扫描系统中所有用户的Internet Settings注册表项
        
        Returns:
            list: 包含用户SID和注册表路径的字典列表
        """
        users_info = []
        resume_handle = 0
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        # 获取已监控的SID集合
        with self.monitor_threads_lock:
            monitored_sids = set(self.monitor_threads.keys())

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
                        # 获取用户的SID
                        sid, _, _ = win32security.LookupAccountName(None, username)
                        sid_string = win32security.ConvertSidToStringSid(sid)

                        # 如果已经在监控列表中，直接追加
                        if sid_string in monitored_sids:
                            users_info.append({
                                "sid": sid_string,
                                "username": username,
                                "reg_key": winreg.HKEY_USERS,
                                "reg_value": f"{sid_string}\\{reg_path}",
                                "sub_key": INTERNET_SUB_KEY,
                                "interval": INTERNET_MONITOR_INTERVAL
                            })
                            continue

                        # 检查该用户的Internet Settings注册表项是否存在
                        try:
                            key = winreg.OpenKey(
                                winreg.HKEY_USERS,
                                f"{sid_string}\\{reg_path}",
                                0,
                                winreg.KEY_READ
                            )
                            winreg.CloseKey(key)

                            # 如果成功打开，添加到结果列表
                            users_info.append({
                                "sid": sid_string,
                                "username": username,
                                "reg_key": winreg.HKEY_USERS,
                                "reg_value": f"{sid_string}\\{reg_path}",
                                "sub_key": INTERNET_SUB_KEY,
                                "interval": INTERNET_MONITOR_INTERVAL
                            })
                        except FileNotFoundError:
                            pass
                        except Exception as e:
                            self.logger.exception(I18n.get("REGISTRY_CHECK_ERROR", sid_string, str(e)))
                    except Exception as e:
                        self.logger.exception(I18n.get("USER_PROCESS_ERROR", username, str(e)))

                if resume_handle == 0:
                    break
        except Exception as e:
            self.logger.exception(I18n.get("USER_ENUM_ERROR", str(e)))

        return users_info
    
    def _add_user_monitor(self, user_info):
        """
        为用户添加注册表监控
        Args:
            user_info: 用户信息字典
        """
        try:
            sid = user_info["sid"]
            username = user_info["username"]
            reg_key = user_info["reg_key"]
            reg_value = user_info["reg_value"]

            # 先设置注册表代理项
            self._set_windows_proxy(reg_key, reg_value)

            # 使用partial将用户信息绑定到回调
            callback = functools.partial(self.on_registry_change, sid=sid, reg_key=reg_key, reg_value=reg_value)

            monitor = RegistryMonitor(
                reg_key,
                reg_value,
                user_info["sub_key"],
                callback,
                user_info["interval"],
                self.logger
            )
            thread = self._start_thread(
                monitor.start_monitoring,
                f"monitor-{username[:10]}"
            )
            with self.monitor_threads_lock:
                self.monitor_threads[sid] = {
                    "thread": thread,
                    "monitor": monitor,
                    "sid": sid,
                    "username": username
                }
            self.logger.info(I18n.get("USER_MONITOR_ADDED", username, sid))
        except Exception as e:
            self.logger.exception(I18n.get("ADD_MONITOR_ERROR", user_info.get("username", "unknown"), str(e)))
    
    def _remove_user_monitor(self, sid):
        """
        移除用户的注册表监控
        
        Args:
            sid: 用户SID
        """
        try:
            # 从字典中获取监控信息
            with self.monitor_threads_lock:
                monitor_info = self.monitor_threads.get(sid)
                if not monitor_info:
                    return
                
                username = monitor_info.get("username", "unknown")
                
                # 停止监控
                monitor_info["monitor"].stop_monitoring()
                
                # 安全停止线程
                self._safely_stop_thread(monitor_info["thread"])
                
                # 从字典中移除
                del self.monitor_threads[sid]
            
            self.logger.info(I18n.get("USER_MONITOR_REMOVED", username, sid))
        except Exception as e:
            self.logger.exception(I18n.get("REMOVE_MONITOR_ERROR", sid, str(e)))

if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(DaemonService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(DaemonService)

    # daemon_service = DaemonService([DAEMON_SERVICE_NAME])
    # daemon_service.main()
