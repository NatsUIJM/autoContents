import os
import json
from openai import OpenAI
from pathlib import Path
import base64
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import traceback
import sys

# 添加日志记录功能
def write_log(message):
    """写入日志到项目根目录的log.txt"""
    try:
        # 获取项目根目录
        project_root = Path(__file__).parent.parent
        log_file = project_root / "log.txt"
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{threading.current_thread().name}] {message}\n")
    except Exception as e:
        print(f"日志写入失败: {e}")

# 加载环境变量
load_dotenv()

# 初始化客户端
try:
    client = OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    write_log("OpenAI客户端初始化成功")
except Exception as e:
    write_log(f"OpenAI客户端初始化失败: {str(e)}")
    write_log(traceback.format_exc())
    raise

# 支持的图像格式
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}

# 线程锁用于进度输出
progress_lock = threading.Lock()

def process_image(image_path: Path, output_path: Path):
    write_log(f"开始处理图像: {image_path}")
    
    try:
        # 检查文件是否存在
        if not image_path.exists():
            write_log(f"图像文件不存在: {image_path}")
            return None
            
        # 将图像编码为base64
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            image_data_url = f"data:image/jpeg;base64,{base64_image}"
        
        write_log(f"图像编码完成: {image_path.name}")

        prompt_text = (
            "请分析这张图片，提取其中的目录信息。"
            "对于每个目录项，请提供：标题（text）和页码（number）。"
            "注意："
            "1. 只需提取目录内容，不要包含其他文本"
            "2. 页码如果是数字则保留为数字，如果没有页码则设置为null"
            "3. 严格按照以下JSON格式返回，不要包含任何额外文本或说明："
            "4. 不要遗漏任何目录项目，但是需要忽略“前言”或“第x版前言”这种与正文一点关系都没有的条目，有一些条目没有直接显示页码，并不代表它们不是目录条目，请基于具体语义而非是否有规范的格式来判断一个内容是否是目录的一部分"
            "5. XX 篇也是目录的一部分，也需要提取"
            "6. 需严格按照原始目录的语言提取，如果出现繁体中文或英文等非简体中文文字，需直接提取原始内容，而不是全部翻译为简体中文"
            "[{\"text\": \"目录项1\", \"number\": 1}, {\"text\": \"目录项2\", \"number\": null}]"
        )

        for attempt in range(5):
            try:
                write_log(f"第{attempt+1}次尝试调用模型: {image_path.name}")
                
                completion = client.chat.completions.create(
                    model="qwen3-vl-235b-a22b-instruct",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": image_data_url}},
                                {"type": "text", "text": prompt_text}
                            ]
                        }
                    ],
                    response_format={"type": "json_object"}  # 强制JSON格式响应
                )

                # 解析响应
                response_content = completion.choices[0].message.content.strip()
                
                write_log(f"模型响应内容长度: {len(response_content)} 字符")

                # 调试输出原始响应内容
                with progress_lock:
                    print(f"[DEBUG] 模型原始响应内容: {response_content}")

                # 如果响应为空，跳过解析
                if not response_content:
                    with progress_lock:
                        print(f"处理 {image_path.name} 第{attempt+1}次尝试失败，模型返回空内容")
                    write_log(f"处理 {image_path.name} 第{attempt+1}次尝试失败，模型返回空内容")
                    continue

                directory_data = json.loads(response_content)
                
                write_log(f"JSON解析成功: {image_path.name}")

                # 验证数据结构
                if isinstance(directory_data, list):
                    valid = True
                    for item in directory_data:
                        if not isinstance(item, dict) or 'text' not in item:
                            valid = False
                            break
                    if valid:
                        # 保存到JSON文件
                        output_file = output_path / (image_path.stem + '_merged.json')
                        with open(output_file, 'w', encoding='utf-8') as f:
                            json.dump(directory_data, f, ensure_ascii=False, indent=2)
                        
                        write_log(f"结果保存成功: {output_file}")
                        
                        with progress_lock:
                            print(f"已处理: {image_path.name} -> {output_file.name}")
                        return directory_data  # 成功处理后返回数据
                
                with progress_lock:
                    print(f"处理 {image_path.name} 第{attempt+1}次尝试失败，数据格式不正确，重新尝试...")
                write_log(f"处理 {image_path.name} 第{attempt+1}次尝试失败，数据格式不正确，重新尝试...")
                
            except json.JSONDecodeError as e:
                with progress_lock:
                    print(f"处理 {image_path.name} 第{attempt+1}次尝试失败，JSON解析错误: {e}")
                write_log(f"处理 {image_path.name} 第{attempt+1}次尝试失败，JSON解析错误: {str(e)}")
                write_log(traceback.format_exc())
            except Exception as e:
                with progress_lock:
                    print(f"处理 {image_path.name} 第{attempt+1}次尝试失败，错误: {e}")
                write_log(f"处理 {image_path.name} 第{attempt+1}次尝试失败，错误: {str(e)}")
                write_log(traceback.format_exc())
        
        with progress_lock:
            print(f"处理 {image_path.name} 失败，已达到最大重试次数")
        write_log(f"处理 {image_path.name} 失败，已达到最大重试次数")
        return None
        
    except Exception as e:
        write_log(f"处理图像时发生异常: {image_path}")
        write_log(f"错误信息: {str(e)}")
        write_log(traceback.format_exc())
        return None


