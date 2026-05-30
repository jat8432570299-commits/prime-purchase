import asyncio
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import gspread
import requests
from dotenv import load_dotenv
from flask import Flask, request
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_TELEGRAM_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",")
    if value.strip().isdigit()
}

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
PRODUCTS_SHEET = os.getenv("GOOGLE_WORKSHEET_PRODUCTS", "Products")
ORDERS_SHEET = os.getenv("GOOGLE_WORKSHEET_ORDERS", "Orders")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

IMB_USER_TOKEN = os.getenv("IMB_USER_TOKEN", "")
IMB_CREATE_ORDER_URL = os.getenv("IMB_CREATE_ORDER_URL", "https://secure-stage.imb.org.in/api/create-order")
IMB_CHECK_STATUS_URL = os.getenv("IMB_CHECK_STATUS_URL", "https://secure-stage.imb.org.in/api/check-order-status")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8080"))

PRODUCT_HEADERS = ["product_id", "name", "price_inr", "description", "active"]
ORDER_HEADERS = [
    "order_id",
    "telegram_user_id",
    "username",
    "product_id",
    "product_name",
    "amount_inr",
    "status",
    "gateway_txn_id",
    "payment_link_url",
    "created_at",
    "paid_at",
    "notes",
]

flask_app = Flask(__name__)
telegram_app: Optional[Application] = None
bot_loop: Optional[asyncio.AbstractEventLoop] = None


@dataclass
class Product:
    product_id: str
    name: str
    price_inr: int
    description: str
    active: bool


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def require_env() -> None:
    missing = [
        name
        for name, value in {
            "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
            "GOOGLE_SHEET_ID": GOOGLE_SHEET_ID,
            "IMB_USER_TOKEN": IMB_USER_TOKEN,
            "PUBLIC_BASE_URL": PUBLIC_BASE_URL,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError("Missing .env values: " + ", ".join(missing))


def get_spreadsheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if SERVICE_ACCOUNT_JSON:
        creds = Credentials.from_service_account_info(json.loads(SERVICE_ACCOUNT_JSON), scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_ID)


def get_or_create_worksheet(spreadsheet, title: str, headers: list[str]):
    try:
        worksheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=title, rows=200, cols=len(headers))

    first_row = worksheet.row_values(1)
    if first_row[: len(headers)] != headers:
        worksheet.update(range_name=f"A1:{chr(64 + len(headers))}1", values=[headers])
        worksheet.format(
            f"A1:{chr(64 + len(headers))}1",
            {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.9, "green": 0.94, "blue": 1}},
        )
    return worksheet


def ensure_sheet_schema() -> tuple[gspread.Worksheet, gspread.Worksheet]:
    spreadsheet = get_spreadsheet()
    products = get_or_create_worksheet(spreadsheet, PRODUCTS_SHEET, PRODUCT_HEADERS)
    orders = get_or_create_worksheet(spreadsheet, ORDERS_SHEET, ORDER_HEADERS)
    return products, orders


def row_dicts(worksheet) -> list[dict[str, str]]:
    return worksheet.get_all_records()


def get_active_products() -> list[Product]:
    products_ws, _ = ensure_sheet_schema()
    products: list[Product] = []
    for row in row_dicts(products_ws):
        active = str(row.get("active", "")).strip().lower() in {"yes", "y", "true", "1", "active"}
        if not active:
            continue
        try:
            price = int(float(str(row.get("price_inr", "0")).strip()))
        except ValueError:
            continue
        product_id = str(row.get("product_id", "")).strip()
        name = str(row.get("name", "")).strip()
        if product_id and name and price > 0:
            products.append(
                Product(
                    product_id=product_id,
                    name=name,
                    price_inr=price,
                    description=str(row.get("description", "")).strip(),
                    active=True,
                )
            )
    return products


def find_product(product_id: str) -> Optional[Product]:
    normalized = product_id.strip().lower()
    for product in get_active_products():
        if product.product_id.lower() == normalized:
            return product
    return None


