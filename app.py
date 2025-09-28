from flask import Flask, render_template, jsonify, request, send_file
import subprocess
import os
import logging
import time
import json
import shutil
from datetime import datetime
import random
import string
import socket
from pypinyin import lazy_pinyin
import sys
import concurrent.futures
import asyncio
import PyPDF2  # Added for PDF validation
import webbrowser
import threading

logger = logging.getLogger('gunicorn.error')

app = Flask(__name__)
from flask import send_from_directory

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(app.static_folder, 'favicon.ico')

@app.route('/apple-touch-icon-precomposed.png')
def apple_icon_precomposed():
    return send_from_directory(app.static_folder, 'apple-touch-icon-precomposed.png')

@app.route('/apple-touch-icon.png')
def apple_icon():
    return send_from_directory(app.static_folder, 'apple-touch-icon.png')

def convert_to_pinyin(text):
    """将中文字符转换为拼音"""
    return ''.join(lazy_pinyin(text))

SCRIPT_TIMEOUT = 300
DATA_FOLDERS = [
    'automark_raw_data',
    'automarker_colour',
    'image_cropper',
    'input_pdf',
    'level_adjusted_content',
    'level_adjuster_cache',
    'llm_processed_content',
    'logs',
    'mark/image_metadata',
    'mark/input_image',
    'merged_content',
    'ocr_extracted_text',
    'ocr_results',
    'output_pdf',
    'processed_images',
    'raw_content',
    'validated_content'
]

SCRIPT_SEQUENCE = [
    ('pdf_to_image', 'PDF转换为图像'),
    ('ocr_and_projection_hybrid', 'OCR识别与投影'),  # Changed from aliyun to hybrid
    ('mark_colour', '颜色标记处理'),
    ('abcd_marker', 'ABCD标记处理'),
    ('image_preprocessor', '图像预处理'),
    ('ocr_hybrid', 'OCR识别'),  # Changed from aliyun to hybrid
    ('ocr_processor', 'OCR后处理'),
    ('text_matcher', '文本匹配'),
    ('content_preprocessor', '内容预处理（下一步可能需要一分钟或更长，请耐心等待）'),
    ('llm_handler', 'LLM处理'),
    ('result_merger', '结果合并（下一步可能需要一分钟或更长，请耐心等待）'),
    ('llm_level_adjuster', 'LLM层级调整'),
    ('content_validator_auto', '内容自动验证'),
    ('pdf_generator', 'PDF生成')
]

QWEN_SCRIPT_SEQUENCE = [
    ('pdf_to_image', 'PDF转换为图像（下一步可能需要一分钟或更长，请耐心等待）'),
    ('qwen_vl_extract', '通义千问OCR识别'),
    ('content_preprocessor', '内容预处理（下一步可能需要一分钟或更长，请耐心等待）'),
    ('llm_handler', 'LLM处理'),
    ('result_merger', '结果合并（下一步可能需要一分钟或更长，请耐心等待）'),
    ('llm_level_adjuster', 'LLM层级调整'),
    ('content_validator_auto', '内容自动验证'),
    ('pdf_generator', 'PDF生成')
]

def generate_random_string(length=6):
    """生成指定长度的随机字母数字组合"""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def generate_session_id():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = generate_random_string()
    return f"{timestamp}_{random_suffix}"

def create_data_folders(session_id):
    base_dir = os.path.join('data', session_id)
    for folder in DATA_FOLDERS:
        folder_path = os.path.join(base_dir, folder)
        os.makedirs(folder_path, exist_ok=True)
    return base_dir

