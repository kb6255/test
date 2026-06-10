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
    '''
# 导入树莓派GPIO控制库，用于读取按键电平
import RPi.GPIO as GPIO
# 导入子进程模块，用来启停、查询、杀死主程序
import subprocess
# 导入系统模块，此处用于文件操作（切换标记文件）
import os
# 导入时间模块，用于按键消抖、延时等待
import time

# ===================== 全局配置区 =====================
KEY_POWER = 26    # 开关机按键，对应树莓派BCM编号26
KEY_MODE  = 19    # 画面切换按键，对应树莓派BCM编号19
APP_PATH = "/home/kongbin/test/danshuangqiehuan.py"  # 主程序完整路径
PY_CMD = "python3"  # 调用python3解释器的命令

# ===================== GPIO初始化 =====================
# 设置GPIO编号模式为 BCM 编码（树莓派标准引脚编码方式）
GPIO.setmode(GPIO.BCM)
# 将开关机引脚设置为【上拉输入模式】
# 引脚默认高电平，按键按下时电平拉低
GPIO.setup(KEY_POWER, GPIO.IN, pull_up_down=GPIO.PUD_UP)
# 将画面切换引脚同样设置为上拉输入模式
GPIO.setup(KEY_MODE,  GPIO.IN, pull_up_down=GPIO.PUD_UP)

# ===================== 自定义函数：检测主程序是否正在运行 =====================
def is_app_running():
    # pgrep -f 查找包含主程序路径的进程
    # capture_output=True：捕获命令输出；text=True：输出转为文本格式
    res = subprocess.run(["pgrep", "-f", "python3.*danshuangqiehuan.py"],capture_output=True,text=True)
    # 返回值规则：找到进程返回0，未找到返回非0
    # 函数最终返回布尔值：True=程序在运行，False=程序未运行
    return res.returncode == 0

# ===================== 自定义函数：发送画面切换指令 =====================
def send_switch_mode():
    # 在/tmp目录创建空标记文件 cam_switch.flag
    # 主程序会轮询检测该文件，存在则执行画面切换，随后删除文件
    open("/tmp/cam_switch.flag","w").close()

# ===================== 主循环：持续轮询按键状态 =====================
while True:
    # ===== 第一路按键：开关机按键(BCM26) 逻辑 =====
    # 检测引脚电平是否为低电平（按键按下）
    if GPIO.input(KEY_POWER) == 0:
        time.sleep(0.02)  # 延时20ms，软件消抖，过滤机械按键抖动干扰
        # 二次确认按键确实按下（消抖校验）
        if GPIO.input(KEY_POWER) == 0:
            # 循环等待，直到按键松开，避免长按重复触发
            while GPIO.input(KEY_POWER)==0:
                time.sleep(0.01)
            
            # 判断当前主程序运行状态
            if is_app_running():
                # 程序正在运行：执行pkill，终止主程序
                subprocess.run(["pkill","-f",APP_PATH])
            else:
                # 程序未运行：调用python3，后台启动主程序
                # cwd 指定工作目录为主程序所在文件夹
                subprocess.Popen([PY_CMD,APP_PATH],cwd=os.path.dirname(APP_PATH))

    # ===== 第二路按键：画面切换按键(BCM19) 逻辑 =====
    # 检测引脚电平是否为低电平（按键按下）
    if GPIO.input(KEY_MODE) == 0:
        time.sleep(0.02)  # 20ms软件消抖
        # 二次确认按键按下
        if GPIO.input(KEY_MODE) == 0:
            # 等待按键松开
            while GPIO.input(KEY_MODE)==0:
                time.sleep(0.01)
            # 仅当主程序运行时，才生成切换标记文件
            if is_app_running():
                send_switch_mode()

    # 主循环休眠50ms，降低CPU占用，持续轮询按键
    time.sleep(0.05)