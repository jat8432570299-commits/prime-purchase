const inventoryService = require('../src/services/inventoryService');
const orderService = require('../src/services/orderService');
const deliveryService = require('../src/services/deliveryService');

async function main() {
  const suffix = Date.now();
  await inventoryService.addAccounts([
    {
      username: `test_user_${suffix}`,
      password: `test_pass_${suffix}`
    }
  ]);

  const order = await orderService.createPendingOrder({
    customerName: 'Smoke Test',
    mobile: '918432570299',
    qty: 1
  });

  const result = await deliveryService.deliverPaidOrder(order, `MOCKPAY-${suffix}`);
  console.log(JSON.stringify({
    ok: true,
    order_id: result.order.order_id,
    delivery_status: result.order.delivery_status,
    accounts_delivered: result.accounts ? result.accounts.length : 0
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

