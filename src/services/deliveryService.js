const inventoryService = require('./inventoryService');
const orderService = require('./orderService');
const imbService = require('./imbService');
const { formatCredentials } = require('../utils/formatters');
const { withLock } = require('../utils/lock');

async function deliverPaidOrder(order, paymentId) {
  return withLock('inventory-delivery', async () => {
    const freshOrder = await orderService.findOrder(order.order_id);
    if (!freshOrder) {
      throw new Error(`Order not found: ${order.order_id}`);
    }

    if (freshOrder.delivery_status === 'delivered') {
      return { alreadyDelivered: true, order: freshOrder };
    }

    const paidOrder = freshOrder.payment_status === 'paid'
      ? freshOrder
      : await orderService.markPaid(freshOrder, paymentId);

    const qty = Number(paidOrder.qty);
    const available = await inventoryService.getAvailableAccounts(qty);
    if (available.length < qty) {
      await imbService.sendWhatsAppMessage(
        paidOrder.mobile,
        `Payment received for ${paidOrder.order_id}, but stock is currently low. Admin has been notified.`
      );
      throw new Error(`Insufficient stock for paid order ${paidOrder.order_id}`);
    }

    const soldAccounts = await inventoryService.markSold(
      available,
      paidOrder.customer_name,
      paidOrder.mobile
    );
    const credentialsText = formatCredentials(soldAccounts);
    const message = [
      `Payment successful. Your order ${paidOrder.order_id} is delivered.`,
      '',
      credentialsText
    ].join('\n');

    await imbService.sendWhatsAppMessage(paidOrder.mobile, message);
    const deliveredOrder = await orderService.markDelivered(paidOrder, credentialsText);

    return {
      alreadyDelivered: false,
      order: deliveredOrder,
      accounts: soldAccounts
    };
  });
}

module.exports = {
  deliverPaidOrder
};

