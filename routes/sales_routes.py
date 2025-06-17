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
    
    query += ' ORDER BY so.created_at DESC'
    
    sales = conn.execute(query, params).fetchall()
    customers = conn.execute('SELECT * FROM customers ORDER BY name').fetchall()
    conn.close()
    
    return render_template('sales.html', sales=sales, customers=customers,
                         search=search, customer_id=customer_id)

@sales_bp.route('/sales/add', methods=['GET', 'POST'])
@login_required
@permission_required('sales')
def add_sale():
    conn = get_db_connection()
    try:
        if request.method == 'POST':
            customer_id = request.form.get('customer_id')
            notes = request.form.get('notes', '')
            salesperson = session.get('username', 'N/A')

            product_ids = request.form.getlist('product_id[]')
            quantities = request.form.getlist('quantity[]')
            unit_prices = request.form.getlist('unit_price[]')

            if not customer_id:
                flash('请选择客户。', 'error')
                customers = conn.execute('SELECT * FROM customers ORDER BY name').fetchall()
                products_for_template = conn.execute('''
                    SELECT id, name, specification, unit, sale_price, stock_quantity as current_stock
                    FROM products 
                    WHERE is_active = 1
                    ORDER BY name
                ''').fetchall()
                return render_template('add_sale.html', customers=customers, products=products_for_template, notes=notes)

            if not any(product_ids) or not any(pid for pid in product_ids if pid.strip()):
                flash('请至少添加一个销售商品。', 'error')
                customers = conn.execute('SELECT * FROM customers ORDER BY name').fetchall()
                products_for_template = conn.execute('''
                    SELECT id, name, specification, unit, sale_price, stock_quantity as current_stock
                    FROM products 
                    WHERE is_active = 1
                    ORDER BY name
                ''').fetchall()
                return render_template('add_sale.html', customers=customers, products=products_for_template, customer_id=customer_id, notes=notes)

            order_no = generate_order_no('SO')
            cursor = conn.execute('''
                INSERT INTO sales_orders (order_no, customer_id, total_amount, salesperson)
                VALUES (?, ?, 0, ?)
            ''', (order_no, customer_id, salesperson))
            sale_id = cursor.lastrowid

            total_amount = 0
            items_data_for_db = []
            for i in range(len(product_ids)):
                if product_ids[i] and product_ids[i].strip() and quantities[i] and unit_prices[i]:
                    try:
                        product_id_val = int(product_ids[i])
                        quantity_val = float(quantities[i])
                        unit_price_val = float(unit_prices[i])
                        
                        # 检查库存
                        product_info = conn.execute('SELECT name, stock_quantity FROM products WHERE id = ?', (product_id_val,)).fetchone()
                        if not product_info or product_info['stock_quantity'] < quantity_val:
                            product_name = product_info['name'] if product_info else f'ID {product_id_val}'
                            current_stock = product_info['stock_quantity'] if product_info else 0
                            flash(f'商品 "{product_name}" 库存不足 (当前库存: {current_stock}, 需求: {quantity_val})。', 'error')
                            # 回滚事务，因为一个商品失败则整个订单失败
                            conn.rollback()
                            customers_on_fail = conn.execute('SELECT * FROM customers ORDER BY name').fetchall()
                            products_on_fail = conn.execute('''
                SELECT id, name, specification, unit, sale_price, stock_quantity as current_stock
                FROM products 
                WHERE is_active = 1
                ORDER BY name
            ''').fetchall()
                            return render_template('add_sale.html', customers=customers_on_fail, products=products_on_fail, customer_id=customer_id, notes=notes)
                            
                        if quantity_val <= 0 or unit_price_val < 0:
                            raise ValueError("无效的数量或单价")
                        amount = quantity_val * unit_price_val
                        total_amount += amount
                        items_data_for_db.append((sale_id, product_id_val, quantity_val, unit_price_val, amount))
                    except ValueError:
                        flash(f'商品行 {i+1} 的数据无效，已跳过。', 'warning')
                        continue
            
            if not items_data_for_db:
                conn.rollback()
                flash('未能添加任何有效的商品明细，销售单创建失败。', 'error')
                customers = conn.execute('SELECT * FROM customers ORDER BY name').fetchall()
                products_for_template = conn.execute('''
                SELECT id, name, specification, unit, sale_price, stock_quantity as current_stock
                FROM products 
                WHERE is_active = 1
                ORDER BY name
            ''').fetchall()
                return render_template('add_sale.html', customers=customers, products=products_for_template, customer_id=customer_id, notes=notes)

            conn.executemany('''
                INSERT INTO sales_order_items (order_id, product_id, quantity, unit_price, amount)
                VALUES (?, ?, ?, ?, ?)
            ''', items_data_for_db)

            conn.execute('UPDATE sales_orders SET total_amount = ? WHERE id = ?', 
                       (total_amount, sale_id))

            customer_name_row = conn.execute('SELECT name FROM customers WHERE id = ?', (customer_id,)).fetchone()
            customer_name = customer_name_row['name'] if customer_name_row else '未知客户'
            record_financial_transaction(conn, '销售收入', order_no, total_amount, 
                                       customer_name, salesperson, 
                                       f'销售单 {order_no} 创建')

            for item_data in items_data_for_db:
                _, prod_id, qty, _, _ = item_data
                record_stock_movement(conn, prod_id, -qty, 'out', order_no, salesperson) # 销售出库，数量为负
            
            conn.commit()
            flash('销售单创建成功，库存和财务已更新！', 'success')
            return redirect(url_for('sales.sales'))
        
        # GET 请求
        customers = conn.execute('SELECT * FROM customers ORDER BY name').fetchall()
        products = conn.execute('''
            SELECT id, name, specification, unit, sale_price, stock_quantity as current_stock
            FROM products 
            WHERE is_active = 1
            ORDER BY name
        ''').fetchall()
        return render_template('add_sale.html', customers=customers, products=products)

    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'操作失败：{str(e)}', 'error')
        customers_on_error = []
        products_on_error = []
        try:
            error_conn = get_db_connection() # 重新获取连接以防主conn已关闭
            customers_on_error = error_conn.execute('SELECT * FROM customers ORDER BY name').fetchall()
            products_on_error = error_conn.execute('''
                SELECT id, name, specification, unit, sale_price, stock_quantity as current_stock
                FROM products 
                WHERE is_active = 1
                ORDER BY name
            ''').fetchall()
            error_conn.close()
        except Exception as fetch_error:
            flash(f'加载表单数据也失败: {str(fetch_error)}', 'error')
        
        return render_template('add_sale.html', customers=customers_on_error, products=products_on_error,
                                 customer_id=request.form.get('customer_id') if request.method == 'POST' else None,
                                 notes=request.form.get('notes') if request.method == 'POST' else None)
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

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

