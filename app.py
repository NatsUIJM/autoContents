from flask import Flask, render_template, jsonify, request, send_file, send_from_directory, Response
import os
import logging
import time
import json
import socket
import webbrowser
import threading
from openai import OpenAI
from dotenv import load_dotenv
import traceback
import re

from mainprogress.pipeline import (
    STEP_SEQUENCE, create_session, pinyin_name, write_initial_json, run_step,
)
from mainprogress.llm_config import (
    load_llm_config, resolve_value, DEFAULT_BASE_URL, DEFAULT_MODEL,
)

load_dotenv()
logger = logging.getLogger('gunicorn.error')

app = Flask(__name__)

# 版本号单一真相源：发版时只改这里（readme 与 tag 同步更新）。
# 前端横幅用它显示当前版本，并与 GitHub Releases 最新 tag 比对做更新提醒。
APP_VERSION = "1.1.0"
RELEASES_API = "https://api.github.com/repos/NatsUIJM/autoContents/releases/latest"

# ==================== Flask 路由 ====================

@app.route('/api_version')
def api_version():
    """返回当前版本与最新 Release 信息，供前端更新检查。"""
    return jsonify({
        'version': APP_VERSION,
        'releases_url': RELEASES_API,
        'download_url': 'https://github.com/NatsUIJM/autoContents/releases/latest',
    })

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(app.static_folder, 'favicon.ico')

@app.route('/apple-touch-icon-precomposed.png')
def apple_icon_precomposed():
    return send_from_directory(app.static_folder, 'apple-touch-icon-precomposed.png')

@app.route('/apple-touch-icon.png')
def apple_icon():
    return send_from_directory(app.static_folder, 'apple-touch-icon.png')

# ==================== 原有路由 ====================

SCRIPT_TIMEOUT = 3000

def load_config_file():
    """加载完整的 llm_config.json，不存在则返回默认结构。"""
    config_path = os.path.join(app.static_folder, 'llm_config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "configs": [],
        "active_id": None
    }

def save_config_file(data):
    """保存完整的 llm_config.json。"""
    config_path = os.path.join(app.static_folder, 'llm_config.json')
    static_dir = app.static_folder
    if not os.path.exists(static_dir):
        os.makedirs(static_dir)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_active_llm_config():
    """获取当前可用的 LLM 配置（统一走 llm_config 模块，出错时回退默认值）。"""
    try:
        return load_llm_config()
    except ValueError:
        return {
            "api_key": "",
            "base_url": DEFAULT_BASE_URL,
            "model": DEFAULT_MODEL,
        }

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    try:
        session_id, base_dir = create_session('data')

        if 'pdf' not in request.files:
            return jsonify({'status': 'error', 'message': '未找到 PDF 文件'})

        pdf_file = request.files['pdf']
        if pdf_file.filename == '':
            return jsonify({'status': 'error', 'message': '未选择 PDF 文件'})

        original_filename = pdf_file.filename
        staged_name = pinyin_name(original_filename)

        pdf_path = os.path.join(base_dir, 'input_pdf', staged_name)
        pdf_file.save(pdf_path)
        write_initial_json(base_dir, staged_name, original_filename)

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

    # 清理文件名中的非法字符，仅保留字母、数字、中文、下划线、连字符和空格
    # Windows/Linux/macOS 通用安全字符集
    safe_book_name = re.sub(r'[<>:"/\\|?*]', '', book_name)
    # 去除首尾空格
    safe_book_name = safe_book_name.strip()
    
    if not safe_book_name:
        safe_book_name = "处理结果"

    # 直接使用书名作为文件名，去掉时间和 TOC 标注
    download_filename = f"{safe_book_name}.pdf"

    response = send_file(file_path, as_attachment=True, download_name=download_filename)
    
    expose_headers = ['Content-Disposition']
    response.headers['Access-Control-Expose-Headers'] = ', '.join(expose_headers)
    
    return response

