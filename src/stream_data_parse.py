import av
# import time
# import subprocess
# from constants import FFMPEG_PATH  # 从 constants.py 中导入常量
# import matplotlib.pyplot as plt
# import numpy as np
# import os
# from constants import TEST_DIR
# from keyframe_extract import extract_keyframes
import io

"""
def extract_keyframes_from_mp4(mp4_data):
    container = av.open(io.BytesIO(mp4_data))
    keyframes = []

    for packet in container.demux(video=0):
        if packet.is_keyframe:
            for frame in packet.decode():
                # 将关键帧转换为图像格式 (PIL Image)
                keyframe_image = frame.to_image()
                keyframes.append(keyframe_image)
                # print(f"Extracted keyframe at pts: {frame.pts}")
    container.close()
    return keyframes

def parse_stream_with_pyav(stream_data):
    keyframes = []
    container = av.open(io.BytesIO(stream_data))

    for frame in container.decode(video=0):
        if frame.key_frame:
            keyframes.append(frame.to_image())

    container.close()
    return keyframes
"""

def parse_stream_with_pyav(stream_data, max_frames=300):
    keyframes = []
    try:
        container = av.open(io.BytesIO(stream_data))
        stream = container.streams.video[0]  # 获取视频流
        stream.codec_context.skip_frame = "NONKEY"  # 跳过非关键帧
        # 获取视频时基
        time_base = float(stream.time_base)
        # 视频时长（秒）
        video_duration = float(stream.duration) * stream.time_base
        # 动态调整间隔
        if video_duration <= 300:  # 小于 5 分钟
            interval_seconds = 0
        elif video_duration <= 3600:  # 小于 1 小时
            interval_seconds = 30
        else:  # 超过 1 小时
            interval_seconds = 60
        # 提取关键帧
        if interval_seconds == 0:
            for frame in container.decode(video=0):
                if frame.key_frame:
                    keyframes.append(frame.to_image())
        else:
            last_saved_time = 0
            keyframe_count = 0
            for frame in container.decode(video=0):
                # 计算当前帧的时间(秒)
                current_time = frame.pts * time_base
                # 检查是否达到间隔时间
                if current_time >= last_saved_time + interval_seconds:
                    keyframes.append(frame.to_image())
                    keyframe_count += 1
                    last_saved_time = current_time
        print(f"视频时基: {time_base}, 视频时长: {video_duration:.2f}秒, 间隔帧时长：{interval_seconds}, 帧数量：{len(keyframes)}")
    except Exception as e:
        print(f"Error extracting keyframes: {e}")
    finally:
        if container:
            container.close()
        return keyframes

"""
def keyframes_show(keyframes):
    frames_num = len(keyframes)
    row_num = frames_num // 3 + 1
    # 创建一个包含 num_images 列的 1 行图像网格
    # fig, axes = plt.subplots(row_num, frames_num, figsize=(15, 5))  # figsize 可以调整图片整体大小

    # 显示每张图片
    for i, frame in enumerate(keyframes):
        plt.subplot(row_num, 3, i + 1)
        plt.imshow(np.array(frame))
        plt.axis('off')  # 不显示坐标轴

    # plt.tight_layout()
    plt.show()

    # for frame in keyframes:
    #     # 将关键帧转换为RGB格式以便显示
    #     frame_rgb = frame.to_image()
    #     # 将其转换为numpy数组以便matplotlib显示
    #     frame_array = np.array(frame_rgb)

    #     # 使用 matplotlib 显示关键帧
    #     plt.imshow(frame_array)
    #     plt.title(f'Keyframe at pts: {frame.pts}')
    #     plt.axis('off')
    #     plt.show()

if __name__ == '__main__':
    file_path = os.path.join(TEST_DIR, 'black_myth.mp4')
    print('==========extract_keyframes_from_mp4==========')
    start_time = time.time()
    keyframes = extract_keyframes_from_mp4(file_path)
    end_time = time.time()
    print(f"Time taken to extract keyframes: {end_time - start_time} seconds, keyframes num: {len(keyframes)}")
    keyframes_show(keyframes)

    # print('==========extract_keyframes==========')
    # start_time = time.time()
    # local_max_frames = extract_keyframes(file_path)
    # end_time = time.time()
    # print(f"Time taken to extract keyframes: {end_time - start_time} seconds, keyframes num: {len(local_max_frames)}")
    # keyframes_show(local_max_frames)

# 使用 mitmproxy 获取的 m4s 数据作为输入
# keyframes = extract_keyframes_from_m4s(m4s_data)

# 示例调用
# if __name__ == '__main__':
#     input_file = 'input.m4s'
#     output_file = 'output.mp4'
#     convert_m4s_to_mp4(input_file, output_file)

"""