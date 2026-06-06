from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import sqlite3
import os
import string
from io import BytesIO
import openpyxl
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'
app.config['UPLOAD_FOLDER'] = 'static/avatars'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.context_processor
def utility_processor():
    def get_cart_count():
        if 'user_id' not in session:
            return 0
        conn = sqlite3.connect('bookstore.db')
        c = conn.cursor()
        result = c.execute("SELECT SUM(quantity) FROM cart WHERE user_id = ?", (session['user_id'],)).fetchone()
        conn.close()
        return result[0] or 0
    return dict(cart_count=get_cart_count())

def sort_products_with_english_last(products, sort_key='name', reverse=False):
    """Сортировка: русские названия сначала, английские в конце"""
    def is_english_first_char(text):
        if not text:
            return False
        first_char = str(text)[0].lower()
        return first_char in string.ascii_lowercase
    
    russian = [p for p in products if not is_english_first_char(p.get(sort_key, ''))]
    english = [p for p in products if is_english_first_char(p.get(sort_key, ''))]
    
    if sort_key == 'price':
        russian.sort(key=lambda x: x.get(sort_key, 0), reverse=reverse)
        english.sort(key=lambda x: x.get(sort_key, 0), reverse=reverse)
    else:
        russian.sort(key=lambda x: str(x.get(sort_key, '')).lower(), reverse=reverse)
        english.sort(key=lambda x: str(x.get(sort_key, '')).lower(), reverse=reverse)
    
    return russian + english

