from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
import os

# 导入自定义模块
from models import init_db, get_db_connection
from auth import login_required, permission_required
from utils import generate_order_no, record_stock_movement, record_financial_transaction
from routes.product_routes import product_bp
from routes.purchase_routes import purchase_bp
from routes.sales_routes import sales_bp

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

# 注册蓝图
app.register_blueprint(product_bp, url_prefix='/product')
app.register_blueprint(purchase_bp, url_prefix='/purchase')
app.register_blueprint(sales_bp, url_prefix='/sales')

# 主页和认证路由
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash('登录成功！', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误！', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    
    # 获取统计数据
    stats = {
        'total_products': conn.execute('SELECT COUNT(*) as count FROM products').fetchone()['count'],
        'total_customers': conn.execute('SELECT COUNT(*) as count FROM customers').fetchone()['count'],
        'total_suppliers': conn.execute('SELECT COUNT(*) as count FROM suppliers').fetchone()['count'],
        'low_stock_products': conn.execute('SELECT COUNT(*) as count FROM products WHERE stock_quantity <= min_stock').fetchone()['count']
    }
    
    # 库存预警
    low_stock_products = conn.execute('''
        SELECT name, stock_quantity, min_stock 
        FROM products 
        WHERE stock_quantity <= min_stock
    ''').fetchall()
    
    high_stock_products = conn.execute('''
        SELECT name, stock_quantity, max_stock 
        FROM products 
        WHERE max_stock > 0 AND stock_quantity >= max_stock
    ''').fetchall()
    
    # 获取最近的交易记录
    recent_transactions = conn.execute('''
        SELECT * FROM financial_transactions 
        ORDER BY transaction_date DESC 
        LIMIT 10
    ''').fetchall()
    
    # 获取系统余额
    balance = conn.execute('SELECT balance FROM system_balance WHERE id = 1').fetchone()
    current_balance = balance['balance'] if balance else 0
    
    conn.close()
    
    return render_template('dashboard.html', stats=stats, 
                         low_stock_products=low_stock_products,
                         high_stock_products=high_stock_products,
                         recent_transactions=recent_transactions, 
                         current_balance=current_balance)

# 供应商管理
@app.route('/suppliers')
@login_required
@permission_required('suppliers')
def suppliers():
    conn = get_db_connection()
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    
    query = 'SELECT * FROM suppliers WHERE 1=1'
    params = []
    
    if search:
        query += ' AND (name LIKE ? OR contact_person LIKE ? OR phone LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    
    if status:
        if status == 'active':
            query += ' AND is_active = 1'
        elif status == 'inactive':
            query += ' AND is_active = 0'
    
    query += ' ORDER BY created_at DESC'
    
    suppliers = conn.execute(query, params).fetchall()
    conn.close()
    return render_template('suppliers.html', suppliers=suppliers, search=search, status=status)

@app.route('/suppliers/add', methods=['GET', 'POST'])
@login_required
@permission_required('suppliers')
def add_supplier():
    if request.method == 'POST':
        name = request.form.get('name', '')
        contact_person = request.form.get('contact_person', '')
        phone = request.form.get('phone', '')
        email = request.form.get('email', '')
        address = request.form.get('address', '')
        notes = request.form.get('notes', '')
        is_active = 1 if request.form.get('is_active') else 0
        
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO suppliers (name, contact_person, phone, email, address, notes, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (name, contact_person, phone, email, address, notes, is_active))
        conn.commit()
        conn.close()
        
        flash('供应商添加成功！', 'success')
        return redirect(url_for('suppliers'))
    
    return render_template('add_supplier.html')

@app.route('/suppliers/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('suppliers')
def edit_supplier(id):
    conn = get_db_connection()
    supplier = conn.execute('SELECT * FROM suppliers WHERE id = ?', (id,)).fetchone()
    
    if request.method == 'POST':
        name = request.form.get('name', '')
        contact_person = request.form.get('contact_person', '')
        phone = request.form.get('phone', '')
        email = request.form.get('email', '')
        address = request.form.get('address', '')
        notes = request.form.get('notes', '')
        is_active = 1 if request.form.get('is_active') else 0
        
        conn.execute('''
            UPDATE suppliers SET name = ?, contact_person = ?, phone = ?, email = ?, 
                               address = ?, notes = ?, is_active = ?
            WHERE id = ?
        ''', (name, contact_person, phone, email, address, notes, is_active, id))
        conn.commit()
        conn.close()
        
        flash('供应商更新成功', 'success')
        return redirect(url_for('suppliers'))
    
    conn.close()
    return render_template('edit_supplier.html', supplier=supplier)

@app.route('/suppliers/view/<int:id>')
@login_required
def view_supplier(id):
    conn = get_db_connection()
    supplier = conn.execute('SELECT * FROM suppliers WHERE id = ?', (id,)).fetchone()
    conn.close()
    return render_template('view_supplier.html', supplier=supplier)

@app.route('/suppliers/delete/<int:id>')
@login_required
@permission_required('suppliers')
def delete_supplier(id):
    conn = get_db_connection()
    
    # 检查是否有采购订单使用此供应商
    purchase_count = conn.execute('SELECT COUNT(*) FROM purchase_orders WHERE supplier_id = ?', (id,)).fetchone()[0]
    if purchase_count > 0:
        flash('该供应商下存在采购订单，无法删除', 'error')
        conn.close()
        return redirect(url_for('suppliers'))
    
    conn.execute('DELETE FROM suppliers WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    flash('供应商删除成功！', 'success')
    return redirect(url_for('suppliers'))

# 客户管理
@app.route('/customers')
@login_required
@permission_required('customers')
def customers():
    conn = get_db_connection()
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    
    query = 'SELECT * FROM customers WHERE 1=1'
    params = []
    
    if search:
        query += ' AND (name LIKE ? OR contact_person LIKE ? OR phone LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    
    if status:
        query += ' AND status = ?'
        params.append(status)
    
    query += ' ORDER BY created_at DESC'
    
    customers = conn.execute(query, params).fetchall()
    conn.close()
    return render_template('customers.html', customers=customers, search=search, status=status)

@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
@permission_required('customers')
def add_customer():
    if request.method == 'POST':
        name = request.form.get('name', '')
        contact_person = request.form.get('contact_person', '')
        phone = request.form.get('phone', '')
        email = request.form.get('email', '')
        address = request.form.get('address', '')
        notes = request.form.get('notes', '')
        is_active = 1 if request.form.get('is_active') else 0
        
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO customers (name, contact_person, phone, email, address, notes, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (name, contact_person, phone, email, address, notes, is_active))
        conn.commit()
        conn.close()
        
        flash('客户添加成功！', 'success')
        return redirect(url_for('customers'))
    
    return render_template('add_customer.html')

@app.route('/customers/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('customers')
def edit_customer(id):
    conn = get_db_connection()
    customer = conn.execute('SELECT * FROM customers WHERE id = ?', (id,)).fetchone()
    
    if request.method == 'POST':
        name = request.form.get('name', '')
        contact_person = request.form.get('contact_person', '')
        phone = request.form.get('phone', '')
        email = request.form.get('email', '')
        address = request.form.get('address', '')
        notes = request.form.get('notes', '')
        is_active = 1 if request.form.get('is_active') else 0
        
        conn.execute('''
            UPDATE customers SET name = ?, contact_person = ?, phone = ?, email = ?, 
                               address = ?, notes = ?, is_active = ?
            WHERE id = ?
        ''', (name, contact_person, phone, email, address, notes, is_active, id))
        conn.commit()
        conn.close()
        
        flash('客户更新成功', 'success')
        return redirect(url_for('customers'))
    
    conn.close()
    return render_template('edit_customer.html', customer=customer)

@app.route('/customers/view/<int:id>')
@login_required
def view_customer(id):
    conn = get_db_connection()
    customer = conn.execute('SELECT * FROM customers WHERE id = ?', (id,)).fetchone()
    conn.close()
    return render_template('view_customer.html', customer=customer)

@app.route('/customers/delete/<int:id>')
@login_required
@permission_required('customers')
def delete_customer(id):
    conn = get_db_connection()
    
    # 检查是否有销售订单使用此客户
    sales_count = conn.execute('SELECT COUNT(*) FROM sales_orders WHERE customer_id = ?', (id,)).fetchone()[0]
    if sales_count > 0:
        flash('该客户下存在销售订单，无法删除', 'error')
        conn.close()
        return redirect(url_for('customers'))
    
    conn.execute('DELETE FROM customers WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    flash('客户删除成功！', 'success')
    return redirect(url_for('customers'))

# 库存管理
@app.route('/inventory')
@login_required
@permission_required('inventory')
def inventory():
    conn = get_db_connection()
    search = request.args.get('search', '')
    stock_status = request.args.get('stock_status', '')
    
    query = '''
        SELECT p.*, c.name as category_name,
               CASE 
                   WHEN p.stock_quantity <= 0 THEN 'out_of_stock'
                   WHEN p.stock_quantity < p.min_stock THEN 'low_stock'
                   WHEN p.stock_quantity > p.max_stock THEN 'overstock'
                   ELSE 'normal'
               END as stock_status
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE 1=1
    '''
    params = []
    
    if search:
        query += ' AND (p.name LIKE ? OR p.specification LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
    
    if stock_status == 'low':
        query += ' AND p.stock_quantity < p.min_stock'
    elif stock_status == 'out':
        query += ' AND p.stock_quantity <= 0'
    elif stock_status == 'excess':
        query += ' AND p.stock_quantity > p.max_stock'
    elif stock_status == 'normal':
        query += ' AND p.stock_quantity >= p.min_stock AND p.stock_quantity <= p.max_stock'
    
    query += ' ORDER BY p.name'
    
    inventory = conn.execute(query, params).fetchall()
    
    # 统计信息
    stats = {
        'total_products': conn.execute('SELECT COUNT(*) as count FROM products').fetchone()['count'],
        'normal_stock': conn.execute('SELECT COUNT(*) as count FROM products WHERE stock_quantity >= min_stock AND stock_quantity <= max_stock').fetchone()['count'],
        'low_stock': conn.execute('SELECT COUNT(*) as count FROM products WHERE stock_quantity < min_stock AND stock_quantity > 0').fetchone()['count'],
        'out_of_stock': conn.execute('SELECT COUNT(*) as count FROM products WHERE stock_quantity <= 0').fetchone()['count']
    }
    
    conn.close()
    
    return render_template('inventory.html', inventory=inventory, stats=stats, 
                         search=search, stock_status=stock_status)

@app.route('/inventory/movements/<int:product_id>')
@login_required
def inventory_movements(product_id):
    conn = get_db_connection()
    
    product = conn.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
    if not product:
        flash('商品不存在！', 'error')
        conn.close()
        return redirect(url_for('inventory'))
    
    movements = conn.execute('''
        SELECT sm.*, u.username as operator_name
        FROM stock_movements sm
        LEFT JOIN users u ON sm.operator = u.username
        WHERE sm.product_id = ?
        ORDER BY sm.created_at DESC
    ''', (product_id,)).fetchall()
    
    conn.close()
    return render_template('inventory_movements.html', product=product, movements=movements)

# 财务管理
@app.route('/finance')
@login_required
@permission_required('finance')
def finance():
    conn = get_db_connection()
    
    # 获取系统余额
    balance_row = conn.execute('SELECT * FROM system_balance WHERE id = 1').fetchone()
    balance = balance_row['balance'] if balance_row else 0
    
    # 获取交易记录
    search = request.args.get('search', '')
    transaction_type = request.args.get('transaction_type', '')
    
    query = 'SELECT * FROM financial_transactions WHERE 1=1'
    params = []
    
    if search:
        query += ' AND (order_no LIKE ? OR counterpart LIKE ? OR notes LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    
    if transaction_type:
        query += ' AND transaction_type = ?'
        params.append(transaction_type)
    
    query += ' ORDER BY transaction_date DESC LIMIT 100'
    
    transactions = conn.execute(query, params).fetchall()
    
    # 今日统计
    today = datetime.now().strftime('%Y-%m-%d')
    today_income = conn.execute('''
        SELECT COALESCE(SUM(amount), 0) as total 
        FROM financial_transactions 
        WHERE DATE(transaction_date) = ? AND transaction_type = 'income'
    ''', (today,)).fetchone()['total']
    
    today_expense = conn.execute('''
        SELECT COALESCE(SUM(amount), 0) as total 
        FROM financial_transactions 
        WHERE DATE(transaction_date) = ? AND transaction_type = 'expense'
    ''', (today,)).fetchone()['total']
    
    stats = {
        'today_income': today_income,
        'today_expense': today_expense
    }
    
    conn.close()
    
    return render_template('finance.html', balance=balance, transactions=transactions, 
                         search=search, transaction_type=transaction_type, stats=stats)

@app.route('/finance/adjust', methods=['GET', 'POST'])
@login_required
@permission_required('finance')
def finance_adjust():
    if request.method == 'POST':
        adjust_type = request.form.get('adjustment_type', '')
        amount = float(request.form.get('amount', 0))
        reason = request.form.get('reason', '')
        
        conn = get_db_connection()
        try:
            if adjust_type == 'deposit':
                # 充值
                conn.execute('UPDATE system_balance SET balance = balance + ? WHERE id = 1', (amount,))
                record_financial_transaction(conn, '调整', 
                    f'DEP{datetime.now().strftime("%Y%m%d%H%M%S")}', 
                    amount, '系统', session['username'], reason)
            else:
                # 提现
                current_balance = conn.execute('SELECT balance FROM system_balance WHERE id = 1').fetchone()['balance']
                if current_balance < amount:
                    flash('余额不足，无法提现！', 'error')
                    return redirect(url_for('finance_adjust'))
                
                conn.execute('UPDATE system_balance SET balance = balance - ? WHERE id = 1', (amount,))
                record_financial_transaction(conn, '调整', 
                    f'WIT{datetime.now().strftime("%Y%m%d%H%M%S")}', 
                    amount, '系统', session['username'], reason)
            
            conn.commit()
            flash(f'{'充值' if adjust_type == 'deposit' else '提现'}成功！', 'success')
            return redirect(url_for('finance'))
        except Exception as e:
            conn.rollback()
            flash(f'操作失败：{str(e)}', 'error')
        finally:
            conn.close()
    
    # GET 请求时获取余额信息
    conn = get_db_connection()
    balance = conn.execute('SELECT * FROM system_balance WHERE id = 1').fetchone()
    conn.close()
    
    return render_template('finance_adjust.html', balance=balance)

# 用户管理
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        old_password = request.form.get('old_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if new_password != confirm_password:
            flash('新密码和确认密码不一致！', 'error')
            return redirect(url_for('profile'))
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        
        if not check_password_hash(user['password_hash'], old_password):
            flash('原密码错误！', 'error')
            conn.close()
            return render_template('profile.html', user=user)
        
        # 更新密码
        new_password_hash = generate_password_hash(new_password)
        conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_password_hash, session['user_id']))
        conn.commit()
        conn.close()
        
        flash('密码修改成功！', 'success')
        return redirect(url_for('profile'))
    
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    
    return render_template('profile.html', user=user)

# 用户管理
@app.route('/users')
@login_required
@permission_required('users')
def users():
    conn = get_db_connection()
    users = conn.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
    conn.close()
    return render_template('users.html', users=users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@permission_required('users')
def add_user():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        role = request.form.get('role', '')
        permissions = ','.join(request.form.getlist('permissions'))
        
        conn = get_db_connection()
        
        # 检查用户名是否已存在
        existing_user = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if existing_user:
            flash('用户名已存在！', 'error')
            conn.close()
            return render_template('add_user.html')
        
        # 创建用户
        password_hash = generate_password_hash(password)
        conn.execute(
            'INSERT INTO users (username, password_hash, role, permissions) VALUES (?, ?, ?, ?)',
            (username, password_hash, role, permissions)
        )
        conn.commit()
        conn.close()
        
        flash('用户创建成功！', 'success')
        return redirect(url_for('users'))
    
    return render_template('add_user.html')

@app.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('users')
def edit_user(id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (id,)).fetchone()
    
    if not user:
        flash('用户不存在！', 'error')
        conn.close()
        return redirect(url_for('users'))
    
    if request.method == 'POST':
        username = request.form.get('username', '')
        role = request.form.get('role', '')
        permissions = ','.join(request.form.getlist('permissions'))
        
        # 检查用户名是否已被其他用户使用
        existing_user = conn.execute('SELECT id FROM users WHERE username = ? AND id != ?', (username, id)).fetchone()
        if existing_user:
            flash('用户名已存在！', 'error')
            conn.close()
            return render_template('edit_user.html', user=user)
        
        # 更新用户信息
        conn.execute(
            'UPDATE users SET username = ?, role = ?, permissions = ? WHERE id = ?',
            (username, role, permissions, id)
        )
        conn.commit()
        conn.close()
        
        flash('用户信息更新成功！', 'success')
        return redirect(url_for('users'))
    
    conn.close()
    return render_template('edit_user.html', user=user)

@app.route('/users/delete/<int:id>', methods=['POST'])
@login_required
@permission_required('users')
def delete_user(id):
    if id == session['user_id']:
        flash('不能删除自己的账户！', 'error')
        return redirect(url_for('users'))
    
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (id,)).fetchone()
    
    if not user:
        flash('用户不存在！', 'error')
        conn.close()
        return redirect(url_for('users'))
    
    conn.execute('DELETE FROM users WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    flash(f'用户 {user["username"]} 删除成功！', 'success')
    return redirect(url_for('users'))

if __name__ == '__main__':
    # 初始化数据库
    if not os.path.exists('inventory_system.db'):
        init_db()
    
    app.run(debug=True, host='0.0.0.0', port=16666)