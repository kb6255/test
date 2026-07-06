# 通过更改config.json中的cycle_storage_gb参数，可以快速测试循环存储功能，设置为1GB会频繁触发循环删除旧视频的逻辑，便于验证功能正确性和稳定性。
from PyQt6.QtWidgets import (QApplication, QMainWindow, QLabel, QHBoxLayout, QWidget, QToolBar,
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
                logger.info("长按拍照键：标记当前视频待锁定")
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
        logger.warning("震动传感器触发，标记当前视频待锁定")

    def clean(self):
        # 退出强制关闭蜂鸣
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        GPIO.cleanup()
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
        self.need_lock = False  # 新增：标记当前分段是否需要锁定
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
        # 全屏显示
        self.showFullScreen()
        self.setFocus()
        self.preview_lab.setFocusPolicy(Qt.FocusPolicy.NoFocus)

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
            cmd = ["lsblk", "-o", "MOUNTPOINT,FSTYPE", "--noheadings"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            lines = result.stdout.strip().splitlines()
            usb_mount = None
            for line in lines:
                parts = line.split()
                if len(parts) < 2:
                    continue
                mp, fs = parts[0], parts[1]
                if fs in ("vfat", "exfat", "ntfs", "fat32") and mp.startswith("/media/"):
                    test_file = os.path.join(mp, ".write_test.tmp")
                    try:
                        with open(test_file, "w") as f:
                            f.write("test")
                        os.remove(test_file)
                        usb_mount = mp
                        break
                    except Exception as e:
                        logger.warning(f"U盘挂载点 {mp} 无写入权限，跳过：{str(e)}")
            if usb_mount:
                save_path = os.path.join(usb_mount, "record")
                lock_path = os.path.join(save_path, "lock_video")
                os.makedirs(save_path, exist_ok=True)
                os.makedirs(lock_path, exist_ok=True)
                logger.info(f"【存储确认】识别可写U盘，实际存储目录：{save_path}")
                return save_path
            else:
                raise Exception("未找到拥有写入权限的U盘")
        except Exception as e:
            local_path = os.path.join(os.path.expanduser("~"), "record_backup")
            os.makedirs(local_path, exist_ok=True)
            logger.warning(f"【存储切换】U盘不可用({str(e)})，切换本地存储：{local_path}")
            return local_path

    def check_disk_space(self):
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
        self.clean_old_video(free_gb)

    def clean_old_video(self, free_gb):
        save_root = self.save_root
        all_video = []
        del_candidate = []

        for fname in os.listdir(save_root):
            if fname.endswith(".mp4"):
                fpath = os.path.join(save_root, fname)
                fsize = os.path.getsize(fpath)
                ctime = os.path.getctime(fpath)
                all_video.append((ctime, fpath, fsize))
                if fpath != self.current_video_path:
                    del_candidate.append((ctime, fpath, fsize))

        total_all_gb = sum(item[2] for item in all_video) / (1024 ** 3)
        limit_gb = self.cfg["cycle_storage_gb"]
        del_candidate.sort()

        logger.info(f"【容量校验】全部录像总大小:{total_all_gb:.2f}GB，上限阈值:{limit_gb}GB")
        while total_all_gb > limit_gb and len(del_candidate) > 0:
            del_time, del_path, del_size = del_candidate.pop(0)
            os.remove(del_path)
            logger.info(f"【自动清理】删除旧录像:{os.path.basename(del_path)}，释放{del_size/(1024**3):.2f}GB")
            total_all_gb -= del_size / (1024 ** 3)

    def init_camera(self):
        try:
            w, h = self.cfg["video_width"], self.cfg["video_height"]
            transform = Transform(vflip=True, hflip=False) if self.cfg["cam_flip"] else Transform(hflip=False)
            self.cam0 = Picamera2(0)
            cfg0 = self.cam0.create_video_configuration(main={"size": (w, h), "format": "RGB888"}, transform=transform)
            self.cam0.configure(cfg0)
            self.cam0.start()
            if self.use_dual_cam:
                self.cam1 = Picamera2(1)
                cfg1 = self.cam1.create_video_configuration(main={"size": (w, h), "format": "RGB888"}, transform=transform)
                self.cam1.configure(cfg1)
                self.cam1.start()
            logger.info("双摄像头初始化成功")
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

    def add_watermark(self, frame_rgb):
        if not self.cfg["enable_watermark"]:
            return frame_rgb
        dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = f"{dt_str}"
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        cv2.putText(frame_bgr, text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
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
            if self.car_run_mode == 0:
                main_img = arr0.copy()
                small_img = cv2.resize(arr1, (small_w, small_h))
            else:
                main_img = arr1.copy()
                small_img = cv2.resize(arr0, (small_w, small_h))
            cv2.rectangle(small_img, (0, 0), (small_w-1, small_h-1), (255,255,255), 3)
            main_img[0:small_h, W-small_w:W, :] = small_img
            main_img = self.add_watermark(main_img)
            self.current_frame_rgb = main_img.copy()
            if self.is_rec and self.writer is not None:
                self.writer.write(main_img)
                if time.time() - self.rec_start_time > self.split_sec:
                    self.split_new_video()
            preview_fix = cv2.cvtColor(main_img, cv2.COLOR_BGR2RGB)
            h, w, ch = preview_fix.shape
            qimg = QImage(preview_fix.data, w, h, ch * w, QImage.Format.Format_RGB888)
            pix = QPixmap.fromImage(qimg).scaled(self.preview_lab.size(), Qt.AspectRatioMode.IgnoreAspectRatio)
            self.preview_lab.setPixmap(pix)
            mod_str = "【前进：前主+后画中画】" if self.car_run_mode == 0 else "【后退：后主+前画中画】"
            rec_str = "正在录像" if self.is_rec else "空闲"
            cam_info = "双摄正常" if self.use_dual_cam else "单摄(后视黑屏)"
            self.stat.showMessage(f"{cam_info}|{rec_str} {mod_str} | 存储:{self.save_root}")
        except Exception as e:
            logger.error(f"画面刷新异常:{str(e)}")
            self.preview_lab.setText(f"画面读取异常，等待重连...")

    def split_new_video(self):
        # 先关闭当前写入器，完成MP4完整封装
        if self.writer:
            self.writer.release()
            self.writer = None
        logger.info("达到分段时长，旧分段录制完成")

        # 若标记需要锁定，复制完整文件到lock目录
        if self.need_lock and self.current_video_path:
            src_file = self.current_video_path
            fname = os.path.basename(src_file)
            dst_file = os.path.join(self.lock_root, f"LOCK_{fname}")
            try:
                subprocess.run(["cp", src_file, dst_file], check=True)
                logger.info(f"分段完整锁定成功：{fname}")
                self.need_lock = False
            except Exception as e:
                logger.error(f"分段锁定复制失败：{str(e)}")
        # 创建下一段录像
        self.create_rec_writer()

    def create_rec_writer(self):
        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_video_path = os.path.join(self.save_root, f"{dt}.mp4")
        w, h = self.cfg["video_width"], self.cfg["video_height"]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.writer = cv2.VideoWriter(self.current_video_path, fourcc, 30, (w, h))
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
            # 停止录制时先关闭写入器
            if self.writer is not None:
                self.writer.release()
                self.writer = None
                # 处理待锁定视频
                if self.need_lock and self.current_video_path:
                    src_file = self.current_video_path
                    fname = os.path.basename(src_file)
                    dst_file = os.path.join(self.lock_root, f"LOCK_{fname}")
                    try:
                        subprocess.run(["cp", src_file, dst_file], check=True)
                        logger.info(f"停止录制，锁定当前视频：{fname}")
                        self.need_lock = False
                    except Exception as e:
                        logger.error(f"停止录制锁定失败：{str(e)}")
            self.act_rec.setText("开始录像")
            self.stat.setStyleSheet("QStatusBar{color:rgb(0,180,0);font-weight:bold}")
            logger.info("停止录像")
            self.gpio.beep(BEEP_LONG)

    def lock_current_video(self):
        # 仅打标记，不再直接复制半成品文件
        if not self.is_rec or not self.current_video_path:
            return
        self.need_lock = True
        logger.info("已标记当前分段为待锁定，分段结束自动复制完整视频")

    def save_pic(self):
        if self.current_frame_rgb is None:
            logger.warning("无可用画面，无法截图")
            return
        # 确保photos文件夹存在
        photos_dir = os.path.join(self.save_root, "photos")
        os.makedirs(photos_dir, exist_ok=True)
        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join(photos_dir, f"shot_{dt}.jpg")
        save_bgr = cv2.cvtColor(self.current_frame_rgb, cv2.COLOR_RGB2BGR)
        cv2.imwrite(save_path, save_bgr)
        logger.info(f"截图保存:{save_path}")

    def open_album(self):
        subprocess.Popen(["xdg-open", self.save_root])

    def closeEvent(self, event):
        if self.cam0:
            self.cam0.stop()
        if self.cam1:
            self.cam1.stop()
        if self.writer:
            self.writer.release()
        self.gpio.clean()
        logger.info("程序正常退出，资源全部释放")
        event.accept()

    def keyPressEvent(self, event):
        logger.info(f"收到按键：{event.key()}")
        if event.key() == Qt.Key.Key_Escape:
            self.showNormal()

if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        app.setStyleSheet("QMenuBar{background:magenta;color:white;}QMenuBar::item{background:magenta;}")
        win = MainWin()
        sys.exit(app.exec())
    except Exception as e:
        logger.critical(f"程序全局崩溃:{str(e)}")
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        GPIO.cleanup()
