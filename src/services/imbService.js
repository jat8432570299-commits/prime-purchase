const axios = require('axios');
const env = require('../config/env');

function buildHeaders() {
  const headers = {
    'Content-Type': 'application/json'
  };

  if (!env.imbAuthHeader) {
    return headers;
  }

  if (env.imbAuthHeader.toLowerCase() === 'authorization') {
    headers.Authorization = env.imbAuthScheme
      ? `${env.imbAuthScheme} ${env.imbApiToken}`
      : env.imbApiToken;
  } else {
    headers[env.imbAuthHeader] = env.imbApiToken;
  }

  return headers;
}

async function imbPost(path, body) {
  const url = `${env.imbApiBaseUrl}${path.startsWith('/') ? path : `/${path}`}`;
  const response = await axios.post(url, body, {
    headers: buildHeaders(),
    timeout: 30000
  });
  return response.data;
}

async function imbFormPost(path, body) {
  const url = `${env.imbApiBaseUrl}${path.startsWith('/') ? path : `/${path}`}`;
  const response = await axios.post(url, new URLSearchParams(body), {
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded'
    },
    timeout: 30000
  });
  return response.data;
}

async function smsquickerPost(path, body) {
  const url = `${env.smsquickerApiBaseUrl}${path.startsWith('/') ? path : `/${path}`}`;
  const response = await axios.post(url, body, {
    headers: {
      'Content-Type': 'application/json'
    },
    timeout: 30000
  });
  return response.data;
}

async function smsquickerFormPost(path, fields) {
  const url = `${env.smsquickerApiBaseUrl}${path.startsWith('/') ? path : `/${path}`}`;
  const form = new FormData();
  Object.entries(fields).forEach(([key, value]) => {
    form.append(key, String(value ?? ''));
  });

  const response = await axios.post(url, form, {
    timeout: 30000
  });
  return response.data;
}

async function getSmsquickerCredits() {
  const url = `${env.smsquickerApiBaseUrl}/api/get/credits?secret=${encodeURIComponent(env.smsquickerApiSecret)}`;
  const response = await axios.get(url, { timeout: 30000 });
  return response.data;
}

async function sendWhatsAppMessage(to, message) {
  if (env.imbWhatsappMockMode || !env.smsquickerApiSecret) {
    console.log(`[MOCK WHATSAPP] to=${to}\n${message}`);
    return { ok: true, mock: true };
  }

  if (env.whatsappProvider === 'smsquicker') {
    if (env.smsquickerSendPath.includes('/api/send/sms')) {
      return smsquickerFormPost(env.smsquickerSendPath, {
        secret: env.smsquickerApiSecret,
        mode: env.smsquickerMode,
        ...(env.smsquickerSendPath.includes('bulk') ? { campaign: env.smsquickerCampaign } : {}),
        [env.smsquickerMessageField]: message,
        [env.smsquickerPhoneField]: to,
        sim: env.smsquickerSim
      });
    }

    if (env.smsquickerSendPath.includes('/api/send/whatsapp')) {
      return smsquickerFormPost(env.smsquickerSendPath, {
        secret: env.smsquickerApiSecret,
        account: env.smsquickerWhatsappAccount,
        [env.smsquickerPhoneField]: to,
        type: env.smsquickerType,
        [env.smsquickerMessageField]: message
      });
    }

    const payload = {
      secret: env.smsquickerApiSecret,
      [env.smsquickerPhoneField]: to,
      [env.smsquickerMessageField]: message
    };
    return smsquickerPost(env.smsquickerSendPath, payload);
  }

  const payload = {
    mobile: to,
    phone: to,
    number: to,
    to,
    message,
    text: message,
    type: 'text'
  };

  return imbPost(env.imbWhatsappSendPath, payload);
}

async function createPaymentLink(order) {
  if (env.imbPaymentMockMode) {
    const base = env.publicBaseUrl || 'http://localhost:3000';
    return {
      raw: { ok: true, mock: true },
      paymentLink: `${base.replace(/\/+$/, '')}/mock-pay/${order.order_id}`
    };
  }

  const callbackUrl = env.publicBaseUrl
    ? `${env.publicBaseUrl.replace(/\/+$/, '')}/webhook/imb-payment`
    : '';

  const payload = {
    customer_mobile: order.mobile,
    user_token: env.imbApiToken,
    amount: String(order.amount),
    order_id: order.order_id,
    redirect_url: callbackUrl || env.publicBaseUrl || 'http://localhost:3000',
    remark1: order.customer_name || order.mobile,
    remark2: order.order_id
  };

  const data = await imbFormPost(env.imbPaymentCreatePath, payload);
  return {
    raw: data,
    paymentLink:
      data.payment_link ||
      data.payment_url ||
      data.url ||
      data?.result?.payment_url ||
      data?.result?.paytm_link ||
      data?.result?.bhim_link ||
      data?.data?.payment_link ||
      data?.data?.payment_url ||
      data?.data?.url ||
      ''
  };
}

async function checkPaymentStatus(orderId) {
  const data = await imbFormPost(env.imbPaymentStatusPath, {
    user_token: env.imbApiToken,
    order_id: orderId
  });

  return {
    raw: data,
    event: extractPaymentEvent(data)
  };
}

function extractPaymentEvent(payload) {
  const body = payload || {};
  const data = body.data || body.payment || body.order || body;
  const orderId =
    data.order_id ||
    data.orderId ||
    data.order_id ||
    data.client_order_id ||
    data.reference_id ||
    data?.result?.orderId ||
    data?.result?.order_id ||
    body.order_id ||
    body.orderId ||
    '';

  const paymentId =
    data.payment_id ||
    data.paymentId ||
    data.transaction_id ||
    data.txn_id ||
    data.utr ||
    data?.result?.utr ||
    body.payment_id ||
    '';

  const statusRaw =
    data.status ||
    data.payment_status ||
    data.txn_status ||
    data.txnStatus ||
    data?.result?.status ||
    data?.result?.txnStatus ||
    body.status ||
    '';

  const normalizedStatus = String(statusRaw).toLowerCase();
  const paid = ['paid', 'success', 'successful', 'captured', 'completed', 'credit'].includes(normalizedStatus);

  return {
    orderId: String(orderId || '').trim(),
    paymentId: String(paymentId || '').trim(),
    status: normalizedStatus,
    paid
  };
}

module.exports = {
  sendWhatsAppMessage,
  createPaymentLink,
  checkPaymentStatus,
  getSmsquickerCredits,
  extractPaymentEvent
};
