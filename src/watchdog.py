# purity_watchdog.py
import os
import sys
import time
import win32file
import win32service
import win32serviceutil
from pathlib import Path
from log import LogManager
from constants import PDATA_PATH, MAIN_SERVICE_NAME, DAEMON_SERVICE_NAME, WATCHDOG_CHECK_INTERVAL

class ServiceWatchdog:
    def __init__(self, watchdog_id):
        self.watchdog_id = watchdog_id
        self.main_service = MAIN_SERVICE_NAME
        self.guardian_service = DAEMON_SERVICE_NAME
        self.check_interval = WATCHDOG_CHECK_INTERVAL
        self.logger = LogManager().get_logger('watchdog', 'watchdog')
        self.is_running = True
        self.lock_dir = Path(PDATA_PATH)
        if not os.path.exists(self.lock_dir):
            os.makedirs(self.lock_dir, exist_ok=True)
        self.logger.info(f"看门狗 #{watchdog_id} 初始化完成")

    def acquire_service_lock(self, service_name):
        """获取服务启动锁，确保只有一个看门狗启动服务"""
        lock_file = self.lock_dir / f"{service_name}.lock"
        try:
            # 尝试创建并锁定文件
            handle = win32file.CreateFile(
                str(lock_file),
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,  # 不允许共享
                None,
                win32file.CREATE_ALWAYS,
                win32file.FILE_ATTRIBUTE_TEMPORARY | win32file.FILE_FLAG_DELETE_ON_CLOSE,
                None
            )
            
            # 写入看门狗ID和时间戳
            lock_info = f"Watchdog-{self.watchdog_id}-{os.getpid()}-{time.time()}"
            win32file.WriteFile(handle, lock_info.encode())
            return handle
        except Exception:
            # 无法获取锁，说明其他看门狗正在启动服务
            return None

    def release_service_lock(self, handle):
        """释放服务启动锁"""
        if handle:
            try:
                win32file.CloseHandle(handle)
            except:
                pass

    def check_and_restart_service(self, service_name):
        """检查并重启服务"""
        try:
            # 检查服务状态
            lock_handle = None
            status = win32serviceutil.QueryServiceStatus(service_name)
            if status[1] in (win32service.SERVICE_START_PENDING, win32service.SERVICE_RUNNING):
                return True  # 服务正常运行
            self.logger.warning(f"看门狗 #{self.watchdog_id} 发现服务 {service_name} 未运行，状态: {status[1]}")
            # 尝试获取启动锁
            lock_handle = self.acquire_service_lock(service_name)
            if lock_handle is None:
                return False  # 其他看门狗正在处理
            # 获得锁，开始启动服务
            self.logger.info(f"看门狗 #{self.watchdog_id} 获得启动锁，正在启动 {service_name}")
            # 使用win32serviceutil启动服务
            win32serviceutil.StartService(service_name)
            # 等待服务启动并验证
            time.sleep(2)
            status = win32serviceutil.QueryServiceStatus(service_name)
            if status[1] in (win32service.SERVICE_START_PENDING, win32service.SERVICE_RUNNING):
                self.logger.info(f"看门狗 #{self.watchdog_id} 成功启动服务 {service_name}")
                return True
            else:
                self.logger.exception(f"看门狗 #{self.watchdog_id} 启动服务 {service_name} 失败，当前状态: {status[1]}")
                return False
        except Exception as e:
            if e.args[0] == 1056: # 服务已运行
                return True
            if e.args[0] == 1115: # 系统正在关机
                return False
            self.logger.exception(f"看门狗 #{self.watchdog_id} 启动服务 {service_name} 时出错: {e}")
            return False
        finally:
            # 释放锁
            if lock_handle:
                self.release_service_lock(lock_handle)
                time.sleep(0.1)  # 短暂延迟避免锁竞争

    def run(self):
        """看门狗主循环"""
        self.logger.info(f"看门狗 #{self.watchdog_id} 开始运行")
        while self.is_running:
            try:
                # 检查主服务
                self.check_and_restart_service(self.main_service)
                # 检查守护服务
                self.check_and_restart_service(self.guardian_service)
                # 等待下一个检查周期
                time.sleep(self.check_interval)
            except Exception as e:
                self.logger.exception(f"看门狗 #{self.watchdog_id} 运行时出错: {e}")
                time.sleep(1)  # 出错时稍长延迟
                # 不需要break，让看门狗继续运行

def main():
    if len(sys.argv) != 2:
        print("用法: purity_watchdog.exe <看门狗ID>")
        sys.exit(1)
    try:
        watchdog_id = int(sys.argv[1])
    except ValueError:
        print("看门狗ID必须是数字")
        sys.exit(1)
    # 创建并运行看门狗
    watchdog = ServiceWatchdog(watchdog_id)
    # 直接运行看门狗，主服务会通过terminate直接终止进程
    watchdog.run()

if __name__ == "__main__":
    main()
