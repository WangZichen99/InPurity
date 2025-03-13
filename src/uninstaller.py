import os
import json
import psutil
import logging
from i18n import I18n
from key import KeyManager
from datetime import datetime, timezone
from constants import TOKEN_PATH, PDATA_PATH
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

class Uninstaller:
    def __init__(self):
        self.logger = self._setup_logger()
        self.key_manager = KeyManager()

    def _setup_logger(self):
        """设置日志记录器"""
        if not os.path.exists(PDATA_PATH):
            os.makedirs(PDATA_PATH)
        # 获取当前日期并格式化
        current_date = datetime.now().strftime('%Y%m%d')
        # 查找当天已存在的日志文件并确定序号
        number = 1
        while True:
            log_filename = f'uninstaller_{current_date}_{number:03d}.log'
            log_path = os.path.join(PDATA_PATH, log_filename)
            if not os.path.exists(log_path):
                break
            number += 1
        logger = logging.getLogger('uninstaller')
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(log_path, encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger
        
    def _is_inno_setup_process(self):
        """验证父进程是否为InnoSetup"""
        try:
            current_process = psutil.Process()
            parent = current_process.parent()
            self.logger.info(I18n.get("PARENT_PROCESS_INFO", parent.name(), parent.status()))
            self.logger.info(I18n.get("VALIDATION_RESULT", parent.name().startswith('InPurity') and parent.status() == 'running'))
            return parent.name().startswith("InPurity") and parent.status() == 'running'
        except:
            return False
            
    def generate_uninstall_token(self):
        """生成加密的卸载标识"""
        if not self._is_inno_setup_process():
            raise Exception("Unauthorized process")
            
        # 准备标识数据
        token_data = {
            "app_name": "InPurity",
            "action": "uninstall",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # 加载公钥
        public_key = self.key_manager.load_public_key()
        
        # 加密数据
        json_data = json.dumps(token_data).encode()
        encrypted_data = public_key.encrypt(
            json_data,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        
        # 保存到文件
        with open(TOKEN_PATH, "wb") as f:
            f.write(encrypted_data)

    def stop_gui(self):
        import signal
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] == 'gui.exe':
                    self.logger.info(I18n.get("TERMINATE_PROCESS", proc.info['name'], proc.info['pid']))
                    os.kill(proc.info['pid'], signal.SIGTERM)  # 发送终止信号
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
                self.logger.info(I18n.get("ERROR", e))

if __name__ == "__main__":
    uninstaller = Uninstaller()
    uninstaller.generate_uninstall_token()
    uninstaller.stop_gui()