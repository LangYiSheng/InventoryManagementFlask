from datetime import datetime
import random
import string

def generate_order_no(prefix=''):
    """生成订单号"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_suffix = ''.join(random.choices(string.digits, k=3))
    return f"{prefix}{timestamp}{random_suffix}"

def format_currency(amount):
    """格式化货币显示"""
    if amount is None:
        return '0.00'
    return f"{float(amount):.2f}"

def calculate_stock_status(current_stock, min_stock, max_stock):
    """计算库存状态"""
    if current_stock <= 0:
        return 'out_of_stock', '缺货'
    elif current_stock < min_stock:
        return 'low_stock', '库存不足'
    elif current_stock > max_stock:
        return 'overstock', '库存过多'
    else:
        return 'normal', '正常'

def record_stock_movement(conn, product_id, change_quantity, movement_type, related_order_no=None, operator=None):
    """记录库存变动"""
    # 获取变动前库存
    product = conn.execute('SELECT stock_quantity FROM products WHERE id = ?', (product_id,)).fetchone()
    stock_before = product['stock_quantity']
    stock_after = stock_before + change_quantity
    
    # 记录库存变动
    conn.execute('''
        INSERT INTO stock_movements 
        (product_id, change_quantity, stock_before, stock_after, movement_type, related_order_no, operator)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (product_id, change_quantity, stock_before, stock_after, movement_type, related_order_no, operator))
    
    # 更新商品库存
    conn.execute('UPDATE products SET stock_quantity = ? WHERE id = ?', (stock_after, product_id))
    
    return stock_after

def record_financial_transaction(conn, transaction_type, order_no, amount, counterpart, operator, notes=None):
    """记录财务交易并更新系统余额"""
    conn.execute('''
        INSERT INTO financial_transactions 
        (transaction_type, order_no, amount, counterpart, operator, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (transaction_type, order_no, amount, counterpart, operator, notes))

    # 更新系统余额
    if transaction_type == '采购支出':
        conn.execute('UPDATE system_balance SET balance = balance - ? WHERE id = 1', (amount,))
    elif transaction_type == '销售收入':
        conn.execute('UPDATE system_balance SET balance = balance + ? WHERE id = 1', (amount,))
    elif transaction_type == '采购退款':
        conn.execute('UPDATE system_balance SET balance = balance + ? WHERE id = 1', (amount,))
    # 可以根据需要添加其他交易类型的余额更新逻辑，例如退款等
    # 例如: elif transaction_type == '销售退款': conn.execute('UPDATE system_balance SET balance = balance - ? WHERE id = 1', (amount,))