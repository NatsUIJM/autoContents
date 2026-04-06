from flask import Flask, render_template, jsonify, request, send_file, send_from_directory, Response
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
from openai import OpenAI
import traceback
import platform
import requests
import uuid

logger = logging.getLogger('gunicorn.error')

app = Flask(__name__)

# ==================== 配置 ====================

# 外部鉴权 API 基础 URL
AUTH_API_BASE_URL = "https://autocontents.uijm2004.workers.dev/api"

# ==================== 鉴权相关函数 ====================

def get_machine_serial():
    """获取机器码"""
    sys_name = platform.system()
    
    if sys_name == "Darwin":  # macOS
        try:
            result = subprocess.run(
                ["/usr/sbin/system_profiler", "SPHardwareDataType"], 
                stdout=subprocess.PIPE, 
                text=True, 
                check=True
            )
            for line in result.stdout.splitlines():
                if "Serial Number" in line:
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
            
    elif sys_name == "Windows":
        try:
            result = subprocess.run(
                ["cmd", "/c", "vol", "C:"], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                timeout=5
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                parts = output.split()
                if parts:
                    candidate = parts[-1]
                    if len(candidate) == 9 and candidate[4] == '-':
                        return candidate
        except Exception:
            pass
    
    # 如果无法获取硬件序列号，使用 MAC 地址作为备选
    try:
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff)
                       for elements in range(0, 2 * 6, 2)][::-1])
        return mac
    except Exception:
        pass
            
    return None

