#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金条管家 v1.1 - 简洁启动器
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
from log import setup_logger
from tkinter import Toplevel
import urllib.request
import hashlib
import requests
import zipfile
from tkinter import filedialog
import importlib.metadata

# --- 日志配置 ---
logger = setup_logger(__name__, 'launcher.log')

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
        self.root.title("金条管家 v1.1 - 简洁启动器")
        
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

        # 启动时检查依赖
        self.root.after(100, self.check_dependencies)

    
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
                              text="金条管家 v1.1",
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
            ("导出日志", self.export_logs, self.colors['accent']),
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
        log_message = f"[{timestamp}] {message}"
        
        # 使用标准logger记录日志
        logger.info(message)

        # 更新UI
        self.log_text.insert(tk.END, log_message + "\n")
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
            self.server_process = subprocess.Popen([sys.executable, app_path], creationflags=creation_flags, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, encoding='utf-8', errors='ignore')
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
                encoding='utf-8',
                errors='ignore'
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
        # --- 新增：启动后延时检查服务状态 ---
        self.root.after(15000, self.check_startup_success) # 15秒后检查

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

    def export_logs(self):
        """将核心日志文件打包成zip"""
        self.log("正在导出日志文件...")
        try:
            log_files = ['app.log', 'scanner.log', 'launcher.log']
            
            # 创建 downloads 目录（如果不存在）
            downloads_dir = 'downloads'
            if not os.path.exists(downloads_dir):
                os.makedirs(downloads_dir)

            zip_filename = f"log_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            zip_filepath = os.path.join(downloads_dir, zip_filename)

            with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for log_file in log_files:
                    log_path = os.path.join('logs', log_file)
                    if os.path.exists(log_path):
                        zipf.write(log_path, arcname=log_file)
                        self.log(f"已添加 {log_file} 到压缩包。")
                    else:
                        self.log(f"警告: 未找到日志文件 {log_file}，已跳过。")
            
            self.log(f"日志导出成功！已保存至: {zip_filepath}")
            messagebox.showinfo("导出成功", f"日志已成功导出到 {zip_filepath}")

        except Exception as e:
            self.log(f"导出日志失败: {e}")
            messagebox.showerror("导出失败", f"导出日志时发生错误: {e}")

    def check_startup_success(self):
        """检查服务是否都成功启动"""
        # 仅在“一键启动”后执行一次
        if not self.services_started:
            return

        server_ok = "运行中" in self.server_status.cget("text")
        scanner_ok = "运行中" in self.scanner_status.cget("text")

        if not (server_ok and scanner_ok):
            self.log("启动失败：一个或多个服务未能成功运行。")
            messagebox.showerror("启动失败", "一个或多个服务未能成功运行。\n将自动为您导出日志文件以便分析问题。")
            self.export_logs()
        else:
            self.log("所有服务均已成功启动。")
        
        # 将此标志位重置，防止重复检查
        self.services_started = False

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

    def check_dependencies(self):
        """检查所有必需的Python包是否已安装。"""
        self.log("正在检查依赖包完整性...")
        missing_packages = []
        try:
            with open('requirements.txt', 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    # 解析包名，例如 "Flask==3.0.3" -> "Flask"
                    package_name = line.split('==')[0].split('>=')[0].split('<=')[0].strip()
                    try:
                        # 对于特殊包名进行映射
                        if package_name.lower() == 'opencv-python-headless':
                            importlib.metadata.version('opencv-python-headless')
                        elif package_name.lower() == 'flask-socketio':
                            importlib.metadata.version('Flask-SocketIO')
                        else:
                            importlib.metadata.version(package_name)
                    except importlib.metadata.PackageNotFoundError:
                        missing_packages.append(package_name)
        except FileNotFoundError:
            messagebox.showerror("严重错误", "找不到 requirements.txt 文件！程序无法继续运行。")
            self.root.destroy()
            return
        except Exception as e:
            messagebox.showerror("错误", f"检查依赖时发生未知错误: {e}")
            return

        if missing_packages:
            msg = "检测到以下必需的组件未安装：\n\n" + "\n".join(missing_packages) + "\n\n是否立即开始自动安装？"
            if messagebox.askyesno("依赖缺失", msg):
                self.install_dependencies()
                messagebox.showinfo("正在安装", "已在新的命令窗口中开始安装依赖库。\n安装完成后，请关闭该窗口并重启本程序。")
                self.root.destroy() # 退出当前程序
            else:
                messagebox.showwarning("警告", "缺少必要的组件，程序可能无法正常运行。")
        else:
            self.log("依赖包完整性检查通过。")

    def install_dependencies(self):
        """打开一个新的终端来安装依赖。"""
        self.log("正在启动依赖安装程序...")
        try:
            # 使用 start cmd /k 在新窗口中执行命令，并保持窗口打开
            # 添加了更俏皮的提示信息
            success_message = "所有依赖都已安装完毕！现在您可以关闭这个窗口，然后重新启动我啦~"
            command = f'start cmd /k "{sys.executable} -m pip install -r requirements.txt && echo. && echo {success_message} && pause"'
            subprocess.Popen(command, shell=True)
        except Exception as e:
            messagebox.showerror("安装失败", f"无法启动安装程序: {e}")

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
            elif "EASYOCR_MODELS_MISSING" in line:
                self.root.after(0, self.show_model_downloader)
            elif line: # 记录扫描器的其他输出
                logger.info(f"{line}") # 直接记录纯净消息
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
            log_line = f"[{name}] {line.strip()}"
            logger.info(log_line)
            self.root.after(0, self.log, log_line)
        if process.stdout:
            process.stdout.close()

    def show_model_downloader(self):
        """显示EasyOCR模型下载器窗口"""
        self.log("检测到EasyOCR模型文件缺失，正在启动下载器...")
        downloader = EasyOCRDownloaderWindow(self.root, self)
        downloader.grab_set() # 模态窗口

# ==================== EasyOCR 下载器窗口 ====================

class EasyOCRDownloaderWindow(Toplevel):
    def __init__(self, parent, launcher_instance):
        super().__init__(parent)
        self.parent = parent
        self.launcher = launcher_instance
        self.colors = self.launcher.colors
        self.title("EasyOCR 模型下载器")
        self.geometry("500x200")
        self.resizable(False, False)
        self.configure(bg=self.colors['bg_secondary'])
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.create_widgets()
        self.start_download_thread()

    def create_widgets(self):
        main_frame = tk.Frame(self, bg=self.colors['bg_secondary'], padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.status_label = tk.Label(main_frame, text="正在准备下载...", font=('Microsoft YaHei UI', 11), fg=self.colors['text'], bg=self.colors['bg_secondary'])
        self.status_label.pack(pady=(0, 10))

        self.progress_bar = ttk.Progressbar(main_frame, orient='horizontal', length=400, mode='determinate')
        self.progress_bar.pack(pady=10)

        self.progress_label = tk.Label(main_frame, text="0%", font=('Microsoft YaHei UI', 10), fg=self.colors['text'], bg=self.colors['bg_secondary'])
        self.progress_label.pack(pady=5)

        self.retry_button = tk.Button(main_frame, text="重试下载", command=self.start_download_thread, state=tk.DISABLED, font=('Microsoft YaHei UI', 10, 'bold'), fg='white', bg=self.colors['warning'], relief='flat', bd=0, padx=15, pady=8)
        self.retry_button.pack(pady=(15, 0))

    def start_download_thread(self):
        self.retry_button.config(state=tk.DISABLED)
        self.status_label.config(text="正在准备下载...", fg=self.colors['text'])
        self.progress_bar['value'] = 0
        self.progress_label.config(text="0%")
        
        download_thread = threading.Thread(target=self._download_thread_target, daemon=True)
        download_thread.start()

    def _reporthook(self, block_num, block_size, total_size):
        if total_size > 0:
            percent = min(100, (block_num * block_size) / total_size * 100)
            self.parent.after(0, self.update_progress, percent)

    def update_progress(self, percent):
        self.progress_bar['value'] = percent
        self.progress_label.config(text=f"{int(percent)}%")

    def _download_thread_target(self):
        try:
            model_dir = os.path.join(os.path.expanduser('~'), '.EasyOCR', 'model')
            if not os.path.exists(model_dir):
                os.makedirs(model_dir)

            models = {
                'craft_mlt_25k.pth': ('https://github.com/JaidedAI/EasyOCR-Models/releases/download/v1.2.2/craft_mlt_25k.pth', '5822dfebd3a146a4933b4b7c8918fedc'),
                'chinese_sim.pth': ('https://github.com/JaidedAI/EasyOCR-Models/releases/download/v1.2.1/chinese_sim.pth', 'b3447d85295542bb8de5a0518bf30939'),
                'english.pth': ('https://github.com/JaidedAI/EasyOCR-Models/releases/download/v1.2.3/english.pth', '7a35c6c70845369b80893a85103a139a')
            }

            for i, (filename, (url, md5sum)) in enumerate(models.items()):
                file_path = os.path.join(model_dir, filename)
                if os.path.exists(file_path):
                    self.launcher.log(f"模型 {filename} 已存在，跳过下载。")
                    continue

                # --- 核心优化：实现主/备/备用下载通道切换 ---
                urls_to_try = [
                    (url, "官方源"),
                    (f"https://ghproxy.com/{url}", "镜像源1"), # 国内加速镜像1
                    (url.replace("github.com", "kgithub.com"), "镜像源2") # 国内加速镜像2
                ]
                
                download_success = False
                last_error = None

                for attempt_url, source_name in urls_to_try:
                    try:
                        self.parent.after(0, self.status_label.config, {'text': f"正从[{source_name}]下载: {filename}"})
                        self.parent.after(0, self.update_progress, 0)
                        
                        # 使用 requests 库进行下载，更稳定且支持超时
                        with requests.get(attempt_url, stream=True, timeout=60) as r: # 延长超时至60秒
                            r.raise_for_status()
                            total_size = int(r.headers.get('content-length', 0))
                            downloaded_size = 0
                            with open(file_path, 'wb') as f:
                                for chunk in r.iter_content(chunk_size=8192):
                                    f.write(chunk)
                                    downloaded_size += len(chunk)
                                    if total_size > 0:
                                        percent = (downloaded_size / total_size) * 100
                                        self.parent.after(0, self.update_progress, percent)
                        
                        download_success = True
                        self.launcher.log(f"从[{source_name}]下载 {filename} 成功。")
                        break # 下载成功，跳出重试循环
                    except requests.exceptions.RequestException as e:
                        self.launcher.log(f"从[{source_name}]下载失败: {e}")
                        last_error = e
                        continue # 尝试下一个源

                if not download_success:
                    raise last_error or Exception("所有下载源均尝试失败。")

                # 验证md5
                with open(file_path, 'rb') as f:
                    downloaded_md5 = hashlib.md5(f.read()).hexdigest()
                if downloaded_md5 != md5sum:
                    raise Exception(f"文件 {filename} MD5校验失败！")
                self.launcher.log(f"模型 {filename} 校验成功。")

            self.parent.after(0, self.on_download_success)

        except Exception as e:
            # 不再将原始错误信息传递给UI，只在日志中记录
            self.launcher.log(f"模型下载失败: {e}")
            # 调用on_download_failed，它现在会显示固定的引导信息
            self.parent.after(0, self.on_download_failed, str(e))

    def on_download_success(self):
        self.status_label.config(text="所有模型下载成功！正在重启扫描器...", fg=self.colors['success'])
        self.parent.after(2000, self.destroy)
        self.launcher.start_scanner()

    def on_download_failed(self, error_msg):
        final_message = "自动下载失败。\n请尝试使用网络代理后重试，或加入Q群 1056160746 获取帮助。"
        self.status_label.config(text=final_message, fg=self.colors['error'], justify=tk.CENTER)
        self.retry_button.config(state=tk.NORMAL)

    def on_closing(self):
        if messagebox.askokcancel("取消下载", "确定要取消下载吗？\n没有模型文件，扫描器将无法工作。"):
            self.destroy()

def main():
    """主函数"""
    try:
        launcher = SimpleLauncher()
        launcher.run()
    except Exception as e:
        messagebox.showerror("错误", f"启动器初始化失败: {str(e)}")

if __name__ == "__main__":
    main()
