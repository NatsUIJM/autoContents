import os
import json
import shutil
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtGui import QPixmap, QImage
from confirmWindow import Ui_MainWindow
import glob
from pathlib import Path

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
        self.current_image_index = 0
        self.json_files = []
        self.current_file_index = 0
        
        # 保存所有待处理任务的列表
        self.all_tasks = []
        self.current_task_index = -1
        
        # 设置信号连接
        self.ui.prevItemButton.clicked.connect(self.prev_item)
        self.ui.nextItemButton.clicked.connect(self.next_item)
        self.ui.prevPageButton.clicked.connect(self.prev_page)
        self.ui.nextPageButton.clicked.connect(self.next_page)
        
        # 初始化文件处理
        self.process_files()
        
    def process_files(self):
        source_dir = Path("5_processedContentInfo")
        target_dir = Path("6_confirmedContentInfo")
        
        if not target_dir.exists():
            target_dir.mkdir(parents=True)
            
        # 先确保文件都复制到了目标文件夹
        json_files = sorted(source_dir.glob("*.json"))
        for source_file in json_files:
            target_file = target_dir / source_file.name
            if not target_file.exists():
                shutil.copy2(source_file, target_file)
        
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
        
    def load_current_item(self):
        if not self.current_json_data:
            return
            
        item = self.current_json_data['items'][self.current_item_index]
        
        # 更新UI
        self.ui.currentTitleLabel.setText(f"{item['text']}")
        self.ui.pageConfirmLineEdit.setText(str(item['number']) if item['number'] is not None else '')
        self.ui.progressLabel.setText(f"处理进度：{self.current_task_index + 1}/{len(self.all_tasks)}")
        
        # 加载相关图片
        self.load_images()
        
    def load_images(self):
        if not self.current_json_path:
            return
            
        textbook_name = self.current_json_path.stem.replace('_final', '')
        
        image_dir = Path("1_picMark/inputPic")
        image_pattern = f"{textbook_name}_page_*.jpg"
        self.current_images = sorted(
            image_dir.glob(image_pattern),
            key=lambda x: int(x.stem.split('_')[-1])
        )
        
        self.current_image_index = 0
        self.display_current_image()
        
    def display_current_image(self):
        if not self.current_images:
            return
            
        if 0 <= self.current_image_index < len(self.current_images):
            image_path = str(self.current_images[self.current_image_index])
            pixmap = QPixmap(image_path)
            scaled_pixmap = pixmap.scaledToHeight(875, QtCore.Qt.SmoothTransformation)
            scene = QtWidgets.QGraphicsScene()
            scene.addPixmap(scaled_pixmap)
            self.ui.imageView.setScene(scene)
        
    def save_current_item(self):
        if not self.current_json_data or self.current_item_index < 0:
            return
            
        # 获取页码
        number_text = self.ui.pageConfirmLineEdit.text().strip()
        number = int(number_text) if number_text.isdigit() else None
        
        # 获取标题
        text = self.ui.currentTitleLabel.text().strip()
        
        # 更新数据
        self.current_json_data['items'][self.current_item_index]['number'] = number
        self.current_json_data['items'][self.current_item_index]['text'] = text
        
        # 保存到文件
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
        
    def prev_page(self):
        if self.current_images and self.current_image_index > 0:
            self.current_image_index -= 1
            self.display_current_image()
            
    def next_page(self):
        if self.current_images and self.current_image_index < len(self.current_images) - 1:
            self.current_image_index += 1
            self.display_current_image()

def main():
    app = QtWidgets.QApplication([])
    window = ContentConfirmWindow()
    window.show()
    app.exec_()

if __name__ == '__main__':
    main()