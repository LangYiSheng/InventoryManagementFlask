from flask import g
import sqlite3
from werkzeug.security import generate_password_hash

DATABASE = 'inventory_system.db'

def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库"""
    conn = get_db_connection()
    
    # 用户表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(20) DEFAULT 'user',
            permissions TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    
    # 商品分类表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            parent_id INTEGER,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parent_id) REFERENCES categories (id)
        )
    ''')
    
    # 商品表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(200) NOT NULL,
            category_id INTEGER,
            specification VARCHAR(200),
            unit VARCHAR(20),
            purchase_price DECIMAL(10,2),
            sale_price DECIMAL(10,2),
            suggested_sale_price DECIMAL(10,2),
            stock_quantity INTEGER DEFAULT 0,
            min_stock INTEGER DEFAULT 0,
            max_stock INTEGER DEFAULT 1000,
            is_active BOOLEAN DEFAULT 1,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories (id)
        )
    ''')
    
    # 供应商表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(200) NOT NULL,
            contact_person VARCHAR(100),
            phone VARCHAR(20),
            email VARCHAR(100),
            address TEXT,
            notes TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 客户表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(200) NOT NULL,
            contact_person VARCHAR(100),
            phone VARCHAR(20),
            email VARCHAR(100),
            address TEXT,
            notes TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 采购单表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no VARCHAR(50) UNIQUE NOT NULL,
            supplier_id INTEGER NOT NULL,
            total_amount DECIMAL(10,2) DEFAULT 0,
            purchaser VARCHAR(100),
            status VARCHAR(20) DEFAULT 'completed',
            notes TEXT,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
        )
    ''')
    
    # 采购单明细表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS purchase_order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price DECIMAL(10,2) NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            FOREIGN KEY (order_id) REFERENCES purchase_orders (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    
    # 采购退货单表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS purchase_returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_order_id INTEGER NOT NULL,
            return_reason TEXT,
            total_return_amount DECIMAL(10,2) DEFAULT 0,
            return_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (original_order_id) REFERENCES purchase_orders (id)
        )
    ''')
    
    # 采购退货明细表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS purchase_return_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            return_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity DECIMAL(10,2) NOT NULL,
            unit_price DECIMAL(10,2) NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            FOREIGN KEY (return_id) REFERENCES purchase_returns (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    
    # 销售单表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sales_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no VARCHAR(50) UNIQUE NOT NULL,
            customer_id INTEGER NOT NULL,
            total_amount DECIMAL(10,2) DEFAULT 0,
            salesperson VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers (id)
        )
    ''')
    
    # 销售单明细表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sales_order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price DECIMAL(10,2) NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            FOREIGN KEY (order_id) REFERENCES sales_orders (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    
    # 销售退货单表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sales_returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_order_id INTEGER NOT NULL,
            original_order_no VARCHAR(50),
            customer_name VARCHAR(200),
            return_reason TEXT,
            total_return_amount DECIMAL(10,2) DEFAULT 0,
            return_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (original_order_id) REFERENCES sales_orders (id)
        )
    ''')
    
    # 销售退货明细表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sales_return_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            return_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity DECIMAL(10,2) NOT NULL,
            unit_price DECIMAL(10,2) NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            FOREIGN KEY (return_id) REFERENCES sales_returns (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    
    # 库存变动记录表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            change_quantity INTEGER NOT NULL,
            stock_before INTEGER NOT NULL,
            stock_after INTEGER NOT NULL,
            movement_type VARCHAR(20) NOT NULL,
            related_order_no VARCHAR(50),
            operator VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    
    # 财务交易表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS financial_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_type VARCHAR(20) NOT NULL,
            order_no VARCHAR(50),
            amount DECIMAL(10,2) NOT NULL,
            counterpart VARCHAR(200),
            operator VARCHAR(100),
            notes TEXT,
            transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 系统余额表
    conn.execute('''
        CREATE TABLE IF NOT EXISTS system_balance (
            id INTEGER PRIMARY KEY,
            balance DECIMAL(15,2) DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 插入默认管理员用户
    admin_password = generate_password_hash('admin')
    conn.execute('INSERT OR IGNORE INTO users (username, password_hash, role, permissions) VALUES (?, ?, ?, ?)',
                ('admin', admin_password, 'admin', 'all'))
    
    # 插入默认系统余额记录
    conn.execute('INSERT OR IGNORE INTO system_balance (id, balance) VALUES (1, 0)')
    
    # 为现有数据库添加suggested_sale_price字段（如果不存在）
    try:
        conn.execute('ALTER TABLE products ADD COLUMN suggested_sale_price DECIMAL(10,2)')
    except Exception:
        # 字段已存在，忽略错误
        pass
    
    conn.commit()
    conn.close()
    print("数据库初始化完成")