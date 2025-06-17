from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import get_db_connection
from auth import login_required, permission_required

product_bp = Blueprint('product', __name__)

@product_bp.route('/products')
@login_required
@permission_required('products')
def products():
    conn = get_db_connection()
    search = request.args.get('search', '')
    category_id = request.args.get('category_id', '')
    status = request.args.get('status', '')
    
    query = '''
        SELECT p.*, c.name as category_name 
        FROM products p 
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE 1=1
    '''
    params = []
    
    if search:
        query += ' AND (p.name LIKE ? OR p.specification LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
    
    if category_id:
        query += ' AND p.category_id = ?'
        params.append(category_id)
    
    if status:
        if status == 'active':
            query += ' AND p.is_active = 1'
        elif status == 'inactive':
            query += ' AND p.is_active = 0'
    
    query += ' ORDER BY p.created_at DESC'
    
    products = conn.execute(query, params).fetchall()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    
    return render_template('products.html', products=products, categories=categories, 
                         search=search, category_id=category_id, status=status)

@product_bp.route('/products/add', methods=['GET', 'POST'])
@login_required
@permission_required('products')
def add_product():
    if request.method == 'POST':
        name = request.form.get('name', '')
        category_id = request.form.get('category_id') or None
        specification = request.form.get('specification', '')
        unit = request.form.get('unit', '')
        purchase_price = float(request.form.get('purchase_price', 0)) if request.form.get('purchase_price') else 0
        sale_price = float(request.form.get('sale_price', 0)) if request.form.get('sale_price') else 0
        min_stock = int(request.form.get('min_stock', 0)) if request.form.get('min_stock') else 0
        max_stock = int(request.form.get('max_stock', 1000)) if request.form.get('max_stock') else 1000
        is_active = 1 if request.form.get('is_active') else 0
        notes = request.form.get('notes', '')
        
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO products (name, category_id, specification, unit, purchase_price, sale_price, min_stock, max_stock, is_active, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, category_id, specification, unit, purchase_price, sale_price, min_stock, max_stock, is_active, notes))
        conn.commit()
        conn.close()
        
        flash('商品添加成功！', 'success')
        return redirect(url_for('product.products'))
    
    conn = get_db_connection()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    
    return render_template('add_product.html', categories=categories)

