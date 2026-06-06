const { v4: uuid } = require('uuid');
const env = require('../config/env');
const sheets = require('./sheetsService');

const ORDER_HEADERS = [
  'order_id',
  'customer_name',
  'mobile',
  'qty',
  'amount',
  'payment_status',
  'delivery_status',
  'payment_provider',
  'payment_id',
  'created_at',
  'delivered_at',
  'credentials'
];

async function listOrders() {
  const data = await sheets.readSheet(env.ordersSheetName);
  return {
    headers: data.headers.length ? data.headers : ORDER_HEADERS,
    rows: data.rows
  };
}

async function createPendingOrder({ customerName, mobile, qty }) {
  await sheets.ensureHeaders(env.ordersSheetName, ORDER_HEADERS);
  const order = {
    order_id: `ORD-${Date.now()}-${uuid().slice(0, 8)}`,
    customer_name: customerName || '',
    mobile,
    qty: String(qty),
    amount: String(qty * env.accountPrice),
    payment_status: 'pending',
    delivery_status: 'pending',
    payment_provider: 'imb',
    payment_id: '',
    created_at: new Date().toISOString(),
    delivered_at: '',
    credentials: ''
  };

  await sheets.appendRows(env.ordersSheetName, [sheets.objectToRow(ORDER_HEADERS, order)]);
  return order;
}

async function findOrder(orderId) {
  const { rows } = await listOrders();
  return rows.find((row) => row.order_id === orderId);
}

async function findRecentOrders(limit = 10) {
  const { rows } = await listOrders();
  return rows.slice(-limit).reverse();
}

async function updateOrder(order) {
  const { headers } = await listOrders();
  await sheets.updateRow(env.ordersSheetName, order._rowNumber, sheets.objectToRow(headers, order));
}

async function markPaid(order, paymentId) {
  const updated = {
    ...order,
    payment_status: 'paid',
    payment_id: paymentId || order.payment_id || ''
  };
  await updateOrder(updated);
  return updated;
}

async function markDelivered(order, credentials) {
  const updated = {
    ...order,
    delivery_status: 'delivered',
    delivered_at: new Date().toISOString(),
    credentials: credentials || order.credentials || ''
  };
  await updateOrder(updated);
  return updated;
}

async function ensureOrderHeaders() {
  await sheets.ensureHeaders(env.ordersSheetName, ORDER_HEADERS);
}

module.exports = {
  ORDER_HEADERS,
  ensureOrderHeaders,
  createPendingOrder,
  findOrder,
  findRecentOrders,
  markPaid,
  markDelivered
};