def init_db():
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        avatar TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        author TEXT,
        price REAL NOT NULL,
        quantity INTEGER DEFAULT 0,
        category TEXT,
        description TEXT,
        cover_image TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS cart (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER DEFAULT 1,
        added_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (product_id) REFERENCES products(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        order_date TEXT DEFAULT CURRENT_TIMESTAMP,
        total_amount REAL NOT NULL,
        status TEXT DEFAULT 'Оплачено',
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        price REAL NOT NULL,
        quantity INTEGER NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id)
    )''')
    
    admin = c.execute("SELECT * FROM users WHERE username = 'admin'").fetchone()
    if not admin:
        c.execute("INSERT INTO users (username, email, password, is_admin) VALUES (?, ?, ?, ?)",
                  ('admin', 'admin@bookstore.com', generate_password_hash('admin123'), 1))
    
    if c.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        test_books = [
            ('Мастер и Маргарита', 'Михаил Булгаков', 450, 10, 'Классика', 'Великий роман о любви и дьяволе', None),
            ('Преступление и наказание', 'Фёдор Достоевский', 390, 5, 'Классика', 'Психологический роман', None),
            ('1984', 'Джордж Оруэлл', 420, 8, 'Антиутопия', 'Роман о тоталитаризме', None),
            ('Harry Potter and the Philosopher\'s Stone', 'J.K. Rowling', 650, 15, 'Fantasy', 'Beginning of adventures', None),
            ('Война и мир', 'Лев Толстой', 890, 3, 'Классика', 'Эпопея о русском обществе', None),
            ('Маленький принц', 'Антуан де Сент-Экзюпери', 350, 20, 'Сказка', 'Мудрая сказка', None),
            ('The Lord of the Rings', 'J.R.R. Tolkien', 1200, 7, 'Fantasy', 'Epic high fantasy novel', None),
        ]
        for book in test_books:
            c.execute("INSERT INTO products (name, author, price, quantity, category, description, cover_image) VALUES (?,?,?,?,?,?,?)",
                      book)
    
    conn.commit()
    conn.close()

init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему', 'warning')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            flash('Доступ запрещён', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    category = request.args.get('category', '')
    sort_by = request.args.get('sort', 'name')
    sort_order = request.args.get('order', 'asc')
    search = request.args.get('search', '')
    
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    
    query = "SELECT * FROM products WHERE 1=1"
    params = []
    
    if category:
        query += " AND category = ?"
        params.append(category)
    if search:
        query += " AND (name LIKE ? OR author LIKE ?)"
        params.append(f'%{search}%')
        params.append(f'%{search}%')
    
    products = c.execute(query, params).fetchall()
    categories = [row[0] for row in c.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != ''").fetchall()]
    
    conn.close()
    
    products_list = []
    for p in products:
        products_list.append({
            'id': p[0], 'name': p[1], 'author': p[2], 'price': p[3],
            'quantity': p[4], 'category': p[5], 'description': p[6],
            'cover_image': p[7], 'created_at': p[8]
        })
    
    reverse = (sort_order == 'desc')
    products_list = sort_products_with_english_last(products_list, sort_by, reverse)
    
    return render_template('index.html', products=products_list, categories=categories,
                           sort_by=sort_by, sort_order=sort_order,
                           current_category=category, search_query=search)

@app.route('/cart')
@login_required
def cart():
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    
    items = c.execute('''
        SELECT c.id, c.product_id, c.quantity, p.name, p.price, p.cover_image, p.quantity as stock
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id = ?
    ''', (session['user_id'],)).fetchall()
    
    cart_items = []
    total = 0
    for item in items:
        subtotal = item[4] * item[2]
        total += subtotal
        cart_items.append({
            'cart_id': item[0], 'product_id': item[1], 'quantity': item[2],
            'name': item[3], 'price': item[4], 'cover_image': item[5],
            'stock': item[6], 'subtotal': subtotal
        })
    
    conn.close()
    return render_template('cart.html', cart_items=cart_items, total=total)

@app.route('/add-to-cart/<int:product_id>')
@login_required
def add_to_cart(product_id):
    quantity = request.args.get('quantity', 1, type=int)
    
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    
    product = c.execute("SELECT quantity FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product or product[0] < quantity:
        flash('Недостаточно товара на складе', 'danger')
        conn.close()
        return redirect(url_for('index'))
    
    existing = c.execute("SELECT id, quantity FROM cart WHERE user_id = ? AND product_id = ?",
                         (session['user_id'], product_id)).fetchone()
    
    if existing:
        new_qty = existing[1] + quantity
        if new_qty > product[0]:
            flash('Недостаточно товара на складе', 'danger')
        else:
            c.execute("UPDATE cart SET quantity = ? WHERE id = ?", (new_qty, existing[0]))
            flash('Товар добавлен в корзину', 'success')
    else:
        c.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, ?)",
                  (session['user_id'], product_id, quantity))
        flash('Товар добавлен в корзину', 'success')
    
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/update-cart', methods=['POST'])
@login_required
def update_cart():
    cart_id = request.form.get('cart_id', type=int)
    quantity = request.form.get('quantity', type=int)
    
    if quantity <= 0:
        return redirect(url_for('remove_from_cart', cart_id=cart_id))
    
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    
    item = c.execute('''
        SELECT c.product_id, p.quantity FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.id = ? AND c.user_id = ?
    ''', (cart_id, session['user_id'])).fetchone()
    
    if item and item[1] >= quantity:
        c.execute("UPDATE cart SET quantity = ? WHERE id = ?", (quantity, cart_id))
        flash('Корзина обновлена', 'success')
    else:
        flash('Недостаточно товара', 'danger')
    
    conn.commit()
    conn.close()
    return redirect(url_for('cart'))

@app.route('/remove-from-cart/<int:cart_id>')
@login_required
def remove_from_cart(cart_id):
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    c.execute("DELETE FROM cart WHERE id = ? AND user_id = ?", (cart_id, session['user_id']))
    conn.commit()
    conn.close()
    flash('Товар удалён из корзины', 'success')
    return redirect(url_for('cart'))

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    
    items = c.execute('''
        SELECT c.id, c.quantity, p.name, p.price
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id = ?
    ''', (session['user_id'],)).fetchall()
    
    if not items:
        conn.close()
        flash('Корзина пуста. Добавьте товары перед оформлением заказа.', 'warning')
        return redirect(url_for('cart'))
    
    if request.method == 'POST':
        cart_items = c.execute('''
            SELECT c.product_id, c.quantity, p.name, p.price, p.quantity as stock
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = ?
        ''', (session['user_id'],)).fetchall()
        
        total = 0
        for item in cart_items:
            if item[4] < item[1]:
                flash(f'Недостаточно товара на складе: {item[2]}', 'danger')
                conn.close()
                return redirect(url_for('cart'))
            total += item[3] * item[1]
        
        c.execute("INSERT INTO orders (user_id, total_amount, status) VALUES (?, ?, ?)",
                  (session['user_id'], total, 'Оплачено'))
        order_id = c.lastrowid
        
        for item in cart_items:
            c.execute('''
                INSERT INTO order_items (order_id, product_id, product_name, price, quantity)
                VALUES (?, ?, ?, ?, ?)
            ''', (order_id, item[0], item[2], item[3], item[1]))
            c.execute("UPDATE products SET quantity = quantity - ? WHERE id = ?", (item[1], item[0]))
        
        c.execute("DELETE FROM cart WHERE user_id = ?", (session['user_id'],))
        conn.commit()
        conn.close()
        
        flash(f'Заказ №{order_id} успешно оформлен на сумму {total} ₽', 'success')
        return redirect(url_for('orders'))
    
    total = sum(item[3] * item[1] for item in items)
    conn.close()
    
    return render_template('checkout.html', cart_items=items, total=total)

@app.route('/orders')
@login_required
def orders():
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    
    user_orders = c.execute('''
        SELECT id, order_date, total_amount, status
        FROM orders
        WHERE user_id = ?
        ORDER BY order_date DESC
    ''', (session['user_id'],)).fetchall()
    
    orders_list = []
    for order in user_orders:
        items = c.execute('''
            SELECT product_name, price, quantity
            FROM order_items
            WHERE order_id = ?
        ''', (order[0],)).fetchall()
        
        order_items = []
        for item in items:
            order_items.append({
                'product_name': item[0],
                'price': item[1],
                'quantity': item[2]
            })
        
        orders_list.append({
            'id': order[0],
            'date': order[1],
            'total': order[2],
            'status': order[3],
            'order_items': order_items
        })
    
    conn.close()
    return render_template('orders.html', orders=orders_list)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = sqlite3.connect('bookstore.db')
        c = conn.cursor()
        user = c.execute("SELECT id, username, password, is_admin, avatar FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user[2], password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['is_admin'] = bool(user[3])
            session['user_avatar'] = user[4]
            flash('Вход выполнен успешно!', 'success')
            
            next_url = request.args.get('next')
            if next_url:
                return redirect(next_url)
            return redirect(url_for('index'))
        else:
            flash('Неверное имя пользователя или пароль', 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        password2 = request.form['password2']
        
        if password != password2:
            flash('Пароли не совпадают', 'danger')
            return redirect(url_for('register'))
        
        if len(password) < 4:
            flash('Пароль должен быть не менее 4 символов', 'danger')
            return redirect(url_for('register'))
        
        conn = sqlite3.connect('bookstore.db')
        c = conn.cursor()
        
        existing = c.execute("SELECT id FROM users WHERE username = ? OR email = ?", (username, email)).fetchone()
        if existing:
            flash('Пользователь с таким именем или email уже существует', 'danger')
            conn.close()
            return redirect(url_for('register'))
        
        c.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                  (username, email, generate_password_hash(password)))
        conn.commit()
        conn.close()
        
        flash('Регистрация успешна! Теперь войдите', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_avatar':
            if 'avatar' in request.files:
                file = request.files['avatar']
                if file and file.filename:
                    ext = file.filename.rsplit('.', 1)[-1].lower()
                    if ext in ['jpg', 'jpeg', 'png', 'gif']:
                        filename = f"user_{session['user_id']}_{datetime.now().timestamp()}.{ext}"
                        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        file.save(filepath)
                        avatar_url = f"/static/avatars/{filename}"
                        c.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar_url, session['user_id']))
                        session['user_avatar'] = avatar_url
                        conn.commit()
                        flash('Аватар обновлён', 'success')
                    else:
                        flash('Неверный формат файла', 'danger')
        
        elif action == 'delete_avatar':
            c.execute("UPDATE users SET avatar = NULL WHERE id = ?", (session['user_id'],))
            session['user_avatar'] = None
            conn.commit()
            flash('Аватар удалён', 'success')
        
        return redirect(url_for('profile'))
    
    user = c.execute("SELECT username, email, avatar FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    conn.close()
    
    return render_template('profile.html', user={
        'username': user[0], 'email': user[1], 'avatar': user[2]
    })

@app.route('/admin/products')
@admin_required
def admin_products():
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    products = c.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('admin_products.html', products=products)

@app.route('/admin/add-product', methods=['GET', 'POST'])
@admin_required
def admin_add_product():
    if request.method == 'POST':
        name = request.form['name']
        author = request.form.get('author', '')
        price = float(request.form['price'])
        quantity = int(request.form['quantity'])
        category = request.form.get('category', '')
        description = request.form.get('description', '')
        
        conn = sqlite3.connect('bookstore.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO products (name, author, price, quantity, category, description)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, author, price, quantity, category, description))
        conn.commit()
        conn.close()
        flash('Товар добавлен', 'success')
        return redirect(url_for('admin_products'))
    
    return render_template('admin_product_form.html', title='Добавить товар', product=None)

@app.route('/admin/edit-product/<int:product_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_product(product_id):
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    
    if request.method == 'POST':
        name = request.form['name']
        author = request.form.get('author', '')
        price = float(request.form['price'])
        quantity = int(request.form['quantity'])
        category = request.form.get('category', '')
        description = request.form.get('description', '')
        
        c.execute('''
            UPDATE products SET name=?, author=?, price=?, quantity=?, category=?, description=?
            WHERE id=?
        ''', (name, author, price, quantity, category, description, product_id))
        conn.commit()
        conn.close()
        flash('Товар обновлён', 'success')
        return redirect(url_for('admin_products'))
    
    product = c.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    return render_template('admin_product_form.html', title='Редактировать товар', product=product)

@app.route('/admin/delete-product/<int:product_id>')
@admin_required
def admin_delete_product(product_id):
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    c.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    flash('Товар удалён', 'success')
    return redirect(url_for('admin_products'))

@app.route('/admin/users')
@admin_required
def admin_users():
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    users = c.execute("SELECT id, username, email, is_admin, created_at FROM users").fetchall()
    conn.close()
    return render_template('admin_users.html', users=users)

@app.route('/admin/json-report')
@admin_required
def admin_json_report():
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    
    products = c.execute("SELECT id, name, author, price, quantity, category FROM products").fetchall()
    users = c.execute("SELECT id, username, email, is_admin, created_at FROM users").fetchall()
    orders = c.execute("SELECT id, user_id, order_date, total_amount, status FROM orders").fetchall()
    
    products_list = [{'id': p[0], 'name': p[1], 'author': p[2], 'price': p[3], 'quantity': p[4], 'category': p[5]} for p in products]
    users_list = [{'id': u[0], 'username': u[1], 'email': u[2], 'is_admin': bool(u[3]), 'registered_at': u[4]} for u in users]
    orders_list = [{'id': o[0], 'user_id': o[1], 'date': o[2], 'total': o[3], 'status': o[4]} for o in orders]
    
    total_revenue = sum(o[3] for o in orders)
    
    conn.close()
    
    report = {
        'store_name': 'BookStore',
        'generated_at': datetime.now().isoformat(),
        'statistics': {
            'total_products': len(products_list),
            'total_users': len(users_list),
            'total_orders': len(orders_list),
            'total_revenue': total_revenue
        },
        'products': products_list,
        'users': users_list,
        'orders': orders_list
    }
    
    return jsonify(report)

@app.route('/get-flash-messages')
def get_flash_messages():
    messages = [{'message': msg, 'category': cat} for cat, msg in get_flashed_messages(with_categories=True)]
    return jsonify(messages)

@app.route('/export-excel')
@login_required
def export_excel():
    conn = sqlite3.connect('bookstore.db')
    c = conn.cursor()
    orders = c.execute('''
        SELECT o.id, o.order_date, o.total_amount, o.status,
               GROUP_CONCAT(oi.product_name || ' (' || oi.quantity || ' шт.)', '; ')
        FROM orders o
        LEFT JOIN order_items oi ON o.id = oi.order_id
        WHERE o.user_id = ?
        GROUP BY o.id
        ORDER BY o.order_date DESC
    ''', (session['user_id'],)).fetchall()
    conn.close()
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Мои заказы"
    
    headers = ['ID заказа', 'Дата', 'Сумма', 'Статус', 'Товары']
    ws.append(headers)
    
    for row in orders:
        ws.append(list(row))
    
    for col in range(1, 6):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 20
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    return send_file(output, download_name='my_orders.xlsx', as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)