const env = require('../config/env');

const checks = [
  ['Google Sheet ID', env.googleSheetId],
  ['Inventory sheet', env.inventorySheetName],
  ['Orders sheet', env.ordersSheetName],
  ['Admin numbers', env.adminNumbers.join(', ')],
  ['IMB API base URL', env.imbApiBaseUrl],
  ['IMB mock mode', env.imbMockMode ? 'enabled' : 'disabled'],
  ['WhatsApp mock mode', env.imbWhatsappMockMode ? 'enabled' : 'disabled'],
  ['Payment mock mode', env.imbPaymentMockMode ? 'enabled' : 'disabled'],
  ['WhatsApp provider', env.whatsappProvider],
  ['SMSQuicker base URL', env.smsquickerApiBaseUrl],
  ['SMSQuicker send path', env.smsquickerSendPath],
  ['SMSQuicker secret', env.smsquickerApiSecret ? 'set' : 'MISSING'],
  ['SMSQuicker WhatsApp account', env.smsquickerWhatsappAccount ? 'set' : 'MISSING'],
  ['WhatsApp send path', env.imbWhatsappSendPath],
  ['Payment create path', env.imbPaymentCreatePath],
  ['Payment status path', env.imbPaymentStatusPath]
];

for (const [label, value] of checks) {
  console.log(`${label}: ${value || 'MISSING'}`);
}

console.log('Config loaded successfully.');
