import win32serviceutil
import win32service
import win32event
import servicemanager
import winreg
import logging
from logging.handlers import TimedRotatingFileHandler
import traceback
import os
import sys
import time
import threading
from filelock import FileLock
from constants import MAIN_SERVICE_NAME, DAEMON_SERVICE_NAME, LOG_PATH, INTERNET_SUB_KEY, SERVICE_SUB_KEY
from db_manager import DatabaseManager
from registry_monitor import RegistryMonitor

class DaemonService(win32serviceutil.ServiceFramework):
    _svc_name_ = DAEMON_SERVICE_NAME
    _svc_display_name_ = "Windows Event Notifier"
    _svc_description_ = "Handles system event notifications and forwards critical notifications to registered services for further action. This service is essential for the smooth operation of event-driven components in the system."

    def __init__(self, args):
        self.logger = self._setup_logger()
        self.db_manager = DatabaseManager()
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.reg_dic = self.get_user_sid()
        self.internet_reg_monitor = RegistryMonitor(
            self.reg_dic['internet_key'],
            self.reg_dic['internet_value'],
            INTERNET_SUB_KEY,
            self.on_registry_change,
            10000,
            DAEMON_SERVICE_NAME) # 初始化注册表监控
        self.service_reg_monitor = RegistryMonitor(
            self.reg_dic['service_key'],
            self.reg_dic['service_value'],
            SERVICE_SUB_KEY,
            self.service_start_change,
            60000,
            DAEMON_SERVICE_NAME) # 初始化注册表监控
        self.running = True

    def _setup_logger(self):
        if not os.path.exists(LOG_PATH):
            os.makedirs(LOG_PATH)
        logger = logging.getLogger(DAEMON_SERVICE_NAME)
        logger.setLevel(logging.INFO)
        handler = TimedRotatingFileHandler(
            os.path.join(LOG_PATH, 'daemon_service.log'),
            when='midnight',
            interval=1,
            backupCount=90,
            encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def SvcStop(self):
        self.logger.info(f'正在停止 {DAEMON_SERVICE_NAME} 服务...')
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        self.running = False
        self.internet_reg_monitor.stop_monitoring()
        if self.internet_reg_monitor_thread:
            self.internet_reg_monitor_thread.join(timeout=10)
        self.service_reg_monitor.stop_monitoring()
        if self.service_reg_monitor_thread:
            self.service_reg_monitor_thread.join(timeout=10)

    def SvcDoRun(self):
        try:
            self.logger.info(f'{DAEMON_SERVICE_NAME} 服务开始运行')
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            # 创建并启动一个线程来运行 registry_monitor 的 start_monitoring 方法
            self.internet_reg_monitor_thread = threading.Thread(target=self.internet_reg_monitor.start_monitoring, daemon=True)
            self.internet_reg_monitor_thread.start()
            # 监听服务启动类型
            self.service_reg_monitor_thread = threading.Thread(target=self.service_reg_monitor.start_monitoring, daemon=True)
            self.service_reg_monitor_thread.start()
            # 定时检查主服务状态
            while self.running:
                self.check_service()
                time.sleep(10)
            # 等待停止事件
            # win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)
        except Exception as e:
            self.logger.error("An error occurred: %s", str(e))
            self.logger.error("Traceback: %s", traceback.format_exc())
            self.SvcStop()
            raise
        finally:
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)  # 错误时停止服务

    """
    def is_service_running(self, service_name):
        # for proc in psutil.process_iter(['pid', 'name']):
        #     if proc.info['name'] == service_name:
        #         return True
        for service in psutil.win_service_iter():
            if service.name() == service_name:
                return service.status() == 'running'
        return False
    """

    def check_service(self):
        try:
            # 获取服务状态
            status = win32serviceutil.QueryServiceStatus(MAIN_SERVICE_NAME)
            # 检查服务是否停止
            # self.logger.info(f"检测状态SERVICE_STOP_PENDING {status[1] == win32service.SERVICE_STOP_PENDING}")
            # self.logger.info(f"检测状态SERVICE_STOPPED {status[1] == win32service.SERVICE_STOPPED}")
            if status[1] == win32service.SERVICE_STOPPED:
                self.logger.info(f"{MAIN_SERVICE_NAME} 已停止，尝试重启")
                # 尝试重新启动服务
                win32serviceutil.StartService(MAIN_SERVICE_NAME)
                self.logger.info(f"{MAIN_SERVICE_NAME} 服务已被重启")
        except Exception as e:
            self.logger.error(f"重启服务失败 {MAIN_SERVICE_NAME}: {e}")

    def _internet_reg_monitor(self):
        self.internet_reg_monitor.start_monitoring()
    
    def _service_reg_monitor(self):
        self.service_reg_monitor.start_monitoring()

    def get_user_sid(self):
        # username = self.db_manager.get_config("username")
        reg_dic = {}
        sid = self.db_manager.get_config("sid")
        reg_dic['internet_key'] = winreg.HKEY_USERS if sid else winreg.HKEY_CURRENT_USER
        reg_dic['internet_value'] = f"{sid}\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" if sid else r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        reg_dic['service_key'] = winreg.HKEY_LOCAL_MACHINE
        reg_dic['service_value'] = f"SYSTEM\\CurrentControlSet\\Services\{MAIN_SERVICE_NAME}"
        return reg_dic

    def get_proxy_port(self):
        # 获取用户端口
        result = self.db_manager.fetchone("SELECT value FROM config WHERE key='proxy_port'")
        return int(result[0]) if result else None
    
    def service_start_change(self, new_values):
        self.logger.info(f"检测到代理设置变化，新值: {new_values}")
        expected_values = {"Start": 0x00000002}
        for key, monitor_values in new_values.items():
            if monitor_values != expected_values.get(key):
                logging.info(f"{key} 被篡改，正在修正...")
                with FileLock(self.reg_dic['service_value']):
                    with winreg.OpenKey(self.reg_dic['service_key'], self.reg_dic['service_value'], 0, winreg.KEY_ALL_ACCESS) as reg_key:
                        try:
                            winreg.SetValueEx(reg_key, key, 0, winreg.REG_DWORD, expected_values.get(key))
                            logging.info(f"{key} 修正完成")
                        except Exception as e:
                            self.logger.error(f'修正代理设置出错: {e}')
                            self.logger.error("Traceback: %s", traceback.format_exc())

    def on_registry_change(self, new_values):
        """当注册表变化时执行的回调函数"""
        self.logger.info(f"检测到代理设置变化，新值: {new_values}")
        # 这里加入修正代理设置的逻辑
        # 如果检测到的值与预期不符，则修正代理设置
        expected_values = {
            "ProxyEnable": 1,  # 期望启用代理
            "ProxyServer": "127.0.0.1:" + str(self.get_proxy_port()),  # 期望的代理服务器
        }
        for key, monitor_values in new_values.items():
            if key == "ProxyOverride":
                # 拆分并过滤掉包含 "127.0.0.1" 或 "localhost" 的值
                proxy_override_list = monitor_values.split(';')
                filtered_proxy_override = [entry for entry in proxy_override_list if "127.0.0.1" not in entry and "local" not in entry]
                if len(proxy_override_list) > len(filtered_proxy_override):
                    logging.info(f"{key} 被篡改，正在修正...")
                    # 重新合并为字符串
                    new_proxy_override = ';'.join(filtered_proxy_override)
                    # 设置新的 ProxyOverride
                    with FileLock(self.reg_dic['internet_value']):
                        with winreg.OpenKey(self.reg_dic['internet_key'], self.reg_dic['internet_value'], 0, winreg.KEY_ALL_ACCESS) as reg_key:
                            try:
                                winreg.SetValueEx(reg_key, key, 0, winreg.REG_SZ, new_proxy_override)
                                logging.info(f"{key} 修正完成")
                            except Exception as e:
                                self.logger.error(f'修正代理设置出错: {e}')
                                self.logger.error("Traceback: %s", traceback.format_exc())
            elif monitor_values != expected_values.get(key):
                logging.info(f"{key} 被篡改，正在修正...")
                with FileLock(self.reg_dic['internet_value']):
                    with winreg.OpenKey(self.reg_dic['internet_key'], self.reg_dic['internet_value'], 0, winreg.KEY_ALL_ACCESS) as reg_key:
                        try:
                            winreg.SetValueEx(reg_key, key, 0, winreg.REG_DWORD if key == "ProxyEnable" else winreg.REG_SZ, expected_values.get(key))
                            logging.info(f"{key} 修正完成")
                        except Exception as e:
                            self.logger.error(f'修正代理设置出错: {e}')
                            self.logger.error("Traceback: %s", traceback.format_exc())

if __name__ == '__main__':
    # venv_path = "D:\\Workspace\\Python\\antiproxy\\.venv\\Lib\\site-packages"
    # sys.path.insert(0, venv_path)
    # import servicemanager

    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(DaemonService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(DaemonService)

    # daemon_service = DaemonService([DAEMON_SERVICE_NAME])
    # daemon_service.main()
