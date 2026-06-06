const orderService = require('../services/orderService');
const deliveryService = require('../services/deliveryService');
const imbService = require('../services/imbService');

async function receiveImbPayment(req, res, next) {
  try {
    const event = imbService.extractPaymentEvent(req.body);

    if (!event.orderId) {
      return res.status(400).json({ ok: false, error: 'Missing order id' });
    }

    if (!event.paid) {
      return res.json({ ok: true, ignored: true, status: event.status });
    }

    const order = await orderService.findOrder(event.orderId);
    if (!order) {
      return res.status(404).json({ ok: false, error: 'Order not found' });
    }

    const result = await deliveryService.deliverPaidOrder(order, event.paymentId);
    return res.json({
      ok: true,
      delivered: !result.alreadyDelivered,
      alreadyDelivered: result.alreadyDelivered
    });
  } catch (error) {
    return next(error);
  }
}

module.exports = {
  receiveImbPayment
};

