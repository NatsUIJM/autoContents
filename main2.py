import os
import sys
import json
import shutil
import subprocess
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QVBoxLayout, QWidget
from PyQt5.QtCore import QThread, pyqtSignal
from UI.mainWindow_2 import Ui_MainWindow
from UI.pdfCard import Ui_Form
from pdf2image import convert_from_path
import logging
from queue import Queue
import io
import traceback

# ScriptRunner 类
class ScriptRunner(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)
    
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
                if self.process is None:
                    break
                    
                line = self.process.stdout.readline()
                if not line and self.process.poll() is not None:
                    break
                line = line.strip()
                if line:
                    self.progress.emit(line)
            
            if self.process and self.process.returncode is not None:
                success = self.process.returncode == 0
                self.finished.emit(success)
            
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit(False)
    
    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()

# PrintRedirector 类
class PrintRedirector(io.StringIO):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def write(self, text):
        self.text_widget.appendPlainText(text.rstrip())

    def flush(self):
        pass

# PDFCard 类
class PDFCard(QtWidgets.QWidget, Ui_Form):
    deleted = QtCore.pyqtSignal(str)
    
    def __init__(self, pdf_path):
        super().__init__()
        self.setupUi(self)
        self.pdf_path = pdf_path
        self.pdf_name = os.path.basename(pdf_path)
        
        self.pdfNameLabel.setText(f'<a href="{pdf_path}" style="color: blue; text-decoration: none;">{self.pdf_name}</a>')
        self.pdfNameLabel.setOpenExternalLinks(False)
        self.pdfNameLabel.setTextInteractionFlags(QtCore.Qt.LinksAccessibleByMouse)
        self.pdfNameLabel.linkActivated.connect(self.open_pdf)
        
        self.load_preview()
        self.load_json_data()
        
        self.deletePDF.clicked.connect(self.on_delete)
        self.deletePDF_2.clicked.connect(self.open_pdf)
        self.tocStartSpinBox.valueChanged.connect(self.save_json_data)
        self.tocEndSpinBox.valueChanged.connect(self.save_json_data)
        self.contentStartSpinBox.valueChanged.connect(self.save_json_data)

    def open_pdf(self):
        if sys.platform == 'win32':
            os.startfile(self.pdf_path)
        elif sys.platform == 'darwin':
            subprocess.call(('open', self.pdf_path))
        else:
            subprocess.call(('xdg-open', self.pdf_path))
        
    def load_preview(self):
        try:
            pages = convert_from_path(self.pdf_path, first_page=1, last_page=1, dpi=72)
            if pages:
                page = pages[0]
                img = page.resize((100, 140))
                bytes_img = io.BytesIO()
                img.save(bytes_img, format='PNG')
                qimg = QtGui.QImage()
                qimg.loadFromData(bytes_img.getvalue())
                
                scene = QtWidgets.QGraphicsScene()
                scene.addPixmap(QtGui.QPixmap.fromImage(qimg))
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
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText(f"确定要删除文件 {self.pdf_name} 吗？")
        msg.setInformativeText("此操作不可撤销。")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        
        if msg.exec_() == QMessageBox.Yes:
            self.deleted.emit(self.pdf_path)

