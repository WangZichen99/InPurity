import os
import sys

# 服务名称
MAIN_SERVICE_NAME = "InPurityService"
DAEMON_SERVICE_NAME = "InPurityDaemonService"

"""获取应用程序的基础路径"""
if getattr(sys, 'frozen', False):
    # 如果是打包后的可执行文件
    BASE_DIR =  os.path.abspath(os.path.join(os.path.dirname(sys.executable), '..'))
    # 服务可执行文件
    MAIN_SERVICE_PATH = os.path.join(BASE_DIR, 'main_service\\main_service.exe')
    DAEMON_SERVICE_PATH = os.path.join(BASE_DIR, 'daemon_service\\daemon_service.exe')
    # 配置执行文件
    CONFIG_PATH = os.path.join(BASE_DIR, 'proxy_config\\')
    # run_mitmdump 路径
    RUN_MITMDUMP_PATH = os.path.join(BASE_DIR, 'run_mitmdump')
    MITMDUMP_PATH = os.path.join(RUN_MITMDUMP_PATH, 'run_mitmdump.exe')
    # proxy.py路径
    INTERNAL_PATH = os.path.join(RUN_MITMDUMP_PATH, '_internal')
    SCRIPT_PATH = os.path.join(INTERNAL_PATH, 'proxy_mitm.py')
    CERTIFICATES_PATH = r"C:\Windows\System32\config\systemprofile\.mitmproxy\mitmproxy-ca-cert.cer"
else:
    # 否则使用当前脚本文件所在的目录的上级目录作为基础路径（src 的上级目录）
    BASE_DIR =  os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    # 服务可执行文件
    MAIN_SERVICE_PATH = os.path.join(BASE_DIR, 'dist\\main_service\\main_service.exe')
    DAEMON_SERVICE_PATH = os.path.join(BASE_DIR, 'dist\\daemon_service\\daemon_service.exe')
    # 配置执行文件
    CONFIG_PATH = os.path.join(BASE_DIR, 'dist\\proxy_config\\')
    # mitmdump 路径
    # MITMDUMP_PATH = os.path.join(BASE_DIR, '.venv\\Scripts\\mitmdump.exe')
    MITMDUMP_PATH = os.path.join(BASE_DIR, 'dist\\run_mitmdump\\run_mitmdump.exe')
    SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'proxy_mitm.py')
    # 证书路径
    CERTIFICATES_PATH = os.path.join(BASE_DIR, 'certificates')
    
# DANGEROUS_VOCAB = ['未满18岁']

# 注册表子键
INTERNET_SUB_KEY = ["ProxyEnable", "ProxyServer", "ProxyOverride"]
SERVICE_SUB_KEY = ["Start"]

# 日志路径
LOG_PATH = os.path.join(BASE_DIR, 'log')
# 数据库文件路径
DATABASE_PATH = os.path.join(BASE_DIR, 'purity.db')
# 模型路径
MODEL_DIR = os.path.join(BASE_DIR, 'model')
# TEXT_MODEL_FILE = os.path.join(MODEL_DIR, 'ernie-3.0-mini-zh.onnx')
# TOKENIZER_DIR = os.path.join(MODEL_DIR, 'tokenizer')

IMAGE_MODEL_FILE = os.path.join(MODEL_DIR, 'mobilenet_v2.onnx')
IMAGE_LABELS = ['drawings', 'hentai', 'neutral', 'porn', 'sexy']
IMAGE_THRESHOLD = 0.3

TEST_DIR = os.path.join(BASE_DIR, 'test')

VIDEO_SIGN = {
        b'\x00\x00\x00\x18ftyp': 'mp4',  # MP4
        b'\x1A\x45\xDF\xA3': 'mkv',      # MKV/WebM
        b'\x47': 'ts',                   # TS
        b'RIFF': 'avi',                  # AVI
        b'FLV': 'flv',                   # FLV
    }