# 通过更改config.json中的cycle_storage_gb参数，可以快速测试循环存储功能，设置为1GB会频繁触发循环删除旧视频的逻辑，便于验证功能正确性和稳定性。
from PyQt6.QtWidgets import (QApplication, QMainWindow, QLabel, QHBoxLayout, QWidget, QToolBar, QFileDialog,
                               QMenu, QDialog, QVBoxLayout, QSpinBox, QCheckBox, QPushButton, QLabel as QLab)
from PyQt6.QtGui import QAction, QFont, QColor
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from picamera2 import Picamera2, controls
from libcamera import Transform
import sys, os, subprocess, json, logging, time
import numpy as np
import cv2
from datetime import datetime
import signal
import RPi.GPIO as GPIO

# ====================== 全局配置常量 ======================
CONFIG_PATH = "/home/kongbin/test/config.json"
LOG_PATH = "/home/kongbin/test/log/record.log"
# GPIO引脚定义
KEY_SNAP = 13       # 拍照短按，长按锁定视频
KEY_MODE = 19       # 画面模式切换
BUZZER_PIN = 5      # 蜂鸣器
SHAKE_PIN = 26      # 震动传感器
# 蜂鸣器时长
BEEP_SHORT = 0.1
BEEP_LONG = 0.3
# 默认配置
DEFAULT_CFG = {
    "device_id": "MA-001",
    "video_width": 1280,
    "video_height": 720,
    "split_minute": 1,
    "enable_watermark": True,
    "enable_audio": True,
    "cycle_storage_gb": 30,
    "warn_space_gb": 5,
    "cam_flip": True
}
# 自动创建日志目录，解决权限报错
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("mineral_rec")

