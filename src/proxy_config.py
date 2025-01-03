import re
import socket
import random
from db_manager import DatabaseManager

def validate_port(port):
    return 49152 <= port <= 65535

def is_valid_upstream_server(server):
    pattern = r'^(http|https)://\d{1,3}(\.\d{1,3}){3}:\d+$'
    return re.match(pattern, server) is not None

def is_port_available(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('localhost', port))
        return True, port
    except socket.error:
        return False, port
    
def get_socket_port():
    socket_port = db_manager.get_config("socket_port")
    if socket_port and is_port_available(int(socket_port)):
        return int(socket_port)
    else:
        while not socket_port or not is_port_available(int(socket_port)):
            socket_port = random.randint(49152, 65535)
        db_manager.update_config("socket_port", socket_port)
        return socket_port
    
def send_restart_command(socket_port):
    # 创建一个 TCP 客户端
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.connect((HOST, socket_port))
            s.sendall(b"RESTART")
            print("已发送重启命令")
        except ConnectionRefusedError as cre:
            print(f"{cre}请确认代理服务是否启动")
        except Exception as e:
            print(e)

if __name__ == '__main__':
    print("使用方法:")
    print("--proxy_port [port]: 设置代理端口，范围在49152到65535之间，默认代理端口：51949")
    print("--upstream_enable [0/1]: 是否启用上游代理，1为启用，0为不启用，默认不启用，若想启用，请先设置--upstream_server")
    print("--upstream_server [http[s]://host:port]: 上游代理服务，如果计算机上已经开启了本地代理（如Clash），请设置为本地代理服务地址（如http://127.0.0.1:7897）")
    print("--set_option [name=value]：设置mitmproxy配置项")
    print("--delete_option [name]：删除某个mitmproxy配置项")
    print("--restart：重启代理，注意：修改代理设置后需要重启代理")
    print("--select [name]: 查询指定的设置")
    print("--select_all: 查询所有设置")
    print("--help: 显示使用方法")
    print("")
    db_manager = DatabaseManager()
    # 定义服务地址和端口
    HOST = "127.0.0.1"

    while True:
        user_input = input("请输入设置名和设置值（例如：--proxy_port 50000），或输入 'exit' 退出: ").strip()
        if user_input.lower() == 'exit':
            break
        if user_input.startswith("--"):
            parts = user_input.split(" ", 1)
            if len(parts) == 1:
                if parts[0] == '--restart':
                    socket_port = get_socket_port()
                    send_restart_command(socket_port)
                elif parts[0] == '--select_all':
                    all_configs = db_manager.get_all_configs()
                    print("所有设置:")
                    for config in all_configs:
                        print(f"{config[0]}: {config[1]}")
                elif parts[0] == '--help':
                    # 重新输出使用方法
                    print("使用方法:")
                    print("--proxy_port [port]: 设置代理端口，范围在49152到65535之间，默认代理端口：51949")
                    print("--upstream_enable [0/1]: 是否启用上游代理，1为启用，0为不启用，默认不启用，若想启用，请先设置--upstream_server")
                    print("--upstream_server [http[s]://host:port]: 上游代理服务，如果计算机上已经开启了本地代理（如Clash），请设置为本地代理服务地址（如http://127.0.0.1:7897）")
                    print("--set_option [name=value]：设置mitmproxy配置项")
                    print("--delete_option [name]：删除某个mitmproxy配置项")
                    print("--restart：重启代理，注意：修改代理设置后需要重启代理")
                    print("--select [name]: 查询指定的设置")
                    print("--select_all: 查询所有设置")
                    print("--help: 显示使用方法")
                else:
                    print("未知的选项，请输入有效的选项。")
            elif len(parts) == 2:
                setting_name = parts[0][2:]  # 去掉前面的 "--"
                setting_value = parts[1]
                try:
                    if setting_name == "proxy_port":
                        if not setting_value.isdigit():
                            raise ValueError("无效的输入，必须为数字")
                        proxyport = int(setting_value)
                        if validate_port(proxyport):
                            if is_port_available(proxyport):
                                db_manager.update_config('proxy_port', proxyport)
                                print(f"代理端口已设置为: {proxyport}")
                            else:
                                print(f"端口 {proxyport} 已被占用")
                        else:
                            print(f"端口号 {proxyport} 不在范围 49152 到 65535 之间")
                    elif setting_name == "upstream_enable":
                        if not setting_value.isdigit():
                            raise ValueError("无效的输入，必须为数字")
                        upstreamenable = int(setting_value)
                        if upstreamenable not in [0, 1]:
                            raise ValueError("无效的输入，必须为0或1")
                        upstream_server = db_manager.get_config('upstream_server')
                        if upstream_server:
                            db_manager.update_config('upstream_enable', upstreamenable)
                            print(f"上游代理启用状态已设置为: {upstreamenable}")
                        else:
                            print("上游代理服务未设置，请先设置--upstream_server")
                    elif setting_name == "upstream_server":
                        if is_valid_upstream_server(setting_value):
                            db_manager.update_config('upstream_server', setting_value)
                            print(f"上游代理服务已设置为: {setting_value}")
                        else:
                            print("无效的上游代理服务格式，请使用 'http://ip:port' 或 'https://ip:port' 格式。")
                    elif setting_name == "set_option":
                        if '=' in setting_value:
                            parts = setting_value.split('=', 1)
                            option_name, option_value = parts
                            db_manager.update_option(option_name, option_value)
                            print(f"设置 {option_name} = {option_value}")
                        else:
                            print("无效的输入，必须包含=")
                    elif setting_name == "delete_option":
                        count = db_manager.delete_option(setting_value)
                        if count > 0:
                            print(f"配置项 {setting_value} 已删除")
                        else:
                            print(f"未找到配置项 {setting_name}，请确认配置项名称")
                    elif setting_name == "select":
                        config_value = db_manager.get_config(setting_value)
                        if config_value is not None:
                            print(f"{setting_value}: {config_value}")
                        else:
                            print(f"未找到设置: {setting_value}")
                    else:
                        print("未知的设置名，请输入有效的设置名。")
                except ValueError as e:
                    print(e)
            else:
                print("输入格式错误，请输入设置名和设置值。")
        else:
            print("输入格式错误，请以 '--' 开头。")
