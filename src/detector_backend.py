# detector_backend.py

import os
import sys
import psutil
import logging
import win32api
import win32con
import win32process
from db_manager import DatabaseManager
from typing import Optional, Dict, Set, List

# --- 特征配置 ---
ELECTRON_MODULES = {"node.dll"}
BROWSER_CORE_MODULES = {"chrome.dll", "msedge.dll", "xul.dll"}
BROWSER_CHILD_ARGS = {"--type=renderer", "--contentproc", "--type=utility", "--type=gpu-process"}
# 系统进程列表
SYSTEM_PROCESSES = {"explorer.exe", "svchost.exe", "winlogon.exe", "lsass.exe", "csrss.exe", "services.exe"}

class BackendDetector:
    """
    负责在后端（服务）执行非GUI相关的浏览器进程甄别。
    """
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.known_browsers: Dict[int, float] = {}
        self.known_non_browsers: Dict[int, float] = {}
        self.module_cache: Dict[str, Optional[Set[str]]] = {}
        self.logger = logger
        # 添加数据库管理器实例
        self.db_manager = DatabaseManager()
        # 缓存代理端口
        self._proxy_port = None

    def _log(self, message: str):
        if self.logger: self.logger.info(message.lstrip())
        else: print(message)

    def _get_proxy_port(self):
        """获取代理端口"""
        if self._proxy_port is not None:
            return self._proxy_port
            
        proxy_port = None
        try:
            proxy_port_str = self.db_manager.get_config("proxy_port")
            if proxy_port_str:
                proxy_port = int(proxy_port_str)
        except (ValueError, TypeError):
            pass

        if proxy_port is None:
            self._log("[警告] 无法获取代理端口，将不过滤指向代理的连接。")
            proxy_port = 0  # 设置为0，这样不会匹配任何端口
            
        self._proxy_port = proxy_port
        return proxy_port

    def _connects_to_proxy(self, pid: int, connections) -> bool:
        """
        检查进程是否连接到本地代理地址
        
        Args:
            pid: 进程ID
            connections: 网络连接列表
            
        Returns:
            bool: 如果进程连接到本地代理地址返回True，否则返回False
        """
        proxy_port = self._get_proxy_port()
        root_exe = psutil.Process(pid).exe()

        for conn in connections:
            if conn.status in [psutil.CONN_ESTABLISHED, psutil.CONN_SYN_SENT, psutil.CONN_SYN_RECV]:
                proc_exe = psutil.Process(conn.pid).exe()
                if conn.raddr and conn.raddr.ip == "127.0.0.1" and conn.raddr.port == proxy_port and proc_exe == root_exe:
                    # self._log(f"[信息] 检测到进程 {pid} 连接到代理 {conn.raddr.ip}:{conn.raddr.port}")
                    return True

        # if self.known_browsers.get(pid):
            # self._log(f"[信息] 检测到进程 {pid} 命中缓存，可能为浏览器进程。")
            # return True

        return False

    def update_cache_from_frontend(self, frontend_cache: dict):
        """用前端GUI确认的结果更新内部缓存。"""
        try:
            for item in frontend_cache.get("browsers", []):
                pid, ctime = item.get("pid"), item.get("ctime")
                if pid and ctime: self.known_browsers[pid] = ctime
            for item in frontend_cache.get("non_browsers", []):
                pid, ctime = item.get("pid"), item.get("ctime")
                if pid and ctime: self.known_non_browsers[pid] = ctime
            # if frontend_cache:
                # self._log("[缓存] 已根据GUI端确认结果更新本地缓存。")
        except Exception as e:
            self._log(f"[错误] 更新缓存失败: {e}")

    def _get_process_modules(self, p: psutil.Process) -> Optional[Set[str]]:
        exe_path = None
        try:
            exe_path = p.exe()
            if exe_path in self.module_cache: return self.module_cache[exe_path]
            modules = set()
            h_proc = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, p.pid)
            try:
                for h_mod in win32process.EnumProcessModules(h_proc):
                    mod_name = win32process.GetModuleFileNameEx(h_proc, h_mod)
                    modules.add(os.path.basename(mod_name).lower())
            finally:
                win32api.CloseHandle(h_proc)
            self.module_cache[exe_path] = modules
            return modules
        except (psutil.Error, win32api.error):
            if exe_path: self.module_cache[exe_path] = None
            return None

    @staticmethod
    def _find_root_process(p: psutil.Process) -> Optional[psutil.Process]:
        current_proc = p
        try:
            exe_path = current_proc.exe()
            for _ in range(10):
                parent = current_proc.parent()
                if parent is None or parent.exe() != exe_path: break
                current_proc = parent
            return current_proc
        except (psutil.Error, FileNotFoundError, PermissionError):
            return None

    def _is_system_process(self, proc: psutil.Process) -> bool:
        """
        检查进程是否为系统进程
        
        Args:
            proc: 进程对象
            
        Returns:
            bool: 如果是系统进程返回True，否则返回False
        """
        try:
            # 检查进程名称
            if proc.name().lower() in SYSTEM_PROCESSES:
                return True
                
            # 检查可执行文件路径
            exe_path = proc.exe().lower()
            if "windows\\system32\\" in exe_path or "windows\\syswow64\\" in exe_path:
                return True
                
            return False
        except (psutil.Error, AttributeError):
            return False

    def get_candidate_processes(self, port: int) -> List[Dict]:
        """
        执行所有后台检查，返回需要GUI进一步确认的候选进程PID列表。
        修改后的逻辑：
        1. 扫描所有建立网络连接的进程（不根据端口号或IP进行筛选）
        2. 检查是否命中缓存和是否具有浏览器特征
        3. 对于通过浏览器特征检查的进程，在添加到候选列表前检查其网络连接是否指向本地代理地址
        4. 只保留未指向本地代理地址的进程作为候选结果
        """
        candidates = []
        processed_root_pids = set()

        try:
            connections = psutil.net_connections(kind="inet")
        except psutil.AccessDenied:
            self._log("错误：需要管理员权限才能获取所有网络连接。")
            return []

        # 收集所有具有网络连接的进程PID（不再根据端口筛选）
        all_connected_pids = {c.pid for c in connections if c.pid}

        if not all_connected_pids:
            # self._log("[检测] 未发现任何具有网络连接的进程。")
            return []
            
        # self._log(f"[检测] 发现 {len(all_connected_pids)} 个具有网络连接的进程: {sorted(list(all_connected_pids))}")
        
        for pid in all_connected_pids:
            try:
                root_proc = self._find_root_process(psutil.Process(pid))
                if not root_proc or root_proc.pid in processed_root_pids:
                    continue
                
                processed_root_pids.add(root_proc.pid)
                
                # 跳过系统进程
                if self._is_system_process(root_proc):
                    # self._log(f"[系统进程] 跳过系统进程 PID={root_proc.pid} ({root_proc.name()})")
                    continue
                
                # 开始甄别
                pid = root_proc.pid
                create_time = root_proc.create_time()
                name = root_proc.name()
                
                if pid in self.known_browsers and self.known_browsers.get(pid) == create_time:
                    # 检查已知浏览器是否连接到代理
                    if not self._connects_to_proxy(pid, connections):
                        # self._log(f"\n[缓存命中] PID={pid} ({name}) 已知为浏览器且不连接到代理。")
                        candidates.append({"pid": pid, "name": name, "status": "known_browser"})
                    # else:
                        # self._log(f"\n[缓存命中] PID={pid} ({name}) 已知为浏览器但连接到代理，跳过。")
                    continue
                    
                if pid in self.known_non_browsers and self.known_non_browsers.get(pid) == create_time:
                    # self._log(f"\n[缓存命中] PID={pid} ({name}) 已知为非浏览器。")
                    continue

                # self._log(f"\n[后台甄别] 开始甄别候选根进程 PID={pid} ({name})")
                
                # 关卡1, 2, 3
                modules = self._get_process_modules(root_proc)
                if modules is None:
                    # self._log(f"  [后台失败] 无法获取模块列表。")
                    self.known_non_browsers[pid] = create_time
                    continue
                
                if any(mod in modules for mod in ELECTRON_MODULES) or any(mod.endswith(".node") for mod in modules):
                    # self._log(f"  [后台排除] 关卡1: 发现Electron/Node.js特征。")
                    self.known_non_browsers[pid] = create_time
                    continue
                
                if any(mod in modules for mod in BROWSER_CORE_MODULES):
                    # self._log(f"  [后台成功] 关卡2: 发现已知浏览器核心模块。")
                    # 在添加到候选列表前检查是否连接到代理
                    if not self._connects_to_proxy(pid, connections):
                        candidates.append({"pid": pid, "name": name, "status": "needs_gui_check"})
                    else:
                        # self._log(f"  [排除] PID={pid} 连接到代理，标记为已知浏览器。")
                        self.known_browsers[pid] = create_time
                    continue

                cmdline_str = " ".join(root_proc.cmdline())
                if "--type=" in cmdline_str or "--contentproc" in cmdline_str:
                    # self._log(f"  [后台失败] 关卡3: 根进程命令行包含子进程参数。")
                    self.known_non_browsers[pid] = create_time
                    continue

                # 关卡3: 检查子进程是否有浏览器特征参数
                child_has_browser_arg = False
                # self._log(f"  [子进程检查] PID={pid} 的子进程数量: {len(root_proc.children())}")
                for child in root_proc.children():
                    if not child.is_running():
                        continue
                    child_cmdline = " ".join(child.cmdline())
                    matched_args = [arg for arg in BROWSER_CHILD_ARGS if arg in child_cmdline]
                    if matched_args:
                        # self._log(f"    [子进程] PID={child.pid} 匹配到浏览器参数: {matched_args}")
                        child_has_browser_arg = True
                        break
                
                if not child_has_browser_arg:
                    # self._log(f"  [后台失败] 关卡3: 未在其子进程中找到浏览器特征参数。")
                    self.known_non_browsers[pid] = create_time
                    continue
                
                # self._log(f"  [后台通过] PID={pid} 通过所有后台检查。")
                # 在添加到候选列表前检查是否连接到代理
                if not self._connects_to_proxy(pid, connections):
                    self._log(f"  [添加候选] PID={pid} 不连接到代理，添加到候选列表。")
                    candidates.append({"pid": pid, "name": name, "status": "needs_gui_check"})
                else:
                    # self._log(f"  [排除] PID={pid} 连接到代理，标记为已知浏览器。")
                    self.known_browsers[pid] = create_time

            except psutil.NoSuchProcess:
                continue
        
        return candidates