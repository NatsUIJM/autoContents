from flask import Flask, render_template, jsonify, request, send_file
import subprocess
import os
import logging
import time
import json
from datetime import datetime
import random
import string
import socket
from pypinyin import lazy_pinyin
import sys
import webbrowser
import threading
import fitz  # 新增：PyMuPDF，用于提取第一页图片
import base64 # 新增：用于图片编码
import re     # 新增：用于清理文件名中的非法字符

# 添加openai库导入
from openai import OpenAI
import traceback

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
    'input_pdf',
    'mark/input_image',
    'raw_content',
    'output_pdf',
    'mark/image_metadata',
    'merged_content',
]

QWEN_SCRIPT_SEQUENCE = [
    ('pdf_to_image', 'PDF转换为图像（下一步可能需要一分钟或更长，请耐心等待）'),
    ('qwen_vl_extract', 'OCR识别'),
    ('content_preprocessor', '内容预处理'),
    ('llm_level_adjuster', '层级调整'),
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

def extract_env_var_name(api_key_value):
    """
    从API KEY值中提取环境变量名称
    例如: $CHERRY_IN_API_KEY$ -> CHERRY_IN_API_KEY
    """
    if api_key_value.startswith('$') and api_key_value.endswith('$'):
        return api_key_value[1:-1]  # 移除开头和结尾的$
    return None

def extract_first_page_and_recognize(pdf_path, original_filename, session_dir, config):
    """提取PDF第一页并调用LLM识别书名"""
    try:
        # 提取第一页
        doc = fitz.open(pdf_path)
        page = doc[0]
        
        # 计算缩放比例，使长边为1000px
        rect = page.rect
        max_dim = max(rect.width, rect.height)
        zoom = 1000.0 / max_dim if max_dim > 1000 else 1.0
        mat = fitz.Matrix(zoom, zoom)
        
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("jpeg")
        doc.close()
        
        base64_image = base64.b64encode(img_data).decode('utf-8')
        image_data_url = f"data:image/jpeg;base64,{base64_image}"
        
        # 解析 config
        api_key_value = config.get("api_key", "")
        env_var_name = extract_env_var_name(api_key_value)
        if env_var_name:
            actual_api_key = os.environ.get(env_var_name, "")
        else:
            actual_api_key = api_key_value
            
        client = OpenAI(
            api_key=actual_api_key,
            base_url=config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        
        prompt = f"这是PDF文件的第一页。该文件的原始文件名为：{original_filename}。请结合图片内容和原始文件名，识别并输出这本书的书名。只需输出书名文本，不要包含任何其他说明、标点或多余内容。"
        
        completion = client.chat.completions.create(
            model=config.get("model", "qwen-vl-max"), # 注意：需要确保使用的模型支持视觉能力
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                        {"type": "text", "text": prompt}
                    ]
                }
            ],
            extra_body={"enable_thinking": False}
        )
        
        book_name = completion.choices[0].message.content.strip()
        # 清理可能的不合法字符
        book_name = re.sub(r'[\\/:*?"<>|]', '_', book_name)
        
        # 保存书名到文件
        info_path = os.path.join(session_dir, 'book_name.txt')
        with open(info_path, 'w', encoding='utf-8') as f:
            f.write(book_name)
            
    except Exception as e:
        logger.error(f"识别书名失败: {str(e)}")

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
        toc_structure = request.form.get('tocStructure', 'original')
        
        if not all([toc_start, toc_end, content_start]):
            return jsonify({'status': 'error', 'message': '页码信息不完整'})
            
        original_filename = pdf_file.filename
        filename_without_ext, file_extension = os.path.splitext(original_filename)
        
        pinyin_filename = convert_to_pinyin(filename_without_ext)
        if len(pinyin_filename) > 25:
            pinyin_filename = pinyin_filename[:25]
        pinyin_filename = pinyin_filename + file_extension
        
        upload_folder = os.path.join(base_dir, 'input_pdf')
        pdf_path = os.path.join(upload_folder, pinyin_filename)
        pdf_file.save(pdf_path)
        
        json_data = {
            "toc_start": int(toc_start),
            "toc_end": int(toc_end),
            "content_start": int(content_start),
            "original_filename": original_filename,
            "toc_structure": toc_structure
        }
        
        json_filename = pinyin_filename.replace(file_extension, '.json')
        json_path = os.path.join(upload_folder, json_filename)
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)
            
        # 开启后台线程识别书名
        config_path = os.path.join(app.static_folder, 'llm_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                llm_config = json.load(f)
        else:
            llm_config = {
                "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "qwen-vl-max"
            }
            
        threading.Thread(
            target=extract_first_page_and_recognize,
            args=(pdf_path, original_filename, base_dir, llm_config)
        ).start()
            
        return jsonify({
            'status': 'success', 
            'message': '文件上传成功',
            'session_id': session_id
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/download_result/<session_id>')
def download_result(session_id):
    data_dir = 'data'
    show_reminder = False
    no_reminder_option = False
    
    if os.path.exists(data_dir):
        folders = [f for f in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, f))]
        folder_count = len(folders)
        
        if folder_count % 5 == 0:
            no_reminder_file = os.path.join('data', 'no_reminder')
            if not os.path.exists(no_reminder_file):
                show_reminder = True
                
            if folder_count >= 15:
                no_reminder_option = True
    
    output_folder = os.path.join('data', session_id, 'output_pdf')
    input_folder = os.path.join('data', session_id, 'input_pdf')

    pdf_files = [f for f in os.listdir(output_folder) if f.endswith('.pdf')]
    if not pdf_files:
        return jsonify({'status': 'error', 'message': '未找到输出PDF文件'})
    file_path = os.path.join(output_folder, pdf_files[0])

    try:
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

    # 优先尝试读取LLM识别出的书名
    book_name = ""
    book_name_path = os.path.join('data', session_id, 'book_name.txt')
    if os.path.exists(book_name_path):
        try:
            with open(book_name_path, 'r', encoding='utf-8') as f:
                book_name = f.read().strip()
        except Exception:
            pass

    # 如果没有识别结果，则回退到原始文件名
    if not book_name:
        if original_filename:
            book_name, _ = os.path.splitext(original_filename)
        else:
            book_name = "处理结果"

    # 生成下载文件名：[LLM识别结果]-时间（yymmddhhmmss）-TOC.pdf
    time_str = datetime.now().strftime("%y%m%d%H%M%S")
    download_filename = f"{book_name}-{time_str}-TOC.pdf"

    response = send_file(file_path, as_attachment=True, download_name=download_filename)
    
    # 暴露 Content-Disposition 和自定义头供前端读取
    expose_headers = ['Content-Disposition']
    
    if show_reminder:
        response.headers['X-Show-Reminder'] = 'true'
        expose_headers.append('X-Show-Reminder')
        
    if no_reminder_option:
        response.headers['X-No-Reminder-Option'] = 'true'
        expose_headers.append('X-No-Reminder-Option')
        
    response.headers['Access-Control-Expose-Headers'] = ', '.join(expose_headers)
    
    return response

@app.route('/set_no_reminder', methods=['POST'])
def set_no_reminder():
    try:
        no_reminder_file = os.path.join('data', 'no_reminder')
        os.makedirs('data', exist_ok=True)
        with open(no_reminder_file, 'w') as f:
            f.write('do not remind')
        return jsonify({'status': 'success', 'message': '已设置不再提醒'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

AZURE_TIMEOUT = 30

def run_azure_with_timeout(python_executable, script_path, env, script_dir):
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

def get_api_key_from_config():
    config_path = os.path.join(app.static_folder, 'llm_config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        api_key_value = config.get('api_key', '')
        
        env_var_name = extract_env_var_name(api_key_value)
        if env_var_name:
            actual_api_key = os.environ.get(env_var_name, '')
            return actual_api_key
        else:
            return api_key_value
    else:
        return ''

@app.route('/run_script/<session_id>/<int:script_index>/<int:retry_count>')
def run_script(session_id, script_index, retry_count):
    ocr_model = request.args.get('ocr_model', 'aliyun')
    
    if ocr_model == 'qwen':
        script_sequence = QWEN_SCRIPT_SEQUENCE
        total_scripts = len(QWEN_SCRIPT_SEQUENCE)
    else:
        script_sequence = []
        total_scripts = 0
    
    if script_index >= len(script_sequence):
        return jsonify({
            'status': 'completed',
            'message': '所有脚本执行完成'
        })
    
    script_name, script_desc = script_sequence[script_index]
    try:
        script_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'mainprogress'))
        script_path = os.path.join(script_dir, f'{script_name}.py')
        base_dir = os.path.abspath(os.path.join('data', session_id))
        
        env = os.environ.copy()
        
        config_path = os.path.join(app.static_folder, 'llm_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            api_key_value = config.get('api_key', '')
            
            env_var_name = extract_env_var_name(api_key_value)
            if env_var_name:
                actual_api_key = os.environ.get(env_var_name, '')
                env[env_var_name] = actual_api_key
                env['DASHSCOPE_API_KEY'] = actual_api_key
            else:
                env['DASHSCOPE_API_KEY'] = api_key_value
        
        env.update({
            'BASE_DIR': base_dir,
            'PDF2JPG_INPUT': f"{base_dir}/input_pdf",
            'PDF2JPG_OUTPUT': f"{base_dir}/mark/input_image",
            'CONTENT_PREPROCESSOR_INPUT': f"{base_dir}/raw_content",
            'CONTENT_PREPROCESSOR_OUTPUT': f"{base_dir}/merged_content",
            'PDF_GENERATOR_INPUT_1': f"{base_dir}/level_adjusted_content",
            'PDF_GENERATOR_INPUT_2': f"{base_dir}/input_pdf",
            'PDF_GENERATOR_OUTPUT_1': f"{base_dir}/output_pdf",
            'QWEN_VL_INPUT': f"{base_dir}/mark/input_image",
            'QWEN_VL_OUTPUT': f"{base_dir}/automark_raw_data",
            'LEVEL_ADJUSTER_INPUT': f"{base_dir}/merged_content",
            'LEVEL_ADJUSTER_OUTPUT': f"{base_dir}/level_adjusted_content",
            'LEVEL_ADJUSTER_CACHE': f"{base_dir}/level_adjuster_cache",
            'LEVEL_ADJUSTER_PICTURES': f"{base_dir}/mark/input_image"
        })

        python_executable = sys.executable
        
        if script_name in ['ocr_hybrid', 'ocr_and_projection_hybrid']:
            ocr_model = request.args.get('ocr_model', 'aliyun')
            
            if ocr_model == 'azure':
                script_path = os.path.join(script_dir, f'{script_name.replace("hybrid", "azure")}.py')
                azure_result = run_azure_with_timeout(python_executable, script_path, env, script_dir)
                
                if azure_result.get('success', False):
                    return jsonify({
                        'status': 'success',
                        'currentScript': script_desc,
                        'message': f'{script_desc} (Azure) 执行成功',
                        'nextIndex': script_index + 1,
                        'totalScripts': total_scripts,
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
            else:
                script_path = os.path.join(script_dir, f'{script_name.replace("hybrid", "aliyun")}.py')
        
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
                return jsonify({
                    'status': 'success',
                    'currentScript': script_desc,
                    'message': f'{script_desc}执行成功',
                    'nextIndex': script_index + 1,
                    'totalScripts': total_scripts,
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

@app.route('/save_prompt/<filename>', methods=['POST'])
def save_prompt(filename):
    try:
        allowed_files = ['extract_prompt.md', 'adjuster_prompt_route.md', 'adjuster_prompt.md']
        if filename not in allowed_files:
            return jsonify({'status': 'error', 'message': '不允许保存该文件'}), 403
            
        content = request.get_data(as_text=True)
        
        static_dir = app.static_folder
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
            
        file_path = os.path.join(static_dir, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        return jsonify({'status': 'success', 'message': f'{filename} 保存成功'})
    except Exception as e:
        logger.error(f"保存提示词文件失败: {str(e)}")
        return jsonify({'status': 'error', 'message': f'保存失败: {str(e)}'}), 500

@app.route('/get_llm_config')
def get_llm_config():
    try:
        config_path = os.path.join(app.static_folder, 'llm_config.json')
        
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return jsonify({'status': 'success', 'config': config})
        else:
            default_config = {
                "api_key": "$DASHSCOPE_API_KEY$",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "qwen3.5-397b-a17b"
            }
            return jsonify({'status': 'success', 'config': default_config})
    except Exception as e:
        logger.error(f"获取 LLM 配置失败: {str(e)}")
        return jsonify({'status': 'error', 'message': f'获取配置失败: {str(e)}'}), 500

@app.route('/save_llm_config', methods=['POST'])
def save_llm_config():
    try:
        config = request.get_json()
        
        required_fields = ['api_key', 'base_url', 'model']
        for field in required_fields:
            if field not in config:
                return jsonify({'status': 'error', 'message': f'缺少必需字段: {field}'}), 400
        
        static_dir = app.static_folder
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
            
        config_path = os.path.join(static_dir, 'llm_config.json')
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            
        return jsonify({'status': 'success', 'message': 'LLM 配置保存成功'})
    except Exception as e:
        logger.error(f"保存 LLM 配置失败: {str(e)}")
        return jsonify({'status': 'error', 'message': f'保存配置失败: {str(e)}'}), 500

@app.route('/test_qwen_service', methods=['POST'])
def test_qwen_service():
    try:
        config_path = os.path.join(app.static_folder, 'llm_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            config = {
                "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "qwen3.5-397b-a17b"
            }
        
        api_key_value = config["api_key"]
        env_var_name = extract_env_var_name(api_key_value)
        if env_var_name:
            actual_api_key = os.environ.get(env_var_name, "")
        else:
            actual_api_key = api_key_value
        
        client = OpenAI(
            api_key=actual_api_key,
            base_url=config["base_url"],
        )

        completion = client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "正在测试通义千问服务访问状态，请输出`正常`这两个中文字符，不要附带任何其他内容"},
            ],
        )
        
        return jsonify({
            'status': 'success',
            'message': '通义千问服务状态正常',
            'response': completion.choices[0].message.content if completion.choices else ''
        })
    except Exception as e:
        logger.error(f"通义千问服务测试失败: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'status': 'error',
            'message': f'测试失败: {str(e)}',
            'error_code': type(e).__name__
        }), 500

@app.route('/test_llm_service', methods=['POST'])
def test_llm_service():
    try:
        data = request.get_json()
        api_key = data.get('api_key', '')
        base_url = data.get('base_url', '')
        model = data.get('model', '')
        
        if not api_key or not base_url or not model:
            return jsonify({
                'status': 'error',
                'message': 'API配置信息不完整，请检查API Key、Base URL和Model是否都已填写'
            }), 400
        
        env_var_name = extract_env_var_name(api_key)
        if env_var_name:
            actual_api_key = os.environ.get(env_var_name, "")
        else:
            actual_api_key = api_key
        
        client = OpenAI(
            api_key=actual_api_key,
            base_url=base_url,
        )

        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "正在测试LLM服务访问状态，请输出`正常`这两个中文字符，不要附带任何其他内容"},
            ],
            extra_body={"enable_thinking": False}
        )
        
        return jsonify({
            'status': 'success',
            'message': 'LLM服务状态正常',
            'response': completion.choices[0].message.content if completion.choices else ''
        })
    except Exception as e:
        logger.error(f"LLM服务测试失败: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'status': 'error',
            'message': f'测试失败: {str(e)}',
            'error_code': type(e).__name__
        }), 500

def find_available_port(start_port=5000, max_port=6000):
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

if __name__ == '__main__':
    port = find_available_port()
    if port is None:
        print("Error: No available ports found between 5000 and 6000")
    else:
        def open_browser():
            time.sleep(1.5)
            webbrowser.open_new(f'http://127.0.0.1:{port}')
            
        threading.Thread(target=open_browser).start()
        
        print(f"Starting server on port {port}")
        app.run(debug=True, port=port, use_reloader=False)