def append_order(update: Update, product: Product) -> str:
    _, orders_ws = ensure_sheet_schema()
    order_id = "ord_" + uuid.uuid4().hex[:12]
    user = update.effective_user
    orders_ws.append_row(
        [
            order_id,
            str(user.id),
            user.username or "",
            product.product_id,
            product.name,
            product.price_inr,
            "pending",
            "",
            "",
            now_iso(),
            "",
            "",
        ],
        value_input_option="USER_ENTERED",
    )
    return order_id


def update_order_payment_link(order_id: str, gateway_txn_id: str, payment_link_url: str) -> None:
    _, orders_ws = ensure_sheet_schema()
    cell = orders_ws.find(order_id, in_column=1)
    if not cell:
        return
    orders_ws.update_cell(cell.row, 8, gateway_txn_id)
    orders_ws.update_cell(cell.row, 9, payment_link_url)


def mark_order_paid(order_id: str, gateway_txn_id: str = "") -> Optional[int]:
    _, orders_ws = ensure_sheet_schema()
    cell = orders_ws.find(order_id, in_column=1)
    if not cell:
        return None

    row_values = orders_ws.row_values(cell.row)
    telegram_user_id = int(row_values[1]) if len(row_values) > 1 and row_values[1].isdigit() else None
    orders_ws.update_cell(cell.row, 7, "paid")
    if gateway_txn_id:
        orders_ws.update_cell(cell.row, 8, gateway_txn_id)
    orders_ws.update_cell(cell.row, 11, now_iso())
    return telegram_user_id


def list_user_orders(telegram_user_id: int) -> list[dict[str, str]]:
    _, orders_ws = ensure_sheet_schema()
    return [
        row
        for row in row_dicts(orders_ws)
        if str(row.get("telegram_user_id", "")).strip() == str(telegram_user_id)
    ]


