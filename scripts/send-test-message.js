const imbService = require('../src/services/imbService');

async function main() {
  const to = process.argv[2];
  const message = process.argv.slice(3).join(' ') || 'Test message from inventory automation';

  if (!to) {
    throw new Error('Usage: node scripts/send-test-message.js 918432570299 "Hello"');
  }

  const result = await imbService.sendWhatsAppMessage(to, message);
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(error.response ? error.response.data : error);
  process.exit(1);
});

