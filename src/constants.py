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

#文本类型
TEXT_CONTENT_TYPES = {"text/html", "text/plain"}

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

PORN_WORDS_CN = [
    "5aWz5ZCM", "LuS5sw==", "5b6u6IOW", "5bC7", "5bGM", "5Lq65aa7", "LuWmhw==", 
    "6aqa", "LuWlsw==", "5Lid6KKc", "6KOk6KKc", "6buR5Lid", "5Lid6YeM5Lid", "6IKJ5oSf", 
    "5Liw5ruh", "5YaF6KGj", "6IeA", "5rer", "5r2u5ZC5", "57K+5ray", "57K+5a2Q", "5Lmx5Lym", 
    "6IKJ5qOS", "57Sn6Lqr", "55Gc5Ly96KOk", "6L+e5L2T", "5ZCK5bim", "5oiY6KGj", "5oiY6KKN", 
    "5oOF6Laj", "LuavjQ==", "6a2F6a2U", "LuWmiA==", "6Lez6JuL", "5oyJ5pGp", "5oCn5oSf", "6IKJ5ryr", 
    "6Ieq5oWw", "LueptA==", "LuWluA==", "6aOe5py65p2v", "54ylLg==", "6JW+5Lid", "5bm76b6Z", 
    "5riU572R", "LuWltA==", "5rex5ZaJ", "5Y+j5Lqk", "6Laz5Lqk", "5YG35oOF", "57qm54Ku", "5YWo6KO4", 
    "6aWl5ri0", "5Ye66L2o", "56eB5oi/", "54af6b6E", "6L2m6ZyH", "5Y+M6aOe", "6Imy5oOF", "5oOF6Imy", 
    "5YGa54ix", "6buR6ay8", "6buR5Lq6", "6bih5be0", "5Lmz5Lqk", "5beo5qOS", "54K46KOCLis=",
    "5rij55S3", "5ZCD55Oc", "6buR5paZ", "54iG5paZ", "5oqW6Z+z", "5b+r5omL", "572R57qi", "56aP5Yip5aes", 
    "5aGM5oi/", "6b6f5aS0", "5Lit5Ye6", "5aup5aa5", "5p6B5ZOB", "56C05aSE", "5pK4566h", "5aSE5aWz", 
    "5YaF5bCE", "5LiB5a2X6KOk", "55S35qih", "5omT5qGp5py6", "6YeN5Y+j", "56eB5a+G", "5q+N54uX", 
    "57Sg5Lq6", "5Yi25pyN", "5Lmx5Lqk", "6IKP",
]

PORN_WORDS_EN = [
    "cG9ybg==", "c2V4", "bnVkZQ==", "YXNz", "ZGljaw==", "dGl0cw==", "bWlsZg==",
    "Y3Vt", "Z2F5", "YmJ3", "b3JnYXNt", "YW5hbA==", "Ymxvd2pvYg==", "aGFuZGpvYg==", 
    "bGVzYmlhbg==", "cHVzc3k=", "Y3Vtc2hvdA==", "ZnVjaw==", "ZnVja2luZw==", "aGVudGFp",
] 
