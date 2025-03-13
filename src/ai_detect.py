import time  # 用于时间记录
import psutil  # 用于内存监控
import hashlib
import threading
import numpy as np
from i18n import I18n
import multiprocessing
from queue import Queue
import onnxruntime as ort
from collections import OrderedDict
from db_manager import DatabaseManager
from constants import IMAGE_MODEL_FILE, IMAGE_THRESHOLD
from concurrent.futures import ThreadPoolExecutor, Future, wait

class ImagePredictor:
    def __init__(self, logger):
            self.logger = logger
            # 初始化线程池和会话管理
            cpu_count = multiprocessing.cpu_count()
            self.max_workers = min(cpu_count * 2, 8)
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
            self.sessions = {}
            self.session_lock = threading.Lock()
            
            # 优化1: 使用OrderedDict实现LRU缓存，而不是简单的字典
            self.image_cache = OrderedDict()  # 用于存储图像预测结果的缓存
            self.cache_lock = threading.Lock()  # 用于保护缓存的线程锁
            self.max_cache_size = 1000  # 最大缓存项数
            
            # 批处理相关
            self.db = DatabaseManager()
            self.enable_batch_processing = self._get_batch_config()  # 从数据库读取配置
            self.batch_size = 8  # 批处理大小
            self.batch_timeout = 0.1  # 批处理等待超时时间（秒）
            self.batch_queue = Queue()  # 批处理队列
            self.batch_results = {}  # 存储批处理结果
            self.batch_lock = threading.Lock()  # 批处理锁
            
            # 优化2-1: 懒加载模型相关 - 只保存路径，不立即加载
            self.model_path = IMAGE_MODEL_FILE
            self.model_initialized = False  # 标记模型是否已初始化
            self.session_last_used = {}  # 记录每个会话最后使用时间
            
            # 优化1-1: 启动内存监控线程
            self.request_count = 0  # 请求计数器，用于基于请求量的清理检查
            self.last_cleanup_time = 0  # 上次清理时间
            self._start_resource_monitor()
            
            if self.enable_batch_processing:
                self._start_batch_processor()  # 只在启用批处理时启动处理器

    def _start_resource_monitor(self):
        """启动资源监控线程"""
        monitor_thread = threading.Thread(
            target=self._resource_monitor,
            daemon=True
        )
        monitor_thread.start()
        
    def _resource_monitor(self):
        """综合资源监控线程"""
        while True:
            time.sleep(300)  # 每5分钟检查一次
            
            # 检查内存使用
            memory_percent = psutil.virtual_memory().percent
            current_time = time.time()
            
            # 只有距离上次清理超过30秒才执行
            if current_time - self.last_cleanup_time > 30:
                if memory_percent > 75:
                    self._perform_cleanup(memory_percent, "定时检查")
                    self.last_cleanup_time = current_time
    
    def _perform_cleanup(self, memory_percent, trigger_source):
        """统一的资源清理方法
        
        Args:
            memory_percent: 当前内存使用百分比
            trigger_source: 触发清理的来源（"定时检查"或"请求量检查"）
        """
        if memory_percent > 85:  # 内存压力非常大
            # 清理所有缓存
            with self.cache_lock:
                self.image_cache.clear()
            # 清理不活跃会话
            self._cleanup_inactive_sessions()
            self.logger.info(I18n.get("memory_high_cleanup", memory_percent, trigger_source))
        elif memory_percent > 75:  # 内存压力较大
            # 清理部分缓存
            with self.cache_lock:
                items_to_remove = len(self.image_cache) // 4  # 统一为清理25%
                for _ in range(items_to_remove):
                    if self.image_cache:
                        self.image_cache.popitem(last=False)
            self.logger.info(I18n.get("memory_medium_cleanup", memory_percent, trigger_source))
    
    def _cleanup_inactive_sessions(self):
        """清理长时间不活跃的会话"""
        with self.session_lock:
            current_time = time.time()
            inactive_threads = []
            
            # 找出不活跃的线程
            for thread_id, last_used in self.session_last_used.items():
                if current_time - last_used > 1800:  # 30分钟未使用
                    inactive_threads.append(thread_id)
            
            # 移除不活跃的会话
            for thread_id in inactive_threads:
                if thread_id in self.sessions:
                    del self.sessions[thread_id]
                    del self.session_last_used[thread_id]
                    self.logger.info(I18n.get("inactive_session_released", thread_id))

    def _get_batch_config(self):
        """从数据库读取批处理配置"""
        try:
            # 使用参数化查询读取配置，利用config_type索引提高查询效率
            result = self.db.fetchone("SELECT value FROM config WHERE key = ? AND config_type = '0'", ('enable_batch_processing',))
            if result:
                return result[0] == '1'
            # 如果配置不存在，创建默认配置（禁用）
            self.db.safe_execute(
                "INSERT INTO config (key, value, config_type) VALUES (?, ?, '0')",
                ('enable_batch_processing', '0')
            )
            return False
        except Exception as e:
            self.logger.exception(I18n.get("batch_config_error", str(e)))
            return False

    def update_batch_config(self, enable: bool):
        """更新批处理配置"""
        try:
            # 使用参数化查询更新数据库配置
            self.db.safe_execute(
                "UPDATE config SET value = ? WHERE key = ? AND config_type = '0'",
                ('1' if enable else '0', 'enable_batch_processing')
            )
            
            # 更新运行时配置
            old_config = self.enable_batch_processing
            self.enable_batch_processing = enable
            
            # 如果配置从禁用变为启用，启动处理器
            if not old_config and enable:
                self._start_batch_processor()
            
            return True
        except Exception as e:
            self.logger.exception(I18n.get("batch_update_error", str(e)))
            return False

    def _start_batch_processor(self):
        """启动批处理处理器线程"""
        def batch_processor():
            while True:
                batch_items = []
                batch_futures = []
                try:
                    # 收集一批图像
                    while len(batch_items) < self.batch_size:
                        try:
                            item = self.batch_queue.get(timeout=self.batch_timeout)
                            batch_items.append(item['img_array'])
                            batch_futures.append(item['future'])
                        except:  # 超时
                            break
                    
                    if not batch_items:  # 没有收集到任何图像
                        continue
                    
                    # 处理收集到的批次
                    if batch_items:
                        # 将图像数组堆叠成批次
                        batch_array = np.stack(batch_items)
                        # 进行批量预测
                        predictions = self._predict_batch(batch_array)
                        # 分发结果
                        for i, future in enumerate(batch_futures):
                            result = predictions[i][1] > IMAGE_THRESHOLD or \
                                    predictions[i][3] > IMAGE_THRESHOLD or \
                                    predictions[i][4] > IMAGE_THRESHOLD
                            future.set_result((predictions[i], result))
                except Exception as e:
                    self.logger.exception(I18n.get("batch_processing_error", str(e)))
                    # 如果发生错误，为所有等待的future设置异常
                    for future in batch_futures:
                        if not future.done():
                            future.set_exception(e)
        
        # 启动批处理线程
        batch_thread = threading.Thread(target=batch_processor, daemon=True)
        batch_thread.start()

    def _predict_batch(self, batch_array):
        """执行批量预测"""
        session = self.get_session()
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name
        predictions = session.run([output_name], {input_name: batch_array})[0]
        return predictions

    def get_session(self):
        """为每个线程获取独立的 ONNX 会话，实现懒加载"""
        thread_id = threading.get_ident()
        with self.session_lock:
            if thread_id not in self.sessions:
                # 延迟加载模型
                self.sessions[thread_id] = ort.InferenceSession(
                    self.model_path,
                    providers=['CPUExecutionProvider']
                )
                
                # 第一次加载模型时进行预热
                if not self.model_initialized:
                    self._warm_up_model(self.sessions[thread_id])
                    self.model_initialized = True
            
            # 更新最后使用时间
            self.session_last_used[thread_id] = time.time()
            return self.sessions[thread_id]
    
    def _warm_up_model(self, session):
        """模型预热，避免首次推理的性能损失"""
        dummy_input = np.random.rand(1, 224, 224, 3).astype(np.float32)
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name
        session.run([output_name], {input_name: dummy_input})

    def _compute_image_hash(self, img_array):
        """计算图像的哈希值，用于缓存查找"""
        return hashlib.md5(img_array.tobytes()).hexdigest()
    
    def _check_cache(self, img_hash):
        """检查图像是否在缓存中，并返回缓存的结果。如果命中，将该项移到最近使用的位置"""
        with self.cache_lock:
            if img_hash in self.image_cache:
                # LRU缓存访问: 移动到最末尾(最近使用的位置)
                self.image_cache.move_to_end(img_hash)
                return self.image_cache[img_hash]
            return None
    
    def _update_cache(self, img_hash, result):
        """更新LRU缓存，如果缓存太大则移除最久未使用的项"""
        with self.cache_lock:
            # 如果缓存已满，移除最久未使用的项(OrderedDict的第一项)
            if len(self.image_cache) >= self.max_cache_size:
                try:
                    # OrderedDict中的第一个项是最久未使用的
                    self.image_cache.popitem(last=False)
                except:
                    # 如果发生错误，清空整个缓存
                    self.image_cache.clear()
            # 添加新的缓存项(自动加到OrderedDict的末尾，表示最近使用)
            self.image_cache[img_hash] = result

    def predict_image(self, img):
        try:
            # 增加请求计数
            self.request_count += 1
            
            # 每处理100个请求检查一次内存，但确保距离上次清理至少间隔30秒
            current_time = time.time()
            if self.request_count % 100 == 0 and current_time - self.last_cleanup_time > 30:
                memory_percent = psutil.virtual_memory().percent
                if memory_percent > 75:
                    self._perform_cleanup(memory_percent, "请求量检查")
                    self.last_cleanup_time = current_time
            
            # 如果是 GIF，进行逐帧检测
            if getattr(img, 'is_animated', False):
                return self._predict_gif(img)
            
            # 调整图像大小并预处理
            img = img.resize((224, 224))  # 调整图像尺寸为 224x224
            img_array = np.array(img)  # 转换为数组
            
            # 如果图像不是 RGB 格式，则将其转换为 RGB
            if img_array.shape[-1] != 3:
                img = img.convert('RGB')
                img_array = np.array(img)
            
            # 计算图像哈希值
            img_hash = self._compute_image_hash(img_array)
            
            # 检查缓存
            cached_result = self._check_cache(img_hash)
            if cached_result is not None:
                self.logger.info(I18n.get("cache_hit", img_hash))
                return cached_result
            
            # 缓存未命中，继续处理
            img_array = img_array.astype(np.float32) / 255.0  # 归一化
            
            if self.enable_batch_processing:
                # 批处理模式
                future = Future()
                self.batch_queue.put({
                    'img_array': img_array,
                    'future': future
                })
                try:
                    # 将超时时间从5秒增加到60秒
                    predictions, result = future.result(timeout=60)
                except TimeoutError:
                    # 超时时记录日志并返回屏蔽结果，但不加入缓存
                    self.logger.warning(I18n.get("image_processing_timeout", img_hash))
                    return True  # 安全起见，将超时图像视为有害
            else:
                # 单张处理模式
                session = self.get_session()
                input_name = session.get_inputs()[0].name
                output_name = session.get_outputs()[0].name
                predictions = session.run([output_name], {input_name: img_array.reshape(1, 224, 224, 3)})[0][0]
                result = predictions[1] > IMAGE_THRESHOLD or \
                        predictions[3] > IMAGE_THRESHOLD or \
                        predictions[4] > IMAGE_THRESHOLD

            self.logger.info(I18n.get("predict_result", predictions, result))
            
            # 更新缓存
            self._update_cache(img_hash, result)
            
            return result
            
        except Exception as e:
            error_msg = str(e)
            # 如果是模型文件不存在的错误，返回 True
            if "NO_SUCHFILE" in error_msg and "File doesn't exist" in error_msg:
                return "No Module File"
            self.logger.info(I18n.get("ONNX_runtime_error", error_msg))
            return False

    def _predict_gif(self, gif_img):
        """并行处理GIF图像的所有帧"""
        try:
            n_frames = gif_img.n_frames
            frames = []
            
            # 收集所有帧
            for frame_idx in range(n_frames):
                gif_img.seek(frame_idx)
                # 转换当前帧为RGB
                frames.append(gif_img.convert('RGB'))
            
            # 优化2: 并行处理所有帧
            futures = []
            for frame in frames:
                # 提交每一帧到线程池进行处理
                futures.append(self.executor.submit(self.predict_image, frame))
            
            # 等待所有帧处理完成
            for future in futures:
                # 一旦有任何一帧被检测为不适当内容，立即返回True
                result = future.result()
                if result is True:
                    # 取消所有其它尚未完成的任务
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    return True
            
            # 所有帧都通过检查
            return False
        except Exception as e:
            self.logger.info(I18n.get("GIF_PROCESS_ERROR", str(e)))
            return False

    def predict_async(self, img):
        """异步处理图像"""
        return self.executor.submit(self.predict_image, img)

    def cleanup(self):
        """清理资源"""
        self.executor.shutdown(wait=True)
        self.sessions.clear()
        # 清理缓存
        with self.cache_lock:
            self.image_cache.clear()
        # 清空批处理队列
        while not self.batch_queue.empty():
            try:
                self.batch_queue.get_nowait()
            except:
                pass
