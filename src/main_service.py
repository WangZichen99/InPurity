import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import threading
import subprocess
import winreg
import sys
import os
import psutil
import time
import logging
from logging.handlers import TimedRotatingFileHandler
import traceback
import random
import signal
from db_manager import DatabaseManager
from filelock import FileLock
from registry_monitor import RegistryMonitor
from constants import MITMDUMP_PATH, MAIN_SERVICE_NAME, DAEMON_SERVICE_NAME, LOG_PATH, SCRIPT_PATH, SERVICE_SUB_KEY

class InPurityService(win32serviceutil.ServiceFramework):
    _svc_name_ = MAIN_SERVICE_NAME
    _svc_display_name_ = "In Putiry Proxy Service"
    _svc_description_ = "In Putiry Proxy Main Service"
    HOST = '127.0.0.1'

    def __init__(self, args):
        self.logger, self.mitmproxy_logger = self._setup_logger()
        self.db_manager = DatabaseManager()
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.reg_dic = self.get_user_sid() # 获取用户信息和注册表信息
        # mitmproxy进程
        self.mitmproxy_process = None
        # 读取mitmproxy输出和错误线程
        self.stdout_thread = None
        self.stderr_thread = None
        # socket通信线程
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.HOST, self.get_socket_port()))
        self.server_socket.listen(1)
        self.server_socket.settimeout(None)
        self.socket_thread = None
        self.service_reg_monitor = RegistryMonitor(
            self.reg_dic['service_key'],
            self.reg_dic['service_value'],
            SERVICE_SUB_KEY,
            self.service_start_change,
            60000,
            MAIN_SERVICE_NAME) # 初始化注册表监控
        # self.stop_event = threading.Event() # 监控停止事件
        self.running = True

    def _setup_logger(self):
        if not os.path.exists(LOG_PATH):
            os.makedirs(LOG_PATH)
        # 主服务日志
        logger = logging.getLogger(MAIN_SERVICE_NAME)
        logger.setLevel(logging.INFO)
        handler = TimedRotatingFileHandler(
            os.path.join(LOG_PATH, 'in_purity_service.log'),
            when='midnight',
            interval=1,
            backupCount=90,
            encoding='utf-8'
        )
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        # mitmproxy日志
        mitmproxy_logger = logging.getLogger('mitmproxy')
        mitmproxy_logger.setLevel(logging.INFO)
        mitmproxy_handler = TimedRotatingFileHandler(
            os.path.join(LOG_PATH, 'mitmproxy.log'),
            when='midnight',
            interval=1,
            backupCount=90,
            encoding='utf-8')
        mitmproxy_logger.addHandler(mitmproxy_handler)
        return logger, mitmproxy_logger

    """
    def set_service_as_critical(self):
        '''
        设置服务为关键服务
        '''
        try:
            key_path = r"SYSTEM\CurrentControlSet\Services\{}".format(self._svc_name_)
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_ALL_ACCESS)
            try:
                service_type, _ = winreg.QueryValueEx(key, "Type")
                if service_type != 0x120:
                    winreg.SetValueEx(key, "Type", 0, winreg.REG_DWORD, 0x120)
                    self.logger.info('服务类型已更新为关键服务')
            except WindowsError:
                winreg.SetValueEx(key, "Type", 0, winreg.REG_DWORD, 0x120)
                self.logger.info('服务类型已设置为关键服务')
        except WindowsError as e:
            self.logger.error(f'设置关键服务失败: {str(e)}')
        finally:
            winreg.CloseKey(key)
    """

    def SvcDoRun(self):
        try:
            self.logger.info(f'{MAIN_SERVICE_NAME} 服务开始运行')
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            # 先检查是否有未正常关闭的mitmproxy进程，防止启动报错
            self.terminate_mitm_processes()
            self.start_socket()
            proxy_port = self.get_proxy_port()
            upstream_enable = self.get_upstream_enable()
            upstream_port = self.get_upstream_server() if upstream_enable else None
            # 修改操作系统代理设置
            self.setup_windows_proxy(proxy_port)
            # 启动mitmproxy代理
            self.start_mitmproxy(proxy_port, upstream_enable, upstream_port)
            # 监听服务启动类型
            self.service_reg_monitor_thread = threading.Thread(target=self.service_reg_monitor.start_monitoring, daemon=True)
            self.service_reg_monitor_thread.start()
            while self.running:
                # self.check_service()
                if self.mitmproxy_process and self.mitmproxy_process.poll() == 1:
                    self.logger.info("mitmproxy代理进程终止，正在重启")
                    self.stop_mitmproxy()
                    self.start_mitmproxy(self.get_proxy_port(), self.get_upstream_enable(), self.get_upstream_server())
                for _ in range(2):
                    if not self.running:
                        break
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

    def SvcStop(self):
        self.logger.info(f'正在停止 {MAIN_SERVICE_NAME} 服务...')
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        self.stop_mitmproxy()
        self.stop_socket()
        self.running = False
        self.service_reg_monitor.stop_monitoring()
        if self.service_reg_monitor_thread:
            self.service_reg_monitor_thread.join(timeout=10)

    """
    def is_service_running(self, service_name):
        '''
        检查服务是否运行
        '''
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
            if status[1] == win32service.SERVICE_STOPPED:
                self.logger.info(f"{MAIN_SERVICE_NAME} 已停止，尝试重启")
                # 尝试重新启动服务
                win32serviceutil.StartService(MAIN_SERVICE_NAME)
                self.logger.info(f"{MAIN_SERVICE_NAME} 服务已被重启")
        except Exception as e:
            self.logger.error(f"重启服务失败 {MAIN_SERVICE_NAME}: {e}")
    
    def _service_reg_monitor(self):
        self.service_reg_monitor.start_monitoring()

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

    def get_socket_port(self):
        socket_port = self.db_manager.get_config("socket_port")
        # socket_port = int(socket_port) if socket_port is not None else socket_port
        if socket_port and self.is_port_available(int(socket_port)):
            return int(socket_port)
        else:
            while not socket_port or not self.is_port_available(int(socket_port)):
                socket_port = random.randint(49152, 65535)
            self.db_manager.update_config("socket_port", socket_port)
            return socket_port

    def start_socket(self):
        """在单独的线程中监听套接字连接"""
        def socket_listener():
            self.logger.info("启动socket监听线程")
            while not self.server_stop_event.is_set():
                try:
                    conn, addr = self.server_socket.accept()
                    data = conn.recv(1024)
                    if data and data.decode().strip() == "RESTART":
                        self.logger.info("收到重启命令, 重启 mitmproxy.")
                        self.stop_mitmproxy()
                        self.start_mitmproxy(self.get_proxy_port(), self.get_upstream_enable(), self.get_upstream_server())
                    conn.close()
                except socket.error as e:
                    if not self.server_stop_event.is_set():
                        self.logger.error(f"socket错误：{str(e)}")
        # 创建并启动套接字监听线程
        self.server_stop_event = threading.Event()
        self.socket_thread = threading.Thread(target=socket_listener)
        self.socket_thread.start()

    def stop_socket(self):
        # 停止 socket 监听线程
        if self.socket_thread:
            self.server_stop_event.set()  # 触发停止事件
            self.server_socket.close()  # 关闭 socket
            self.socket_thread.join()

    def get_proxy_port(self):
        '''
        获取代理端口
        '''
        proxy_port = self.db_manager.get_config("proxy_port")
        self.logger.info(f'获取代理端口： {proxy_port}')
        return proxy_port if proxy_port and self.is_port_available(int(proxy_port)) else self.logger.info("请先设置代理端口并检查是否可用")
    
    def get_upstream_enable(self):
        '''
        获取代理端口
        '''
        upstream_enable = self.db_manager.get_config("upstream_enable")
        self.logger.info(f'获取是否启用上游代理： {upstream_enable}')
        return int(upstream_enable)
    
    def get_upstream_server(self):
        '''
        获取代理端口
        '''
        upstream_server = self.db_manager.get_config("upstream_server")
        self.logger.info(f'获取上游代理服务地址： {upstream_server}')
        return upstream_server if upstream_server else self.logger.info("请先设置上游代理服务地址")

    def get_mitmproxy_option(self):
        options = self.db_manager.get_all_options()
        formatted_options = []
        for option_name, option_value in options:
            formatted_options.append('--set')
            formatted_options.append(f"{option_name}={option_value}")
        self.logger.info(f'获取代理配置： {formatted_options}')
        return formatted_options

    def is_port_available(self, port):
        '''
        检查端口是否可用
        '''
        if not port:
            return False 
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
            self.logger.info(f'端口 {port} 可用')
            return True
        except socket.error:
            self.logger.info(f'端口 {port} 不可用：{socket.error}')
            return False

    def get_user_sid(self):
        self.username = self.db_manager.get_config("username")
        self.sid = self.db_manager.get_config("sid")
        self.logger.info(f"username：{self.username}")
        self.logger.info(f"sid：{self.sid}")
        key_type = winreg.HKEY_USERS if self.sid else winreg.HKEY_CURRENT_USER
        if key_type == winreg.HKEY_USERS:
            self.logger.info('key_type = HKEY_USERS')
        elif key_type == winreg.HKEY_CURRENT_USER:
            self.logger.info('key_type = HKEY_CURRENT_USER')
        key_path = f"{self.sid}\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" if self.sid else r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        self.logger.info(f"key_path = {key_path}")
        reg_dic = {
            "internet_key": key_type,
            "internet_value": key_path,
            "service_key": winreg.HKEY_LOCAL_MACHINE,
            "service_value": f"SYSTEM\\CurrentControlSet\\Services\{DAEMON_SERVICE_NAME}"
        }
        return reg_dic

    def setup_windows_proxy(self, proxy_port):
        '''
        设置windows代理
        '''
        with FileLock(self.reg_dic['internet_value']):
            with winreg.OpenKey(self.reg_dic['internet_key'], self.reg_dic['internet_value'], 0, winreg.KEY_ALL_ACCESS) as key:
                try:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"127.0.0.1:{proxy_port}")
                    proxy_override, _ = winreg.QueryValueEx(key, "ProxyOverride")
                    # 拆分并过滤掉包含 "127.0.0.1" 或 "localhost" 的值
                    proxy_override_list = proxy_override.split(';')
                    filtered_proxy_override = [entry for entry in proxy_override_list if "127.0.0.1" not in entry and "local" not in entry]
                    if len(proxy_override_list) > len(filtered_proxy_override):
                        # 重新合并为字符串
                        new_proxy_override = ';'.join(filtered_proxy_override)
                        # 设置新的 ProxyOverride
                        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, new_proxy_override)
                        self.logger.info(f'ProxyOverride={new_proxy_override}')
                    proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                    proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    self.logger.info(f'设置Windows代理: ProxyEnable={proxy_enable}, ProxyServer={proxy_server}')
                except Exception as e:
                    self.logger.error(f'设置Windows代理出错：{e}')
                    self.logger.error("Traceback: %s", traceback.format_exc())

    def start_mitmproxy(self, proxy_port, upstream_enable, upstream_server):
        '''
        启动mitmproxy
        '''
        cmd = [
            MITMDUMP_PATH,
            '-s', SCRIPT_PATH,
            '-p', str(proxy_port),
        ]
        if upstream_enable:
            cmd.extend(['--mode', 'upstream:' + str(upstream_server)])
        cmd.extend(self.get_mitmproxy_option())
        self.logger.info(f'执行命令：{cmd}')
        try:
            # 启动子进程
            self.mitmproxy_process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                bufsize=1,
                universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            # 使用非阻塞方式读取输出
            def read_output(pipe, logger, stop_event):
                while not stop_event.is_set():
                    line = pipe.readline()
                    if not line:
                        break
                    logger.info(line.strip())
            
            # 创建并启动读取输出的线程
            self.proxy_stop_event = threading.Event()
            self.stdout_thread = threading.Thread(target=read_output, args=(self.mitmproxy_process.stdout, self.mitmproxy_logger, self.proxy_stop_event))
            self.stderr_thread = threading.Thread(target=read_output, args=(self.mitmproxy_process.stderr, self.mitmproxy_logger, self.proxy_stop_event))
            self.stdout_thread.daemon = True
            self.stderr_thread.daemon = True
            self.stdout_thread.start()
            self.stderr_thread.start()
            
            # 等待一段时间，检查进程是否成功启动
            time.sleep(5)
            if self.mitmproxy_process.poll() is None:
                self.logger.info(f"mitmdump 启动成功，端口： {proxy_port}，上游代理： {upstream_enable}， 上游代理地址： {upstream_server}")
            else:
                self.logger.error("mitmdump 启动失败")
        except Exception as e:
            self.logger.error(f"执行命令时发生错误: {e}")
            self.logger.error("Traceback: %s", traceback.format_exc())

    def stop_mitmproxy(self):
        if self.mitmproxy_process:
            self.logger.info("停止mitmproxy进程...")
            self.mitmproxy_process.terminate()
            self.mitmproxy_process.wait(timeout=10) # 等待线程终止，最多10秒
            self.proxy_stop_event.set() # 通知读取线程停止
            # 关闭标准输出和标准错误流
            self.mitmproxy_process.stdout.close()
            self.mitmproxy_process.stderr.close()
            # 等待读取线程结束
            if self.stdout_thread:
                self.stdout_thread.join(timeout=5)
            if self.stderr_thread:
                self.stderr_thread.join(timeout=5)
            self.logger.info("mitmproxy进程和相关线程已停止")
            self.mitmproxy_process = None    
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'] in ('mitmdump.exe', 'mitmproxy.exe', 'run_mitmdump.exe') and proc.is_running():
                self.logger.info(f"{proc.info['name']}未停止")
                self.terminate_mitm_processes()

    def terminate_mitm_processes(self):
        # 遍历所有进程
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                # 检查进程名称是否为 mitmdump 或 mitmproxy
                if proc.info['name'] in ('mitmdump.exe', 'mitmproxy.exe', 'run_mitmdump.exe'):
                    self.logger.info(f"终止进程: {proc.info['name']} (PID: {proc.info['pid']})")
                    os.kill(proc.info['pid'], signal.SIGTERM)  # 发送终止信号
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
                self.logger.info(f"终止mitmproxy进程错误：{e}")

if __name__ == '__main__':
    # venv_path = "D:\\Workspace\\Python\\antiproxy\\.venv\\Lib\\site-packages"
    # sys.path.insert(0, venv_path)
    # import servicemanager
    # print("Python executable:", sys.executable)

    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(InPurityService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(InPurityService)

    # if len(sys.argv) == 1:
    #     # 本地测试逻辑
    #     service = InPurityService([MAIN_SERVICE_NAME])
    #     service.main()  # 直接运行服务的主逻辑
    # else:
    #     # Windows 服务管理的控制逻辑
    #     win32serviceutil.HandleCommandLine(InPurityService)
