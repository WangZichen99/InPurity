import re
import socket

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style

from i18n import I18n as _
from db_manager import DatabaseManager

class ProxyConfigCompleter(Completer):
    """自定义命令补全器"""
    
    def __init__(self, proxy_config):
        self.proxy_config = proxy_config
        self.commands = {
            'port': self.complete_port,
            'upstream': self.complete_upstream,
            'batch': self.complete_batch,
            'setopt': self.complete_empty,
            'delopt': self.complete_delopt,
            'select': self.complete_select,
            'restart': self.complete_empty,
            'quit': self.complete_empty,
            'help': self.complete_help,
            '?': self.complete_help
        }
        # 缓存常用选项列表，避免频繁查询数据库
        self.options_cache = None
        self.configs_cache = None
        self.last_cache_update = 0
    
    def _should_refresh_cache(self):
        """检查是否应该刷新缓存（5秒过期）"""
        import time
        current_time = time.time()
        if current_time - self.last_cache_update > 5:
            self.last_cache_update = current_time
            return True
        return False
    
    def get_completions(self, document, complete_event):
        text = document.text
        if ' ' in text:
            # 命令参数补全
            cmd, arg = text.split(' ', 1)
            cmd = cmd.strip()
            arg = arg.strip()
            
            if cmd in self.commands:
                for completion in self.commands[cmd](arg):
                    yield Completion(completion, start_position=-len(arg))
        else:
            # 命令名补全
            for cmd in self.commands:
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text))
    
    def complete_port(self, text):
        if not text:
            return ['51949']
        return []
    
    def complete_upstream(self, text):
        options = ['enable', 'disable', 'http://', 'https://']
        return [opt for opt in options if opt.startswith(text)]
    
    def complete_batch(self, text):
        options = ['enable', 'disable']
        return [opt for opt in options if opt.startswith(text)]
    
    def complete_delopt(self, text):
        # 使用缓存减少数据库查询
        if self.options_cache is None or self._should_refresh_cache():
            self.options_cache = self.proxy_config.db_manager.get_all_options()
        
        option_names = [opt[0] for opt in self.options_cache]
        return [opt for opt in option_names if opt.startswith(text)]
    
    def complete_select(self, text):
        # 使用缓存减少数据库查询
        if self.configs_cache is None or self._should_refresh_cache():
            self.configs_cache = self.proxy_config.db_manager.get_all_configs()
        
        config_names = [conf[0] for conf in self.configs_cache]
        return [conf for conf in config_names if conf.startswith(text)]
    
    def complete_help(self, text):
        return [cmd for cmd in self.commands if cmd.startswith(text)]
    
    def complete_empty(self, text):
        return []

