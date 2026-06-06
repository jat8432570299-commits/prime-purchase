const express = require('express');
const env = require('../config/env');

const router = express.Router();

router.get('/', (req, res) => {
  res.json({
    ok: true,
    service: 'whatsapp-inventory-automation',
    features: {
      emailOnlyAdd: true,
      paymentPolling: true,
      openAdminCommands: true
    },
    config: {
      googleSheetId: env.googleSheetId,
      inventorySheetName: env.inventorySheetName,
      ordersSheetName: env.ordersSheetName,
      settingsSheetName: env.settingsSheetName
    },
    time: new Date().toISOString()
  });
});

module.exports = router;
