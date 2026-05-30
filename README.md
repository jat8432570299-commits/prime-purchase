# Prime Purchase Telegram Store Bot + Google Sheets + IMB Payment

Ye template legitimate digital products/services ke liye hai. Third-party accounts, credentials, ya platform-policy violate karne wali items sell/deliver karne ke liye use na karein.

## Flow

1. Customer `/products` se active items dekhta hai.
2. Customer `/buy PRODUCT_ID` bhejta hai.
3. Bot Google Sheet me pending order banata hai.
4. Bot IMB Payment Gateway order create karke payment link aur UPI app links bhejta hai.
5. IMB webhook payment success par Sheet order status `paid` kar deta hai.
6. Bot customer ko confirmation bhejta hai. Fulfilment manual/compliant rakha gaya hai.

## Google Sheet tabs

Bot first run par headers create kar dega.

`Products`

```text
product_id | name | price_inr | description | active
```

Example row:

```text
course_basic | Basic Course | 499 | Recorded course access | yes
```

`Orders`

```text
order_id | telegram_user_id | username | product_id | product_name | amount_inr | status | payment_link_id | payment_link_url | created_at | paid_at | notes
```

## Setup

```powershell
cd "C:\Users\hp658\Desktop\New folder (2)\legit-telegram-store-bot"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `.env`:

- `TELEGRAM_BOT_TOKEN`: BotFather token.
- `ADMIN_TELEGRAM_IDS`: comma-separated admin Telegram numeric IDs.
- `GOOGLE_SHEET_ID`: Sheet URL me `/d/.../edit` ke beech wala ID.
- `GOOGLE_SERVICE_ACCOUNT_FILE`: Google service account JSON file path.
- `GOOGLE_SERVICE_ACCOUNT_JSON`: Cloud hosting par service account JSON ka full one-line value.
- `IMB_USER_TOKEN`: IMB Payment Gateway API token.
- `IMB_CREATE_ORDER_URL`: IMB create order endpoint.
- `IMB_CHECK_STATUS_URL`: IMB status check endpoint.
- `PUBLIC_BASE_URL`: ngrok/cloudflared/public domain, for example `https://abc.ngrok-free.app`.

Share Google Sheet with service account email as `Editor`.

## Run

```powershell
python bot.py
```

## Cloud Hosting

PC off rakhna hai to bot ko Render/Railway/VPS jaise cloud host par run karein. Cloudflare Tunnel local PC ko expose karta hai, isliye PC off hote hi tunnel band ho jayega. Cloudflare ko domain/DNS ke liye use kar sakte hain.

Render/Railway env variables me local `.env` ki values add karein. `service_account.json` file upload karne ke bajay `GOOGLE_SERVICE_ACCOUNT_JSON` me JSON ka full content paste kar sakte hain.

Local webhook URL:

```text
http://localhost:8080/imb/webhook
```

IMB dashboard me webhook/callback URL set karein:

```text
https://your-public-url.example.com/imb/webhook
```

IMB docs ke according Create Order API payment URL, Paytm link, PhonePe link aur BHIM/UPI link return karta hai: https://developer.imb.org.in/Docs/index

## Bot commands

```text
/start
/products
/buy PRODUCT_ID
/orders
/sync
```

`/sync` sirf admin ke liye hai. Ye sheet headers check/create karta hai.
