import os
import json
import shutil
import subprocess
import time
import sys
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QVBoxLayout, QWidget
from mainWindow import Ui_MainWindow
from pdfCard import Ui_Form
from pdf2image import convert_from_path

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
        super().__init__()
        self.setupUi(self)
        
        # 初始化PDF文件夹
        self.pdf_dir = "0_originPDF"
        os.makedirs(self.pdf_dir, exist_ok=True)
        
        # 设置滚动区域的布局
        self.scroll_layout = QVBoxLayout(self.scrollAreaWidgetContents)
        self.scroll_layout.setAlignment(QtCore.Qt.AlignTop)
        
        # 连接信号
        self.pushButton_5.clicked.connect(self.add_pdfs)
        # 连接第二步按钮的点击事件
        self.pushButton_3.clicked.connect(self.run_pic_mark)
        
        # 初始加载已有PDF
        self.load_existing_pdfs()

    def run_pic_mark(self):
        """运行1_picMark.py"""
        try:
            # 检查是否有PDF文件
            if not os.path.exists(self.pdf_dir) or not any(f.lower().endswith('.pdf') for f in os.listdir(self.pdf_dir)):
                QMessageBox.warning(
                    self,
                    "警告",
                    "请先添加PDF文件！"
                )
                return

            # 检查1_picMark.py是否存在
            if not os.path.exists("1_picMark.py"):
                QMessageBox.critical(
                    self,
                    "错误",
                    "未找到1_picMark.py文件！"
                )
                return

            # 使用Python解释器运行1_picMark.py
            python_executable = sys.executable
            subprocess.Popen([python_executable, "0_pdf2jpg.py"])
            time.sleep(1)
            subprocess.Popen([python_executable, "1_picMark.py"])

        except Exception as e:
            QMessageBox.critical(
                self,
                "错误",
                f"运行1_picMark.py失败：{str(e)}"
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

if __name__ == '__main__':
    import sys
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())