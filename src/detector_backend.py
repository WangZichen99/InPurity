# detector_backend.py

import os
import sys
import logging
from typing import Optional, Dict, Set, List

# 确保在Windows上运行
# if sys.platform != "win32":
    # raise ImportError("This module is for Windows only.")

# try:
import psutil
import win32api
import win32con
import win32process
# except ImportError:
    # raise ImportError("Missing libraries. Please run 'pip install psutil pywin32'.")

# --- 特征配置 ---
ELECTRON_MODULES = {"node.dll"}
BROWSER_CORE_MODULES = {"chrome.dll", "msedge.dll", "xul.dll"}
BROWSER_CHILD_ARGS = {"--type=renderer", "--contentproc", "--type=utility", "--type=gpu-process"}

class BackendDetector:
    """
    负责在后端（服务）执行非GUI相关的浏览器进程甄别。
    """
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.known_browsers: Dict[int, float] = {}
        self.known_non_browsers: Dict[int, float] = {}
        self.module_cache: Dict[str, Optional[Set[str]]] = {}
        self.logger = logger

    def _log(self, message: str):
        if self.logger: self.logger.info(message.lstrip())
        else: print(message)

    def update_cache_from_frontend(self, frontend_cache: dict):
        """用前端GUI确认的结果更新内部缓存。"""
        try:
            for item in frontend_cache.get("browsers", []):
                pid, ctime = item.get("pid"), item.get("ctime")
                if pid and ctime: self.known_browsers[pid] = ctime
            for item in frontend_cache.get("non_browsers", []):
                pid, ctime = item.get("pid"), item.get("ctime")
                if pid and ctime: self.known_non_browsers[pid] = ctime
            if frontend_cache:
                self._log("[缓存] 已根据GUI端确认结果更新本地缓存。")
        except Exception as e:
            self._log(f"[错误] 更新缓存失败: {e}")

    def _get_process_modules(self, p: psutil.Process) -> Optional[Set[str]]:
        # ... (与之前版本相同)
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
        # ... (与之前版本相同)
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

    def get_candidate_processes(self, port: int) -> List[Dict]:
        """
        执行所有后台检查，返回需要GUI进一步确认的候选进程PID列表。
        """
        candidates = []
        processed_root_pids = set()

        try:
            connections = psutil.net_connections(kind="inet")
        except psutil.AccessDenied:
            self._log("错误：需要管理员权限才能获取所有网络连接。")
            return []

        initial_pids = {c.pid for c in connections if c.raddr and c.status == 'ESTABLISHED' and c.raddr.ip in ("127.0.0.1", "::1") and c.raddr.port == port and c.pid}

        if not initial_pids:
            self._log(f"[检测] 未发现任何进程连接到端口 {port}。")
            return []
            
        self._log(f"[检测] 发现 {len(initial_pids)} 个初始进程: {sorted(list(initial_pids))}")
        
        for pid in initial_pids:
            try:
                root_proc = self._find_root_process(psutil.Process(pid))
                if not root_proc or root_proc.pid in processed_root_pids:
                    continue
                
                processed_root_pids.add(root_proc.pid)
                
                # 开始甄别
                pid = root_proc.pid
                create_time = root_proc.create_time()
                name = root_proc.name()
                
                if pid in self.known_browsers and self.known_browsers.get(pid) == create_time:
                    self._log(f"\n[缓存命中] PID={pid} ({name}) 已知为浏览器。")
                    candidates.append({"pid": pid, "name": name, "status": "known_browser"})
                    continue
                if pid in self.known_non_browsers and self.known_non_browsers.get(pid) == create_time:
                    self._log(f"\n[缓存命中] PID={pid} ({name}) 已知为非浏览器。")
                    continue

                self._log(f"\n[后台甄别] 开始甄别候选根进程 PID={pid} ({name})")
                
                # 关卡1, 2, 3
                modules = self._get_process_modules(root_proc)
                if modules is None:
                    self._log(f"  [后台失败] 无法获取模块列表。")
                    self.known_non_browsers[pid] = create_time
                    continue
                
                if any(mod in modules for mod in ELECTRON_MODULES) or any(mod.endswith(".node") for mod in modules):
                    self._log(f"  [后台排除] 关卡1: 发现Electron/Node.js特征。")
                    self.known_non_browsers[pid] = create_time
                    continue
                
                if any(mod in modules for mod in BROWSER_CORE_MODULES):
                    self._log(f"  [后台成功] 关卡2: 发现已知浏览器核心模块。")
                    candidates.append({"pid": pid, "name": name, "status": "needs_gui_check"})
                    continue

                cmdline_str = " ".join(root_proc.cmdline())
                if "--type=" in cmdline_str or "--contentproc" in cmdline_str:
                    self._log(f"  [后台失败] 关卡3: 根进程命令行包含子进程参数。")
                    self.known_non_browsers[pid] = create_time
                    continue

                child_has_browser_arg = any(
                    any(arg in " ".join(c.cmdline()) for arg in BROWSER_CHILD_ARGS)
                    for c in root_proc.children(recursive=True) if c.is_running()
                )
                if not child_has_browser_arg:
                    self._log(f"  [后台失败] 关卡3: 未在其子进程中找到浏览器特征参数。")
                    self.known_non_browsers[pid] = create_time
                    continue
                
                self._log(f"  [后台通过] PID={pid} 通过所有后台检查，需要GUI确认。")
                candidates.append({"pid": pid, "name": name, "status": "needs_gui_check"})

            except psutil.NoSuchProcess:
                continue
        
        return candidates