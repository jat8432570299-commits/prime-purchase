const env = require('../config/env');
const orderService = require('./orderService');
const imbService = require('./imbService');
const deliveryService = require('./deliveryService');

let running = false;

async function pollOnce() {
  if (running) return;
  running = true;

  try {
    const orders = await orderService.findPendingPaymentOrders();

    for (const order of orders) {
      try {
        const status = await imbService.checkPaymentStatus(order.order_id);
        if (status.event.paid) {
          await deliveryService.deliverPaidOrder(order, status.event.paymentId);
          console.log(`Delivered paid order via polling: ${order.order_id}`);
        }
      } catch (error) {
        console.error(`Payment poll failed for ${order.order_id}:`, error.message);
      }
    }
  } finally {
    running = false;
  }
}

function startPaymentPoller() {
  if (!env.paymentPollEnabled) return;

  const intervalMs = Math.max(env.paymentPollIntervalSeconds, 15) * 1000;
  setInterval(pollOnce, intervalMs);
  setTimeout(pollOnce, 5000);
  console.log(`Payment poller enabled every ${intervalMs / 1000}s`);
}

module.exports = {
  startPaymentPoller,
  pollOnce
};
