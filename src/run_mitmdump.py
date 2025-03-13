import sys
import proxy_mitm
from mitmproxy.tools.main import mitmdump

if __name__ == "__main__":
    mitmdump(sys.argv[1:])