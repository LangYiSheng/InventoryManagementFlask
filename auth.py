from functools import wraps
from flask import session, redirect, url_for, flash
from models import get_db_connection

def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def permission_required(permission):
    """权限验证装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('请先登录', 'error')
                return redirect(url_for('login'))
            
            # 获取用户权限
            conn = get_db_connection()
            user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
            conn.close()
            
            if not user:
                flash('用户不存在', 'error')
                return redirect(url_for('login'))
            
            # 检查权限
            user_permissions = user['permissions'].split(',') if user['permissions'] else []
            if 'all' not in user_permissions and permission not in user_permissions:
                flash('权限不足', 'error')
                return redirect(url_for('dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator