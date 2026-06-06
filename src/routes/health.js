const express = require('express');

const router = express.Router();

router.get('/', (req, res) => {
  res.json({
    ok: true,
    service: 'whatsapp-inventory-automation',
    time: new Date().toISOString()
  });
});

module.exports = router;