def create_payment_link(order_id: str, update: Update, product: Product) -> dict[str, str]:
    user = update.effective_user
    payload = {
        "customer_mobile": "9999999999",
        "user_token": IMB_USER_TOKEN,
        "amount": str(product.price_inr),
        "order_id": order_id,
        "redirect_url": f"{PUBLIC_BASE_URL}/payment/thanks?order_id={order_id}",
        "remark1": f"telegram_user_{user.id}",
        "remark2": product.product_id,
    }
    response = requests.post(
        IMB_CREATE_ORDER_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status") not in {True, "true", "TRUE", "success", "SUCCESS"}:
        raise RuntimeError(data.get("message", "IMB order create failed"))
    return data.get("result", {})


def check_imb_order_status(order_id: str) -> dict:
    response = requests.post(
        IMB_CHECK_STATUS_URL,
        data={"user_token": IMB_USER_TOKEN, "order_id": order_id},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def is_imb_status_paid(status_response: dict) -> bool:
    status = str(status_response.get("status", "")).upper()
    result = status_response.get("result") or {}
    result_status = str(result.get("status") or result.get("txnStatus") or "").upper()
    return status in {"SUCCESS", "COMPLETED"} or result_status in {"SUCCESS", "COMPLETED"}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Namaste! Legitimate products/services ke liye store bot ready hai.\n\n"
        "Commands:\n"
        "/products - active products dekhein\n"
        "/buy PRODUCT_ID - order aur payment link banayein\n"
        "/orders - apne orders dekhein"
    )


async def products_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    products = get_active_products()
    if not products:
        await update.message.reply_text("Abhi koi active product Sheet me nahi mila.")
        return

    lines = ["*Available Products*"]
    for product in products:
        description = f"\n{product.description}" if product.description else ""
        lines.append(f"\n*{product.name}* - ₹{product.price_inr}\nID: `{product.product_id}`{description}")
    lines.append("\nBuy karne ke liye: `/buy PRODUCT_ID`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Format: /buy PRODUCT_ID")
        return

    product = find_product(context.args[0])
    if not product:
        await update.message.reply_text("Product nahi mila ya inactive hai. /products check karein.")
        return

    order_id = append_order(update, product)
    try:
        payment_data = create_payment_link(order_id, update, product)
        payment_link_url = payment_data.get("payment_url", "")
        update_order_payment_link(order_id, payment_data.get("orderId", order_id), payment_link_url)
    except (requests.HTTPError, RuntimeError) as exc:
        await update.message.reply_text(f"Payment link create nahi ho paya. Admin ko batayein. Order: {order_id}")
        print(f"IMB error for {order_id}: {exc}")
        return

    paytm_link = payment_data.get("paytm_link", "")
    phonepe_link = payment_data.get("phonepe_link", "")
    bhim_link = payment_data.get("bhim_link", "")
    app_links = "\n".join(
        line
        for line in [
            f"Paytm: {paytm_link}" if paytm_link else "",
            f"PhonePe: {phonepe_link}" if phonepe_link else "",
            f"BHIM/UPI: {bhim_link}" if bhim_link else "",
        ]
        if line
    )

    await update.message.reply_text(
        f"Order ban gaya: `{order_id}`\n"
        f"Product: *{product.name}*\n"
        f"Amount: ₹{product.price_inr}\n\n"
        f"Payment link:\n{payment_link_url}\n\n"
        f"{app_links}",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    orders = list_user_orders(update.effective_user.id)
    if not orders:
        await update.message.reply_text("Aapka koi order abhi Sheet me nahi mila.")
        return

    lines = ["*Your Orders*"]
    for order in orders[-10:]:
        lines.append(
            f"\n`{order.get('order_id')}` - {order.get('product_name')} - "
            f"₹{order.get('amount_inr')} - *{order.get('status')}*"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_TELEGRAM_IDS:
        await update.message.reply_text("Ye admin command hai.")
        return
    ensure_sheet_schema()
    await update.message.reply_text("Sheet headers synced.")


@flask_app.get("/health")
def health():
    return {"ok": True}


@flask_app.get("/payment/thanks")
def payment_thanks():
    return "Payment response received. Telegram par confirmation check karein."


@flask_app.post("/imb/webhook")
def imb_webhook():
    payload = request.form.to_dict(flat=True) or (request.get_json(silent=True) or {})
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    status = str(payload.get("status") or result.get("txnStatus") or result.get("status") or "").upper()
    order_id = str(payload.get("order_id") or result.get("orderId") or "").strip()
    gateway_txn_id = str(result.get("utr") or result.get("orderId") or order_id).strip()

    if order_id and status in {"SUCCESS", "COMPLETED", "TRUE"}:
        try:
            verified_status = check_imb_order_status(order_id)
        except requests.RequestException as exc:
            print(f"IMB status check failed for {order_id}: {exc}")
            return {"ok": False, "error": "status check failed"}, 502

        if not is_imb_status_paid(verified_status):
            return {"ok": True, "verified": False}

        verified_result = verified_status.get("result") or {}
        verified_txn_id = str(verified_result.get("utr") or verified_result.get("orderId") or gateway_txn_id).strip()
        telegram_user_id = mark_order_paid(order_id, verified_txn_id)
        if telegram_user_id and telegram_app and bot_loop:
            message = (
                f"Payment confirm ho gaya.\nOrder: `{order_id}`\n\n"
                "Aapka order processing me hai. Team compliant fulfilment ke liye contact karegi."
            )
            asyncio.run_coroutine_threadsafe(
                telegram_app.bot.send_message(
                    chat_id=telegram_user_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                ),
                bot_loop,
            )
    return {"ok": True}


def run_flask() -> None:
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("products", products_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("sync", sync_command))
    return app


def main() -> None:
    global telegram_app, bot_loop
    require_env()
    ensure_sheet_schema()

    telegram_app = build_app()
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)
    threading.Thread(target=run_flask, daemon=True).start()
    telegram_app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
