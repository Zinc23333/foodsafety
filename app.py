from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file, flash, session
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import json
import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import matplotlib.pyplot as plt
import io
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # 用于session加密
plt.rcParams['font.family'] = 'HarmonyOSSans_SC'

# 数据库初始化
def init_db():
    conn = sqlite3.connect('food_safety.db')
    c = conn.cursor()
    
    # 创建用户表
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')
    
    # 创建企业表
    c.execute('''
        CREATE TABLE IF NOT EXISTS enterprises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            license_no TEXT UNIQUE,
            business_type TEXT,
            expire_date DATE
        )
    ''')
    
    # 创建产品表
    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            batch_id TEXT PRIMARY KEY,
            enterprise_id INTEGER,
            product_name TEXT,
            production_date DATE,
            shelf_life INTEGER,
            FOREIGN KEY (enterprise_id) REFERENCES enterprises (id)
        )
    ''')
    
    # 创建检测记录表
    c.execute('''
        CREATE TABLE IF NOT EXISTS inspections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT,
            indicator_name TEXT,
            test_value REAL,
            unit TEXT,
            test_date DATE DEFAULT CURRENT_DATE,
            FOREIGN KEY (batch_id) REFERENCES products (batch_id)
        )
    ''')
    
    # 检查是否已存在管理员用户
    c.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if c.fetchone()[0] == 0:
        # 创建默认管理员用户
        c.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ('admin', generate_password_hash('admin123'), 'admin')
        )
    
    conn.commit()
    conn.close()

# 合规性规则配置
RULES = {
    "乳制品": {
        "菌落总数": {"max": 100000, "unit": "CFU/g"},
        "大肠菌群": {"max": 10, "unit": "MPN/g"}
    },
    "蔬菜类": {
        "敌敌畏残留": {"max": 0.1, "unit": "mg/kg"}
    }
}

# 登录装饰器
def login_required(f):
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# 管理员权限装饰器
def admin_required(f):
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'admin':
            flash('需要管理员权限')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/enterprise/register', methods=['GET', 'POST'])
def register_enterprise():
    if request.method == 'POST':
        data = request.form
        conn = sqlite3.connect('food_safety.db')
        c = conn.cursor()
        c.execute('''
        INSERT INTO enterprises (name, license_no, business_type, expire_date)
        VALUES (?, ?, ?, ?)
        ''', (data['name'], data['license_no'], data['business_type'], data['expire_date']))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    return render_template('enterprise_register.html')

@app.route('/product/register', methods=['GET', 'POST'])
def register_product():
    if request.method == 'POST':
        data = request.form
        conn = sqlite3.connect('food_safety.db')
        c = conn.cursor()
        c.execute('''
        INSERT INTO products (batch_id, enterprise_id, product_name, production_date, shelf_life)
        VALUES (?, ?, ?, ?, ?)
        ''', (data['batch_id'], data['enterprise_id'], data['product_name'], 
              data['production_date'], data['shelf_life']))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    return render_template('product_register.html')

@app.route('/inspection/add', methods=['GET', 'POST'])
def add_inspection():
    if request.method == 'POST':
        data = request.form
        conn = sqlite3.connect('food_safety.db')
        c = conn.cursor()
        c.execute('''
        INSERT INTO inspections (batch_id, indicator_name, test_value, unit)
        VALUES (?, ?, ?, ?)
        ''', (data['batch_id'], data['indicator_name'], 
              data['test_value'], data['unit']))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    return render_template('inspection_add.html')

@app.route('/analysis/<batch_id>')
def analyze_batch(batch_id):
    conn = sqlite3.connect('food_safety.db')
    c = conn.cursor()
    
    # 获取产品信息
    c.execute('SELECT * FROM products WHERE batch_id = ?', (batch_id,))
    product = c.fetchone()
    if not product:
        flash('未找到该批次产品')
        return redirect(url_for('list_products'))
    
    # 获取检测数据
    c.execute('SELECT * FROM inspections WHERE batch_id = ?', (batch_id,))
    inspections = c.fetchall()
    if not inspections:
        flash('该批次产品暂无检测数据')
        return redirect(url_for('list_products'))
    
    warnings = []
    
    # 过期检测
    production_date = datetime.strptime(product[3], '%Y-%m-%d')
    expiration_date = production_date + timedelta(days=product[4])
    if expiration_date - datetime.now() < timedelta(days=7):
        warnings.append(f"产品将在7日内过期（到期日：{expiration_date.strftime('%Y-%m-%d')}）")
    
    # 指标检测
    for inspection in inspections:
        indicator_name = inspection[2]
        test_value = inspection[3]
        unit = inspection[4]
        
        # 这里需要根据产品类型获取对应的规则
        # 简化处理，假设所有产品都使用乳制品规则
        if indicator_name in RULES["乳制品"]:
            rule = RULES["乳制品"][indicator_name]
            if test_value > rule["max"] * 1.05:
                warnings.append(f"{indicator_name}超标：{test_value}{unit} > 国标{rule['max']}{unit}")
    
    conn.close()
    return render_template('analysis_result.html', 
                         batch_id=batch_id,
                         warnings=warnings,
                         inspections=inspections)

@app.route('/enterprise/list')
def list_enterprises():
    conn = sqlite3.connect('food_safety.db')
    c = conn.cursor()
    c.execute('SELECT * FROM enterprises')
    enterprises = c.fetchall()
    conn.close()
    return render_template('enterprise_list.html', enterprises=enterprises)

@app.route('/product/list')
def list_products():
    conn = sqlite3.connect('food_safety.db')
    c = conn.cursor()
    c.execute('''
    SELECT p.*, e.name as enterprise_name 
    FROM products p 
    JOIN enterprises e ON p.enterprise_id = e.id
    ''')
    products = c.fetchall()
    conn.close()
    return render_template('product_list.html', products=products)

@app.route('/inspection/list')
def list_inspections():
    conn = sqlite3.connect('food_safety.db')
    c = conn.cursor()
    
    # 首先检查是否有检测记录
    c.execute("SELECT COUNT(*) FROM inspections")
    count = c.fetchone()[0]
    if count == 0:
        flash('当前没有检测记录，请先添加检测数据')
        return redirect(url_for('index'))
    
    # 获取检测记录
    c.execute('''
    SELECT i.*, p.product_name, e.name as enterprise_name 
    FROM inspections i 
    LEFT JOIN products p ON i.batch_id = p.batch_id
    LEFT JOIN enterprises e ON p.enterprise_id = e.id
    ORDER BY i.test_date DESC
    ''')
    inspections = c.fetchall()
    conn.close()
    
    # 打印调试信息
    print(f"检测记录数量: {len(inspections)}")
    for inspection in inspections:
        print(f"检测记录: {inspection}")
    
    return render_template('inspection_list.html', inspections=inspections)

@app.route('/report/generate/<batch_id>')
def generate_report(batch_id):
    conn = sqlite3.connect('food_safety.db')
    c = conn.cursor()
    
    # 获取产品信息
    c.execute('''
    SELECT p.batch_id, p.product_name, p.production_date, p.shelf_life, e.name as enterprise_name 
    FROM products p 
    JOIN enterprises e ON p.enterprise_id = e.id 
    WHERE p.batch_id = ?
    ''', (batch_id,))
    product = c.fetchone()
    
    if not product:
        flash('未找到该批次产品')
        return redirect(url_for('list_products'))
    
    # 获取检测数据
    c.execute('SELECT * FROM inspections WHERE batch_id = ?', (batch_id,))
    inspections = c.fetchall()
    
    if not inspections:
        flash('该批次产品暂无检测数据')
        return redirect(url_for('list_products'))
    
    # 生成PDF报告
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    
    try:
        # 设置中文字体
        pdfmetrics.registerFont(TTFont('SimSun', 'SimSun.ttf'))
        p.setFont('SimSun', 12)
    except Exception as e:
        print(f"SimSun字体加载错误: {e}")
        # 如果无法加载中文字体，使用默认字体
        p.setFont('Helvetica', 12)
    
    # 写入报告内容
    p.drawString(100, 800, f"食品安全检测报告 - {batch_id}")
    p.drawString(100, 780, f"企业名称：{product[4]}")  # enterprise_name
    p.drawString(100, 760, f"产品名称：{product[1]}")  # product_name
    p.drawString(100, 740, f"生产日期：{product[2]}")  # production_date
    
    # 写入检测数据
    y = 700
    for inspection in inspections:
        p.drawString(100, y, f"检测指标：{inspection[2]}")
        p.drawString(100, y-20, f"检测值：{inspection[3]}{inspection[4]}")
        y -= 40
    
    # 生成趋势图
    plt.figure(figsize=(6, 4))
    
    # 设置图表字体
    plt.rcParams['font.sans-serif'] = ['HarmonyOS Sans SC', 'SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False
    
    indicators = [i[2] for i in inspections]
    values = [i[3] for i in inspections]
    plt.bar(indicators, values)
    plt.title('检测指标对比', fontproperties='HarmonyOS Sans SC')
    plt.xticks(rotation=45, fontproperties='HarmonyOS Sans SC')
    plt.tight_layout()
    
    # 保存图表到临时文件
    temp_img_path = f'temp_chart_{batch_id}.png'
    plt.savefig(temp_img_path, format='png', bbox_inches='tight', dpi=300)
    plt.close()
    
    # 将图表添加到PDF
    p.drawImage(temp_img_path, 100, y-300, width=400, height=200)
    
    # 删除临时文件
    os.remove(temp_img_path)
    
    p.save()
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'report_{batch_id}.pdf',
        mimetype='application/pdf'
    )

@app.route('/dashboard')
def dashboard():
    conn = sqlite3.connect('food_safety.db')
    c = conn.cursor()
    
    # 获取统计数据
    c.execute('SELECT COUNT(*) FROM enterprises')
    enterprise_count = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM products')
    product_count = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM inspections')
    inspection_count = c.fetchone()[0]
    
    # 获取即将过期的产品
    c.execute('''
    SELECT p.*, e.name as enterprise_name 
    FROM products p 
    JOIN enterprises e ON p.enterprise_id = e.id
    WHERE date(p.production_date, '+' || p.shelf_life || ' days') <= date('now', '+7 days')
    ''')
    expiring_products = c.fetchall()
    
    conn.close()
    
    return render_template('dashboard.html',
                         enterprise_count=enterprise_count,
                         product_count=product_count,
                         inspection_count=inspection_count,
                         expiring_products=expiring_products)

# 登录路由
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = sqlite3.connect('food_safety.db')
        c = conn.cursor()
        c.execute("SELECT id, username, password, role FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()
        
        if user and check_password_hash(user[2], password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['role'] = user[3]
            flash('登录成功')
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误')
    
    return render_template('login.html')

# 退出登录路由
@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录')
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True) 