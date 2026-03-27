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
        export_filename = request.form.get('exportFilename', '%name-toc')  # 默认为%name-toc
        
        if not all([toc_start, toc_end, content_start]):
            return jsonify({'status': 'error', 'message': '页码信息不完整'})
            
        # 保存原始文件名（中文）
        original_filename = pdf_file.filename
        filename_without_ext, file_extension = os.path.splitext(original_filename)
        
        # 转换文件名为拼音并限制长度为 25 个字符
        pinyin_filename = convert_to_pinyin(filename_without_ext)
        # 清理文件名中的非法字符
        invalid_chars = '<>:"/\\|？*'
        for char in invalid_chars:
            pinyin_filename = pinyin_filename.replace(char, '_')
        # 限制长度为 25 个字符
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
            "original_filename": original_filename,  # 添加原始文件名字段
            "toc_structure": toc_structure,  # 添加目录结构选择字段
            "export_filename": export_filename  # 添加导出文件名配置
        }
        
        # JSON 文件名使用拼音 (限制长度) - 确保与 PDF 文件名一致
        json_filename = os.path.splitext(pinyin_filename)[0] + '.json'
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
    # 检查data目录下的文件夹数量是否为5的倍数
    data_dir = 'data'
    show_reminder = False
    no_reminder_option = False
    
    if os.path.exists(data_dir):
        folders = [f for f in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, f))]
        folder_count = len(folders)
        
        # 如果文件夹数量是5的倍数，设置一个标志用于前端显示弹窗
        if folder_count % 5 == 0:
            # 检查是否已经设置了不再弹出
            no_reminder_file = os.path.join('data', 'no_reminder')
            if not os.path.exists(no_reminder_file):
                show_reminder = True
                
            # 如果文件夹数量大于等于15个，则显示"不再弹出"选项
            if folder_count >= 15:
                no_reminder_option = True
    
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
            return jsonify({'status': 'error', 'message': '未找到原始 PDF 文件'})

        json_file_name = os.path.splitext(original_pdf)[0] + '.json'
        json_path = os.path.join(input_folder, json_file_name)

        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        original_filename = json_data.get('original_filename', None)
        export_filename_template = json_data.get('export_filename', '%name-toc')
        toc_start = json_data.get('toc_start', 1)
        toc_end = json_data.get('toc_end', toc_start)

    except Exception as e:
        print(f"[ERROR] 读取 JSON 时出错：{e}")
        original_filename = None
        export_filename_template = '%name-toc'
        toc_start = 1
        toc_end = 1

    # 使用自定义文件名或默认逻辑
    if original_filename:
        # 使用与 pdf_generator.py 相同的占位符替换逻辑
        from datetime import datetime
        name_without_ext = os.path.splitext(original_filename)[0]
        download_filename_base = export_filename_template.replace('%name', name_without_ext)
        download_filename_base = download_filename_base.replace('%date', datetime.now().strftime("%Y%m%d_%H%M%S"))
        
        if toc_start and toc_end:
            range_str = f"{toc_start}-{toc_end}"
            download_filename_base = download_filename_base.replace('%range', range_str)
        else:
            download_filename_base = download_filename_base.replace('%range', '')
        
        # 清理非法字符
        invalid_chars = '<>:"/\\|？*'
        for char in invalid_chars:
            download_filename_base = download_filename_base.replace(char, '_')
        
        download_filename = f"{download_filename_base}.pdf"
    else:
        # 万不得已，使用处理结果.pdf
        download_filename = '处理结果.pdf'

    # 返回下载链接
    response = send_file(file_path, as_attachment=True, download_name=download_filename)
    
    # 如果需要显示提醒，则添加特殊响应头
    if show_reminder:
        response.headers['X-Show-Reminder'] = 'true'
        
    # 如果需要显示"不再弹出"选项，则添加另一个响应头
    if no_reminder_option:
        response.headers['X-No-Reminder-Option'] = 'true'
    
    return response

