import os
import glob
import time
import shutil
import logging
import threading
from i18n import I18n
from constants import LOG_PATH
from typing import Dict, Optional
from datetime import datetime, date

class LogManager:
    _instance = None
    _lock = threading.Lock()
    _initialized = False
    rotate_flag = False #是否正在执行轮转
    deamon_flag = False #每个exe进程使用不同的log实例，无法重复执行的交给守护进程去做
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance
    
    def __init__(self):
        # 防止重复初始化
        if self.__class__._initialized:
            return
        self.__class__._initialized = True
        self._initialize()

    def _initialize(self):
        self.base_dir = LOG_PATH
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir, exist_ok=True)
        self.archive_dir = os.path.join(self.base_dir, 'archive')
        self.max_days = 30
        self.check_interval = 10
        self.loggers: Dict[str, logging.Logger] = {}
        self.handlers: Dict[str, logging.FileHandler] = {}
        self.running = True
        self.logger = self.get_logger("LogManager", "log_manager")
        # 创建必要的目录
        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self.archive_dir, exist_ok=True)
        # 检查需要轮转的日志文件
        self.rotate_dict = self._get_rotate_logs()
        if len(self.rotate_dict) > 0 and not self.rotate_flag:
            self._rotate_logs()
            if self.deamon_flag:
                self._cleanup_old_archives()
        # 启动检查线程
        self.check_thread = threading.Thread(target=self._check_rotate, name='check-rotate', daemon=True)
        self.check_thread.start()

    def _get_rotate_logs(self) -> dict:
        # 获取需要归档的日志文件
        rotate_dict = {}
        log_files = glob.glob(os.path.join(self.base_dir, '*.log'))
        if not log_files:
            return rotate_dict
        script_list = [key.split('@')[0] for key in self.loggers.keys()]
        self.deamon_flag = "daemon_service" in script_list
        for log_file in log_files:
            try:
                # 文件名格式为 script_name_YYYYMMDD.log
                file_name = os.path.basename(log_file)
                date_str = file_name.split('_')[-1].split('.')[0]
                log_date = datetime.strptime(date_str, "%Y%m%d").date()
                script_name = file_name[0: file_name.rfind('_')]
                if log_date != date.today() and (script_name in script_list or (self.deamon_flag and script_name == "installer")):
                    rotate_dict[script_name] = (log_file, date_str)
            except (ValueError, IndexError):
                continue
        return rotate_dict
    
    def get_logger(self, logger_name: str, script_name: str) -> logging.Logger:
        """
        获取或创建一个日志记录器
        :param logger_name: 日志记录器名称
        :param script_name: 脚本名称
        :return: Logger实例
        """
        logger_key = f"{script_name}@{logger_name}"
        with self._lock:
            if logger_key not in self.loggers:
                # 创建新的日志记录器
                logger = logging.getLogger(logger_name)
                logger.setLevel(logging.INFO)
                # 创建日志文件处理器
                log_file = self._get_current_log_file(script_name)
                handler = logging.FileHandler(log_file, encoding='utf-8')
                formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                )
                handler.setFormatter(formatter)
                logger.addHandler(handler)
                self.loggers[logger_key] = logger
                self.handlers[logger_key] = handler
            return self.loggers[logger_key]
    
    def _get_current_log_file(self, script_name: str) -> str:
        """获取当前日志文件路径"""
        return os.path.join(self.base_dir, f'{script_name}_{date.today().strftime("%Y%m%d")}.log')
    
    def _check_rotate(self):
        """定期检查日期变化和执行日志轮转"""
        while self.running:
            try:
                rotate_dict = self._get_rotate_logs()
                if len(rotate_dict) > 0 and not self.rotate_flag:
                    self.rotate_dict = rotate_dict
                    self._rotate_logs()
                    if self.deamon_flag:
                        self._cleanup_old_archives()
                time.sleep(self.check_interval)
            except Exception as e:
                self.logger.exception(I18n.get("check_rotate_error", str(e)))
    
    def _rotate_logs(self):
        """轮转handler"""
        try:
            self.rotate_flag = True
            for logger_key, logger in self.loggers.items():
                script_name = logger_key.split('@')[0]
                # 移除旧的handler
                old_handler = self.handlers[logger_key]
                logger.removeHandler(old_handler)
                old_handler.close()
                # 创建新的handler
                new_log_file = self._get_current_log_file(script_name)
                new_handler = logging.FileHandler(new_log_file, encoding='utf-8')
                new_handler.setFormatter(old_handler.formatter)
                logger.addHandler(new_handler)
                self.handlers[logger_key] = new_handler
            if len(self.rotate_dict) > 0:
                if "log_manager" in self.rotate_dict.keys() and not self.deamon_flag:
                    self.rotate_dict.pop("log_manager")
                for script_name in list(self.rotate_dict.keys()):
                    file_path, date_str = self.rotate_dict[script_name]
                    archive_date_dir = os.path.join(self.archive_dir, date_str)
                    if not os.path.exists(archive_date_dir):
                        os.makedirs(archive_date_dir, exist_ok=True)
                    try:
                        dest_file = os.path.join(archive_date_dir, os.path.basename(file_path))
                        if os.path.exists(dest_file):
                            os.remove(dest_file)
                        shutil.move(file_path, archive_date_dir)
                        self.rotate_dict.pop(script_name)
                        self.logger.info(I18n.get("move_file", file_path, archive_date_dir))
                    except Exception as e:
                        self.logger.exception(I18n.get("move_file_error", str(e)))
        except Exception as e:
            self.logger.exception(I18n.get("log_exception", str(e)))
        finally:
            self.rotate_flag = False

    def _cleanup_old_archives(self):
        """清理超过保留天数的归档文件"""
        try:
            current_time = time.time()
            for date_dir in glob.glob(os.path.join(self.archive_dir, '*')):
                if os.path.isdir(date_dir):
                    dir_time = os.path.getmtime(date_dir)
                    if (current_time - dir_time) > (self.max_days * 24 * 60 * 60):
                        try:
                            shutil.rmtree(date_dir)
                            self.logger.info(I18n.get("removed_archive", date_dir))
                        except Exception as e:
                            self.logger.exception(I18n.get("remove_dir_error", date_dir, str(e)))
        except Exception as e:
            self.logger.exception(I18n.get("cleanup_archives_error", str(e)))
    
    def cleanup(self, script_name: Optional[str] = None, logger_name: Optional[str] = None):
        """
        清理指定的日志资源
        :param script_name: 脚本名称，如果为None则清理所有资源
        :param logger_name: 日志记录器名称，如果为None则清理指定脚本的所有日志
        """
        with self._lock:
            if script_name:
                # 清理指定脚本的日志资源
                keys_to_cleanup = []
                for logger_key in self.loggers.keys():
                    script, log_name = logger_key.split('@', 1)
                    if script == script_name:
                        if logger_name is None or log_name == logger_name:
                            keys_to_cleanup.append(logger_key)
                
                for key in keys_to_cleanup:
                    self._cleanup_logger(key)
            if not script_name or len(self.loggers) == 0:
                # 如果没有指定脚本名称，则停止检查线程并清理所有资源
                self.running = False
                if self.check_thread.is_alive():
                    self.check_thread.join(timeout=1)
                # 清理所有日志资源
                for logger_key in list(self.loggers.keys()):
                    self._cleanup_logger(logger_key)
                self.loggers.clear()
                self.handlers.clear()
    
    def _cleanup_logger(self, logger_key: str):
        """
        清理指定的日志记录器
        :param logger_key: 日志记录器的键
        """
        if logger_key in self.loggers:
            logger = self.loggers[logger_key]
            handler = self.handlers[logger_key]
            handler.close()
            logger.removeHandler(handler)
            del self.loggers[logger_key]
            del self.handlers[logger_key]

# if __name__ == "__main__":
#     import psutil, win32ts
#     try:
#         while True:
#             for proc in psutil.process_iter(['pid', 'exe']):
#                 try:
#                     if proc.info['exe'] and proc.info['exe'].lower().endswith('explorer.exe'):
#                         print(f"Found explorer.exe at PID {proc.info['pid']}")
#                         # 可选：检查会话 ID
#                         session_id = proc.session_id() if hasattr(proc, 'session_id') else None
#                         active_session = win32ts.WTSGetActiveConsoleSessionId()
#                         if session_id == active_session:
#                             print(f"Found explorer.exe at PID {proc.info['pid']}")
#                             break
#                         # 或直接返回：return proc.info['pid']
#                 except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
#                     print(f"Skipped process: {e}")
#                     continue
#             print("No explorer.exe found")
#             time.sleep(1)
#     except Exception as e:
#         print(f"Error: {e}")
#     log = LogManager()
#     log.base_dir = os.path.join('D:\Program Files (x86)\InPurity', 'log')
#     log.current_date = datetime.strptime('20250123', "%Y%m%d").date()
#     log._rotate_logs(date.today())