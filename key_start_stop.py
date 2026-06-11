#!/usr/bin/env python3
import RPi.GPIO as GPIO
import subprocess
import os
import time
import signal

# 配置
KEY_POWER = 26    # 启停按键
KEY_MODE  = 19    # 模式切换按键
APP_PATH = "/home/kongbin/test/danshuangqiehuan.py"
PY_CMD = "python3"

# 初始化GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(KEY_POWER, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(KEY_MODE,  GPIO.IN, pull_up_down=GPIO.PUD_UP)

def is_app_running():
    """检查主程序是否在运行"""
    try:
        res = subprocess.run(["pgrep","-f",APP_PATH], capture_output=True, text=True)
        return res.returncode == 0
    except Exception:
        return False

def toggle_app():
    """启停主程序"""
    if is_app_running():
        subprocess.run(["pkill","-f",APP_PATH])
    else:
        subprocess.Popen([PY_CMD,APP_PATH], cwd=os.path.dirname(APP_PATH))

def send_switch_mode():
    """给主程序发送SIGUSR1信号，触发模式切换"""
    if is_app_running():
        try:
            pid = subprocess.check_output(["pgrep","-f",APP_PATH], text=True).strip().split()[0]
            subprocess.run(["pkill","-USR1",pid])
        except Exception:
            pass

def debounce_input(pin):
    """按键消抖，按下松开后返回True"""
    if GPIO.input(pin) == 0:
        time.sleep(0.02)
        if GPIO.input(pin) == 0:
            while GPIO.input(pin) == 0:
                time.sleep(0.01)
            return True
    return False

try:
    while True:
        if debounce_input(KEY_POWER):
            toggle_app()

        if debounce_input(KEY_MODE):
            send_switch_mode()

        time.sleep(0.05)

except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()