@app.route('/run_script/<session_id>/<int:script_index>/<int:retry_count>')
def run_script(session_id, script_index, retry_count):
    total_scripts = len(STEP_SEQUENCE)

    if script_index >= total_scripts:
        return jsonify({
            'status': 'completed',
            'message': '所有脚本执行完成',
            'totalScripts': total_scripts
        })

    base_dir = os.path.abspath(os.path.join('data', session_id))
    step = run_step(script_index, base_dir, timeout=SCRIPT_TIMEOUT)

    if step.ok:
        return jsonify({
            'status': 'success',
            'currentScript': step.desc,
            'message': f'{step.desc}执行成功',
            'nextIndex': script_index + 1,
            'totalScripts': total_scripts,
            'retryCount': 0,
            'session_id': session_id,
            'stdout': step.stdout,
            'stderr': step.stderr
        })

    message = step.error or f'{step.desc}执行失败'
    return jsonify({
        'status': 'error',
        'currentScript': step.desc,
        'message': message,
        'stdout': step.stdout,
        'stderr': step.stderr,
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
        data = load_config_file()
        configs = data.get('configs', [])
        active_id = data.get('active_id')
        # 返回当前激活配置的完整信息，方便前端直接使用
        active_config = None
        for c in configs:
            if c.get('id') == active_id:
                active_config = c
                break
        if active_config is None and configs:
            active_config = configs[0]
        # 尚无已保存配置时，回退到环境变量默认值（兼容 .env / OPENAI_* 个性化配置）
        if not configs:
            active_config = {
                'id': None,
                'name': '',
                'api_key': os.getenv("OPENAI_API_KEY", ""),
                'base_url': os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL),
                'model': os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
            }
        return jsonify({
            'status': 'success',
            'configs': configs,
            'active_id': active_id,
            'active_config': active_config
        })
    except Exception as e:
        logger.error(f"获取 LLM 配置失败：{str(e)}")
        return jsonify({'status': 'error', 'message': f'获取配置失败：{str(e)}'}), 500

@app.route('/save_llm_config', methods=['POST'])
def save_llm_config():
    try:
        config_entry = request.get_json()

        required_fields = ['api_key', 'base_url', 'model']
        for field in required_fields:
            if field not in config_entry:
                return jsonify({'status': 'error', 'message': f'缺少必需字段：{field}'}), 400

        data = load_config_file()
        configs = data.get('configs', [])

        config_id = config_entry.get('id', '')
        name = config_entry.get('name', '').strip()
        if not name:
            name = config_entry.get('model', '未命名')

        if config_id:
            # 更新已有配置
            found = False
            for c in configs:
                if c.get('id') == config_id:
                    c['name'] = name
                    c['api_key'] = config_entry['api_key']
                    c['base_url'] = config_entry['base_url']
                    c['model'] = config_entry['model']
                    found = True
                    break
            if not found:
                return jsonify({'status': 'error', 'message': f'配置 {config_id} 不存在'}), 404
        else:
            # 新增配置
            import uuid
            config_id = uuid.uuid4().hex[:8]
            configs.append({
                'id': config_id,
                'name': name,
                'api_key': config_entry['api_key'],
                'base_url': config_entry['base_url'],
                'model': config_entry['model']
            })

        # 如果还没有激活配置，自动激活第一个
        if not data.get('active_id'):
            data['active_id'] = configs[0]['id']

        data['configs'] = configs
        save_config_file(data)

        return jsonify({'status': 'success', 'message': 'LLM 配置保存成功', 'id': config_id})
    except Exception as e:
        logger.error(f"保存 LLM 配置失败：{str(e)}")
        return jsonify({'status': 'error', 'message': f'保存配置失败：{str(e)}'}), 500

@app.route('/delete_llm_config/<config_id>', methods=['POST'])
def delete_llm_config(config_id):
    try:
        data = load_config_file()
        configs = data.get('configs', [])

        if len(configs) <= 1:
            return jsonify({'status': 'error', 'message': '至少需要保留一个配置'}), 400

        new_configs = [c for c in configs if c.get('id') != config_id]
        if len(new_configs) == len(configs):
            return jsonify({'status': 'error', 'message': f'配置 {config_id} 不存在'}), 404

        data['configs'] = new_configs
        if data.get('active_id') == config_id:
            data['active_id'] = new_configs[0]['id']

        save_config_file(data)
        return jsonify({'status': 'success', 'message': '配置已删除', 'active_id': data['active_id']})
    except Exception as e:
        logger.error(f"删除 LLM 配置失败：{str(e)}")
        return jsonify({'status': 'error', 'message': f'删除配置失败：{str(e)}'}), 500

@app.route('/set_active_config/<config_id>', methods=['POST'])
def set_active_config(config_id):
    try:
        data = load_config_file()
        configs = data.get('configs', [])
        if not any(c.get('id') == config_id for c in configs):
            return jsonify({'status': 'error', 'message': f'配置 {config_id} 不存在'}), 404

        data['active_id'] = config_id
        save_config_file(data)
        return jsonify({'status': 'success', 'message': '已切换激活配置'})
    except Exception as e:
        logger.error(f"切换激活配置失败：{str(e)}")
        return jsonify({'status': 'error', 'message': f'切换配置失败：{str(e)}'}), 500

@app.route('/test_qwen_service', methods=['POST'])
def test_qwen_service():
    try:
        config = get_active_llm_config()

        client = OpenAI(
            api_key=config["api_key"],
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
        
        try:
            actual_api_key = resolve_value(api_key)
        except ValueError:
            actual_api_key = ""
        
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
        app.run(debug=True, port=port, use_reloader=False, threaded=True)