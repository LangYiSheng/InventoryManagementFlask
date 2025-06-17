from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import get_db_connection
from auth import login_required, permission_required
from utils import generate_order_no, record_stock_movement, record_financial_transaction
from datetime import datetime

purchase_bp = Blueprint('purchase', __name__)

@purchase_bp.route('/purchases')
@login_required
@permission_required('purchases')
def purchases():
    conn = get_db_connection()
    search = request.args.get('search', '')
    supplier_id = request.args.get('supplier_id', '')
    status = request.args.get('status', '')
    
    query = '''
        SELECT po.*, s.name as supplier_name, po.purchaser
        FROM purchase_orders po
        LEFT JOIN suppliers s ON po.supplier_id = s.id
        WHERE 1=1
    '''
    params = []
    
    if search:
        query += ' AND (po.order_no LIKE ? OR s.name LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
    
    if supplier_id:
        query += ' AND po.supplier_id = ?'
        params.append(supplier_id)
    
    if status:
        query += ' AND po.status = ?'
        params.append(status)
    else:
        # 默认不显示已退货的单据
        query += ' AND po.status != ?'
        params.append('已退货')
    
    query += ' ORDER BY po.created_at DESC'
    
    purchases = conn.execute(query, params).fetchall()
    suppliers = conn.execute('SELECT * FROM suppliers ORDER BY name').fetchall()
    conn.close()
    
    return render_template('purchases.html', purchases=purchases, suppliers=suppliers,
                         search=search, supplier_id=supplier_id, status=status)

