#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一日志模块
提供一个标准化的日志配置函数，供项目中其他模块调用。
"""

import os
import logging
from logging.handlers import TimedRotatingFileHandler
import sys

LOGS_DIR = "logs"

def setup_logger(logger_name, log_file, level=logging.INFO, subprocess_mode=False):
    """
    配置并返回一个logger实例。

    :param logger_name: logger的名称，通常是__name__
    :param log_file: 日志文件的名称 (例如 'app.log')
    :param level: 日志记录级别
    :param subprocess_mode: 如果为True，则控制台输出不带格式，以便父进程捕获和处理。
    :return: 配置好的logger实例
    """
    # 确保logs目录存在
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)

    log_path = os.path.join(LOGS_DIR, log_file)

    # 创建一个logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    # 防止重复添加handler
    if logger.hasHandlers():
        logger.handlers.clear()

    # 创建一个handler，用于写入日志文件，并实现日志轮转
    # when="midnight": 每天午夜进行轮转
    # interval=1: 每天轮转一次
    # backupCount=7: 保留最近7个日志文件
    file_handler = TimedRotatingFileHandler(
        log_path, when="midnight", interval=1, backupCount=7, encoding='utf-8'
    )
    file_handler.suffix = "%Y-%m-%d"  # 设置日志文件后缀
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)

    # 创建一个handler，用于将日志输出到控制台
    # 增加 encoding 和 errors 参数以处理Windows控制台的编码问题
    stream_handler = logging.StreamHandler(sys.stdout)
    
    # 如果是子进程模式，控制台只输出原始消息，方便父进程捕获和重新格式化
    if subprocess_mode:
        stream_formatter = logging.Formatter('%(message)s')
        stream_handler.setFormatter(stream_formatter)
    else:
        stream_handler.setFormatter(formatter)

    stream_handler.encoding = 'utf-8'
    stream_handler.errors = 'ignore'


    # 给logger添加handler
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger