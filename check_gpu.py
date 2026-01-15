#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU检测工具 - 检查系统是否支持GPU加速
"""

def check_gpu_support():
    """检查GPU支持情况"""
    print("🔍 正在检测GPU支持情况...")
    print("=" * 50)
    
    # 检查CUDA
    try:
        import torch
        if torch.cuda.is_available():
            print("✅ CUDA可用")
            print(f"   GPU数量: {torch.cuda.device_count()}")
            for i in range(torch.cuda.device_count()):
                gpu_name = torch.cuda.get_device_name(i)
                print(f"   GPU {i}: {gpu_name}")
        else:
            print("❌ CUDA不可用")
    except ImportError:
        print("⚠️ PyTorch未安装，无法检测CUDA")
    
    print("-" * 50)
    
    # 检查EasyOCR GPU支持
    try:
        import easyocr
        print("✅ EasyOCR已安装")
        
        # 尝试GPU模式
        try:
            print("🔄 测试EasyOCR GPU模式...")
            reader = easyocr.Reader(['en'], gpu=True, verbose=False)
            print("✅ EasyOCR GPU模式可用")
            
            # 检查设备信息
            if hasattr(reader, 'device'):
                print(f"   设备: {reader.device}")
            
        except Exception as e:
            print(f"❌ EasyOCR GPU模式不可用: {e}")
            print("🔄 测试EasyOCR CPU模式...")
            try:
                reader = easyocr.Reader(['en'], gpu=False, verbose=False)
                print("✅ EasyOCR CPU模式可用")
            except Exception as cpu_e:
                print(f"❌ EasyOCR CPU模式也不可用: {cpu_e}")
                
    except ImportError:
        print("❌ EasyOCR未安装")
        print("   请运行: pip install easyocr")
    
    print("=" * 50)
    
    # 给出建议
    print("💡 建议:")
    try:
        import torch
        if torch.cuda.is_available():
            print("   ✅ 您的系统支持GPU加速，OCR识别速度会更快")
        else:
            print("   ⚠️ 您的系统不支持GPU加速，将使用CPU模式")
            print("   💡 如需GPU加速，请确保:")
            print("      1. 安装了NVIDIA显卡")
            print("      2. 安装了CUDA驱动")
            print("      3. 安装了支持CUDA的PyTorch")
    except ImportError:
        print("   ⚠️ 无法检测GPU支持，建议安装PyTorch")

if __name__ == "__main__":
    check_gpu_support()
    input("\n按回车键退出...")
