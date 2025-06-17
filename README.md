# Flask 库存管理系统

一个基于 Flask 框架开发的完整库存管理系统，支持商品管理、采购管理、销售管理、库存监控和财务管理等功能。

## 功能特性

### 🔐 用户认证与权限管理
- 用户登录/登出
- 基于角色的权限控制
- 细粒度权限管理（商品、采购、销售等模块权限）
- 用户管理（添加、编辑、删除用户）

### 📦 商品管理
- 商品信息管理（名称、规格、单位、价格等）
- 商品分类管理
- 库存数量管理
- 库存预警（最小库存、最大库存）
- 商品状态管理（启用/禁用）

### 🏪 供应商与客户管理
- 供应商信息管理
- 客户信息管理
- 联系人信息维护
- 供应商/客户状态管理

### 📋 采购管理
- 采购订单创建与管理
- 采购订单明细管理
- 采购退货处理
- 采购订单状态跟踪
- 自动生成采购单号

### 💰 销售管理
- 销售订单创建与管理
- 销售订单明细管理
- 销售退货处理
- 自动生成销售单号
- 销售数据统计

### 📊 库存管理
- 实时库存监控
- 库存变动记录
- 库存预警提醒
- 库存状态分析（缺货、库存不足、库存过多）

### 💳 财务管理
- 财务交易记录
- 系统余额管理
- 收支明细跟踪
- 财务数据统计

### 📈 数据统计与报表
- 仪表板数据展示
- 商品统计
- 客户/供应商统计
- 库存预警统计
- 最近交易记录

## 技术架构

### 后端技术栈
- **Web框架**: Flask 2.3.3
- **数据库**: SQLite3
- **密码加密**: Werkzeug Security
- **模板引擎**: Jinja2 3.1.2
- **会话管理**: Flask Session

### 项目结构
```
FlaskProject/
├── app.py                 # 主应用文件
├── models.py             # 数据模型和数据库初始化
├── auth.py               # 认证和权限装饰器
├── utils.py              # 工具函数
├── requirements.txt      # 项目依赖
├── routes/               # 路由模块
│   ├── __init__.py
│   ├── product_routes.py # 商品相关路由
│   ├── purchase_routes.py# 采购相关路由
│   └── sales_routes.py   # 销售相关路由
├── templates/            # HTML模板文件
│   ├── base.html        # 基础模板
│   ├── dashboard.html   # 仪表板
│   ├── login.html       # 登录页面
│   ├── products.html    # 商品列表
│   ├── add_product.html # 添加商品
│   ├── purchases.html   # 采购列表
│   ├── sales.html       # 销售列表
│   └── ...              # 其他页面模板
└── static/              # 静态文件目录
```

### 数据库设计

系统使用 SQLite 数据库，包含以下主要数据表：

- **users**: 用户表（用户信息、角色、权限）
- **categories**: 商品分类表
- **products**: 商品表（商品信息、库存、价格）
- **suppliers**: 供应商表
- **customers**: 客户表
- **purchase_orders**: 采购订单表
- **purchase_order_items**: 采购订单明细表
- **purchase_returns**: 采购退货表
- **purchase_return_items**: 采购退货明细表
- **sales_orders**: 销售订单表
- **sales_order_items**: 销售订单明细表
- **sales_returns**: 销售退货表
- **sales_return_items**: 销售退货明细表
- **stock_movements**: 库存变动记录表
- **financial_transactions**: 财务交易表
- **system_balance**: 系统余额表

## 安装与运行

### 环境要求
- Python 3.7+
- pip

### 安装步骤

1. **克隆项目**
```bash
git clone <repository-url>
cd FlaskProject
```

2. **创建虚拟环境（推荐）**
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

3. **安装依赖**
```bash
pip install -r requirements.txt
```

4. **初始化数据库**
```bash
python -c "from models import init_db; init_db()"
```

5. **运行应用**
```bash
python app.py
```

6. **访问应用**
打开浏览器访问 `http://localhost:5000`

### 默认账户
- **用户名**: admin
- **密码**: admin
- **权限**: 所有权限

## 核心功能模块

### 认证系统
- 使用 Flask Session 管理用户会话
- Werkzeug 提供密码哈希加密
- 装饰器实现登录验证和权限控制

### 权限系统
- 基于字符串的权限标识
- 支持模块级权限控制（products, purchases, sales, etc.）
- 超级权限 'all' 拥有所有权限

### 库存管理
- 自动库存变动记录
- 库存预警机制
- 支持最小库存和最大库存设置

### 订单系统
- 自动生成唯一订单号
- 支持订单明细管理
- 完整的退货流程

### 财务系统
- 自动记录财务交易
- 实时更新系统余额
- 支持收入和支出分类

## 开发说明

### 添加新功能
1. 在 `models.py` 中添加数据表结构
2. 在相应的路由文件中添加业务逻辑
3. 创建对应的 HTML 模板
4. 更新权限系统（如需要）

### 自定义配置
- 修改 `app.py` 中的 `secret_key`
- 数据库文件路径在 `models.py` 中的 `DATABASE` 变量
- 可以扩展 `utils.py` 添加更多工具函数

## 依赖说明

```
Flask==2.3.3          # Web框架
Werkzeug==2.3.7       # WSGI工具库，提供密码哈希等功能
Jinja2==3.1.2         # 模板引擎
MarkupSafe==2.1.3     # 安全的字符串处理
Itsdangerous==2.1.2   # 数据签名
Click==8.1.7          # 命令行工具
Blinker==1.6.3        # 信号系统
```

## 贡献

欢迎提交 Issue 和 Pull Request 来改进这个项目。

---

**注意**: 这是一个学习和演示项目，在生产环境使用前请进行充分的安全性评估和测试。
