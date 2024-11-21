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

'''
def convert_m4s_to_mp4(m4s_file, output_file):
    """
    使用打包的 FFmpeg 将 .m4s 文件转换为 .mp4 文件。
    """
    # 构建 FFmpeg 命令
    command = [
        FFMPEG_PATH,  # 使用 constants.py 中定义的路径常量
        '-i', m4s_file,  # 输入文件
        '-c', 'copy',    # 直接复制流，不进行重新编码
        output_file      # 输出文件
    ]

    # 执行命令并等待其完成
    try:
        subprocess.run(command, check=True)
        print(f"Conversion completed successfully: {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"Error during conversion: {e}")
'''

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
    stream = io.BytesIO(stream_data)
    container = av.open(stream)

    for frame in container.decode(video=0):
        if frame.key_frame:
            keyframes.append(frame.to_image())

    container.close()
    return keyframes

"""
def extract_keyframes_from_m4s(m4s_data):
    # 使用 av.open 从字节流或文件中打开视频
    container = av.open(m4s_data)
    keyframes = []

    # 遍历视频流
    for frame in container.decode(video=0):
        # 检查是否为关键帧
        if frame.is_keyframe:
            keyframes.append(frame)

    return keyframes


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