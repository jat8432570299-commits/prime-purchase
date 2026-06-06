const env = require('../config/env');
const sheets = require('./sheetsService');

const SETTINGS_HEADERS = ['key', 'value'];
const DEFAULT_PASSWORD_KEY = 'DEFAULT_PASSWORD';

async function ensureSettings() {
  await sheets.ensureHeaders(env.settingsSheetName, SETTINGS_HEADERS);
  const { rows } = await sheets.readSheet(env.settingsSheetName);
  const hasDefaultPassword = rows.some((row) => row.key === DEFAULT_PASSWORD_KEY);

  if (!hasDefaultPassword) {
    await sheets.appendRows(env.settingsSheetName, [[DEFAULT_PASSWORD_KEY, env.defaultAccountPassword]]);
  }
}

async function getSetting(key, fallback = '') {
  await ensureSettings();
  const { rows } = await sheets.readSheet(env.settingsSheetName);
  const setting = rows.find((row) => row.key === key);
  return setting && setting.value ? setting.value : fallback;
}

async function getDefaultPassword() {
  return getSetting(DEFAULT_PASSWORD_KEY, env.defaultAccountPassword);
}

module.exports = {
  SETTINGS_HEADERS,
  DEFAULT_PASSWORD_KEY,
  ensureSettings,
  getDefaultPassword
};
