const fs = require('fs');
const path = require('path');
const { google } = require('googleapis');
const env = require('../config/env');

const SCOPES = ['https://www.googleapis.com/auth/spreadsheets'];

function getCredentials() {
  if (env.googleServiceAccountJson) {
    return JSON.parse(env.googleServiceAccountJson);
  }

  const filePath = path.resolve(process.cwd(), env.googleServiceAccountFile);
  if (!fs.existsSync(filePath)) {
    throw new Error(`Google service account file not found: ${filePath}`);
  }
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

async function getClient() {
  const auth = new google.auth.GoogleAuth({
    credentials: getCredentials(),
    scopes: SCOPES
  });
  return google.sheets({ version: 'v4', auth });
}

function rowsToObjects(values) {
  const [headers = [], ...rows] = values || [];
  return rows.map((row, index) => {
    const item = {};
    headers.forEach((header, columnIndex) => {
      item[header] = row[columnIndex] || '';
    });
    item._rowNumber = index + 2;
    return item;
  });
}

function objectToRow(headers, object) {
  return headers.map((header) => object[header] ?? '');
}

async function readSheet(sheetName) {
  await ensureSheetExists(sheetName);
  const sheets = await getClient();
  const response = await sheets.spreadsheets.values.get({
    spreadsheetId: env.googleSheetId,
    range: `${sheetName}!A:Z`
  });
  const values = response.data.values || [];
  return {
    headers: values[0] || [],
    rows: rowsToObjects(values)
  };
}

async function appendRows(sheetName, rows) {
  if (!rows.length) return;
  await ensureSheetExists(sheetName);
  const sheets = await getClient();
  await sheets.spreadsheets.values.append({
    spreadsheetId: env.googleSheetId,
    range: `${sheetName}!A:Z`,
    valueInputOption: 'USER_ENTERED',
    requestBody: { values: rows }
  });
}

async function updateRow(sheetName, rowNumber, row) {
  await ensureSheetExists(sheetName);
  const sheets = await getClient();
  await sheets.spreadsheets.values.update({
    spreadsheetId: env.googleSheetId,
    range: `${sheetName}!A${rowNumber}:Z${rowNumber}`,
    valueInputOption: 'USER_ENTERED',
    requestBody: { values: [row] }
  });
}

async function ensureHeaders(sheetName, headers) {
  await ensureSheetExists(sheetName);
  const sheets = await getClient();
  await sheets.spreadsheets.values.update({
    spreadsheetId: env.googleSheetId,
    range: `${sheetName}!A1:${String.fromCharCode(64 + headers.length)}1`,
    valueInputOption: 'USER_ENTERED',
    requestBody: { values: [headers] }
  });
}

async function ensureSheetExists(sheetName) {
  const sheets = await getClient();
  const spreadsheet = await sheets.spreadsheets.get({
    spreadsheetId: env.googleSheetId,
    fields: 'sheets.properties.title'
  });

  const exists = (spreadsheet.data.sheets || []).some(
    (sheet) => sheet.properties && sheet.properties.title === sheetName
  );

  if (exists) return;

  await sheets.spreadsheets.batchUpdate({
    spreadsheetId: env.googleSheetId,
    requestBody: {
      requests: [
        {
          addSheet: {
            properties: {
              title: sheetName
            }
          }
        }
      ]
    }
  });
}

module.exports = {
  readSheet,
  appendRows,
  updateRow,
  ensureHeaders,
  ensureSheetExists,
  objectToRow
};
