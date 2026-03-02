# 金条管家 v1.1 主程序运行相关文件清单

本项目是一个基于 Python 的金条数据管理和自动扫描系统。以下是运行主程序所需的核心文件：

## 1. 启动入口
- [`启动.vbs`](启动.vbs): Windows 端的静默启动脚本，负责调用 `modern_launcher.py` 并提供异常重启保活。
- [`modern_launcher.py`](modern_launcher.py): 图形化启动器（GUI），负责管理后端服务和扫描器进程，包含依赖检查、自动下载模型等功能。

## 2. 核心后端服务
- [`app.py`](app.py): 基于 Flask 和 SocketIO 的 Web 后端服务器，处理数据持久化（SQLite）、API 请求以及前端实时通信。
- [`log.py`](log.py): 统一的日志管理模块，为各组件提供标准化的日志记录功能。
- [`config.json`](config.json): 程序的配置文件，存储扫描热键、OCR 区域设置及 GPU 加速选项。
- `records.db`: (运行后生成) SQLite 数据库文件，存储所有角色和金条记录。

## 3. 扫描器组件
- [`scanner.py`](scanner.py): 基于 EasyOCR 的图像识别核心，监听热键并抓取游戏窗口进行数据采集。
- [`get_mouse_coords.py`](get_mouse_coords.py): 辅助工具，用于获取屏幕坐标以配置 `config.json` 中的扫描区域。

## 4. 前端界面 (Web UI)
后端通过 Flask 渲染以下 HTML 文件：
- [`dashboard.html`](dashboard.html): 主仪表板，实时显示各角色金条变动。
- [`history.html`](history.html): 历史记录查询页面。
- [`groups.html`](groups.html): 角色分组管理页面。
- [`days_tracker.html`](days_tracker.html): 天数追踪页面。

## 5. 环境与依赖
- [`requirements.txt`](requirements.txt): 列出了运行程序所需的 Python 第三方库（如 Flask, EasyOCR, PyAutoGUI 等）。
- `.gitignore`: 规定了无需提交到版本控制的文件（如日志、数据库、虚拟环境）。
