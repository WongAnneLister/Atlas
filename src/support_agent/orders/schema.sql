DROP TABLE IF EXISTS refund_request_items;
DROP TABLE IF EXISTS refund_requests;
DROP TABLE IF EXISTS shipments;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS seed_metadata;

CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE CHECK (email LIKE '%@example.com')
);
CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'paid', 'shipped', 'in_transit', 'delivered', 'cancelled',
        'refunded', 'partially_refunded'
    )),
    order_date TEXT NOT NULL,
    delivered_at TEXT,
    currency TEXT NOT NULL,
    total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
    paid_with_coupon INTEGER NOT NULL CHECK (paid_with_coupon IN (0, 1)),
    coupon_code TEXT,
    CHECK (paid_with_coupon = (coupon_code IS NOT NULL)),
    UNIQUE (order_id, customer_id)
);
CREATE INDEX orders_customer_date ON orders(customer_id, order_date DESC, order_id DESC);
CREATE TABLE order_items (
    item_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    product_id TEXT NOT NULL,
    model TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    final_sale INTEGER NOT NULL CHECK (final_sale IN (0, 1)),
    refunded_quantity INTEGER NOT NULL CHECK (
        refunded_quantity >= 0 AND refunded_quantity <= quantity
    ),
    UNIQUE (item_id, order_id)
);
CREATE INDEX items_order ON order_items(order_id);
CREATE TABLE shipments (
    order_id TEXT PRIMARY KEY REFERENCES orders(order_id),
    carrier TEXT NOT NULL,
    tracking_number TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('shipped', 'in_transit', 'delayed', 'delivered')),
    shipped_at TEXT NOT NULL,
    expected_delivery TEXT NOT NULL,
    last_event_at TEXT NOT NULL,
    last_event TEXT NOT NULL
);
CREATE TABLE refund_requests (
    request_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    idempotency_key TEXT,
    status TEXT NOT NULL CHECK (status = 'pending_review'),
    created_at TEXT NOT NULL,
    FOREIGN KEY (order_id, customer_id) REFERENCES orders(order_id, customer_id),
    UNIQUE (request_id, order_id),
    CONSTRAINT refund_requests_idempotency_key UNIQUE (idempotency_key)
);
CREATE TABLE refund_request_items (
    request_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    PRIMARY KEY (request_id, item_id),
    FOREIGN KEY (request_id, order_id) REFERENCES refund_requests(request_id, order_id),
    FOREIGN KEY (item_id, order_id) REFERENCES order_items(item_id, order_id)
);
CREATE TABLE seed_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