# MainWindow 类
class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        
        self.pdf_dir = os.path.join("data", "input_pdf")
        os.makedirs(self.pdf_dir, exist_ok=True)
        self.script_runner = None
        self.current_script_index = 0
        
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setAlignment(QtCore.Qt.AlignTop)
        self.scrollArea.setWidget(self.scroll_widget)
        
        # 连接按钮信号
        self.add_pdf.clicked.connect(self.add_pdfs)
        self.start_process.clicked.connect(self.start_execution)
        
        # 设置初始状态
        self.load_existing_pdfs()
        self.update_pdf_count()
        
        # 设置日志重定向
        self.log_redirector = PrintRedirector(self.log)
        sys.stdout = self.log_redirector

    def update_pdf_count(self):
        count = self.scroll_layout.count()
        self.num_of_pdf.setText(f"已选择 {count} 个文件")

    def load_existing_pdfs(self):
        if os.path.exists(self.pdf_dir):
            for filename in os.listdir(self.pdf_dir):
                if filename.lower().endswith('.pdf'):
                    self.add_pdf_card(os.path.join(self.pdf_dir, filename))

    def add_pdf_card(self, pdf_path):
        card = PDFCard(pdf_path)
        card.deleted.connect(self.remove_pdf)
        self.scroll_layout.addWidget(card)
        self.update_pdf_count()

    def add_pdfs(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择PDF文件",
            "",
            "PDF Files (*.pdf)"
        )
        
        if not files:
            return
            
        for file_path in files:
            filename = os.path.basename(file_path)
            dest_path = os.path.join(self.pdf_dir, filename)
            
            if os.path.exists(dest_path):
                new_filename = self.generate_unique_filename(filename)
                dest_path = os.path.join(self.pdf_dir, new_filename)
            
            try:
                shutil.copy2(file_path, dest_path)
                self.add_pdf_card(dest_path)
                print(f"已添加：{filename}")
            except Exception as e:
                print(f"添加失败：{filename} - {str(e)}")

    def remove_pdf(self, pdf_path):
        try:
            os.remove(pdf_path)
            json_path = os.path.splitext(pdf_path)[0] + '.json'
            if os.path.exists(json_path):
                os.remove(json_path)
                
            for i in range(self.scroll_layout.count()):
                widget = self.scroll_layout.itemAt(i).widget()
                if isinstance(widget, PDFCard) and widget.pdf_path == pdf_path:
                    widget.deleteLater()
                    break
                    
            self.update_pdf_count()
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "错误",
                f"删除文件失败: {str(e)}"
            )

    def generate_unique_filename(self, filename):
        name, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(os.path.join(self.pdf_dir, filename)):
            filename = f"{name}_{counter}{ext}"
            counter += 1
        return filename

    def reset_all_labels(self):
        labels = [
            self.pdf_to_image, self.ocr_and_projection, self.mark_colour,
            self.abcd_marker, self.image_marker, self.image_preprocessor,
            self.ocr, self.ocr_processor, self.text_matcher,
            self.content_preprocessor, self.llm_handler, self.result_merger,
            self.llm_level_adjuster, self.content_validator, self.pdf_generator
        ]
        for label in labels:
            label.setText(label.text().split(" ", 1)[1])

    def update_label_status(self, script_name, status):
        status_map = {
            'running': '⏳ ',
            'success': '✅ ',
            'error': '❌ '
        }
        
        label_map = {
            'pdf_to_image.py': self.pdf_to_image,
            'ocr_and_projection_azure.py': self.ocr_and_projection,
            'ocr_and_projection_aliyun.py': self.ocr_and_projection,
            'mark_colour.py': self.mark_colour,
            'abcd_marker.py': self.abcd_marker,
            'image_marker.py': self.image_marker,
            'image_preprocessor.py': self.image_preprocessor,
            'ocr_azure.py': self.ocr,
            'ocr_aliyun.py': self.ocr,
            'ocr_processor.py': self.ocr_processor,
            'text_matcher.py': self.text_matcher,
            'content_preprocessor.py': self.content_preprocessor,
            'llm_handler.py': self.llm_handler,
            'result_merger.py': self.result_merger,
            'llm_level_adjuster.py': self.llm_level_adjuster,
            'content_validator.py': self.content_validator,
            'pdf_generator.py': self.pdf_generator
        }
        
        if script_name in label_map:
            label = label_map[script_name]
            status_icon = status_map.get(status, '')
            original_text = label.text().split(" ", 1)[-1]
            label.setText(f"{status_icon}{original_text}")

    def start_execution(self):
        if not os.path.exists(self.pdf_dir) or not any(f.lower().endswith('.pdf') for f in os.listdir(self.pdf_dir)):
            QMessageBox.warning(self, "警告", "请先添加PDF文件！")
            return

        self.reset_all_labels()
        self.scripts = self.generate_script_sequence()
        self.current_script_index = 0
        self.start_process.setEnabled(False)
        self.add_pdf.setEnabled(False)
        self.run_next_script()

    def generate_script_sequence(self):
        service = self.service_select.currentText().lower()
        mode = self.AutoSelectBtn.currentText()  # 获取自动化模式选择
        
        base_sequence = [
            "pdf_to_image.py",
            f"ocr_and_projection_{service}.py",
            "mark_colour.py",
            "abcd_marker.py",
            "image_preprocessor.py",
            f"ocr_{service}.py",
            "ocr_processor.py",
            "text_matcher.py",
            "content_preprocessor.py",
            "llm_handler.py",
            "result_merger.py",
            "llm_level_adjuster.py"
        ]
        
        if mode == "半自动":
            # 在abcd_marker.py之后插入image_marker.py
            marker_index = base_sequence.index("abcd_marker.py") + 1
            base_sequence.insert(marker_index, "image_marker.py")
            
            # 在llm_level_adjuster.py之后插入content_validator.py
            base_sequence.append("content_validator.py")
        else:
            # 全自动模式使用content_validator_auto.py
            base_sequence.append("content_validator_auto.py")
        
        # 最后添加pdf生成脚本
        base_sequence.append("pdf_generator.py")
        
        return base_sequence

    def run_next_script(self):
        if self.current_script_index >= len(self.scripts):
            self.finish_execution()
            return
            
        script = self.scripts[self.current_script_index]
        script_path = os.path.join("mainprogress", script)
        
        if not os.path.exists(script_path):
            self.handle_error(f"未找到脚本文件：{script}")
            return
            
        print(f"执行脚本：{script}")
        self.update_label_status(script, 'running')
        
        self.script_runner = ScriptRunner(script)
        self.script_runner.progress.connect(self.update_progress)
        self.script_runner.finished.connect(self.handle_script_finished)
        self.script_runner.error.connect(self.handle_error)
        self.script_runner.start()

    def update_progress(self, text):
        print(text)

    def handle_script_finished(self, success):
        current_script = self.scripts[self.current_script_index]
        if success:
            self.update_label_status(current_script, 'success')
            self.current_script_index += 1
            self.run_next_script()
        else:
            self.update_label_status(current_script, 'error')
            self.handle_error(f"执行{current_script}时出错")

    def handle_error(self, error_msg):
        print(f"错误：{error_msg}")
        self.start_process.setEnabled(True)
        self.add_pdf.setEnabled(True)
        
        if self.current_script_index < len(self.scripts):
            current_script = self.scripts[self.current_script_index]
            self.update_label_status(current_script, 'error')
            
        QMessageBox.critical(self, "错误", error_msg)

    def finish_execution(self):
        print("所有脚本执行完成")
        self.start_process.setEnabled(True)
        self.add_pdf.setEnabled(True)
        QMessageBox.information(self, "完成", "所有处理已完成")

    def closeEvent(self, event):
        if self.script_runner and self.script_runner.isRunning():
            self.script_runner.stop()
            self.script_runner.wait()
        event.accept()

def main():
    app = QtWidgets.QApplication(sys.argv)
    
    # 设置应用程序样式
    app.setStyle("Fusion")
    
    # 创建浅色调色板
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(240, 240, 240))
    palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(0, 0, 0))
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(255, 255, 255))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(245, 245, 245))
    palette.setColor(QtGui.QPalette.Text, QtGui.QColor(0, 0, 0))
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(240, 240, 240))
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(0, 0, 0))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(42, 130, 218))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(255, 255, 255))
    
    # 应用调色板
    app.setPalette(palette)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()