const env = require('../config/env');
const sheets = require('./sheetsService');

const WEBHOOK_LOG_HEADERS = ['created_at', 'source', 'mobile', 'message', 'raw'];

async function ensureWebhookLogHeaders() {
  await sheets.ensureHeaders(env.webhookLogsSheetName, WEBHOOK_LOG_HEADERS);
}

async function logIncoming({ source, mobile, message, raw }) {
  await ensureWebhookLogHeaders();
  await sheets.appendRows(env.webhookLogsSheetName, [[
    new Date().toISOString(),
    source || 'whatsapp',
    mobile || '',
    message || '',
    JSON.stringify(raw || {})
  ]]);
}

module.exports = {
  WEBHOOK_LOG_HEADERS,
  ensureWebhookLogHeaders,
  logIncoming
};
