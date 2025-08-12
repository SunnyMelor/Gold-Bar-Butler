#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金条管家 v1.0 - Web后端服务器
提供数据存储、去重逻辑和API服务
"""

import sqlite3
import json
import os
import sys
import logging
from logging import handlers
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string, g
from flask_socketio import SocketIO
import re
import pytz
import threading


# --- 优化：统一日志配置 (支持写入logs文件夹) ---
LOGS_DIR = "logs"
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

# 使用TimedRotatingFileHandler实现日志轮转
log_file_path = os.path.join(LOGS_DIR, "app.log")
# 设置日志记录，每天轮换一次，保留7个备份
file_handler = logging.handlers.TimedRotatingFileHandler(
    log_file_path, when="midnight", interval=1, backupCount=7, encoding='utf-8'
)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
# 添加后缀，例如 .2025-08-12
file_handler.suffix = "%Y-%m-%d"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        file_handler
    ]
)

app = Flask(__name__)
socketio = SocketIO(app)

# --- 优化：统一数据库连接管理 ---
def get_db():
    """获取数据库连接，并存储在应用上下文中"""
    if 'db' not in g:
        g.db = sqlite3.connect('records.db', timeout=15)
        g.db.row_factory = sqlite3.Row  # 让查询结果可以像字典一样访问
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    """在应用上下文销毁时自动关闭数据库连接"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_database():
    """初始化数据库"""
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        # 原有的records表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                change INTEGER DEFAULT 0
            )
        ''')

        # 新增账号信息表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_name TEXT UNIQUE NOT NULL,
                group_name TEXT DEFAULT '',
                collect_level INTEGER DEFAULT 0,
                craft_level INTEGER DEFAULT 0,
                combat_level INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                weekly_fishing_done BOOLEAN DEFAULT 0,
                weekly_boss_done BOOLEAN DEFAULT 0,
                weekly_alliance_done BOOLEAN DEFAULT 0,
                weekly_points_done BOOLEAN DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                window_title TEXT DEFAULT ""
            )
        ''')

        # 创建索引以提高查询性能
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_account_timestamp ON records(account_name, timestamp DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_account_name ON accounts(account_name)')

        # 创建自动复位记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auto_reset_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reset_date TEXT NOT NULL,
                reset_time TEXT NOT NULL,
                accounts_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        ''')


        # --- 优化：简化数据库迁移 ---
        def add_column_if_not_exists(cursor, table, column_name, column_def):
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [col[1] for col in cursor.fetchall()]
            if column_name not in columns:
                logging.info(f"向表 {table} 添加新字段: {column_name}")
                cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column_name} {column_def}')

        add_column_if_not_exists(cursor, 'records', 'change', 'INTEGER DEFAULT 0')
        add_column_if_not_exists(cursor, 'accounts', 'window_title', 'TEXT DEFAULT ""')
        
        db.commit()
        logging.info("数据库初始化检查完成。")

def natural_sort_key(text):
    """自然排序键函数，确保 筑梦10 在 筑梦2 之后"""
    def convert(text):
        return int(text) if text.isdigit() else text.lower()
    return [convert(c) for c in re.split('([0-9]+)', text)]

def get_last_sunday_4am():
    """获取上一个周日凌晨3点的时间（北京时间）"""
    beijing_tz = pytz.timezone('Asia/Shanghai')
    now = datetime.now(beijing_tz)

    # 计算距离上一个周日的天数
    days_since_sunday = now.weekday() + 1  # Monday=0, Sunday=6, 所以Sunday+1=7
    if days_since_sunday == 7:  # 如果今天是周日
        if now.hour >= 3:  # 如果已经过了凌晨3点
            last_sunday = now.date()
        else:  # 如果还没到凌晨4点
            last_sunday = (now - timedelta(days=7)).date()
    else:
        last_sunday = (now - timedelta(days=days_since_sunday)).date()

    # 构造上一个周日凌晨3点的时间
    last_sunday_3am = beijing_tz.localize(datetime.combine(last_sunday, datetime.min.time().replace(hour=3)))
    return last_sunday_3am

def get_daily_reset_time():
    """获取每日重置时间点（北京时间凌晨3点）"""
    beijing_tz = pytz.timezone('Asia/Shanghai')
    now = datetime.now(beijing_tz)
    
    # 如果当前时间早于凌晨3点，则重置点是昨天的凌晨3点
    if now.hour < 3:
        reset_date = now.date() - timedelta(days=1)
    else:
        reset_date = now.date()
        
    # 构造重置时间
    reset_time = beijing_tz.localize(datetime.combine(reset_date, datetime.min.time().replace(hour=3)))
    return reset_time


def check_and_auto_reset():
    """检查是否需要自动复位任务"""
    try:
        last_sunday_4am = get_last_sunday_4am()
        reset_date = last_sunday_4am.strftime('%Y-%m-%d')

        db = get_db()
        cursor = db.cursor()

        # 检查这个周日是否已经复位过
        cursor.execute('SELECT id FROM auto_reset_log WHERE reset_date = ?', (reset_date,))
        if cursor.fetchone():
            return False

        # 执行自动复位
        cursor.execute('''
            UPDATE accounts SET
                weekly_fishing_done = 0,
                weekly_boss_done = 0,
                weekly_alliance_done = 0,
                weekly_points_done = 0,
                updated_at = ?
        ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))
        accounts_count = cursor.rowcount

        # 记录复位日志
        cursor.execute('''
            INSERT INTO auto_reset_log (reset_date, reset_time, accounts_count, created_at)
            VALUES (?, ?, ?, ?)
        ''', (
            reset_date,
            last_sunday_4am.strftime('%H:%M:%S'),
            accounts_count,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ))
        db.commit()
        logging.info(f"成功自动复位 {accounts_count} 个账号的周常任务。")
        return True

    except Exception as e:
        logging.error(f"自动复位检查失败: {e}")
        return False

