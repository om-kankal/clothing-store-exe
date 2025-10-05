# app.py – Universal Store Billing (EXE) – FINAL
import sys, os, datetime, uuid
from PyQt5.QtWidgets import *
from PyQt5.QtCore import QDate
from PyQt5.QtPrintSupport import QPrinter, QPrintDialog
from PyQt5.QtGui import QFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
import sqlite3

DB = os.path.join(os.path.dirname(__file__), 'store.db')
conn = sqlite3.connect(DB, check_same_thread=False)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# ---------- SCHEMA + MIGRATION ----------
cur.executescript('''
PRAGMA foreign_keys = OFF;
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS products(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,
    price REAL NOT NULL,
    cost_price REAL NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL,
    tax_rate REAL DEFAULT 18,
    barcode TEXT UNIQUE,
    description TEXT
);
CREATE TABLE IF NOT EXISTS customers(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT UNIQUE,
    email TEXT,
    address TEXT,
    total_purchases REAL DEFAULT 0,
    last_visit DATE
);
CREATE TABLE IF NOT EXISTS invoices(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT UNIQUE,
    date DATE,
    customer_id INTEGER,
    subtotal REAL,
    discount_name TEXT,
    discount_percent REAL,
    tax REAL,
    total REAL
);
CREATE TABLE IF NOT EXISTS invoice_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER,
    product_id INTEGER,
    quantity INTEGER,
    price REAL,
    cost_price REAL,
    tax_rate REAL
);
INSERT OR IGNORE INTO settings(key,value) VALUES
('store_name','Lilly''s Closet'),
('store_address','6351 Fringilla Avenue\nGardena Colorado 37\nUnited States'),
('store_email','lillyscloset@gmail.com'),
('store_phone','559-104-5475'),
('dark_mode','0');
PRAGMA foreign_keys = ON;
''')

# migrate columns
cols = [r['name'] for r in cur.execute("PRAGMA table_info(products)").fetchall()]
if 'cost_price' not in cols:
    cur.execute("ALTER TABLE products ADD COLUMN cost_price REAL NOT NULL DEFAULT 0")
    cur.execute("ALTER TABLE invoice_items ADD COLUMN cost_price REAL NOT NULL DEFAULT 0")
conn.commit()


def get_setting(k, default=""):
    return cur.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()['value'] or default


def set_setting(k, v):
    cur.execute("REPLACE INTO settings(key,value) VALUES(?,?)", (k, v))
    conn.commit()


