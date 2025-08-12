#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金条管家 v1.0 - 简洁启动器
适配心跳检测功能 + 智能保活
"""

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import threading
import time
import webbrowser
import sys
import os
import socket
from datetime import datetime

# --- 全局日志文件 (支持写入logs文件夹) ---
LOGS_DIR = "logs"
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

LOG_FILE = os.path.join(LOGS_DIR, "launcher_log.txt")
# 清空旧日志
with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write(f"--- 启动器日志 ({datetime.now()}) ---\n")

class SimpleLauncher:
    def __init__(self):
        # 简洁配色方案
        self.colors = {
            'bg_primary': '#2c3e50',      # 主背景
            'bg_secondary': '#34495e',    # 次要背景
            'accent': '#3498db',          # 主题色
            'success': '#27ae60',         # 成功色
            'warning': '#f39c12',         # 警告色
            'error': '#e74c3c',           # 错误色
            'text': '#ecf0f1',            # 文字色
        }

        self.root = tk.Tk()
        self.root.title("金条管家 v1.0 - 简洁启动器")
        
        # 设置窗口
        self.setup_window()
        
        # 进程管理
        self.server_process = None
        self.scanner_process = None
        self.server_port = 8080
        
        # 保活功能
        self.keepalive_enabled = True
        self.max_restart_attempts = 3
        self.scanner_restart_count = 0
        self.scanner_was_running = False # 修复：新增状态，防止启动时就重启
        self.services_started = False # 防止重复启动
        
        # 创建界面
        self.create_ui()

        # 扫描器定时重启
        self.scanner_restart_timer = None
        self.restart_interval_hours = 3  # 每3小时重启一次
        self.play_sound_on_next_restart = False # 修复：用于区分手动/自动重启的声音
        
        # 启动监控
        self.start_monitoring()
    
    def setup_window(self):
        """设置窗口属性"""
        window_width = 600
        window_height = 500
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.root.resizable(False, False)
        self.root.configure(bg=self.colors['bg_primary'])
    
    def create_ui(self):
        """创建用户界面"""
        # 主容器
        main_frame = tk.Frame(self.root, bg=self.colors['bg_primary'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # 标题
        title_label = tk.Label(main_frame, 
                              text="金条管家 v1.0",
                              font=('Microsoft YaHei UI', 20, 'bold'),
                              fg=self.colors['text'],
                              bg=self.colors['bg_primary'])
        title_label.pack(pady=(0, 10))
        
        subtitle_label = tk.Label(main_frame, 
                                 text="简洁启动器 • 心跳检测 • 智能保活", 
                                 font=('Microsoft YaHei UI', 10),
                                 fg=self.colors['accent'],
                                 bg=self.colors['bg_primary'])
        subtitle_label.pack(pady=(0, 30))
        
        # 状态显示
        self.create_status_section(main_frame)
        
        # 控制按钮
        self.create_control_section(main_frame)
        
        # 日志区域
        self.create_log_section(main_frame)
        
        # 状态栏
        self.create_status_bar(main_frame)
    
    def create_status_section(self, parent):
        """创建状态显示区域"""
        status_frame = tk.LabelFrame(parent, text="服务状态", 
                                    font=('Microsoft YaHei UI', 12, 'bold'),
                                    fg=self.colors['text'],
                                    bg=self.colors['bg_secondary'],
                                    bd=2, relief='groove')
        status_frame.pack(fill=tk.X, pady=(0, 20))
        
        # 服务器状态
        server_frame = tk.Frame(status_frame, bg=self.colors['bg_secondary'])
        server_frame.pack(fill=tk.X, padx=15, pady=10)
        
        tk.Label(server_frame, text="Web服务器:", 
                font=('Microsoft YaHei UI', 11),
                fg=self.colors['text'], bg=self.colors['bg_secondary']).pack(side=tk.LEFT)
        
        self.server_status = tk.Label(server_frame, text="● 未启动", 
                                     font=('Microsoft YaHei UI', 11, 'bold'),
                                     fg=self.colors['error'], bg=self.colors['bg_secondary'])
        self.server_status.pack(side=tk.RIGHT)
        
        # 扫描器状态
        scanner_frame = tk.Frame(status_frame, bg=self.colors['bg_secondary'])
        scanner_frame.pack(fill=tk.X, padx=15, pady=(0, 10))
        
        tk.Label(scanner_frame, text="扫描器:", 
                font=('Microsoft YaHei UI', 11),
                fg=self.colors['text'], bg=self.colors['bg_secondary']).pack(side=tk.LEFT)
        
        self.scanner_status = tk.Label(scanner_frame, text="● 未启动", 
                                      font=('Microsoft YaHei UI', 11, 'bold'),
                                      fg=self.colors['error'], bg=self.colors['bg_secondary'])
        self.scanner_status.pack(side=tk.RIGHT)
        
        # 心跳检测状态
        heartbeat_frame = tk.Frame(status_frame, bg=self.colors['bg_secondary'])
        heartbeat_frame.pack(fill=tk.X, padx=15, pady=(0, 10))
        
        tk.Label(heartbeat_frame, text="心跳检测:", 
                font=('Microsoft YaHei UI', 11),
                fg=self.colors['text'], bg=self.colors['bg_secondary']).pack(side=tk.LEFT)
        
        self.heartbeat_status = tk.Label(heartbeat_frame, text="● 已启用", 
                                        font=('Microsoft YaHei UI', 11, 'bold'),
                                        fg=self.colors['success'], bg=self.colors['bg_secondary'])
        self.heartbeat_status.pack(side=tk.RIGHT)
    
    def create_control_section(self, parent):
        """创建控制按钮区域"""
        control_frame = tk.LabelFrame(parent, text="服务控制", 
                                     font=('Microsoft YaHei UI', 12, 'bold'),
                                     fg=self.colors['text'],
                                     bg=self.colors['bg_secondary'],
                                     bd=2, relief='groove')
        control_frame.pack(fill=tk.X, pady=(0, 20))
        
        # 主要按钮
        main_buttons = tk.Frame(control_frame, bg=self.colors['bg_secondary'])
        main_buttons.pack(fill=tk.X, padx=15, pady=15)
        
        # 一键启动
        start_btn = tk.Button(main_buttons, text="一键启动", 
                             command=self.start_all_services,
                             font=('Microsoft YaHei UI', 12, 'bold'),
                             fg='white', bg=self.colors['success'],
                             relief='flat', bd=0, padx=20, pady=10,
                             cursor='hand2')
        start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        # 停止所有
        stop_btn = tk.Button(main_buttons, text="停止所有", 
                            command=self.stop_all_services,
                            font=('Microsoft YaHei UI', 12, 'bold'),
                            fg='white', bg=self.colors['error'],
                            relief='flat', bd=0, padx=20, pady=10,
                            cursor='hand2')
        stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # 详细控制
        detail_buttons = tk.Frame(control_frame, bg=self.colors['bg_secondary'])
        detail_buttons.pack(fill=tk.X, padx=15, pady=(0, 15))
        
        buttons = [
            ("打开面板", self.open_dashboard, self.colors['accent']),
            ("重启扫描器", lambda: self.restart_scanner(manual=True), self.colors['warning']),
            ("查看日志", self.open_logs_folder, self.colors['accent']),
            ("坐标工具", self.open_coord_tool, self.colors['accent'])
        ]
        
        for i, (text, command, color) in enumerate(buttons):
            btn = tk.Button(detail_buttons, text=text, command=command,
                           font=('Microsoft YaHei UI', 10),
                           fg='white', bg=color,
                           relief='flat', bd=0, padx=15, pady=8,
                           cursor='hand2')
            btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0 if i == 0 else 2, 2 if i < len(buttons)-1 else 0))
        
        # 保活开关
        keepalive_frame = tk.Frame(control_frame, bg=self.colors['bg_secondary'])
        keepalive_frame.pack(fill=tk.X, padx=15, pady=(0, 15))
        
        self.keepalive_var = tk.BooleanVar(value=True)
        keepalive_cb = tk.Checkbutton(keepalive_frame, text="智能保活 (心跳检测间隔: 5秒)",
                                     variable=self.keepalive_var,
                                     command=self.toggle_keepalive,
                                     font=('Microsoft YaHei UI', 10),
                                     fg=self.colors['text'],
                                     bg=self.colors['bg_secondary'],
                                     selectcolor=self.colors['bg_primary'],
                                     activebackground=self.colors['bg_secondary'])
        keepalive_cb.pack()
    
    def create_log_section(self, parent):
        """创建日志区域"""
        log_frame = tk.LabelFrame(parent, text="运行日志", 
                                 font=('Microsoft YaHei UI', 12, 'bold'),
                                 fg=self.colors['text'],
                                 bg=self.colors['bg_secondary'],
                                 bd=2, relief='groove')
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 日志文本
        self.log_text = tk.Text(log_frame,
                               font=('Consolas', 9),
                               bg=self.colors['bg_primary'],
                               fg=self.colors['text'],
                               insertbackground=self.colors['text'],
                               selectbackground=self.colors['accent'],
                               relief='flat', bd=0,
                               wrap=tk.WORD, height=8)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 滚动条
        scrollbar = tk.Scrollbar(self.log_text)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.log_text.yview)
    
    def create_status_bar(self, parent):
        """创建状态栏"""
        status_bar = tk.Frame(parent, bg=self.colors['bg_secondary'], height=30)
        status_bar.pack(fill=tk.X)
        status_bar.pack_propagate(False)
        
        self.status_text = tk.Label(status_bar, text="启动器已就绪",
                                   font=('Microsoft YaHei UI', 9),
                                   fg=self.colors['text'],
                                   bg=self.colors['bg_secondary'])
        self.status_text.pack(side=tk.LEFT, padx=10, pady=5)
        
        self.time_label = tk.Label(status_bar, text="",
                                  font=('Microsoft YaHei UI', 9),
                                  fg=self.colors['accent'],
                                  bg=self.colors['bg_secondary'])
        self.time_label.pack(side=tk.RIGHT, padx=10, pady=5)
        
        self.update_time()

    # ==================== 功能方法 ====================

    def log(self, message):
        """添加日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}\n"

        # --- 新增：同时输出到控制台，以便bat启动时查看日志 ---
        print(log_message.strip())
        sys.stdout.flush()

        # --- 新增：写入日志文件 ---
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_message)

        self.log_text.insert(tk.END, log_message)
        self.log_text.see(tk.END)

        # 限制日志行数
        lines = self.log_text.get("1.0", tk.END).count('\n')
        if lines > 50:
            self.log_text.delete("1.0", "10.0")

        # 更新状态栏
        self.status_text.config(text=f"{message}")

    def update_time(self):
        """更新时间"""
        current_time = datetime.now().strftime("%H:%M:%S")
        self.time_label.config(text=current_time)
        self.root.after(1000, self.update_time)

    def check_port(self, port):
        """检查端口"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(('localhost', port))
                return result == 0
        except:
            return False

    def start_monitoring(self):
        """启动监控"""
        def monitor():
            while True:
                try:
                    # --- 改进的服务器状态检查 ---
                    server_running = self.check_port(self.server_port)
                    if server_running:
                        self.root.after(0, lambda: self.update_status("server", "运行中", self.colors['success']))
                    else:
                        # 增加启动初期的宽容度，给 waitress 足够的时间
                        # 如果服务是用户手动启动的，并且进程存在，但在启动后的15秒内端口未就绪，则显示“正在启动”
                        if self.services_started and self.server_process and self.server_process.poll() is None:
                            # 检查自启动以来经过了多长时间
                            if not hasattr(self, 'server_start_time'):
                                self.server_start_time = time.time()
                            
                            if time.time() - self.server_start_time < 15:
                                self.root.after(0, lambda: self.update_status("server", "正在启动...", self.colors['warning']))
                            else:
                                self.root.after(0, lambda: self.update_status("server", "启动失败", self.colors['error']))
                        else:
                            self.root.after(0, lambda: self.update_status("server", "未启动", self.colors['error']))

                    # 检查扫描器状态
                    if self.scanner_process and self.scanner_process.poll() is None:
                        self.root.after(0, lambda: self.update_status("scanner", "运行中", self.colors['success']))
                        
                        # 扫描器保活检查
                        if self.keepalive_enabled:
                            self.check_scanner_health()
                    else:
                        self.root.after(0, lambda: self.update_status("scanner", "未启动", self.colors['error']))
                        
                        # 自动重启扫描器 (仅当它之前在运行时)
                        if self.keepalive_enabled and self.scanner_was_running and self.scanner_restart_count < self.max_restart_attempts:
                            self.log("检测到扫描器意外停止，将自动重启...")
                            self.scanner_was_running = False # 重置状态
                            self.root.after(0, self.auto_restart_scanner)

                    time.sleep(3)  # 监控间隔3秒
                except:
                    time.sleep(5)

        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()

    def check_scanner_health(self):
        """检查扫描器健康状态"""
        # 这里可以添加更复杂的健康检查逻辑
        # 比如检查扫描器的日志输出、响应时间等
        pass

    def auto_restart_scanner(self):
        """自动重启扫描器"""
        if self.scanner_restart_count < self.max_restart_attempts:
            self.scanner_restart_count += 1
            self.log(f"自动重启扫描器 (第{self.scanner_restart_count}次)")
            self.restart_scanner(manual=False)

    def update_status(self, service, status, color):
        """更新状态显示"""
        if service == "server":
            self.server_status.config(text=f"● {status}", fg=color)
        elif service == "scanner":
            self.scanner_status.config(text=f"● {status}", fg=color)

    def toggle_keepalive(self):
        """切换保活状态"""
        self.keepalive_enabled = self.keepalive_var.get()
        if self.keepalive_enabled:
            self.log("智能保活已启用 (心跳检测: 5秒间隔)")
            self.heartbeat_status.config(text="● 已启用", fg=self.colors['success'])
        else:
            self.log("智能保活已禁用")
            self.heartbeat_status.config(text="● 已禁用", fg=self.colors['error'])

    # ==================== 服务控制 ====================

    def start_server(self):
        """启动服务器"""
        if self.server_process and self.server_process.poll() is None:
            self.log("服务器已在运行中")
            return

        try:
            self.log("正在启动Web服务器...")
            # 添加 creationflags 来隐藏窗口
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            env = os.environ.copy()
            env["PYTHONLEGACYWINDOWSSTDIO"] = "1"
            app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')
            self.server_process = subprocess.Popen([sys.executable, app_path], creationflags=creation_flags, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, encoding='utf-8')
            threading.Thread(target=self.log_subprocess_output, args=(self.server_process, "Server"), daemon=True).start()
            self.log("Web服务器进程已启动")
        except Exception as e:
            self.log(f"启动服务器失败: {str(e)}")

    def stop_server(self):
        """停止服务器"""
        if self.server_process:
            try:
                self.server_process.kill()  # 使用kill强制终止
                self.server_process = None
                self.log("Web服务器已停止")
            except Exception as e:
                self.log(f"停止服务器失败: {str(e)}")

    def start_scanner(self):
        """启动扫描器"""
        if self.scanner_process and self.scanner_process.poll() is None:
            self.log("扫描器已在运行中")
            return

        try:
            self.log("正在启动扫描器 (心跳检测已集成)...")
            # 添加 creationflags 来隐藏窗口
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            env = os.environ.copy()
            env["PYTHONLEGACYWINDOWSSTDIO"] = "1"
            # --- 优化：捕获标准输出，并隐藏窗口 ---
            scanner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scanner.py')
            self.scanner_process = subprocess.Popen(
                [sys.executable, scanner_path],
                creationflags=creation_flags,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # 修复：将stderr合并到stdout，防止死锁
                text=True,
                bufsize=1,
                env=env,
                encoding='utf-8'
            )
            # --- 优化：启动监听线程来处理输出和就绪信号 ---
            threading.Thread(target=self.listen_to_scanner, daemon=True).start()
            self.log("扫描器进程已启动，正在等待就绪信号...")
            self.scanner_restart_count = 0  # 重置重启计数
        except Exception as e:
            self.log(f"启动扫描器失败: {str(e)}")

    def stop_scanner(self):
        """停止扫描器"""
        if self.scanner_process:
            try:
                self.scanner_process.kill()  # 使用kill强制终止
                self.scanner_process = None
                self.scanner_was_running = False # 修复：用户手动停止，不算意外
                if self.scanner_restart_timer:
                    self.scanner_restart_timer.cancel()
                self.log("扫描器已停止，自动重启计时器已取消")
            except Exception as e:
                self.log(f"停止扫描器失败: {str(e)}")

    def restart_scanner(self, manual=False):
        """重启扫描器"""
        self.log("正在重启扫描器...")
        self.play_sound_on_next_restart = manual # 修复：设置标志位
        self.stop_scanner()
        time.sleep(2)
        self.start_scanner()
        self.log("扫描器重启请求已发送")
        # 提示音现在由 listen_to_scanner 在收到就绪信号后播放

    def start_all_services(self):
        """一键启动所有服务"""
        if self.services_started:
            self.log("服务已在运行中，无需重复启动。")
            return
        self.log("正在启动所有服务...")
        self.server_start_time = time.time() # 记录服务器启动时间
        self.start_server()
        # 增加等待时间，给waitress充分的初始化时间
        time.sleep(5)
        self.start_scanner()
        self.log("所有服务启动命令已发送！请观察状态指示灯。")
        self.services_started = True

    def stop_all_services(self):
        """停止所有服务"""
        self.log("正在停止所有服务...")
        self.stop_scanner()
        self.stop_server()
        self.log("所有服务已停止")

    def open_dashboard(self):
        """打开面板"""
        url = f"http://localhost:{self.server_port}"
        webbrowser.open(url)
        self.log(f"已打开主面板: {url}")

    def open_coord_tool(self):
        """打开坐标工具"""
        try:
            subprocess.Popen([sys.executable, 'get_mouse_coords.py'])
            self.log("坐标测量工具已启动")
        except Exception as e:
            self.log(f"启动坐标工具失败: {str(e)}")

    def open_logs_folder(self):
        """打开日志文件夹"""
        try:
            # 使用 os.startfile (仅限Windows) 来打开文件夹
            os.startfile(LOGS_DIR)
            self.log(f"已打开日志文件夹: {LOGS_DIR}")
        except Exception as e:
            self.log(f"打开日志文件夹失败: {str(e)}")
            messagebox.showerror("错误", f"无法打开日志文件夹: {e}")

    def on_closing(self):
        """关闭程序"""
        if messagebox.askokcancel("退出", "确定要退出启动器吗？\n\n注意：这将停止所有正在运行的服务。"):
            self.log("正在关闭启动器...")
            self.keepalive_enabled = False
            self.stop_all_services()
            if self.scanner_restart_timer:
                self.scanner_restart_timer.cancel()
            self.root.destroy()

    def run(self):
        """运行启动器"""
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.log("简洁启动器已就绪 - 心跳检测功能已集成")
        self.root.mainloop()

    # --- 修复：将以下方法移入 SimpleLauncher 类中 ---
    def listen_to_scanner(self):
        """监听扫描器进程的输出，以捕获就绪信号和日志"""
        if not self.scanner_process or not self.scanner_process.stdout:
            return

        for line in iter(self.scanner_process.stdout.readline, ''):
            if not line:
                break
            line = line.strip()
            if "SCANNER_READY" in line:
                self.root.after(0, self.on_scanner_ready)
            elif line: # 记录扫描器的其他输出
                # 修复：确保从后台线程更新UI是线程安全的
                self.root.after(0, self.log, f"[Scanner] {line}")

        # 进程结束后也清理一下
        if self.scanner_process and self.scanner_process.stdout:
            self.scanner_process.stdout.close()

    def on_scanner_ready(self):
        """当扫描器发送'Ready'信号时调用"""
        self.log("扫描器已就绪！现在可以按热键进行扫描。")
        self.update_status("scanner", "运行中", self.colors['success'])
        self.scanner_was_running = True # 修复：标记扫描器已成功运行
        if self.play_sound_on_next_restart:
            self.root.bell() # 修复：仅在手动重启时播放提示音
            self.play_sound_on_next_restart = False # 重置标志位
        # --- 启动定时重启 ---
        self.schedule_next_restart()

    def schedule_next_restart(self):
        """安排下一次扫描器重启"""
        if self.scanner_restart_timer:
            self.scanner_restart_timer.cancel()

        interval_seconds = self.restart_interval_hours * 3600
        self.scanner_restart_timer = threading.Timer(interval_seconds, self.timed_restart_scanner)
        self.scanner_restart_timer.daemon = True
        self.scanner_restart_timer.start()

        try:
            from datetime import datetime, timedelta
            next_restart_time = datetime.now() + timedelta(hours=self.restart_interval_hours)
            self.log(f"下一次扫描器自动重启安排在: {next_restart_time.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            self.log(f"无法记录下次重启时间: {e}")


    def timed_restart_scanner(self):
        """由定时器触发的重启扫描器功能"""
        if self.scanner_process and self.scanner_process.poll() is None:
            self.log("执行定时重启任务，正在重启扫描器...")
            self.root.after(0, lambda: self.restart_scanner(manual=False))
        else:
            self.log("定时重启任务跳过：扫描器未在运行。")
        # 安排下一次重启
        self.schedule_next_restart()

    def log_subprocess_output(self, process, name):
        """读取并记录子进程的输出"""
        if not process or not process.stdout:
            return
        for line in iter(process.stdout.readline, ''):
            if not line:
                break
            self.root.after(0, self.log, f"[{name}] {line.strip()}")
        if process.stdout:
            process.stdout.close()

def main():
    """主函数"""
    try:
        launcher = SimpleLauncher()
        launcher.run()
    except Exception as e:
        messagebox.showerror("错误", f"启动器初始化失败: {str(e)}")


if __name__ == "__main__":
    main()