@sales_bp.route('/sales/return/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('sales')
def sales_return(id):
    conn = get_db_connection()
    try:
        # 获取销售单信息
        sale = conn.execute('''
            SELECT so.*, c.name as customer_name
            FROM sales_orders so
            LEFT JOIN customers c ON so.customer_id = c.id
            WHERE so.id = ?
        ''', (id,)).fetchone()
        
        if not sale:
            flash('销售单不存在。', 'error')
            return redirect(url_for('sales.sales'))

        # 销售单创建后即可退货，无需状态检查

        if request.method == 'POST':
            return_reason = request.form.get('return_reason', '').strip()
            if not return_reason:
                flash('请填写退货原因。', 'error')
                # 重新获取数据并渲染页面
                items_to_return = conn.execute('''
                    SELECT soi.product_id, p.name as product_name, soi.quantity, soi.unit_price, soi.amount
                    FROM sales_order_items soi
                    JOIN products p ON soi.product_id = p.id
                    WHERE soi.order_id = ?
                ''', (id,)).fetchall()
                return render_template('sales_return.html', sale=sale, items=items_to_return)

            # 创建退货单
            cursor = conn.execute('''
                INSERT INTO sales_returns (original_order_id, original_order_no, customer_name, return_reason, total_return_amount)
                VALUES (?, ?, ?, ?, ?)
            ''', (id, sale['order_no'], sale['customer_name'], return_reason, sale['total_amount']))
            return_id = cursor.lastrowid

            # 获取原销售单商品明细并全部退货
            items = conn.execute('SELECT * FROM sales_order_items WHERE order_id = ?', (id,)).fetchall()
            total_return_amount = 0
            
            for item in items:
                # 插入退货明细
                conn.execute('''
                    INSERT INTO sales_return_items (return_id, product_id, quantity, unit_price, amount)
                    VALUES (?, ?, ?, ?, ?)
                ''', (return_id, item['product_id'], item['quantity'], item['unit_price'], item['amount']))
                
                total_return_amount += item['amount']
                
                # 记录库存变动 (增加退回商品的数量)
                record_stock_movement(conn, item['product_id'], item['quantity'], 'in', 
                                    f'销售退货-{sale["order_no"]}', session.get('username', 'N/A'))

            # 更新退货单总金额
            conn.execute('UPDATE sales_returns SET total_return_amount = ? WHERE id = ?', (total_return_amount, return_id))
            
            # 删除原销售单及其明细（退货后从销售单管理中移除）
            conn.execute('DELETE FROM sales_order_items WHERE order_id = ?', (id,))
            conn.execute('DELETE FROM sales_orders WHERE id = ?', (id,))

            # 记录财务交易 (销售退款)
            record_financial_transaction(conn, '销售退款', sale['order_no'], total_return_amount, 
                                       sale['customer_name'], session.get('username', 'N/A'), 
                                       f'销售单 {sale["order_no"]} 退货，原因：{return_reason}')

            conn.commit()
            flash('销售单退货成功！库存和财务已更新，原销售单已移至退货单管理。', 'success')
            return redirect(url_for('sales.sales_returns'))
        
        # GET 请求，显示退货页面
        items_to_return = conn.execute('''
            SELECT soi.product_id, p.name as product_name, soi.quantity, soi.unit_price, soi.amount
            FROM sales_order_items soi
            JOIN products p ON soi.product_id = p.id
            WHERE soi.order_id = ?
        ''', (id,)).fetchall()
        
        if not items_to_return:
            flash('该销售单没有可退货的商品。', 'warning')
        
        return render_template('sales_return.html', sale=sale, items=items_to_return)
        
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'退货失败：{str(e)}', 'error')
        return redirect(url_for('sales.view_sale', id=id))
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@sales_bp.route('/sales_returns')
@login_required
@permission_required('sales')
def sales_returns():
    conn = get_db_connection()
    search = request.args.get('search', '')
    customer_id = request.args.get('customer_id', '')
    status = request.args.get('status', '')
    
    query = '''
        SELECT sr.*, c.name as customer_name, so.order_no as original_order_no, so.customer_id,
               COALESCE(SUM(sri.quantity * sri.unit_price), 0) as total_amount,
               COUNT(sri.id) as item_count
        FROM sales_returns sr
        LEFT JOIN sales_orders so ON sr.original_order_id = so.id
        LEFT JOIN customers c ON so.customer_id = c.id
        LEFT JOIN sales_return_items sri ON sr.id = sri.return_id
        WHERE 1=1
    '''
    params = []
    
    if search:
        query += ' AND (CAST(sr.id AS TEXT) LIKE ? OR c.name LIKE ? OR so.order_no LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    
    if customer_id:
        query += ' AND so.customer_id = ?'
        params.append(customer_id)
    
    query += ' GROUP BY sr.id ORDER BY sr.return_date DESC'
    
    returns = conn.execute(query, params).fetchall()
    customers = conn.execute('SELECT * FROM customers ORDER BY name').fetchall()
    conn.close()
    
    return render_template('sales_returns.html', returns=returns, customers=customers,
                         search=search, customer_id=customer_id, status=status)

@sales_bp.route('/sales_return/view/<int:return_id>')
@login_required
@permission_required('sales')
def view_sales_return(return_id):
    conn = get_db_connection()
    
    # 获取退货单信息
    return_order = conn.execute('''
        SELECT sr.*
        FROM sales_returns sr
        WHERE sr.id = ?
    ''', (return_id,)).fetchone()
    
    if not return_order:
        flash('退货单不存在！', 'error')
        return redirect(url_for('sales.sales_returns'))
    
    # 获取退货明细
    return_items = conn.execute('''
        SELECT sri.*, p.name as product_name, p.unit
        FROM sales_return_items sri
        LEFT JOIN products p ON sri.product_id = p.id
        WHERE sri.return_id = ?
    ''', (return_id,)).fetchall()
    
    conn.close()
    
    return render_template('view_sales_return.html', return_order=return_order, return_items=return_items)