# 添加新的路由处理不再提醒的设置
@app.route('/set_no_reminder', methods=['POST'])
def set_no_reminder():
    try:
        # 创建一个标记文件表示用户选择不再提醒
        no_reminder_file = os.path.join('data', 'no_reminder')
        os.makedirs('data', exist_ok=True)
        with open(no_reminder_file, 'w') as f:
            f.write('do not remind')
        return jsonify({'status': 'success', 'message': '已设置不再提醒'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

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

def extract_env_var_name(api_key_value):
    """
    从API KEY值中提取环境变量名称
    例如: $CHERRY_IN_API_KEY$ -> CHERRY_IN_API_KEY
    """
    if api_key_value.startswith('$') and api_key_value.endswith('$'):
        return api_key_value[1:-1]  # 移除开头和结尾的$
    return None

def get_api_key_from_config():
    """
    从配置文件中获取API KEY，支持从环境变量读取
    """
    config_path = os.path.join(app.static_folder, 'llm_config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        api_key_value = config.get('api_key', '')
        
        # 检查是否是环境变量引用格式
        env_var_name = extract_env_var_name(api_key_value)
        if env_var_name:
            # 从环境变量中获取实际值
            actual_api_key = os.environ.get(env_var_name, '')
            return actual_api_key
        else:
            # 直接返回配置文件中的值（可能是硬编码的API KEY）
            return api_key_value
    else:
        # 如果配置文件不存在，返回空字符串
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
        
        # 修复点1：继承父进程的所有环境变量，防止自定义环境变量丢失
        env = os.environ.copy()
        
        # 修复点2：动态解析并设置对应的环境变量名
        config_path = os.path.join(app.static_folder, 'llm_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            api_key_value = config.get('api_key', '')
            
            env_var_name = extract_env_var_name(api_key_value)
            if env_var_name:
                actual_api_key = os.environ.get(env_var_name, '')
                env[env_var_name] = actual_api_key
                env['DASHSCOPE_API_KEY'] = actual_api_key  # 兼容保留
            else:
                env['DASHSCOPE_API_KEY'] = api_key_value
        
        # 添加应用所需的环境变量
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
# 在 app.py 中添加以下新路由

@app.route('/save_prompt/<filename>', methods=['POST'])
def save_prompt(filename):
    """保存提示词文件"""
    try:
        # 限制只能保存指定的提示词文件
        allowed_files = ['extract_prompt.md', 'adjuster_prompt_route.md', 'adjuster_prompt.md']
        if filename not in allowed_files:
            return jsonify({'status': 'error', 'message': '不允许保存该文件'}), 403
            
        # 获取请求体中的内容
        content = request.get_data(as_text=True)
        
        # 确保 static 目录存在
        static_dir = app.static_folder
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
            
        # 保存文件
        file_path = os.path.join(static_dir, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        return jsonify({'status': 'success', 'message': f'{filename} 保存成功'})
    except Exception as e:
        logger.error(f"保存提示词文件失败：{str(e)}")
        return jsonify({'status': 'error', 'message': f'保存失败：{str(e)}'}), 500

@app.route('/save_default_export_filename', methods=['POST'])
def save_default_export_filename():
    """保存默认的导出文件名格式"""
    try:
        data = request.get_json()
        export_filename = data.get('exportFilename', '%name-toc')
        
        # 确保 static 目录存在
        static_dir = app.static_folder
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
        
        # 保存默认设置到文件
        config_file = os.path.join(static_dir, 'default_export_filename.json')
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump({'export_filename': export_filename}, f, ensure_ascii=False, indent=2)
        
        return jsonify({'status': 'success', 'message': '默认导出文件名已保存'})
    except Exception as e:
        logger.error(f"保存默认导出文件名失败：{str(e)}")
        return jsonify({'status': 'error', 'message': f'保存失败：{str(e)}'}), 500

@app.route('/get_default_export_filename', methods=['GET'])
def get_default_export_filename():
    """获取默认的导出文件名格式"""
    try:
        config_file = os.path.join(app.static_folder, 'default_export_filename.json')
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({'exportFilename': data.get('export_filename', '%name-toc')})
        else:
            # 返回默认值
            return jsonify({'exportFilename': '%name-toc'})
    except Exception as e:
        logger.error(f"获取默认导出文件名失败：{str(e)}")
        return jsonify({'exportFilename': '%name-toc'})

# 添加获取和保存 llm_config.json 的路由
@app.route('/get_llm_config')
def get_llm_config():
    """获取 LLM 配置"""
    try:
        import json
        config_path = os.path.join(app.static_folder, 'llm_config.json')
        
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return jsonify({'status': 'success', 'config': config})
        else:
            # 如果配置文件不存在，返回默认值
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
    """保存 LLM 配置"""
    try:
        import json
        config = request.get_json()
        
        # 验证必需的字段
        required_fields = ['api_key', 'base_url', 'model']
        for field in required_fields:
            if field not in config:
                return jsonify({'status': 'error', 'message': f'缺少必需字段: {field}'}), 400
        
        # 确保 static 目录存在
        static_dir = app.static_folder
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
            
        # 保存配置文件
        config_path = os.path.join(static_dir, 'llm_config.json')
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            
        return jsonify({'status': 'success', 'message': 'LLM 配置保存成功'})
    except Exception as e:
        logger.error(f"保存 LLM 配置失败: {str(e)}")
        return jsonify({'status': 'error', 'message': f'保存配置失败: {str(e)}'}), 500

@app.route('/test_qwen_service', methods=['POST'])
def test_qwen_service():
    """
    测试通义千问服务状态
    """
    try:
        # 读取配置文件
        config_path = os.path.join(app.static_folder, 'llm_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            # 使用默认配置
            config = {
                "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "qwen3.5-397b-a17b"
            }
        
        # 从配置文件获取API KEY，支持环境变量引用
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
    """
    测试任意LLM服务状态
    """
    try:
        # 从前端获取配置
        data = request.get_json()
        api_key = data.get('api_key', '')
        base_url = data.get('base_url', '')
        model = data.get('model', '')
        
        if not api_key or not base_url or not model:
            return jsonify({
                'status': 'error',
                'message': 'API配置信息不完整，请检查API Key、Base URL和Model是否都已填写'
            }), 400
        
        # 处理API密钥中的环境变量引用
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