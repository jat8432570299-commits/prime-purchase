const { v4: uuid } = require('uuid');
const env = require('../config/env');
const sheets = require('./sheetsService');
const settingsService = require('./settingsService');

const INVENTORY_HEADERS = ['id', 'username', 'password', 'status', 'sold_to', 'sold_number', 'sold_date'];

async function listInventory() {
  const data = await sheets.readSheet(env.inventorySheetName);
  return {
    headers: data.headers.length ? data.headers : INVENTORY_HEADERS,
    rows: data.rows
  };
}

async function getAvailableAccounts(qty) {
  const { rows } = await listInventory();
  return rows.filter((row) => String(row.status || '').toLowerCase() === 'available').slice(0, qty);
}

async function getStockCount() {
  const { rows } = await listInventory();
  return rows.filter((row) => String(row.status || '').toLowerCase() === 'available').length;
}

async function addAccounts(accounts) {
  await sheets.ensureHeaders(env.inventorySheetName, INVENTORY_HEADERS);
  const defaultPassword = await settingsService.getDefaultPassword();
  const rows = accounts.map((account) => [
    uuid(),
    account.username,
    account.password || defaultPassword,
    'available',
    '',
    '',
    ''
  ]);
  await sheets.appendRows(env.inventorySheetName, rows);
  return rows.length;
}

async function markSold(accounts, customerName, mobile) {
  const { headers } = await listInventory();
  const soldDate = new Date().toISOString();

  for (const account of accounts) {
    const updated = {
      ...account,
      status: 'sold',
      sold_to: customerName || mobile,
      sold_number: mobile,
      sold_date: soldDate
    };
    await sheets.updateRow(env.inventorySheetName, account._rowNumber, sheets.objectToRow(headers, updated));
  }

  return accounts.map((account) => ({
    id: account.id,
    username: account.username,
    password: account.password
  }));
}

async function ensureInventoryHeaders() {
  await sheets.ensureHeaders(env.inventorySheetName, INVENTORY_HEADERS);
}

module.exports = {
  INVENTORY_HEADERS,
  ensureInventoryHeaders,
  getAvailableAccounts,
  getStockCount,
  addAccounts,
  markSold
};
