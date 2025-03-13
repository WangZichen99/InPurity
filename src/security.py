import os
import json
from key import KeyManager
from constants import TOKEN_PATH
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

class SecurityManager:
    def __init__(self):
        self.key_manager = KeyManager()
        self.private_key = self.key_manager.load_private_key()
        
    def verify_uninstall_token(self):
        """验证卸载标识是否合法"""
        if not os.path.exists(TOKEN_PATH):
            return False
        try:
            # 读取标识文件
            with open(TOKEN_PATH, "rb") as f:
                encrypted_data = f.read()
                
            # 解密数据
            decrypted_data = self.private_key.decrypt(
                encrypted_data,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            # 解析JSON数据
            token_data = json.loads(decrypted_data.decode())

            # 验证时间戳
            token_time = datetime.fromisoformat(token_data["timestamp"])
            if datetime.now(timezone.utc) - token_time > timedelta(minutes=5):
                return False
                
            # 验证其他字段
            return (token_data["app_name"] == "InPurity" and token_data["action"] == "uninstall")
                   
        except Exception as e:
            print(f"Token verification failed: {str(e)}")
            return False

# if __name__ == "__main__":
#     security = SecurityManager()
#     print(security.verify_uninstall_token())