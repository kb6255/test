import sys
import cv2
from PyQt6.QtWidgets import QApplication,QMainWindow,QWidget,QHBoxLayout,QLabel
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QImage,QPixmap
from picamera2 import Picamera2

class Win(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("车载本地监控")
        self.resize(1280,720)

        # 摄像头0初始化，用预览配置（低延迟适配Qt实时预览）
        self.p2_0 = Picamera2(0)
        # preview预览配置，只负责低延迟出图，transform对capture_array无效因此不写
        preview_conf = self.p2_0.create_preview_configuration(main={"size":(640,480)})
        self.p2_0.configure(preview_conf)
        self.p2_0.start()

        # UI布局
        center = QWidget()
        self.setCentralWidget(center)
        lay = QHBoxLayout(center)
        self.lab0 = QLabel()
        lay.addWidget(self.lab0)

        # 30fps定时器刷新画面
        self.tim = QTimer()
        self.tim.timeout.connect(self.update_frame)
        self.tim.start(33)

    def update_frame(self):
        # 获取原始画面
        arr0 = self.p2_0.capture_array()
        # ==========关键：180度旋转转正画面（上下+左右翻转，适配倒装摄像头）==========
        #arr0 = cv2.flip(arr0, -1)
        self.set_img(arr0,self.lab0)

    def set_img(self,arr,lab):
        # BGR转RGB给Qt渲染
        rgb = cv2.cvtColor(arr,cv2.COLOR_BGR2RGB)
        h,w,ch = rgb.shape
        qimg = QImage(rgb.data,w,h,ch*w,QImage.Format.Format_RGB888)
        lab.setPixmap(QPixmap.fromImage(qimg))

if __name__=="__main__":
    app = QApplication(sys.argv)
    win = Win()
    win.show()
    sys.exit(app.exec())