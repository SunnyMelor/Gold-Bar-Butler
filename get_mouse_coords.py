#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可视化坐标测量工具 - 金条管家 v1.1
支持动态创建和编辑扫描配置 (Profile)
"""

import tkinter as tk
from tkinter import ttk, messagebox
import pyautogui
import pygetwindow as gw
import time
import threading
import json
from PIL import Image, ImageTk
import os

class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

class CoordinateSelector:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🎯 可视化坐标测量工具 v1.1")

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = int(screen_width * 0.8)
        window_height = int(screen_height * 0.8)
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.root.resizable(True, True)
        self.root.minsize(1200, 800)

        self.game_window = None
        self.is_monitoring = False
        self.selection_start = None
        self.selection_end = None
        self.current_screenshot = None
        self.config_path = 'config.json'
        self.config = self.load_config()

        self.create_widgets()
        self.start_coordinate_monitoring()

    def load_config(self):
        if not os.path.exists(self.config_path):
            messagebox.showerror("错误", f"配置文件 {self.config_path} 未找到！")
            self.root.destroy()
            return None
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def create_widgets(self):
        container = ScrollableFrame(self.root)
        container.pack(fill="both", expand=True)
        main_frame = container.scrollable_frame
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)

        title_label = ttk.Label(main_frame, text="🎯 可视化坐标测量工具 v1.1", font=('Microsoft YaHei', 20, 'bold'))
        title_label.grid(row=0, column=0, columnspan=3, pady=(10, 30), padx=10)

        config_selection_frame = ttk.LabelFrame(main_frame, text="⚙️ 配置选择", padding="15")
        config_selection_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 15), padx=10)
        config_selection_frame.columnconfigure(1, weight=1)

        ttk.Label(config_selection_frame, text="游戏窗口:", font=('Microsoft YaHei', 12)).grid(row=0, column=0, sticky=tk.W, padx=(0, 15))
        self.window_var = tk.StringVar()
        self.window_combo = ttk.Combobox(config_selection_frame, textvariable=self.window_var, state="readonly", font=('Microsoft YaHei', 11), height=8)
        self.window_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 15))
        self.window_combo.bind('<<ComboboxSelected>>', self.on_window_selected)
        refresh_btn = ttk.Button(config_selection_frame, text="🔄 刷新", command=self.refresh_windows)
        refresh_btn.grid(row=0, column=2)
        self.window_info_label = ttk.Label(config_selection_frame, text="请选择游戏窗口", foreground="gray", font=('Microsoft YaHei', 11))
        self.window_info_label.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(15, 0))

        # --- Profile 输入框 ---
        ttk.Label(config_selection_frame, text="扫描配置 (Profile):", font=('Microsoft YaHei', 12)).grid(row=2, column=0, sticky=tk.W, padx=(0, 15), pady=(15,0))
        self.profile_var = tk.StringVar()
        self.profile_entry = ttk.Entry(config_selection_frame, textvariable=self.profile_var, font=('Microsoft YaHei', 11))
        self.profile_entry.grid(row=2, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=(15,0))

        control_frame = ttk.LabelFrame(main_frame, text="📊 控制面板", padding="15")
        control_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(10, 15))
        control_frame.configure(width=400)

        coord_frame = ttk.LabelFrame(control_frame, text="📍 实时坐标", padding="15")
        coord_frame.pack(fill=tk.X, pady=(0, 15))
        self.screen_coord_label = ttk.Label(coord_frame, text="屏幕坐标: (0, 0)", font=('Consolas', 14, 'bold'))
        self.screen_coord_label.pack(anchor=tk.W, pady=(0, 8))
        self.relative_coord_label = ttk.Label(coord_frame, text="相对坐标: (0, 0)", font=('Consolas', 14, 'bold'))
        self.relative_coord_label.pack(anchor=tk.W)

        selection_frame = ttk.LabelFrame(control_frame, text="🎯 区域选择", padding="15")
        selection_frame.pack(fill=tk.X, pady=(0, 15))
        ttk.Label(selection_frame, text="左上角:", font=('Microsoft YaHei', 12, 'bold')).pack(anchor=tk.W)
        self.start_coord_label = ttk.Label(selection_frame, text="未选择", font=('Consolas', 13), foreground="gray")
        self.start_coord_label.pack(anchor=tk.W, padx=(25, 0), pady=(5, 10))
        ttk.Label(selection_frame, text="右下角:", font=('Microsoft YaHei', 12, 'bold')).pack(anchor=tk.W)
        self.end_coord_label = ttk.Label(selection_frame, text="未选择", font=('Consolas', 13), foreground="gray")
        self.end_coord_label.pack(anchor=tk.W, padx=(25, 0), pady=(5, 10))
        ttk.Label(selection_frame, text="区域大小:", font=('Microsoft YaHei', 12, 'bold')).pack(anchor=tk.W)
        self.size_label = ttk.Label(selection_frame, text="0 x 0", font=('Consolas', 13), foreground="gray")
        self.size_label.pack(anchor=tk.W, padx=(25, 0), pady=(5, 0))

        region_type_frame = ttk.LabelFrame(control_frame, text="🔧 设置目标区域", padding="15")
        region_type_frame.pack(fill=tk.X, pady=(0, 15))
        self.region_type_var = tk.StringVar(value="gold")
        ttk.Radiobutton(region_type_frame, text="上下文区域 (Context)", variable=self.region_type_var, value="context").pack(anchor=tk.W)
        ttk.Radiobutton(region_type_frame, text="金条区域 (Gold)", variable=self.region_type_var, value="gold").pack(anchor=tk.W)

        button_frame = ttk.Frame(control_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))
        style = ttk.Style()
        style.configure('Large.TButton', font=('Microsoft YaHei', 11), padding=(10, 8))
        style.configure('Save.TButton', font=('Microsoft YaHei', 12, 'bold'), padding=(10, 10))
        self.capture_btn = ttk.Button(button_frame, text="📸 刷新预览", command=self.capture_screenshot, style='Large.TButton')
        self.capture_btn.pack(fill=tk.X, pady=(0, 8))
        self.clear_btn = ttk.Button(button_frame, text="🗑️ 清除选择", command=self.clear_selection, style='Large.TButton')
        self.clear_btn.pack(fill=tk.X, pady=(0, 8))
        self.save_btn = ttk.Button(button_frame, text="💾 保存/新建 Profile", command=self.save_config, style='Save.TButton')
        self.save_btn.pack(fill=tk.X, pady=(15, 0))

        preview_frame = ttk.LabelFrame(main_frame, text="🖼️ 实时预览 (点击拖拽选择区域)", padding="15")
        preview_frame.grid(row=2, column=1, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 10))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(preview_frame, bg="lightgray", width=800, height=600)
        self.canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        v_scrollbar_preview = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        v_scrollbar_preview.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.canvas.configure(yscrollcommand=v_scrollbar_preview.set)
        h_scrollbar_preview = ttk.Scrollbar(preview_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        h_scrollbar_preview.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.canvas.configure(xscrollcommand=h_scrollbar_preview.set)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

        self.refresh_windows()

    def refresh_windows(self):
        windows = gw.getAllWindows()
        game_windows = [w for w in windows if "明日之后" in w.title and w.visible and w.width > 100 and w.height > 100 and "资源管理器" not in w.title]
        game_windows.sort(key=lambda w: w.width * w.height, reverse=True)
        self.game_windows = game_windows
        self.window_combo['values'] = [f"{w.title} ({w.width}x{w.height})" for w in game_windows]
        if game_windows:
            self.window_combo.current(0)
            self.on_window_selected()
        else:
            messagebox.showwarning("警告", "未找到明日之后游戏窗口！")

    def on_window_selected(self, event=None):
        if not self.game_windows: return
        selected_index = self.window_combo.current()
        if selected_index < 0: return
        self.game_window = self.game_windows[selected_index]
        self.window_info_label.config(text=f"✅ 窗口: {self.game_window.title}\n📏 大小: {self.game_window.width}x{self.game_window.height}", foreground="black")
        self.capture_screenshot()

    def start_coordinate_monitoring(self):
        self.is_monitoring = True
        threading.Thread(target=self.coordinate_monitor_loop, daemon=True).start()

    def coordinate_monitor_loop(self):
        while self.is_monitoring:
            try:
                if self.game_window:
                    mx, my = pyautogui.position()
                    rx, ry = mx - self.game_window.left, my - self.game_window.top
                    self.root.after(0, self.update_coordinate_display, mx, my, rx, ry)
                time.sleep(0.1)
            except Exception:
                time.sleep(1)

    def update_coordinate_display(self, sx, sy, rx, ry):
        self.screen_coord_label.config(text=f"屏幕坐标: ({sx:4d}, {sy:4d})")
        color = "green" if self.game_window and 0 <= rx <= self.game_window.width and 0 <= ry <= self.game_window.height else "red"
        self.relative_coord_label.config(text=f"相对坐标: ({rx:4d}, {ry:4d})", foreground=color)

    def capture_screenshot(self):
        if not self.game_window:
            messagebox.showwarning("警告", "请先选择游戏窗口！")
            return
        try:
            self.game_window.activate()
            time.sleep(0.2)
            self.current_screenshot = pyautogui.screenshot(region=(self.game_window.left, self.game_window.top, self.game_window.width, self.game_window.height))
            self.display_screenshot()
        except Exception as e:
            messagebox.showerror("错误", f"截图失败: {str(e)}")

    def display_screenshot(self):
        if not self.current_screenshot: return
        
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        img_width, img_height = self.current_screenshot.size
        aspect = img_width / img_height

        if canvas_width / aspect <= canvas_height:
            disp_w, disp_h = canvas_width, int(canvas_width / aspect)
        else:
            disp_w, disp_h = int(canvas_height * aspect), canvas_height
        
        resized = self.current_screenshot.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(resized)
        
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.draw_selection_box()

    def on_canvas_click(self, event):
        if not self.current_screenshot: return
        ax, ay = self.get_actual_coords(event.x, event.y)
        self.selection_start = (ax, ay)
        self.selection_end = None
        self.start_coord_label.config(text=f"({ax}, {ay})", foreground="green")
        self.end_coord_label.config(text="拖拽中...", foreground="gray")
        self.draw_selection_box()

    def on_canvas_drag(self, event):
        if not self.selection_start: return
        ax, ay = self.get_actual_coords(event.x, event.y)
        self.selection_end = (ax, ay)
        self.end_coord_label.config(text=f"({ax}, {ay})", foreground="green")
        self.update_selection_info()
        self.draw_selection_box()

    def on_canvas_release(self, event):
        if not self.selection_start: return
        self.on_canvas_drag(event)

    def get_actual_coords(self, canvas_x, canvas_y):
        if not self.current_screenshot: return 0, 0
        
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        img_width, img_height = self.current_screenshot.size
        aspect = img_width / img_height

        if canvas_width / aspect <= canvas_height:
            disp_w, disp_h = canvas_width, int(canvas_width / aspect)
        else:
            disp_w, disp_h = int(canvas_height * aspect), canvas_height
            
        scale_x = img_width / disp_w
        scale_y = img_height / disp_h
        
        return int(self.canvas.canvasx(canvas_x) * scale_x), int(self.canvas.canvasy(canvas_y) * scale_y)

    def clear_selection(self):
        self.selection_start = self.selection_end = None
        self.start_coord_label.config(text="未选择", foreground="gray")
        self.end_coord_label.config(text="未选择", foreground="gray")
        self.size_label.config(text="0 x 0", foreground="gray")
        self.draw_selection_box()

    def update_selection_info(self):
        if self.selection_start and self.selection_end:
            w = abs(self.selection_end[0] - self.selection_start[0])
            h = abs(self.selection_end[1] - self.selection_start[1])
            self.size_label.config(text=f"{w} x {h}", foreground="blue")

    def get_canvas_scale(self):
        if not self.current_screenshot: return 1.0, 1.0
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        img_width, img_height = self.current_screenshot.size
        aspect = img_width / img_height
        if canvas_width / aspect <= canvas_height:
            disp_w, disp_h = canvas_width, int(canvas_width / aspect)
        else:
            disp_w, disp_h = int(canvas_height * aspect), canvas_height
        return disp_w / img_width, disp_h / img_height

    def draw_selection_box(self):
        self.canvas.delete("selection")
        if self.selection_start and self.selection_end:
            scale_x, scale_y = self.get_canvas_scale()
            x1, y1 = min(self.selection_start[0], self.selection_end[0]) * scale_x, min(self.selection_start[1], self.selection_end[1]) * scale_y
            x2, y2 = max(self.selection_start[0], self.selection_end[0]) * scale_x, max(self.selection_start[1], self.selection_end[1]) * scale_y
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=2, tags="selection")

    def save_config(self):
        if not self.selection_start or not self.selection_end:
            messagebox.showwarning("警告", "请先在右侧预览图中框选一个区域！")
            return
        if not self.game_window:
            messagebox.showwarning("警告", "请先选择游戏窗口！")
            return
        
        res_key = f"{self.game_window.width}x{self.game_window.height}"
        profile_name = self.profile_var.get()
        region_type_to_set = self.region_type_var.get()

        if not profile_name:
            messagebox.showerror("错误", "请在“扫描配置 (Profile)”输入框中输入一个名称！")
            return

        try:
            x1, y1 = self.selection_start
            x2, y2 = self.selection_end
            new_region = [min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)]

            if 'resolutions' not in self.config: self.config['resolutions'] = {}
            if res_key not in self.config['resolutions']: self.config['resolutions'][res_key] = {}
            if 'scan_profiles' not in self.config['resolutions'][res_key]: self.config['resolutions'][res_key]['scan_profiles'] = []

            profiles = self.config['resolutions'][res_key]['scan_profiles']
            profile_to_update = next((p for p in profiles if p.get('name') == profile_name), None)

            action = "更新"
            if not profile_to_update:
                action = "创建"
                profile_to_update = {"name": profile_name, "context_check": None, "gold_region": None}
                profiles.append(profile_to_update)

            field_name_display = ""
            if region_type_to_set == 'context':
                if 'context_check' not in profile_to_update or profile_to_update['context_check'] is None:
                    profile_to_update['context_check'] = {'keywords': [profile_name]}
                profile_to_update['context_check']['region'] = new_region
                field_name_display = "上下文区域 (context_check.region)"
            else: # 'gold'
                profile_to_update['gold_region'] = new_region
                field_name_display = "金条区域 (gold_region)"

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)

            info_text = (f"✅ 配置{action}成功！\n\n"
                         f"分辨率: {res_key}\n"
                         f"Profile: {profile_name}\n"
                         f"更新字段: {field_name_display}\n"
                         f"新坐标: {new_region}\n\n"
                         f"配置已成功写入 {self.config_path}")
            messagebox.showinfo("成功", info_text)

        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {str(e)}")

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()

    def on_closing(self):
        self.is_monitoring = False
        self.root.destroy()

def main():
    try:
        app = CoordinateSelector()
        app.run()
    except Exception as e:
        messagebox.showerror("程序启动失败", f"发生致命错误: {str(e)}")

if __name__ == "__main__":
    main()
