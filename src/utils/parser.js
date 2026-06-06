function parseIncomingMessage(payload) {
  const body = payload || {};
  const message =
    body.message ||
    body.text ||
    body.body ||
    body?.data?.message ||
    body?.data?.text ||
    body?.messages?.[0]?.text?.body ||
    body?.messages?.[0]?.body ||
    '';

  const mobile =
    body.mobile ||
    body.from ||
    body.phone ||
    body.sender ||
    body?.data?.mobile ||
    body?.data?.from ||
    body?.contacts?.[0]?.wa_id ||
    body?.messages?.[0]?.from ||
    '';

  const customerName =
    body.customer_name ||
    body.name ||
    body?.data?.name ||
    body?.contacts?.[0]?.profile?.name ||
    '';

  return {
    text: String(message || '').trim(),
    mobile: String(mobile || '').trim(),
    customerName: String(customerName || '').trim()
  };
}

function parseBuy(text) {
  const match = String(text || '').trim().match(/^BUY\s+(\d+)$/i);
  if (!match) return null;
  const qty = Number(match[1]);
  if (!Number.isInteger(qty) || qty <= 0) return null;
  return { qty };
}

function parseAdd(text) {
  const lines = String(text || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (!/^ADD\b/i.test(lines[0] || '')) return null;

  const firstLineRest = lines[0].replace(/^ADD\b/i, '').trim();
  const accountLines = firstLineRest ? [firstLineRest, ...lines.slice(1)] : lines.slice(1);

  const accounts = accountLines
    .map((line) => {
      const [username] = line.split(/\s+/);
      return username ? { username } : null;
    })
    .filter(Boolean);

  return { accounts };
}

module.exports = {
  parseIncomingMessage,
  parseBuy,
  parseAdd
};