def get_latest_quantity(account_name):
    """获取指定账号的最新金条数量"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('SELECT quantity FROM records WHERE account_name = ? ORDER BY timestamp DESC LIMIT 1', (account_name,))
    
    result = cursor.fetchone()
    return result['quantity'] if result else None

@app.route('/api/record', methods=['POST'])
def record_data():
    """记录数据接口 - 包含去重逻辑"""
    try:
        data = request.get_json()
        account_name = data.get('account_name')
        quantity = data.get('quantity')
        window_title = data.get('window_title', '')

        if not account_name or quantity is None:
            return jsonify({'error': '缺少必要参数'}), 400

        # 获取该账号的最新记录
        latest_quantity = get_latest_quantity(account_name)

        # 去重逻辑：只有当数量发生变化时才记录
        if latest_quantity is None or latest_quantity != quantity:
            db = get_db()
            cursor = db.cursor()
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 计算变化量
            change = quantity - (latest_quantity if latest_quantity is not None else quantity)

            # 记录金条数据
            cursor.execute(
                'INSERT INTO records (account_name, quantity, timestamp, change) VALUES (?, ?, ?, ?)',
                (account_name, quantity, timestamp, change)
            )

            # 确保账号在accounts表中存在，并更新窗口标题
            cursor.execute('SELECT id FROM accounts WHERE account_name = ?', (account_name,))
            if not cursor.fetchone():
                cursor.execute(
                    'INSERT INTO accounts (account_name, window_title, created_at, updated_at) VALUES (?, ?, ?, ?)',
                    (account_name, window_title, timestamp, timestamp)
                )
            else:
                cursor.execute(
                    'UPDATE accounts SET window_title = ?, updated_at = ? WHERE account_name = ?',
                    (window_title, timestamp, account_name)
                )

            db.commit()

            # --- 优化：发送精确的更新数据，而不是通用信号 ---
            # 1. 获取这个账号的最新变化量
            cursor.execute(
                '''
                SELECT SUM(change) as daily_change
                FROM records
                WHERE account_name = ? AND timestamp >= ?
                ''',
                (account_name, get_daily_reset_time().strftime('%Y-%m-%d %H:%M:%S'))
            )
            daily_change_result = cursor.fetchone()
            daily_change = daily_change_result['daily_change'] if daily_change_result else 0

            # 2. 获取全局的总金条和总变化
            all_dashboard_data = fetch_dashboard_data_as_list()
            total_gold = sum(item['current_quantity'] for item in all_dashboard_data)
            total_change = sum(item['change'] for item in all_dashboard_data)

            # 3. 构造精确的更新负载
            update_payload = {
                'account_name': account_name,
                'new_quantity': quantity,
                'new_change': daily_change,
                'last_update': timestamp,
                'total_gold': total_gold,
                'total_change': total_change
            }
            
            # 4. 发送精确更新信号
            socketio.emit('update_single_account', update_payload)
            return jsonify({'success': True, 'message': '数据已记录', 'changed': True})
        else:
            pass  # 数据未变化，跳过记录
            return jsonify({'success': True, 'message': '数据未变化', 'changed': False})

    except Exception as e:
        logging.error(f"记录数据时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

def fetch_dashboard_data_as_list():
    """获取仪表板数据的核心逻辑，返回列表"""
    db = get_db()
    cursor = db.cursor()
    reset_time = get_daily_reset_time()
    reset_time_str = reset_time.strftime('%Y-%m-%d %H:%M:%S')

    query = '''
        WITH DailyChanges AS (
            SELECT account_name, SUM(change) as daily_change
            FROM records
            WHERE timestamp >= ?
            GROUP BY account_name
        ),
        LatestQuantities AS (
            SELECT account_name, quantity, timestamp,
                   ROW_NUMBER() OVER(PARTITION BY account_name ORDER BY timestamp DESC) as rn
            FROM records
        )
        SELECT
            a.account_name,
            COALESCE(lq.quantity, 0) as current_quantity,
            COALESCE(dc.daily_change, 0) as change,
            lq.timestamp as last_update
        FROM accounts a
        LEFT JOIN (SELECT * FROM LatestQuantities WHERE rn = 1) lq ON a.account_name = lq.account_name
        LEFT JOIN DailyChanges dc ON a.account_name = dc.account_name
    '''

    cursor.execute(query, (reset_time_str,))
    data = cursor.fetchall()

    return [{
        'account_name': row['account_name'],
        'current_quantity': row['current_quantity'],
        'change': row['change'],
        'last_update': row['last_update'] or ''
    } for row in data]

@app.route('/api/dashboard-data')
def get_dashboard_data():
    """获取仪表板数据 - v3，基于存储的变化量"""
    try:
        data = fetch_dashboard_data_as_list()
        return jsonify(data)
    except Exception as e:
        logging.error(f"获取仪表板数据时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/history-data')
def get_history_data():
    """获取历史数据"""
    try:
        db = get_db()
        cursor = db.cursor()

        cursor.execute('SELECT account_name, quantity, timestamp FROM records ORDER BY timestamp DESC')
        records = cursor.fetchall()

        result = [{
            'account_name': r['account_name'],
            'quantity': r['quantity'],
            'timestamp': r['timestamp']
        } for r in records]

        return jsonify(result)

    except Exception as e:
        logging.error(f"获取历史数据时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

def get_accounts_data():
    """获取所有账号信息的辅助函数"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        SELECT a.account_name, a.window_title, a.group_name, a.collect_level, a.craft_level, a.combat_level,
               a.notes, a.weekly_fishing_done, a.weekly_boss_done,
               a.weekly_alliance_done, a.weekly_points_done, r.quantity, r.timestamp
        FROM accounts a
        LEFT JOIN (
            SELECT account_name, quantity, timestamp,
                   ROW_NUMBER() OVER (PARTITION BY account_name ORDER BY timestamp DESC) as rn
            FROM records
        ) r ON a.account_name = r.account_name AND r.rn = 1
    ''')
    accounts = cursor.fetchall()

    return [{
        'account_name': acc['account_name'],
        'window_title': acc['window_title'] or '',
        'group_name': acc['group_name'] or '',
        'collect_level': acc['collect_level'] or 0,
        'craft_level': acc['craft_level'] or 0,
        'combat_level': acc['combat_level'] or 0,
        'notes': acc['notes'] or '',
        'weekly_fishing_done': bool(acc['weekly_fishing_done']),
        'weekly_boss_done': bool(acc['weekly_boss_done']),
        'weekly_alliance_done': bool(acc['weekly_alliance_done']),
        'weekly_points_done': bool(acc['weekly_points_done']),
        'gold_quantity': acc['quantity'] or 0,
        'last_update': acc['timestamp'] or ''
    } for acc in accounts]

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    """获取所有账号信息"""
    try:
        check_and_auto_reset()
        return jsonify(get_accounts_data())
    except Exception as e:
        logging.error(f"获取账号信息时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    """处理客户端连接事件，发送合并后的完整数据"""
    try:
        with app.app_context():
            logging.info("客户端连接，正在准备初始数据...")
            # 1. 获取基础账号数据
            accounts_list = get_accounts_data()
            # 2. 获取包含变化量的仪表板数据
            dashboard_list = fetch_dashboard_data_as_list()

            # 3. 创建一个用于快速查找变化量的字典
            changes_map = {item['account_name']: item['change'] for item in dashboard_list}

            # 4. 合并数据，将变化量添加到每个账号中
            merged_data = []
            for account in accounts_list:
                account['change'] = changes_map.get(account['account_name'], 0)
                merged_data.append(account)
            
            # 5. 发送合并后的完整数据
            socketio.emit('initial_data', merged_data)
            logging.info("成功发送初始数据。")
        
    except Exception as e:
        logging.error(f"发送初始数据时出错: {e}")

@app.route('/api/accounts', methods=['POST'])
def update_account():
    """更新账号信息"""
    try:
        data = request.get_json()
        account_name = data.get('account_name')

        if not account_name:
            return jsonify({'error': '缺少账号名称'}), 400
        
        db = get_db()
        cursor = db.cursor()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        update_data = {
            'account_name': account_name,
            'group_name': data.get('group_name', ''),
            'collect_level': data.get('collect_level', 0),
            'craft_level': data.get('craft_level', 0),
            'combat_level': data.get('combat_level', 0),
            'notes': data.get('notes', ''),
            'weekly_fishing_done': data.get('weekly_fishing_done', False),
            'weekly_boss_done': data.get('weekly_boss_done', False),
            'weekly_alliance_done': data.get('weekly_alliance_done', False),
            'weekly_points_done': data.get('weekly_points_done', False),
            'updated_at': timestamp
        }

        cursor.execute('SELECT id FROM accounts WHERE account_name = ?', (account_name,))
        if cursor.fetchone():
            # 更新
            query = '''
                UPDATE accounts SET
                    group_name = :group_name, collect_level = :collect_level, craft_level = :craft_level,
                    combat_level = :combat_level, notes = :notes, weekly_fishing_done = :weekly_fishing_done,
                    weekly_boss_done = :weekly_boss_done, weekly_alliance_done = :weekly_alliance_done,
                    weekly_points_done = :weekly_points_done, updated_at = :updated_at
                WHERE account_name = :account_name
            '''
        else:
            # 新增
            update_data['created_at'] = timestamp
            query = '''
                INSERT INTO accounts (
                    account_name, group_name, collect_level, craft_level, combat_level, notes,
                    weekly_fishing_done, weekly_boss_done, weekly_alliance_done, weekly_points_done,
                    created_at, updated_at
                ) VALUES (
                    :account_name, :group_name, :collect_level, :craft_level, :combat_level, :notes,
                    :weekly_fishing_done, :weekly_boss_done, :weekly_alliance_done, :weekly_points_done,
                    :created_at, :updated_at
                )
            '''
        
        cursor.execute(query, update_data)
        db.commit()
        return jsonify({'success': True, 'message': '账号信息已更新'})

    except Exception as e:
        logging.error(f"更新账号信息时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts/<account_name>', methods=['DELETE'])
def delete_account(account_name):
    """删除账号及其所有历史记录"""
    try:
        db = get_db()
        cursor = db.cursor()

        # 删除历史记录
        cursor.execute('DELETE FROM records WHERE account_name = ?', (account_name,))
        records_deleted = cursor.rowcount

        # 删除账号信息
        cursor.execute('DELETE FROM accounts WHERE account_name = ?', (account_name,))
        
        db.commit()

        logging.info(f"已删除账号 {account_name}，删除了 {records_deleted} 条历史记录")
        return jsonify({
            'success': True,
            'message': f'已删除账号 {account_name} 及其 {records_deleted} 条历史记录'
        })

    except Exception as e:
        logging.error(f"删除账号时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reset-change', methods=['POST'])
def reset_change():
    """重置所有账号的当日变化"""
    try:
        db = get_db()
        cursor = db.cursor()
        reset_time_str = get_daily_reset_time().strftime('%Y-%m-%d %H:%M:%S')

        # 1. 获取所有账号的最新金条数
        cursor.execute('''
            SELECT a.account_name, lq.quantity
            FROM accounts a
            LEFT JOIN (
                SELECT account_name, quantity, ROW_NUMBER() OVER(PARTITION BY account_name ORDER BY timestamp DESC) as rn
                FROM records
            ) lq ON a.account_name = lq.account_name AND lq.rn = 1
        ''')
        latest_quantities = {row['account_name']: row['quantity'] for row in cursor.fetchall()}

        # 2. 删除今天的变化记录
        cursor.execute('DELETE FROM records WHERE timestamp >= ?', (reset_time_str,))
        
        # 3. 为每个账号插入一条新的基准记录
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for account_name, quantity in latest_quantities.items():
            if quantity is not None:
                cursor.execute(
                    'INSERT INTO records (account_name, quantity, timestamp, change) VALUES (?, ?, ?, ?)',
                    (account_name, quantity, timestamp, 0)
                )

        db.commit()
        
        # 4. 通过SocketIO通知前端更新
        socketio.emit('data_updated') # 发送一个通用更新信号，让前端重新加载所有数据
        
        logging.info(f"成功重置了 {len(latest_quantities)} 个账号的当日变化。")
        return jsonify({'success': True, 'message': f'成功重置 {len(latest_quantities)} 个账号的当日变化'})

    except Exception as e:
        logging.error(f"重置变化时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/auto-reset-log')
def get_auto_reset_log():
    """获取自动复位日志"""
    try:
        db = get_db()
        cursor = db.cursor()

        cursor.execute('SELECT * FROM auto_reset_log ORDER BY reset_date DESC LIMIT 10')
        logs = cursor.fetchall()

        result = [{
            'reset_date': log['reset_date'],
            'reset_time': log['reset_time'],
            'accounts_count': log['accounts_count'],
            'created_at': log['created_at']
        } for log in logs]

        return jsonify(result)

    except Exception as e:
        logging.error(f"获取自动复位日志时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500


def extract_server_name(window_title):
    """从窗口标题中提取服务器名称"""
    if window_title and ' - ' in window_title and ' - 明日之后' in window_title:
        parts = window_title.split(' - ')
        if len(parts) >= 3:
            # 服务器名是倒数第二部分
            return parts[-2].strip()
    return '未知服务器'

@socketio.on('start_export')
def handle_export_request():
    """处理来自客户端的CSV导出请求，并实时报告进度"""
    logging.info("收到CSV导出请求，开始处理...")
    try:
        import csv
        
        socketio.emit('export_progress', {'percent': 5, 'message': '正在初始化...'})
        
        # 1. 获取数据
        accounts = get_accounts_data()
        if not accounts:
            logging.warning("没有可导出的数据")
            socketio.emit('export_finished', {'success': False, 'error': '没有可导出的数据'})
            return
        
        total_accounts = len(accounts)
        logging.info(f"成功获取 {total_accounts} 条账号数据。")
        socketio.emit('export_progress', {'percent': 15, 'message': f'已获取 {total_accounts} 条账号数据...'})
        socketio.sleep(0.1)

        # 2. 准备导出目录
        export_dir = '导出数据'
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
        
        filename = f"金条数据_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        file_path = os.path.join(export_dir, filename)
        
        socketio.emit('export_progress', {'percent': 25, 'message': '正在生成CSV文件...'})
        socketio.sleep(0.1)

        # 3. 写入CSV文件
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.writer(csvfile)
            
            # 写入表头 - 只保留需要的字段
            writer.writerow(['角色名称', '金条数量', '服务器'])
            socketio.emit('export_progress', {'percent': 35, 'message': '表头已生成，正在填充数据...'})
            socketio.sleep(0.1)
            
            # 写入数据行 - 只导出需要的字段
            for i, account in enumerate(accounts):
                server_name = extract_server_name(account.get('window_title', ''))
                writer.writerow([
                    account['account_name'],
                    account['gold_quantity'],
                    server_name
                ])
                
                progress = 35 + int((i + 1) / total_accounts * 55)
                if i % 10 == 0 or i == total_accounts - 1: # 每10条或最后一条更新一次进度
                    socketio.emit('export_progress', {'percent': progress, 'message': f'正在处理: {account["account_name"]} ({i+1}/{total_accounts})'})
                    socketio.sleep(0.01)

        socketio.emit('export_progress', {'percent': 95, 'message': '数据写入完成，正在完成导出...'})
        socketio.sleep(0.1)
        
        logging.info(f"数据已成功导出到: {file_path}")
        socketio.emit('export_progress', {'percent': 100, 'message': '导出完成！'})
        socketio.emit('export_finished', {'success': True, 'path': file_path})

    except Exception as e:
        logging.error(f"生成CSV时出错: {str(e)}")
        socketio.emit('export_finished', {'success': False, 'error': str(e)})

@app.route('/')
def dashboard():
    """主仪表板页面"""
    # 每次加载主页时，检查是否需要执行每周重置
    check_and_auto_reset()
    return render_template_string(open('dashboard.html', 'r', encoding='utf-8').read())

@app.route('/history')
def history():
    """历史记录页面"""
    return render_template_string(open('history.html', 'r', encoding='utf-8').read())


if __name__ == '__main__':
    # 初始化数据库
    init_database()

    logging.info("金条管家 v1.0 服务器启动")
    logging.info("仪表板: http://localhost:8080")
    logging.info("历史记录: http://localhost:8080/history")

    # 启动Flask-SocketIO应用
    socketio.run(app, host='0.0.0.0', port=8080, debug=False)