# ====================== GPIO中断回调 ======================
class GpioHandler:
    def __init__(self, win):
        self.win = win
        self.long_press_timer = {}
        GPIO.setmode(GPIO.BCM)
        # 输入按键
        GPIO.setup(KEY_SNAP, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(KEY_MODE, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(SHAKE_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # 低电平触发：默认高电平 关闭蜂鸣
        GPIO.setup(BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)

        GPIO.add_event_detect(KEY_SNAP, GPIO.FALLING, callback=self.key_snap_cb, bouncetime=200)
        GPIO.add_event_detect(KEY_MODE, GPIO.FALLING, callback=self.key_mode_cb, bouncetime=200)
        GPIO.add_event_detect(SHAKE_PIN, GPIO.FALLING, callback=self.shake_cb, bouncetime=300)

    # 安全蜂鸣，开子线程sleep，不阻塞中断回调
    def beep(self, sec):
        import threading
        def beep_task():
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
            time.sleep(sec)
            GPIO.output(BUZZER_PIN, GPIO.LOW)
        t = threading.Thread(target=beep_task, daemon=True)
        t.start()

    def key_snap_cb(self, ch):
        t_start = time.time()
        while GPIO.input(ch) == 0:
            if time.time() - t_start > 2:
                self.win.lock_current_video()
                self.beep(BEEP_LONG)
                logger.info("长按拍照键：锁定当前视频")
                return
        self.win.save_pic()
        self.beep(BEEP_SHORT)
        logger.info("短按拍照键：截图保存")

    def key_mode_cb(self, ch):
        self.win.switch_car_mode()
        self.beep(BEEP_SHORT)
        logger.info("模式切换按键触发")

    def shake_cb(self, ch):
        self.win.lock_current_video()
        self.beep(BEEP_LONG)
        logger.warning("震动传感器触发，锁定当前录像片段")

    def clean(self):
        # 退出强制关闭蜂鸣
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        GPIO.cleanup()
# class GpioHandler:
#     def __init__(self, win):
#         self.win = win
#         self.long_press_timer = {}
#         GPIO.setmode(GPIO.BCM)
#         # 按键上拉输入
#         GPIO.setup(KEY_SNAP, GPIO.IN, pull_up_down=GPIO.PUD_UP)
#         GPIO.setup(KEY_MODE, GPIO.IN, pull_up_down=GPIO.PUD_UP)
#         GPIO.setup(SHAKE_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
#         GPIO.setup(BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)
#         # 注册下降沿中断
#         GPIO.add_event_detect(KEY_SNAP, GPIO.FALLING, callback=self.key_snap_cb, bouncetime=200)
#         GPIO.add_event_detect(KEY_MODE, GPIO.FALLING, callback=self.key_mode_cb, bouncetime=200)
#         GPIO.add_event_detect(SHAKE_PIN, GPIO.FALLING, callback=self.shake_cb, bouncetime=300)

#     def beep(self, sec):
#         GPIO.output(BUZZER_PIN, GPIO.HIGH)
#         time.sleep(sec)
#         GPIO.output(BUZZER_PIN, GPIO.LOW)

#     def key_snap_cb(self, ch):
#         # 长按2s判定紧急锁定
#         t_start = time.time()
#         while GPIO.input(ch) == 0:
#             if time.time() - t_start > 2:
#                 self.win.lock_current_video()
#                 self.beep(BEEP_LONG)
#                 logger.info("长按拍照键：锁定当前视频")
#                 return
#         self.win.save_pic()
#         self.beep(BEEP_SHORT)
#         logger.info("短按拍照键：截图保存")

#     def key_mode_cb(self, ch):
#         self.win.switch_car_mode()
#         self.beep(BEEP_SHORT)
#         logger.info("模式切换按键触发")

#     def shake_cb(self, ch):
#         self.win.lock_current_video()
#         self.beep(BEEP_LONG)
#         logger.warning("震动传感器触发，锁定当前录像片段")

#     def clean(self):
#         GPIO.output(BUZZER_PIN, GPIO.LOW)
#         GPIO.cleanup()

# ====================== 设置弹窗 ======================
class SettingDialog(QDialog):
    def __init__(self, cfg, parent):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("记录仪参数设置")
        self.resize(400, 300)
        layout = QVBoxLayout()
        # 分段时长
        layout.addWidget(QLab("录像分段时长(分钟)"))
        self.split_sp = QSpinBox()
        self.split_sp.setRange(1, 30)
        self.split_sp.setValue(cfg["split_minute"])
        layout.addWidget(self.split_sp)
        # 水印开关
        self.water_cb = QCheckBox("开启画面时间设备水印")
        self.water_cb.setChecked(cfg["enable_watermark"])
        layout.addWidget(self.water_cb)
        # 音频开关
        self.audio_cb = QCheckBox("开启录音")
        self.audio_cb.setChecked(cfg["enable_audio"])
        layout.addWidget(self.audio_cb)
        # 保存按钮
        save_btn = QPushButton("保存设置")
        save_btn.clicked.connect(self.save_cfg)
        layout.addWidget(save_btn)
        self.setLayout(layout)

    def save_cfg(self):
        self.cfg["split_minute"] = self.split_sp.value()
        self.cfg["enable_watermark"] = self.water_cb.isChecked()
        self.cfg["enable_audio"] = self.audio_cb.isChecked()
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        self.accept()

# ====================== 主窗口程序 ======================
class MainWin(QMainWindow):
    def __init__(self):
        super().__init__()
        # 加载配置文件
        self.load_config()
        self.setWindowTitle("矿用本安行车记录仪 V2.0完善版")
        self.resize(self.cfg["video_width"], self.cfg["video_height"])
        # 界面基础
        self.center_widget = QWidget()
        self.setCentralWidget(self.center_widget)
        lay = QHBoxLayout(self.center_widget)
        self.preview_lab = QLabel("等待摄像头启动...")
        self.preview_lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.preview_lab)
        # 菜单栏 洋红底色
        bar = self.menuBar()
        bar.setStyleSheet("QMenuBar {background-color: magenta;color:#fff;}QMenuBar::item {background-color: magenta;}")
        menu_file = bar.addMenu("文件")
        menu_set = bar.addMenu("设置")
        menu_album = bar.addMenu("相册/录像")
        # 文件菜单
        act_save = QAction("手动截图", self)
        act_save.triggered.connect(self.save_pic)
        menu_file.addAction(act_save)
        # 设置菜单
        act_setting = QAction("参数配置", self)
        act_setting.triggered.connect(self.open_setting)
        menu_set.addAction(act_setting)
        # 相册菜单
        act_open_album = QAction("打开存储目录", self)
        act_open_album.triggered.connect(self.open_album)
        menu_album.addAction(act_open_album)
        # 工具栏
        toolbar = QToolBar("快捷操作")
        self.addToolBar(toolbar)
        self.act_rec = QAction("开始录像", self)
        self.act_rec.triggered.connect(self.rec_toggle)
        toolbar.addAction(self.act_rec)
        self.act_mode = QAction("模式：前进(前主+后画中画)", self)
        self.act_mode.triggered.connect(self.switch_car_mode)
        toolbar.addAction(self.act_mode)
        # 状态栏
        self.stat = self.statusBar()
        self.stat.setStyleSheet("QStatusBar{font-size:12px;font-weight:bold;}")
        # 摄像头变量
        self.use_dual_cam = True
        self.car_run_mode = 0  # 0前进 1后退
        self.cam0 = None
        self.cam1 = None
        self.init_camera()
        # 存储路径
        self.save_root = self.get_usb_dir()
        self.lock_root = os.path.join(self.save_root, "lock_video")
        os.makedirs(self.save_root, exist_ok=True)
        os.makedirs(self.lock_root, exist_ok=True)
        # GPIO管理
        self.gpio = GpioHandler(self)
        # 录像相关
        self.is_rec = False
        self.writer = None
        self.rec_start_time = None
        self.split_sec = self.cfg["split_minute"] * 60
        self.current_video_path = ""
        # 画面缓存（用于截图，保证截图和预览画面完全一致）
        self.current_frame_rgb = None
        # 画面定时器 33ms
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(33)
        # 磁盘空间检测定时器 30s一次
        self.disk_timer = QTimer()
        self.disk_timer.timeout.connect(self.check_disk_space)
        self.disk_timer.start(30000)
        # 全屏隐藏鼠标
        self.showFullScreen()
        app.setOverrideCursor(Qt.CursorShape.BlankCursor)

    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                self.cfg = json.load(f)
        else:
            self.cfg = DEFAULT_CFG
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2)

    def open_setting(self):
        dlg = SettingDialog(self.cfg, self)
        if dlg.exec():
            self.load_config()
            self.split_sec = self.cfg["split_minute"] * 60
            logger.info("参数配置已更新")
    def get_usb_dir(self):
        try:
            cmd = "lsblk -o MOUNTPOINT,FSTYPE | grep /media/"
            out = subprocess.check_output(cmd, shell=True, encoding="utf-8")
            lines = out.strip().splitlines()
            for line in lines:
                mp, fs = line.split()
                if fs in ("vfat", "exfat", "ntfs", "fat32"):
                    return os.path.join(mp, "record")
            # 无U盘本地存储
            logger.warning("未检测到U盘，切换本地存储")
            return os.path.join(os.path.expanduser("~"), "record_backup")
        except Exception as e:
            logger.error(f"U盘检测异常:{str(e)}")
            return os.path.join(os.path.expanduser("~"), "record_backup")
    
    # def get_usb_dir(self):
    #     try:
    #         # 改用subprocess.run，grep无结果不会抛异常
    #         cmd = ["lsblk", "-o", "MOUNTPOINT,FSTYPE", "--noheadings"]
    #         result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
    #         lines = result.stdout.strip().splitlines()
    #         usb_mount = None
    #         for line in lines:
    #             parts = line.split()
    #             if len(parts) < 2:
    #                 continue
    #             mp, fs = parts[0], parts[1]
    #             # 筛选移动存储格式
    #             if fs in ("vfat", "exfat", "ntfs", "fat32") and mp.startswith("/media/"):
    #                 # 写入权限测试，无法写入直接跳过该U盘
    #                 test_file = os.path.join(mp, ".write_test.tmp")
    #                 try:
    #                     with open(test_file, "w") as f:
    #                         f.write("test")
    #                     os.remove(test_file)
    #                     usb_mount = mp
    #                     break
    #                 except Exception as e:
    #                     logger.warning(f"U盘挂载点 {mp} 无写入权限，跳过：{str(e)}")
    #         if usb_mount:
    #             save_path = os.path.join(usb_mount, "record")
    #             lock_path = os.path.join(save_path, "lock_video")
    #             os.makedirs(save_path, exist_ok=True)
    #             os.makedirs(lock_path, exist_ok=True)
    #             logger.info(f"【存储确认】识别可写U盘，实际存储目录：{save_path}")
    #             return save_path
    #         else:
    #             raise Exception("未找到拥有写入权限的U盘")
    #     except Exception as e:
    #         local_path = os.path.join(os.path.expanduser("~"), "record_backup")
    #         os.makedirs(local_path, exist_ok=True)
    #         logger.warning(f"【存储切换】U盘不可用({str(e)})，切换本地存储：{local_path}")
    #         return local_path

    def check_disk_space(self):
        # 每次磁盘检测自动重新识别U盘，支持中途插拔
        new_root = self.get_usb_dir()
        if new_root != self.save_root:
            self.save_root = new_root
            self.lock_root = os.path.join(self.save_root, "lock_video")
            os.makedirs(self.save_root, exist_ok=True)
            os.makedirs(self.lock_root, exist_ok=True)
            logger.info(f"【存储目录更新】已切换至：{self.save_root}")

        statvfs = os.statvfs(self.save_root)
        free_gb = (statvfs.f_frsize * statvfs.f_bavail) / (1024**3)
        warn_gb = self.cfg["warn_space_gb"]
        if free_gb < warn_gb:
            self.stat.setStyleSheet("QStatusBar{color:rgb(255,160,0);font-weight:bold}")
            self.stat.showMessage(f"【告警】剩余空间不足{warn_gb}GB！请清理录像 | 剩余{free_gb:.1f}GB")
            self.gpio.beep(BEEP_LONG)
        else:
            self.stat.setStyleSheet("QStatusBar{color:rgb(0,180,0);font-weight:bold}")
        # 循环清理旧视频
        self.clean_old_video(free_gb)

    # def clean_old_video(self, free_gb):
    #     cycle_gb = self.cfg["cycle_storage_gb"]
    #     if free_gb > cycle_gb:
    #         return
    #     # 只清理普通录像，不碰锁定视频
    #     files = []
    #     for f in os.listdir(self.save_root):
    #         if f.endswith(".mp4") and not os.path.join(self.save_root, f).startswith(self.lock_root):
    #             full_p = os.path.join(self.save_root, f)
    #             files.append((os.path.getctime(full_p), full_p))
    #     files.sort()
    #     # 依次删除最早视频直到空间达标
    #     for ctime, path in files:
    #         if free_gb > cycle_gb:
    #             break
    #         try:
    #             os.remove(path)
    #             logger.info(f"循环清理旧录像:{os.path.basename(path)}")
    #             statvfs = os.statvfs(self.save_root)
    #             free_gb = (statvfs.f_frsize * statvfs.f_bavail) / (1024**3)
    #         except Exception as e:
    #             logger.error(f"删除录像失败:{str(e)}")
    def clean_old_video(self, free_gb):
        save_root = self.save_root
        all_video = []       # 全部录像（含当前录制）
        del_candidate = []    # 可删除的旧录像（排除当前录制）

        for fname in os.listdir(save_root):
            if fname.endswith(".mp4"):
                fpath = os.path.join(save_root, fname)
                fsize = os.path.getsize(fpath)
                ctime = os.path.getctime(fpath)
                all_video.append((ctime, fpath, fsize))
                # 当前正在写入的视频不加入删除列表
                if fpath != self.current_video_path:
                    del_candidate.append((ctime, fpath, fsize))

        # 计算所有视频总占用（包含正在录制的片段）
        total_all_gb = sum(item[2] for item in all_video) / (1024 ** 3)
        limit_gb = self.cfg["cycle_storage_gb"]
        # 按创建时间升序，最旧文件排在前面
        del_candidate.sort()

        logger.info(f"【容量校验】全部录像总大小:{total_all_gb:.2f}GB，上限阈值:{limit_gb}GB")
        # 总容量超过4GB，循环删除最早视频
        while total_all_gb > limit_gb and len(del_candidate) > 0:
            del_time, del_path, del_size = del_candidate.pop(0)
            os.remove(del_path)
            logger.info(f"【自动清理】删除旧录像:{os.path.basename(del_path)}，释放{del_size/(1024**3):.2f}GB")
            total_all_gb -= del_size / (1024 ** 3)

    def init_camera(self):
        try:
            w, h = self.cfg["video_width"], self.cfg["video_height"]
            # 2. 判断是否开启画面垂直翻转，生成翻转参数
            transform = Transform(vflip=True) if self.cfg["cam_flip"] else Transform()
            self.cam0 = Picamera2(0)
            cfg0 = self.cam0.create_video_configuration(main={"size": (w, h), "format": "RGB888"}, transform=transform)
            self.cam0.configure(cfg0)
            self.cam0.start()
            # ========== 双摄模式开启，则初始化第二路 cam1 (CSI1) ==========
            if self.use_dual_cam:
                self.cam1 = Picamera2(1)
                cfg1 = self.cam1.create_video_configuration(main={"size": (w, h), "format": "RGB888"}, transform=transform)
                self.cam1.configure(cfg1)
                self.cam1.start()
            logger.info("双摄像头初始化成功")
        # 捕获摄像头所有异常：排线松、摄像头未识别、占用、权限不足等
        except Exception as e:
            logger.error(f"摄像头初始化失败:{str(e)}")
            self.preview_lab.setText(f"摄像头异常:{str(e)}，3s后重试")
            QTimer.singleShot(3000, self.init_camera)

    def switch_car_mode(self):
        self.car_run_mode = 1 - self.car_run_mode
        if self.car_run_mode == 0:
            self.act_mode.setText("模式：前进(前主+后画中画)")
        else:
            self.act_mode.setText("模式：后退(后主+前画中画)")

    # ========== 修复水印色彩失真核心函数 ==========
    def add_watermark(self, frame_rgb):
        if not self.cfg["enable_watermark"]:
            return frame_rgb
        dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dev_id = self.cfg["device_id"]
        mode_str = "前进" if self.car_run_mode == 0 else "后退"
        # text = f"{dt_str} 设备:{dev_id} {mode_str}"
        text = f"{dt_str}"
        # RGB转BGR后绘图，避免通道颠倒失真
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        cv2.putText(frame_bgr, text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        # 绘图完成转回原生RGB还给画面流程
        frame_fixed = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        return frame_fixed

    def update_frame(self):
        try:
            arr0 = self.cam0.capture_array()
            if self.use_dual_cam and self.cam1 is not None:
                arr1 = self.cam1.capture_array()
            else:
                arr1 = np.zeros_like(arr0)
            H, W, C = arr0.shape
            small_w = W // 3
            small_h = H // 3
            # 合成画中画+白色边框区分
            if self.car_run_mode == 0:
                main_img = arr0.copy()
                small_img = cv2.resize(arr1, (small_w, small_h))
            else:
                main_img = arr1.copy()
                small_img = cv2.resize(arr0, (small_w, small_h))
            # 画中画白色边框（缩放图像不影响主画面通道）
            cv2.rectangle(small_img, (0, 0), (small_w-1, small_h-1), (255,255,255), 3)
            main_img[0:small_h, W-small_w:W, :] = small_img
            # 水印处理（已修复通道转换，无色彩失真）
            main_img = self.add_watermark(main_img)
            # 缓存当前完整RGB画面，用于截图功能
            self.current_frame_rgb = main_img.copy()
            # 分段录像判断
            if self.is_rec and self.writer is not None:
                # 去掉RGB2BGR转换，直接写入原图
                self.writer.write(main_img)
                if time.time() - self.rec_start_time > self.split_sec:
                    self.split_new_video()
            # Qt渲染：main_img原生RGB直接渲染，无多余转换
            # 新增：BGR → RGB，专门给界面预览
            preview_fix = cv2.cvtColor(main_img, cv2.COLOR_BGR2RGB)
            h, w, ch = preview_fix.shape
            qimg = QImage(preview_fix.data, w, h, ch * w, QImage.Format.Format_RGB888)
            # pix = QPixmap.fromImage(qimg).scaled(self.preview_lab.size(), Qt.AspectRatioMode.KeepAspectRatio)
            pix = QPixmap.fromImage(qimg).scaled(self.preview_lab.size(), Qt.AspectRatioMode.IgnoreAspectRatio)# 裁剪拉伸
            # pix = QPixmap.fromImage(qimg).scaled(  # 遮挡状态栏
            #     self.preview_lab.size(),
            #     Qt.AspectRatioMode.KeepAspectRatioByExpanding
            # )
            self.preview_lab.setPixmap(pix)
            # 状态栏文字
            mod_str = "【前进：前主+后画中画】" if self.car_run_mode == 0 else "【后退：后主+前画中画】"
            rec_str = "正在录像" if self.is_rec else "空闲"
            cam_info = "双摄正常" if self.use_dual_cam else "单摄(后视黑屏)"
            self.stat.showMessage(f"{cam_info}|{rec_str} {mod_str} | 存储:{self.save_root}")
        except Exception as e:
            logger.error(f"画面刷新异常:{str(e)}")
            self.preview_lab.setText(f"画面读取异常，等待重连...")

    def split_new_video(self):
        if self.writer:
            self.writer.release()
            self.writer = None
        logger.info("达到分段时长，新建录像文件")
        self.create_rec_writer()

    def create_rec_writer(self):
        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_video_path = os.path.join(self.save_root, f"{dt}.mp4")
        w, h = self.cfg["video_width"], self.cfg["video_height"]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.writer = cv2.VideoWriter(self.current_video_path, fourcc, 30, (w, h))
        # 关键校验：判断录像文件是否成功打开
        if self.writer.isOpened():
            logger.info(f"【录像创建成功】文件路径：{self.current_video_path}")
        else:
            logger.error(f"【录像创建失败】无法写入路径：{self.current_video_path}")
        self.rec_start_time = time.time()

    def rec_toggle(self):
        self.is_rec = not self.is_rec
        if self.is_rec:
            self.create_rec_writer()
            self.act_rec.setText("停止录像")
            self.stat.setStyleSheet("QStatusBar{color:rgb(255,0,0);font-weight:bold}")
            logger.info(f"开始录像，文件:{self.current_video_path}")
            self.gpio.beep(BEEP_SHORT)
        else:
            if self.writer is not None:
                self.writer.release()
                self.writer = None
            self.act_rec.setText("开始录像")
            self.stat.setStyleSheet("QStatusBar{color:rgb(0,180,0);font-weight:bold}")
            logger.info("停止录像")
            self.gpio.beep(BEEP_LONG)

    def lock_current_video(self):
        if not self.is_rec or not self.current_video_path:
            return
        try:
            name = os.path.basename(self.current_video_path)
            dst = os.path.join(self.lock_root, f"LOCK_{name}")
            subprocess.run(["cp", self.current_video_path, dst])
            logger.info(f"视频锁定完成:{name}")
        except Exception as e:
            logger.error(f"锁定视频失败:{str(e)}")

    # ========== 修复截图逻辑：使用缓存的完整预览帧，画面和预览完全一致 ==========
    def save_pic(self):
        if self.current_frame_rgb is None:
            logger.warning("无可用画面，无法截图")
            return
        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_jpg = os.path.join(self.save_root, f"shot_{dt}.jpg")
        save_path, _ = QFileDialog.getSaveFileName(self, "保存高清截图", default_jpg, "*.jpg")
        if save_path:
            # 缓存RGB转BGR保存，和预览画面色彩100%匹配
            save_bgr = cv2.cvtColor(self.current_frame_rgb, cv2.COLOR_RGB2BGR)
            cv2.imwrite(save_path, save_bgr)
            logger.info(f"截图保存:{save_path}")

    def open_album(self):
        os.system(f"xdg-open {self.save_root} &")

    def closeEvent(self, event):
        # 释放摄像头
        if self.cam0:
            self.cam0.stop()
        if self.cam1:
            self.cam1.stop()
        # 关闭录像
        if self.writer:
            self.writer.release()
        # 清理GPIO，强制关闭蜂鸣
        self.gpio.clean()
        logger.info("程序正常退出，资源全部释放")
        event.accept()

    # ESC退出全屏
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.showNormal()
            app.restoreOverrideCursor()

if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        app.setStyleSheet("QMenuBar{background:magenta;color:white;}QMenuBar::item{background:magenta;}")
        win = MainWin()
        sys.exit(app.exec())
    except Exception as e:
        logger.critical(f"程序全局崩溃:{str(e)}")
        # 崩溃强制拉高蜂鸣器
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        GPIO.cleanup()