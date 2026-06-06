function normalizePhone(value) {
  return String(value || '').replace(/\D/g, '');
}

function isAdmin(value, admins) {
  const phone = normalizePhone(value);
  return admins.map(normalizePhone).includes(phone);
}

module.exports = {
  normalizePhone,
  isAdmin
};

