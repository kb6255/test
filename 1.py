import RPi.GPIO as GPIO
import time

BUZZER_PIN = 0
GPIO.setmode(GPIO.BCM)

# 先配置输出并立刻拉高，消除浮空
GPIO.setup(BUZZER_PIN, GPIO.OUT)
GPIO.output(BUZZER_PIN, GPIO.HIGH)
time.sleep(0.5)
print("=== 初始高电平，蜂鸣器应停止 ===")
time.sleep(2)

# 循环4组长短鸣叫测试
for i in range(4):
    print(f"\n===== 第{i+1}组测试 =====")
    # 短鸣0.1s
    GPIO.output(BUZZER_PIN, GPIO.LOW)
    print("输出LOW，蜂鸣器响 0.1s")
    time.sleep(0.1)
    GPIO.output(BUZZER_PIN, GPIO.HIGH)
    print("输出HIGH，停止鸣叫，停留1秒")
    time.sleep(1)

    # 长鸣0.3s
    GPIO.output(BUZZER_PIN, GPIO.LOW)
    print("输出LOW，蜂鸣器长响 0.3s")
    time.sleep(0.3)
    GPIO.output(BUZZER_PIN, GPIO.HIGH)
    print("输出HIGH，停止鸣叫，停留1秒")
    time.sleep(1)

print("\n全部测试完成，保持高电平关闭蜂鸣器")
GPIO.output(BUZZER_PIN, GPIO.HIGH)
time.sleep(3)
GPIO.cleanup()