class ProxyConfig:
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.HOST = "127.0.0.1"
        
        # 命令处理函数映射
        self.commands = {
            'port': self.cmd_port,
            'upstream': self.cmd_upstream,
            'setopt': self.cmd_setopt,
            'delopt': self.cmd_delopt,
            'select': self.cmd_select,
            'batch': self.cmd_batch,
            'restart': self.cmd_restart,
            'quit': self.cmd_quit,
            'help': self.cmd_help,
            '?': self.cmd_help
        }
        
        # 命令帮助文档
        self.help_docs = {
            'port': _.get('help_port'),
            'upstream': _.get('help_upstream'),
            'setopt': _.get('help_setopt'),
            'delopt': _.get('help_delopt'),
            'select': _.get('help_select'),
            'batch': _.get('help_batch'),
            'restart': _.get('help_restart'),
            'quit': _.get('help_quit'),
            'help': _.get('help_help')
        }
        
        # 命令分类 - 使用国际化
        self.categories = {
            _.get('category_proxy_settings'): ['port', 'upstream', 'batch'],
            _.get('category_config_management'): ['setopt', 'delopt', 'select'],
            _.get('category_system_operations'): ['restart', 'quit']
        }
        
        # 设置样式
        self.style = Style.from_dict({
            'prompt': 'ansicyan bold',
            'output': '',
            'error': 'ansired bold',
        })
        
        # 创建会话
        self.session = PromptSession(
            completer=ProxyConfigCompleter(self),
            style=self.style,
            # history_filename='.inpurity_history'
        )
    
    def validate_port(self, port):
        return 49152 <= port <= 65535

    def is_valid_upstream_server(self, server):
        """验证上游服务器地址，支持IP和域名"""
        # 支持域名或IP地址
        pattern = r'^(http|https)://([a-zA-Z0-9][-a-zA-Z0-9.]*(\.[a-zA-Z0-9][-a-zA-Z0-9.]*)+|\d{1,3}(\.\d{1,3}){3}):\d+$'
        return re.match(pattern, server) is not None

    def is_port_available(self, port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
            return True
        except socket.error:
            return False

    def send_restart_command(self):
        socket_port = self.db_manager.get_config("socket_port")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.connect((self.HOST, int(socket_port)))
                s.sendall(b"RESTART")
                self.print_output(_.get('restart_sent'))
            except ConnectionRefusedError as cre:
                self.print_error(_.get('restart_error', cre))
            except Exception as e:
                self.print_error(_.get('error_generic', str(e)))
    
    def print_output(self, text):
        print(text)
    
    def print_error(self, text):
        print(f"\033[91m{text}\033[0m")  # 红色输出错误信息
    
    def cmd_port(self, arg):
        if not arg:
            self.print_error(_.get('port_required'))
            return
        try:
            port = int(arg)
            if self.validate_port(port):
                if self.is_port_available(port):
                    self.db_manager.update_config('proxy_port', port)
                    self.print_output(_.get('port_set', port))
                else:
                    self.print_error(_.get('port_in_use', port))
            else:
                self.print_error(_.get('port_out_range', port))
        except ValueError:
            self.print_error(_.get('port_invalid'))
    
    def cmd_upstream(self, arg):
        if not arg:
            self.print_error(_.get('operation_required'))
            return

        if arg == 'enable':
            upstream_server = self.db_manager.get_config('upstream_server')
            if upstream_server:
                self.db_manager.update_config('upstream_enable', 1)
                self.print_output(_.get('upstream_enabled'))
            else:
                self.print_error(_.get('upstream_not_set'))
        elif arg == 'disable':
            self.db_manager.update_config('upstream_enable', 0)
            self.print_output(_.get('upstream_disabled'))
        elif arg.startswith(('http://', 'https://')):
            if self.is_valid_upstream_server(arg):
                self.db_manager.update_config('upstream_server', arg)
                self.db_manager.update_config('upstream_enable', 1)
                self.print_output(_.get('upstream_set', arg))
            else:
                self.print_error(_.get('upstream_invalid'))
        else:
            self.print_error(_.get('upstream_cmd_invalid'))
    
    def cmd_setopt(self, arg):
        if not arg:
            self.print_error(_.get('option_required'))
            return
        if '=' not in arg:
            self.print_error(_.get('option_invalid'))
            return
        
        name, value = arg.split('=', 1)
        name = name.strip()
        value = value.strip()
            
        self.db_manager.update_option(name, value)
        self.print_output(_.get('option_set', name, value))
    
    def cmd_delopt(self, arg):
        if not arg:
            self.print_error(_.get('option_name_required'))
            return
        
        count = self.db_manager.delete_option(arg)
        if count > 0:
            self.print_output(_.get('option_deleted', arg))
        else:
            self.print_error(_.get('option_not_found', arg))
    
    def cmd_select(self, arg):
        if arg:
            config_value = self.db_manager.get_config(arg)
            if config_value is not None:
                self.print_output(_.get('config_value_display', arg, config_value))
            else:
                self.print_error(_.get('config_not_found', arg))
        else:
            all_configs = self.db_manager.get_all_configs()
            self.print_output(_.get('all_configs'))
            for config in all_configs:
                self.print_output(_.get('config_value_display', config[0], config[1]))
    
    def cmd_batch(self, arg):
        if not arg:
            self.print_error(_.get("batch_required"))
            return

        arg = arg.lower()
        if arg not in ['enable', 'disable']:
            self.print_error(_.get("batch_cmd_invalid"))
            return

        try:
            self.db_manager.update_config(
                'enable_batch_processing',
                '1' if arg == 'enable' else '0'
            )
            self.print_output(_.get("batch_enabled" if arg == 'enable' else "batch_disabled"))
        except Exception as e:
            self.print_error(_.get('error_generic', str(e)))
    
    def cmd_restart(self, _):
        self.send_restart_command()
    
    def cmd_quit(self, _):
        return True
    
    def cmd_help(self, arg):
        if arg:
            # 显示特定命令的帮助
            if arg in self.help_docs:
                self.print_output(self.help_docs[arg])
            else:
                self.print_output(_.get('unknown_command', arg))
        else:
            # 显示所有命令的帮助
            self.print_output(_.get('available_commands'))
            for category, commands in self.categories.items():
                self.print_output(f"\n{category}:")
                for cmd in commands:
                    if cmd in self.help_docs:
                        # 显示第一行帮助信息作为简要说明
                        doc = self.help_docs[cmd].split('\n')[0]
                        self.print_output(f"  {cmd:<10}{doc}")
    
    def run(self):
        print(_.get('proxy_tool_intro'))
        
        while True:
            try:
                text = self.session.prompt('InPurity> ')
                text = text.strip()
                
                if not text:
                    continue
                
                # 解析命令和参数
                parts = text.split(' ', 1)
                cmd = parts[0]
                arg = parts[1] if len(parts) > 1 else ''
                
                # 执行命令
                if cmd in self.commands:
                    if self.commands[cmd](arg):
                        break
                else:
                    self.print_error(_.get('unknown_command', cmd))
            
            except KeyboardInterrupt:
                continue
            except EOFError:
                break
            except Exception as e:
                self.print_error(_.get('error_generic', str(e)))
        
        print(_.get('goodbye'))

if __name__ == '__main__':
    app = ProxyConfig()
    app.run()
