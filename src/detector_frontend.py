# detector_frontend.py

# import sys
import logging
from typing import Optional

# 确保在Windows上运行
# if sys.platform != "win32":
#     raise ImportError("This module is for Windows only.")

# try:
import psutil
# import win32gui
import win32process
import win32con
import win32api
import ctypes
from ctypes import wintypes
# except ImportError:
    # raise ImportError("Missing libraries. Please run 'pip install psutil pywin32'.")
    
# 使用ctypes替换win32gui
_user32 = ctypes.windll.user32
EnumWindows = _user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetParent = _user32.GetParent
GetWindowTextLengthW = _user32.GetWindowTextLengthW
IsWindowVisible = _user32.IsWindowVisible

class FrontendActions:
    """
    负责在前端（GUI）执行需要用户会话权限的操作。
    """
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger

    def _log(self, message: str):
        if self.logger: self.logger.info(message)
        else: print(message)

    def has_visible_main_window(self, pid: int) -> bool:
        """[ctypes实现] 检查进程是否有可见主窗口。"""
        handles = []
        def enum_windows_callback(hwnd, _):
            if IsWindowVisible(hwnd) and GetWindowTextLengthW(hwnd) > 0:
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == found_pid and GetParent(hwnd) == 0:
                    handles.append(hwnd)
            return True
        try:
            EnumWindows(EnumWindowsProc(enum_windows_callback), 0)
            return bool(handles)
        except Exception as e:
            self._log(f"检查窗口时出错 PID={pid}: {e}")
            return False

    def close_gracefully(self, pid: int):
        """[pywin32实现] 尝试优雅关闭进程。"""
        try:
            p = psutil.Process(pid)
            name = p.name()
            self._log(f"  -> 尝试优雅关闭 PID={pid} ({name})")
            
            # 使用ctypes查找窗口
            hwnd = self.has_visible_main_window(pid) and self._get_main_window_handle(pid)

            if hwnd:
                win32api.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                self._log(f"✅ 已向 PID={pid} 发送 WM_CLOSE 关闭请求。")
            else:
                self._log(f"  [警告] 未能找到 PID={pid} 的主窗口，将直接强制关闭。")
                p.terminate()
        except psutil.NoSuchProcess:
            pass # 进程已不存在
        except Exception as e:
            self._log(f"❌ 关闭 PID={pid} 时发生错误: {e}")

    def _get_main_window_handle(self, pid: int) -> Optional[int]:
        # 这是has_visible_main_window的一个变体，返回句柄本身
        handles = []
        # ... (与has_visible_main_window内部逻辑几乎一样，只是返回handle[0])
        def enum_windows_callback(hwnd, _):
            if IsWindowVisible(hwnd) and GetWindowTextLengthW(hwnd) > 0:
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == found_pid and GetParent(hwnd) == 0:
                    handles.append(hwnd)
            return True
        try:
            EnumWindows(EnumWindowsProc(enum_windows_callback), 0)
            return handles[0] if handles else None
        except Exception:
            return None