import ctypes
import winreg
import logging
import win32api
import traceback
import win32event
from ctypes import wintypes
from filelock import FileLock

KEY_NOTIFY = 0x0010
REG_NOTIFY_CHANGE_LAST_SET = 0x00000004

# 转换
WINREG_2_CTYPES = {
    winreg.HKEY_CURRENT_USER: 0x80000001,
    winreg.HKEY_LOCAL_MACHINE: 0x80000002,
    winreg.HKEY_USERS: 0x80000003
}

class RegistryMonitor:
    def __init__(self, registry_type, registry_path, sub_key, callback, wait_millis, log_name):
        self.registry_type = WINREG_2_CTYPES.get(registry_type)
        self.registry_path = registry_path
        self.sub_key = sub_key
        self.callback = callback
        self.wait_millis = wait_millis
        self.hkey = None
        self.event = win32event.CreateEvent(None, 0, 0, None)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.logger = logging.getLogger(log_name)

    def start_monitoring(self):
        # 打开注册表项
        self.hkey = self._open_registry_key(self.registry_type, self.registry_path)
        if self.hkey is None:
            return
        # 开始监听注册表项的变化
        self.logger.info(f"开始监听 {self.hkey}")
        self._monitor_registry_change()

    def _open_registry_key(self, hive, subkey):
        try:
            with FileLock(self.registry_path):
                # 使用 winreg.OpenKey 打开注册表项
                hkey = winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | winreg.KEY_NOTIFY)
                return hkey
        except Exception as e:
            self.logger.error(f"无法打开注册表项: {self.registry_path}, 错误: {e}")
            return None

    def _read_registry_values(self):
        """读取代理设置的值"""
        values = {}
        for value_name in self.sub_key:
            try:
                # 获取值和类型
                value, regtype = winreg.QueryValueEx(self.hkey, value_name)
                # 根据类型处理值
                if regtype == winreg.REG_SZ:
                    values[value_name] = value
                elif regtype == winreg.REG_DWORD:
                    values[value_name] = value
                else:
                    self.logger.warning(f"未处理的注册表类型: {regtype} 对于值: {value_name}")
                    values[value_name] = None
            except Exception as e:
                self.logger.error(f"无法读取注册表值: {value_name}, 错误: {e}")
                self.logger.error("Traceback: %s", traceback.format_exc())
                values[value_name] = None
        return values

    def _monitor_registry_change(self):
        while True:
            # 获取 self.event 的底层 Windows 句柄
            event_handle = wintypes.HANDLE(self.event.handle)
            # 调用 RegNotifyChangeKeyValue 监听注册表键的修改
            result = ctypes.windll.advapi32.RegNotifyChangeKeyValue(
                self.hkey.handle,            # 注册表句柄
                True,                        # 是否监控子键
                REG_NOTIFY_CHANGE_LAST_SET,  # 监控键的最后写入时间
                event_handle,                # 事件句柄，转换为 HANDLE 类型
                True                         # 异步操作
            )
            if result != 0:
                self.logger.error("无法设置注册表通知")
                break
            # 等待注册表变化事件
            handles = (self.event, self.stop_event)
            ret = win32event.WaitForMultipleObjects(handles, 0, self.wait_millis)
            if ret == win32event.WAIT_OBJECT_0 + 1:
                self.logger.info("收到停止信号")
                break
            elif ret == win32event.WAIT_OBJECT_0:
                self.logger.info("检测到代理设置发生变化")
                new_values = self._read_registry_values()
                self.callback(new_values)  # 触发回调函数，并传递新读取的值
                # 重置事件并继续监听
                win32event.ResetEvent(self.event)
            elif ret == win32event.WAIT_TIMEOUT:
                continue
            else:
                self.logger.error(f"等待事件时发生错误: {ret}")
                break
        self.logger.info(f"{self.hkey} 监听结束")
        self.cleanup()

    def stop_monitoring(self):
        win32event.SetEvent(self.stop_event)

    def cleanup(self):
        if self.hkey:
            ctypes.windll.advapi32.RegCloseKey(self.hkey)
        if self.event:
            win32event.CloseHandle(self.event)
        win32api.CloseHandle(self.stop_event)
