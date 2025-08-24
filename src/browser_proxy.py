import psutil
import win32gui
import win32process
import win32con
import win32api
import sys
import re
import os

# --- 配置部分 ---
CHROME_NAMES = {
    "win32": {"chrome.exe", "msedge.exe", "chromium.exe"},
    "darwin": {"Google Chrome", "Microsoft Edge", "Chromium"},
    "linux": {"chrome", "google-chrome", "chromium", "chromium-browser", "microsoft-edge"},
}
PLAT = "win32" if os.name == "nt" else ("darwin" if sys.platform == "darwin" else "linux")
EXCLUDE_LOCAL_PORTS = {51949}
HIT_LOCAL_PORTS = {7897}
LOOPBACKS = {"127.0.0.1", "::1"}
PROXY_FLAG_RE = re.compile(r"--proxy-server\s*=\s*([^\s]+)", re.IGNORECASE)

# --- 辅助函数 ---
def iter_chrome_procs():
    """迭代所有 Chrome 家族进程的 psutil.Process 对象，并预加载信息。"""
    names = CHROME_NAMES.get(PLAT, set())
    # 预加载 parent() 和 cmdline() 所需的信息
    attrs = ["pid", "name", "cmdline", "ppid"]
    for p in psutil.process_iter(attrs):
        try:
            name = (p.info["name"] or "").strip()
            if not name and p.info.get("cmdline"):
                name = os.path.basename(p.info["cmdline"][0])
            base = name.lower()
            for n in names:
                if base == n.lower():
                    yield p
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, FileNotFoundError):
            continue

def detect_proxy_from_cmdline(p):
    try:
        cmdline_list = p.info.get("cmdline") or p.cmdline()
        if not cmdline_list: return None
        cmd = " ".join(cmdline_list)
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return None
    m = PROXY_FLAG_RE.search(cmd)
    if not m: return None
    raw = m.group(0); spec = m.group(1); mapping = {}
    parts = spec.strip('"').strip("'").split(";")
    for part in parts:
        if "=" in part: k, v = part.split("=", 1); mapping[k.strip().lower()] = v.strip()
        else: mapping["all"] = part.strip()
    return {"raw": raw, "mapping": mapping}

def detect_proxy_from_local_connections(p, exclude_ports, hit_ports):
    try:
        conns = p.net_connections(kind="inet")
    except (psutil.AccessDenied, psutil.NoSuchProcess): return False
    for c in conns:
        if c.raddr and c.status == psutil.CONN_ESTABLISHED:
            rip, rport = c.raddr.ip, c.raddr.port
            if rip in LOOPBACKS:
                if rport in exclude_ports: continue
                if rport in hit_ports: return True
    return False

def find_browser_root_procs(detected_procs):
    """
    从一组检测到的（可能是子）进程中，找出它们所属的根进程。
    判断依据：向上追溯父进程链，浏览器主进程的命令行通常没有 --type=... 参数。
    """
    if not detected_procs:
        return []

    root_procs_to_close = set()
    
    # 获取所有Chrome进程的名称集合，用于判断父进程是否为Chrome
    chrome_names = set()
    for name_set in CHROME_NAMES.values():
        chrome_names.update(name_set)
    chrome_names_lower = {name.lower() for name in chrome_names}

    for p in detected_procs:
        current_proc = p
        # 设置一个最大向上追溯层数，防止无限循环或意外情况
        for _ in range(10):
            try:
                # 预加载的信息可能不全，需要再次获取
                with current_proc.oneshot():
                    cmdline = current_proc.cmdline()
                    proc_name = current_proc.name()
                
                cmdline_str = " ".join(cmdline)
                
                # 检查当前进程是否为Chrome家族
                if proc_name.lower() not in chrome_names_lower:
                    break

                # **关键判断：如果没有 --type= 参数，则认为是主进程**
                if "--type=" not in cmdline_str:
                    root_procs_to_close.add(current_proc)
                    break
                
                # 如果有 --type= 参数，继续向上查找其父进程
                parent = current_proc.parent()
                if parent is None:
                    root_procs_to_close.add(current_proc)
                    break
                current_proc = parent

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
                
    return list(root_procs_to_close)

