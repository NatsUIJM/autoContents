"""
文件名: content_validator.py (原名: 6_confirmContent.py)
功能: 内容确认GUI程序，用于验证和修正提取的内容
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import os
import json
import shutil
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtGui import QPixmap, QImage
from UI.confirmWindow import Ui_MainWindow
import glob
from pathlib import Path
from PIL import Image
import io
from config.paths import PathConfig

class ContentConfirmWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        
        # 初始化变量
        self.current_json_path = None
        self.current_json_data = None
        self.current_item_index = -1
        self.current_images = []
        self.json_files = []
        self.current_file_index = 0
        
        # 保存所有待处理任务的列表
        self.all_tasks = []
        self.current_task_index = -1
        
        # 设置按钮文本（添加快捷键提示）
        self.ui.prevItemButton.setText("上一条 (Shift+Enter)")
        self.ui.nextItemButton.setText("下一条 (Enter)")
        
        # 设置信号连接
        self.ui.prevItemButton.clicked.connect(self.prev_item)
        self.ui.nextItemButton.clicked.connect(self.next_item)
        
        # 设置快捷键
        self.next_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("Return"), self)
        self.next_shortcut.activated.connect(self.next_item)
        self.prev_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("Shift+Return"), self)
        self.prev_shortcut.activated.connect(self.prev_item)
        
        # 设置下一条按钮的激活样式
        self.ui.nextItemButton.setAutoDefault(True)
        self.ui.nextItemButton.setDefault(True)
        
        # 设置图片查看器为可滚动
        self.ui.imageView.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.ui.imageView.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        
        # 初始化文件处理
        self.process_files()

    def find_reference_files(self, book_name):
        """查找参考文件"""
        reference_dir = Path(PathConfig.CONTENT_VALIDATOR_INPUT_2)
        reference_files = []
        
        for file_path in reference_dir.glob("*.json"):
            file_name = file_path.name
            # 检查文件名是否以书本名开头
            if not file_name.startswith(book_name):
                continue
            # 检查书本名是否只出现一次
            if file_name.count(book_name) > 1:
                continue
            # 检查文件名是否包含"辅助"
            if "辅助" in file_name:
                continue
            reference_files.append(file_path)
            
        return reference_files
    def convert_number_field(self, target_file):
        """处理步骤1: 转换number字段的类型"""
        modified = False
        with open(target_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        for item in data['items']:
            if isinstance(item['number'], str):
                try:
                    # 尝试转换为整数
                    item['number'] = int(item['number'])
                    modified = True
                except ValueError:
                    # 如果转换失败，设置为null并取消确认状态
                    item['number'] = None
                    item['confirmed'] = False
                    modified = True
                    
        if modified:
            with open(target_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        
        return data if modified else None

    def auto_confirm_matching_items(self, target_file, target_data):
        """处理步骤2: 自动确认匹配的条目"""
        # 获取书本名（去除_final后缀）
        book_name = target_file.stem.replace('_final', '')
        
        # 查找参考文件
        reference_files = self.find_reference_files(book_name)
        
        # 从参考文件中读取所有条目
        reference_items = []
        for ref_file in reference_files:
            with open(ref_file, 'r', encoding='utf-8') as f:
                ref_data = json.load(f)
                reference_items.extend(ref_data['items'])
        
        # 处理每个未确认的条目
        modified = False
        for item in target_data['items']:
            if not item['confirmed']:
                # 在参考条目中查找匹配项
                for ref_item in reference_items:
                    if (item['text'] == ref_item['text'] and 
                        item['number'] is not None and
                        item['number'] == ref_item['number']):
                        item['confirmed'] = True
                        modified = True
                        break
        
        if modified:
            with open(target_file, 'w', encoding='utf-8') as f:
                json.dump(target_data, f, ensure_ascii=False, indent=2)
        
        return target_data if modified else None

    def fill_null_numbers(self, target_file, target_data):
        """处理步骤3: 填充null的number字段"""
        modified = False
        items = target_data['items']
        
        for i in range(len(items) - 1):
            if items[i]['number'] is None:
                items[i]['number'] = items[i + 1]['number']
                modified = True
        
        if modified:
            with open(target_file, 'w', encoding='utf-8') as f:
                json.dump(target_data, f, ensure_ascii=False, indent=2)
        
        return target_data if modified else None

    def preprocess_json_file(self, target_file):
        """按顺序执行所有预处理步骤"""
        # 步骤1: 转换number字段类型
        data = self.convert_number_field(target_file)
        if data is None:  # 如果没有修改，重新读取数据
            with open(target_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        
        # 步骤2: 自动确认匹配项
        data = self.auto_confirm_matching_items(target_file, data)
        if data is None:  # 如果没有修改，重新读取数据
            with open(target_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        
        # 步骤3: 填充null的number字段
        data = self.fill_null_numbers(target_file, data)        
    def process_files(self):
        source_dir = Path(PathConfig.CONTENT_VALIDATOR_INPUT)
        target_dir = Path(PathConfig.CONTENT_VALIDATOR_OUTPUT)
        
        # 确保输出目录存在
        os.makedirs(target_dir, exist_ok=True)
            
        # 先确保文件都复制到了目标文件夹并进行预处理
        json_files = sorted(source_dir.glob("*.json"))
        for source_file in json_files:
            target_file = target_dir / source_file.name
            if not target_file.exists():
                shutil.copy2(source_file, target_file)
                # 对新复制的文件进行预处理
                self.preprocess_json_file(target_file)
        
        # 只从目标文件夹加载任务
        self.all_tasks = []
        self.json_files = sorted(target_dir.glob("*.json"))
        
        # 构建任务序列
        for json_file in self.json_files:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                source_name = json_file.stem.replace('_final', '')
                for idx, item in enumerate(data['items']):
                    if not item['confirmed']:
                        self.all_tasks.append({
                            'file_path': json_file,
                            'item_index': idx,
                            'source': source_name,
                            'title': item['text']
                        })
        
        # 开始处理第一个任务
        if self.all_tasks:
            self.current_task_index = 0
            self.load_current_task()
            self.print_task_info()

    def concatenate_images(self, image_paths):
        """垂直连接所有图片"""
        images = [Image.open(str(path)) for path in image_paths]
        
        target_width = 775
        resized_images = []
        for img in images:
            ratio = target_width / img.width
            new_height = int(img.height * ratio)
            resized_img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
            resized_images.append(resized_img)
            
        total_height = sum(img.height for img in resized_images)
        combined_image = Image.new('RGB', (target_width, total_height))
        
        y_offset = 0
        for img in resized_images:
            combined_image.paste(img, (0, y_offset))
            y_offset += img.height
            
        with io.BytesIO() as bio:
            combined_image.save(bio, format='PNG')
            bytes_data = bio.getvalue()
            qimg = QImage.fromData(bytes_data)
            return QPixmap.fromImage(qimg)

    def load_current_task(self):
        if 0 <= self.current_task_index < len(self.all_tasks):
            task = self.all_tasks[self.current_task_index]
            self.current_json_path = task['file_path']
            with open(self.current_json_path, 'r', encoding='utf-8') as f:
                self.current_json_data = json.load(f)
            self.current_item_index = task['item_index']
            self.load_current_item()
            
    def print_task_info(self):
        print("\n任务序列:")
        for idx, task in enumerate(self.all_tasks):
            print(f"{idx + 1}. [{task['source']}]-[{task['title']}]")
        print(f"\n当前正在处理第 {self.current_task_index + 1} 个任务，共 {len(self.all_tasks)} 个任务")
        
        if self.current_task_index == len(self.all_tasks) - 1:
            self.ui.nextItemButton.setText("完成 (Enter)")
        else:
            self.ui.nextItemButton.setText("下一条 (Enter)")
            
    def load_current_item(self):
        if not self.current_json_data:
            return
            
        item = self.current_json_data['items'][self.current_item_index]
        
        self.ui.currentTitleLabel.setText(f"{item['text']}")
        self.ui.pageConfirmLineEdit.setText(str(item['number']) if item['number'] is not None else '')
        self.ui.progressLabel.setText(f"处理进度：{self.current_task_index + 1}/{len(self.all_tasks)}")
        
        self.ui.pageConfirmLineEdit.selectAll()
        
        need_refresh = True
        if self.current_task_index > 0:
            prev_task = self.all_tasks[self.current_task_index - 1]
            current_task = self.all_tasks[self.current_task_index]
            if prev_task['source'] == current_task['source']:
                need_refresh = False
                
        if need_refresh:
            self.load_images()
        
    def load_images(self):
        if not self.current_json_path:
            return
            
        textbook_name = self.current_json_path.stem.replace('_final', '')
        
        image_dir = Path(PathConfig.CONTENT_VALIDATOR_IMAGES)
        image_pattern = f"{textbook_name}_page_*.jpg"
        self.current_images = sorted(
            image_dir.glob(image_pattern),
            key=lambda x: int(x.stem.split('_')[-1])
        )
        
        self.display_current_image()
        
    def display_current_image(self):
        if not self.current_images:
            return
            
        combined_pixmap = self.concatenate_images(self.current_images)
        scene = QtWidgets.QGraphicsScene()
        scene.addPixmap(combined_pixmap)
        self.ui.imageView.setScene(scene)
        
        self.ui.imageView.verticalScrollBar().setValue(0)
        
    def save_current_item(self):
        if not self.current_json_data or self.current_item_index < 0:
            return
            
        number_text = self.ui.pageConfirmLineEdit.text().strip()
        number = int(number_text) if number_text.isdigit() else None
        
        text = self.ui.currentTitleLabel.text().strip()
        
        self.current_json_data['items'][self.current_item_index]['number'] = number
        self.current_json_data['items'][self.current_item_index]['text'] = text
        
        with open(self.current_json_path, 'w', encoding='utf-8') as f:
            json.dump(self.current_json_data, f, ensure_ascii=False, indent=2)
            
    def prev_item(self):
        self.save_current_item()
        if self.current_task_index > 0:
            self.current_task_index -= 1
            self.load_current_task()
            self.print_task_info()
        
    def next_item(self):
        self.save_current_item()
        if self.current_task_index < len(self.all_tasks) - 1:
            self.current_task_index += 1
            self.load_current_task()
            self.print_task_info()
        elif self.current_task_index == len(self.all_tasks) - 1:
            self.close()

def main():
    app = QtWidgets.QApplication([])
    window = ContentConfirmWindow()
    window.show()
    app.exec_()

if __name__ == '__main__':
    main()