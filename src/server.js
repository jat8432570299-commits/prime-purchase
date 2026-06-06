const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const morgan = require('morgan');
const env = require('./config/env');
const webhookRoutes = require('./routes/webhooks');
const healthRoutes = require('./routes/health');
const paymentPoller = require('./services/paymentPoller');

const app = express();

app.use(helmet());
app.use(cors());
app.use(express.json({ limit: '2mb' }));
app.use(express.urlencoded({ extended: true }));
app.use(morgan(env.nodeEnv === 'production' ? 'combined' : 'dev'));

app.use('/health', healthRoutes);
app.use('/webhook', webhookRoutes);

app.get('/', (req, res) => {
  res.json({
    ok: true,
    routes: ['/health', '/webhook/whatsapp', '/webhook/imb-payment']
  });
});

app.get('/mock-pay/:orderId', (req, res) => {
  res.type('html').send(`
    <!doctype html>
    <html>
      <head><title>Mock Payment</title></head>
      <body style="font-family: Arial, sans-serif; padding: 24px;">
        <h1>Mock Payment</h1>
        <p>Order ID: <strong>${req.params.orderId}</strong></p>
        <p>To mark this paid, POST this JSON to <code>/webhook/imb-payment</code>:</p>
        <pre>{
  "order_id": "${req.params.orderId}",
  "payment_id": "MOCK-${Date.now()}",
  "status": "success"
}</pre>
      </body>
    </html>
  `);
});

app.use((req, res) => {
  res.status(404).json({ ok: false, error: 'Route not found' });
});

app.use((error, req, res, next) => {
  console.error(error);
  res.status(500).json({
    ok: false,
    error: env.nodeEnv === 'production' ? 'Internal server error' : error.message
  });
});

app.listen(env.port, () => {
  console.log(`WhatsApp inventory server running on port ${env.port}`);
  paymentPoller.startPaymentPoller();
});
