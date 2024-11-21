# import re
import numpy as np
# import pandas as pd
# from PIL import Image
# from io import BytesIO
import onnxruntime as ort
# from bs4 import BeautifulSoup
# from transformers import AutoTokenizer
# from constants import TOKENIZER_DIR, TEXT_MODEL_FILE
from constants import IMAGE_MODEL_FILE, IMAGE_LABELS, IMAGE_THRESHOLD
# import matplotlib.pyplot as plt

"""
tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_DIR, clean_up_tokenization_spaces=True)
ort_session = ort.InferenceSession(TEXT_MODEL_FILE)

def sliding_window_predict(text, window_size=128, stride=64, threshold=0.8):
    words = list(text)  # 将文本转换为字符列表
    windows = []
    for i in range(0, len(words) - window_size + 1, stride):
        window = ''.join(words[i:i+window_size])
        windows.append(window)
    
    if len(windows) == 0:  # 处理文本长度小于窗口大小的情况
        windows = [text]
    
    inputs = tokenizer(windows, truncation=True, padding='max_length', max_length=window_size, return_tensors="np")
    
    # 使用ONNX模型进行预测
    ort_inputs = {ort_session.get_inputs()[0].name: inputs["input_ids"]}
    ort_outs = ort_session.run(None, ort_inputs)
    logits = ort_outs[0]
    
    # 使用numpy实现softmax
    exp_logits = np.exp(logits - np.max(logits, axis=-1, keepdims=True))
    probabilities = exp_logits / np.sum(exp_logits, axis=-1, keepdims=True)
    predictions = probabilities[:, 1]  # 取正类（porn）的概率
    prob = np.mean(predictions)  # 返回所有窗口的平均概率
    if prob > threshold:
        print(text, prob)
    return prob > threshold

def predict_text(text, min_length=10):
    is_removed = 0
    # 使用 BeautifulSoup 解析 HTML
    soup = BeautifulSoup(text, 'html.parser')
    
    # 找到所有的 p 和 a标签
    tags = soup.find_all(['p', 'a'])
    
    for tag in tags:
        content = tag.get_text()
        if len(content) < min_length:
            continue
        if sliding_window_predict(content):
            # 如果检测结果为 1，则移除该标签
            tag.decompose()
            is_removed = 1
    
    # 返回处理后的 HTML 文本
    return is_removed, str(soup)
"""

def predict_image(img):
    # 下载网络图片
    # response = requests.get(image_url)
    # img = Image.open(BytesIO(content))

    # 调整图像大小并预处理
    img = img.resize((224, 224))  # 调整图像尺寸为 224x224
    img_array = np.array(img)  # 转换为数组
    # 如果图像不是 RGB 格式，则将其转换为 RGB
    if img_array.shape[-1] != 3:
        img = img.convert('RGB')
        img_array = np.array(img)
    img_array = img_array.astype(np.float32) / 255.0  # 归一化
    img_array = np.expand_dims(img_array, axis=0)  # 增加批量维度

    # 加载 ONNX 模型
    session = ort.InferenceSession(IMAGE_MODEL_FILE)

    # 获取模型输入输出的名字
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    # 进行 ONNX 模型预测
    predictions = session.run([output_name], {input_name: img_array})[0]
    print("预测结果:", predictions)

    # 显示图片
    # plt.figure(figsize=(6, 6))
    # plt.imshow(img)
    # plt.axis('off')
    # plt.title('输入图片')
    # plt.show()

    # 获取分数最大值的索引
    # max_index = np.argmax(predictions, axis=1)[0]  # axis=1 表示按行取最大值
    # label = IMAGE_LABELS[max_index]  # 根据索引找到对应的标签
    # scores = predictions[0][max_index]
    # print(f"预测标签: {label}")
    # print(f"预测分数: {scores}")
    # return predictions

    if predictions[0][1] > IMAGE_THRESHOLD or predictions[0][3] > IMAGE_THRESHOLD or predictions[0][4] > IMAGE_THRESHOLD:
        return 1
    else:
        return 0