# 添加PDF验证函数，从testpdf.py导入的逻辑
def check_pdf(file_path):
    """检查PDF文件是否损坏"""
    try:
        with open(file_path, 'rb') as file:
            # 尝试读取PDF文件
            reader = PyPDF2.PdfReader(file)
            # 尝试获取页数
            num_pages = len(reader.pages)
            # 尝试访问每一页以验证内容
            for i in range(num_pages):
                reader.pages[i]
            return True, f"正常: {num_pages}页"
    except Exception as e:
        return False, str(e)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    try:
        session_id = generate_session_id()
        base_dir = create_data_folders(session_id)
        
        if 'pdf' not in request.files:
            return jsonify({'status': 'error', 'message': '未找到PDF文件'})
            
        pdf_file = request.files['pdf']
        if pdf_file.filename == '':
            return jsonify({'status': 'error', 'message': '未选择PDF文件'})
            
        toc_start = request.form.get('tocStart')
        toc_end = request.form.get('tocEnd')
        content_start = request.form.get('contentStart')
        toc_structure = request.form.get('tocStructure', 'original')  # 默认为原始目录
        
        if not all([toc_start, toc_end, content_start]):
            return jsonify({'status': 'error', 'message': '页码信息不完整'})
            
        # 保存原始文件名（中文）
        original_filename = pdf_file.filename
        filename_without_ext, file_extension = os.path.splitext(original_filename)
        
        # 转换文件名为拼音并限制长度为25个字符
        pinyin_filename = convert_to_pinyin(filename_without_ext)
        if len(pinyin_filename) > 25:
            pinyin_filename = pinyin_filename[:25]
        pinyin_filename = pinyin_filename + file_extension
        
        upload_folder = os.path.join(base_dir, 'input_pdf')
        pdf_path = os.path.join(upload_folder, pinyin_filename)
        pdf_file.save(pdf_path)
        
        # 检查上传的PDF是否有效
        is_valid_pdf, error_message = check_pdf(pdf_path)
        if not is_valid_pdf:
            return jsonify({'status': 'error', 'message': f'上传的PDF文件已损坏: {error_message}'})
        
        json_data = {
            "toc_start": int(toc_start),
            "toc_end": int(toc_end),
            "content_start": int(content_start),
            "original_filename": original_filename,  # 添加原始文件名字段
            "toc_structure": toc_structure  # 添加目录结构选择字段
        }
        
        # JSON文件名使用拼音(限制长度)
        json_filename = pinyin_filename.replace(file_extension, '.json')
        json_path = os.path.join(upload_folder, json_filename)
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)
            
        return jsonify({
            'status': 'success', 
            'message': '文件上传成功',
            'session_id': session_id
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/download_result/<session_id>')
def download_result(session_id):
    output_folder = os.path.join('data', session_id, 'output_pdf')
    input_folder = os.path.join('data', session_id, 'input_pdf')

    # 获取输出文件（假设只有一个）
    pdf_files = [f for f in os.listdir(output_folder) if f.endswith('.pdf')]
    if not pdf_files:
        return jsonify({'status': 'error', 'message': '未找到输出PDF文件'})
    file_path = os.path.join(output_folder, pdf_files[0])

    # 使用与上传时一致的 JSON 文件名
    try:
        # 假设上传时 JSON 文件名为 input_pdf_dir/原始文件名.json
        input_files = [f for f in os.listdir(input_folder) if f.endswith('.pdf') or f.endswith('.json')]
        original_pdf = next((f for f in input_files if f.endswith('.pdf')), None)
        if not original_pdf:
            return jsonify({'status': 'error', 'message': '未找到原始PDF文件'})

        json_file_name = os.path.splitext(original_pdf)[0] + '.json'
        json_path = os.path.join(input_folder, json_file_name)

        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        original_filename = json_data.get('original_filename', None)

    except Exception as e:
        print(f"[ERROR] 读取 JSON 时出错: {e}")
        original_filename = None

    # 优先使用原始文件名生成 -toc 版本
    if original_filename:
        base_name, ext = os.path.splitext(original_filename)
        download_filename = f"{base_name}-toc{ext}"
    else:
        # 万不得已，使用处理结果.pdf
        download_filename = '处理结果.pdf'

    # 检查生成的PDF是否有效
    is_valid, message = check_pdf(file_path)
    if not is_valid:
        return jsonify({'status': 'error', 'message': message})

    # 返回下载链接
    return send_file(file_path, as_attachment=True, download_name=download_filename)


AZURE_TIMEOUT = 30  # Azure服务超时时间（秒）

def run_azure_with_timeout(python_executable, script_path, env, script_dir):
    """运行Azure OCR脚本，带有超时控制"""
    try:
        result = subprocess.run(
            [python_executable, script_path],
            env=env,
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=AZURE_TIMEOUT
        )
        
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr
        }
    except subprocess.TimeoutExpired as e:
        return {
            'success': False,
            'error': 'Azure OCR timeout',
            'stdout': e.stdout.decode() if e.stdout else '',
            'stderr': e.stderr.decode() if e.stderr else ''
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

@app.route('/run_script/<session_id>/<int:script_index>/<int:retry_count>')
def run_script(session_id, script_index, retry_count):
    ocr_model = request.args.get('ocr_model', 'aliyun')  # 获取OCR模型参数
    
    # 根据OCR模型选择确定脚本序列
    if ocr_model == 'qwen':
        script_sequence = QWEN_SCRIPT_SEQUENCE
        total_scripts = len(QWEN_SCRIPT_SEQUENCE)  # 8个脚本
    else:
        script_sequence = SCRIPT_SEQUENCE
        total_scripts = len(SCRIPT_SEQUENCE)  # 14个脚本
    
    if script_index >= len(script_sequence):
        return jsonify({
            'status': 'completed',
            'message': '所有脚本执行完成'
        })
    
    script_name, script_desc = script_sequence[script_index]
    try:
        # 获取脚本的完整路径
        script_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'mainprogress'))
        script_path = os.path.join(script_dir, f'{script_name}.py')
        
        # 设置基础目录（使用绝对路径）
        base_dir = os.path.abspath(os.path.join('data', session_id))
        
        # 构建新的环境变量
        env = {}  # 创建新的环境变量字典，而不是继承现有的
        
        # 添加系统必要的环境变量
        if os.name == 'nt':  # Windows系统
            env = os.environ.copy()
            # 添加系统路径
            env['PATH'] = os.environ.get('PATH', '')
            env['SYSTEMROOT'] = os.environ.get('SYSTEMROOT', '')
            env['TEMP'] = os.environ.get('TEMP', '')
            env['TMP'] = os.environ.get('TMP', '')
            # 添加Python相关路径
            env['PYTHONPATH'] = os.environ.get('PYTHONPATH', '')
            # 添加API相关的环境变量
            env['DASHSCOPE_API_KEY'] = os.environ.get('DASHSCOPE_API_KEY', '')
            env['DEEPSEEK_API_KEY'] = os.environ.get('DEEPSEEK_API_KEY', '')
            env['ALIBABA_CLOUD_ACCESS_KEY_ID'] = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID', '')
            env['ALIBABA_CLOUD_ACCESS_KEY_SECRET'] = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET', '')
            env['AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT'] = os.environ.get('AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT', '')
            env['AZURE_DOCUMENT_INTELLIGENCE_KEY'] = os.environ.get('AZURE_DOCUMENT_INTELLIGENCE_KEY', '')
        elif os.name == 'posix':  # macOS系统
            # 添加系统路径
            env['PATH'] = os.environ.get('PATH', '')
            env['TMPDIR'] = os.environ.get('TMPDIR', '')
            # 添加Python相关路径
            env['PYTHONPATH'] = os.environ.get('PYTHONPATH', '')
            # 添加API相关的环境变量
            env['DASHSCOPE_API_KEY'] = os.environ.get('DASHSCOPE_API_KEY', '')
            env['DEEPSEEK_API_KEY'] = os.environ.get('DEEPSEEK_API_KEY', '')
            env['ALIBABA_CLOUD_ACCESS_KEY_ID'] = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID', '')
            env['ALIBABA_CLOUD_ACCESS_KEY_SECRET'] = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET', '')
            env['AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT'] = os.environ.get('AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT', '')
            env['AZURE_DOCUMENT_INTELLIGENCE_KEY'] = os.environ.get('AZURE_DOCUMENT_INTELLIGENCE_KEY', '')
        
        # 添加应用所需的环境变量（使用绝对路径）
        env.update({
            'BASE_DIR': base_dir,
            
            # pdf2jpg.py路径配置
            'PDF2JPG_INPUT': f"{base_dir}/input_pdf",
            'PDF2JPG_OUTPUT': f"{base_dir}/mark/input_image",
            
            # image_marker路径配置
            'PICMARK_INPUT_DIR': f"{base_dir}/mark/input_image",
            'PICMARK_OUTPUT_DIR': f"{base_dir}/mark/image_metadata",
            
            # image_preprocessor路径配置
            'IMAGE_PREPROCESSOR_INPUT': f"{base_dir}/mark/input_image",
            'IMAGE_PREPROCESSOR_JSON': f"{base_dir}/mark/image_metadata",
            'IMAGE_PREPROCESSOR_OUTPUT': f"{base_dir}/processed_images",
            'IMAGE_PREPROCESSOR_CUT': f"{base_dir}/image_cropper",
            
            # ocr_azure.py路径配置
            'OCR_AZURE_INPUT_1': f"{base_dir}/processed_images",
            'OCR_AZURE_OUTPUT_1': f"{base_dir}/ocr_results",
            
            # ocr_aliyun.py路径配置
            'ALIYUN_OCR_INPUT': f"{base_dir}/processed_images",
            'ALIYUN_OCR_OUTPUT': f"{base_dir}/ocr_results",
            
            # ocr_processor.py路径配置
            'OCRPROCESS_INPUT_1': f"{base_dir}/processed_images",
            'OCRPROCESS_INPUT_2': f"{base_dir}/ocr_results",
            'OCRPROCESS_OUTPUT_1': f"{base_dir}/ocr_extracted_text",
            
            # text_matcher路径配置
            'TEXT_MATCHER_INPUT': f"{base_dir}/ocr_extracted_text",
            'TEXT_MATCHER_OUTPUT': f"{base_dir}/raw_content",
            
            # content_preprocessor.py路径配置
            'CONTENT_PREPROCESSOR_INPUT': f"{base_dir}/raw_content",
            
            # llm_handler.py路径配置
            'LLM_HANDLER_INPUT': f"{base_dir}/raw_content",
            'LLM_HANDLER_OUTPUT': f"{base_dir}/llm_processed_content",
            
            # result_merger.py路径配置
            'RESULT_MERGER_INPUT_RAW': f"{base_dir}/raw_content",
            'RESULT_MERGER_INPUT_LLM': f"{base_dir}/llm_processed_content",
            'RESULT_MERGER_OUTPUT': f"{base_dir}/merged_content",
            'RESULT_MERGER_LOGS': f"{base_dir}/logs",
            'RESULT_MERGER_JSON': f"{base_dir}/input_pdf",
            
            # llm_level_adjuster路径配置
            'LEVEL_ADJUSTER_INPUT': f"{base_dir}/merged_content",
            'LEVEL_ADJUSTER_OUTPUT': f"{base_dir}/level_adjusted_content",
            'LEVEL_ADJUSTER_CACHE': f"{base_dir}/level_adjuster_cache",
            
            # content_validator.py路径配置
            'CONTENT_VALIDATOR_INPUT': f"{base_dir}/level_adjusted_content",
            'CONTENT_VALIDATOR_INPUT_2': f"{base_dir}/llm_processed_content",
            'CONTENT_VALIDATOR_OUTPUT': f"{base_dir}/validated_content",
            'CONTENT_VALIDATOR_IMAGES': f"{base_dir}/image_cropper",
            
            # pdf_generator.py路径配置
            'PDF_GENERATOR_INPUT_1': f"{base_dir}/validated_content",
            'PDF_GENERATOR_INPUT_2': f"{base_dir}/input_pdf",
            'PDF_GENERATOR_OUTPUT_1': f"{base_dir}/output_pdf",
            
            # ocr_and_projection_azure.py路径配置
            'OCR_PROJ_AZURE_INPUT': f"{base_dir}/mark/input_image",
            'OCR_PROJ_AZURE_OUTPUT': f"{base_dir}/automark_raw_data",
            
            # ocr_processor.py路径配置
            'OCR_PROJ_ALIYUN_INPUT': f"{base_dir}/mark/input_image",
            'OCR_PROJ_ALIYUN_OUTPUT': f"{base_dir}/automark_raw_data",
            
            # mark_color.py路径配置
            'MARK_COLOR_INPUT': f"{base_dir}/automark_raw_data",
            'MARK_COLOR_INPUT_DATA': f"{base_dir}/input_pdf",
            'MARK_COLOR_INPUT_IMAGE': f"{base_dir}/mark/input_image",
            'MARK_COLOR_OUTPUT': f"{base_dir}/automarker_colour",
            
            # ABCD标记路径配置
            'ABCD_INPUT_JSON': f"{base_dir}/automarker_colour",
            'ABCD_INPUT_JPG': f"{base_dir}/mark/input_image",
            'ABCD_OUTPUT': f"{base_dir}/mark/image_metadata",
            
            # content_validator_auto.py路径配置
            'CONTENT_VALIDATOR_AUTO_INPUT': f"{base_dir}/level_adjusted_content",
            'CONTENT_VALIDATOR_AUTO_OUTPUT': f"{base_dir}/validated_content"
        })
        
        # 获取Python解释器的完整路径
        python_executable = sys.executable
        
        # 修改OCR相关脚本处理逻辑
        if script_name in ['ocr_hybrid', 'ocr_and_projection_hybrid']:
            ocr_model = request.args.get('ocr_model', 'aliyun')  # 默认使用aliyun
            
            if ocr_model == 'azure':
                script_path = os.path.join(script_dir, f'{script_name.replace("hybrid", "azure")}.py')
                azure_result = run_azure_with_timeout(python_executable, script_path, env, script_dir)
                
                if azure_result.get('success', False):
                    return jsonify({
                        'status': 'success',
                        'currentScript': script_desc,
                        'message': f'{script_desc} (Azure) 执行成功',
                        'nextIndex': script_index + 1,
                        'totalScripts': total_scripts,  # 使用正确的脚本总数
                        'retryCount': 0,
                        'session_id': session_id,
                        'stdout': azure_result.get('stdout', ''),
                        'stderr': azure_result.get('stderr', '')
                    })
                else:
                    return jsonify({
                        'status': 'error',
                        'currentScript': script_desc,
                        'message': f'{script_desc} (Azure) 执行失败',
                        'stdout': azure_result.get('stdout', ''),
                        'stderr': azure_result.get('stderr', ''),
                        'retryCount': retry_count,
                        'scriptIndex': script_index,
                        'session_id': session_id
                    })
            else:  # aliyun
                script_path = os.path.join(script_dir, f'{script_name.replace("hybrid", "aliyun")}.py')
        
        # 执行脚本（包括非OCR脚本和Aliyun OCR脚本）
        try:
            result = subprocess.run(
                [python_executable, script_path],
                env=env,
                cwd=script_dir,
                capture_output=True,
                text=True,
                timeout=SCRIPT_TIMEOUT
            )
            
            if result.returncode == 0:
                # 如果是最后一个脚本(PDF生成)，检查生成的PDF是否有效
                if script_index == len(script_sequence) - 1:
                    output_folder = os.path.join(base_dir, 'output_pdf')
                    pdf_files = [f for f in os.listdir(output_folder) if f.endswith('.pdf')]
                    
                    if pdf_files:
                        file_path = os.path.join(output_folder, pdf_files[0])
                        is_valid_pdf, pdf_check_message = check_pdf(file_path)
                        
                        if not is_valid_pdf:
                            return jsonify({
                                'status': 'error',
                                'currentScript': script_desc,
                                'message': '输出文件校验失败，请查阅[问题排查方案](https://github.com/NatsUIJM/autoContents/blob/main/docs/问题排查方案.md)以获取帮助。',
                                'stdout': result.stdout,
                                'stderr': result.stderr,
                                'retryCount': retry_count,
                                'scriptIndex': script_index,
                                'session_id': session_id
                            })
                
                return jsonify({
                    'status': 'success',
                    'currentScript': script_desc,
                    'message': f'{script_desc}执行成功',
                    'nextIndex': script_index + 1,
                    'totalScripts': total_scripts,  # 使用正确的脚本总数
                    'retryCount': 0,
                    'session_id': session_id,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                })
            else:
                return jsonify({
                    'status': 'error',
                    'currentScript': script_desc,
                    'message': f'{script_desc}执行失败',
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'retryCount': retry_count,
                    'scriptIndex': script_index,
                    'session_id': session_id
                })
        except subprocess.TimeoutExpired as e:
            return jsonify({
                'status': 'error',
                'currentScript': script_desc,
                'message': f'脚本执行超时（{SCRIPT_TIMEOUT}秒）',
                'stdout': e.stdout.decode() if e.stdout else '',
                'stderr': e.stderr.decode() if e.stderr else '',
                'retryCount': retry_count,
                'scriptIndex': script_index,
                'session_id': session_id
            })
            
    except Exception as e:
        logger.error(f"执行脚本时发生错误: {str(e)}")
        return jsonify({
            'status': 'error',
            'currentScript': script_desc,
            'message': f'执行出错: {str(e)}',
            'retryCount': retry_count,
            'scriptIndex': script_index,
            'session_id': session_id
        })

    
def find_available_port(start_port=5000, max_port=6000):
    """查找可用的端口号"""
    current_port = start_port
    while (current_port <= max_port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(('', current_port))
            sock.close()
            return current_port
        except OSError:
            current_port += 1
        finally:
            sock.close()
    return None

# Then modify the if __name__ == '__main__' section:
if __name__ == '__main__':
    port = find_available_port()
    if port is None:
        print("Error: No available ports found between 5000 and 6000")
    else:
        # Define function to open browser after a delay
        def open_browser():
            time.sleep(1.5)  # Wait a bit for server to start, even after reload
            webbrowser.open_new(f'http://127.0.0.1:{port}')
            
        # Start browser in a separate thread
        threading.Thread(target=open_browser).start()
        
        print(f"Starting server on port {port}")
        app.run(debug=True, port=port, use_reloader=False)  # Disable reloader to avoid port changes