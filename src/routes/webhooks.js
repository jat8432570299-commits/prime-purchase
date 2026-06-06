const express = require('express');
const whatsappController = require('../controllers/whatsappController');
const paymentController = require('../controllers/paymentController');

const router = express.Router();

router.get('/whatsapp', whatsappController.verifyWebhook);
router.post('/whatsapp', whatsappController.receiveWhatsApp);
router.post('/imb-payment', paymentController.receiveImbPayment);

module.exports = router;

