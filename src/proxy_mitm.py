import re
import time
import base64
import hashlib
import threading
import numpy as np
from i18n import I18n
from io import BytesIO
import imageio.v3 as iio
from datetime import date
from mitmproxy import http
from log import LogManager
from threading import Timer
from bs4 import BeautifulSoup
from ai_detect import ImagePredictor
from db_manager import DatabaseManager
from forbid_manager import ForbidEventManager
from PIL import Image, UnidentifiedImageError
from urllib.parse import urlparse, parse_qs
from constants import (STREAMING_TYPES, SKIP_CONTENT_TYPES, IMAGE_EXTENSIONS, 
                      TEXT_CONTENT_TYPES, PORN_WORDS_CN, PORN_WORDS_EN)

class InPurityProxy:
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.log_manager = LogManager()
        self.logger = self.log_manager.get_logger('InPurity', 'in_purity')
        self.site_stats = {}  # 保存统计数据
        self.site_timers = {}  # 保存每个网页的计时器
        self.DELAY_TIME = 10  # 延迟时间（秒）
        self.MAX_DELAY_TIME = 60  # 最大延迟时间（秒）
        self.predictor = ImagePredictor(self.logger)
        self.dangerous_count = 0 # 危险访问次数
        self.req_forbid = False # 禁止所有请求标识
        self.img_forbid = False # 禁止所有图片标识
        self.forbid_timer = None # 禁止任务定时器
        self.forbid_date = date.today() # 禁止日期
        
        # 黑名单缓存相关
        self.blacklist_cache = set()  # 使用集合存储黑名单，提高查询效率
        self.blacklist_lock = threading.Lock()  # 用于保护黑名单缓存的线程锁
        self.CACHE_REFRESH_INTERVAL = 300  # 缓存刷新间隔（秒）
        self.cache_refresh_paused = False  # 缓存刷新暂停标志

        # 预解码敏感词并转换为Set
        self.sensitive_words_cn = set()
        self.sensitive_words_en = set()
        # self.blocked_words = set()
        self._preload_sensitive_words()
        
        # 站点统计相关的线程锁
        self.stats_lock = threading.Lock()  # 用于保护站点统计数据的线程锁
        
        # 初始化禁止事件管理器
        self.forbid_manager = ForbidEventManager()
        
        self._init_blacklist_cache()  # 初始化黑名单缓存
        self._check_active_forbid_events()  # 检查活跃的禁止事件
        self._start_cache_refresh_timer()  # 启动定时刷新
    
    def _check_active_forbid_events(self):
        """检查是否有活跃的禁止事件"""
        try:
            self.forbid_manager.clear_expired_events()
            active_event = self.forbid_manager.get_active_forbid_event()
            if active_event:
                # 设置禁止标志
                mode = active_event['mode']
                if mode == "images":
                    self.img_forbid = True
                elif mode == "requests":
                    self.req_forbid = True
                
                # 恢复黑名单缓存快照
                with self.blacklist_lock:
                    self.blacklist_cache = active_event['cache_set']
                
                # 恢复危险计数
                self.dangerous_count = active_event.get('count', 0)
                
                # 暂停黑名单缓存刷新
                self.pause_cache_refresh()
                
                # 设置定时器在禁止事件结束后恢复
                remaining_time = active_event['end_time'] - time.time()
                if remaining_time > 0:
                    self.logger.info(I18n.get("ACTIVE_FORBID_FOUND", mode, int(remaining_time / 60)))
                    self.forbid_timer = Timer(remaining_time, self.reset_forbid, (mode,))
                    self.forbid_timer.daemon = True
                    self.forbid_timer.start()
        except Exception as e:
            self.logger.error(I18n.get("FORBID_EVENT_CHECK_ERROR", str(e)))
    
    def _init_blacklist_cache(self):
        """初始化黑名单缓存"""
        try:
            with self.blacklist_lock:
                # 使用参数化查询和索引提高查询效率
                result = self.db_manager.fetchall("SELECT host FROM black_site")
                if result:
                    self.blacklist_cache = set([item[0] for item in result])
                self.logger.info(I18n.get("BLACKLIST_CACHE_INIT", len(self.blacklist_cache)))
        except Exception as e:
            self.logger.error(I18n.get("BLACKLIST_CACHE_ERROR", str(e)))
    
    def _refresh_blacklist_cache(self):
        """刷新黑名单缓存"""
        try:
            # 如果刷新被暂停，则跳过
            if self.cache_refresh_paused:
                return
                
            with self.blacklist_lock:
                # 使用参数化查询和索引提高查询效率
                result = self.db_manager.fetchall("SELECT host FROM black_site")
                if result:
                    self.blacklist_cache = set([item[0] for item in result])
                else:
                    self.blacklist_cache.clear()
                self.logger.info(I18n.get("BLACKLIST_CACHE_REFRESH", len(self.blacklist_cache)))
        except Exception as e:
            self.logger.error(I18n.get("BLACKLIST_CACHE_ERROR", str(e)))
    
    def _start_cache_refresh_timer(self):
        """启动定时刷新任务"""
        def refresh_task():
            while True:
                time.sleep(self.CACHE_REFRESH_INTERVAL)
                self._refresh_blacklist_cache()
        
        refresh_thread = threading.Thread(target=refresh_task, daemon=True)
        refresh_thread.start()
    
    def pause_cache_refresh(self):
        """暂停黑名单缓存刷新"""
        self.cache_refresh_paused = True
        self.logger.info(I18n.get("BLACKLIST_CACHE_REFRESH_PAUSED"))
    
    def resume_cache_refresh(self):
        """恢复黑名单缓存刷新"""
        self.cache_refresh_paused = False
        self._refresh_blacklist_cache()  # 立即执行一次刷新
        self.logger.info(I18n.get("BLACKLIST_CACHE_REFRESH_RESUMED"))
    
    def _preload_sensitive_words(self):
        """预加载和解码敏感词到内存中"""
        # 加载中文敏感词
        for encoded_word in PORN_WORDS_CN:
            try:
                word = base64.b64decode(encoded_word).decode('utf-8')
                self.sensitive_words_cn.add(word)
            except Exception as e:
                self.logger.exception(I18n.get("ERROR", e))
        
        # 加载英文敏感词
        for encoded_word in PORN_WORDS_EN:
            try:
                word = base64.b64decode(encoded_word).decode('utf-8').lower()
                self.sensitive_words_en.add(word)
            except Exception as e:
                self.logger.exception(I18n.get("ERROR", e))

    def md5_hash(self, text):
        """
        计算字符串的 MD5 哈希值
        """
        return hashlib.md5(text.encode()).hexdigest()
    
    def is_blacklisted(self, host):
        """
        检查 Host 的 MD5 是否在黑名单缓存中
        """
        host_md5 = self.md5_hash(host)
        with self.blacklist_lock:
            return host_md5 in self.blacklist_cache

    def _is_image_request(self, flow: http.HTTPFlow, content_type: str) -> bool:
        """判断是否为图片请求"""
        # 检查 URL 扩展名
        url = flow.request.url.lower()
        if any(url.endswith(ext) for ext in IMAGE_EXTENSIONS):
            return True
            
        # 检查 sec-fetch-dest
        if flow.request.headers.get("sec-fetch-dest", "") == "image":
            return True
            
        # 检查 content-type
        if content_type and 'image' in content_type.lower():
            return True
            
        return False

    def request(self, flow: http.HTTPFlow) -> None:
        """在请求阶段检查 host 是否在黑名单中"""
        if self.req_forbid:
            flow.kill()
            return
        # 检查 URL 是否在黑名单中
        parsed_url = urlparse(flow.request.url)
        main_domain = f"{parsed_url.scheme}://{parsed_url.netloc}/"
        if self.is_blacklisted(main_domain):
            flow.kill()
            self.logger.info(I18n.get("BLACKLIST_URL_INTERCEPTED", flow.request.url))
            return
        raw_referer = flow.request.headers.get("Referer", None)
        if raw_referer is not None:
            raw_referer = urlparse(raw_referer)
            referer = f"{raw_referer.scheme}://{raw_referer.netloc}/"
            if self.is_blacklisted(referer):
                flow.kill()
                return

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        content_type = flow.response.headers.get("Content-Type", "").lower()
        # 检查搜索内容
        if any(content_type.startswith(type) for type in TEXT_CONTENT_TYPES):
            html_content = flow.response.text 
            if html_content: # 确保内容不为空
                soup = BeautifulSoup(html_content, 'html.parser')
                title_tag = soup.find('title')
                if title_tag:
                    title_text = title_tag.get_text(strip=True)
            # search_term = self._extract_and_decode_search_params(flow.request.url)
            # before = len(self.blocked_words)
            if title_text and self._contains_sensitive_keywords(title_text):
                self.logger.info(I18n.get("SENSITIVE_SEARCH_BLOCKED"))
                flow.kill()
                # after = len(self.blocked_words)
                # if after > before:
                #     self.dangerous_count += 1
                #     self.set_forbid()
                return
        # 图像流媒体拦截
        if self.img_forbid and (self._is_image_request(flow, content_type) or 
                               ("video" in content_type or "octet-stream" in content_type) or 
                               ("bilibili" in flow.request.url and "player" in flow.request.url)):
            flow.kill()
            return
        # 根据内容类型判断是否需要流式处理
        if any(content_type.startswith(t) for t in STREAMING_TYPES):
            flow.response.stream = True
            self.logger.info(I18n.get("STREAM_DATA_DETECTED", content_type))

    def _extract_and_decode_search_params(self, url: str) -> str:
        """提取URL中的查询参数并正确解码，包括多次编码的情况"""
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        # 常见搜索参数名称
        search_params = ['q', 'query', 'wd', 'word', 'keyword', 'kw', 'text', 'search', 'p']
        # 提取可能的搜索参数
        for param in search_params:
            if param in query_params:
                value = query_params[param][0]
                return value
        # 如果没有找到常见搜索参数，则检查所有参数值
        # for param, values in query_params.items():
        #     for value in values:
        #         decoded_value = self._deep_url_decode(value)
        #         # 如果解码后的值包含中文，可能是搜索词
        #         if self._contains_chinese(decoded_value):
        #             return decoded_value
        return ""
    
    def _contains_sensitive_keywords(self, search_term: str) -> bool:
        """检查搜索词是否包含敏感关键词"""
        if not search_term:
            return False
        
        # chinese_word_pattern = re.compile(r'[\u4e00-\u9fff]+')
        english_word_pattern = re.compile(r'[a-zA-Z]+')
        # chinese_term = chinese_word_pattern.findall(search_term)
        english_term = english_word_pattern.findall(search_term)

        # if chinese_term:
        #     for term in chinese_term:
        for word in self.sensitive_words_cn:
            if re.search(word, search_term):
                # self.blocked_words.add(search_term)
                return True
        if english_term:
            for term in english_term:
                if term.lower() in self.sensitive_words_en:
                    # self.blocked_words.add(term)
                    return True
        return False

    def response(self, flow: http.HTTPFlow) -> None:
        if flow.response.status_code == 200:
            content_type = flow.response.headers.get("Content-Type", "").lower()
            
            # 快速过滤掉不需要处理的内容类型
            if any(t in content_type for t in SKIP_CONTENT_TYPES):
                return
                
            # 检查是否为图片请求
            if self._is_image_request(flow, content_type):
                # 跳过 SVG 和图标
                if "svg" in content_type or "icon" in content_type:
                    self.logger.info(I18n.get("SVG_IMAGE_SKIPPED", flow.request.url))
                    return
                    
                self._handle_image_response(flow)

    def _handle_image_response(self, flow: http.HTTPFlow) -> None:
        """处理图片响应"""
        referer = flow.request.headers.get("Referer", None)

        if not referer:
            return
        
        parsed_url = urlparse(referer)
        referer_root = f"{parsed_url.scheme}://{parsed_url.netloc}/"
        referer = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
            
        try:
            # 处理图片数据
            if flow.request.url.startswith("data:image"):
                base64_data = flow.request.url.split(",")[1]
                image_data = base64.b64decode(base64_data)
            else:
                image_data = flow.response.content

            # 创建图片对象
            if "avif" in flow.response.headers.get("Content-Type", "").lower() or flow.request.url.lower().endswith('.avif'):
                avifimg = iio.imread(image_data)
                if avifimg.ndim == 4:
                    avifimg = np.squeeze(avifimg)
                img = Image.fromarray(avifimg)
            else:
                img = Image.open(BytesIO(image_data))

            # 异步处理图像
            future = self.predictor.predict_async(img)
            try:
                predict_result = future.result(timeout=60)
                
                with self.stats_lock:
                    # 检查 referer 是否仍然存在（可能已被清理）
                    if referer not in self.site_stats:
                        self.site_stats[referer] = {
                            "root": referer_root, 
                            "total_images": 0, 
                            "problematic_images": 0,
                            "features": set()  # 只保留问题图像特征
                        }
                    
                    # 更新总图片数
                    self.site_stats[referer]["total_images"] += 1
                    
                    # 如果检测到问题图片，更新统计
                    if predict_result and predict_result != "No Module File":
                        # 生成图像特征签名
                        url_parts = urlparse(flow.request.url).path.split('/')
                        filename = url_parts[-1] if url_parts else ""
                        width, height = img.size
                        image_feature = f"{width}x{height}_{filename}"
                        
                        # 检查是否已经记录过这个问题图像
                        if image_feature not in self.site_stats[referer]["features"]:
                            self.site_stats[referer]["problematic_images"] += 1
                            self.site_stats[referer]["features"].add(image_feature)
                        else:
                            # 如果是已知的问题图像，减少总计数以抵消重复
                            self.site_stats[referer]["total_images"] -= 1
                        
                        flow.response.status_code = 403
                        flow.response.content = b"Forbidden"
                        self.logger.info(I18n.get("IMAGE_URL_INTERCEPTED", flow.request.url, referer))
                    
                    # 重置计时器 - 不同类型的页面设置不同的延迟
                    if referer in self.site_timers:
                        # 检查是否超过最大延迟时间
                        elapsed_time = time.time() - self.site_timers[referer]["start_time"]
                        if elapsed_time < self.MAX_DELAY_TIME:
                            # 未超过最大延迟时间，重置计时器
                            self.site_timers[referer]["timer"].cancel()
                            self.site_timers[referer]["timer"] = Timer(self.DELAY_TIME, self.print_final_stats, (referer,))
                            self.site_timers[referer]["timer"].start()
                    else:
                        # 设置延迟时间
                        self.site_timers[referer] = {"start_time": time.time(), "timer": None}
                        self.site_timers[referer]["timer"] = Timer(self.DELAY_TIME, self.print_final_stats, (referer,))
                        self.site_timers[referer]["timer"].start()
                    
            except TimeoutError:
                self.logger.error(I18n.get("IMAGE_PROCESS_TIMEOUT", flow.request.url))
        except UnidentifiedImageError:
            self.logger.error(I18n.get("UNRECOGNIZED_IMAGE", flow.request.url))
        except Exception as e:
            self.logger.exception(I18n.get("IMAGE_PROCESS_ERROR", e))

    def print_final_stats(self, referer):
        """
        打印每个网站的最终统计数据
        """
        with self.stats_lock:
            if referer not in self.site_stats:
                return
                
            total_images = self.site_stats[referer]["total_images"]
            problematic_images = self.site_stats[referer]["problematic_images"]
            root = self.site_stats[referer]["root"]
            
            if total_images > 3:
                ratio = problematic_images / total_images
                self.logger.info(I18n.get("FINAL_STATS", referer))
                self.logger.info(I18n.get("TOTAL_IMG", total_images))
                self.logger.info(I18n.get("PROBLEM_IMG", problematic_images))
                self.logger.info(I18n.get("PROBLEM_RATIO", ratio))
                # 如果问题图片的比例大于 60%，将 root 存入黑名单
                if ratio > 0.6:
                    self.add_to_blacklist(root)
                    if ratio >= 0.65:
                        self.dangerous_count += 1
                        self.set_forbid()
                        
            # 清理数据
            self.site_stats.pop(referer, None)
            timer = self.site_timers.pop(referer, None)["timer"]
            if timer:
                timer.cancel()

    def set_forbid(self):
        """设置禁止标识"""
        # 取消已有的定时器
        if self.forbid_timer is not None and self.forbid_timer.is_alive():
            self.forbid_timer.cancel()
        
        # 根据危险次数确定禁止模式和时长
        if self.dangerous_count > 0 and self.dangerous_count <= 3:
            mode = "images"
            self.img_forbid = True
            interval = self.dangerous_count * 10 * 60  # 10-30分钟
        elif self.dangerous_count > 3:
            mode = "requests"
            self.img_forbid = False
            self.req_forbid = True
            interval = self.dangerous_count * 30 * 60  # 2小时以上
        
        # 创建定时器，在指定时间后恢复
        self.forbid_timer = Timer(interval, self.reset_forbid, (mode,))
        self.forbid_timer.daemon = True
        self.forbid_timer.start()
        
        # 记录当前时间作为开始时间
        start_time = time.time()
        
        # 暂停黑名单缓存刷新
        self.pause_cache_refresh()
        
        # 保存禁止事件信息到文件
        with self.blacklist_lock:
            # 创建黑名单缓存的快照
            cache_snapshot = self.blacklist_cache.copy()
            # 保存事件信息，包含危险计数
            self.forbid_manager.save_forbid_event(mode, start_time, interval, cache_snapshot, self.dangerous_count)
        
        self.logger.info(I18n.get("START_FORBID", self.dangerous_count, mode, interval // 60))
    
    def reset_forbid(self, mode):
        """重置禁止标识"""
        if mode == "images":
            self.img_forbid = False
        elif mode == "requests":
            self.req_forbid = False
        
        # 恢复黑名单缓存刷新
        self.resume_cache_refresh()
        
        # 清理过期的禁止事件
        self.forbid_manager.clear_expired_events()

        # 清理拦截搜索词
        self.blocked_words.clear()
        
        self.logger.info(I18n.get("RESET_FORBID", mode))

    def add_to_blacklist(self, host):
        """将域名添加到黑名单数据库和缓存"""
        host_md5 = self.md5_hash(host)
        try:
            # 使用参数化查询和安全执行方法添加黑名单
            self.db_manager.safe_execute("INSERT OR IGNORE INTO black_site (host) VALUES (?)", (host_md5,))
            with self.blacklist_lock:
                self.blacklist_cache.add(host_md5)
            self.logger.info(I18n.get("DOMAIN_BLACKLISTED", host))
        except Exception as e:
            self.logger.error(I18n.get("BLACKLIST_ADD_ERROR", str(e)))

    def done(self):
        """当代理关闭时调用"""
        self.predictor.cleanup()
        self.logger.info(I18n.get("PROXY_SERVICE_STOPPED"))
        self.log_manager.cleanup(script_name='mitmproxy')
        self.log_manager.cleanup(script_name='in_purity')

addons = [
    InPurityProxy()
]
