import os
import json
import shutil
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtGui import QPixmap, QImage
from confirmWindow import Ui_MainWindow
import glob
from pathlib import Path
from PIL import Image
import io

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
        
        # 设置Enter键快捷键
        self.next_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("Return"), self)
        self.next_shortcut.activated.connect(self.next_item)
        
        # 设置Shift+Enter快捷键
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

    def concatenate_images(self, image_paths):
        """垂直连接所有图片"""
        images = [Image.open(str(path)) for path in image_paths]
        
        # 统一宽度为775像素
        target_width = 775
        resized_images = []
        for img in images:
            # 计算等比例缩放后的高度
            ratio = target_width / img.width
            new_height = int(img.height * ratio)
            resized_img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
            resized_images.append(resized_img)
            
        # 计算总高度
        total_height = sum(img.height for img in resized_images)
        
        # 创建新图片
        combined_image = Image.new('RGB', (target_width, total_height))
        
        # 垂直拼接图片
        y_offset = 0
        for img in resized_images:
            combined_image.paste(img, (0, y_offset))
            y_offset += img.height
            
        # 转换为QPixmap
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
        
        # 更新"下一条"按钮文本
        if self.current_task_index == len(self.all_tasks) - 1:
            self.ui.nextItemButton.setText("完成 (Enter)")
        else:
            self.ui.nextItemButton.setText("下一条 (Enter)")
            
    def load_current_item(self):
        if not self.current_json_data:
            return
            
        item = self.current_json_data['items'][self.current_item_index]
        
        # 更新UI
        self.ui.currentTitleLabel.setText(f"{item['text']}")
        self.ui.pageConfirmLineEdit.setText(str(item['number']) if item['number'] is not None else '')
        self.ui.progressLabel.setText(f"处理进度：{self.current_task_index + 1}/{len(self.all_tasks)}")
        
        # 全选页码确认框中的内容
        self.ui.pageConfirmLineEdit.selectAll()
        
        # 判断是否需要刷新图片
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
        
        image_dir = Path("6_1_cutPic")
        image_pattern = f"{textbook_name}_page_*.jpg"
        self.current_images = sorted(
            image_dir.glob(image_pattern),
            key=lambda x: int(x.stem.split('_')[-1])
        )
        
        self.display_current_image()
        
    def display_current_image(self):
        if not self.current_images:
            return
            
        # 连接所有图片并显示
        combined_pixmap = self.concatenate_images(self.current_images)
        scene = QtWidgets.QGraphicsScene()
        scene.addPixmap(combined_pixmap)
        self.ui.imageView.setScene(scene)
        
        # 重置滚动条位置
        self.ui.imageView.verticalScrollBar().setValue(0)
        
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
        elif self.current_task_index == len(self.all_tasks) - 1:
            # 如果是最后一个任务，保存后退出程序
            self.close()

def main():
    app = QtWidgets.QApplication([])
    window = ContentConfirmWindow()
    window.show()
    app.exec_()

if __name__ == '__main__':
    main()