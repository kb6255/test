from PyQt6.QtWidgets import (QApplication,QMainWindow,QLabel,QHBoxLayout,QWidget,QToolBar,QFileDialog)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QTimer,Qt
from PyQt6.QtGui import QImage,QPixmap
from picamera2 import Picamera2
from libcamera import Transform
import sys,os,subprocess
import numpy as np
import cv2
from datetime import datetime
import signal
# 导入GPIO库
import RPi.GPIO as GPIO
import time

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
        self.stat.showMessage("摄像头初始化中 | 正在自动检索存储...")

        # ========== 摄像头配置 ==========
        self.use_dual_cam = True
        # self.use_dual_cam = False
        self.car_run_mode = 0  # 0前进 1后退
        self.cam0 = None
        self.cam1 = None
        self.init_camera()

        # 存储路径
        self.save_root = self.get_usb_dir()
        os.makedirs(self.save_root,exist_ok=True)

        # ========== GPIO按键配置 ==========
        # 引脚定义
        self.KEY_MODE = 19    # 画面切换键
        self.KEY_SNAP = 13    # 拍照键（可自行修改）
        self.init_gpio()
        # 按键防抖标记，防止长按重复触发
        self.key_mode_flag = False
        self.key_snap_flag = False

        # 画面+按键轮询定时器（33ms刷新画面，同时检测按键）
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(33)

        self.is_rec = False
        self.writer = None

        self.showFullScreen()
        # 移除原文件标记、信号监听，不再依赖外部脚本
        # self.switch_flag_file = "/tmp/cam_switch.flag"
        # signal.signal(signal.SIGUSR1,self.sig_switch_mode)

    # 初始化GPIO
    def init_gpio(self):
        GPIO.setmode(GPIO.BCM)
        # 上拉输入，按键按下为低电平
        GPIO.setup(self.KEY_MODE, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.KEY_SNAP, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # 按键检测逻辑（在画面定时器中轮询）
    def check_gpio_key(self):
        # 1. 画面切换按键
        if GPIO.input(self.KEY_MODE) == 0:
            if not self.key_mode_flag:
                time.sleep(0.02)  # 软件消抖
                if GPIO.input(self.KEY_MODE) == 0:
                    self.switch_car_mode()
                    self.key_mode_flag = True
        else:
            self.key_mode_flag = False

        # 2. 拍照按键
        if GPIO.input(self.KEY_SNAP) == 0:
            if not self.key_snap_flag:
                time.sleep(0.02)  # 软件消抖
                if GPIO.input(self.KEY_SNAP) == 0:
                    self.save_pic()
                    self.key_snap_flag = True
        else:
            self.key_snap_flag = False

    # 自动搜寻U盘函数
    def get_usb_dir(self):
        try:
            cmd = "lsblk -o MOUNTPOINT,FSTYPE | grep /media/"
            out = subprocess.check_output(cmd,shell=True,encoding="utf-8")
            lines = out.strip().splitlines()
            usb_path = None
            for line in lines:
                mp,fs = line.split()
                if fs in ("vfat","exfat","ntfs","fat32"):
                    usb_path = mp
                    break
            if usb_path:
                return os.path.join(usb_path,"record")
            else:
                home = os.path.expanduser("~")
                return os.path.join(home,"record_backup")
        except:
            home = os.path.expanduser("~")
            return os.path.join(home,"record_backup")

    def init_camera(self):
        # 前视0，后视1
        self.cam0 = Picamera2(0)
        cfg0 = self.cam0.create_video_configuration({"size":(1280,720),"format":"RGB888"},transform=Transform(vflip=True))
        self.cam0.configure(cfg0)
        self.cam0.start()

        if self.use_dual_cam:
            self.cam1 = Picamera2(1)
            cfg1 = self.cam1.create_video_configuration({"size":(1280,720),"format":"RGB888"},transform=Transform(vflip=True))
            self.cam1.configure(cfg1)
            self.cam1.start()
        else:
            self.cam1 = None

    def switch_car_mode(self):
        # 前进<->后退循环切换
        self.car_run_mode = 1 - self.car_run_mode
        if self.car_run_mode == 0:
            self.act_mode.setText("模式：前进(前主+后画中画)")
        else:
            self.act_mode.setText("模式：后退(后主+前画中画)")

    def update_frame(self):
        # 每帧优先检测按键
        self.check_gpio_key()

        arr0 = self.cam0.capture_array()
        if self.use_dual_cam and self.cam1 is not None:
            arr1 = self.cam1.capture_array()
        else:
            arr1 = np.zeros_like(arr0)

        H,W,C = arr0.shape
        small_w = W//3
        small_h = H//3

        if self.car_run_mode == 0:
            main_img = arr0.copy()
            small_img = cv2.resize(arr1,(small_w,small_h))
        else:
            main_img = arr1.copy()
            small_img = cv2.resize(arr0,(small_w,small_h))

        main_img[0:small_h, W-small_w:W, :] = small_img

        # 录像编码
        if self.is_rec and self.writer is not None:
            frame_bgr = cv2.cvtColor(main_img, cv2.COLOR_RGB2BGR)
            self.writer.write(frame_bgr)

        # Qt渲染
        # main_img_rgb = cv2.cvtColor(main_img, cv2.COLOR_BGR2RGB)
        h,w,ch = main_img_rgb.shape
        # qimg = QImage(main_img_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        qimg = QImage(main_img.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg).scaled(self.preview_lab.size(),Qt.AspectRatioMode.KeepAspectRatio)
        self.preview_lab.setPixmap(pix)

        mod_str = "【前进：前主+后画中画】" if self.car_run_mode==0 else "【后退：后主+前画中画】"
        rec_str = "正在录像" if self.is_rec else "空闲"
        cam_info = "双摄" if self.use_dual_cam else "单摄(后置黑屏)"
        self.stat.showMessage(f"摄像头正常|{cam_info}|{rec_str} {mod_str} | 存储:{self.save_root}")

    def rec_toggle(self):
        self.is_rec = not self.is_rec
        if self.is_rec:
            dt = datetime.now().strftime("%Y%m%d_%H%M%S")
            video_path = os.path.join(self.save_root,f"{dt}.mp4")
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.writer = cv2.VideoWriter(video_path,fourcc,30,(1280,720))
            self.act_rec.setText("停止录像")
        else:
            if self.writer is not None:
                self.writer.release()
                self.writer = None
            self.act_rec.setText("开始录像")

    def save_pic(self):
        # 实体按键触发/菜单触发 共用截图逻辑
        default_jpg = os.path.join(self.save_root,"shot.jpg")
        save_path,_ = QFileDialog.getSaveFileName(self,"保存截图",default_jpg,"*.jpg")
        if save_path:
            pix = self.preview_lab.pixmap()
            pix.save(save_path)

    def open_album(self):
        os.system(f"xdg-open {self.save_root} &")

    # 窗口关闭时释放GPIO、摄像头资源
    def closeEvent(self, event):
        # 停止摄像头
        if self.cam0:
            self.cam0.stop()
        if self.cam1:
            self.cam1.stop()
        # 停止录像
        if self.writer:
            self.writer.release()
        # 释放GPIO
        GPIO.cleanup()
        event.accept()

if __name__=="__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet("QMenuBar{background:magenta;}QMenuBar::item{background:magenta;}")
    win = MainWin()
    win.show()
    sys.exit(app.exec())