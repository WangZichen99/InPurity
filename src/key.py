import os
import win32con
import win32crypt
import win32security
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

class KeyManager:
    def __init__(self):
        self.cert_store_name = "InPurity"
        self.keys_path = os.path.join(os.environ["ProgramData"], "InPurity", "keys")
        os.makedirs(self.keys_path, exist_ok=True)
        
    def generate_key_pair(self):
        """生成新的RSA密钥对并加密存储"""
        # 生成私钥
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        
        # 获取公钥
        public_key = private_key.public_key()
        
        # 序列化密钥
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        # 使用DPAPI加密
        protected_private = win32crypt.CryptProtectData(
            private_bytes,
            "InPurity Private Key",
            None, None, None,
            0x04
        )
        
        protected_public = win32crypt.CryptProtectData(
            public_bytes,
            "InPurity Public Key",
            None, None, None,
            0x04
        )
        
        # 存储加密后的密钥
        with open(os.path.join(self.keys_path, "private.key"), "wb") as f:
            f.write(protected_private)
            
        with open(os.path.join(self.keys_path, "public.key"), "wb") as f:
            f.write(protected_public)
            
    def load_private_key(self):
        """加载并解密私钥"""
        try:
            with open(os.path.join(self.keys_path, "private.key"), "rb") as f:
                protected_data = f.read()
                
            decrypted_data = win32crypt.CryptUnprotectData(
                protected_data,
                None, None, None,
                0x04
            )[1]
            
            return serialization.load_pem_private_key(
                decrypted_data,
                password=None
            )
        except Exception as e:
            raise Exception(f"Failed to load private key: {str(e)}")
            
    def load_public_key(self):
        """加载并解密公钥"""
        try:
            with open(os.path.join(self.keys_path, "public.key"), "rb") as f:
                protected_data = f.read()
                
            decrypted_data = win32crypt.CryptUnprotectData(
                protected_data,
                None, None, None,
                0x04
            )[1]
            
            return serialization.load_pem_public_key(decrypted_data)
        except Exception as e:
            raise Exception(f"Failed to load public key: {str(e)}")
        
    def _secure_directory(self, path):
        """设置目录的安全权限"""
        # 获取 SYSTEM 和 Administrators 的 SID
        system_sid = win32security.ConvertStringSidToSid("S-1-5-18")
        admins_sid = win32security.ConvertStringSidToSid("S-1-5-32-544")
        
        # 创建新的安全描述符
        sd = win32security.SECURITY_DESCRIPTOR()
        
        # 创建 ACL
        acl = win32security.ACL()
        
        # 添加 ACE (访问控制条目)
        acl.AddAccessAllowedAce(
            win32security.ACL_REVISION,
            win32con.GENERIC_ALL,
            system_sid
        )
        acl.AddAccessAllowedAce(
            win32security.ACL_REVISION,
            win32con.GENERIC_ALL,
            admins_sid
        )
        
        # 设置 DACL
        sd.SetSecurityDescriptorDacl(1, acl, 0)
        
        # 应用安全设置
        win32security.SetFileSecurity(
            path,
            win32security.DACL_SECURITY_INFORMATION,
            sd
        )