def main():
    write_log("=== qwen_vl_extract.py 开始执行 ===")
    
    try:
        # 检查BASE_DIR环境变量是否存在
        base_dir = os.getenv("BASE_DIR")
        if base_dir:
            # 使用会话目录路径
            input_path = Path(base_dir) / "mark" / "input_image"
            output_path = Path(base_dir) / "raw_content"
            write_log(f"使用会话目录路径: {base_dir}")
        else:
            # 回退到原来的环境变量
            input_path_str = os.getenv("QWEN_VL_EXTRACT_INPUT")
            output_path_str = os.getenv("QWEN_VL_EXTRACT_OUTPUT")
            write_log(f"环境变量 QWEN_VL_EXTRACT_INPUT: {input_path_str}")
            write_log(f"环境变量 QWEN_VL_EXTRACT_OUTPUT: {output_path_str}")
            
            if not input_path_str or not output_path_str:
                write_log("错误: 未设置必要的环境变量")
                print("错误: 未设置必要的环境变量")
                return
                
            input_path = Path(input_path_str)
            output_path = Path(output_path_str)
        
        write_log(f"输入路径: {input_path}")
        write_log(f"输出路径: {output_path}")
        write_log(f"输入路径是否存在: {input_path.exists()}")
        write_log(f"输出路径是否存在: {output_path.exists()}")
        
        # 确保输出目录存在
        output_path.mkdir(parents=True, exist_ok=True)
        write_log(f"输出目录创建完成: {output_path}")
        
        # 获取所有图像文件
        if not input_path.exists():
            write_log(f"输入路径不存在: {input_path}")
            print(f"输入路径不存在: {input_path}")
            return
            
        image_files = [f for f in input_path.iterdir() 
                       if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS]
        
        write_log(f"找到 {len(image_files)} 个图像文件")
        print(f"找到 {len(image_files)} 个图像文件，开始处理...")
        
        # 使用线程池并发处理，最大并发度9
        with ThreadPoolExecutor(max_workers=9) as executor:
            # 提交所有任务
            future_to_image = {executor.submit(process_image, image_file, output_path): image_file 
                              for image_file in image_files}
            
            # 收集结果
            results = []
            for future in as_completed(future_to_image):
                image_file = future_to_image[future]
                try:
                    result = future.result()
                    if result is not None:
                        results.append((image_file.stem, result))
                except Exception as e:
                    with progress_lock:
                        print(f"处理 {image_file.name} 时发生异常: {e}")
                    write_log(f"处理 {image_file.name} 时发生异常: {str(e)}")
                    write_log(traceback.format_exc())
        
        write_log(f"处理完成，共处理 {len(results)} 个文件")
        print(f"处理完成，共处理 {len(results)} 个文件")
        
    except Exception as e:
        write_log(f"主函数执行时发生异常: {str(e)}")
        write_log(traceback.format_exc())
        print(f"主函数执行时发生异常: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
