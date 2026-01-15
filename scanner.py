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
import winsound
import threading
from log import setup_logger
import signal
import sys
import os
from PIL import Image, ImageEnhance, ImageFilter
import cv2
import numpy as np

# --- 日志配置 ---
logger = setup_logger(__name__, 'scanner.log', subprocess_mode=True)

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
        self.last_config_mtime = 0 # 用于热加载

        # 初始化EasyOCR
        self.init_easyocr()

        # 设置信号处理
        self.setup_signal_handlers()

        logger.info(f"EasyOCR扫描器初始化完成")
        logger.info(f"金条扫描热键: {self.hotkey.upper()}")

    def init_easyocr(self):
        """初始化EasyOCR，并根据配置智能选择模式"""
        try:
            import easyocr
            use_gpu = self.config.get('use_gpu', True)

            if use_gpu:
                try:
                    self.reader = easyocr.Reader(['ch_sim', 'en'], gpu=True)
                    logger.info("EasyOCR GPU模式初始化成功")
                    # 如果配置文件是false但成功了，则更新回true
                    if not self.config.get('use_gpu'):
                        self.config['use_gpu'] = True
                        self.save_config()
                except Exception as gpu_error:
                    logger.warning(f"GPU模式初始化失败: {gpu_error}")
                    logger.warning("这可能是由于CUDA、PyTorch或NVIDIA驱动不兼容导致的。")
                    logger.info("自动切换到CPU模式，并更新配置文件...")
                    self.config['use_gpu'] = False
                    self.save_config()
                    self.reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)
                    logger.info("EasyOCR CPU模式初始化成功")
            else:
                self.reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)
                logger.info("根据配置，使用CPU模式初始化EasyOCR")

        except ImportError:
            logger.error("EasyOCR未安装，请运行: pip install easyocr")
            raise
        except Exception as e:
            logger.error(f"EasyOCR初始化失败: {e}")
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
            logger.warning(f"播放提示音失败: {e}")

    def setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            logger.info(f"接收到信号 {signum}，正在安全退出...")
            self.shutdown()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, signal_handler)
    
    def shutdown(self):
        """安全关闭扫描器"""
        logger.info("🛑 开始安全关闭扫描器...")
        self.running = False
        self.exit_event.set()
        self.cleanup_scanner_resources()
        logger.info("✅ 扫描器安全关闭完成")
    
    def cleanup_scanner_resources(self):
        """清理扫描器资源"""
        try:
            # 清理EasyOCR资源
            if hasattr(self, 'reader'):
                # 显式删除reader，帮助垃圾回收
                del self.reader
                self.reader = None
            
            # 清理OpenCV资源
            # cv2.destroyAllWindows() # 移除此行，因为它在 headless opencv 中会导致错误，并且此处不需要
            
            # 强制垃圾回收
            import gc
            gc.collect()
            
            logger.debug("🧹 扫描器资源清理完成")
            
        except Exception as e:
            logger.warning(f"⚠️ 资源清理时出现异常: {e}")
    
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
                logger.debug("💚 扫描器健康检查通过")
            else:
                logger.warning("⚠️ 扫描器健康检查失败")
                
            return is_healthy
            
        except Exception as e:
            logger.error(f"❌ 扫描器健康检查异常: {e}")
            return False

    
    def load_config(self):
        """加载配置文件，如果不存在则创建"""
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                self.last_config_mtime = os.path.getmtime('config.json')
                return config_data
        except FileNotFoundError:
            logger.warning("配置文件 config.json 未找到，将创建一个默认配置")
            default_config = {
                "hotkey": "f9",
                "use_gpu": True,
                "resolutions": {
                    "1920x1080": {
                        "scan_profiles": [
                            {
                                "name": "默认",
                                "pixel_check": null,
                                "gold_region": [850, 850, 150, 50]
                            }
                        ]
                    }
                }
            }
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            return default_config
        except json.JSONDecodeError as e:
            logger.error(f"配置文件格式错误: {e}")
            raise

    def save_config(self):
        """保存当前配置到文件"""
        try:
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.debug("配置已成功保存到 config.json")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
    
    def extract_account_name(self, window_title):
        """从窗口标题提取账号名"""
        if " - " in window_title:
            return window_title.split(" - ")[0].strip()
        return window_title.strip()
    
    def get_active_game_window(self):
        """获取一个游戏窗口，即使它不是当前激活的窗口"""
        try:
            # 寻找所有匹配的游戏窗口，不再要求窗口必须处于激活状态
            # 这允许用户在按下热键后立即切换到其他窗口
            game_windows = gw.getWindowsWithTitle('明日之后')
            if not game_windows:
                game_windows = gw.getWindowsWithTitle('LifeAfter') # 兼容英文标题

            if game_windows:
                # 默认选择找到的第一个窗口。对于只开一个游戏窗口的用户来说，这是可靠的。
                window = game_windows[0]
                logger.info(f"检测到游戏窗口: {window.title} ({window.width}x{window.height})")
                return window
            
            return None
        except Exception as e:
            logger.error(f"获取游戏窗口失败: {str(e)}")
            return None
    
    def extract_number_from_text(self, text):
        """从OCR文本中提取数字"""
        logger.info(f"原始OCR文本: '{text}'")

        # 扩展字符替换映射，修复常见OCR错误
        char_map = {
            'O': '0', 'o': '0', '〇': '0', '○': '0',
            'I': '1', 'l': '1', '|': '1', '!': '1',
            'B': '8', 'G': '6', 'S': '5', 'Z': '2',
            'q': '9', 'g': '9', '€': '6', '£': '1',
            ' ': '', '\t': '', '\n': '', '\r': ''
        }
        
        corrected_text = text
        for wrong, right in char_map.items():
            corrected_text = corrected_text.replace(wrong, right)
        
        if corrected_text != text:
            logger.info(f"修正后文本: '{corrected_text}'")

        # 移除所有非数字字符（保留数字和“万”字）
        cleaned_text = re.sub(r'[^\d万]', '', corrected_text)
        
        # 处理“万”单位
        if '万' in cleaned_text:
            try:
                num_part = re.findall(r'(\d+\.?\d*)万', cleaned_text)
                if num_part:
                    return int(float(num_part[0]) * 10000)
            except:
                pass
        
        # 提取所有连续数字序列
        numbers = re.findall(r'\d+', cleaned_text)
        if not numbers:
            logger.warning(f"未找到数字: '{cleaned_text}'")
            return None
        
        # 选择最长的数字序列（最可能是完整的金条数量）
        longest_num = max(numbers, key=len)
        
        # 额外验证：如果最长数字长度小于4，可能是截断错误，尝试合并所有数字
        if len(longest_num) < 4 and len(numbers) > 1:
            combined = ''.join(numbers)
            if len(combined) > len(longest_num):
                logger.info(f"数字可能被分割，合并后: {combined}")
                longest_num = combined
        
        # 防止首位为0（除非数字本身就是0）
        if longest_num.startswith('0') and len(longest_num) > 1:
            longest_num = longest_num.lstrip('0')
            if not longest_num:
                longest_num = '0'
        
        try:
            return int(longest_num)
        except ValueError:
            logger.error(f"无法转换为整数: '{longest_num}'")
            return None


    def extract_number_from_easyocr_result(self, results):
        """从EasyOCR结果中提取数字"""
        if not results:
            logger.warning("EasyOCR没有识别到任何文本")
            return None, ""
        all_text = " ".join([res[1] for res in results])
        quantity = self.extract_number_from_text(all_text)
        return quantity, all_text

    def preprocess_image(self, image):
        """图像预处理 - 为EasyOCR优化，增加内存管理"""
        try:
            # 1. 转换为灰度图
            img_array = np.array(image.convert('L'))

            # 2. 图像缩放（放大以提高小字体识别率）
            scale_factor = 2.5
            enlarged = cv2.resize(img_array, (0, 0), fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_LINEAR)

            # 3. 中值滤波降噪（比高斯模糊更能保留边缘）
            denoised = cv2.medianBlur(enlarged, 3)

            # 4. 自适应直方图均衡化（增强局部对比度，效果优于全局增强）
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(denoised)

            # 5. Otsu's Binarization (自动寻找最佳阈值)
            _, binarized = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            
            return binarized
            
        except Exception as e:
            logger.error(f"图像预处理失败: {e}")
            # 返回原始图像的简单处理版本
            return np.array(image.convert('L'))
        finally:
            # 确保释放临时变量
            try:
                del img_array, enlarged, denoised, enhanced
            except:
                pass
    
    def focus_window_and_capture_gold(self, window, window_screenshot):
        """从已截取的窗口图像中，裁剪固定的金条区域进行OCR（无上下文识别）"""
        try:
            resolution_key = f"{window.width}x{window.height}"
            resolutions = self.config.get('resolutions', {})
            scan_profiles = resolutions.get(resolution_key, {}).get('scan_profiles')

            if not scan_profiles:
                logger.error(f"无法找到分辨率 {resolution_key} 的 'scan_profiles' 配置")
                return None, None

            # 选择第一个扫描配置作为固定区域（旧版固定区域选择模式）
            # 优先选择没有 context_check 的配置，否则使用第一个配置
            selected_profile = None
            for profile in scan_profiles:
                if not profile.get('context_check'):
                    selected_profile = profile
                    break
            if not selected_profile:
                selected_profile = scan_profiles[0]
                logger.warning(f"所有配置均包含上下文检查，将使用第一个配置: {selected_profile.get('name')}")

            gold_region = selected_profile.get('gold_region')
            if not gold_region:
                logger.error(f"配置 '{selected_profile.get('name')}' 中缺少 'gold_region'。")
                return None, "配置错误"

            logger.info(f"使用固定区域配置 '{selected_profile.get('name')}' 扫描金条区域: {gold_region}")
            
            # 裁剪金条区域
            gold_crop_box = (gold_region[0], gold_region[1], gold_region[0] + gold_region[2], gold_region[1] + gold_region[3])
            screenshot = window_screenshot.crop(gold_crop_box)

            # 图像预处理
            processed_image = self.preprocess_image(screenshot)
            
            # 使用 allowlist 限制只识别数字，大幅提升数字识别精度
            # detail=0 表示只返回文本和置信度，不返回位置框（简化结果）
            try:
                results = self.reader.readtext(processed_image, allowlist='0123456789', detail=0)
            except Exception as e:
                logger.warning(f"allowlist 参数可能不被支持，回退到全字符识别: {e}")
                results = self.reader.readtext(processed_image, detail=0)
            
            # 如果没有识别到任何文本，尝试不使用 allowlist 再识别一次（兼容性回退）
            if not results:
                logger.warning("使用 allowlist 未识别到文本，尝试全字符识别...")
                results = self.reader.readtext(processed_image, detail=0)
            
            # 将结果列表合并为字符串
            all_text = " ".join(results) if results else ""
            quantity = self.extract_number_from_text(all_text)
            return quantity, all_text

        except Exception as e:
            logger.error(f"图像处理和OCR过程出错: {str(e)}")
            return None, None
    
    def submit_data(self, account_name, quantity, window_title=None):
        """提交数据到服务器"""
        try:
            data = {'account_name': account_name, 'quantity': quantity, 'window_title': window_title}
            response = requests.post(self.api_url, json=data, timeout=10)
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            logger.error(f"网络请求失败: {str(e)}")
            return False
    
    def scan_gold(self):
        """扫描金条数量（简化版，合并自原on_hotkey_pressed）"""
        # --- 修复：添加热键防抖，防止一次按键触发多次扫描 ---
        now = time.time()
        if now - self.last_scan_time < 1:  # 1秒冷却时间
            logger.warning("操作过于频繁，请稍后再试...")
            return
        self.last_scan_time = now
        
        try:
            self.scan_count += 1
            
            # --- 优化：基于内存的智能引擎重建 ---
            # --- 优化：基于内存的智能引擎重建 ---
            # 每隔一段时间检查一次内存，而不是每次都检查，避免频繁重建引擎
            if self.scan_count > 0 and self.scan_count % self.cleanup_interval == 0 and self.check_memory_usage():
                self.reinit_easyocr_engine()
            
            active_window = self.get_active_game_window()
            if not active_window:
                logger.warning("未找到任何明日之后游戏窗口")
                self.play_sound("no_window")
                return

            # --- 核心优化：立即截取整个窗口，避免后续操作被切屏影响 ---
            try:
                window_screenshot = pyautogui.screenshot(region=(active_window.left, active_window.top, active_window.width, active_window.height))
                logger.debug("已成功截取整个窗口图像。")
            except Exception as e:
                logger.error(f"截取窗口图像失败: {e}")
                self.play_sound("error")
                return
            
            account_name = self.extract_account_name(active_window.title)
            # 将截图传递给处理函数
            quantity, ocr_text = self.focus_window_and_capture_gold(active_window, window_screenshot)
            
            if quantity is not None:
                if self.submit_data(account_name, quantity, active_window.title):
                    logger.info(f"{account_name}: {quantity} 金条 - 提交成功 (扫描次数: {self.scan_count})")
                    self.play_sound("success")
                    return
                else:
                    logger.error(f"{account_name}: 数据提交失败")
                    self.play_sound("network_error")
                    return
            else:
                logger.warning(f"{account_name}: EasyOCR识别失败 ('{ocr_text}')")
                self.play_sound("ocr_failed")
                return
                
        except Exception as e:
            logger.error(f"❌ 扫描过程异常: {e}")
            self.play_sound("error")
    
    def reinit_easyocr_engine(self):
        """
        完全重建EasyOCR引擎，这是解决长期运行内存问题的最有效方法
        """
        logger.info("🔄 正在完全重建EasyOCR引擎以释放资源...")
        try:
            # 1. 清理旧资源
            self.cleanup_scanner_resources()
            
            # 2. 重新初始化
            self.init_easyocr()
            
            # 3. 重置扫描计数器
            self.scan_count = 0
            
            logger.info("✅ EasyOCR引擎重建成功!")
            
        except Exception as e:
            logger.error(f"❌ 重建EasyOCR引擎失败: {e}")
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
    
    
    def reload_config(self):
        """重新加载配置并应用更改"""
        logger.info("检测到配置文件变化，正在热加载...")
        new_config = self.load_config()
        
        # 热更新热键
        old_hotkey = self.hotkey
        new_hotkey = new_config.get('hotkey', 'f9')
        
        if old_hotkey != new_hotkey:
            try:
                keyboard.remove_hotkey(old_hotkey)
                keyboard.add_hotkey(new_hotkey, self.scan_gold)
                self.hotkey = new_hotkey
                logger.info(f"热键已成功从 [{old_hotkey.upper()}] 更新为 [{new_hotkey.upper()}]")
            except Exception as e:
                logger.error(f"热更新热键失败: {e}")

        self.config = new_config
        logger.info("配置热加载完成。")

    def start_monitoring(self):
        """开始监听热键和配置文件"""
        gpu_status = "GPU加速" if hasattr(self.reader, 'device') and 'cuda' in str(self.reader.device) else "CPU模式"
 
        logger.info(f"EasyOCR金条管家扫描器启动")
        logger.info(f"金条扫描热键: [{self.hotkey.upper()}]")
        logger.info(f"OCR引擎: EasyOCR (深度学习) - {gpu_status}")
 
        # 注册热键
        keyboard.add_hotkey(self.hotkey, self.scan_gold)
        
        logger.info("热键注册成功，等待触发...")
        print("SCANNER_READY", flush=True)

        # 启动配置文件监控线程
        config_monitor_thread = threading.Thread(target=self.monitor_config_changes, daemon=True)
        config_monitor_thread.start()
        
        try:
            # 使用 threading.Event.wait() 替代无限循环，显著降低CPU占用
            self.exit_event.wait()
        except KeyboardInterrupt:
            logger.info("🛑 接收到中断信号，正在安全退出...")
        finally:
            self.shutdown()
            logger.info("🔚 监听循环结束")

    def monitor_config_changes(self):
        """后台监控配置文件变化的线程函数"""
        while self.running:
            try:
                current_mtime = os.path.getmtime('config.json')
                if current_mtime != self.last_config_mtime:
                    self.reload_config()
            except FileNotFoundError:
                logger.warning("config.json 在运行时被删除，热加载暂停。")
            except Exception as e:
                logger.error(f"监控配置文件时出错: {e}")
            
            time.sleep(3) # 每3秒检查一次