def get_auth_key_path():
    """获取 auth.key 文件路径（根目录）"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auth.key')

def read_auth_key():
    """读取 auth.key 文件内容"""
    auth_path = get_auth_key_path()
    if os.path.exists(auth_path):
        with open(auth_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return None

def write_auth_key(content):
    """写入 auth.key 文件"""
    auth_path = get_auth_key_path()
    with open(auth_path, 'w', encoding='utf-8') as f:
        f.write(content)

def delete_auth_key():
    """删除 auth.key 文件"""
    auth_path = get_auth_key_path()
    if os.path.exists(auth_path):
        os.remove(auth_path)

def is_trial_active():
    """检查试用是否激活"""
    content = read_auth_key()
    return content == 'Trail'

def is_activated():
    """检查是否已正式激活（32 位激活码）"""
    content = read_auth_key()
    return content is not None and len(content) == 32

def check_auth():
    """检查鉴权状态，返回 (是否通过，激活码或 None)"""
    content = read_auth_key()
    if content is None:
        return False, None
    if content == 'Trail':
        return True, None  # 试用模式
    if len(content) == 32:
        return True, content  # 正式激活
    return False, None

# ==================== Flask 路由 ====================

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(app.static_folder, 'favicon.ico')

@app.route('/apple-touch-icon-precomposed.png')
def apple_icon_precomposed():
    return send_from_directory(app.static_folder, 'apple-touch-icon-precomposed.png')

@app.route('/apple-touch-icon.png')
def apple_icon():
    return send_from_directory(app.static_folder, 'apple-touch-icon.png')

# ==================== 鉴权 API 端点（联网校验） ====================

@app.route('/api/trail', methods=['POST'])
def api_trail():
    """开始试用 - 联网校验"""
    try:
        data = request.get_json()
        machine_code = data.get('machine_code', '')
        
        if not machine_code:
            return jsonify({'status': 'error', 'message': '机器码不能为空'}), 400
        
        # 调用外部 API 进行校验
        try:
            response = requests.post(
                f"{AUTH_API_BASE_URL}/trial",
                json={'machine_code': machine_code},
                timeout=30
            )
            external_data = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"连接外部鉴权服务失败：{str(e)}")
            return jsonify({
                'status': 'error',
                'message': f'连接鉴权服务器失败：{str(e)}'
            }), 503
        
        # 检查外部 API 响应
        if response.status_code == 200 and external_data.get('status') == 'success':
            # 校验成功，写入试用标识
            write_auth_key('Trail')
            logger.info(f"试用激活成功 - 机器码：{machine_code}")
            return jsonify({
                'status': 'success',
                'message': external_data.get('message', '试用已激活')
            })
        else:
            # 校验失败，返回外部 API 的错误信息
            error_message = external_data.get('message', '试用激活失败')
            logger.warning(f"试用激活失败 - 机器码：{machine_code}, 原因：{error_message}")
            return jsonify({
                'status': 'error',
                'message': error_message
            }), 400
            
    except Exception as e:
        logger.error(f"试用激活失败：{str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/activate', methods=['POST'])
def api_activate():
    """正式激活 - 联网校验"""
    try:
        data = request.get_json()
        machine_code = data.get('machine_code', '')
        activation_code = data.get('activation_code', '')
        
        if not machine_code:
            return jsonify({'status': 'error', 'message': '机器码不能为空'}), 400
        
        if not activation_code or len(activation_code) != 32:
            return jsonify({'status': 'error', 'message': '激活码必须为 32 个字符'}), 400
        
        # 调用外部 API 进行校验
        try:
            response = requests.post(
                f"{AUTH_API_BASE_URL}/activate",
                json={
                    'machine_code': machine_code,
                    'activation_code': activation_code
                },
                timeout=30
            )
            external_data = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"连接外部鉴权服务失败：{str(e)}")
            return jsonify({
                'status': 'error',
                'message': f'连接鉴权服务器失败：{str(e)}'
            }), 503
        
        # 检查外部 API 响应
        if response.status_code == 200 and external_data.get('status') == 'success':
            # 校验成功，写入激活码
            write_auth_key(activation_code)
            logger.info(f"正式激活成功 - 机器码：{machine_code}")
            return jsonify({
                'status': 'success',
                'message': external_data.get('message', '激活成功')
            })
        else:
            # 校验失败，返回外部 API 的错误信息
            error_message = external_data.get('message', '激活失败')
            logger.warning(f"正式激活失败 - 机器码：{machine_code}, 原因：{error_message}")
            return jsonify({
                'status': 'error',
                'message': error_message
            }), 400
            
    except Exception as e:
        logger.error(f"激活失败：{str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/deactivate', methods=['POST'])
def api_deactivate():
    """反激活 - 联网校验"""
    try:
        data = request.get_json()
        activation_code = data.get('activation_code', '')
        
        if not activation_code or len(activation_code) != 32:
            return jsonify({'status': 'error', 'message': '激活码必须为 32 个字符'}), 400
        
        # 调用外部 API 进行校验
        try:
            response = requests.post(
                f"{AUTH_API_BASE_URL}/deactivate",
                json={'activation_code': activation_code},
                timeout=30
            )
            external_data = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"连接外部鉴权服务失败：{str(e)}")
            return jsonify({
                'status': 'error',
                'message': f'连接鉴权服务器失败：{str(e)}'
            }), 503
        
        # 检查外部 API 响应
        if response.status_code == 200 and external_data.get('status') == 'success':
            # 校验成功，删除 auth.key 文件
            delete_auth_key()
            logger.info(f"反激活成功")
            return jsonify({
                'status': 'success',
                'message': external_data.get('message', '反激活成功')
            })
        else:
            # 校验失败，返回外部 API 的错误信息
            error_message = external_data.get('message', '反激活失败')
            logger.warning(f"反激活失败 - 原因：{error_message}")
            return jsonify({
                'status': 'error',
                'message': error_message
            }), 400
            
    except Exception as e:
        logger.error(f"反激活失败：{str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/auth', methods=['GET'])
def api_auth():
    """鉴权验证（执行脚本前调用）- 联网校验"""
    try:
        machine_code = request.args.get('machine_code', '')
        activation_code = request.args.get('activation_code', '')
        
        if not machine_code:
            return jsonify({'status': 'error', 'message': '机器码不能为空'}), 400
        
        # 获取本地存储的激活码（优先使用本地的）
        local_auth_code = read_auth_key()
        if local_auth_code is None:
            return jsonify({
                'status': 'error',
                'message': '未找到授权文件，请先试用或激活',
                'auth_passed': False
            }), 403
        
        # 调用外部 API 进行校验
        try:
            response = requests.get(
                f"{AUTH_API_BASE_URL}/auth",
                params={
                    'machine_code': machine_code,
                    'activation_code': local_auth_code
                },
                timeout=30
            )
            external_data = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"连接外部鉴权服务失败：{str(e)}")
            return jsonify({
                'status': 'error',
                'message': f'连接鉴权服务器失败：{str(e)}',
                'auth_passed': False
            }), 503
        
        # 检查外部 API 响应
        if response.status_code == 200 and external_data.get('status') == 'success':
            logger.info(f"鉴权通过 - 机器码：{machine_code}")
            return jsonify({
                'status': 'success',
                'message': external_data.get('message', '鉴权通过'),
                'auth_passed': True,
                'is_trial': local_auth_code == 'Trail'
            })
        else:
            # 校验失败，返回外部 API 的错误信息
            error_message = external_data.get('message', '鉴权失败')
            logger.warning(f"鉴权失败 - 机器码：{machine_code}, 原因：{error_message}")
            return jsonify({
                'status': 'error',
                'message': error_message,
                'auth_passed': False
            }), 403
            
    except Exception as e:
        logger.error(f"鉴权验证失败：{str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/auth_status', methods=['GET'])
def api_auth_status():
    """获取当前鉴权状态（前端初始化时调用）- 仅本地检查"""
    try:
        content = read_auth_key()
        
        if content is None:
            return jsonify({
                'status': 'success',
                'has_key': False,
                'is_trial': False,
                'is_activated': False
            })
        elif content == 'Trail':
            return jsonify({
                'status': 'success',
                'has_key': True,
                'is_trial': True,
                'is_activated': False
            })
        elif len(content) == 32:
            return jsonify({
                'status': 'success',
                'has_key': True,
                'is_trial': False,
                'is_activated': True
            })
        else:
            return jsonify({
                'status': 'success',
                'has_key': True,
                'is_trial': False,
                'is_activated': False
            })
    except Exception as e:
        logger.error(f"获取鉴权状态失败：{str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/machine_code', methods=['GET'])
def api_machine_code():
    """获取机器码"""
    try:
        serial = get_machine_serial()
        if serial:
            return jsonify({
                'status': 'success',
                'machine_code': serial
            })
        else:
            return jsonify({
                'status': 'error',
                'message': '无法获取机器码'
            }), 500
    except Exception as e:
        logger.error(f"获取机器码失败：{str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==================== 原有路由 ====================

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
    ('pdf_metadata_extractor', 'PDF 元数据提取'),
    ('pdf_to_image', 'PDF 转 JPG'),
    ('qwen_vl_extract', '目录数据提取'),
    ('determine_toc_levels', '目录层级确定'),
    ('content_postprocessor', '目录后处理'),
    ('pdf_generator', '生成 PDF')
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
    从 API KEY 值中提取环境变量名称
    例如：$CHERRY_IN_API_KEY$ -> CHERRY_IN_API_KEY
    """
    if api_key_value.startswith('$') and api_key_value.endswith('$'):
        return api_key_value[1:-1]
    return None

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    # 执行前检查鉴权
    auth_passed, _ = check_auth()
    if not auth_passed:
        return jsonify({'status': 'error', 'message': '请先试用或激活后才能使用'}), 403
    
    try:
        session_id = generate_session_id()
        base_dir = create_data_folders(session_id)
        
        if 'pdf' not in request.files:
            return jsonify({'status': 'error', 'message': '未找到 PDF 文件'})
            
        pdf_file = request.files['pdf']
        if pdf_file.filename == '':
            return jsonify({'status': 'error', 'message': '未选择 PDF 文件'})
            
        original_filename = pdf_file.filename
        filename_without_ext, file_extension = os.path.splitext(original_filename)
        
        pinyin_filename = convert_to_pinyin(filename_without_ext)
        if len(pinyin_filename) > 25:
            pinyin_filename = pinyin_filename[:25]
        pinyin_filename = pinyin_filename + file_extension
        
        upload_folder = os.path.join(base_dir, 'input_pdf')
        pdf_path = os.path.join(upload_folder, pinyin_filename)
        pdf_file.save(pdf_path)
        
        json_filename = pinyin_filename.replace(file_extension, '.json')
        json_path = os.path.join(upload_folder, json_filename)
        
        initial_json_data = {
            "toc_start": 0,
            "toc_end": 0,
            "content_start": 0,
            "original_filename": original_filename,
            "book_name": ""
        }
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(initial_json_data, f, ensure_ascii=False, indent=4)
            
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

    pdf_files = [f for f in os.listdir(output_folder) if f.endswith('.pdf')]
    if not pdf_files:
        return jsonify({'status': 'error', 'message': '未找到输出 PDF 文件'})
    file_path = os.path.join(output_folder, pdf_files[0])

    book_name = "处理结果"
    try:
        json_files = [f for f in os.listdir(input_folder) if f.endswith('.json')]
        if json_files:
            json_path = os.path.join(input_folder, json_files[0])
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            extracted_name = json_data.get('book_name', '')
            if extracted_name:
                book_name = extracted_name
    except Exception as e:
        logger.error(f"读取 JSON 时出错：{e}")

    time_str = datetime.now().strftime("%y%m%d%H%M%S")
    download_filename = f"{book_name}-{time_str}-TOC.pdf"

    response = send_file(file_path, as_attachment=True, download_name=download_filename)
    
    expose_headers = ['Content-Disposition']
    response.headers['Access-Control-Expose-Headers'] = ', '.join(expose_headers)
    
    return response

