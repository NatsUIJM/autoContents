import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
import sys
import os
import json
from PIL import Image
from PyQt5.QtWidgets import (QApplication, QMainWindow, QGraphicsScene, 
                            QGraphicsView, QGraphicsLineItem, QGraphicsEllipseItem)
from PyQt5.QtGui import QPixmap, QImage, QPen, QPainter
from PyQt5.QtCore import Qt, QPointF, QLineF, QRectF
from UI.markWindow import Ui_MainWindow
from config.paths import PathConfig

def natural_sort_key(s):
    import re
    # 提取文件名中的数字部分并转换为整数用于排序
    numbers = re.findall(r'\d+', s)
    if numbers:
        return int(numbers[0])
    return 0

class DraggableLine(QGraphicsLineItem):
    def __init__(self, x1, y1, x2, y2, is_vertical=False, parent=None):
        super().__init__(0, 0, x2-x1, y2-y1, parent)
        self.is_vertical = is_vertical
        self.setFlag(self.ItemIsMovable)
        self.setFlag(self.ItemSendsScenePositionChanges)
        self.setAcceptHoverEvents(True)  # 允许接收悬停事件
        self.setPen(QPen(Qt.red, 5))  # 默认红色
        self.main_window = None
        self.setPos(x1, y1)
        
    def hoverEnterEvent(self, event):
        # 根据线条方向设置不同的光标
        if self.is_vertical:
            self.setCursor(Qt.SizeHorCursor)  # 水平调整光标
        else:
            self.setCursor(Qt.SizeVerCursor)  # 垂直调整光标
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.ArrowCursor)  # 恢复默认光标
        super().hoverLeaveEvent(event)
        
    def mousePressEvent(self, event):
        # 在鼠标按下时也设置对应的光标
        if self.is_vertical:
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.SizeVerCursor)
        super().mousePressEvent(event)
        if self.main_window:
            print("\n拖动开始:")
            self.main_window.check_intersections()
    
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.main_window:
            print("\n拖动结束:")
            self.main_window.check_intersections()
        
    def mouseMoveEvent(self, event):
        orig_pos = event.lastScenePos()
        new_pos = event.scenePos()
        
        if self.is_vertical:
            dx = new_pos.x() - orig_pos.x()
            self.moveBy(dx, 0)
        else:
            dy = new_pos.y() - orig_pos.y()
            self.moveBy(0, dy)

class DraggableCircle(QGraphicsEllipseItem):
    def __init__(self, x, y, diameter, parent=None):
        super().__init__(0, 0, diameter, diameter, parent)
        self.setFlag(self.ItemIsMovable)
        self.setFlag(self.ItemSendsScenePositionChanges)
        self.setAcceptHoverEvents(True)  # 允许接收悬停事件
        self.setPen(QPen(Qt.green, 5))
        self.setPos(x - diameter/2, y - diameter/2)
        self.main_window = None
        
    def hoverEnterEvent(self, event):
        self.setCursor(Qt.SizeAllCursor)  # 设置为四向移动光标
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.ArrowCursor)  # 恢复默认光标
        super().hoverLeaveEvent(event)
        
    def mousePressEvent(self, event):
        self.setCursor(Qt.SizeAllCursor)  # 设置为四向移动光标
        super().mousePressEvent(event)
        if self.main_window:
            print("\n移动开始:")
            self.main_window.check_positions()
    
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.main_window:
            print("\n移动结束:")
            self.main_window.check_positions()

class CustomGraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.StrongFocus)  # 设置焦点策略
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        
    def focusInEvent(self, event):
        """视图获得焦点时被调用"""
        super().focusInEvent(event)
        self.viewport().update()  # 更新视图
        
