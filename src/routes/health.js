const express = require('express');

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
    time: new Date().toISOString()
  });
});

module.exports = router;