def close_gracefully_windows(pid):
    """
    在 Windows 上通过发送 WM_CLOSE 消息来优雅地关闭进程的主窗口。
    """
    if sys.platform != "win32":
        return False

    def find_main_window_handle(p):
        # 回调函数，用于 EnumWindows
        def enum_windows_callback(hwnd, hwnds):
            # 检查窗口是否可见且有标题
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                # 获取窗口所属的进程ID
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == p.pid:
                    hwnds.append(hwnd)
            return True
        
        handles = []
        try:
            # 枚举所有顶层窗口
            win32gui.EnumWindows(enum_windows_callback, handles)
            return handles[0] if handles else None # 返回找到的第一个主窗口句柄
        except Exception:
            return None

    try:
        p = psutil.Process(pid)
        hwnd = find_main_window_handle(p)
        if hwnd:
            print(f"  -> 找到 PID={pid} 的主窗口句柄，发送 WM_CLOSE 消息...")
            # PostMessage 是异步的，它将消息放入消息队列后立即返回
            win32api.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            print(f"✅ 已向 PID={pid} ({p.name()}) 发送正常关闭请求。")
            return True
        else:
            print(f"⚠️ 未能找到 PID={pid} 的主窗口，将回退到强制关闭。")
            p.terminate() # Fallback
            return False
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

def close_process_gracefully(p: psutil.Process):
    """
    尝试跨平台地优雅关闭一个进程。
    如果优雅关闭失败，则回退到 terminate。
    """
    pid = p.pid
    name = p.name()
    
    print(f"  -> 准备优雅关闭 PID={pid} ({name})")

    closed = False
    if sys.platform == "win32":
        closed = close_gracefully_windows(pid)
    # elif sys.platform == "darwin":
        # macOS 版本需要按名称关闭，这里简化处理
        # 实际应用中可能需要更复杂的逻辑来处理多实例
        # closed = close_gracefully_mac(name)
    # elif sys.platform.startswith("linux"):
        # closed = close_gracefully_linux(pid)
    
    if not closed:
        try:
            print(f"  -> 优雅关闭失败或不支持，回退到强制关闭 PID={pid}")
            p.terminate()
            p.wait(timeout=5)
        except psutil.NoSuchProcess:
            print(f"ℹ️ 进程 PID={pid} 在强制关闭前已消失。")
        except psutil.TimeoutExpired:
            print(f"  -> Terminate 超时，强制 kill PID={pid}")
            p.kill()
        except psutil.Error as e:
            print(f"❌ 强制关闭 PID={pid} 时发生错误: {e}")

# --- 主逻辑 ---
def main(exclude_ports=EXCLUDE_LOCAL_PORTS, hit_ports=HIT_LOCAL_PORTS, auto_close=True):
    print("--- 开始检测 Chrome 进程代理使用情况 ---")
    detected_procs = []
    for p in iter_chrome_procs():
        try:
            is_proxy_detected = False
            details = []
            if detect_proxy_from_local_connections(p, exclude_ports, hit_ports):
                is_proxy_detected = True
                details.append("本地连接命中")
            
            cmd_info = detect_proxy_from_cmdline(p)
            if cmd_info:
                # 可以在这里增加对cmd_info的端口检查，使其更精确
                is_proxy_detected = True
                details.append("命令行参数命中")

            if is_proxy_detected:
                print(f"\n--- 发现代理使用 ---")
                print(f"  子进程 PID: {p.pid}, 名称: {p.name()}, 检测方式: {', '.join(details)}")
                detected_procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    if detected_procs:
        print(f"\n[分析] 检测到 {len(detected_procs)} 个子进程使用代理。正在查找其根进程...")
        root_procs_to_close = find_browser_root_procs(detected_procs)
        
        if not root_procs_to_close:
             print("[警告] 未能明确找到根进程，将尝试关闭所有检测到的进程。")
             root_procs_to_close = detected_procs

        unique_root_pids = sorted(list({p.pid for p in root_procs_to_close}))
        print(f"\n[操作总结] 将关闭 {len(unique_root_pids)} 个 Chrome 根进程。")
        print(f"  根进程 PID 列表: {unique_root_pids}")
        
        if auto_close:
            print("准备关闭这些根进程...")
            for p in root_procs_to_close:
                close_process_gracefully(p)
        else:
            print("（未自动关闭，auto_close=False）")
    else:
        print("\n[结果] 未发现任何 Chrome 进程使用代理。")

if __name__ == "__main__":
    main(auto_close=True)