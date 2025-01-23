import os
import sys
import json
import shutil
import subprocess
import time
import io
import threading
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QVBoxLayout, QWidget
from UI.mainWindow import Ui_MainWindow
from UI.pdfCard import Ui_Form
from pdf2image import convert_from_path
from PyQt5.QtCore import QThread, pyqtSignal, QTimer
from queue import Queue

import sys
import traceback
import logging
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QLabel, QVBoxLayout, QWidget
from PyQt5.QtCore import QThread, pyqtSignal

logging.basicConfig(
    filename='error.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class ScriptRunner(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)  # 新增错误信号
    
    def __init__(self, script_name):
        super().__init__()
        self.script_name = script_name
        self.process = None
        
    def run(self):
        try:
            self.process = subprocess.Popen(
                [sys.executable, os.path.join("mainprogress", self.script_name)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8'
            )
            
            while True:
                if self.process is None:  # 检查进程是否存在
                    break
                    
                try:
                    line = self.process.stdout.readline()
                    if not line and self.process.poll() is not None:
                        break
                    line = line.strip()
                    if line:
                        self.progress.emit(line)
                except Exception as e:
                    logging.error(f"读取输出错误: {str(e)}")
                    logging.error(traceback.format_exc())
                    self.error.emit(str(e))
                    break
            
            if self.process and self.process.returncode is not None:
                success = self.process.returncode == 0
                self.finished.emit(success)
            
        except Exception as e:
            logging.error(f"运行脚本错误: {str(e)}")
            logging.error(traceback.format_exc())
            self.error.emit(str(e))
            self.finished.emit(False)
    
    def stop(self):
        """安全停止进程"""
        try:
            if self.process:
                self.process.terminate()
                self.process.wait(timeout=3)  # 等待最多3秒
                if self.process.poll() is None:  # 如果进程还在运行
                    self.process.kill()  # 强制结束
        except Exception as e:
            logging.error(f"停止进程错误: {str(e)}")
            logging.error(traceback.format_exc())


class PDFCard(QtWidgets.QWidget, Ui_Form):
    deleted = QtCore.pyqtSignal(str)  # 信号：删除PDF时发出
    
    def __init__(self, pdf_path):
        super().__init__()
        self.setupUi(self)
        self.pdf_path = pdf_path
        self.pdf_name = os.path.basename(pdf_path)
        
        # 将 PDF 名称标签设置为可点击的链接样式
        self.pdfNameLabel.setText(f'<a href="{pdf_path}" style="color: blue; text-decoration: none;">{self.pdf_name}</a>')
        self.pdfNameLabel.setOpenExternalLinks(False)  # 禁用默认的链接处理
        self.pdfNameLabel.setTextInteractionFlags(QtCore.Qt.LinksAccessibleByMouse)
        self.pdfNameLabel.linkActivated.connect(self.open_pdf)
        
        # 加载第一页预览
        self.load_preview()
        
        # 加载JSON数据
        self.load_json_data()
        
        # 连接信号
        self.deletePDF.clicked.connect(self.on_delete)
        self.tocStartSpinBox.valueChanged.connect(self.save_json_data)
        self.tocEndSpinBox.valueChanged.connect(self.save_json_data)
        self.contentStartSpinBox.valueChanged.connect(self.save_json_data)

    def open_pdf(self):
        """使用系统默认程序打开PDF"""
        if sys.platform == 'win32':
            os.startfile(self.pdf_path)
        elif sys.platform == 'darwin':  # macOS
            subprocess.call(('open', self.pdf_path))
        else:  # linux variants
            subprocess.call(('xdg-open', self.pdf_path))
        
    def load_preview(self):
        try:
            # 转换PDF第一页为图像
            pages = convert_from_path(self.pdf_path, first_page=1, last_page=1, dpi=72)
            if pages:
                # 获取第一页
                page = pages[0]
                # 调整大小为 100x140
                img = page.resize((100, 140))
                # 转换为QPixmap
                qimg = QtGui.QImage(img.tobytes(), img.width, img.height, QtGui.QImage.Format_RGB888)
                pixmap = QtGui.QPixmap.fromImage(qimg)
                
                # 创建场景和添加图片
                scene = QtWidgets.QGraphicsScene()
                scene.addPixmap(pixmap)
                self.graphicsView.setScene(scene)
        except Exception as e:
            print(f"加载预览图失败: {e}")

    def load_json_data(self):
        json_path = os.path.splitext(self.pdf_path)[0] + '.json'
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.tocStartSpinBox.setValue(data.get('toc_start', 1))
                    self.tocEndSpinBox.setValue(data.get('toc_end', 1))
                    self.contentStartSpinBox.setValue(data.get('content_start', 1))
            except Exception as e:
                print(f"加载JSON数据失败: {e}")

    def save_json_data(self):
        json_path = os.path.splitext(self.pdf_path)[0] + '.json'
        data = {
            'toc_start': self.tocStartSpinBox.value(),
            'toc_end': self.tocEndSpinBox.value(),
            'content_start': self.contentStartSpinBox.value()
        }
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存JSON数据失败: {e}")

    def on_delete(self):
        # 添加确认对话框
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText(f"确定要删除文件 {self.pdf_name} 吗？")
        msg.setInformativeText("此操作不可撤销。")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        
        if msg.exec_() == QMessageBox.Yes:
            self.deleted.emit(self.pdf_path)

class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self):
        try:
            super().__init__()
            self.setupUi(self)
        
            # 初始化PDF文件夹
            self.pdf_dir = os.path.join("data", "input_pdf")
            os.makedirs(self.pdf_dir, exist_ok=True)
            
            # 设置滚动区域的布局
            self.scroll_layout = QVBoxLayout(self.scrollAreaWidgetContents)
            self.scroll_layout.setAlignment(QtCore.Qt.AlignTop)
            
            # 连接信号
            self.pushButton_5.clicked.connect(self.add_pdfs)  # 添加PDF文件
            self.pushButton_3.clicked.connect(self.run_pic_mark)  # 标记目录版面
            self.pushButton_6.clicked.connect(self.run_ocr_process)  # OCR流程
            self.pushButton_2.clicked.connect(self.run_confirm_content)  # 处理错误数据
            self.pushButton.clicked.connect(self.run_process_pdf)  # 目录挂入PDF
            
            # 初始加载已有PDF
            self.load_existing_pdfs()

            self.current_script_index = 0
            self.script_runner = None

        except Exception as e:
            logging.error(f"初始化错误: {str(e)}")
            logging.error(traceback.format_exc())
            raise


    def check_progress(self):
        """定时检查并更新进度"""
        if self.script_runner:
            latest_output = self.script_runner.get_latest_output()
            if latest_output is not None:
                # 确保输出不为空且不是空白字符
                if latest_output.strip():
                    self.label_3.setText(f"当前进度：{latest_output}")
                    print(f"Debug - 更新进度: {latest_output}")  # 用于调试

    def run_pic_mark(self):
        """运行image_marker.py"""
        try:
            # 检查是否有PDF文件
            if not os.path.exists(self.pdf_dir) or not any(f.lower().endswith('.pdf') for f in os.listdir(self.pdf_dir)):
                QMessageBox.warning(
                    self,
                    "警告",
                    "请先添加PDF文件！"
                )
                return

            # 检查脚本文件是否存在
            if not os.path.exists(os.path.join("mainprogress", "image_marker.py")):
                QMessageBox.critical(
                    self,
                    "错误",
                    "未找到image_marker.py文件！"
                )
                return

            # 使用Python解释器运行脚本
            python_executable = sys.executable
            subprocess.Popen([python_executable, os.path.join("mainprogress", "pdf_to_image.py")])
            time.sleep(1)
            subprocess.Popen([python_executable, os.path.join("mainprogress", "image_marker.py")])

        except Exception as e:
            QMessageBox.critical(
                self,
                "错误",
                f"运行image_marker.py失败：{str(e)}"
            )

    def generate_unique_filename(self, original_path):
        """生成唯一的文件名"""
        directory = os.path.dirname(original_path)
        filename = os.path.basename(original_path)
        name, ext = os.path.splitext(filename)
        counter = 1
        
        while os.path.exists(original_path):
            new_name = f"{name}_{counter}{ext}"
            original_path = os.path.join(directory, new_name)
            counter += 1
            
        return original_path
        
    def load_existing_pdfs(self):
        if os.path.exists(self.pdf_dir):
            for filename in os.listdir(self.pdf_dir):
                if filename.lower().endswith('.pdf'):
                    self.add_pdf_card(os.path.join(self.pdf_dir, filename))

    def add_pdfs(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择PDF文件",
            "",
            "PDF Files (*.pdf)"
        )
        
        if not files:
            return
            
        # 检查重复并准备文件映射
        duplicates = []
        file_mapping = {}  # 原始路径 -> 目标路径的映射
        
        for file_path in files:
            filename = os.path.basename(file_path)
            dest_path = os.path.join(self.pdf_dir, filename)
            
            if os.path.exists(dest_path):
                duplicates.append(filename)
                # 生成新的文件名
                dest_path = self.generate_unique_filename(dest_path)
            
            file_mapping[file_path] = dest_path
        
        # 如果有重复，询问用户
        if duplicates:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setText("发现重复文件:")
            msg.setInformativeText(
                "以下文件已存在:\n" + "\n".join(duplicates) + 
                "\n\n这些文件将被重命名后添加。是否继续？"
            )
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            if msg.exec_() != QMessageBox.Yes:
                return
        
        # 复制文件到目标目录
        for src_path, dest_path in file_mapping.items():
            try:
                shutil.copy2(src_path, dest_path)
                self.add_pdf_card(dest_path)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "错误",
                    f"复制文件失败: {os.path.basename(src_path)}\n{str(e)}"
                )

    def add_pdf_card(self, pdf_path):
        card = PDFCard(pdf_path)
        card.deleted.connect(self.remove_pdf)
        self.scroll_layout.addWidget(card)

    def remove_pdf(self, pdf_path):
        try:
            os.remove(pdf_path)
            # 删除对应的JSON文件
            json_path = os.path.splitext(pdf_path)[0] + '.json'
            if os.path.exists(json_path):
                os.remove(json_path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "错误",
                f"删除文件失败: {str(e)}"
            )
            return

        # 从界面移除卡片
        for i in range(self.scroll_layout.count()):
            widget = self.scroll_layout.itemAt(i).widget()
            if isinstance(widget, PDFCard) and widget.pdf_path == pdf_path:
                widget.deleteLater()
                break

    def run_script_with_output(self, script_name, status_text):
        """运行脚本并更新状态"""
        try:
            # 更新当前进行的状态
            self.label_2.setText(status_text)
            
            # 运行脚本并捕获输出
            process = subprocess.Popen(
                [sys.executable, os.path.join("mainprogress", script_name)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            # 读取输出并更新进度文本
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    self.label_3.setText(f"当前进度：{output.strip()}")
                    QtWidgets.QApplication.processEvents()  # 保持UI响应
                    
            return process.poll() == 0  # 返回是否成功执行
            
        except Exception as e:
            self.label_3.setText(f"当前进度：错误 - {str(e)}")
            return False
    def update_progress(self, text):
        self.label_3.setText(f"当前进度：{text}")

    def handle_script_finished(self, success):
        if success:
            self.current_script_index += 1
            self.run_next_script()
        else:
            self.update_timer.stop()
            self.pushButton_6.setEnabled(True)  # 出错时重新启用OCR按钮
            QMessageBox.critical(
                self,
                "错误",
                f"执行{self.scripts_and_status[self.current_script_index][0]}时出错"
            )


    def run_ocr_process(self):
        """执行OCR处理流程"""
        selected_service = self.service_select.currentText()
        
        ocr_script = "ocr_azure.py" if selected_service == "Azure" else "ocr_aliyun.py"
        
        self.scripts_and_status = [
            ("image_preprocessor.py", "当前进行：图像文件切分（1/7）"),
            (ocr_script, "当前进行：执行 OCR 处理（2/7）"),
            ("ocr_processor.py", "当前进行：处理 OCR 结果（3/7）"),
            ("text_matcher.py", "当前进行：匹配 OCR 结果（4/7）"),
            ("content_preprocessor.py", "当前进行：JSON 文件切分（5/7）"),
            ("llm_handler.py", "当前进行：JSON 文件处理（6/7）"),
            ("result_merger.py", "当前进行：JSON 文件合并（7/7）")
        ]
        
        self.pushButton_6.setEnabled(False)  # 禁用按钮
        self.label_3.setText("当前进度：")
        self.current_script_index = 0
        self.run_next_script()

    def run_next_script(self):
        try:
            if self.current_script_index >= len(self.scripts_and_status):
                self.finish_process()
                return
                
            script, status = self.scripts_and_status[self.current_script_index]
            script_path = os.path.join("mainprogress", script)
            
            if not os.path.exists(script_path):
                self.handle_error(f"未找到脚本文件：{script}")
                return
                
            self.label_2.setText(status)
            
            self.script_runner = ScriptRunner(script)
            self.script_runner.progress.connect(self.update_progress)
            self.script_runner.finished.connect(self.handle_script_finished)
            self.script_runner.error.connect(self.handle_error)
            self.script_runner.start()
            
        except Exception as e:
            logging.error(f"运行脚本错误: {str(e)}")
            logging.error(traceback.format_exc())
            self.handle_error(str(e))
   
    def closeEvent(self, event):
        """窗口关闭事件"""
        try:
            if self.script_runner and self.script_runner.isRunning():
                self.script_runner.stop()
                self.script_runner.wait()
            event.accept()
        except Exception as e:
            logging.error(f"关闭窗口错误: {str(e)}")
            logging.error(traceback.format_exc())
            event.accept()

    def handle_error(self, error_msg):
        """统一错误处理"""
        logging.error(f"错误: {error_msg}")
        self.pushButton_6.setEnabled(True)
        QMessageBox.critical(self, "错误", error_msg)

    def finish_process(self):
        """完成处理"""
        try:
            self.label_2.setText("当前进行：（已完成）")
            self.label_3.setText("当前进度：处理完成")
            self.pushButton_6.setEnabled(True)
            QMessageBox.information(self, "完成", "OCR处理流程已完成")
        except Exception as e:
            logging.error(f"完成处理错误: {str(e)}")
            logging.error(traceback.format_exc())

    def run_confirm_content(self):
        """运行确认内容脚本"""
        script_path = os.path.join("mainprogress", "content_validator.py")
        if not os.path.exists(script_path):
            QMessageBox.critical(self, "错误", "未找到content_validator.py文件")
            return
            
        try:
            subprocess.Popen([sys.executable, script_path])
        except Exception as e:
            QMessageBox.critical(self, "错误", f"运行content_validator.py失败：{str(e)}")
    
    def update_progress(self, text):
        """更新进度显示"""
        self.label_3.setText(f"当前进度：{text}")

    def handle_script_finished(self, success):
        if success:
            self.current_script_index += 1
            self.run_next_script()
        else:
            self.pushButton_6.setEnabled(True)
            QMessageBox.critical(
                self,
                "错误",
                f"执行{self.scripts_and_status[self.current_script_index][0]}时出错"
            )

    def run_process_pdf(self):
        """运行PDF处理脚本"""
        script_path = os.path.join("mainprogress", "pdf_generator.py")
        if not os.path.exists(script_path):
            QMessageBox.critical(self, "错误", "未找到pdf_generator.py文件")
            return
            
        try:
            subprocess.Popen([sys.executable, script_path])
        except Exception as e:
            QMessageBox.critical(self, "错误", f"运行pdf_generator.py失败：{str(e)}")

def exception_hook(exctype, value, traceback):
    logging.error('未捕获的异常:', exc_info=(exctype, value, traceback))
    sys.__excepthook__(exctype, value, traceback)  # 调用默认的异常处理

sys.excepthook = exception_hook

if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        logging.error(f"程序启动错误: {str(e)}")
        logging.error(traceback.format_exc())