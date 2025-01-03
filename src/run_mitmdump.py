import sys
import ai_detect
import proxy_mitm
import stream_data_parse
from mitmproxy.tools.main import mitmdump

if __name__ == "__main__":
    print(sys.argv[1:])
    mitmdump(sys.argv[1:])