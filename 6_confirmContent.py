import sys
import os
import json
import shutil
from typing import List, Dict, Tuple
from PyQt5.QtWidgets import QApplication, QMainWindow, QGraphicsScene
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import Qt, QTimer
from confirmWindow import Ui_MainWindow

class DataManager:
    def __init__(self):
        self.source_dir = "5_processedContentInfo"
        self.target_dir = "6_confirmedContentInfo"
        self.items = []  # 所有需要确认的项目
        self.current_index = 0
        self.load_all_items()

    def load_all_items(self):
        """加载所有需要确认的项目"""
        self.items = []
        # 遍历source_dir中的所有JSON文件
        for filename in os.listdir(self.source_dir):
            if not filename.endswith('.json'):
                continue
                
            filepath = os.path.join(self.source_dir, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 筛选未确认的项目，并添加源文件信息
                for item in data['items']:
                    if item.get('confirmed') == False:
                        item['source_file'] = filename
                        self.items.append(item)

    def get_current_item(self) -> Dict:
        """获取当前项目"""
        if 0 <= self.current_index < len(self.items):
            return self.items[self.current_index]
        return None

    def get_image_files(self, item: Dict) -> List[str]:
        """获取当前项目对应的图片文件列表"""
        source_file = item['source_file']
        book_name = source_file.replace('_processed.json', '')
        
        image_files = []
        current_dir = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.join(current_dir, "1_picMark", "inputPic")
        
        print(f"Looking for images for book: {book_name}")
        
        # 收集所有匹配的文件
        matching_files = []
        for file in os.listdir(base_path):
            if file.startswith(f"{book_name}_page_") and file.endswith(".jpg"):
                try:
                    # 提取页码
                    page_num = int(file.replace(f"{book_name}_page_", "").replace(".jpg", ""))
                    matching_files.append((page_num, os.path.join(base_path, file)))
                except ValueError:
                    print(f"Skipping file with invalid page number: {file}")
        
        # 按页码排序
        matching_files.sort(key=lambda x: x[0])
        
        # 提取排序后的文件路径
        image_files = [file_path for _, file_path in matching_files]
        
        print("Found files in order:")
        for page_num, file_path in matching_files:
            print(f"  Page {page_num}: {file_path}")
        
        return image_files

    def save_current_item(self, new_page_number: int):
        """保存当前项目"""
        current_item = self.get_current_item()
        if not current_item:
            return

        source_filename = current_item['source_file']
        target_filename = os.path.join(self.target_dir, source_filename)
        
        # 如果目标文件不存在，从源文件复制
        if not os.path.exists(target_filename):
            source_path = os.path.join(self.source_dir, source_filename)
            os.makedirs(self.target_dir, exist_ok=True)
            shutil.copy2(source_path, target_filename)

        # 读取目标文件
        with open(target_filename, 'r', encoding='utf-8') as f:
            target_data = json.load(f)

        # 更新对应项目
        for item in target_data['items']:
            if (item['text'] == current_item['text'] and 
                item['level'] == current_item['level']):
                item['number'] = new_page_number
                item['confirmed'] = True
                break

        # 保存更新后的文件
        with open(target_filename, 'w', encoding='utf-8') as f:
            json.dump(target_data, f, ensure_ascii=False, indent=2)

    def move_to_next(self) -> bool:
        """移动到下一项"""
        if self.current_index < len(self.items) - 1:
            self.current_index += 1
            return True
        return False

    def move_to_prev(self) -> bool:
        """移动到上一项"""
        if self.current_index > 0:
            self.current_index -= 1
            return True
        return False

    def get_progress(self) -> Tuple[int, int]:
        """获取当前进度"""
        return self.current_index + 1, len(self.items)

class ConfirmWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        
        # 初始化场景和视图
        self.scene = QGraphicsScene()
        self.imageView.setScene(self.scene)
        
        self.data_manager = DataManager()
        self.current_images = []
        self.current_image_index = 0
        
        # 设置信号连接
        self.prevPageButton.clicked.connect(self.on_prev_page)
        self.nextPageButton.clicked.connect(self.on_next_page)
        self.prevItemButton.clicked.connect(self.on_prev_item)
        self.nextItemButton.clicked.connect(self.on_next_item)
        
        # 检查是否有数据需要处理
        if len(self.data_manager.items) == 0:
            print("No items to process")
            self.close()
            return
            
        # 初始加载数据
        self.load_current_item()
        self.update_next_button_state()

    def update_next_button_state(self):
        """更新下一条按钮的状态"""
        current, total = self.data_manager.get_progress()
        if current == total:  # 最后一条
            self.nextItemButton.setText("完成")
        else:
            self.nextItemButton.setText("下一条")

    def on_next_item(self):
        """下一条按钮点击处理"""
        self.save_current_item()
        current, total = self.data_manager.get_progress()
        
        if current == total:  # 最后一条
            print("Processing completed")
            self.close()  # 关闭程序
        elif self.data_manager.move_to_next():
            self.load_current_item()
            self.update_next_button_state()

    def closeEvent(self, event):
        """窗口关闭事件处理"""
        self.save_current_item()  # 保存最后的更改
        event.accept()

    def showEvent(self, event):
        """窗口显示事件"""
        super().showEvent(event)
        # 确保图片正确显示
        QTimer.singleShot(100, self.initial_display)

    def initial_display(self):
        """初始显示"""
        if self.current_images:
            self.imageView.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            print("Initial display completed")

    def resizeEvent(self, event):
        """窗口大小改变事件"""
        super().resizeEvent(event)
        if self.current_images:
            self.imageView.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def load_current_item(self):
        """加载当前项目"""
        item = self.data_manager.get_current_item()
        if not item:
            print("No current item found")
            return

        # 更新标题
        self.currentTitleLabel.setText(f"当前标题：{item['text']}")
        print(f"Loading item: {item['text']}")
        
        # 更新页码
        self.pageConfirmLineEdit.setText(str(item['number']))
        
        # 更新进度
        current, total = self.data_manager.get_progress()
        self.progressLabel.setText(f"处理进度：第 {current} 条，共 {total} 条")
        
        # 加载图片
        self.current_images = self.data_manager.get_image_files(item)
        print(f"Found images: {self.current_images}")
        self.current_image_index = 0
        self.display_current_image()

    def display_current_image(self):
        """显示当前图片"""
        if not self.current_images:
            print("No images available")
            return
            
        if self.current_image_index >= len(self.current_images):
            print(f"Invalid image index: {self.current_image_index}")
            return

        image_path = self.current_images[self.current_image_index]
        print(f"Displaying image: {image_path}")
        
        if not os.path.exists(image_path):
            print(f"Image file not found: {image_path}")
            return

        # 清除当前场景
        self.scene.clear()
        
        # 加载图片
        image = QImage(image_path)
        if image.isNull():
            print(f"Failed to load image: {image_path}")
            return
            
        print(f"Original image size: {image.width()}x{image.height()}")
        
        # 等比缩放到高度875
        if image.height() > 875:
            image = image.scaledToHeight(875, Qt.SmoothTransformation)
            print(f"Scaled image size: {image.width()}x{image.height()}")
        
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            print("Failed to convert QImage to QPixmap")
            return
            
        # 添加到场景
        self.scene.addPixmap(pixmap)
        
        # 将 QRect 转换为 QRectF
        rect = pixmap.rect()
        self.scene.setSceneRect(rect.x(), rect.y(), rect.width(), rect.height())
        print(f"Scene rectangle set to: {rect.x()}, {rect.y()}, {rect.width()}, {rect.height()}")
        
        # 调整视图
        self.imageView.setScene(self.scene)
        self.imageView.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        print("Image display completed")

    def resizeEvent(self, event):
        """窗口大小改变时重新调整图片"""
        super().resizeEvent(event)
        if self.scene.items():
            self.imageView.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def save_current_item(self):
        """保存当前项目"""
        try:
            new_page_number = int(self.pageConfirmLineEdit.text())
            self.data_manager.save_current_item(new_page_number)
        except ValueError:
            pass  # 处理页码输入错误

    def on_prev_page(self):
        """上一页按钮点击处理"""
        if self.current_image_index > 0:
            self.current_image_index -= 1
            self.display_current_image()

    def on_next_page(self):
        """下一页按钮点击处理"""
        if self.current_image_index < len(self.current_images) - 1:
            self.current_image_index += 1
            self.display_current_image()

    def on_prev_item(self):
        """上一条按钮点击处理"""
        self.save_current_item()
        if self.data_manager.move_to_prev():
            self.load_current_item()

    def on_next_item(self):
        """下一条按钮点击处理"""
        self.save_current_item()
        if self.data_manager.move_to_next():
            self.load_current_item()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ConfirmWindow()
    window.show()
    sys.exit(app.exec_())