class MainApplication(QMainWindow):
    def __init__(self):
        super().__init__()
        # 设置窗口相关属性
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)  # 添加置顶标志
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)  # 确保显示时激活窗口
        
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        
        # 设置焦点策略
        self.setFocusPolicy(Qt.StrongFocus)
        
        self.graphics_view = CustomGraphicsView()
        self.graphics_view.setFocusPolicy(Qt.StrongFocus)  # 设置视图的焦点策略
        
        layout_item = self.ui.verticalLayout.replaceWidget(
            self.ui.graphicsView, 
            self.graphics_view
        )
        if layout_item:
            layout_item.widget().deleteLater()
        
        self.current_page = 0
        self.image_files = []
        self.current_image = None
        self.scene = QGraphicsScene()
        self.graphics_view.setScene(self.scene)
        
        self.scene.setSceneRect(0, 0, 780, 850)
        
        self.lines = []
        self.green_line = None
        self.blue_lines = []  # 存储所有蓝线
        self.ban_symbols = []  # 存储禁止符号
        self.process_symbols = []  # 存储处理标记（红点）
        self.original_height = 0  # 添加原始高度属性
        self.setup_lines()
        
        self.ui.nextPageBtn.clicked.connect(self.next_page)
        self.ui.prevPageBtn.clicked.connect(self.prev_page)
        self.ui.addColumnBtn.clicked.connect(self.toggle_green_line)
        self.ui.addSectionBtn.clicked.connect(self.add_blue_line)
        self.ui.deleteSectionBtn.clicked.connect(self.remove_blue_line)
        self.ui.addBanBtn.clicked.connect(self.add_ban_symbol)
        self.ui.deleteBanBtn.clicked.connect(self.remove_ban_symbol)
        self.ui.addProcessBtn.clicked.connect(self.add_process_symbol)
        self.ui.deleteProcessBtn.clicked.connect(self.remove_process_symbol)
        
        self.init_application()
    
    def add_blue_line(self):
        # 创建新的蓝线（初始位置在中间位置）
        y_pos = 400 + len(self.blue_lines) * 50  # 每条新线都比上一条低50像素
        if y_pos > 800:  # 如果位置太低，重置到上面
            y_pos = 400
        
        blue_line = DraggableLine(0, y_pos, 780, y_pos, False)
        blue_line.setPen(QPen(Qt.blue, 5))  # 设置为蓝色
        blue_line.main_window = self
        self.scene.addItem(blue_line)
        self.blue_lines.append(blue_line)
        
        self.check_intersections()
    
    def remove_blue_line(self):
        if self.blue_lines:  # 如果有蓝线
            line = self.blue_lines.pop()  # 移除最后添加的一条
            self.scene.removeItem(line)
            self.check_intersections()
    
    def toggle_green_line(self):
        if self.green_line is None:
            self.green_line = DraggableLine(400, 0, 400, 850, True)
            self.green_line.setPen(QPen(Qt.green, 5))
            self.green_line.main_window = self
            self.scene.addItem(self.green_line)
            self.ui.addColumnBtn.setText("删除分栏标记")
        else:
            self.scene.removeItem(self.green_line)
            self.green_line = None
            self.ui.addColumnBtn.setText("添加分栏标记")
        
        self.check_intersections()
    
    def setup_lines(self):
        h1 = DraggableLine(0, 200, 780, 200, False)
        h2 = DraggableLine(0, 600, 780, 600, False)
        v1 = DraggableLine(200, 0, 200, 850, True)
        v2 = DraggableLine(600, 0, 600, 850, True)
        
        self.lines = [h1, h2, v1, v2]
        for line in self.lines:
            line.main_window = self
            self.scene.addItem(line)
    
    def find_intersection(self, h_line, v_line):
        h_pos = h_line.pos()
        v_pos = v_line.pos()
        
        x = v_pos.x()
        y = h_pos.y()
        return QPointF(x, y)
    
    def check_intersections(self):
        # 获取固定的红色竖线
        v_lines = [line for line in self.lines if line.is_vertical]
        v_lines.sort(key=lambda x: x.pos().x())
        
        # 获取固定的红色横线
        h_lines = [line for line in self.lines if not line.is_vertical]
        h_lines.sort(key=lambda x: x.pos().y())
        
        # 计算ABCD四个交点
        points = {
            'A': self.find_intersection(h_lines[0], v_lines[0]),
            'B': self.find_intersection(h_lines[0], v_lines[1]),
            'C': self.find_intersection(h_lines[1], v_lines[0]),
            'D': self.find_intersection(h_lines[1], v_lines[1])
        }
        
        # 如果绿线存在，计算EF交点
        if self.green_line:
            points['E'] = self.find_intersection(h_lines[0], self.green_line)
            points['F'] = self.find_intersection(h_lines[1], self.green_line)
        
        # 对所有蓝线，计算与红竖线和绿线的交点
        for i, blue_line in enumerate(self.blue_lines, 1):
            # 与红竖线的交点
            points[f'M{i}'] = self.find_intersection(blue_line, v_lines[0])
            points[f'N{i}'] = self.find_intersection(blue_line, v_lines[1])
            
            # 如果绿线存在，计算与绿线的交点
            if self.green_line:
                points[f'P{i}'] = self.find_intersection(blue_line, self.green_line)
        
        # 按字母顺序输出所有点的坐标
        for point_name in sorted(points.keys()):
            point = points[point_name]
            print(f"点{point_name}: ({point.x():.2f}, {point.y():.2f})")
        
        # 在输出所有点坐标后添加禁止符号位置的检查
        self.check_positions()
    
    def reset_drawing_area(self):
        # 移除除固定红线外的所有线条和标记
        for item in self.scene.items():
            if isinstance(item, (DraggableLine, DraggableCircle)):
                if item not in self.lines:  # 不移除固定的红线
                    self.scene.removeItem(item)
        
        # 重置绿线和蓝线列表
        self.green_line = None
        self.blue_lines = []
        self.ban_symbols = []
        self.process_symbols = []
        
        # 重置绿线按钮文本
        self.ui.addColumnBtn.setText("添加分栏标记")
        
        # 重置固定红线位置
        h1, h2, v1, v2 = self.lines
        h1.setPos(0, 200)
        h2.setPos(0, 600)
        v1.setPos(200, 0)
        v2.setPos(600, 0)

    def check_positions(self):
        for i, symbol in enumerate(self.ban_symbols, 1):
            center_x = symbol.pos().x() + symbol.rect().width()/2
            center_y = symbol.pos().y() + symbol.rect().height()/2
            print(f"点X{i}: ({center_x:.2f}, {center_y:.2f})")
        
        for i, symbol in enumerate(self.process_symbols, 1):
            center_x = symbol.pos().x() + symbol.rect().width()/2
            center_y = symbol.pos().y() + symbol.rect().height()/2
            print(f"点Y{i}: ({center_x:.2f}, {center_y:.2f})")
    
    def load_page_marks(self):
        current_image = self.image_files[self.current_page]
        base_name = os.path.splitext(current_image)[0]
        json_path = os.path.join(PathConfig.PICMARK_OUTPUT_DIR, f'{base_name}.json')
        
        if not os.path.exists(json_path):
            return
        
        # 读取JSON文件
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 计算缩放比例（从原始尺寸到显示尺寸）
        scale = 850 / data['original_height']
        points = data['points']
        
        # 重置绘图区域
        self.reset_drawing_area()
        
        # 设置红线位置
        h1, h2, v1, v2 = self.lines
        h1.setPos(0, points['A']['y'] * scale)
        h2.setPos(0, points['C']['y'] * scale)
        v1.setPos(points['A']['x'] * scale, 0)
        v2.setPos(points['B']['x'] * scale, 0)
        
        # 如果存在E和F点，添加绿线
        if 'E' in points and 'F' in points:
            x = points['E']['x'] * scale
            self.green_line = DraggableLine(x, 0, x, 850, True)
            self.green_line.setPen(QPen(Qt.green, 5))
            self.green_line.main_window = self
            self.scene.addItem(self.green_line)
            self.ui.addColumnBtn.setText("删除分栏标记")
        
        # 添加蓝线
        m_points = [(k, v) for k, v in points.items() if k.startswith('M')]
        for m_key, m_point in m_points:
            num = m_key[1:]  # 获取编号
            y = m_point['y'] * scale
            blue_line = DraggableLine(0, y, 780, y, False)
            blue_line.setPen(QPen(Qt.blue, 5))
            blue_line.main_window = self
            self.scene.addItem(blue_line)
            self.blue_lines.append(blue_line)
        
        # 添加禁止标记
        x_points = [(k, v) for k, v in points.items() if k.startswith('X')]
        for _, x_point in x_points:
            x = x_point['x'] * scale
            y = x_point['y'] * scale
            diameter = 10
            ban_symbol = DraggableCircle(x, y, diameter)
            ban_symbol.setPen(QPen(Qt.green, 5))  # 改为绿色
            ban_symbol.main_window = self
            self.scene.addItem(ban_symbol)
            self.ban_symbols.append(ban_symbol)

        # 添加处理标记
        y_points = [(k, v) for k, v in points.items() if k.startswith('Y')]
        for _, y_point in y_points:
            x = y_point['x'] * scale
            y = y_point['y'] * scale
            diameter = 10
            process_symbol = DraggableCircle(x, y, diameter)
            process_symbol.setPen(QPen(Qt.red, 5))
            process_symbol.main_window = self
            self.scene.addItem(process_symbol)
            self.process_symbols.append(process_symbol)

    def add_ban_symbol(self):
        y_pos = 400 + len(self.ban_symbols) * 50
        if y_pos > 800:
            y_pos = 400
        
        diameter = 10  # 线宽的2倍
        ban_symbol = DraggableCircle(400, y_pos, diameter)
        ban_symbol.setPen(QPen(Qt.green, 5))  # 改为绿色
        ban_symbol.main_window = self
        self.scene.addItem(ban_symbol)
        self.ban_symbols.append(ban_symbol)
        
        self.check_positions()
    
    def remove_ban_symbol(self):
        if self.ban_symbols:
            symbol = self.ban_symbols.pop()
            self.scene.removeItem(symbol)
            self.check_positions()
    
    def add_process_symbol(self):
        y_pos = 400 + len(self.process_symbols) * 50
        if y_pos > 800:
            y_pos = 400
        
        diameter = 10  # 线宽的2倍
        process_symbol = DraggableCircle(400, y_pos, diameter)
        process_symbol.setPen(QPen(Qt.red, 5))  # 设置为红色
        process_symbol.main_window = self
        self.scene.addItem(process_symbol)
        self.process_symbols.append(process_symbol)
        
        self.check_positions()

    def remove_process_symbol(self):
        if self.process_symbols:
            symbol = self.process_symbols.pop()
            self.scene.removeItem(symbol)
            self.check_positions()

    def init_application(self):
        # 确保输入输出目录存在
        if not os.path.exists(PathConfig.PICMARK_INPUT_DIR):
            os.makedirs(PathConfig.PICMARK_INPUT_DIR)
        if not os.path.exists(PathConfig.PICMARK_OUTPUT_DIR):
            os.makedirs(PathConfig.PICMARK_OUTPUT_DIR)
            
        valid_extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
        self.image_files = [f for f in os.listdir(PathConfig.PICMARK_INPUT_DIR) 
                        if f.lower().endswith(valid_extensions)]
        # 使用自然排序
        self.image_files.sort(key=natural_sort_key)
        
        if not self.image_files:
            self.ui.label.setText("处理进度：未找到图片文件")
            self.ui.nextPageBtn.setEnabled(False)
            self.ui.prevPageBtn.setEnabled(False)
            return
            
        self.load_current_image()
        self.update_progress_label()
        self.update_button_states()
        
    def load_current_image(self):
        if 0 <= self.current_page < len(self.image_files):
            image_path = os.path.join(PathConfig.PICMARK_INPUT_DIR, 
                                    self.image_files[self.current_page])            
            # 获取原始图片尺寸
            with Image.open(image_path) as img:
                _, self.original_height = img.size
            
            pixmap = QPixmap(image_path)
            
            target_height = 850
            scaled_width = int((target_height / pixmap.height()) * pixmap.width())
            scaled_pixmap = pixmap.scaled(scaled_width, target_height, 
                                        Qt.KeepAspectRatio, 
                                        Qt.SmoothTransformation)
            
            for item in self.scene.items():
                if isinstance(item, QGraphicsLineItem):
                    continue
                self.scene.removeItem(item)
            
            pixmap_item = self.scene.addPixmap(scaled_pixmap)
            pixmap_item.setZValue(-1)
            
            # 重置绘图区域并检查是否有已存在的标记
            self.reset_drawing_area()
            
            # 检查并加载已存在的标记
            current_image = self.image_files[self.current_page]
            base_name = os.path.splitext(current_image)[0]
            json_path = os.path.join(PathConfig.PICMARK_OUTPUT_DIR, f'{base_name}.json')
            
            if os.path.exists(json_path):
                self.load_page_marks()


    def showEvent(self, event):
        """窗口显示时被调用"""
        super().showEvent(event)
        self.activateWindow()  # 激活窗口
        self.raise_()  # 将窗口提升到最前
        
    def focusInEvent(self, event):
        """窗口获得焦点时被调用"""
        super().focusInEvent(event)
        self.graphics_view.setFocus()  # 确保图形视图获得焦点

    def update_progress_label(self):
        total_pages = len(self.image_files)
        current_page = self.current_page + 1
        self.ui.label.setText(f"处理进度：{current_page}/{total_pages}")
    
    def update_button_states(self):
        self.ui.prevPageBtn.setEnabled(self.current_page > 0)
        is_last_page = self.current_page == len(self.image_files) - 1
        self.ui.nextPageBtn.setText("完成" if is_last_page else "下一页")
    
    def collect_points_data(self):
        v_lines = [line for line in self.lines if line.is_vertical]
        h_lines = [line for line in self.lines if not line.is_vertical]
        v_lines.sort(key=lambda x: x.pos().x())
        h_lines.sort(key=lambda x: x.pos().y())
        
        points = {}
        
        # ABCD点
        points['A'] = {'x': round(self.find_intersection(h_lines[0], v_lines[0]).x(), 2),
                      'y': round(self.find_intersection(h_lines[0], v_lines[0]).y(), 2)}
        points['B'] = {'x': round(self.find_intersection(h_lines[0], v_lines[1]).x(), 2),
                      'y': round(self.find_intersection(h_lines[0], v_lines[1]).y(), 2)}
        points['C'] = {'x': round(self.find_intersection(h_lines[1], v_lines[0]).x(), 2),
                      'y': round(self.find_intersection(h_lines[1], v_lines[0]).y(), 2)}
        points['D'] = {'x': round(self.find_intersection(h_lines[1], v_lines[1]).x(), 2),
                      'y': round(self.find_intersection(h_lines[1], v_lines[1]).y(), 2)}
        
        # EF点（如果存在绿线）
        if self.green_line:
            points['E'] = {'x': round(self.find_intersection(h_lines[0], self.green_line).x(), 2),
                          'y': round(self.find_intersection(h_lines[0], self.green_line).y(), 2)}
            points['F'] = {'x': round(self.find_intersection(h_lines[1], self.green_line).x(), 2),
                          'y': round(self.find_intersection(h_lines[1], self.green_line).y(), 2)}
        
        # MNP点
        for i, blue_line in enumerate(self.blue_lines, 1):
            points[f'M{i}'] = {'x': round(self.find_intersection(blue_line, v_lines[0]).x(), 2),
                              'y': round(self.find_intersection(blue_line, v_lines[0]).y(), 2)}
            points[f'N{i}'] = {'x': round(self.find_intersection(blue_line, v_lines[1]).x(), 2),
                              'y': round(self.find_intersection(blue_line, v_lines[1]).y(), 2)}
            if self.green_line:
                points[f'P{i}'] = {'x': round(self.find_intersection(blue_line, self.green_line).x(), 2),
                                  'y': round(self.find_intersection(blue_line, self.green_line).y(), 2)}
        
        # X点（禁止符号）
        for i, symbol in enumerate(self.ban_symbols, 1):
            center_x = symbol.pos().x() + symbol.rect().width()/2
            center_y = symbol.pos().y() + symbol.rect().height()/2
            points[f'X{i}'] = {'x': round(center_x, 2), 'y': round(center_y, 2)}

        # Y点（处理标记）
        for i, symbol in enumerate(self.process_symbols, 1):
            center_x = symbol.pos().x() + symbol.rect().width()/2
            center_y = symbol.pos().y() + symbol.rect().height()/2
            points[f'Y{i}'] = {'x': round(center_x, 2), 'y': round(center_y, 2)}
        
        return {
            'original_height': self.original_height,
            'points': points
        }
    
    def save_points_data(self):
        data = self.collect_points_data()
        current_image = self.image_files[self.current_page]
        base_name = os.path.splitext(current_image)[0]
        output_path = os.path.join(PathConfig.PICMARK_OUTPUT_DIR, f'{base_name}.json')
        
        # 保存初始JSON
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # 读取JSON并修改
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 计算缩放比
        scale = data['original_height'] / 850
        
        # 1. 先转换所有坐标
        for point in data['points'].values():
            point['x'] = round(point['x'] * scale, 2)
            point['y'] = round(point['y'] * scale, 2)
        
        # 2. 重排ABCD点
        points = data['points']
        abcd_points = [(k, v) for k, v in points.items() if k in ['A', 'B', 'C', 'D']]
        # 按y坐标排序
        abcd_points.sort(key=lambda x: x[1]['y'])
        # 分成上下两组
        top_two = sorted(abcd_points[:2], key=lambda x: x[1]['x'])
        bottom_two = sorted(abcd_points[2:], key=lambda x: x[1]['x'])
        
        # 重新赋值
        points['A'] = top_two[0][1]      # 左上
        points['B'] = top_two[1][1]      # 右上
        points['C'] = bottom_two[0][1]   # 左下
        points['D'] = bottom_two[1][1]   # 右下

        # 3. 重排M/N/P点
        m_points = [(k, v) for k, v in data['points'].items() if k.startswith('M')]
        if m_points:
            # 按y坐标排序
            m_points.sort(key=lambda x: x[1]['y'])
            
            # 创建新的字典存储重排后的点
            new_points = {}
            for k, v in data['points'].items():
                if not k.startswith(('M', 'N', 'P')):
                    new_points[k] = v
            
            # 重新编号并添加M/N/P点
            for i, (old_key, point) in enumerate(m_points, 1):
                old_num = old_key[1:]  # 获取原来的编号
                
                # 添加M点
                new_points[f'M{i}'] = data['points'][f'M{old_num}']
                # 添加N点
                if f'N{old_num}' in data['points']:
                    new_points[f'N{i}'] = data['points'][f'N{old_num}']
                # 添加P点
                if f'P{old_num}' in data['points']:
                    new_points[f'P{i}'] = data['points'][f'P{old_num}']
            
            data['points'] = new_points
        
        # 4. 重排X点
        x_points = [(k, v) for k, v in data['points'].items() if k.startswith('X')]
        if x_points:
            x_points.sort(key=lambda x: x[1]['y'])
            
            # 创建临时字典存储重排后的X点
            temp_x_points = {}
            for i, (_, point) in enumerate(x_points, 1):
                temp_x_points[f'X{i}'] = point
            
            # 更新原字典中的X点
            for k in list(data['points'].keys()):
                if k.startswith('X'):
                    data['points'].pop(k)
            data['points'].update(temp_x_points)

        # 重排Y点
        y_points = [(k, v) for k, v in data['points'].items() if k.startswith('Y')]
        if y_points:
            y_points.sort(key=lambda x: x[1]['y'])
            
            # 创建临时字典存储重排后的Y点
            temp_y_points = {}
            for i, (_, point) in enumerate(y_points, 1):
                temp_y_points[f'Y{i}'] = point
            
            # 更新原字典中的Y点
            for k in list(data['points'].keys()):
                if k.startswith('Y'):
                    data['points'].pop(k)
            data['points'].update(temp_y_points)
        
        # 保存修改后的JSON
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def next_page(self):
        self.save_points_data()  # 保存当前页面的数据
        if self.current_page < len(self.image_files) - 1:
            self.current_page += 1
            self.reset_drawing_area()  # 在加载新图像前重置
            self.load_current_image()
            self.update_progress_label()
            self.update_button_states()
        else:
            self.close()
    
    def prev_page(self):
        self.save_points_data()  # 保存当前页面的数据
        if self.current_page > 0:
            self.current_page -= 1
            self.load_current_image()  # 这里会自动检查和加载标记
            self.update_progress_label()
            self.update_button_states()

def main():
    app = QApplication(sys.argv)
    window = MainApplication()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()