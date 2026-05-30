# Prime Purchase Telegram Inventory Bot

Ye project legitimate digital inventory, access codes, vouchers, license keys, ya apne allowed product items ke liye hai. Third-party accounts/credentials ya policy-violating items sell/deliver karne ke liye use na karein.

## Flow

1. Customer `/start` ya `/products` se 1 Month aur 6 Month plans dekhta hai.
2. Bot plan price aur remaining stock Google Sheet se dikhata hai.
3. Customer button se quantity select karta hai, ya command use karta hai: `/buy 1m 2`.
4. Bot selected quantity ke items reserve karta hai aur pending order banata hai.
5. IMB payment link/UPI app links customer ko milte hain.
6. Payment success webhook ke baad reserved items `sold` mark hote hain.
7. Customer ko purchased inventory items Telegram par deliver ho jate hain.
8. Dashboard tab me price, stock, sold count, aur total sales update hoti hai.

## Google Sheet tabs

Bot `/sync` ya first run par ye tabs aur headers create kar dega.

`1 Month Inventory`

```text
item_id | item_value | password_or_pin | added_date | status | sold_to_username | telegram_user_id | order_id | purchase_date | notes
```

`6 Month Inventory`

```text
item_id | item_value | password_or_pin | added_date | status | sold_to_username | telegram_user_id | order_id | purchase_date | notes
```

Inventory add karne ka simple tareeka: `item_value` column me apna legal item/code add karein. Bot next sync/run par blank fields auto fill karega:

- `item_id`
- `password_or_pin`
- `added_date`
- `status = available`

`Dashboard`

```text
key | value | description
```

Editable keys:

```text
1_month_price
6_month_price
default_password_or_pin
```

Auto summary keys:

```text
total_sales_amount
1_month_sold
1_month_remaining
6_month_sold
6_month_remaining
```

`Orders`

```text
order_id | telegram_user_id | username | plan_id | plan_name | quantity | amount_inr | status | gateway_txn_id | payment_link_url | item_ids | delivered_items | created_at | paid_at | notes
```

## Bot commands

```text
/start
/products
/buy 1m 2
/buy 6m 1
/orders
/dashboard
/sync
```

`/dashboard` aur `/sync` sirf admin Telegram IDs ke liye hain.

## Setup

```powershell
cd "C:\Users\hp658\Desktop\New folder (2)\Prime Purchase"
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `.env`:

- `TELEGRAM_BOT_TOKEN`: BotFather token.
- `ADMIN_TELEGRAM_IDS`: comma-separated admin Telegram numeric IDs.
- `GOOGLE_SHEET_ID`: Sheet URL me `/d/.../edit` ke beech wala ID.
- `GOOGLE_SERVICE_ACCOUNT_FILE`: local JSON file path.
- `GOOGLE_SERVICE_ACCOUNT_JSON`: Render/cloud par service account JSON ka full one-line value.
- `IMB_USER_TOKEN`: IMB Payment Gateway API token.
- `IMB_CREATE_ORDER_URL`: IMB create order endpoint.
- `IMB_CHECK_STATUS_URL`: IMB status check endpoint.
- `EXISTING_WEBSITE_WEBHOOK_URL`: old website webhook URL. Default code me old website forward URL set hai.
- `WEBHOOK_FORWARD_STRICT`: `true` karne par old website forward fail hua to IMB ko error return hoga.
- `PUBLIC_BASE_URL`: Render URL, example `https://prime-purchase.onrender.com`.

## IMB webhook

IMB dashboard me callback/webhook URL:

```text
https://prime-purchase.onrender.com/imb/webhook
```

Bot same callback ko existing website webhook par forward bhi karega.