def run_scanner_main():
    """主函数 - 带自动重启功能"""
    max_restarts = 5
    restart_count = 0
    while restart_count < max_restarts:
        try:
            logger.info(f"启动扫描器 (第 {restart_count + 1} 次)")
            scanner = GoldScanner()
            scanner.start_monitoring() # 这是启动函数
            break
        except KeyboardInterrupt:
            logger.info("用户中断，程序退出")
            break
        except Exception as e:
            restart_count += 1
            logger.error(f"程序异常: {str(e)}")
            if restart_count < max_restarts:
                wait_time = min(restart_count * 5, 30)
                logger.info(f"{wait_time}秒后自动重启 (重启次数: {restart_count}/{max_restarts})")
                time.sleep(wait_time)
            else:
                logger.error(f"达到最大重启次数 ({max_restarts})，程序退出")
                # 在打包后，input会引发错误，所以注释掉
                # input("按回车键退出...")
                break

def main():
    """
    预检函数：检查EasyOCR模型是否存在。
    如果不存在，则通知启动器进行下载。
    """
    try:
        # --- 修复：使用更通用的方法定位EasyOCR模型目录 ---
        # easyocr.utils.get_model_storage_directory() 在某些版本中不存在，
        # 我们直接构建标准路径，这更可靠。
        model_dir = os.path.join(os.path.expanduser('~'), '.EasyOCR', 'model')
        
        # 对于 ['ch_sim', 'en']，需要3个核心模型文件
        required_models = ['craft_mlt_25k.pth', 'english.pth', 'chinese_sim.pth']
        
        all_models_exist = True
        for model_file in required_models:
            if not os.path.exists(os.path.join(model_dir, model_file)):
                all_models_exist = False
                logger.warning(f"EasyOCR 模型文件缺失: {model_file}")
                break
        
        if not all_models_exist:
            # 向启动器发送模型缺失信号
            print("EASYOCR_MODELS_MISSING", flush=True)
            sys.exit(0) # 正常退出，让启动器接管
        else:
            # 模型都存在，正常运行扫描器
            run_scanner_main()

    except ImportError:
        # 如果连easyocr库本身都没有，也发送信号
        print("EASYOCR_LIBRARY_MISSING", flush=True)
        sys.exit(1)
    except Exception as e:
        # 预检阶段发生其他错误
        print(f"PRE_FLIGHT_CHECK_ERROR: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()