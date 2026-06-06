const inventoryService = require('../src/services/inventoryService');
const orderService = require('../src/services/orderService');
const settingsService = require('../src/services/settingsService');

async function main() {
  await inventoryService.ensureInventoryHeaders();
  await orderService.ensureOrderHeaders();
  await settingsService.ensureSettings();
  console.log('Sheet headers are ready.');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
