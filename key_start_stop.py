'''
import RPi.GPIO as GPIO
import subprocess
import os
import time

# =========配置========
KEY_PIN = 26          # BCM引脚
APP_PATH = "/home/kongbin/test/danshuangqiehuan.py"
PY_CMD = "python3"

GPIO.setmode(GPIO.BCM)
# 开启内部上拉
GPIO.setup(KEY_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def is_app_running():
    # 查询进程是否存在
    res = subprocess.run(["pgrep","-f",APP_PATH],capture_output=True,text=True)
    return res.returncode == 0

while True:
    if GPIO.input(KEY_PIN) == 0:
        time.sleep(0.02)
        # 消抖，确认按下
        if GPIO.input(KEY_PIN) == 0:
            while GPIO.input(KEY_PIN)==0:
                time.sleep(0.01)
            # 按键松开触发
            if is_app_running():
                # 正在运行 → 关闭程序
                subprocess.run(["pkill","-f",APP_PATH])
            else:
                # 未运行 → 后台启动
                subprocess.Popen([PY_CMD,APP_PATH],cwd=os.path.dirname(APP_PATH))
    time.sleep(0.05)
'''
import RPi.GPIO as GPIO
import subprocess
import os
import time

# 配置
KEY_POWER = 26    #开关机按键
KEY_MODE  = 19    #画面切换按键
APP_PATH = "/home/kongbin/test/danshuangqiehuan.py"
PY_CMD = "python3"

GPIO.setmode(GPIO.BCM)
#上拉输入
GPIO.setup(KEY_POWER, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(KEY_MODE,  GPIO.IN, pull_up_down=GPIO.PUD_UP)

def is_app_running():
    res = subprocess.run(["pgrep","-f",APP_PATH],capture_output=True,text=True)
    return res.returncode == 0

def send_switch_mode():
    # 新建标记文件，主程序检测到自动切换
    open("/tmp/cam_switch.flag","w").close()

while True:
    # ===== 按键1：开关机 =====
    if GPIO.input(KEY_POWER) == 0:
        time.sleep(0.02)
        if GPIO.input(KEY_POWER) == 0:
            while GPIO.input(KEY_POWER)==0:
                time.sleep(0.01)
            if is_app_running():
                subprocess.run(["pkill","-f",APP_PATH])
            else:
                subprocess.Popen([PY_CMD,APP_PATH],cwd=os.path.dirname(APP_PATH))

    # ===== 按键2：画面模式切换 =====
    if GPIO.input(KEY_MODE) == 0:
        time.sleep(0.02)
        if GPIO.input(KEY_MODE) == 0:
            while GPIO.input(KEY_MODE)==0:
                time.sleep(0.01)
            if is_app_running():
                send_switch_mode()

    time.sleep(0.05)