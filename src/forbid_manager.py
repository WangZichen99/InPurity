import os
import mmap
import time
import base64
import pickle
import traceback
import threading
import win32crypt
from datetime import datetime
from constants import IMNATSEKR_PATH

class ForbidEventManager:
    """禁止事件管理器，负责禁止事件的存储、读取和管理"""
    
    def __init__(self):
        """初始化禁止事件管理器"""
        # 禁止事件文件的路径
        self.forbid_file_path = IMNATSEKR_PATH
        
        # 确保目录存在
        parent_dir = os.path.dirname(self.forbid_file_path)
        os.makedirs(parent_dir, exist_ok=True)
        
        # 检查文件是否存在，如果不存在则创建一个空的.pyd文件
        if not os.path.exists(self.forbid_file_path):
            self._create_fake_pyd_file()
        
        # 设置初始文件大小以确保有足够空间
        self._ensure_initial_file_size()
        
        # 创建内存映射
        self._setup_memory_mapping()
        
        # 事件分隔符 (记录分隔符，不可见字符)
        self.event_separator = '\x1E'
        # 线程锁，保证线程安全
        self.file_lock = threading.RLock()
        
        # 使用不常见的二进制序列作为标记
        # 使用看起来像合法的二进制指令或数据的字节序列
        self.data_start_mark = b'\xE9\x45\x8B\x27\x19'  # 模拟跳转指令
        self.data_end_mark = b'\xC3\x90\x90\x90\x90'    # 模拟返回指令和NOP填充
    
    def _create_fake_pyd_file(self):
        """创建一个伪装的.pyd文件"""
        try:
            with open(self.forbid_file_path, 'wb') as f:
                # 写入一些看起来像二进制模块的随机头数据
                f.write(b'\x03\xf3\r\n\x00\x00\x00\x00')  # Python模块魔术数
                f.write(os.urandom(32))  # 添加一些随机数据
                f.write(b'_intercept\x00')  # 模块名称
                f.write(os.urandom(64))  # 再添加一些随机数据
        except Exception as e:
            print(f"创建伪装pyd文件时出错: {str(e)}")
            traceback.print_exc()
    
    def _setup_memory_mapping(self):
        """设置内存映射以占用文件"""
        try:
            # 确保文件至少有一定大小
            self._ensure_file_size()
            
            # 关闭现有句柄（如果有）
            self._close_file_handles()
            
            # 打开文件并创建内存映射
            self._file_handle = open(self.forbid_file_path, 'r+b')
            self._mmap = mmap.mmap(self._file_handle.fileno(), 0)
        except Exception as e:
            print(f"创建内存映射失败: {str(e)}")
            traceback.print_exc()
            # 确保属性存在，即使创建失败
            if not hasattr(self, '_file_handle'):
                self._file_handle = None
            if not hasattr(self, '_mmap'):
                self._mmap = None
    
    def _close_file_handles(self):
        """关闭现有的文件句柄和内存映射"""
        try:
            if hasattr(self, '_mmap') and self._mmap:
                self._mmap.close()
                self._mmap = None
            if hasattr(self, '_file_handle') and self._file_handle:
                self._file_handle.close()
                self._file_handle = None
        except Exception as e:
            print(f"关闭文件句柄时出错: {str(e)}")
            traceback.print_exc()
        
    def _ensure_file_size(self):
        """确保文件至少有一定大小，以便创建内存映射"""
        try:
            size = os.path.getsize(self.forbid_file_path)
            if size < 1024:  # 如果文件太小
                with open(self.forbid_file_path, 'ab') as f:
                    f.write(b'\x00' * (1024 - size))  # 扩展文件大小
        except Exception as e:
            print(f"确保文件大小时出错: {str(e)}")
            traceback.print_exc()
    
    def __del__(self):
        """析构函数，确保清理资源"""
        self._close_file_handles()
    
    def _encrypt_data(self, data):
        """加密数据"""
        try:
            # 使用 pickle 序列化数据
            serialized_data = pickle.dumps(data)
            # 使用 DPAPI 加密数据
            protected_data = win32crypt.CryptProtectData(
                serialized_data,
                "InPurity Forbid Event",
                None, None, None,
                0x04
            )
            # 再进行 base64 编码，便于存储
            return base64.b64encode(protected_data).decode('utf-8')
        except Exception as e:
            print(f"加密数据失败: {str(e)}")
            traceback.print_exc()
            return None
    
    def _decrypt_data(self, encrypted_data):
        """解密数据"""
        try:
            # base64 解码
            decoded_data = base64.b64decode(encrypted_data)
            # 使用 DPAPI 解密数据
            decrypted_data = win32crypt.CryptUnprotectData(
                decoded_data,
                None, None, None,
                0x04
            )[1]
            # 使用 pickle 反序列化数据
            return pickle.loads(decrypted_data)
        except Exception as e:
            print(f"解密数据失败: {str(e)}")
            traceback.print_exc()
            return None
    
    def _ensure_initial_file_size(self):
        """确保文件有足够的初始大小"""
        try:
            # 初始分配较大空间，以便存储加密数据
            initial_size = 32 * 1024  # 32KB 初始大小
            current_size = os.path.getsize(self.forbid_file_path) if os.path.exists(self.forbid_file_path) else 0
            
            if current_size < initial_size:
                with open(self.forbid_file_path, 'ab') as f:
                    f.write(b'\x00' * (initial_size - current_size))
        except Exception as e:
            print(f"设置初始文件大小时出错: {str(e)}")
            traceback.print_exc()
    
    def _resize_mapped_file(self, needed_size):
        """调整内存映射文件的大小"""
        try:
            # 关闭现有映射
            self._close_file_handles()
            
            # 获取当前文件大小
            current_size = os.path.getsize(self.forbid_file_path)
            
            # 如果需要更大的空间，则调整文件大小
            if needed_size > current_size:
                # 计算新的文件大小（向上取整到最接近的4KB的倍数）
                new_size = ((needed_size + 4095) // 4096) * 4096
                
                with open(self.forbid_file_path, 'ab') as f:
                    f.write(b'\x00' * (new_size - current_size))
            
            # 重新创建内存映射
            self._setup_memory_mapping()
            return True
        except Exception as e:
            print(f"调整文件大小时出错: {str(e)}")
            traceback.print_exc()
            return False
    
    def _read_data_from_mmap(self):
        """从内存映射中读取数据"""
        try:
            if not self._mmap:
                return None, ""
            
            # 将整个映射读入内存
            self._mmap.seek(0)
            file_content = self._mmap.read()
            
            # 检查是否为我们创建的伪装pyd文件
            if file_content.startswith(b'\x03\xf3\r\n\x00\x00\x00\x00'):
                header_size = 128
                header = file_content[:header_size] if len(file_content) >= header_size else file_content
                
                # 查找分隔符位置
                separator_pos = file_content.find(b'\n\n')
                if separator_pos != -1:
                    # 提取数据部分
                    data_content = file_content[separator_pos+2:]
                    # 查找数据标记
                    start_pos = data_content.find(self.data_start_mark)
                    end_pos = data_content.find(self.data_end_mark)
                    
                    if start_pos != -1 and end_pos != -1 and start_pos < end_pos:
                        # 提取标记之间的实际数据
                        actual_content = data_content[start_pos + len(self.data_start_mark):end_pos]
                        try:
                            return header, actual_content.decode('utf-8')
                        except UnicodeDecodeError:
                            print("无法解码数据")
                            traceback.print_exc()
                            return header, ""
                return header, ""
            else:
                # 如果不是我们创建的文件，查找数据标记
                start_pos = file_content.find(self.data_start_mark)
                end_pos = file_content.find(self.data_end_mark)
                
                if start_pos != -1 and end_pos != -1 and start_pos < end_pos:
                    actual_content = file_content[start_pos + len(self.data_start_mark):end_pos]
                    try:
                        return None, actual_content.decode('utf-8')
                    except UnicodeDecodeError:
                        print("无法解码数据")
                        traceback.print_exc()
                        return None, ""
                else:
                    return None, ""
        except Exception as e:
            print(f"从内存映射读取数据时出错: {str(e)}")
            traceback.print_exc()
            return None, ""
    
    def _write_data_to_mmap(self, content):
        """将数据写入内存映射"""
        try:
            if not self._mmap:
                return False
            
            # 获取头部信息
            header, _ = self._read_data_from_mmap()
            
            # 准备要写入的数据
            marked_content = self.data_start_mark + content.encode('utf-8') + self.data_end_mark
            
            # 计算总大小
            total_size = 0
            if header:
                total_size += len(header) + 2  # 头部 + 分隔符 \n\n
            total_size += len(marked_content)
            
            # 检查是否需要调整文件大小
            if total_size > len(self._mmap):
                # 需要重新调整文件大小
                if not self._resize_mapped_file(total_size):
                    return False
            
            # 清空文件内容（写入零字节）
            self._mmap.seek(0)
            self._mmap.write(b'\x00' * len(self._mmap))
            
            # 将新内容写入内存映射
            self._mmap.seek(0)
            if header:
                self._mmap.write(header)
                self._mmap.write(b'\n\n')
            self._mmap.write(marked_content)
            
            # 确保数据被写入磁盘
            self._mmap.flush()
            
            return True
        except Exception as e:
            print(f"写入内存映射时出错: {str(e)}")
            traceback.print_exc()
            return False
    
    def _read_file_content(self):
        """读取文件内容（使用内存映射）"""
        return self._read_data_from_mmap()
    
    def _write_with_preserved_header(self, content):
        """写入内容并保留文件头部（使用内存映射）"""
        return self._write_data_to_mmap(content)
    
    def save_forbid_event(self, mode, start_time, duration, cache_set, count=0):
        """保存禁止事件"""
        with self.file_lock:
            try:
                # 计算结束时间
                end_time = start_time + duration
                
                # 创建事件数据
                event_data = {
                    'mode': mode,
                    'start_time': start_time,
                    'duration': duration,
                    'end_time': end_time,
                    'cache_set': list(cache_set),  # 转换为列表以便序列化
                    'count': count  # 添加危险计数
                }
                
                # 读取现有事件
                existing_events = self.read_forbid_events()
                
                # 添加新事件
                existing_events.append(event_data)
                
                # 只保留未过期的事件
                current_time = time.time()
                valid_events = [event for event in existing_events if event['end_time'] > current_time]
                # 加密所有事件数据
                encrypted_events = []
                for event in valid_events:
                    encrypted_event = self._encrypt_data(event)
                    if encrypted_event:  # 确保加密成功
                        encrypted_events.append(encrypted_event)
                # 将所有事件写入文件，使用分隔符分隔
                content = self.event_separator.join(encrypted_events)
                # 写入文件
                return self._write_with_preserved_header(content)
            except Exception as e:
                print(f"保存禁止事件失败: {str(e)}")
                traceback.print_exc()
                return False
    
    def read_forbid_events(self):
        """读取所有禁止事件"""
        with self.file_lock:
            try:
                # 读取文件内容
                _, content = self._read_file_content()
                
                if not content:
                    return []
                
                # 分割事件
                encrypted_events = content.split(self.event_separator)

                # 解密所有事件
                events = []
                for encrypted_event in encrypted_events:
                    if encrypted_event:  # 确保不是空字符串
                        event = self._decrypt_data(encrypted_event)
                        if event:
                            # 将缓存集合从列表转回为集合
                            event['cache_set'] = set(event['cache_set'])
                            events.append(event)
                
                return events
            except Exception as e:
                print(f"读取禁止事件失败: {str(e)}")
                traceback.print_exc()
                return []
    
    def get_active_forbid_event(self):
        """获取当前活跃的禁止事件（如果有）"""
        try:
            events = self.read_forbid_events()
            current_time = time.time()
            
            # 按结束时间降序排序，找到最近的一个未过期事件
            active_events = [event for event in events if event['end_time'] > current_time]
            if active_events:
                # 按结束时间降序排序，返回结束时间最晚的事件
                return sorted(active_events, key=lambda x: x['end_time'], reverse=True)[0]
        except Exception as e:
            print(f"获取活跃禁止事件失败: {str(e)}")
            traceback.print_exc()
        
        return None
    
    def clear_expired_events(self):
        """清理过期的事件"""
        with self.file_lock:
            try:
                events = self.read_forbid_events()
                current_time = time.time()
                
                # 过滤出未过期的事件
                valid_events = [event for event in events if event['end_time'] > current_time]
                
                # 只有当有事件被清理时才重新写入文件
                if len(valid_events) < len(events):
                    # 加密所有事件数据
                    encrypted_events = []
                    for event in valid_events:
                        encrypted_event = self._encrypt_data(event)
                        if encrypted_event:  # 确保加密成功
                            encrypted_events.append(encrypted_event)
                    
                    # 将所有事件写入文件，使用分隔符分隔
                    content = self.event_separator.join(encrypted_events)
                    
                    # 写入文件并保留头部
                    return self._write_with_preserved_header(content)
                
                return True
            except Exception as e:
                print(f"清理过期事件失败: {str(e)}")
                traceback.print_exc()
                return False


# 用于测试ForbidEventManager类的功能
if __name__ == "__main__":
    '''
    encrypted_data = "AQAAANCMnd8BFdERjHoAwE/Cl+sBAAAAFIA/BuvCek2W+y2UfEUr8gQAAAAsAAAASQBuAFAAdQByAGkAdAB5ACAARgBvAHIAYgBpAGQAIABFAHYAZQBuAHQAAAAQZgAAAAEAACAAAABpffIHqAgFwBIDNtsZ/yDWA0YCicWvaGXeJ546/e1BBgAAAAAOgAAAAAIAACAAAABPjNDSsZMANnheesqXgPwIy5WMnkp0xNVUj5BbejREzoAAAAC6e1DZQH+wMTZmRSrxWr8HYT98lglvgfntXqupR/iN+42Ztr1Ye3fz0MPoebBOKNkWmN6taWduI9aTXUxUm5r3ITBMZ+/miRW1C3nlq0Jx/w+lScaxq+DdMv1UZkuEav6ep+pOk7nRJZe9yWGQZnYx357TWJ09Lv1bgRQzJm48ZUAAAABc6FAV5HZczauiRY+LOww98gNIL0AHy8V2Pt7/KtKapzvloqmetHb7FAJaDkpsxLhMLk86+Sw6J4XquFV8nANz"

    # base64 解码
    decoded_data = base64.b64decode(encrypted_data)
    # 使用 DPAPI 解密数据
    decrypted_data = win32crypt.CryptUnprotectData(
        decoded_data,
        None, None, None,
        0x04
    )[1]
    # 使用 pickle 反序列化数据
    print(pickle.loads(decrypted_data))

    exit(1)
    '''


    print("开始测试禁止事件管理器...")
    
    # 创建管理器实例
    manager = ForbidEventManager()
    
    # 检查并清理现有的过期事件
    manager.clear_expired_events()
    
    # 检查是否有活跃的禁止事件
    active_event = manager.get_active_forbid_event()
    if active_event:
        print("发现活跃的禁止事件:")
        print(f"  模式: {active_event['mode']}")
        print(f"  开始时间: {datetime.fromtimestamp(active_event['start_time']).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  结束时间: {datetime.fromtimestamp(active_event['end_time']).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  剩余时间: {int((active_event['end_time'] - time.time()) / 60)} 分钟")
        print(f"  黑名单缓存条目数: {len(active_event['cache_set'])}")
    else:
        print("没有发现活跃的禁止事件")
    
    # 测试保存短时间的禁止事件
    print("\n测试保存短时间禁止事件 (5秒)...")
    current_time = time.time()
    # 模拟黑名单缓存集合
    test_cache_set = set(['test1', 'test2', 'test3'])
    manager.save_forbid_event('images', current_time, 5, test_cache_set)

    # 读取并显示刚保存的事件
    events = manager.read_forbid_events()
    print(f"读取到 {len(events)} 个禁止事件")
    for i, event in enumerate(events):
        print(f"事件 {i+1}:")
        print(f"  模式: {event['mode']}")
        print(f"  开始时间: {datetime.fromtimestamp(event['start_time']).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  结束时间: {datetime.fromtimestamp(event['end_time']).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  持续时间: {event['duration']} 秒")
        print(f"  黑名单缓存条目数: {len(event['cache_set'])}")
    
    # 等待短暂事件过期
    print("\n等待短暂事件过期...")
    time.sleep(6)
    
    # 清理过期事件
    print("清理过期事件...")
    manager.clear_expired_events()
    
    # 再次检查活跃事件
    events = manager.read_forbid_events()
    print(f"清理后剩余 {len(events)} 个禁止事件")
    
    # 测试保存长时间的禁止事件
    print("\n测试保存长时间禁止事件 (30分钟)...")
    # 模拟更大的黑名单缓存集合
    larger_cache_set = set([f'test{i}' for i in range(100)])
    manager.save_forbid_event('requests', current_time, 1800, larger_cache_set)
    
    # 获取活跃事件
    active_event = manager.get_active_forbid_event()
    if active_event:
        print("最新的活跃禁止事件:")
        print(f"  模式: {active_event['mode']}")
        print(f"  开始时间: {datetime.fromtimestamp(active_event['start_time']).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  结束时间: {datetime.fromtimestamp(active_event['end_time']).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  持续时间: {int(active_event['duration'] / 60)} 分钟")
        print(f"  黑名单缓存条目数: {len(active_event['cache_set'])}")
    
    # 文件检查
    print(f"\n禁止事件文件存储在: {manager.forbid_file_path}")
    
    if os.path.exists(manager.forbid_file_path):
        file_size = os.path.getsize(manager.forbid_file_path)
        print(f"文件大小: {file_size} 字节")
        print("文件内容是加密的，无法直接查看")
        
        # 尝试打开文件，查看部分内容（加密的）
        try:
            with open(manager.forbid_file_path, 'rb') as f:
                content = f.read(100)  # 只读取前100个字符
                print(f"文件前100个字符(加密后): {content}...")
        except Exception as e:
            print(f"读取文件内容时出错: {str(e)}")
    else:
        print("文件不存在，可能创建失败")
    
    print("\n测试完成!") 