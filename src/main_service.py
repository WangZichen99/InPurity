import os
import sys
import time
import signal
import psutil
import winreg
import random
import socket
import win32ts
import win32api
import win32con
import threading
import win32file
import subprocess
import win32event
import win32profile
import win32service
import win32process
import win32security
import servicemanager
from i18n import I18n
import win32serviceutil
from pathlib import Path
from log import LogManager
from filelock import FileLock
from security import SecurityManager
from db_manager import DatabaseManager
from registry_monitor import RegistryMonitor
from constants import (MITMDUMP_PATH, MAIN_SERVICE_NAME, DAEMON_SERVICE_NAME, 
                       SCRIPT_PATH, SERVICE_SUB_KEY, GUI_PATH, SYSTEM_PROCESSES,
                       SERVICE_HOST, GUI_PIPE_NAME, RANDOM_PORT_MIN, RANDOM_PORT_MAX,
                       DEFAULT_THREAD_TIMEOUT, MAX_USER_WAIT_SECONDS, EXPECTED_VALUES)

class InPurityService(win32serviceutil.ServiceFramework):
    _svc_name_ = MAIN_SERVICE_NAME
    _svc_display_name_ = "In Purity Proxy Service"
    _svc_description_ = "In Purity Proxy Main Service"

    def __init__(self, args):
        """
        初始化服务
        
        Args:
            args: 服务启动参数
        """
        self.db_manager = DatabaseManager()
        self.security_manager = SecurityManager()
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('MainService', 'main_service')
        self.mitmproxy_logger = self.log_manager.get_logger('Mitmproxy', 'mitmproxy')
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.service_stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.registry_paths = self.get_user_sid()  # 获取用户信息和注册表信息
        self.stop_event = threading.Event()
        self.gui_process = None
        self.gui_pipe = None
        # mitmproxy进程
        self.mitmproxy_process = None
        # 读取mitmproxy输出和错误线程
        self.proxy_stop_event = None
        self.stdout_thread = None
        self.stderr_thread = None
        # socket通信线程
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((SERVICE_HOST, self.get_socket_port()))
        self.server_socket.listen(1)
        self.server_socket.settimeout(None)
        self.socket_thread = None
        # 监听守护服务配置
        self.stop_daemon_thread = None
        self.service_reg_monitor = RegistryMonitor(
            self.registry_paths['service_key'],
            self.registry_paths['service_value'],
            SERVICE_SUB_KEY,
            self.service_start_change,
            60000,
            self.logger)
        self.service_reg_monitor_thread = None
        self.running = True

    def SvcDoRun(self):
        """
        服务主运行函数
        
        初始化并启动所有组件，包括mitmproxy、套接字通信和服务监控
        """
        try:
            self.logger.info(I18n.get("MAIN_SVC_START"))
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            
            # 初始化阶段
            # 先检查是否有未正常关闭的mitmproxy进程，防止启动报错
            self.terminate_mitm_processes()
            self.start_socket()
            # 在单独线程中启动GUI和创建管道，不阻塞主服务
            self._start_thread(self._gui_pipe_manager, "gui-pipe-manager")
            # 启动mitmproxy代理
            self.start_mitmproxy()
            # 监听服务启动类型
            self.monitor_daemon()
            
            # 运行阶段 - 主循环
            self._run_main_loop()
            
            # 等待停止事件
            win32event.WaitForSingleObject(self.service_stop_event, win32event.INFINITE)
        except Exception as e:
            self.logger.exception(I18n.get("ERROR", e))
            self.SvcStop()
            raise
        finally:
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)  # 错误时停止服务
            
    def _run_main_loop(self):
        """
        服务主循环，监控mitmproxy进程状态
        """
        while self.running:
            # 检查mitmproxy进程是否仍在运行
            if self.mitmproxy_process and self.mitmproxy_process.poll() is not None:
                self.logger.info(I18n.get("MITMPROXY_TERMINATED"))
                self.stop_mitmproxy()
                self.start_mitmproxy()
                
            # 每20秒检查一次，分为4次5秒的间隔，以便更快地响应停止请求
            for _ in range(4):
                if not self.running:
                    break
                time.sleep(5)

    def SvcStop(self):
        """
        处理服务停止请求
        
        验证停止请求合法性，关闭所有资源和线程
        """
        try:
            self.logger.info(I18n.get("SVC_STOP_SIGNAL"))
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            
            # 验证合法性
            if not self._verify_stop_request():
                return
                
            # 开始清理资源
            self.logger.info(I18n.get("MAIN_SVC_STOPPING"))
            self.stop_event.set()
            self.running = False
            
            # 按照依赖关系顺序停止组件
            self._stop_all_components()
            
        except Exception as e:
            self.logger.exception(I18n.get("ERROR", e))
        finally:
            # 确保最终清理
            self.log_manager.cleanup(script_name='main_service')
            win32event.SetEvent(self.service_stop_event)
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def _verify_stop_request(self):
        """
        验证停止请求的合法性
        
        Returns:
            bool: 如果请求合法则返回True，否则返回False
        """
        if not self.security_manager.verify_uninstall_token():
            self.logger.warning(I18n.get("ILLEGAL_STOP"))
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            return False
        return True
        
    def _stop_all_components(self):
        """
        按照依赖关系顺序停止所有组件
        """
        # 先停止mitmproxy，它依赖于其他组件
        self.stop_mitmproxy()

        # 停止套接字
        self.stop_socket()

        # 停止GUI进程
        self.stop_gui_process()

        # 最后停止守护程序监控
        self.stop_daemon()

    def _gui_pipe_manager(self):
        """
        管理GUI启动和管道连接的线程函数
        
        此函数在单独的线程中运行，负责启动GUI程序并建立管道连接
        如果失败，会定期重试，但不会阻塞主服务功能
        """
        while not self.stop_event.is_set() and (self.gui_process is None or self.gui_pipe is None):
            try:
                # 启动GUI进程
                if self.gui_process is None or not self.gui_process.is_running():
                    self.gui_process = self.launch_gui_process(GUI_PATH)
                
                if self.gui_process is not None and self.gui_pipe is None:
                    try:
                        self.gui_pipe = win32file.CreateFile(
                            GUI_PIPE_NAME,
                            win32file.GENERIC_WRITE,
                            0,
                            None,
                            win32file.OPEN_EXISTING,
                            0,
                            None
                        )
                        self.logger.info(I18n.get("PIPE_CREATED"))
                        # 成功连接，发送初始消息
                        self._send_to_gui(I18n.get("SERVICE_CONNECTED_TO_GUI"))
                        return  # 成功连接，退出函数
                    except Exception as e:
                        if isinstance(e, win32file.error) and e.args[0] == 2:  # 文件未找到
                            self.logger.info(I18n.get("WAITING_FOR_PIPE"))
                        else:
                            raise  # 其他错误重新抛出
                
            except Exception as e:
                self.logger.exception(I18n.get("GUI_PIPE_ERROR", str(e)))

            if self.gui_process is None or self.gui_pipe is None:
                time.sleep(5)

    def launch_gui_process(self, exe_path):
        """
        在用户上下文中启动GUI进程
        
        Args:
            exe_path (str): GUI可执行文件路径
            
        Returns:
            int or None: 启动的GUI进程ID，如果启动失败则返回None
        """
        try:
            # 首先检查是否已有GUI进程在运行
            gui_process_name = os.path.basename(exe_path)
            for proc in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    # 检查进程名称或可执行文件路径是否匹配
                    if (proc.info['name'] == gui_process_name or 
                        (proc.info['exe'] and os.path.normpath(proc.info['exe']) == os.path.normpath(exe_path))):
                        # 验证进程是否在活动用户会话中
                        session_id = win32ts.ProcessIdToSessionId(proc.info['pid'])
                        if session_id == win32ts.WTSGetActiveConsoleSessionId():
                            return proc
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            # 如果没有找到现有进程，则启动新进程
            work_dir = str(Path(exe_path).parent)
            sa = win32security.SECURITY_ATTRIBUTES()
            sa.bInheritHandle = 1
            # Create startup info
            startup_info = win32process.STARTUPINFO()
            startup_info.dwFlags = win32con.STARTF_USESHOWWINDOW
            startup_info.wShowWindow = win32con.SW_SHOW
            # 获取活动用户会话的进程ID
            user_pid = self.get_user_pid()
            if user_pid:
                # 打开用户进程和token
                process_handle = win32api.OpenProcess(
                    # win32con.PROCESS_QUERY_INFORMATION, 
                    win32con.PROCESS_ALL_ACCESS,
                    False, 
                    user_pid
                )
                # 获取用户token
                token_handle = win32security.OpenProcessToken(
                    process_handle,
                    win32con.TOKEN_DUPLICATE | win32con.TOKEN_QUERY |
                    win32con.TOKEN_ASSIGN_PRIMARY | win32con.TOKEN_ADJUST_DEFAULT |
                    win32con.TOKEN_ADJUST_SESSIONID | win32con.TOKEN_ADJUST_PRIVILEGES
                )
                # 复制token
                new_token = win32security.DuplicateTokenEx(
                    token_handle,
                    win32security.SecurityImpersonation,
                    win32con.TOKEN_ALL_ACCESS,
                    win32security.TokenPrimary
                )
                # 获取活动会话ID
                active_session_id = win32ts.WTSGetActiveConsoleSessionId()
                # 设置会话ID
                win32security.SetTokenInformation(
                    new_token, 
                    win32security.TokenSessionId, 
                    active_session_id
                )
                # 创建环境块
                env_block = win32profile.CreateEnvironmentBlock(token_handle, False)
                # 创建进程
                sa = win32security.SECURITY_ATTRIBUTES()
                sa.bInheritHandle = 1
                startup_info = win32process.STARTUPINFO()
                startup_info.dwFlags = win32con.STARTF_USESHOWWINDOW
                startup_info.wShowWindow = win32con.SW_SHOWNORMAL  # 使用SHOWNORMAL而不是SHOW
                # 设置更完整的创建标志
                creation_flags = win32con.CREATE_NEW_CONSOLE | win32con.CREATE_UNICODE_ENVIRONMENT
                creation_flags |= win32con.NORMAL_PRIORITY_CLASS  # 设置正常优先级
                # 创建进程
                process_handle, thread_handle, pid, tid = win32process.CreateProcessAsUser(
                    new_token,
                    exe_path,
                    None,
                    sa,
                    sa,
                    False,
                    creation_flags,
                    env_block,
                    work_dir,
                    startup_info
                )
                # 设置线程优先级
                win32process.SetThreadPriority(thread_handle, win32process.THREAD_PRIORITY_NORMAL)
                # 关闭句柄
                win32api.CloseHandle(process_handle)
                win32api.CloseHandle(thread_handle)
                win32api.CloseHandle(token_handle)
                self.logger.info(I18n.get("SUCCESS_LAUNCHED", pid))
                time.sleep(0.5)
                process = psutil.Process(pid)
                return process
            else:
                self.logger.info(I18n.get("NO_USER_CONTEXT"))
                return None
        except Exception as e:
            self.logger.exception(I18n.get("FAILED_LAUNCH", e))
            return None
            # raise

    def get_user_pid(self):
        """
        获取活动用户会话的进程ID
        
        查找符合系统进程条件且在活动控制台会话中的进程
        
        Returns:
            int or None: 找到的用户进程ID，如果未找到或超时则返回None
        """
        try:
            start_time = time.time()
            active_session_id = win32ts.WTSGetActiveConsoleSessionId()
            
            while time.time() - start_time < MAX_USER_WAIT_SECONDS:
                for proc in psutil.process_iter(['pid', 'name', 'exe']):
                    try:
                        exe_path = proc.info['exe']
                        if exe_path and any(exe_path.lower().endswith(proc_name) for proc_name in SYSTEM_PROCESSES):
                            # 仍需使用win32ts获取会话ID
                            session_id = win32ts.ProcessIdToSessionId(proc.info['pid'])
                            if session_id == active_session_id:
                                return proc.info['pid']
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue
                    except Exception as e:
                        self.logger.exception(I18n.get("ERROR", e))
                time.sleep(1)
                
            self.logger.warning(I18n.get("MAX_WAIT_EXCEEDED"))
            return None
        except Exception as e:
            self.logger.exception(I18n.get("FAILED_USER_CONTEXT", e))
            return None

    def _send_to_gui(self, message):
        """
        向GUI发送消息的安全方法
        
        Args:
            message (str): 要发送的消息
        """
        if not self.gui_pipe:
            return  # 如果没有管道连接，直接返回
            
        try:
            # 将消息转换为字节并发送
            message_bytes = message.encode() if isinstance(message, str) else message
            win32file.WriteFile(self.gui_pipe, message_bytes)
        except Exception as e:
            if e.args()[0] != 232:
                self.logger.exception(I18n.get("GUI_PIPE_WRITE_ERROR", str(e)))
            # 关闭失败的管道
            win32file.CloseHandle(self.gui_pipe)
            self.gui_pipe = None
            if not self.gui_process.is_running():
                self.gui_process = None

    def _start_thread(self, target, name, args=(), daemon=True):
        """
        统一的线程启动方法
        
        Args:
            target (callable): 线程执行的函数
            name (str): 线程名称
            args (tuple, optional): 传递给目标函数的参数。默认为()
            daemon (bool, optional): 是否设置为守护线程。默认为True
            
        Returns:
            threading.Thread: 已启动的线程对象
        """
        thread = threading.Thread(target=target, name=name, args=args)
        thread.daemon = daemon
        thread.start()
        self.logger.info(I18n.get("THREAD_STARTED", name))
        return thread
        
    def _safely_stop_thread(self, thread, event=None, timeout=None):
        """
        安全地停止线程，避免线程资源泄露
        
        Args:
            thread (Thread): 要停止的线程
            event (Event, optional): 线程停止事件。默认为None
            timeout (int, optional): 等待线程停止的超时时间(秒)。默认为None，使用类默认超时时间
            
        Returns:
            bool: 如果线程成功停止返回True，超时则返回False
        """
        if not thread:
            return True
            
        if event:
            event.set()
            
        if thread.is_alive():
            timeout = timeout or DEFAULT_THREAD_TIMEOUT
            thread.join(timeout=timeout)
            if thread.is_alive():
                self.logger.warning(I18n.get("THREAD_STOP_TIMEOUT", thread.name))
                return False
        return True

    def start_socket(self):
        """
        在单独的线程中监听套接字连接
        
        创建并启动套接字监听线程，处理接收到的命令
        """
        def socket_listener():
            self.logger.info(I18n.get("SOCKET_LISTEN_START"))
            while not self.stop_event.is_set():
                try:
                    # 接受连接
                    conn, addr = self.server_socket.accept()
                    try:
                        data = conn.recv(1024)
                        command = data.decode().strip()
                        if command == "RESTART":
                            self.logger.info(I18n.get("MITMPROXY_RESTART"))
                            self.stop_mitmproxy()
                            self.start_mitmproxy()
                    finally:
                        # 确保连接被关闭
                        conn.close()
                except socket.error as e:
                    if e.errno == 10054:
                        self.logger.info(I18n.get("REMOTE_CONN_CLOSED"))
                    else:
                        self.logger.exception(I18n.get("SOCKET_LISTEN_ERROR", e))
                    if self.stop_event.is_set():
                        break
            # 线程结束前清理
            try:
                self.server_socket.close()
                self.logger.info(I18n.get("SOCKET_THREAD_STOPPED"))
            except Exception as e:
                self.logger.exception(I18n.get("SOCKET_CLOSE_ERROR", e))
                
        # 创建并启动套接字监听线程
        self.socket_thread = self._start_thread(socket_listener, "socket-communication")

    def stop_socket(self):
        """
        停止套接字监听线程
        
        设置停止事件并发送空连接以解除accept()阻塞
        """
        # 停止 socket 监听线程
        try:
            if self.socket_thread:
                # 发送一个空连接来解除accept()阻塞
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.connect((SERVICE_HOST, self.server_socket.getsockname()[1]))
                except:
                    pass
                self._safely_stop_thread(self.socket_thread)
        except Exception as e:
            self.logger.exception(I18n.get("SOCKET_STOP_ERROR", e))

    def stop_gui_process(self):
        # 然后关闭GUI管道
        if self.gui_pipe:
            try:
                self.gui_pipe.close()
                self.gui_pipe = None
                self.logger.info(I18n.get("GUI_PIPE_CLOSED"))
            except Exception as e:
                self.logger.exception(I18n.get("GUI_PIPE_CLOSE_ERROR", e))
        # 关闭GUI进程
        if self.gui_process and self.gui_process.is_running():
            try:
                self.gui_process.terminate()
                self.gui_process = None
                self.logger.info(I18n.get("GUI_PROCESS_CLOSED"))
            except Exception as e:
                self.logger.exception(I18n.get("GUI_PROCESS_CLOSE_ERROR", e))

    def monitor_daemon(self):
        """
        监控守护服务状态
        
        创建线程监控守护服务，如果发现服务停止，尝试重新启动
        """
        def daemon_listener():
            time.sleep(10)
            while not self.stop_event.is_set():
                try:
                    if not self.security_manager.verify_uninstall_token():
                        # 获取服务状态
                        status = win32serviceutil.QueryServiceStatus(DAEMON_SERVICE_NAME)
                        # 检查服务是否停止
                        if status[1] == win32service.SERVICE_STOPPED:
                            self.logger.info(I18n.get("DAEMON_SVC_RESTART_ATTEMPT"))
                            # 尝试重新启动服务
                            win32serviceutil.StartService(DAEMON_SERVICE_NAME)
                            self.logger.info(I18n.get("DAEMON_SVC_RESTARTED"))
                            time.sleep(0.5)
                    time.sleep(0.5)
                except Exception as e:
                    # 处理系统正在关机时的错误 (错误码 1115)
                    if e.args[0] == 1115:
                        self.logger.warning(I18n.get("SYSTEM_SHUTDOWN_WARNING"))
                        break
                    else:
                        # 重新抛出其他异常
                        self.logger.exception(I18n.get("ERROR", e))
            self.logger.info(I18n.get("MONITOR_DAEMON_END"))

        self.stop_daemon_thread = self._start_thread(daemon_listener, "daemon-monitor")
        
        # 监听守护服务启动类型
        self.service_reg_monitor_thread = self._start_thread(
            self.service_reg_monitor.start_monitoring, 
            "daemon-reg-monitor"
        )

    def stop_daemon(self):
        """
        停止守护服务监控
        
        设置停止事件并安全地终止相关线程
        """
        self._safely_stop_thread(self.stop_daemon_thread)
        
        self.service_reg_monitor.stop_monitoring()
        self._safely_stop_thread(self.service_reg_monitor_thread)

    def _service_reg_monitor(self):
        self.service_reg_monitor.start_monitoring()

    def service_start_change(self, new_values):
        """
        处理服务启动类型变更事件
        
        Args:
            new_values (dict): 包含变更后服务配置的字典
        """
        try:
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
            service = win32service.OpenService(scm, DAEMON_SERVICE_NAME, win32service.SERVICE_ALL_ACCESS)
            if new_values.get("Start", "") != EXPECTED_VALUES["Start"]:
                self.logger.info(I18n.get("SVC_SETTINGS_CHANGED", new_values))
                win32service.ChangeServiceConfig(
                    service, 
                    win32service.SERVICE_NO_CHANGE, 
                    win32service.SERVICE_AUTO_START, 
                    win32service.SERVICE_ERROR_NORMAL, None, None, 0, None, None, None, None)
        except Exception as e:
            self.logger.exception(I18n.get("DAEMON_CONFIG_FAIL", e))
        finally:
            win32service.CloseServiceHandle(service)
            win32service.CloseServiceHandle(scm)

    def _get_config(self, config_name, default_value=None, validator=None, converter=None, error_message=None, success_message=None):
        """
        通用配置获取方法
        
        Args:
            config_name (str): 配置项名称
            default_value: 默认值，如未找到配置或验证失败时返回
            validator (callable, optional): 验证函数，验证配置值是否有效
            converter (callable, optional): 转换函数，将配置值转换为所需类型
            error_message (str, optional): 验证失败时记录的错误消息
            success_message (callable, optional): 成功获取配置时记录的消息及其参数
            
        Returns:
            配置值，经过转换和验证后的
        """
        config_value = self.db_manager.get_config(config_name)
        
        # 应用转换器
        if config_value is not None and converter:
            try:
                config_value = converter(config_value)
            except Exception as e:
                self.logger.warning(I18n.get("CONFIG_CONVERT_ERROR", config_name, str(e)))
                return default_value
        
        # 应用验证器
        if validator and not validator(config_value):
            if error_message:
                self.logger.info(error_message)
            return default_value
        
        # 记录成功消息
        if success_message and config_value is not None:
            self.logger.info(success_message(config_value))
            
        return config_value if config_value is not None else default_value

    def get_socket_port(self):
        """
        获取套接字通信端口
        
        如果配置的端口不可用，随机生成一个可用端口
        
        Returns:
            int: 可用的套接字通信端口
        """
        port_validator = lambda port: port and self.is_port_available(int(port))
        port_converter = int
        socket_port = self._get_config("socket_port", None, port_validator, port_converter)
        
        if socket_port is None:
            # 找到可用端口
            available_port = None
            while available_port is None:
                test_port = random.randint(RANDOM_PORT_MIN, RANDOM_PORT_MAX)
                if self.is_port_available(test_port):
                    available_port = test_port
            
            # 更新配置并返回
            self.db_manager.update_config("socket_port", available_port)
            socket_port = available_port
            
        return socket_port

    def get_proxy_port(self):
        """
        获取代理端口
        
        Returns:
            int or None: 可用的代理端口，如果没有可用端口则记录日志并返回None
        """
        port_validator = lambda port: port and self.is_port_available(int(port))
        port_converter = int
        return self._get_config(
            "proxy_port", 
            None,
            port_validator,
            port_converter,
            I18n.get("PROXY_PORT_CHECK"),
            lambda value: I18n.get("PROXY_PORT_GET", value)
        )

    def get_upstream_enable(self):
        """
        获取上游代理启用状态
        
        Returns:
            bool: 上游代理是否启用，True表示启用，False表示禁用
        """
        def bool_converter(value):
            return bool(int(value)) if value is not None else False
        
        return self._get_config(
            "upstream_enable",
            False,
            None,
            bool_converter,
            None,
            lambda value: I18n.get(
                "UPSTREAM_PROXY_STATUS", 
                I18n.get("ENABLE") if value else I18n.get("DISABLE")
            )
        )

    def get_upstream_server(self):
        """
        获取上游代理服务器地址
        
        Returns:
            str or None: 上游代理服务器地址，如果未配置则记录日志并返回None
        """
        return self._get_config(
            "upstream_server",
            None,
            None,
            None,
            I18n.get("UPSTREAM_PROXY_REQUIRED"),
            lambda value: I18n.get("UPSTREAM_PROXY_ADDRESS", value)
        )

    def get_mitmproxy_option(self):
        """
        获取mitmproxy的所有配置选项
        
        Returns:
            list: 格式化后的mitmproxy命令行选项列表
        """
        formatted_options = []
        options = self.db_manager.get_all_options()
        
        if not options:
            return formatted_options
            
        for option_name, option_value in options:
            formatted_options.append('--set')
            formatted_options.append(f"{option_name}={option_value}")
    
        self.logger.info(I18n.get("PROXY_CONFIG_GET", formatted_options))
        return formatted_options

    def is_port_available(self, port):
        """
        检查指定端口是否可用
        
        Args:
            port (int): 要检查的端口号
            
        Returns:
            bool: 如果端口可用则返回True，否则返回False
        """
        if not port:
            return False 
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
            self.logger.info(I18n.get("PORT_AVAILABLE", port))
            return True
        except socket.error:
            self.logger.info(I18n.get("PORT_UNAVAILABLE", port, socket.error))
            return False

    def get_user_sid(self):
        """
        获取用户SID和相关注册表信息
        
        Returns:
            dict: 包含注册表键和值路径的字典
        """
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
        """
        设置Windows系统代理
        
        Args:
            proxy_port (int): 代理服务器端口
        """
        with FileLock(self.registry_paths['internet_value']):
            try:
                with winreg.OpenKey(self.registry_paths['internet_key'], self.registry_paths['internet_value'], 0, winreg.KEY_ALL_ACCESS) as key:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"127.0.0.1:{proxy_port}")
                    proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                    proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    self.logger.info(I18n.get("WIN_PROXY_SET", proxy_enable, proxy_server))
            except Exception as e:
                self.logger.exception(I18n.get("WIN_PROXY_ERROR", e))

    def start_mitmproxy(self):
        """
        启动mitmproxy代理服务
        
        启动mitmproxy进程，设置命令行参数，并创建线程读取输出流
        """
        proxy_port = self.get_proxy_port()
        upstream_enable = self.get_upstream_enable()
        upstream_server = self.get_upstream_server() if upstream_enable else None
        cmd = [
            MITMDUMP_PATH,
            '-s', SCRIPT_PATH,
            '-p', str(proxy_port),
        ]
        if upstream_enable:
            cmd.extend(['--mode', 'upstream:' + str(upstream_server)])
        cmd.extend(self.get_mitmproxy_option())
        self.logger.info(I18n.get("EXECUTE_COMMAND", cmd))
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
                    if line:
                        message = line.strip()
                        logger.info(message)
                        self._send_to_gui(message)
            # 创建并启动读取输出的线程
            self.proxy_stop_event = threading.Event()
            self.stdout_thread = self._start_thread(
                read_output, 
                "mitmproxy-stdout", 
                args=(self.mitmproxy_process.stdout, self.mitmproxy_logger, self.proxy_stop_event)
            )
            self.stderr_thread = self._start_thread(
                read_output, 
                "mitmproxy-stderr", 
                args=(self.mitmproxy_process.stderr, self.mitmproxy_logger, self.proxy_stop_event)
            )
            # 等待一段时间，检查进程是否成功启动
            time.sleep(5)
            if self.mitmproxy_process.poll() is None:
                self.logger.info(I18n.get("MITMDUMP_START_SUCCESS", proxy_port, I18n.get("ENABLE") if upstream_enable else I18n.get("DISABLE"), upstream_server))
                # 修改操作系统代理设置
                self.setup_windows_proxy(proxy_port)
            else:
                self.logger.error(I18n.get("MITMDUMP_START_FAIL"))
        except Exception as e:
            self.logger.exception(I18n.get("COMMAND_EXEC_ERROR", e))

    def stop_mitmproxy(self):
        """
        停止mitmproxy代理服务
        
        终止mitmproxy进程，关闭相关线程和管道
        """
        if self.mitmproxy_process:
            self.logger.info(I18n.get("MITMPROXY_STOPPING"))
            self.mitmproxy_process.terminate()
            try:
                self.mitmproxy_process.wait(timeout=10) # 等待线程终止，最多10秒
            except subprocess.TimeoutExpired:
                self.logger.warning(I18n.get("FORCE_KILL_PROCESS"))
                self.mitmproxy_process.kill()
                
            if self.proxy_stop_event:
                self.proxy_stop_event.set() # 通知读取线程停止
                
            # 关闭标准输出和标准错误流
            try:
                self.mitmproxy_process.stdout.close()
                self.mitmproxy_process.stderr.close()
            except:
                pass
                
            # 安全停止读取线程
            self._safely_stop_thread(self.stdout_thread)
            self._safely_stop_thread(self.stderr_thread)
            
            self.logger.info(I18n.get("MITMPROXY_STOPPED"))
            self.mitmproxy_process = None
            
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'] in ('mitmdump.exe', 'mitmproxy.exe', 'run_mitmdump.exe') and proc.is_running():
                self.logger.info(I18n.get("PROCESS_NOT_STOPPED", proc.info['name']))
                self.terminate_mitm_processes()

    def terminate_mitm_processes(self):
        """
        终止所有mitmproxy相关进程
        
        遍历所有进程，查找并终止mitmdump.exe、mitmproxy.exe和run_mitmdump.exe进程
        """
        # 定义需要终止的进程名列表
        mitm_process_names = ('mitmdump.exe', 'mitmproxy.exe', 'run_mitmdump.exe')
        
        # 遍历所有进程
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                # 检查进程名称是否为 mitmdump 或 mitmproxy
                if proc.info['name'] in mitm_process_names:
                    self.logger.info(I18n.get("TERMINATE_PROCESS", proc.info['name'], proc.info['pid']))
                    os.kill(proc.info['pid'], signal.SIGTERM)  # 发送终止信号
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
                self.logger.info(I18n.get("MITMPROXY_TERM_ERROR", e))

if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(InPurityService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(InPurityService)

    # 本地测试逻辑
    # service = InPurityService([MAIN_SERVICE_NAME])
    # service.SvcDoRun()  # 直接运行服务的主逻辑
