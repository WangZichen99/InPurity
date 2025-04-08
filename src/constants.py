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
    IMNATSEKR_PATH = os.path.join(RUN_MITMDUMP_PATH, '_internal', '_intercept.pyd')
    MITMDUMP_PATH = os.path.join(RUN_MITMDUMP_PATH, 'run_mitmdump.exe')
    # GUI
    GUI_DIR_PATH = os.path.join(BASE_DIR, 'gui')
    GUI_PATH = os.path.join(GUI_DIR_PATH, 'gui.exe')
    # proxy.py路径
    INTERNAL_PATH = os.path.join(RUN_MITMDUMP_PATH, '_internal')
    SCRIPT_PATH = os.path.join(INTERNAL_PATH, 'proxy_mitm.py')
    CERTIFICATES_PATH = r"C:\Windows\System32\config\systemprofile\.mitmproxy\mitmproxy-ca-cert.cer"
else:
    # 否则使用当前脚本文件所在的目录的上级目录作为基础路径（src 的上级目录）
    BASE_DIR =  os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    # 服务可执行文件
    MAIN_SERVICE_PATH = os.path.join(BASE_DIR, 'target\\dist\\main_service\\main_service.exe')
    DAEMON_SERVICE_PATH = os.path.join(BASE_DIR, 'target\\dist\\daemon_service\\daemon_service.exe')
    # 配置执行文件
    CONFIG_PATH = os.path.join(BASE_DIR, 'target\\dist\\proxy_config\\')
    # mitmdump 路径
    # MITMDUMP_PATH = os.path.join(BASE_DIR, '.venv\\Scripts\\mitmdump.exe')
    RUN_MITMDUMP_PATH = os.path.join(BASE_DIR, 'target\\dist\\run_mitmdump')
    IMNATSEKR_PATH = os.path.join(RUN_MITMDUMP_PATH, '_internal', '_intercept.pyd')
    MITMDUMP_PATH = os.path.join(RUN_MITMDUMP_PATH, 'run_mitmdump.exe')
    SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'proxy_mitm.py')
    # GUI
    GUI_DIR_PATH = os.path.join(BASE_DIR, 'target\\dist\\gui')
    GUI_PATH = os.path.join(GUI_DIR_PATH, 'gui.exe')
    # 证书路径
    CERTIFICATES_PATH = os.path.join(BASE_DIR, "certificates")
PDATA_PATH = os.path.join(os.environ["ProgramData"], "InPurity")
TOKEN_PATH = os.path.join(PDATA_PATH, "uninstall.token")
ICON_PATH = os.path.join(BASE_DIR, "icon.ico")

# DANGEROUS_VOCAB = ['未满18岁']

# 注册表子键
INTERNET_SUB_KEY = ["ProxyEnable", "ProxyServer"]
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

SYSTEM_PROCESSES = ['taskhostw.exe', 'explorer.exe']

# 快速过滤规则
SKIP_EXTENSIONS = {'.css', '.js', '.woff', '.woff2', '.ttf', '.eot', '.svg', '.ico', '.mp3', '.mp4', '.wasm'}
SKIP_CONTENT_TYPES = {
    'text/css', 'application/javascript', 'application/x-javascript',
    'text/javascript', 'font/woff', 'font/woff2', 'application/font-woff',
    'application/font-woff2', 'image/svg+xml', 'image/x-icon', 'audio/',
    'video/', 'application/wasm'
}

# 图片相关常量
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.avif'}
IMAGE_CONTENT_TYPES = {
    'image/jpeg', 'image/png', 'image/gif', 'image/bmp', 
    'image/webp', 'image/tiff', 'image/avif', 'image/x-icon'
}

# 流媒体类型
STREAMING_TYPES = {
    # 媒体类型
    'video/', 'audio/', 'application/pdf',
    'application/x-mpegURL', 'application/dash+xml', 
    # 压缩文件
    'application/zip', 'application/x-gzip',
    'application/x-tar', 'application/x-bzip2',
    'application/x-7z-compressed', 'application/x-rar-compressed',
    # 数据流
    'text/event-stream', 'application/octet-stream',
    'application/xml', 'application/vnd.yt-ump',
    # 特殊传输
    'multipart/byteranges'
}

# 视频签名
VIDEO_SIGN = {
    b'\x00\x00\x00\x18ftyp': 'mp4',  # MP4
    b'\x1A\x45\xDF\xA3': 'mkv',      # MKV/WebM
    b'\x47': 'ts',                   # TS
    b'RIFF': 'avi',                  # AVI
    b'FLV': 'flv',                   # FLV
}

# 服务通信相关常量
SERVICE_HOST = '127.0.0.1'
GUI_PIPE_NAME = r"\\.\pipe\GUIPipe"
RANDOM_PORT_MIN = 49152
RANDOM_PORT_MAX = 65535
DEFAULT_THREAD_TIMEOUT = 5  # 线程停止的默认超时时间（秒）
MAX_USER_WAIT_SECONDS = 600  # 等待用户进程的最长时间（10分钟）
EXPECTED_VALUES = {"Start": 0x00000002, "DelayedAutostart": 0x00000001}

# 守护服务相关常量
DAEMON_THREAD_JOIN_TIMEOUT = 10  # 守护服务线程终止等待时间（秒）
DAEMON_SERVICE_CHECK_DELAY = 10  # 守护服务初始检查延迟（秒）
INTERNET_MONITOR_INTERVAL = 10000  # 互联网设置监控间隔（毫秒）
SERVICE_MONITOR_INTERVAL = 60000  # 服务设置监控间隔（毫秒）
SERVICE_AUTO_START = 0x00000002  # 服务自动启动类型