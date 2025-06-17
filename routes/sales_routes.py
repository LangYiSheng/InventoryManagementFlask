from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import get_db_connection
from auth import login_required, permission_required
from utils import generate_order_no, record_stock_movement, record_financial_transaction
from datetime import datetime

sales_bp = Blueprint('sales', __name__)

@sales_bp.route('/sales')
@login_required
@permission_required('sales')
def sales():
    conn = get_db_connection()
    search = request.args.get('search', '')
    customer_id = request.args.get('customer_id', '')
    status = request.args.get('status', '')
    
    query = '''
        SELECT so.*, c.name as customer_name
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        WHERE 1=1
    '''
    params = []
    
    if search:
        query += ' AND (so.order_no LIKE ? OR c.name LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
    
    if customer_id:
        query += ' AND so.customer_id = ?'
        params.append(customer_id)
    
    if status:
        query += ' AND so.status = ?'
        params.append(status)
    
    query += ' ORDER BY so.created_at DESC'
    
    sales = conn.execute(query, params).fetchall()
    customers = conn.execute('SELECT * FROM customers ORDER BY name').fetchall()
    conn.close()
    
    return render_template('sales.html', sales=sales, customers=customers,
                         search=search, customer_id=customer_id, status=status)

@sales_bp.route('/sales/add', methods=['GET', 'POST'])
@login_required
@permission_required('sales')
def add_sale():
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        notes = request.form.get('notes', '')
        
        conn = get_db_connection()
        try:
            # 创建销售单
            order_no = generate_order_no('SO')
            conn.execute('''
                INSERT INTO sales_orders (order_no, customer_id, total_amount, status, notes, created_by)
                VALUES (?, ?, 0, '待确认', ?, ?)
            ''', (order_no, customer_id, notes, session['user_id']))
            
            sale_id = conn.lastrowid
            conn.commit()
            
            flash('销售单创建成功！', 'success')
            return redirect(url_for('sales.edit_sale', id=sale_id))
        except Exception as e:
            conn.rollback()
            flash(f'创建失败：{str(e)}', 'error')
        finally:
            conn.close()
    
    conn = get_db_connection()
    customers = conn.execute('SELECT * FROM customers ORDER BY name').fetchall()
    products = conn.execute('SELECT * FROM products ORDER BY name').fetchall()
    conn.close()
    
    return render_template('add_sale.html', customers=customers, products=products)

@sales_bp.route('/sales/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('sales')
def edit_sale(id):
    conn = get_db_connection()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'confirm':
            # 确认销售单
            try:
                # 更新库存和财务记录
                items = conn.execute('''
                    SELECT soi.*, p.name as product_name
                    FROM sales_order_items soi
                    LEFT JOIN products p ON soi.product_id = p.id
                    WHERE soi.order_id = ?
                ''', (id,)).fetchall()
                
                total_amount = 0
                for item in items:
                    # 检查库存
                    product = conn.execute('SELECT stock_quantity FROM products WHERE id = ?', 
                                         (item['product_id'],)).fetchone()
                    if product['stock_quantity'] < item['quantity']:
                        flash(f'商品 {item["product_name"]} 库存不足！', 'error')
                        return redirect(url_for('sales.edit_sale', id=id))
                    
                    # 更新库存
                    conn.execute('UPDATE products SET stock_quantity = stock_quantity - ? WHERE id = ?',
                               (item['quantity'], item['product_id']))
                    
                    # 记录库存变动
                    record_stock_movement(conn, item['product_id'], 'out', item['quantity'], 
                                        f'销售出库 - {item["product_name"]}', session['username'])
                    
                    total_amount += item['quantity'] * item['unit_price']
                
                # 更新销售单状态和总金额
                conn.execute('UPDATE sales_orders SET status = ?, total_amount = ? WHERE id = ?',
                           ('已确认', total_amount, id))
                
                # 记录财务交易
                sale = conn.execute('SELECT * FROM sales_orders WHERE id = ?', (id,)).fetchone()
                record_financial_transaction(conn, '销售', sale['order_no'], total_amount, 
                                           '客户', session['username'], f'销售单确认 - {sale["order_no"]}')
                
                conn.commit()
                flash('销售单确认成功！', 'success')
            except Exception as e:
                conn.rollback()
                flash(f'确认失败：{str(e)}', 'error')
        
        elif action == 'add_item':
            # 添加商品
            product_id = request.form.get('product_id')
            quantity = int(request.form.get('quantity', 0))
            unit_price = float(request.form.get('unit_price', 0))
            
            try:
                conn.execute('''
                    INSERT INTO sales_order_items (order_id, product_id, quantity, unit_price)
                    VALUES (?, ?, ?, ?)
                ''', (id, product_id, quantity, unit_price))
                conn.commit()
                flash('商品添加成功！', 'success')
            except Exception as e:
                conn.rollback()
                flash(f'添加失败：{str(e)}', 'error')
    
    # 获取销售单信息
    sale = conn.execute('''
        SELECT so.*, c.name as customer_name
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        WHERE so.id = ?
    ''', (id,)).fetchone()
    
    # 获取销售单商品
    items = conn.execute('''
        SELECT soi.*, p.name as product_name, p.specification
        FROM sales_order_items soi
        LEFT JOIN products p ON soi.product_id = p.id
        WHERE soi.order_id = ?
    ''', (id,)).fetchall()
    
    # 获取所有商品
    products = conn.execute('SELECT * FROM products ORDER BY name').fetchall()
    
    conn.close()
    
    return render_template('edit_sale.html', sale=sale, items=items, products=products)

@sales_bp.route('/sales/view/<int:id>')
@login_required
@permission_required('sales')
def view_sale(id):
    conn = get_db_connection()
    
    # 获取销售单信息
    sale = conn.execute('''
        SELECT so.*, c.name as customer_name, c.contact_person, c.phone
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        WHERE so.id = ?
    ''', (id,)).fetchone()
    
    # 获取销售单商品
    items = conn.execute('''
        SELECT soi.*, p.name as product_name, p.specification, p.unit
        FROM sales_order_items soi
        LEFT JOIN products p ON soi.product_id = p.id
        WHERE soi.order_id = ?
    ''', (id,)).fetchall()
    
    conn.close()
    
    return render_template('view_sale.html', sale=sale, items=items)