import hmac
import win32api
import win32con

class Utils:
    @staticmethod
    def _get_machine_secret() -> bytes:
        """
        基于机器特定信息生成密钥
        """
        # 获取不易变的系统信息作为密钥材料
        machine_guid = win32api.RegOpenKeyEx(
            win32con.HKEY_LOCAL_MACHINE,
            "SOFTWARE\\Microsoft\\Cryptography",
            0,
            win32con.KEY_READ
        )
        guid = win32api.RegQueryValueEx(machine_guid, "MachineGuid")[0]
        
        # 添加额外的系统特定信息
        cpu_info = win32api.RegOpenKeyEx(
            win32con.HKEY_LOCAL_MACHINE,
            "HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0",
            0,
            win32con.KEY_READ
        )
        processor_id = win32api.RegQueryValueEx(cpu_info, "ProcessorNameString")[0]
        
        # 组合信息生成密钥
        return hmac.new(
            guid.encode(),
            processor_id.encode(),
            'sha256'
        ).digest()
    
    @staticmethod
    def generate_signature(timestamp: str, services: list) -> str:
        """
        生成配置签名
        """
        message = f"{timestamp}|{'|'.join(sorted(services))}"
        return hmac.new(
            Utils._get_machine_secret(),
            message.encode(),
            'sha256'
        ).hexdigest()
