#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金条管家 v1.1 - Web后端服务器
提供数据存储、去重逻辑和API服务
"""

import eventlet
eventlet.monkey_patch()
import sqlite3
import json
import os
import sys
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string, g
from flask_socketio import SocketIO
from log import setup_logger
import re
import pytz
import threading


# --- 日志配置 ---
logger = setup_logger(__name__, 'app.log')

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

        # 新增分组信息表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
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


        # 新增天数追踪表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS days_tracker_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_name TEXT UNIQUE NOT NULL,
                notes TEXT DEFAULT '',
                start_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')


        # --- 优化：简化数据库迁移 ---
        def add_column_if_not_exists(cursor, table, column_name, column_def):
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [col[1] for col in cursor.fetchall()]
            if column_name not in columns:
                logger.info(f"向表 {table} 添加新字段: {column_name}")
                cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column_name} {column_def}')

        add_column_if_not_exists(cursor, 'records', 'change', 'INTEGER DEFAULT 0')
        add_column_if_not_exists(cursor, 'accounts', 'window_title', 'TEXT DEFAULT ""')
        add_column_if_not_exists(cursor, 'accounts', 'banned_until', 'TEXT DEFAULT NULL')
        
        db.commit()
        logger.info("数据库初始化检查完成。")

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
        logger.info(f"成功自动复位 {accounts_count} 个账号的周常任务。")
        return True

    except Exception as e:
        logger.error(f"自动复位检查失败: {e}")
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

            # 2. 获取全局的总金条和总变化 (优化)
            totals = get_global_totals()
            total_gold = totals['total_gold']
            total_change = totals['total_change']

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
            logger.debug(f"账号 {account_name} 的数据未变化，跳过记录。")
            return jsonify({'success': True, 'message': '数据未变化', 'changed': False})

    except Exception as e:
        logger.error(f"记录数据时出错: {str(e)}")
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

def get_global_totals():
    """高效地获取全局总金条和总变化"""
    db = get_db()
    cursor = db.cursor()
    reset_time_str = get_daily_reset_time().strftime('%Y-%m-%d %H:%M:%S')

    # 一次性查询所有未封禁账号的最新金条数
    cursor.execute('''
        SELECT SUM(lq.quantity) as total_gold
        FROM (
            SELECT r.account_name, r.quantity, ROW_NUMBER() OVER(PARTITION BY r.account_name ORDER BY r.timestamp DESC) as rn
            FROM records r
            JOIN accounts a ON r.account_name = a.account_name
            WHERE a.banned_until IS NULL
        ) lq
        WHERE lq.rn = 1
    ''')
    total_gold_result = cursor.fetchone()
    total_gold = total_gold_result['total_gold'] if total_gold_result and total_gold_result['total_gold'] is not None else 0

    # 一次性查询当日未封禁账号的总变化
    cursor.execute('''
        SELECT SUM(r.change) as total_change
        FROM records r
        JOIN accounts a ON r.account_name = a.account_name
        WHERE r.timestamp >= ? AND a.banned_until IS NULL
    ''', (reset_time_str,))
    total_change_result = cursor.fetchone()
    total_change = total_change_result['total_change'] if total_change_result and total_change_result['total_change'] is not None else 0

    return {'total_gold': total_gold, 'total_change': total_change}

@app.route('/api/dashboard-data')
def get_dashboard_data():
    """获取仪表板数据 - v3，基于存储的变化量"""
    try:
        data = fetch_dashboard_data_as_list()
        return jsonify(data)
    except Exception as e:
        logger.error(f"获取仪表板数据时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/history-data')
def get_history_data():
    """获取历史数据 - 支持分页与筛选"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        account_name = request.args.get('account_name')
        date_filter = request.args.get('date')  # Format: YYYY-MM-DD

        db = get_db()
        cursor = db.cursor()

        # 构建查询
        query = 'SELECT account_name, quantity, timestamp FROM records'
        params = []
        conditions = []

        if account_name:
            conditions.append('account_name = ?')
            params.append(account_name)
        
        if date_filter:
            # 假设 timestamp 格式为 "YYYY-MM-DD HH:MM:SS"
            conditions.append('timestamp LIKE ?')
            params.append(f'{date_filter}%')

        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)

        # 获取总条数
        count_query = f"SELECT COUNT(*) FROM ({query})"
        cursor.execute(count_query, params)
        total_records = cursor.fetchone()[0]

        # 添加排序和分页
        query += ' ORDER BY timestamp DESC LIMIT ? OFFSET ?'
        params.extend([per_page, (page - 1) * per_page])

        cursor.execute(query, params)
        records = cursor.fetchall()

        data = [{
            'account_name': r['account_name'],
            'quantity': r['quantity'],
            'timestamp': r['timestamp']
        } for r in records]

        return jsonify({
            'data': data,
            'total': total_records,
            'page': page,
            'per_page': per_page,
            'has_next': (page * per_page) < total_records
        })

    except Exception as e:
        logger.error(f"获取历史数据时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

def get_accounts_data():
    """获取所有账号信息的辅助函数"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        SELECT a.account_name, a.window_title, a.group_name, a.collect_level, a.craft_level, a.combat_level,
               a.notes, a.weekly_fishing_done, a.weekly_boss_done,
               a.weekly_alliance_done, a.weekly_points_done, r.quantity, r.timestamp, a.banned_until
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
        'last_update': acc['timestamp'] or '',
        'banned_until': acc['banned_until']
    } for acc in accounts]

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    """获取所有账号信息"""
    try:
        check_and_auto_reset()
        # --- 新增：在获取数据前，先处理自动解封 ---
        auto_unban_accounts()
        return jsonify(get_accounts_data())
    except Exception as e:
        logger.error(f"获取账号信息时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/account-names', methods=['GET'])
def get_account_names():
    """获取所有账号名称列表，用于快速填充选择器"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT account_name FROM accounts ORDER BY account_name ASC')
        accounts = cursor.fetchall()
        return jsonify([acc['account_name'] for acc in accounts])
    except Exception as e:
        logger.error(f"获取账号名称列表时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    """处理客户端连接事件，发送合并后的完整数据"""
    try:
        with app.app_context():
            logger.info("客户端连接，正在准备初始数据...")
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
            logger.info("成功发送初始数据。")
        
    except Exception as e:
        logger.error(f"发送初始数据时出错: {e}")

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

        cursor.execute('SELECT * FROM accounts WHERE account_name = ?', (account_name,))
        existing_account = cursor.fetchone()

        if existing_account:
            # 更新：只更新请求中提供的字段
            update_fields = {'updated_at': timestamp}
            
            # 检查更新请求是否来自主面板（包含任务、等级、备注等信息）
            is_dashboard_update = any(k in data for k in [
                'collect_level', 'craft_level', 'combat_level', 'notes',
                'weekly_fishing_done', 'weekly_boss_done',
                'weekly_alliance_done', 'weekly_points_done'
            ])

            for key, value in data.items():
                if key != 'account_name' and key in existing_account.keys():
                    # 如果是来自主面板的更新，则忽略 group_name 字段，防止误操作覆盖分组信息
                    # 分组的修改应该只在分组页面进行
                    if key == 'group_name' and is_dashboard_update:
                        continue
                    update_fields[key] = value
            
            set_clause = ', '.join([f'{key} = ?' for key in update_fields.keys()])
            values = list(update_fields.values())
            values.append(account_name)

            query = f'UPDATE accounts SET {set_clause} WHERE account_name = ?'
            cursor.execute(query, tuple(values))

        else:
            # 新增：使用请求中的数据，并为缺失的字段提供默认值
            insert_data = {
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
                'created_at': timestamp,
                'updated_at': timestamp
            }
            
            cols = ', '.join(insert_data.keys())
            placeholders = ', '.join(['?'] * len(insert_data))
            query = f'INSERT INTO accounts ({cols}) VALUES ({placeholders})'
            cursor.execute(query, tuple(insert_data.values()))
        db.commit()
        return jsonify({'success': True, 'message': '账号信息已更新'})

    except Exception as e:
        logger.error(f"更新账号信息时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ban-account', methods=['POST'])
def ban_account():
    """封禁一个账号"""
    try:
        data = request.get_json()
        account_name = data.get('account_name')
        if not account_name:
            return jsonify({'error': '缺少 account_name 参数'}), 400

        # 计算解封时间：3天后的凌晨3点
        beijing_tz = pytz.timezone('Asia/Shanghai')
        now = datetime.now(beijing_tz)
        unban_date = now.date() + timedelta(days=3)
        unban_time = beijing_tz.localize(datetime.combine(unban_date, datetime.min.time().replace(hour=3)))
        unban_time_str = unban_time.strftime('%Y-%m-%d %H:%M:%S')

        db = get_db()
        cursor = db.cursor()
        cursor.execute('UPDATE accounts SET banned_until = ? WHERE account_name = ?', (unban_time_str, account_name))
        db.commit()

        logger.info(f"账号 {account_name} 已被封禁，解封时间: {unban_time_str}")
        return jsonify({'success': True, 'banned_until': unban_time_str})

    except Exception as e:
        logger.error(f"封禁账号时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/unban-account', methods=['POST'])
def unban_account():
    """手动解封一个账号"""
    try:
        data = request.get_json()
        account_name = data.get('account_name')
        if not account_name:
            return jsonify({'error': '缺少 account_name 参数'}), 400

        db = get_db()
        cursor = db.cursor()
        cursor.execute('UPDATE accounts SET banned_until = NULL WHERE account_name = ?', (account_name,))
        db.commit()

        logger.info(f"账号 {account_name} 已被手动解封。")
        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"解封账号时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

def auto_unban_accounts():
    """自动解封到期的账号"""
    try:
        beijing_tz = pytz.timezone('Asia/Shanghai')
        now_str = datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')
        
        db = get_db()
        cursor = db.cursor()
        
        # 查找所有已到解封时间的账号
        cursor.execute('UPDATE accounts SET banned_until = NULL WHERE banned_until IS NOT NULL AND banned_until <= ?', (now_str,))
        unbanned_count = cursor.rowcount
        db.commit()

        if unbanned_count > 0:
            logger.info(f"自动解封了 {unbanned_count} 个账号。")

    except Exception as e:
        logger.error(f"自动解封账号时出错: {e}")

@app.route('/api/accounts/bulk-update', methods=['POST'])
def bulk_update_accounts():
    """批量更新多个账号的信息（例如，移动到新分组）"""
    try:
        data = request.get_json()
        logger.info(f"Bulk update request received: {data}")

        account_names = data.get('account_names')
        updates = data.get('updates')

        if not account_names or not isinstance(account_names, list) or not isinstance(updates, dict):
            logger.error(f"Bulk update failed due to invalid parameters. account_names: {account_names}, updates: {updates}")
            return jsonify({'error': '缺少必要参数或参数格式不正确'}), 400

        db = get_db()
        cursor = db.cursor()

        cursor.execute("PRAGMA table_info(accounts)")
        valid_columns = {row[1] for row in cursor.fetchall()}
        
        safe_updates = {k: v for k, v in updates.items() if k in valid_columns}
        
        if not safe_updates:
            logger.error(f"Bulk update failed: No valid fields to update in {updates}")
            return jsonify({'error': '没有有效的更新字段'}), 400

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        safe_updates['updated_at'] = timestamp

        set_clause = ', '.join([f'{key} = ?' for key in safe_updates.keys()])
        placeholders = ','.join(['?'] * len(account_names))
        
        query = f'UPDATE accounts SET {set_clause} WHERE account_name IN ({placeholders})'
        values = tuple(list(safe_updates.values()) + account_names)

        logger.info(f"Executing bulk update query: {query}")
        logger.info(f"With values: {values}")
        
        cursor.execute(query, values)
        db.commit()

        logger.info(f"批量更新了 {cursor.rowcount} 个账号。")
        return jsonify({'success': True, 'message': f'成功更新 {cursor.rowcount} 个账号。'})

    except Exception as e:
        logger.exception(f"批量更新账号时发生严重错误: {e}")
        return jsonify({'error': f'服务器内部错误: {str(e)}'}), 500

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

        logger.info(f"已删除账号 {account_name}，删除了 {records_deleted} 条历史记录")
        return jsonify({
            'success': True,
            'message': f'已删除账号 {account_name} 及其 {records_deleted} 条历史记录'
        })

    except Exception as e:
        logger.error(f"删除账号时出错: {str(e)}")
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
        
        logger.info(f"成功重置了 {len(latest_quantities)} 个账号的当日变化。")
        return jsonify({'success': True, 'message': f'成功重置 {len(latest_quantities)} 个账号的当日变化'})

    except Exception as e:
        logger.error(f"重置变化时出错: {str(e)}")
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
        logger.error(f"获取自动复位日志时出错: {str(e)}")
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
    logger.info("收到CSV导出请求，开始处理...")
    try:
        import csv
        
        socketio.emit('export_progress', {'percent': 5, 'message': '正在初始化...'})
        
        # 1. 获取数据
        accounts = get_accounts_data()
        if not accounts:
            logger.warning("没有可导出的数据")
            socketio.emit('export_finished', {'success': False, 'error': '没有可导出的数据'})
            return

        # --- 新增：按角色名称进行自然排序 ---
        accounts.sort(key=lambda x: natural_sort_key(x['account_name']))
        
        total_accounts = len(accounts)
        logger.info(f"成功获取并排序 {total_accounts} 条账号数据。")
        socketio.emit('export_progress', {'percent': 15, 'message': f'已获取并排序 {total_accounts} 条账号数据...'})
        socketio.sleep(0.1)

        # 2. 准备导出目录
        export_dir = 'downloads'
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
        
        filename = f"金条数据_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        file_path = os.path.join(export_dir, filename)
        
        socketio.emit('export_progress', {'percent': 25, 'message': '正在生成CSV文件...'})
        socketio.sleep(0.1)

        # 3. 写入CSV文件
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.writer(csvfile)
            
            # --- 修改：调整表头顺序和名称 ---
            writer.writerow(['服务器', '角色名称', '金条数', '状态'])
            socketio.emit('export_progress', {'percent': 35, 'message': '表头已生成，正在填充数据...'})
            socketio.sleep(0.1)
            
            # 写入数据行 - 只导出需要的字段
            for i, account in enumerate(accounts):
                server_name = extract_server_name(account.get('window_title', ''))
                # --- 修改：调整写入行的数据顺序 ---
                status = "封禁中" if account.get('banned_until') else ""
                writer.writerow([
                    server_name,
                    account['account_name'],
                    account['gold_quantity'],
                    status
                ])
                
                progress = 35 + int((i + 1) / total_accounts * 55)
                if i % 10 == 0 or i == total_accounts - 1: # 每10条或最后一条更新一次进度
                    socketio.emit('export_progress', {'percent': progress, 'message': f'正在处理: {account["account_name"]} ({i+1}/{total_accounts})'})
                    socketio.sleep(0.01)

        socketio.emit('export_progress', {'percent': 95, 'message': '数据写入完成，正在完成导出...'})
        socketio.sleep(0.1)
        
        logger.info(f"数据已成功导出到: {file_path}")
        socketio.emit('export_progress', {'percent': 100, 'message': '导出完成！'})
        socketio.emit('export_finished', {'success': True, 'path': file_path})

    except Exception as e:
        logger.error(f"生成CSV时出错: {str(e)}")
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


@app.route('/groups')
def groups():
    """分组管理页面"""
    return render_template_string(open('groups.html', 'r', encoding='utf-8').read())


@app.route('/days-tracker')
def days_tracker():
    """天数追踪页面"""
    return render_template_string(open('days_tracker.html', 'r', encoding='utf-8').read())


@app.route('/api/status')
def get_status():
    """检查应用状态，例如是否已初始化"""
    is_initialized = os.path.exists('records.db')
    return jsonify({'is_initialized': is_initialized})

@socketio.on('start_initialization')
def handle_initialization_request():
    """处理客户端的初始化请求"""
    logger.info("收到客户端初始化请求，开始执行...")
    # 使用一个新的线程来执行初始化，避免阻塞
    socketio.start_background_task(target=initialize_with_progress)

def initialize_with_progress():
    """带进度报告的数据库初始化函数"""
    with app.app_context():
        try:
            socketio.emit('initialization_progress', {'percent': 5, 'message': '正在准备环境...'})
            socketio.sleep(0.5)

            db = get_db()
            cursor = db.cursor()

            socketio.emit('initialization_progress', {'percent': 20, 'message': '创建核心记录表 (records)...'})
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    change INTEGER DEFAULT 0
                )
            ''')
            socketio.sleep(0.5)

            socketio.emit('initialization_progress', {'percent': 40, 'message': '创建账号信息表 (accounts)...'})
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
            socketio.sleep(0.5)

            socketio.emit('initialization_progress', {'percent': 60, 'message': '创建分组信息表 (groups)...'})
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            socketio.sleep(0.5)
            
            socketio.emit('initialization_progress', {'percent': 70, 'message': '创建自动复位日志表...'})
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS auto_reset_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reset_date TEXT NOT NULL,
                    reset_time TEXT NOT NULL,
                    accounts_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            ''')
            socketio.sleep(0.5)

            socketio.emit('initialization_progress', {'percent': 75, 'message': '创建天数追踪表...'})
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS days_tracker_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_name TEXT UNIQUE NOT NULL,
                    notes TEXT DEFAULT '',
                    start_date TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            socketio.sleep(0.5)

            socketio.emit('initialization_progress', {'percent': 80, 'message': '创建查询索引...'})
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_account_timestamp ON records(account_name, timestamp DESC)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_account_name ON accounts(account_name)')
            socketio.sleep(0.5)

            socketio.emit('initialization_progress', {'percent': 90, 'message': '检查并更新表结构...'})
            def add_column_if_not_exists(cursor, table, column_name, column_def):
                cursor.execute(f"PRAGMA table_info({table})")
                columns = [col[1] for col in cursor.fetchall()]
                if column_name not in columns:
                    logger.info(f"向表 {table} 添加新字段: {column_name}")
                    cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column_name} {column_def}')
            
            add_column_if_not_exists(cursor, 'records', 'change', 'INTEGER DEFAULT 0')
            add_column_if_not_exists(cursor, 'accounts', 'window_title', 'TEXT DEFAULT ""')
            add_column_if_not_exists(cursor, 'accounts', 'banned_until', 'TEXT DEFAULT NULL')
            socketio.sleep(0.5)

            db.commit()
            logger.info("数据库初始化成功。")
            socketio.emit('initialization_progress', {'percent': 100, 'message': '初始化完成！'})
            socketio.emit('initialization_finished')

        except Exception as e:
            logger.error(f"数据库初始化过程中出错: {e}")
            socketio.emit('initialization_failed', {'error': str(e)})


@app.route('/api/groups', methods=['GET'])
def get_groups():
    """获取所有分组信息"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT id, name, notes FROM groups ORDER BY name ASC')
        groups = cursor.fetchall()
        return jsonify([dict(g) for g in groups])
    except Exception as e:
        logger.error(f"获取分组列表时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/groups', methods=['POST'])
def create_group():
    """创建一个新分组"""
    try:
        data = request.get_json()
        name = data.get('name')
        if not name:
            return jsonify({'error': '分组名称不能为空'}), 400

        db = get_db()
        cursor = db.cursor()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        try:
            cursor.execute(
                'INSERT INTO groups (name, notes, created_at, updated_at) VALUES (?, ?, ?, ?)',
                (name, data.get('notes', ''), timestamp, timestamp)
            )
            db.commit()
            group_id = cursor.lastrowid
            return jsonify({'success': True, 'message': '分组已创建', 'id': group_id}), 201
        except sqlite3.IntegrityError:
            return jsonify({'error': '该分组名称已存在'}), 409

    except Exception as e:
        logger.error(f"创建分组时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/groups/<int:group_id>', methods=['PUT'])
def update_group(group_id):
    """更新一个分组的信息"""
    try:
        data = request.get_json()
        name = data.get('name')
        notes = data.get('notes')

        if not name:
            return jsonify({'error': '分组名称不能为空'}), 400

        db = get_db()
        cursor = db.cursor()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            cursor.execute(
                'UPDATE groups SET name = ?, notes = ?, updated_at = ? WHERE id = ?',
                (name, notes, timestamp, group_id)
            )
            db.commit()
            if cursor.rowcount == 0:
                return jsonify({'error': '未找到指定的分组'}), 404
            return jsonify({'success': True, 'message': '分组已更新'})
        except sqlite3.IntegrityError:
            return jsonify({'error': '该分组名称已存在'}), 409

    except Exception as e:
        logger.error(f"更新分组时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/groups/<int:group_id>', methods=['DELETE'])
def delete_group(group_id):
    """删除一个分组"""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Optional: Before deleting the group, un-assign members
        cursor.execute('SELECT name FROM groups WHERE id = ?', (group_id,))
        group = cursor.fetchone()
        if group:
            group_name = group['name']
            cursor.execute('UPDATE accounts SET group_name = "" WHERE group_name = ?', (group_name,))
        
        cursor.execute('DELETE FROM groups WHERE id = ?', (group_id,))
        db.commit()

        if cursor.rowcount == 0:
            return jsonify({'error': '未找到指定的分组'}), 404
            
        logger.info(f"已删除分组 ID: {group_id}，并解散了其成员的分组。")
        return jsonify({'success': True, 'message': '分组已删除'})

    except Exception as e:
        logger.error(f"删除分组时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/days-tracker-entries', methods=['GET'])
def get_days_tracker_entries():
    """获取所有天数追踪条目"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT account_name, notes, start_date, created_at, updated_at FROM days_tracker_entries ORDER BY account_name ASC')
        entries = cursor.fetchall()
        return jsonify([{
            'account_name': e['account_name'],
            'notes': e['notes'],
            'start_date': e['start_date'],
            'created_at': e['created_at'],
            'updated_at': e['updated_at']
        } for e in entries])
    except Exception as e:
        logger.error(f"获取天数追踪条目时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/days-tracker-entries', methods=['POST'])
def create_or_update_days_tracker_entry():
    """创建或更新天数追踪条目（账号唯一）"""
    try:
        data = request.get_json()
        account_name = data.get('account_name')
        notes = data.get('notes', '')
        start_date = data.get('start_date')

        if not account_name or not start_date:
            return jsonify({'error': '缺少必要参数: account_name 或 start_date'}), 400

        db = get_db()
        cursor = db.cursor()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 检查是否已存在
        cursor.execute('SELECT id FROM days_tracker_entries WHERE account_name = ?', (account_name,))
        existing = cursor.fetchone()

        if existing:
            # 更新现有条目
            cursor.execute('''
                UPDATE days_tracker_entries SET notes = ?, start_date = ?, updated_at = ? WHERE account_name = ?
            ''', (notes, start_date, timestamp, account_name))
        else:
            # 插入新条目
            cursor.execute('''
                INSERT INTO days_tracker_entries (account_name, notes, start_date, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (account_name, notes, start_date, timestamp, timestamp))

        db.commit()
        return jsonify({'success': True, 'message': '天数追踪条目已保存'})
    except Exception as e:
        logger.error(f"保存天数追踪条目时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/days-tracker-entries/<account_name>', methods=['DELETE'])
def delete_days_tracker_entry(account_name):
    """删除指定账号的天数追踪条目"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('DELETE FROM days_tracker_entries WHERE account_name = ?', (account_name,))
        db.commit()
        if cursor.rowcount == 0:
            return jsonify({'error': '未找到指定账号的条目'}), 404
        return jsonify({'success': True, 'message': '天数追踪条目已删除'})
    except Exception as e:
        logger.error(f"删除天数追踪条目时出错: {str(e)}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # 首次运行时，数据库将由客户端通过socket请求初始化
    if not os.path.exists('records.db'):
        logger.warning("数据库 'records.db' 未找到。等待客户端发起初始化请求...")
    else:
        # 如果数据库已存在，还是执行一次快速检查和迁移，以防有更新
        init_database()

    logger.info("金条管家 v1.1 服务器启动")
    logger.info("仪表板: http://localhost:8080")
    logger.info("历史记录: http://localhost:8080/history")

    # 启动Flask-SocketIO应用
    logger.info("使用 eventlet 异步服务器启动...")
    socketio.run(app, host='0.0.0.0', port=8080, debug=False)
