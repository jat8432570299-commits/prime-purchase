const imbService = require('../src/services/imbService');

async function main() {
  const result = await imbService.getSmsquickerCredits();
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(error.response ? error.response.data : error);
  process.exit(1);
});

