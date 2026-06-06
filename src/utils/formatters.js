function formatCredentials(accounts) {
  return accounts
    .map((account, index) => `${index + 1}. ${account.username} / ${account.password}`)
    .join('\n');
}

function orderSummary(order) {
  return [
    `Order ID: ${order.order_id}`,
    `Qty: ${order.qty}`,
    `Amount: ${order.amount}`,
    `Payment: ${order.payment_status}`,
    `Delivery: ${order.delivery_status}`
  ].join('\n');
}

module.exports = {
  formatCredentials,
  orderSummary
};