@app.route('/run_script/<session_id>/<int:script_index>/<int:retry_count>')
def run_script(session_id, script_index, retry_count):
    # 执行前检查鉴权
    auth_passed, _ = check_auth()
    if not auth_passed:
        return jsonify({'status': 'error', 'message': '鉴权失败，请先试用或激活'}), 403
    
    script_sequence = QWEN_SCRIPT_SEQUENCE
    total_scripts = len(script_sequence)
    
    if script_index >= total_scripts:
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
            'PDF_METADATA_EXTRACTOR_INPUT': f"{base_dir}/input_pdf",
            'PDF_METADATA_EXTRACTOR_OUTPUT': f"{base_dir}/input_pdf",
            'PDF2JPG_INPUT': f"{base_dir}/input_pdf",
            'PDF2JPG_OUTPUT': f"{base_dir}/mark/input_image",
            'CONTENT_POSTPROCESSOR_INPUT': f"{base_dir}/raw_content",
            'CONTENT_POSTPROCESSOR_OUTPUT': f"{base_dir}/level_adjusted_content",
            'PDF_GENERATOR_INPUT_1': f"{base_dir}/level_adjusted_content",
            'PDF_GENERATOR_INPUT_2': f"{base_dir}/input_pdf",
            'PDF_GENERATOR_OUTPUT_1': f"{base_dir}/output_pdf",
            'QWEN_VL_INPUT': f"{base_dir}/mark/input_image",
            'QWEN_VL_OUTPUT': f"{base_dir}/automark_raw_data"
        })

        python_executable = sys.executable
        
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
        logger.error(f"执行脚本时发生错误：{str(e)}")
        return jsonify({
            'status': 'error',
            'currentScript': script_desc,
            'message': f'执行出错：{str(e)}',
            'retryCount': retry_count,
            'scriptIndex': script_index,
            'session_id': session_id
        })