@product_bp.route('/products/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('products')
def edit_product(id):
    conn = get_db_connection()
    
    if request.method == 'POST':
        name = request.form.get('name', '')
        category_id = request.form.get('category_id') or None
        specification = request.form.get('specification', '')
        unit = request.form.get('unit', '')
        purchase_price = float(request.form.get('purchase_price', 0)) if request.form.get('purchase_price') else 0
        sale_price = float(request.form.get('sale_price', 0)) if request.form.get('sale_price') else 0
        min_stock = int(request.form.get('min_stock', 0)) if request.form.get('min_stock') else 0
        max_stock = int(request.form.get('max_stock', 1000)) if request.form.get('max_stock') else 1000
        is_active = 1 if request.form.get('is_active') else 0
        notes = request.form.get('notes', '')
        
        conn.execute('''
            UPDATE products 
            SET name=?, category_id=?, specification=?, unit=?, purchase_price=?, sale_price=?, min_stock=?, max_stock=?, is_active=?, notes=?
            WHERE id=?
        ''', (name, category_id, specification, unit, purchase_price, sale_price, min_stock, max_stock, is_active, notes, id))
        conn.commit()
        conn.close()
        
        flash('商品更新成功！', 'success')
        return redirect(url_for('product.products'))
    
    product = conn.execute('SELECT * FROM products WHERE id = ?', (id,)).fetchone()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    
    return render_template('edit_product.html', product=product, categories=categories)

@product_bp.route('/products/view/<int:id>')
@login_required
@permission_required('products')
def view_product(id):
    conn = get_db_connection()
    product = conn.execute('''
        SELECT p.*, c.name as category_name 
        FROM products p 
        LEFT JOIN categories c ON p.category_id = c.id 
        WHERE p.id = ?
    ''', (id,)).fetchone()
    
    # 获取库存变动记录
    movements = conn.execute('''
        SELECT * FROM stock_movements 
        WHERE product_id = ? 
        ORDER BY created_at DESC 
        LIMIT 20
    ''', (id,)).fetchall()
    
    conn.close()
    
    # 转换字段名以匹配模板
    if product:
        product = dict(product)
        product['status'] = 'active' if product['is_active'] else 'inactive'
        product['remark'] = product['notes']
        product['safety_stock'] = product['min_stock']
        product['current_stock'] = product['stock_quantity']
    
    return render_template('view_product.html', product=product, movements=movements)

@product_bp.route('/categories')
@login_required
@permission_required('products')
def categories():
    conn = get_db_connection()
    categories = conn.execute('''
        SELECT c1.*, c2.name as parent_name 
        FROM categories c1 
        LEFT JOIN categories c2 ON c1.parent_id = c2.id 
        ORDER BY c1.name
    ''').fetchall()
    conn.close()
    
    return render_template('categories.html', categories=categories)

@product_bp.route('/categories/add', methods=['GET', 'POST'])
@login_required
@permission_required('products')
def add_category():
    if request.method == 'POST':
        name = request.form['name']
        parent_id = request.form.get('parent_id') or None
        
        conn = get_db_connection()
        conn.execute('INSERT INTO categories (name, parent_id) VALUES (?, ?)', (name, parent_id))
        conn.commit()
        conn.close()
        
        flash('分类添加成功', 'success')
        return redirect(url_for('product.categories'))
    
    conn = get_db_connection()
    parent_categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    return render_template('add_category.html', parent_categories=parent_categories)

@product_bp.route('/categories/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('products')
def edit_category(id):
    conn = get_db_connection()
    
    if request.method == 'POST':
        name = request.form.get('name', '')
        description = request.form.get('description', '')
        parent_id = request.form.get('parent_id')
        
        # 如果parent_id为空字符串，设置为None
        if parent_id == '':
            parent_id = None
        
        conn.execute('UPDATE categories SET name=?, description=?, parent_id=? WHERE id=?', 
                    (name, description, parent_id, id))
        conn.commit()
        conn.close()
        
        flash('分类更新成功！', 'success')
        return redirect(url_for('product.categories'))
    
    category = conn.execute('SELECT * FROM categories WHERE id = ?', (id,)).fetchone()
    # 获取所有分类作为上级分类选项（排除当前分类本身）
    parent_categories = conn.execute('SELECT * FROM categories WHERE id != ? ORDER BY name', (id,)).fetchall()
    conn.close()
    
    return render_template('edit_category.html', category=category, parent_categories=parent_categories)

@product_bp.route('/delete_category/<int:id>')
@login_required
@permission_required('products')
def delete_category(id):
    conn = get_db_connection()
    
    # 检查是否有子分类
    child_count = conn.execute('SELECT COUNT(*) FROM categories WHERE parent_id = ?', (id,)).fetchone()[0]
    if child_count > 0:
        flash('该分类下存在子分类，无法删除', 'error')
        conn.close()
        return redirect(url_for('product.categories'))
    
    # 检查是否有商品使用此分类
    product_count = conn.execute('SELECT COUNT(*) FROM products WHERE category_id = ?', (id,)).fetchone()[0]
    if product_count > 0:
        flash('该分类下存在商品，无法删除', 'error')
        conn.close()
        return redirect(url_for('product.categories'))
    
    conn.execute('DELETE FROM categories WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    flash('分类删除成功', 'success')
    return redirect(url_for('product.categories'))

@product_bp.route('/delete_product/<int:id>')
@login_required
def delete_product(id):
    conn = get_db_connection()
    
    # 检查是否有相关订单
    purchase_count = conn.execute('SELECT COUNT(*) FROM purchase_order_items WHERE product_id = ?', (id,)).fetchone()[0]
    sales_count = conn.execute('SELECT COUNT(*) FROM sales_order_items WHERE product_id = ?', (id,)).fetchone()[0]
    
    if purchase_count > 0 or sales_count > 0:
        flash('该商品存在相关订单，无法删除', 'error')
        conn.close()
        return redirect(url_for('product.products'))
    
    conn.execute('DELETE FROM products WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    flash('商品删除成功', 'success')
    return redirect(url_for('product.products'))