# WhatsApp Inventory Automation

Node.js + Express inventory/order automation using:

- Google Sheets for inventory and orders
- Unofficial WhatsApp/IMB API for sending messages
- IMB payment webhook for paid delivery

## Sheet Setup

Create three tabs in your Google Sheet. `npm run setup:sheets` can create them automatically.

Inventory headers:

```text
id | username | password | status | sold_to | sold_number | sold_date
```

Orders headers:

```text
order_id | customer_name | mobile | qty | amount | payment_status | delivery_status | payment_provider | payment_id | created_at | delivered_at | credentials
```

Settings headers:

```text
key | value
```

Settings row:

```text
DEFAULT_PASSWORD | your_common_password
```

Allowed inventory statuses:

```text
available, sold
```

## Commands

Customer:

```text
BUY 5
```

Admin:

```text
STOCK
ORDERS
ADD
email1@example.com
```

Bulk add:

```text
ADD
email1@example.com
email2@example.com
```

New accounts use the password from `Settings -> DEFAULT_PASSWORD`. To change the password for future accounts, edit that value directly in Google Sheets.

## Setup

1. Install Node.js LTS.
2. Run:

```bash
npm install
```

3. Copy `.env.example` to `.env`.
4. Put Google service account file here:

```text
credentials/google-service-account.json
```

5. Share the Google Sheet with the service account email as Editor.
6. Check config:

```bash
npm run check
```

7. Start server:

```bash
npm start
```

## Webhooks

Set these URLs in your panel/deployment:

```text
POST https://your-domain.com/webhook/whatsapp
POST https://your-domain.com/webhook/imb-payment
GET  https://your-domain.com/health
```

## Render Deployment

Build command:

```text
npm install
```

Start command:

```text
npm start
```

Add all `.env` values in Render Environment tab. For Google credentials, either:

- Add the JSON file through Render secret files, then set `GOOGLE_SERVICE_ACCOUNT_FILE`, or
- Put the JSON as one-line env var `GOOGLE_SERVICE_ACCOUNT_JSON`.

This repo also includes `render.yaml`. Keep these Render values secret:

```text
IMB_API_TOKEN
GOOGLE_SERVICE_ACCOUNT_JSON
WEBHOOK_VERIFY_TOKEN
```

## IMB API Notes

The project keeps IMB endpoints configurable because unofficial API panels use different payload formats.

Important env values:

```env
IMB_API_BASE_URL=https://secure-stage.imb.org.in
IMB_WHATSAPP_SEND_PATH=/api/send-message
IMB_PAYMENT_CREATE_PATH=/api/payment/create
```

If your panel uses different paths or response fields, update only `.env` or `src/services/imbService.js`.

For local testing without sending real WhatsApp/API requests:

```env
IMB_MOCK_MODE=true
```

For live deployment:

```env
IMB_MOCK_MODE=false
```
