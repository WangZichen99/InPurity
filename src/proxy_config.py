import re
import socket
import random
import cmd2
from typing import List
from db_manager import DatabaseManager

class ProxyConfig(cmd2.Cmd):
    def __init__(self):
        # 设置要隐藏的命令
        hidden_commands = ['alias', 'edit', 'eof', 'history', 'macro', 'run_pyscript', 'run_script', 'shell', 'shortcuts', 'py', 'set']
        super().__init__(allow_cli_args=False)
        
        # 隐藏不需要的命令
        for command in hidden_commands:
            setattr(self, f'do_{command}', None)
            setattr(self, f'help_{command}', None)
            setattr(self, f'complete_{command}', None)
        
        self.db_manager = DatabaseManager()
        self.HOST = "127.0.0.1"
        self.prompt = "InPurity> "
        self.intro = """代理配置工具
使用 help 或 ? 查看帮助
使用 Tab 键自动补全命令和参数"""
        
        # 设置命令分类
        self.categories = {
            'Proxy Settings': ['port', 'upstream'],
            'Configuration': ['setopt', 'delopt', 'select'],
            'System': ['restart', 'quit']
        }
        
        # 设置命令分组显示
        self.cmd_categories = {
            cmd: category for category, cmds in self.categories.items() for cmd in cmds
        }

    def validate_port(self, port):
        return 49152 <= port <= 65535

    def is_valid_upstream_server(self, server):
        pattern = r'^(http|https)://\d{1,3}(\.\d{1,3}){3}:\d+$'
        return re.match(pattern, server) is not None

    def is_port_available(self, port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
            return True, port
        except socket.error:
            return False, port

    def get_socket_port(self):
        socket_port = self.db_manager.get_config("socket_port")
        if socket_port and self.is_port_available(int(socket_port)):
            return int(socket_port)
        else:
            while not socket_port or not self.is_port_available(int(socket_port)):
                socket_port = random.randint(49152, 65535)
            self.db_manager.update_config("socket_port", socket_port)
            return socket_port

    def send_restart_command(self, socket_port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.connect((self.HOST, socket_port))
                s.sendall(b"RESTART")
                self.poutput("已发送重启命令")
            except ConnectionRefusedError as cre:
                self.perror(f"{cre}请确认代理服务是否启动")
            except Exception as e:
                self.perror(str(e))

    def complete_port(self, text, line, begidx, endidx) -> List[str]:
        """端口号自动补全"""
        if not text:
            return ['51949']  # 默认端口
        return []

    def complete_upstream(self, text, line, begidx, endidx) -> List[str]:
        """upstream命令自动补全"""
        options = ['enable', 'disable', 'http://', 'https://']
        if not text:
            return options
        return [opt for opt in options if opt.startswith(text)]

    def complete_delopt(self, text, line, begidx, endidx) -> List[str]:
        """delopt命令的配置项自动补全"""
        all_options = self.db_manager.get_all_options()
        option_names = [opt[0] for opt in all_options]
        if not text:
            return option_names
        return [opt for opt in option_names if opt.startswith(text)]

    def complete_select(self, text, line, begidx, endidx) -> List[str]:
        """select命令的配置项自动补全"""
        all_configs = self.db_manager.get_all_configs()
        config_names = [conf[0] for conf in all_configs]
        if not text:
            return config_names
        return [conf for conf in config_names if conf.startswith(text)]

    def do_port(self, arg):
        """设置代理端口 port <port_number> 端口范围: 49152-65535"""
        if not arg:
            self.perror("请指定端口号")
            return
        try:
            port = int(arg)
            if self.validate_port(port):
                if self.is_port_available(port):
                    self.db_manager.update_config('proxy_port', port)
                    self.poutput(f"代理端口已设置为: {port}")
                else:
                    self.perror(f"端口 {port} 已被占用")
            else:
                self.perror(f"端口号 {port} 不在范围 49152 到 65535 之间")
        except ValueError:
            self.perror("无效的端口号，必须为数字")

    def do_upstream(self, arg):
        """上游代理设置 upstream enable(启用)|disable(禁用)|http[s]://host:port(设置上游代理服务器)"""
        if not arg:
            self.perror("请指定操作类型")
            return

        if arg == 'enable':
            upstream_server = self.db_manager.get_config('upstream_server')
            if upstream_server:
                self.db_manager.update_config('upstream_enable', 1)
                self.poutput("上游代理已启用")
            else:
                self.perror("上游代理服务未设置，请先设置上游代理服务器地址")
        elif arg == 'disable':
            self.db_manager.update_config('upstream_enable', 0)
            self.poutput("上游代理已禁用")
        elif arg.startswith(('http://', 'https://')):
            if self.is_valid_upstream_server(arg):
                self.db_manager.update_config('upstream_server', arg)
                self.db_manager.update_config('upstream_enable', 1)
                self.poutput(f"上游代理服务已设置为: {arg} 并已启用")
            else:
                self.perror("无效的上游代理服务格式，请使用 'http://ip:port' 或 'https://ip:port' 格式")
        else:
            self.perror("无效的upstream命令，请使用 enable、disable 或输入代理服务器地址")

    def do_setopt(self, arg):
        """设置mitmproxy配置项 setopt <name>=<value>"""
        if not arg:
            self.perror("请指定配置项和值")
            return
        if '=' not in arg:
            self.perror("无效的输入，必须包含=")
            return
        
        name, value = arg.split('=', 1)
        name = name.strip()
        value = value.strip()
            
        self.db_manager.update_option(name, value)
        self.poutput(f"设置 {name} = {value}")

    def do_delopt(self, arg):
        """删除mitmproxy配置项 delopt <name>"""
        if not arg:
            self.perror("请指定要删除的配置项名称")
            return
        
        count = self.db_manager.delete_option(arg)
        if count > 0:
            self.poutput(f"配置项 {arg} 已删除")
        else:
            self.perror(f"未找到配置项 {arg}")

    def do_select(self, arg):
        """查询配置 select <name>"""
        if arg:
            config_value = self.db_manager.get_config(arg)
            if config_value is not None:
                self.poutput(f"{arg}: {config_value}")
            else:
                self.perror(f"未找到设置: {arg}")
        else:
            all_configs = self.db_manager.get_all_configs()
            self.poutput("所有配置:")
            for config in all_configs:
                self.poutput(f"{config[0]}: {config[1]}")

    def do_restart(self, _):
        """重启代理服务"""
        socket_port = self.get_socket_port()
        self.send_restart_command(socket_port)

    def do_quit(self, _):
        """退出程序"""
        return True

    def do_EOF(self, _):
        return self.do_quit(_)

    def do_help(self, arg):
        """显示帮助信息"""
        if arg:
            # 显示特定命令的帮助
            try:
                func = getattr(self, 'do_' + arg)
                doc = func.__doc__
                if doc:
                    self.poutput(doc)
                else:
                    self.poutput(f"命令 '{arg}' 没有帮助文档")
            except AttributeError:
                self.poutput(f"未知命令: '{arg}'")
        else:
            # 显示所有命令的帮助
            self.poutput("\n可用命令:")
            for category, commands in self.categories.items():
                for cmd in commands:
                    func = getattr(self, 'do_' + cmd)
                    if func and func.__doc__:
                        # 显示完整的文档字符串
                        doc = func.__doc__
                        # 对文档进行缩进处理，使其更易读
                        self.poutput(f"  {cmd:<10}{doc}\n")

    # 设置 ? 为help命令的别名
    do_question = do_help

if __name__ == '__main__':
    app = ProxyConfig()
    app.cmdloop()
