from mitmproxy import http
from PIL import Image, ImageSequence, ImageFilter
import io
import logging
import os
import ai_detect
from io import BytesIO
import stream_data_parse as stream_parse
from logging.handlers import TimedRotatingFileHandler
from threading import Timer
import hashlib
from db_manager import DatabaseManager
from constants import LOG_PATH
# import re
# import tldextract

class InPurityProxy:
    def __init__(self):
        self.logger = self._setup_logger()
        self.site_stats = {}  # 保存统计数据
        self.site_timers = {}  # 保存每个网页的计时器
        self.DELAY_TIME = 10  # 延迟时间（秒）
        self.db_manager = DatabaseManager()

    def _setup_logger(self):
        if not os.path.exists(LOG_PATH):
            os.makedirs(LOG_PATH)
        logger = logging.getLogger('InPurityProxy')
        logger.setLevel(logging.INFO)
        handler = TimedRotatingFileHandler(
            os.path.join(LOG_PATH, 'in_purity_proxy.log'),
            when='midnight',
            interval=1,
            backupCount=90,
            encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def blur_image(self, image, radius=50):
        """对图像应用高斯模糊"""
        return image.filter(ImageFilter.GaussianBlur(radius=radius))

    def process_gif(self, image):
        """处理 GIF 图像"""
        frames = [self.blur_image(frame.convert("RGBA")) for frame in ImageSequence.Iterator(image)]
        img_byte_arr = io.BytesIO()
        frames[0].save(img_byte_arr, format="GIF", save_all=True, append_images=frames[1:], loop=0)
        return img_byte_arr.getvalue()

    def process_static_image(self, image):
        """处理静态图像"""
        blurred_image = self.blur_image(image)
        img_byte_arr = io.BytesIO()
        original_format = image.format or "PNG"
        blurred_image.save(img_byte_arr, format=original_format)
        return img_byte_arr.getvalue()
    
    def md5_hash(self, text):
        """
        计算字符串的 MD5 哈希值
        """
        return hashlib.md5(text.encode()).hexdigest()
    
    def is_blacklisted(self, host):
        """
        检查 Host 的 MD5 是否在黑名单数据库中
        """
        host_md5 = self.md5_hash(host)
        result = self.db_manager.fetchone("SELECT 1 FROM black_site WHERE host = ?", (host_md5,)) is not None
        return result
    
    def request(self, flow: http.HTTPFlow) -> None:
        """
        在请求阶段检查 host 是否在黑名单中
        """
        authority = flow.request.headers.get(":authority", None)
        host = authority if authority else flow.request.host
        if self.is_blacklisted(host):
            flow.kill()
            # 如果 host 在黑名单中，返回 403
            # flow.response = http.Response.make(
            #     403,  # 返回403状态码
            #     b"Forbidden: Blacklisted site",  # 响应体
            #     {"Content-Type": "text/plain"}  # 响应头
            # )
            self.logger.info(f"拦截黑名单网站请求: {host}")

    def response(self, flow: http.HTTPFlow) -> None:
        if flow.response.status_code == 200:
            content_type = flow.response.headers.get("Content-Type", "")
            # if "text/html" in content_type:
            #     # 使用正则表达式提取charset
            #     match = re.search(r'charset=([^\s;]+)', content_type, re.IGNORECASE)
            #     if match:
            #         charset = match.group(1)
            #     else:
            #         charset = "utf-8"
            #     is_removed, predict_text = ai_detect.predict_text(flow.response.content)
            #     flow.response.content = predict_text.encode(charset)
            #     if is_removed:
            #         self.logger.info(f'文本修改url{flow.request.url}')
            if "image" in content_type:
                # 获取 authority，如果没有则使用 Host
                authority = flow.request.headers.get(":authority", None)
                host = authority if authority else flow.request.host
                
                # 初始化该网站的统计信息（如果之前未记录）
                if host not in self.site_stats:
                    self.site_stats[host] = {"total_images": 0, "problematic_images": 0}
                
                # 统计该网站的图片总数
                self.site_stats[host]["total_images"] += 1
                predict_result = ai_detect.predict_image(img = Image.open(BytesIO(flow.response.content)))
                if predict_result:
                    flow.response.status_code = 403
                    flow.response.content = b"Forbidden"
                    self.logger.info(f'图片拦截url：{flow.request.url}')
                    self.site_stats[host]["problematic_images"] += 1  # 统计有问题的图片
                # 打印当前图片的检测结果
                # total_images = site_stats[host]["total_images"]
                # problematic_images = site_stats[host]["problematic_images"]
                # print(f"Site: {host} | Total images: {total_images}, Problematic images: {problematic_images}")
                
                # 重置计时器，每次处理完图片请求后启动计时器
                self.reset_timer(host)
            elif "video" in content_type:
                if "mp4" in content_type:
                    keyframes = stream_parse.extract_keyframes_from_mp4(flow.response.content)
                    for keyframe in keyframes:
                        predict_result = ai_detect.predict_image(img = keyframe)
                        if predict_result:
                            flow.response.status_code = 403
                            flow.response.content = b"Forbidden"
                            self.logger.info(f'mp4拦截url：{flow.request.url}')
                            break
                else:
                    keyframes = stream_parse.parse_stream_with_pyav(flow.response.content)
                    for keyframe in keyframes:
                        predict_result = ai_detect.predict_image(img = keyframe)
                        if predict_result:
                            flow.response.status_code = 403
                            flow.response.content = b"Forbidden"
                            self.logger.info(f'视频拦截url：{flow.request.url}')
                            break
            # elif "audio" in content_type:
            #     return
            # elif "application/octet-stream" in content_type:
            #     # 调用ffmpeg处理文件流
            #     return
            # else:
            #     return
        
    def print_final_stats(self, host):
        """
        打印每个网站的最终统计数据
        """
        total_images = self.site_stats[host]["total_images"]
        problematic_images = self.site_stats[host]["problematic_images"]
        
        if total_images > 0:
            ratio = problematic_images / total_images
            self.logger.info(f"\n=== Final Stats for {host} ===")
            self.logger.info(f"Total images: {total_images}")
            self.logger.info(f"Problematic images: {problematic_images}")
            self.logger.info(f"Ratio of problematic images: {ratio:.2%}\n")
            # 如果问题图片的比例大于 60%，将 host 存入数据库
            if ratio > 0.6:
                host_md5 = self.md5_hash(host)
                self.db_manager.execute_query("INSERT OR IGNORE INTO black_site (host) VALUES (?)", (host_md5,))
                self.logger.info(f"域名 {host} 已加入黑名单.\n")
        # else:
            # self.logger.info(f"\n=== No images detected for {host} ===\n")

    def reset_timer(self, host):
        """
        重置并启动计时器
        """
        # 如果之前的计时器还在运行，取消它
        if host in self.site_timers and self.site_timers[host]:
            self.site_timers[host].cancel()
        
        # 启动新的计时器，当 DELAY_TIME 秒内没有新图片请求时，触发统计输出
        self.site_timers[host] = Timer(self.DELAY_TIME, self.print_final_stats, [host])
        self.site_timers[host].start()

addons = [
    InPurityProxy()
]