require('dotenv').config();

function required(name) {
  const value = process.env[name];
  if (!value || value.trim() === '') {
    throw new Error(`Missing required env: ${name}`);
  }
  return value.trim();
}

function optional(name, fallback = '') {
  const value = process.env[name];
  return value && value.trim() !== '' ? value.trim() : fallback;
}

function numberValue(name, fallback) {
  const raw = optional(name, String(fallback));
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    throw new Error(`Env ${name} must be a number`);
  }
  return parsed;
}

function csv(name) {
  return optional(name)
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function booleanValue(name, fallback = false) {
  const value = optional(name, String(fallback));
  return ['1', 'true', 'yes', 'on'].includes(value.toLowerCase());
}

const env = {
  port: numberValue('PORT', 3000),
  nodeEnv: optional('NODE_ENV', 'development'),
  publicBaseUrl: optional('PUBLIC_BASE_URL'),
  googleSheetId: required('GOOGLE_SHEET_ID'),
  googleServiceAccountFile: optional('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials/google-service-account.json'),
  googleServiceAccountJson: optional('GOOGLE_SERVICE_ACCOUNT_JSON'),
  inventorySheetName: optional('INVENTORY_SHEET_NAME', 'Inventory'),
  ordersSheetName: optional('ORDERS_SHEET_NAME', 'Orders'),
  settingsSheetName: optional('SETTINGS_SHEET_NAME', 'Settings'),
  defaultAccountPassword: optional('DEFAULT_ACCOUNT_PASSWORD', 'change_this_password'),
  adminNumbers: csv('ADMIN_NUMBERS').length ? csv('ADMIN_NUMBERS') : csv('ADMIN_TELEGRAM_IDS'),
  accountPrice: numberValue('ACCOUNT_PRICE', 100),
  imbApiBaseUrl: required('IMB_API_BASE_URL').replace(/\/+$/, ''),
  imbApiToken: required('IMB_API_TOKEN'),
  imbWebhookSecret: optional('IMB_WEBHOOK_SECRET'),
  imbMockMode: booleanValue('IMB_MOCK_MODE', false),
  imbWhatsappMockMode: booleanValue('IMB_WHATSAPP_MOCK_MODE', booleanValue('IMB_MOCK_MODE', false)),
  imbPaymentMockMode: booleanValue('IMB_PAYMENT_MOCK_MODE', booleanValue('IMB_MOCK_MODE', false)),
  imbWhatsappSendPath: optional('IMB_WHATSAPP_SEND_PATH', '/api/send-message'),
  imbPaymentCreatePath: optional('IMB_PAYMENT_CREATE_PATH', '/api/create-order'),
  imbPaymentStatusPath: optional('IMB_PAYMENT_STATUS_PATH', '/api/check-order-status'),
  paymentPollEnabled: booleanValue('PAYMENT_POLL_ENABLED', true),
  paymentPollIntervalSeconds: numberValue('PAYMENT_POLL_INTERVAL_SECONDS', 60),
  imbAuthHeader: optional('IMB_AUTH_HEADER', ''),
  imbAuthScheme: optional('IMB_AUTH_SCHEME', ''),
  whatsappProvider: optional('WHATSAPP_PROVIDER', 'smsquicker').toLowerCase(),
  smsquickerApiBaseUrl: optional('SMSQUICKER_API_BASE_URL', 'https://smsquicker.com').replace(/\/+$/, ''),
  smsquickerApiSecret: optional('SMSQUICKER_API_SECRET'),
  smsquickerSendPath: optional('SMSQUICKER_SEND_PATH', '/api/send/whatsapp'),
  smsquickerPhoneField: optional('SMSQUICKER_PHONE_FIELD', 'phone'),
  smsquickerMessageField: optional('SMSQUICKER_MESSAGE_FIELD', 'message'),
  smsquickerWhatsappAccount: optional('SMSQUICKER_WHATSAPP_ACCOUNT'),
  smsquickerType: optional('SMSQUICKER_TYPE', 'text'),
  smsquickerMode: optional('SMSQUICKER_MODE', 'devices'),
  smsquickerCampaign: optional('SMSQUICKER_CAMPAIGN', 'WhatsApp Inventory'),
  smsquickerSim: optional('SMSQUICKER_SIM', '1'),
  webhookVerifyToken: optional('WEBHOOK_VERIFY_TOKEN', 'verify-token')
};

module.exports = env;
