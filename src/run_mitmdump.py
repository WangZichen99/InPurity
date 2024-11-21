import sys
from mitmproxy.tools.main import mitmdump
import proxy
import stream_data_parse
import ai_detect

if __name__ == "__main__":
    print(sys.argv[1:])
    mitmdump(sys.argv[1:])