@app.route('/stream_log')
def stream_log():
    def generate():
        log_file = 'log.txt'
        if not os.path.exists(log_file):
            open(log_file, 'w', encoding='utf-8').close()
            
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            for line in lines[-5:]:
                yield f"data: {json.dumps({'text': line.strip()})}\n\n"
            
            while True:
                line = f.readline()
                if line:
                    yield f"data: {json.dumps({'text': line.strip()})}\n\n"
                else:
                    time.sleep(0.5)
                    
    return Response(generate(), mimetype='text/event-stream')

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
        logger.error(f"获取 LLM 配置失败：{str(e)}")
        return jsonify({'status': 'error', 'message': f'获取配置失败：{str(e)}'}), 500

@app.route('/save_llm_config', methods=['POST'])
def save_llm_config():
    try:
        config = request.get_json()
        
        required_fields = ['api_key', 'base_url', 'model']
        for field in required_fields:
            if field not in config:
                return jsonify({'status': 'error', 'message': f'缺少必需字段：{field}'}), 400
        
        static_dir = app.static_folder
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
            
        config_path = os.path.join(static_dir, 'llm_config.json')
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            
        return jsonify({'status': 'success', 'message': 'LLM 配置保存成功'})
    except Exception as e:
        logger.error(f"保存 LLM 配置失败：{str(e)}")
        return jsonify({'status': 'error', 'message': f'保存配置失败：{str(e)}'}), 500

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
                {"role": "user", "content": "正在测试通义千问服务访问状态，请输出 `正常` 这两个中文字符，不要附带任何其他内容"},
            ],
        )
        
        return jsonify({
            'status': 'success',
            'message': '通义千问服务状态正常',
            'response': completion.choices[0].message.content if completion.choices else ''
        })
    except Exception as e:
        logger.error(f"通义千问服务测试失败：{str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'status': 'error',
            'message': f'测试失败：{str(e)}',
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
                'message': 'API 配置信息不完整，请检查 API Key、Base URL 和 Model 是否都已填写'
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
                {"role": "user", "content": "正在测试 LLM 服务访问状态，请输出 `正常` 这两个中文字符，不要附带任何其他内容"},
            ],
            extra_body={"enable_thinking": False}
        )
        
        return jsonify({
            'status': 'success',
            'message': 'LLM 服务状态正常',
            'response': completion.choices[0].message.content if completion.choices else ''
        })
    except Exception as e:
        logger.error(f"LLM 服务测试失败：{str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'status': 'error',
            'message': f'测试失败：{str(e)}',
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