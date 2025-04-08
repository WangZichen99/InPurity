import pystray
import win32file
import win32pipe
import threading
import tkinter as tk
from PIL import Image
from i18n import I18n
from log import LogManager
from constants import ICON_PATH
from tkinter import scrolledtext
from concurrent.futures import ThreadPoolExecutor

class ProxyGUI:
    def __init__(self):
        log = LogManager()
        self.logger = log.get_logger("gui", "gui")
        self.ICON_PATH = ICON_PATH
        self.window = tk.Tk()
        self.output_text = None
        self.tray_icon = None
        self.running = True
        self.auto_scroll = True
        self.pipe = None
        self.rebuild_lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.setup_ui()
        self.create_pipe()
        
    def setup_ui(self):
        self.window.title("Proxy Log")
        self.window.geometry("1000x450")
        self.window.iconbitmap(self.ICON_PATH)
        self.window.configure(bg='black')
        # 设置窗口在屏幕中心
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        window_width = 1000
        window_height = 450
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.window.geometry(f"{window_width}x{window_height}+{x}+{y}")
        # 创建带样式的滚动文本框
        self.output_text = scrolledtext.ScrolledText(
            self.window, 
            wrap=tk.WORD,
            bg='black',  # 文本框背景为黑色
            fg='white',  # 文本为白色
            insertbackground='white',  # 光标颜色为白色
            selectbackground='gray',  # 选中文本的背景色
            selectforeground='white',  # 选中文本的前景色
            font=('Consolas', 14),  # 使用等宽字体
        )
        self.output_text.pack(expand=True, fill=tk.BOTH)
        self.output_text.vbar.config(command=self.scroll_event)
        # 创建托盘图标
        self.create_tray_icon()
        # 设置关闭按钮行为
        self.window.protocol("WM_DELETE_WINDOW", self.hide_window)

    def create_tray_icon(self):
        image = Image.open(self.ICON_PATH)
        menu = pystray.Menu(pystray.MenuItem('show', self.show_window, default=True, visible=False))
        self.tray_icon = pystray.Icon("inpurity", image, "proxylog", menu)
        self.window.after(0, self.run_tray_icon)

    def create_pipe(self):
        with self.rebuild_lock:
            if self.pipe:
                return
            try:
                self.pipe = win32pipe.CreateNamedPipe(
                    r"\\.\pipe\GUIPipe",  # 管道的名称
                    win32pipe.PIPE_ACCESS_INBOUND,  # 只允许客户端向管道写数据
                    win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,  # 管道类型
                    1,  # 最大连接数
                    65536,  # 输出缓冲区大小
                    65536,  # 输入缓冲区大小
                    0,  # 默认超时
                    None
                )
                self.logger.info(I18n.get("pipe_created"))
                self.listen_thread()
            except Exception as e:
                self.logger.exception(I18n.get("pipe_create_error", str(e)))

    def listen_thread(self):
        def listen_for_messages():
            self.logger.info(I18n.get("listening_messages"))
            try:
                while self.running:
                    win32pipe.ConnectNamedPipe(self.pipe, None)  # 等待客户端连接
                    self.logger.info(I18n.get("client_connected"))
                    while self.running:
                        try:
                            # 读取管道数据
                            hr, data = win32file.ReadFile(self.pipe, 65536)
                            if hr == 0:
                                message = data.decode() + "\n"
                                if message:
                                    self.output_text.config(state=tk.NORMAL)
                                    self.output_text.insert(tk.END, message)
                                    if self.auto_scroll:
                                        self.output_text.see(tk.END)
                                    self.output_text.config(state=tk.DISABLED)
                        except Exception as e:
                            if e.args[0] == 109: # 管道已结束
                                self.logger.info(e.args[-1])
                            else:
                                self.logger.exception(I18n.get("pipe_read_error", str(e)))
                            break
            except Exception as e:
                if e.args[0] == 232: # 管道正在被关闭
                    self.logger.info(e.args[-1])
                else:
                    self.logger.exception(I18n.get("pipe_connect_error", str(e)))
            finally:
                if self.pipe:
                    win32file.CloseHandle(self.pipe)
                    self.pipe = None
                self.logger.info(I18n.get("pipe_closed"))
                if self.running:
                    self.executor.submit(self.create_pipe)
        self.executor.submit(listen_for_messages)

    def scroll_event(self, *args):
        """
        处理滚动条拖动和鼠标滚轮滚动事件。
        - 拖动滚动条时更新视图并根据位置设置 auto_scroll。
        - 滚轮滚动时更新视图并检查是否在最底部。
        """
        if args[0] == 'moveto':
            moveto = float(args[1])
            self.output_text.yview_moveto(moveto)
        elif args[0] == 'scroll':
            # 处理鼠标滚轮滚动
            units = int(args[1])
            self.output_text.yview_scroll(units, 'units')
        if self.output_text.yview()[1] >= 1.0:
            self.auto_scroll = True
        else:
            self.auto_scroll = False

    def run_tray_icon(self):
        """将 pystray 图标放入 Tkinter 主线程运行"""
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self, icon, item):
        """使用 after() 方法确保 deiconify() 在主线程中调用"""
        self.window.after(0, self._deiconify_window)

    def _deiconify_window(self):
        """在主线程中显示窗口"""
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def hide_window(self):
        self.window.withdraw()

    def quit_app(self):
        self.running = False
        if self.tray_icon:
            self.tray_icon.stop()
        self.executor.shutdown(wait=False)
        if self.window:
            self.window.quit()
            self.window.destroy()

if __name__ == '__main__':
    gui = None
    try:
        gui = ProxyGUI()
        gui.window.mainloop()
    except Exception as e:
        if gui:
            gui.logger.exception(f"exception: {e}")
        print(e)
    finally:
        if gui:
            gui.quit_app()