# ----------------------------------------------------------
class BillingApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Universal Store Billing – Complete")
        self.resize(1350, 900)
        self.cart = []
        self.discount = {"name": "", "percent": 0.0}
        self.dark_mode = bool(int(get_setting('dark_mode')))
        self.apply_theme()
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.init_billing_tab()
        self.init_product_tab()
        self.init_customer_tab()
        self.init_report_tab()
        self.init_history_tab()
        self.init_settings_tab()
        self.load_products()
        self.load_customers()

    # ---------- THEME ----------
    def apply_theme(self):
        if self.dark_mode:
            self.setStyleSheet("""
                * { background:#1e1e2e; color:#f5f5f5; }
                QPushButton { background:#7b2cbf; border:1px solid #9d4edd; padding:6px; border-radius:4px; }
                QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox { background:#2e2e3e; border:1px solid #9d4edd; }
                QTableWidget { gridline-color:#5a189a; alternate-background-color:#2e2e3e; }
                QHeaderView::section { background:#7b2cbf; color:#ffffff; }
            """)
        else:
            self.setStyleSheet("""
                * { background:#f5f5f5; color:#1e1e2e; }
                QPushButton { background:#7b2cbf; color:white; border:none; padding:6px; border-radius:4px; }
                QPushButton:hover { background:#9d4edd; }
                QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox { background:white; border:1px solid #7b2cbf; }
                QTableWidget { gridline-color:#7b2cbf; alternate-background-color:#f3e5f5; }
                QHeaderView::section { background:#7b2cbf; color:#ffffff; }
            """)

    # ---------- BILLING ----------
    def init_billing_tab(self):
        w = QWidget()
        lay = QHBoxLayout(w)

        # LEFT – products
        left = QVBoxLayout()
        self.bill_search = QLineEdit()
        self.bill_search.setPlaceholderText("Search products")
        self.product_table = QTableWidget()
        self.product_table.setColumnCount(8)
        self.product_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Category", "Price", "Cost", "Stock", "Tax%", "Barcode"])
        self.product_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        left.addWidget(QLabel("Products"))
        left.addWidget(self.bill_search)
        left.addWidget(self.product_table)
        add_btn = QPushButton("Add to Cart")
        add_btn.clicked.connect(self.add_to_cart)
        left.addWidget(add_btn)

        # MIDDLE – cart
        mid = QVBoxLayout()
        self.cart_table = QTableWidget()
        self.cart_table.setColumnCount(7)
        self.cart_table.setHorizontalHeaderLabels(
            ["Name", "Price", "Qty", "Cost", "Tax%", "Line Total", "Remove"])
        mid.addWidget(QLabel("Shopping Cart"))
        mid.addWidget(self.cart_table)

        # Discount
        disc_lay = QHBoxLayout()
        self.discount_name = QLineEdit()
        self.discount_percent = QDoubleSpinBox()
        self.discount_percent.setMaximum(100)
        disc_lay.addWidget(QLabel("Discount Name"))
        disc_lay.addWidget(self.discount_name)
        disc_lay.addWidget(QLabel("%"))
        disc_lay.addWidget(self.discount_percent)
        mid.addLayout(disc_lay)

        # RIGHT – customer + totals
        right = QFormLayout()
        self.inv_lbl_num = QLabel(str(uuid.uuid4().hex[:8].upper()))
        self.inv_date = QDateEdit(QDate.currentDate())
        self.cust_name = QLineEdit()
        self.cust_phone = QLineEdit()
        self.lbl_subtotal = QLabel("0.00")
        self.lbl_discount = QLabel("0.00")
        self.lbl_tax = QLabel("0.00")
        self.lbl_total = QLabel("0.00")
        self.lbl_profit = QLabel("0.00")
        self.lbl_profit.setStyleSheet("color:green;font-weight:bold")
        right.addRow("Invoice #", self.inv_lbl_num)
        right.addRow("Date", self.inv_date)
        right.addRow("Customer Name", self.cust_name)
        right.addRow("Phone", self.cust_phone)
        right.addRow("Subtotal", self.lbl_subtotal)
        right.addRow("Discount", self.lbl_discount)
        right.addRow("Tax", self.lbl_tax)
        right.addRow("Grand Total", self.lbl_total)
        right.addRow("Profit (hover)", self.lbl_profit)

        # Buttons
        btn_save = QPushButton("Save Invoice")
        btn_pdf = QPushButton("Save PDF")
        btn_print = QPushButton("Print")
        btn_save.clicked.connect(lambda: self.save_invoice(mode="save"))
        btn_pdf.clicked.connect(lambda: self.save_invoice(mode="pdf"))
        btn_print.clicked.connect(lambda: self.save_invoice(mode="print"))
        right.addWidget(btn_save)
        right.addWidget(btn_pdf)
        right.addWidget(btn_print)

        lay.addLayout(left, 2)
        lay.addLayout(mid, 3)
        lay.addLayout(right, 1)
        self.tabs.addTab(w, "Billing")

        self.bill_search.textChanged.connect(self.search_products_bill)
        self.discount_percent.valueChanged.connect(self.refresh_cart)
        self.lbl_total.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.lbl_total and event.type() == event.Enter:
            self.show_profit()
        return super().eventFilter(obj, event)

    def show_profit(self):
        sub = sum(i['price'] * i['qty'] for i in self.cart)
        cost = sum(i['cost_price'] * i['qty'] for i in self.cart)
        disc = sub * self.discount_percent.value() / 100
        profit = sub - disc - cost
        self.lbl_profit.setText(f"{profit:.2f}")

    def search_products_bill(self, txt):
        rows = cur.execute("SELECT * FROM products WHERE name LIKE ? OR barcode LIKE ?",
                           (f"%{txt}%", f"%{txt}%")).fetchall()
        self.product_table.setRowCount(len(rows))
        for idx, r in enumerate(rows):
            for col, val in enumerate([r['id'], r['name'], r['category'], r['price'],
                                       r['cost_price'], r['stock'], r['tax_rate'], r['barcode']]):
                self.product_table.setItem(idx, col, QTableWidgetItem(str(val)))

    def add_to_cart(self):
        idx = self.product_table.currentRow()
        if idx == -1:
            return
        prod_id = int(self.product_table.item(idx, 0).text())
        qty, ok = QInputDialog.getInt(self, "Quantity", "Enter quantity:", 1, 1, 9999)
        if not ok:
            return
        stock = int(self.product_table.item(idx, 5).text())
        if qty > stock:
            QMessageBox.warning(self, "Stock", "Not enough stock.")
            return
        name = self.product_table.item(idx, 1).text()
        price = float(self.product_table.item(idx, 3).text())
        cost_price = float(self.product_table.item(idx, 4).text())
        tax_rate = float(self.product_table.item(idx, 6).text())

        for item in self.cart:
            if item['id'] == prod_id:
                item['qty'] += qty
                break
        else:
            self.cart.append({'id': prod_id, 'name': name, 'price': price,
                              'cost_price': cost_price, 'tax_rate': tax_rate, 'qty': qty})
        self.refresh_cart()

    def refresh_cart(self):
        self.cart_table.setRowCount(len(self.cart))
        subtotal = discount = tax = 0
        for item in self.cart:
            subtotal += item['price'] * item['qty']
            tax += item['price'] * item['qty'] * item['tax_rate'] / 100
        discount = subtotal * self.discount_percent.value() / 100
        total = subtotal - discount + tax

        for row, item in enumerate(self.cart):
            line_total = item['price'] * item['qty']  # NO tax inside
            self.cart_table.setItem(row, 0, QTableWidgetItem(item['name']))
            self.cart_table.setItem(row, 1, QTableWidgetItem(str(item['price'])))
            self.cart_table.setItem(row, 2, QTableWidgetItem(str(item['qty'])))
            self.cart_table.setItem(row, 3, QTableWidgetItem(str(item['cost_price'])))
            self.cart_table.setItem(row, 4, QTableWidgetItem(str(item['tax_rate'])))
            self.cart_table.setItem(row, 5, QTableWidgetItem(f"{line_total:.2f}"))
            rem_btn = QPushButton("Remove")
            rem_btn.clicked.connect(lambda _, r=row: self.remove_from_cart(r))
            self.cart_table.setCellWidget(row, 6, rem_btn)

        self.lbl_subtotal.setText(f"{subtotal:.2f}")
        self.lbl_discount.setText(f"{discount:.2f}")
        self.lbl_tax.setText(f"{tax:.2f}")
        self.lbl_total.setText(f"{total:.2f}")

    def remove_from_cart(self, row):
        del self.cart[row]
        self.refresh_cart()

    def save_invoice(self, mode):
        if not self.cart:
            QMessageBox.warning(self, "Empty", "Cart is empty.")
            return
        inv_num = self.inv_lbl_num.text()
        date = self.inv_date.date().toPyDate().isoformat()
        cust_name = self.cust_name.text()
        cust_phone = self.cust_phone.text()
        cust_id = None
        if cust_phone:
            cur.execute("SELECT id FROM customers WHERE phone=?", (cust_phone,))
            cust = cur.fetchone()
            if cust:
                cust_id = cust['id']
            else:
                cur.execute("INSERT INTO customers(name, phone) VALUES(?,?)",
                            (cust_name or "Walk-in", cust_phone))
                cust_id = cur.lastrowid

        subtotal = sum(i['price'] * i['qty'] for i in self.cart)
        tax = sum(i['price'] * i['qty'] * i['tax_rate'] / 100 for i in self.cart)
        discount = subtotal * self.discount_percent.value() / 100
        total = subtotal - discount + tax

        cur.execute(
            "INSERT INTO invoices(invoice_number, date, customer_id, subtotal, discount_name, discount_percent, tax, total) VALUES(?,?,?,?,?,?,?,?)",
            (inv_num, date, cust_id, subtotal,
             self.discount_name.text(), self.discount_percent.value(), tax, total))
        inv_id = cur.lastrowid

        for item in self.cart:
            cur.execute(
                "INSERT INTO invoice_items(invoice_id, product_id, quantity, price, cost_price, tax_rate) VALUES(?,?,?,?,?,?)",
                (inv_id, item['id'], item['qty'], item['price'], item['cost_price'], item['tax_rate']))
            cur.execute("UPDATE products SET stock=stock-? WHERE id=?", (item['qty'], item['id']))
        conn.commit()

        if cust_id:
            cur.execute("UPDATE customers SET total_purchases=total_purchases+?, last_visit=? WHERE id=?",
                        (total, date, cust_id))
            conn.commit()

        # ask file location
        default_name = f"invoice_{inv_num}.pdf"
        file_path, _ = QFileDialog.getSaveFileName(self, "Save PDF", default_name, "*.pdf")
        if not file_path:
            return

        self.generate_pdf(file_path, inv_id, inv_num, date, cust_name, cust_phone)
        if mode == "print":
            self.print_generated_pdf(file_path)
        elif mode == "save":
            pass  # already saved
        QMessageBox.information(self, "Saved", f"Invoice saved at\n{file_path}")

        # reset billing fields
        self.cart.clear()
        self.refresh_cart()
        self.inv_lbl_num.setText(str(uuid.uuid4().hex[:8].upper()))
        self.discount_name.clear()
        self.discount_percent.setValue(0)
        self.cust_name.clear()
        self.cust_phone.clear()
        self.load_customers()
        self.load_history()

    def generate_pdf(self, path, inv_id, inv_num, date, cust_name, cust_phone):
        store_name = get_setting('store_name')
        store_addr = get_setting('store_address')
        store_email = get_setting('store_email')
        store_phone = get_setting('store_phone')
        items = cur.execute('''
            SELECT p.name, ii.quantity, ii.price, ii.tax_rate
            FROM invoice_items ii
            JOIN products p ON p.id = ii.product_id
            WHERE ii.invoice_id=?''', (inv_id,)).fetchall()
        inv = cur.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone()

        c = canvas.Canvas(path, pagesize=A4)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(100, 800, store_name)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(100, 780, "INVOICE")
        c.setFont("Helvetica", 11)
        c.drawString(100, 760, f"BILL TO: {cust_name}")
        c.drawString(100, 745, f"PHONE: {cust_phone}")
        c.drawString(100, 730, f"ADDRESS: {store_addr.replace('\\n', ', ')}")
        c.drawString(400, 760, f"INVOICE #: {inv_num}")
        c.drawString(400, 745, f"ISSUE DATE: {date}")
        c.drawString(400, 730, f"DUE DATE: {date}")

        y = 700
        c.drawString(100, y, "DESCRIPTION")
        c.drawString(300, y, "QTY")
        c.drawString(360, y, "PRICE")
        c.drawString(420, y, "TOTAL")
        y -= 20
        subtotal = 0
        for it in items:
            line_total = it['price'] * it['quantity']  # NO tax
            subtotal += line_total
            c.drawString(100, y, it['name'])
            c.drawString(300, y, str(it['quantity']))
            c.drawString(360, y, f"{it['price']:.2f}")
            c.drawString(420, y, f"{line_total:.2f}")
            y -= 20
        y -= 10
        c.drawString(100, y, "SUBTOTAL")
        c.drawString(420, y, f"{subtotal:.2f}")
        y -= 20
        if inv['discount_percent'] > 0:
            c.drawString(100, y, f"DISCOUNT ({inv['discount_name']})")
            c.drawString(420, y, f"{subtotal * inv['discount_percent'] / 100:.2f}")
            y -= 20
        c.drawString(100, y, "TAX")
        c.drawString(420, y, f"{inv['tax']:.2f}")
        y -= 20
        c.drawString(100, y, "TOTAL")
        c.drawString(420, y, f"{inv['total']:.2f}")
        y -= 40
        c.drawString(100, y, f"EMAIL: {store_email}")
        c.drawString(100, y - 20, f"PHONE: {store_phone}")
        c.save()

    def print_generated_pdf(self, path):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        dlg = QPrintDialog(printer, self)
        if dlg.exec_() == QDialog.Accepted:
            pass  # OS dialog

    # ------------------------------------------------------
    # PRODUCTS TAB
    def init_product_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.prod_table = QTableWidget()
        self.prod_table.setColumnCount(8)
        self.prod_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Category", "Price", "Cost", "Stock", "Tax%", "Barcode"])
        lay.addWidget(self.prod_table)
        btn_add = QPushButton("Add Product")
        btn_add.clicked.connect(self.add_product_dialog)
        btn_del = QPushButton("Delete Selected")
        btn_del.clicked.connect(self.delete_product)
        btn_export = QPushButton("Export Data → PDF")
        btn_export.clicked.connect(self.export_products_pdf)
        lay.addWidget(btn_add)
        lay.addWidget(btn_del)
        lay.addWidget(btn_export)
        self.tabs.addTab(w, "Products")
        self.load_products()

    def load_products(self):
        rows = cur.execute("SELECT * FROM products").fetchall()
        self.prod_table.setRowCount(len(rows))
        for idx, r in enumerate(rows):
            for col, val in enumerate([r['id'], r['name'], r['category'], r['price'],
                                       r['cost_price'], r['stock'], r['tax_rate'], r['barcode']]):
                self.prod_table.setItem(idx, col, QTableWidgetItem(str(val)))

    def add_product_dialog(self):
        d = QDialog(self)
        d.setWindowTitle("Add Product")
        f = QFormLayout(d)
        name = QLineEdit()
        cat = QLineEdit()
        price = QDoubleSpinBox();
        price.setMaximum(999999)
        cost_price = QDoubleSpinBox();
        cost_price.setMaximum(999999)
        stock = QSpinBox();
        stock.setMaximum(999999)
        tax = QDoubleSpinBox();
        tax.setValue(18);
        tax.setMaximum(100)
        barcode = QLineEdit()
        desc = QLineEdit()
        for w, l in [(name, "Name"), (cat, "Category"), (price, "Price"),
                     (cost_price, "Cost Price"), (stock, "Stock"),
                     (tax, "Tax %"), (barcode, "Barcode"), (desc, "Description")]:
            f.addRow(l, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        f.addWidget(bb)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        if d.exec_() == QDialog.Accepted:
            cur.execute(
                "INSERT INTO products(name,category,price,cost_price,stock,tax_rate,barcode,description) VALUES(?,?,?,?,?,?,?,?)",
                (name.text(), cat.text(), price.value(), cost_price.value(),
                 stock.value(), tax.value(), barcode.text(), desc.text()))
            conn.commit()
            self.load_products()

    def delete_product(self):
        idx = self.prod_table.currentRow()
        if idx == -1:
            return
        prod_id = int(self.prod_table.item(idx, 0).text())
        name = self.prod_table.item(idx, 1).text()
        reply = QMessageBox.question(self, "Delete", f"Delete {name}?")
        if reply == QMessageBox.Yes:
            cur.execute("DELETE FROM products WHERE id=?", (prod_id,))
            conn.commit()
            self.load_products()

    def export_products_pdf(self):
        rows = cur.execute("SELECT * FROM products").fetchall()
        if not rows:
            QMessageBox.information(self, "Export", "No products to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Products PDF", "products.pdf", "*.pdf")
        if not path:
            return
        doc = SimpleDocTemplate(path, pagesize=A4)
        data = [["ID", "Name", "Category", "Price", "Cost", "Stock", "Tax%", "Barcode"]]
        for r in rows:
            data.append([str(r[k]) for k in ['id', 'name', 'category', 'price', 'cost_price',
                                             'stock', 'tax_rate', 'barcode']])
        t = Table(data)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#7b2cbf")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#f3e5f5")),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor("#7b2cbf"))
        ]))
        doc.build([t])
        QMessageBox.information(self, "Export", "Products exported to PDF.")

    # ------------------------------------------------------
    # CUSTOMER TAB
    def init_customer_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.cust_table = QTableWidget()
        self.cust_table.setColumnCount(6)
        self.cust_table.setHorizontalHeaderLabels(["ID", "Name", "Phone", "Email", "Purchases", "Actions"])
        lay.addWidget(self.cust_table)
        btn_add = QPushButton("Add Customer")
        btn_add.clicked.connect(self.add_customer_dialog)
        lay.addWidget(btn_add)
        self.tabs.addTab(w, "Customers")
        self.load_customers()

    def load_customers(self):
        rows = cur.execute("SELECT * FROM customers").fetchall()
        self.cust_table.setRowCount(len(rows))
        for idx, r in enumerate(rows):
            for col, val in enumerate([r['id'], r['name'], r['phone'], r['email'], r['total_purchases']]):
                self.cust_table.setItem(idx, col, QTableWidgetItem(str(val)))
            btn_full = QPushButton("Full Info")
            btn_full.clicked.connect(lambda _, cid=r['id']: self.show_customer_bills(cid))
            self.cust_table.setCellWidget(idx, 5, btn_full)

    def add_customer_dialog(self):
        d = QDialog(self)
        d.setWindowTitle("Add Customer")
        f = QFormLayout(d)
        name = QLineEdit()
        phone = QLineEdit()
        email = QLineEdit()
        addr = QLineEdit()
        for w, l in [(name, "Name"), (phone, "Phone"), (email, "Email"), (addr, "Address")]:
            f.addRow(l, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        f.addWidget(bb)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        if d.exec_() == QDialog.Accepted:
            cur.execute("INSERT INTO customers(name,phone,email,address) VALUES(?,?,?,?)",
                        (name.text(), phone.text(), email.text(), addr.text()))
            conn.commit()
            self.load_customers()

    def show_customer_bills(self, cid):
        invoices = cur.execute("SELECT * FROM invoices WHERE customer_id=?", (cid,)).fetchall()
        if not invoices:
            QMessageBox.information(self, "No Bills", "No invoices for this customer.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Customer Bills")
        dlg.resize(800, 500)
        table = QTableWidget()
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(["Invoice #", "Date", "Subtotal", "Discount", "Tax", "Total"])
        table.setRowCount(len(invoices))
        for row, inv in enumerate(invoices):
            for col, key in enumerate(['invoice_number', 'date', 'subtotal', 'discount_name', 'tax', 'total']):
                table.setItem(row, col, QTableWidgetItem(str(inv[key])))
        view_btn = QPushButton("View Bill PDF")
        view_btn.clicked.connect(lambda: self.save_customer_pdf(invoices[table.currentRow()]))
        lay = QVBoxLayout(dlg)
        lay.addWidget(table)
        lay.addWidget(view_btn)
        dlg.exec_()

    def save_customer_pdf(self, inv):
        store_name = get_setting('store_name')
        store_addr = get_setting('store_address')
        store_email = get_setting('store_email')
        store_phone = get_setting('store_phone')

        items = cur.execute('''
            SELECT p.name, ii.quantity, ii.price, ii.tax_rate
            FROM invoice_items ii
            JOIN products p ON p.id = ii.product_id
            WHERE ii.invoice_id=?''', (inv['id'],)).fetchall()
        cust = cur.execute("SELECT name, phone FROM customers WHERE id=?", (inv['customer_id'],)).fetchone()
        cust_name = cust['name'] if cust else "Walk-in"
        cust_phone = cust['phone'] if cust else ""

        path, _ = QFileDialog.getSaveFileName(self, "Save Customer Bill", f"{inv['invoice_number']}.pdf", "*.pdf")
        if not path:
            return
        self.generate_pdf(path, inv['id'], inv['invoice_number'], inv['date'], cust_name, cust_phone)
        QMessageBox.information(self, "PDF", "Customer bill saved.")

    # ----------------------------------------------------------
    # HISTORY TAB
    def init_history_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        search_lay = QHBoxLayout()
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search customer / invoice")
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self.search_history)
        search_lay.addWidget(self.history_search)
        search_lay.addWidget(search_btn)
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels(
            ["Invoice #", "Date", "Customer", "Subtotal", "Discount", "Tax", "Total"])
        lay.addLayout(search_lay)
        lay.addWidget(self.history_table)
        view_btn = QPushButton("View Bill PDF")
        view_btn.clicked.connect(lambda: self.open_history_pdf())
        lay.addWidget(view_btn)
        self.tabs.addTab(w, "History")
        self.load_history()

    def load_history(self):
        rows = cur.execute('''
            SELECT i.*, c.name as customer
            FROM invoices i
            JOIN customers c ON c.id = i.customer_id
            ORDER BY i.date DESC
        ''').fetchall()
        self.populate_history(rows)

    def search_history(self):
        txt = self.history_search.text()
        sql = '''
            SELECT i.*, c.name as customer
            FROM invoices i
            JOIN customers c ON c.id = i.customer_id
            WHERE c.name LIKE ? OR i.invoice_number LIKE ?
            ORDER BY i.date DESC
        '''
        rows = cur.execute(sql, (f"%{txt}%", f"%{txt}%")).fetchall()
        self.populate_history(rows)

    def populate_history(self, rows):
        self.history_table.setRowCount(len(rows))
        for idx, r in enumerate(rows):
            for col, key in enumerate(
                    ['invoice_number', 'date', 'customer', 'subtotal', 'discount_name', 'tax', 'total']):
                self.history_table.setItem(idx, col, QTableWidgetItem(str(r[key])))

    def open_history_pdf(self):
        idx = self.history_table.currentRow()
        if idx == -1:
            return
        inv_num = self.history_table.item(idx, 0).text()
        inv = cur.execute("SELECT * FROM invoices WHERE invoice_number=?", (inv_num,)).fetchone()
        cust = cur.execute("SELECT name, phone FROM customers WHERE id=?", (inv['customer_id'],)).fetchone()
        cust_name = cust['name'] if cust else "Walk-in"
        cust_phone = cust['phone'] if cust else ""
        path, _ = QFileDialog.getSaveFileName(self, "Save History Bill", f"{inv_num}.pdf", "*.pdf")
        if not path:
            return
        self.generate_pdf(path, inv['id'], inv_num, inv['date'], cust_name, cust_phone)
        QMessageBox.information(self, "PDF", "History bill saved.")

    # ----------------------------------------------------------
    # REPORT TAB
    def init_report_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.report_table = QTableWidget()
        self.report_table.setColumnCount(5)
        self.report_table.setHorizontalHeaderLabels(["Metric", "Today", "This Month", "Total", "Discount Today"])
        lay.addWidget(self.report_table)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self.refresh_report)
        lay.addWidget(btn_refresh)
        self.tabs.addTab(w, "Reports")
        self.refresh_report()

    def refresh_report(self):
        today = datetime.date.today().isoformat()
        this_month = today[:7]
        today_sales = cur.execute("SELECT SUM(total) FROM invoices WHERE date=?", (today,)).fetchone()[0] or 0
        month_sales = cur.execute("SELECT SUM(total) FROM invoices WHERE date LIKE ?", (this_month + "%",)).fetchone()[
                          0] or 0
        total_customers = cur.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        low_stock = cur.execute("SELECT COUNT(*) FROM products WHERE stock < 10").fetchone()[0]
        today_discount = \
        cur.execute("SELECT SUM(subtotal * discount_percent / 100) FROM invoices WHERE date=?", (today,)).fetchone()[
            0] or 0
        self.report_table.setRowCount(4)
        data = [
            ("Sales (₹)", f"{today_sales:.2f}", f"{month_sales:.2f}", "", f"{today_discount:.2f}"),
            ("Customers", "", "", str(total_customers), ""),
            ("Low Stock Items", "", "", str(low_stock), ""),
        ]
        for row, (metric, today_val, month_val, total_val, discount_val) in enumerate(data):
            for col, val in enumerate([metric, today_val, month_val, total_val, discount_val]):
                self.report_table.setItem(row, col, QTableWidgetItem(str(val)))

    # ----------------------------------------------------------
    # SETTINGS TAB
    def init_settings_tab(self):
        w = QWidget()
        lay = QFormLayout(w)
        self.store_name = QLineEdit(get_setting('store_name'))
        self.store_addr = QTextEdit(get_setting('store_address'))
        self.store_email = QLineEdit(get_setting('store_email'))
        self.store_phone = QLineEdit(get_setting('store_phone'))

        self.dark_toggle = QCheckBox("Dark Mode")
        self.dark_toggle.setChecked(self.dark_mode)
        self.dark_toggle.toggled.connect(self.toggle_dark_mode)

        lay.addRow("Store Name", self.store_name)
        lay.addRow("Store Address", self.store_addr)
        lay.addRow("Store Email", self.store_email)
        lay.addRow("Store Phone", self.store_phone)
        lay.addWidget(self.dark_toggle)

        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        lay.addWidget(save_btn)
        self.tabs.addTab(w, "Settings")

    def toggle_dark_mode(self, checked):
        self.dark_mode = checked
        self.apply_theme()

    def save_settings(self):
        set_setting('store_name', self.store_name.text())
        set_setting('store_address', self.store_addr.toPlainText())
        set_setting('store_email', self.store_email.text())
        set_setting('store_phone', self.store_phone.text())
        set_setting('dark_mode', str(int(self.dark_mode)))
        self.apply_theme()


# ---------- ENTRY ----------
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setFont(QFont("Arial", 9))
    win = BillingApp()
    win.show()
    sys.exit(app.exec_())
