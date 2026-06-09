from PyQt6.QtWidgets import (QApplication,QMainWindow,QLabel,QHBoxLayout,QWidget,QToolBar,QFileDialog)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QTimer,Qt
from PyQt6.QtGui import QImage,QPixmap
from picamera2 import Picamera2
from libcamera import Transform
import sys,os,numpy as np
import cv2
from datetime import datetime

class MainWin(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("矿用本安行车记录仪")
        self.resize(1280,720)

        # 预览控件
        self.center_widget = QWidget()
        self.setCentralWidget(self.center_widget)
        lay = QHBoxLayout(self.center_widget)
        self.preview_lab = QLabel("等待摄像头启动...")
        self.preview_lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.preview_lab)

        # 菜单栏(洋红底色)
        bar = self.menuBar()
        bar.setStyleSheet("QMenuBar {background-color: magenta;}QMenuBar::item {background-color: magenta;}")
        menu_file = bar.addMenu("文件")
        menu_set = bar.addMenu("设置")
        menu_album = bar.addMenu("相册")

        act_save = QAction("手动截图",self)
        act_save.triggered.connect(self.save_pic)
        menu_file.addAction(act_save)
        act_open_album = QAction("打开相册目录",self)
        act_open_album.triggered.connect(self.open_album)
        menu_album.addAction(act_open_album)

        # 工具栏：录像 + 前进/后退模式切换按钮
        toolbar = QToolBar("快捷操作")
        self.addToolBar(toolbar)
        self.act_rec = QAction("开始录像",self)
        self.act_rec.triggered.connect(self.rec_toggle)
        toolbar.addAction(self.act_rec)

        self.act_mode = QAction("模式：前进(前主+后画中画)",self)
        self.act_mode.triggered.connect(self.switch_car_mode)
        toolbar.addAction(self.act_mode)

        # 状态栏
        self.stat = self.statusBar()
        self.stat.showMessage("摄像头初始化中 | U盘路径:/media/kongbin/E295-3564")

        # 0=前进(前主、后小窗) 1=后退(后主、前小窗)
        self.car_run_mode = 0
        self.cam0 = None
        self.cam1 = None
        self.init_camera()

        # 画面刷新定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(33)
        self.is_rec = False
        self.writer = None  # 录像写入对象
        self.save_root = "/media/kongbin/E295-3564/record"
        os.makedirs(self.save_root,exist_ok=True) #自动创建录像文件夹

    def init_camera(self):
        # 前视0，后视1
        self.cam0 = Picamera2(0)
        cfg0 = self.cam0.create_video_configuration({"size":(1280,720),"format":"RGB888"},transform=Transform(vflip=True))
        self.cam0.configure(cfg0)
        self.cam0.start()

        self.cam1 = Picamera2(0)
        cfg1 = self.cam1.create_video_configuration({"size":(1280,720),"format":"RGB888"},transform=Transform(vflip=True))
        self.cam1.configure(cfg1)
        self.cam1.start()

    def switch_car_mode(self):
        # 前进<->后退循环切换
        self.car_run_mode = 1 - self.car_run_mode
        if self.car_run_mode == 0:
            self.act_mode.setText("模式：前进(前主+后画中画)")
        else:
            self.act_mode.setText("模式：后退(后主+前画中画)")

    def update_frame(self):
        arr0 = self.cam0.capture_array() #前
        arr1 = self.cam1.capture_array() #后
        H,W,C = arr0.shape
        # 小窗尺寸：主画面宽高1/4
        small_w = W//4
        small_h = H//4

        if self.car_run_mode == 0:
            # 前进：前视全屏，后视缩小放右上角
            main_img = arr0.copy()
            small_img = cv2.resize(arr1,(small_w,small_h))
        else:
            # 后退：后视全屏，前视缩小放右上角
            main_img = arr1.copy()
            small_img = cv2.resize(arr0,(small_w,small_h))
        # 贴在右上角
        main_img[0:small_h, W-small_w:W, :] = small_img

        # ======如果正在录像，写入当前合成帧======
        if self.is_rec and self.writer is not None:
            # opencv保存需要BGR格式，RGB转BGR
            frame_bgr = cv2.cvtColor(main_img,cv2.COLOR_RGB2BGR)
            self.writer.write(frame_bgr)

        # Qt渲染
        h,w,ch = main_img.shape
        qimg = QImage(main_img.data,w,h,ch*w,QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg).scaled(self.preview_lab.size(),Qt.AspectRatioMode.KeepAspectRatio)
        self.preview_lab.setPixmap(pix)

        mod_str = "【前进：前主+后画中画】" if self.car_run_mode==0 else "【后退：后主+前画中画】"
        rec_str = "正在录像" if self.is_rec else "空闲"
        self.stat.showMessage(f"摄像头正常 | {rec_str} {mod_str} | U盘:/media/kongbin/E295-3564")

    def rec_toggle(self):
        self.is_rec = not self.is_rec
        if self.is_rec:
            # 开始录像：按时间生成文件名
            dt = datetime.now().strftime("%Y%m%d_%H%M%S")
            video_path = os.path.join(self.save_root,f"{dt}.mp4")
            # 编码：mp4v，分辨率1280*720，帧率30
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.writer = cv2.VideoWriter(video_path,fourcc,30,(1280,720))
            self.act_rec.setText("停止录像")
        else:
            # 停止录像，释放写入
            if self.writer is not None:
                self.writer.release()
                self.writer = None
            self.act_rec.setText("开始录像")

    def save_pic(self):
        save_path,_ = QFileDialog.getSaveFileName(self,"保存截图","/media/kongbin/E295-3564/shot.jpg","*.jpg")
        if save_path:
            pix = self.preview_lab.pixmap()
            pix.save(save_path)

    def open_album(self):
        os.system(f"xdg-open /media/kongbin/E295-3564 &")

if __name__=="__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet("QMenuBar{background:magenta;}QMenuBar::item{background:magenta;}")
    win = MainWin()
    win.show()
    sys.exit(app.exec())