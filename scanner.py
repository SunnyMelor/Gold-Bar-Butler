#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
明日之后金条扫描器 - 简化版
只保留金条扫描功能
"""

import pygetwindow as gw
import pyautogui
import keyboard
import requests
import json
import time
import re
import logging
import winsound
import threading
import signal
import sys
from PIL import Image, ImageEnhance, ImageFilter
import cv2
import numpy as np

# --- 修复第一处：开启日志 ---
# 配置日志输出到控制台
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
    encoding='utf-8'  # 修复：强制使用UTF-8编码，解决控制台emoji乱码问题
)

class GoldScanner:
    def __init__(self):
        self.config = self.load_config()
        self.hotkey = self.config.get('hotkey', 'f9')
        self.api_url = 'http://localhost:8080/api/record'

        self.running = True
        self.scanner_thread = None
        self.exit_event = threading.Event()
        
        # 内存管理相关
        self.scan_count = 0
        self.cleanup_interval = 50  # 每50次扫描后清理一次内存
        self.last_cleanup_time = time.time()
        self.max_memory_usage = 500 * 1024 * 1024  # 500MB内存限制
        self.last_scan_time = 0  # 用于热键防抖

        # 初始化EasyOCR
        self.init_easyocr()

        # 设置信号处理
        self.setup_signal_handlers()

        logging.info(f"EasyOCR扫描器初始化完成")
        logging.info(f"金条扫描热键: {self.hotkey.upper()}")

    def init_easyocr(self):
        """初始化EasyOCR"""
        try:
            import easyocr
            try:
                self.reader = easyocr.Reader(['ch_sim', 'en'], gpu=True)
                logging.info("EasyOCR GPU模式初始化成功")
            except Exception as gpu_error:
                logging.warning(f"GPU模式初始化失败: {gpu_error}")
                logging.info("回退到CPU模式...")
                self.reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)
                logging.info("EasyOCR CPU模式初始化成功")
        except ImportError:
            logging.error("EasyOCR未安装，请运行: pip install easyocr")
            raise
        except Exception as e:
            logging.error(f"EasyOCR初始化失败: {e}")
            raise

    def play_sound(self, sound_type="success"):
        """播放提示音
        sound_type: 'success', 'error', 'no_window', 'ocr_failed', 'network_error'
        """
        try:
            if sound_type == "success":
                # 成功：双音调上升
                winsound.Beep(1000, 200)
                time.sleep(0.1)
                winsound.Beep(1200, 200)
            elif sound_type == "no_window":
                # 未匹配窗口标题：三短音
                for _ in range(3):
                    winsound.Beep(800, 150)
                    time.sleep(0.1)
            elif sound_type == "ocr_failed":
                # OCR识别失败：低音长鸣
                winsound.Beep(300, 600)
            elif sound_type == "network_error":
                # 网络错误：双低音
                winsound.Beep(250, 300)
                time.sleep(0.1)
                winsound.Beep(250, 300)
            else:  # error 或其他
                # 一般错误：单低音
                winsound.Beep(400, 500)
        except Exception as e:
            logging.warning(f"播放提示音失败: {e}")

    def setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            logging.info(f"接收到信号 {signum}，正在安全退出...")
            self.shutdown()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, signal_handler)
    
    def shutdown(self):
        """安全关闭扫描器"""
        logging.info("🛑 开始安全关闭扫描器...")
        self.running = False
        self.exit_event.set()
        self.cleanup_scanner_resources()
        logging.info("✅ 扫描器安全关闭完成")
    
    def cleanup_scanner_resources(self):
        """清理扫描器资源"""
        try:
            # 清理EasyOCR资源
            if hasattr(self, 'reader'):
                # 显式删除reader，帮助垃圾回收
                del self.reader
                self.reader = None
            
            # 清理OpenCV资源
            cv2.destroyAllWindows()
            
            # 强制垃圾回收
            import gc
            gc.collect()
            
            logging.debug("🧹 扫描器资源清理完成")
            
        except Exception as e:
            logging.warning(f"⚠️ 资源清理时出现异常: {e}")
    
    def verify_scanner_health(self):
        """验证扫描器健康状态"""
        try:
            # 检查所有核心组件
            health_checks = [
                self.check_easyocr_status(),
                self.check_config_status(),
                hasattr(self, 'hotkey') and self.hotkey,
                hasattr(self, 'api_url') and self.api_url
            ]
            
            is_healthy = all(health_checks)
            
            if is_healthy:
                logging.debug("💚 扫描器健康检查通过")
            else:
                logging.warning("⚠️ 扫描器健康检查失败")
                
            return is_healthy
            
        except Exception as e:
            logging.error(f"❌ 扫描器健康检查异常: {e}")
            return False

    
    def load_config(self):
        """加载配置文件"""
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logging.error("配置文件 config.json 不存在")
            raise
        except json.JSONDecodeError as e:
            logging.error(f"配置文件格式错误: {e}")
            raise
    
    def extract_account_name(self, window_title):
        """从窗口标题提取账号名"""
        if " - " in window_title:
            return window_title.split(" - ")[0].strip()
        return window_title.strip()
    
    def get_active_game_window(self):
        """获取当前激活的游戏窗口"""
        try:
            active_window = gw.getActiveWindow()
            if active_window and ("明日之后" in active_window.title or "LifeAfter" in active_window.title):
                logging.info(f"检测到聚焦的游戏窗口: {active_window.title} ({active_window.width}x{active_window.height})")
                return active_window
            return None
        except Exception as e:
            logging.error(f"获取活动窗口失败: {str(e)}")
            return None
    
    def extract_number_from_text(self, text):
        """从OCR文本中提取数字"""
        # (此函数内容不变，因此省略以节约空间)
        # 此处应包含您脚本中完整的 extract_number_from_text 函数代码
        logging.info(f"原始OCR文本: '{text}'")
        cleaned_text = re.sub(r'[^\d万]', '', text)
        if '万' in cleaned_text:
            try:
                num_part = re.findall(r'(\d+\.?\d*)万', cleaned_text)
                if num_part:
                    return int(float(num_part[0]) * 10000)
            except:
                pass
        numbers = re.findall(r'\d+', cleaned_text)
        if numbers:
            return int(max(numbers, key=len))
        return None


    def extract_number_from_easyocr_result(self, results):
        """从EasyOCR结果中提取数字"""
        if not results:
            logging.warning("EasyOCR没有识别到任何文本")
            return None, ""
        all_text = " ".join([res[1] for res in results])
        quantity = self.extract_number_from_text(all_text)
        return quantity, all_text

    def preprocess_image(self, image):
        """图像预处理 - 为EasyOCR优化，增加内存管理"""
        try:
            # 转换为灰度图
            img_array = np.array(image.convert('L'))
            
            # 限制图像大小，避免内存过度使用
            height, width = img_array.shape
            max_dimension = 1200  # 限制最大尺寸
            
            if max(height, width) > max_dimension:
                scale = max_dimension / max(height, width)
                new_width = int(width * scale)
                new_height = int(height * scale)
                img_array = cv2.resize(img_array, (new_width, new_height), interpolation=cv2.INTER_AREA)
            
            # 适度放大以提高识别率
            scale_factor = 2  # 降低放大倍数，减少内存使用
            enlarged = cv2.resize(img_array, (0, 0), fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
            
            # 增强对比度
            enhanced = cv2.convertScaleAbs(enlarged, alpha=1.2, beta=3)
            
            # 轻微模糊以减少噪声
            blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
            
            return blurred
            
        except Exception as e:
            logging.error(f"图像预处理失败: {e}")
            # 返回原始图像的简单处理版本
            return np.array(image.convert('L'))
        finally:
            # 确保释放临时变量
            try:
                del img_array, enlarged, enhanced
            except:
                pass
    
    def focus_window_and_capture_gold(self, window):
        """聚焦窗口并截图OCR - 金条模式"""
        try:
            window.activate()
            time.sleep(0.2)
            resolution_key = f"{window.width}x{window.height}"
            resolutions = self.config.get('resolutions', {})
            region_config = resolutions.get(resolution_key, {}).get('gold_region')
            if not region_config:
                logging.error(f"无法找到分辨率配置: {resolution_key}")
                return None, None
            
            absolute_x = window.left + region_config[0]
            absolute_y = window.top + region_config[1]
            screenshot = pyautogui.screenshot(region=(absolute_x, absolute_y, region_config[2], region_config[3]))
            processed_image = self.preprocess_image(screenshot)
            results = self.reader.readtext(processed_image)
            return self.extract_number_from_easyocr_result(results)
        except Exception as e:
            logging.error(f"聚焦窗口和OCR过程出错: {str(e)}")
            return None, None
    
    def submit_data(self, account_name, quantity, window_title=None):
        """提交数据到服务器"""
        try:
            data = {'account_name': account_name, 'quantity': quantity, 'window_title': window_title}
            response = requests.post(self.api_url, json=data, timeout=10)
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            logging.error(f"网络请求失败: {str(e)}")
            return False
    
    def scan_gold(self):
        """扫描金条数量（简化版，合并自原on_hotkey_pressed）"""
        # --- 修复：添加热键防抖，防止一次按键触发多次扫描 ---
        now = time.time()
        if now - self.last_scan_time < 2:  # 2秒冷却时间
            logging.warning("操作过于频繁，请稍后再试...")
            return
        self.last_scan_time = now
        
        try:
            self.scan_count += 1
            
            # 定期内存清理（基于扫描次数或内存使用量）
            # --- 修复：用引擎重建替代简单的内存清理 ---
            if self.scan_count > 0 and self.scan_count % 100 == 0:  # 每100次扫描重建一次引擎
                self.reinit_easyocr_engine()
            
            active_window = self.get_active_game_window()
            if not active_window:
                logging.warning("当前没有聚焦的明日之后游戏窗口")
                self.play_sound("no_window")
                return
            
            account_name = self.extract_account_name(active_window.title)
            quantity, ocr_text = self.focus_window_and_capture_gold(active_window)
            
            if quantity is not None:
                if self.submit_data(account_name, quantity, active_window.title):
                    logging.info(f"{account_name}: {quantity} 金条 - 提交成功 (扫描次数: {self.scan_count})")
                    self.play_sound("success")
                else:
                    logging.error(f"{account_name}: 数据提交失败")
                    self.play_sound("network_error")
            else:
                logging.warning(f"{account_name}: EasyOCR识别失败 ('{ocr_text}')")
                self.play_sound("ocr_failed")
                
        except Exception as e:
            logging.error(f"❌ 扫描过程异常: {e}")
            self.play_sound("error")
    
    def reinit_easyocr_engine(self):
        """
        完全重建EasyOCR引擎，这是解决长期运行内存问题的最有效方法
        """
        logging.info("🔄 正在完全重建EasyOCR引擎以释放资源...")
        try:
            # 1. 清理旧资源
            self.cleanup_scanner_resources()
            
            # 2. 重新初始化
            self.init_easyocr()
            
            # 3. 重置扫描计数器
            self.scan_count = 0
            
            logging.info("✅ EasyOCR引擎重建成功!")
            
        except Exception as e:
            logging.error(f"❌ 重建EasyOCR引擎失败: {e}")
            # 如果重建失败，尝试安全关闭
            self.shutdown()
    
    def check_memory_usage(self):
        """检查内存使用情况"""
        try:
            import psutil
            process = psutil.Process()
            memory_usage = process.memory_info().rss
            
            return memory_usage > self.max_memory_usage
            
        except Exception:
            return False
    
    
    def start_monitoring(self):
        """开始监听热键"""
        gpu_status = "GPU加速" if hasattr(self.reader, 'device') and 'cuda' in str(self.reader.device) else "CPU模式"

        logging.info(f"EasyOCR金条管家扫描器启动")
        logging.info(f"金条扫描热键: [{self.hotkey.upper()}]")
        logging.info(f"OCR引擎: EasyOCR (深度学习) - {gpu_status}")

        # 注册热键
        # 注册热键，直接绑定扫描函数
        keyboard.add_hotkey(self.hotkey, self.scan_gold)
        
        logging.info("热键注册成功，等待触发...")
        print("SCANNER_READY", flush=True)
        
        try:
            # 使用 threading.Event.wait() 替代无限循环，显著降低CPU占用
            self.exit_event.wait()
        except KeyboardInterrupt:
            logging.info("🛑 接收到中断信号，正在安全退出...")
        finally:
            self.shutdown()
            logging.info("🔚 监听循环结束")

def main():
    """主函数 - 带自动重启功能"""
    max_restarts = 5
    restart_count = 0
    while restart_count < max_restarts:
        try:
            logging.info(f"启动扫描器 (第 {restart_count + 1} 次)")
            scanner = GoldScanner()
            scanner.start_monitoring() # 这是启动函数
            break
        except KeyboardInterrupt:
            logging.info("用户中断，程序退出")
            break
        except Exception as e:
            restart_count += 1
            logging.error(f"程序异常: {str(e)}")
            if restart_count < max_restarts:
                wait_time = min(restart_count * 5, 30)
                logging.info(f"{wait_time}秒后自动重启 (重启次数: {restart_count}/{max_restarts})")
                time.sleep(wait_time)
            else:
                logging.error(f"达到最大重启次数 ({max_restarts})，程序退出")
                input("按回车键退出...")
                break

if __name__ == "__main__":
    main()