@purchase_bp.route('/purchases/add', methods=['GET', 'POST'])
@login_required
@permission_required('purchases')
def add_purchase():
    conn = get_db_connection()
    try:
        if request.method == 'POST':
            supplier_id = request.form.get('supplier_id')
            notes = request.form.get('notes', '')
            purchaser = session.get('username', 'N/A') # 获取采购员，默认为当前用户

            # 获取表单提交的商品数据
            product_ids = request.form.getlist('product_id[]') # 注意name的[]
            quantities = request.form.getlist('quantity[]')
            unit_prices = request.form.getlist('unit_price[]')

            if not supplier_id:
                flash('请选择供应商。', 'error')
                # 重新加载页面，保留已填数据需要更复杂的处理，这里简化
                suppliers = conn.execute('SELECT * FROM suppliers ORDER BY name').fetchall()
                products_for_template = conn.execute('''
                    SELECT id, name, specification, unit, purchase_price, stock_quantity as current_stock
                    FROM products 
                    WHERE is_active = 1
                    ORDER BY name
                ''').fetchall()
                return render_template('add_purchase.html', suppliers=suppliers, products=products_for_template, notes=notes)
            
            # 检查是否至少添加了一项商品
            if not any(product_ids) or not any(pid for pid in product_ids if pid.strip()): # 确保至少有一个非空商品ID
                flash('请至少添加一个采购商品。', 'error')
                suppliers = conn.execute('SELECT * FROM suppliers ORDER BY name').fetchall()
                products_for_template = conn.execute('''
                    SELECT id, name, specification, unit, purchase_price, stock_quantity as current_stock
                    FROM products 
                    WHERE is_active = 1
                    ORDER BY name
                ''').fetchall()
                return render_template('add_purchase.html', suppliers=suppliers, products=products_for_template, supplier_id=supplier_id, notes=notes)

            # 创建采购单
            order_no = generate_order_no('PO')
            cursor = conn.execute('''
                INSERT INTO purchase_orders (order_no, supplier_id, total_amount, status, notes, purchaser, created_by)
                VALUES (?, ?, 0, '进行中', ?, ?, ?)
            ''', (order_no, supplier_id, notes, purchaser, session['user_id']))
            
            purchase_id = cursor.lastrowid
            
            # 添加商品明细并计算总金额
            total_amount = 0
            items_data_for_db = []
            for i in range(len(product_ids)):
                if product_ids[i] and product_ids[i].strip() and quantities[i] and unit_prices[i]: # 确保 product_id 不为空或仅包含空格
                    try:
                        product_id_val = int(product_ids[i])
                        quantity_val = float(quantities[i])
                        unit_price_val = float(unit_prices[i])
                        if quantity_val <= 0 or unit_price_val < 0: # 数量必须大于0，单价不能为负
                            raise ValueError("无效的数量或单价")
                        amount = quantity_val * unit_price_val
                        total_amount += amount
                        items_data_for_db.append((purchase_id, product_id_val, quantity_val, unit_price_val, amount))
                    except ValueError:
                        # 如果转换失败或值无效，跳过此项，或可以添加错误提示
                        flash(f'商品行 {i+1} 的数据无效，已跳过。', 'warning')
                        continue
            
            if not items_data_for_db:
                conn.rollback() # 如果没有有效的商品项，回滚采购单创建
                flash('未能添加任何有效的商品明细，采购单创建失败。', 'error')
                suppliers = conn.execute('SELECT * FROM suppliers ORDER BY name').fetchall()
                products_for_template = conn.execute('''
                    SELECT id, name, specification, unit, suggested_sale_price, stock_quantity as current_stock
                    FROM products 
                    WHERE is_active = 1
                    ORDER BY name
                ''').fetchall()
                return render_template('add_purchase.html', suppliers=suppliers, products=products_for_template, supplier_id=supplier_id, notes=notes)

            conn.executemany('''
                INSERT INTO purchase_order_items (order_id, product_id, quantity, unit_price, amount)
                VALUES (?, ?, ?, ?, ?)
            ''', items_data_for_db)
            
            # 更新采购单总金额和状态
            conn.execute('UPDATE purchase_orders SET total_amount = ?, status = ? WHERE id = ?', 
                       (total_amount, '已确认', purchase_id))
            
            # 记录财务交易 (应付账款增加)
            supplier_name_row = conn.execute('SELECT name FROM suppliers WHERE id = ?', (supplier_id,)).fetchone()
            supplier_name = supplier_name_row['name'] if supplier_name_row else '未知供应商'
            record_financial_transaction(conn, '采购支出', order_no, total_amount, 
                                       supplier_name, session['username'], 
                                       f'采购单 {order_no} 创建')
            
            # 记录库存变动 (采购入库)
            for item_data in items_data_for_db:
                _, prod_id, qty, _, _ = item_data
                record_stock_movement(conn, prod_id, qty, 'in', order_no, session['username'])
            
            conn.commit()
            flash('采购单创建成功，库存和财务已更新！', 'success')
            return redirect(url_for('purchase.purchases'))
        
        # GET 请求
        suppliers = conn.execute('SELECT * FROM suppliers ORDER BY name').fetchall()
        products = conn.execute('''
            SELECT id, name, specification, unit, purchase_price, stock_quantity as current_stock
            FROM products 
            WHERE is_active = 1
            ORDER BY name
        ''').fetchall()
        return render_template('add_purchase.html', suppliers=suppliers, products=products)

    except Exception as e:
        if conn: # 确保conn存在才执行rollback
            conn.rollback()
        flash(f'操作失败：{str(e)}', 'error')
        # 发生异常时，也尝试加载必要数据以重新渲染表单
        suppliers_on_error = []
        products_on_error = []
        try:
            # 尝试重新获取数据，即使主逻辑失败
            # 确保在 finally 块之外重新获取连接，如果 conn 在 try 中可能已关闭或无效
            error_conn = get_db_connection()
            suppliers_on_error = error_conn.execute('SELECT * FROM suppliers ORDER BY name').fetchall()
            products_on_error = error_conn.execute('''
                SELECT id, name, specification, unit, purchase_price, stock_quantity as current_stock
                FROM products 
                WHERE is_active = 1
                ORDER BY name
            ''').fetchall()
            error_conn.close()
        except Exception as fetch_error:
            flash(f'加载表单数据也失败: {str(fetch_error)}', 'error')
        
        return render_template('add_purchase.html', suppliers=suppliers_on_error, products=products_on_error, 
                                 supplier_id=request.form.get('supplier_id') if request.method == 'POST' else None,
                                 notes=request.form.get('notes') if request.method == 'POST' else None)
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# 删除 edit_purchase 路由，因为编辑功能合并到创建流程中
# @purchase_bp.route('/purchases/edit/<int:id>', methods=['GET', 'POST'])
# @login_required
# @permission_required('purchases')
# def edit_purchase(id):
    # conn = get_db_connection() # 这行及后续整个函数都将被删除或注释掉
    # ... (原 edit_purchase 函数的全部内容)
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_basic':
            # 更新基本信息
            # conn 在此action内部管理
            update_basic_conn = get_db_connection()
            try:
                supplier_id = request.form.get('supplier_id')
                purchaser = request.form.get('purchaser')
                notes = request.form.get('notes')
                
                update_basic_conn.execute('''
                    UPDATE purchase_orders 
                    SET supplier_id = ?, purchaser = ?, notes = ?
                    WHERE id = ?
                ''', (supplier_id, purchaser, notes, id))
                update_basic_conn.commit()
                flash('采购单信息更新成功！', 'success')
            except Exception as e:
                update_basic_conn.rollback()
                flash(f'更新失败：{str(e)}', 'error')
            finally:
                if update_basic_conn:
                    update_basic_conn.close()
        
        elif action == 'confirm':
            # 确认采购单
            # conn 在此action内部管理
            confirm_conn = get_db_connection()
            try:
                # 更新库存和财务记录
                items = confirm_conn.execute('''
                    SELECT poi.*, p.name as product_name, p.specification
                    FROM purchase_order_items poi
                    LEFT JOIN products p ON poi.product_id = p.id
                    WHERE poi.order_id = ?
                ''', (id,)).fetchall()
            except Exception as e:
                confirm_conn.rollback()
                flash(f'确认失败：{str(e)}', 'error')
            finally:
                if confirm_conn:
                    confirm_conn.close()
        
        elif action == 'add_item':
            # 保存商品明细
            add_item_conn = get_db_connection()
            try:
                # 获取现有商品明细
                existing_items_raw = add_item_conn.execute('SELECT product_id, quantity, unit_price FROM purchase_order_items WHERE order_id = ?', (id,)).fetchall()
                existing_items = {(item['product_id'], float(item['quantity']), float(item['unit_price'])) for item in existing_items_raw}

                # 获取表单提交的商品数据
                product_ids = request.form.getlist('product_id')
                quantities = request.form.getlist('quantity')
                unit_prices = request.form.getlist('unit_price')

                current_items = set()
                new_items_data = []
                for i in range(len(product_ids)):
                    if product_ids[i] and quantities[i] and unit_prices[i]:
                        product_id = int(product_ids[i])
                        quantity = float(quantities[i])
                        unit_price = float(unit_prices[i])
                        current_items.add((product_id, quantity, unit_price))
                        new_items_data.append({'product_id': product_id, 'quantity': quantity, 'unit_price': unit_price, 'amount': quantity * unit_price})

                # 检查是否有变化
                if existing_items != current_items:
                    # 删除现有商品明细
                    add_item_conn.execute('DELETE FROM purchase_order_items WHERE order_id = ?', (id,))
                    
                    # 重新添加商品明细
                    for item_data in new_items_data:
                        add_item_conn.execute('''
                            INSERT INTO purchase_order_items (order_id, product_id, quantity, unit_price, amount)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (id, item_data['product_id'], item_data['quantity'], item_data['unit_price'], item_data['amount']))
                    
                    add_item_conn.commit()
                    flash('采购单商品明细已更新！', 'success')
                else:
                    flash('商品明细未发生变化。', 'info')

            except Exception as e:
                add_item_conn.rollback()
                flash(f'保存失败：{str(e)}', 'error')
            finally:
                if add_item_conn:
                    add_item_conn.close()
    
    final_conn = None
    try:
        final_conn = get_db_connection()
        # 获取采购单信息
        purchase = final_conn.execute('''
            SELECT po.*, s.name as supplier_name
            FROM purchase_orders po
            LEFT JOIN suppliers s ON po.supplier_id = s.id
            WHERE po.id = ?
        ''', (id,)).fetchone()

        if not purchase:
            flash('采购单不存在！', 'error')
            return redirect(url_for('purchase.purchases'))

        # 获取采购单商品
        items = final_conn.execute('''
            SELECT poi.*, p.name as product_name, p.specification
            FROM purchase_order_items poi
            LEFT JOIN products p ON poi.product_id = p.id
            WHERE poi.order_id = ?
        ''', (id,)).fetchall()

        # 计算总金额
        current_total_amount = sum(item['amount'] for item in items) if items else 0

        action_taken = request.form.get('action') if request.method == 'POST' else None
        # 只有在添加/编辑商品明细 (add_item) 或明确更新基础信息后，才考虑更新总金额及相关记录
        if action_taken == 'add_item' or (action_taken == 'update_basic' and request.method == 'POST'):
            # 获取最新的商品明细，因为它们可能刚刚被修改
            current_items_for_calc = final_conn.execute('''
                SELECT poi.*, p.name as product_name
                FROM purchase_order_items poi
                JOIN products p ON poi.product_id = p.id
                WHERE poi.order_id = ?
            ''', (id,)).fetchall()
            
            new_total_amount = sum(item['quantity'] * item['unit_price'] for item in current_items_for_calc) if current_items_for_calc else 0

            # 检查总金额是否有变化，或者是否是 add_item 操作 (add_item 总是触发后续逻辑)
            if purchase['total_amount'] != new_total_amount or action_taken == 'add_item':
                # 更新采购单总金额和状态
                # 状态可以保持'进行中'，或者根据业务逻辑设置为'已更新'等
                final_conn.execute('UPDATE purchase_orders SET total_amount = ?, status = ? WHERE id = ?', 
                                   (new_total_amount, '进行中', id))
                
                # 重新获取采购单信息，确保 supplier_name 等信息是最新的
                updated_purchase_info = final_conn.execute('''
                    SELECT po.*, s.name as supplier_name 
                    FROM purchase_orders po 
                    LEFT JOIN suppliers s ON po.supplier_id = s.id 
                    WHERE po.id = ?
                ''', (id,)).fetchone()

                if updated_purchase_info:
                    # 记录财务交易 (应付账款增加/调整)
                    # 注意: 交易类型和描述需要根据实际业务场景精确定义
                    record_financial_transaction(final_conn, '采购支出', updated_purchase_info['order_no'], new_total_amount, 
                                               updated_purchase_info['supplier_name'], session['username'], 
                                               f'采购单 {updated_purchase_info["order_no"]} 更新')
                    
                    # 记录库存变动 (采购入库)
                    # 这里的逻辑假设每次编辑商品都是对当前采购单库存影响的完整体现
                    # 如果需要更复杂的增量更新或防止重复记录，需要调整 record_stock_movement 或在此处添加逻辑
                    for item in current_items_for_calc:
                        record_stock_movement(final_conn, item['product_id'], item['quantity'], 'in', 
                                            updated_purchase_info['order_no'], session['username'])
                    
                    final_conn.commit()
                    # 更新内存中的 purchase 变量以反映最新数据
                    purchase = updated_purchase_info
                    flash('采购单已更新，库存和财务已相应调整。', 'success')
                else:
                    final_conn.rollback() # 如果获取更新后的采购单信息失败，则回滚
                    flash('更新采购单信息失败，操作已回滚。', 'error')
            elif purchase['total_amount'] == new_total_amount and action_taken == 'update_basic':
                 # 如果是 update_basic 且总金额未变，则只提交基础信息的更改 (已在 action='update_basic' 块中完成)
                 # 此处不需要额外操作，之前的 flash('采购单信息更新成功！') 已经提示
                 pass
        
        total_amount = purchase['total_amount'] # 使用数据库中最新的总金额

        # 获取所有商品和供应商，用于表单选择
        products = final_conn.execute('''
            SELECT id, name, specification, unit, purchase_price, stock_quantity as current_stock
            FROM products 
            WHERE is_active = 1
            ORDER BY name
        ''').fetchall()
        suppliers = final_conn.execute('SELECT * FROM suppliers ORDER BY name').fetchall()

    except Exception as e:
        flash(f'加载采购单详情失败: {str(e)}', 'error')
        # 如果是POST请求中的错误，可能需要保留部分已填数据，但这里简化处理，直接重定向
        return redirect(url_for('purchase.purchases_list'))
    finally:
        if final_conn:
            final_conn.close()

    # 确保在 finally 块之后，purchase 和 items 仍然可用，如果上面 try 块出错，它们可能未定义
    # 但由于出错会重定向，所以到达这里的 purchase 和 items 应该是有效的
    # 如果 try 块中 flash 了错误并重定向，则不会执行到 render_template
    if not purchase: # 再次检查，以防万一
        # 此处 flash 和 redirect 已经在 try-except 中处理
        # 若能到此，说明 purchase 应该已加载，但作为防御性编程
        flash('采购单数据未能加载。', 'error')
        return redirect(url_for('purchase.purchases_list'))
    
    # 获取所有供应商
    # suppliers = conn.execute('SELECT * FROM suppliers ORDER BY name').fetchall() # 这行将在finally后执行，如果conn已关闭会出错
    
    # conn.close() # 连接关闭移到finally块中
    
    # return render_template('edit_purchase.html', purchase=purchase, items=items, products=products, suppliers=suppliers)

    # GET请求或POST请求处理完毕后（如果未重定向）
    # 需要确保conn是有效的，如果之前已关闭则重新获取
    # 这里的逻辑与 purchase_return 类似，确保数据获取和模板渲染的conn有效性
    
    # 重新组织获取数据的逻辑，确保在conn关闭前完成
    # 或者在渲染前重新获取连接和数据

    _purchase = None
    _items = None
    _products = None
    _suppliers = None

    # 尝试在 finally 块之前获取所有需要的数据
    # 如果 conn 在 POST 的 try/except 中关闭了，这里就需要重新获取
    # 为了代码清晰，我们在渲染前总是获取最新的数据
    
    final_conn = get_db_connection()
    try:
        _purchase = final_conn.execute('''
            SELECT po.*, s.name as supplier_name
            FROM purchase_orders po
            LEFT JOIN suppliers s ON po.supplier_id = s.id
            WHERE po.id = ?
        ''', (id,)).fetchone()
        
        _items = final_conn.execute('''
            SELECT poi.*, p.name as product_name, p.specification
            FROM purchase_order_items poi
            LEFT JOIN products p ON poi.product_id = p.id
            WHERE poi.order_id = ?
        ''', (id,)).fetchall()
        
        _products = final_conn.execute('''
            SELECT id, name, specification, unit, purchase_price, stock_quantity as current_stock
            FROM products 
            WHERE is_active = 1
            ORDER BY name
        ''').fetchall()
        _suppliers = final_conn.execute('SELECT * FROM suppliers ORDER BY name').fetchall()

        # 重新计算总金额并更新（如果需要）
        # 这个逻辑在POST的add_item后也执行了，这里是为了GET请求时的数据准确性
        if _purchase and _items:
            current_total_amount = sum(item['amount'] for item in _items)
            if current_total_amount != _purchase['total_amount']:
                final_conn.execute('UPDATE purchase_orders SET total_amount = ? WHERE id = ?', (current_total_amount, id))
                final_conn.commit()
                # 重新获取更新后的采购单信息
                _purchase = final_conn.execute('''
                    SELECT po.*, s.name as supplier_name
                    FROM purchase_orders po
                    LEFT JOIN suppliers s ON po.supplier_id = s.id
                    WHERE po.id = ?
                ''', (id,)).fetchone()

    finally:
        if final_conn:
            final_conn.close()
            
    if not _purchase: # 如果采购单不存在，则跳转
        flash('采购单不存在或获取失败!', 'error')
        return redirect(url_for('purchase.purchases'))

    return render_template('edit_purchase.html', purchase=_purchase, items=_items, products=_products, suppliers=_suppliers)

@purchase_bp.route('/purchases/view/<int:id>')
@login_required
@permission_required('purchases')
def view_purchase(id):
    conn = get_db_connection()
    
    # 获取采购单信息
    purchase = conn.execute('''
        SELECT po.*, s.name as supplier_name, s.contact_person, s.phone
        FROM purchase_orders po
        LEFT JOIN suppliers s ON po.supplier_id = s.id
        WHERE po.id = ?
    ''', (id,)).fetchone()
    
    # 获取采购单商品
    items = conn.execute('''
        SELECT poi.*, p.name as product_name, p.specification, p.unit
        FROM purchase_order_items poi
        LEFT JOIN products p ON poi.product_id = p.id
        WHERE poi.order_id = ?
    ''', (id,)).fetchall()
    
    # 计算总金额并更新
    total_amount = sum(item['amount'] for item in items) if items else 0
    if total_amount != purchase['total_amount']:
        conn.execute('UPDATE purchase_orders SET total_amount = ? WHERE id = ?', (total_amount, id))
        conn.commit()
        # 重新获取更新后的采购单信息
        purchase = conn.execute('''
            SELECT po.*, s.name as supplier_name, s.contact_person, s.phone
            FROM purchase_orders po
            LEFT JOIN suppliers s ON po.supplier_id = s.id
            WHERE po.id = ?
        ''', (id,)).fetchone()
    
    conn.close()
    
    return render_template('view_purchase.html', purchase=purchase, items=items)

@purchase_bp.route('/purchase_return/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('purchases')
def purchase_return(id):
    conn = get_db_connection()
    
    try:
        purchase = conn.execute('''
            SELECT po.*, s.name as supplier_name
            FROM purchase_orders po
            LEFT JOIN suppliers s ON po.supplier_id = s.id
            WHERE po.id = ?
        ''', (id,)).fetchone()
        
        if not purchase:
            flash('采购单不存在！', 'error')
            return redirect(url_for('purchase.purchases'))
        
        if request.method == 'POST':
            return_reason = request.form.get('return_reason')
            
            if not return_reason:
                flash('请填写退货原因！', 'error')
                return redirect(request.url)
            
            try:
                # 创建退货单
                cursor = conn.execute('''
                    INSERT INTO purchase_returns (original_order_id, return_reason)
                    VALUES (?, ?)
                ''', (id, return_reason))
                
                return_id = cursor.lastrowid
                
                # 获取采购单的所有商品并全部退货
                items = conn.execute('''
                    SELECT poi.product_id, poi.quantity, poi.unit_price
                    FROM purchase_order_items poi
                    WHERE poi.order_id = ?
                ''', (id,)).fetchall()
                
                total_return_amount = 0
                
                for item in items:
                    product_id = item['product_id']
                    return_quantity = item['quantity']
                    unit_price = item['unit_price']
                    
                    # 插入退货明细
                    amount = return_quantity * unit_price
                    conn.execute('''
                        INSERT INTO purchase_return_items (return_id, product_id, quantity, unit_price, amount)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (return_id, product_id, return_quantity, unit_price, amount))
                    
                    total_return_amount += return_quantity * unit_price
                    
                    # 记录库存变动（退货减少库存）
                    record_stock_movement(conn, product_id, -return_quantity, 'out', f'Return PO-{purchase["order_no"]}', session['username'])
                
                # 更新退货单总金额
                conn.execute('UPDATE purchase_returns SET total_return_amount = ? WHERE id = ?', (total_return_amount, return_id))
                
                # 记录财务交易 (采购退款)
                record_financial_transaction(conn, '采购退款', purchase['order_no'], total_return_amount, 
                                               purchase['supplier_name'], session['username'], 
                                               f'采购单 {purchase["order_no"]} 退货')
                
                # 更新原采购单状态为已退货或部分退货（根据业务逻辑）
                conn.execute('UPDATE purchase_orders SET status = ? WHERE id = ?', ('已退货', id))
                
                conn.commit()
                flash('采购退货成功！库存和财务已更新。', 'success')
                return redirect(url_for('purchase.purchases'))
                
            except Exception as e:
                conn.rollback()
                flash(f'退货失败：{str(e)}', 'error')
                return redirect(url_for('purchase.purchases'))
        
        # GET 请求，显示退货页面
        items_to_return = conn.execute('''
            SELECT poi.product_id, p.name as product_name, p.specification, p.unit, 
                   poi.quantity, poi.unit_price, poi.amount, p.stock_quantity as current_stock
            FROM purchase_order_items poi
            JOIN products p ON poi.product_id = p.id
            WHERE poi.order_id = ?
            ORDER BY poi.id
        ''', (id,)).fetchall()
        
        if not items_to_return:
            flash('该采购单没有可退货的商品。', 'warning')
        
        return render_template('purchase_return.html', purchase=purchase, items=items_to_return)
        
    except Exception as e:
        flash(f'加载退货页面时发生错误: {str(e)}', 'error')
        return redirect(url_for('purchase.purchases'))
    finally:
        if conn:
            conn.close()

@purchase_bp.route('/purchase_returns')
@login_required
@permission_required('purchases')
def purchase_returns():
    conn = get_db_connection()
    search = request.args.get('search', '')
    supplier_id = request.args.get('supplier_id', '')
    status = request.args.get('status', '')
    
    query = '''
        SELECT pr.*, s.name as supplier_name, po.order_no as original_order_no, po.supplier_id,
               COALESCE(SUM(pri.quantity * pri.unit_price), 0) as total_amount,
               COUNT(pri.id) as item_count
        FROM purchase_returns pr
        LEFT JOIN purchase_orders po ON pr.original_order_id = po.id
        LEFT JOIN suppliers s ON po.supplier_id = s.id
        LEFT JOIN purchase_return_items pri ON pr.id = pri.return_id
        WHERE 1=1
    '''
    params = []
    
    if search:
        query += ' AND (CAST(pr.id AS TEXT) LIKE ? OR s.name LIKE ? OR po.order_no LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    
    if supplier_id:
        query += ' AND po.supplier_id = ?'
        params.append(supplier_id)
    
    query += ' GROUP BY pr.id ORDER BY pr.return_date DESC'
    
    returns = conn.execute(query, params).fetchall()
    suppliers = conn.execute('SELECT * FROM suppliers ORDER BY name').fetchall()
    conn.close()
    
    return render_template('purchase_returns.html', returns=returns, suppliers=suppliers,
                         search=search, supplier_id=supplier_id, status=status)

@purchase_bp.route('/purchase_return/view/<int:return_id>')
@login_required
@permission_required('purchases')
def view_purchase_return(return_id):
    conn = get_db_connection()
    
    # 获取退货单信息
    return_order = conn.execute('''
        SELECT pr.*, po.order_no as original_order_no, s.name as supplier_name
        FROM purchase_returns pr
        LEFT JOIN purchase_orders po ON pr.original_order_id = po.id
        LEFT JOIN suppliers s ON po.supplier_id = s.id
        WHERE pr.id = ?
    ''', (return_id,)).fetchone()
    
    if not return_order:
        flash('退货单不存在！', 'error')
        return redirect(url_for('purchase.purchase_returns'))
    
    # 获取退货明细
    items = conn.execute('''
        SELECT pri.*, p.name as product_name, p.specification, p.unit
        FROM purchase_return_items pri
        LEFT JOIN products p ON pri.product_id = p.id
        WHERE pri.return_id = ?
        ORDER BY pri.id
    ''', (return_id,)).fetchall()
    
    conn.close()
    return render_template('view_purchase_return.html', return_order=return_order, items=items)