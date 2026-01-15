import keyboard
import time
import datetime

print("--- 热键功能最小化测试 ---")
print("这个脚本只测试F9热键是否能被监听到。")
print("请不要运行其他脚本，只运行这一个。")

def on_f9_pressed():
    # 获取当前时间并打印
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"✅ F9 热键在 {current_time} 被成功按下了！")

# 注册F9热键
keyboard.add_hotkey('f9', on_f9_pressed)

print("\n🔥 热键F9已注册。现在脚本将持续运行，等待你按下F9...")
print("请开始测试。按 Ctrl+C 退出脚本。")

# 让脚本持续运行
while True:
    time.sleep(1)