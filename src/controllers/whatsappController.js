const env = require('../config/env');
const inventoryService = require('../services/inventoryService');
const orderService = require('../services/orderService');
const imbService = require('../services/imbService');
const { parseIncomingMessage, parseBuy, parseAdd } = require('../utils/parser');
const { normalizePhone, isAdmin } = require('../utils/phone');
const { orderSummary } = require('../utils/formatters');

async function handleBuy({ qty, mobile, customerName }) {
  const stock = await inventoryService.getStockCount();
  if (stock < qty) {
    await imbService.sendWhatsAppMessage(
      mobile,
      `Sorry, only ${stock} account(s) are available right now.`
    );
    return;
  }

  const order = await orderService.createPendingOrder({
    customerName,
    mobile,
    qty
  });

  const payment = await imbService.createPaymentLink(order);
  const paymentText = payment.paymentLink
    ? `Pay here: ${payment.paymentLink}`
    : 'Payment link could not be generated. Admin will contact you shortly.';

  await imbService.sendWhatsAppMessage(
    mobile,
    [
      `Order created: ${order.order_id}`,
      `Qty: ${qty}`,
      `Amount: ${order.amount}`,
      paymentText
    ].join('\n')
  );
}

async function handleAdmin(text, mobile) {
  if (/^STOCK$/i.test(text)) {
    const stock = await inventoryService.getStockCount();
    await imbService.sendWhatsAppMessage(mobile, `Available stock: ${stock}`);
    return;
  }

  if (/^ORDERS$/i.test(text)) {
    const orders = await orderService.findRecentOrders(10);
    const message = orders.length
      ? orders.map(orderSummary).join('\n\n')
      : 'No orders found.';
    await imbService.sendWhatsAppMessage(mobile, message);
    return;
  }

  const add = parseAdd(text);
  if (add) {
    if (!add.accounts.length) {
      await imbService.sendWhatsAppMessage(mobile, 'Use: ADD username password');
      return;
    }
    const count = await inventoryService.addAccounts(add.accounts);
    await imbService.sendWhatsAppMessage(mobile, `Added ${count} account(s) with default password from Settings sheet.`);
    return;
  }

  await imbService.sendWhatsAppMessage(mobile, 'Admin commands: STOCK, ORDERS, ADD then email list');
}

async function receiveWhatsApp(req, res, next) {
  try {
    const incoming = parseIncomingMessage(req.body);
    const mobile = normalizePhone(incoming.mobile);
    const text = incoming.text;

    if (!mobile || !text) {
      return res.status(200).json({ ok: true, ignored: true });
    }

    const adminNumbers = env.adminNumbers.length ? env.adminNumbers : ['918432570299'];
    if (isAdmin(mobile, adminNumbers) && (/^(STOCK|ORDERS|ADD\b)/i.test(text))) {
      await handleAdmin(text, mobile);
      return res.json({ ok: true });
    }

    const buy = parseBuy(text);
    if (buy) {
      await handleBuy({
        qty: buy.qty,
        mobile,
        customerName: incoming.customerName
      });
      return res.json({ ok: true });
    }

    await imbService.sendWhatsAppMessage(
      mobile,
      ['Send BUY quantity to place order.', 'Example: BUY 5'].join('\n')
    );
    return res.json({ ok: true });
  } catch (error) {
    return next(error);
  }
}

function verifyWebhook(req, res) {
  const token = req.query.token || req.query['hub.verify_token'];
  const challenge = req.query.challenge || req.query['hub.challenge'] || 'ok';

  if (token === env.webhookVerifyToken) {
    return res.status(200).send(challenge);
  }

  return res.status(403).send('Invalid verify token');
}

module.exports = {
  receiveWhatsApp,
  verifyWebhook
};
