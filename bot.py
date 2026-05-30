import asyncio
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import gspread
import requests
from dotenv import load_dotenv
from flask import Flask, request
from google.oauth2.service_account import Credentials
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_TELEGRAM_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",")
    if value.strip().isdigit()
}

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
SHEET_6_MONTH = os.getenv("GOOGLE_WORKSHEET_6_MONTH", "6 Month Inventory")
SHEET_1_MONTH = os.getenv("GOOGLE_WORKSHEET_1_MONTH", "1 Month Inventory")
DASHBOARD_SHEET = os.getenv("GOOGLE_WORKSHEET_DASHBOARD", "Dashboard")
ORDERS_SHEET = os.getenv("GOOGLE_WORKSHEET_ORDERS", "Orders")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

IMB_USER_TOKEN = os.getenv("IMB_USER_TOKEN", "")
IMB_CREATE_ORDER_URL = os.getenv("IMB_CREATE_ORDER_URL", "https://secure-stage.imb.org.in/api/create-order")
IMB_CHECK_STATUS_URL = os.getenv("IMB_CHECK_STATUS_URL", "https://secure-stage.imb.org.in/api/check-order-status")
EXISTING_WEBSITE_WEBHOOK_URL = os.getenv(
    "EXISTING_WEBSITE_WEBHOOK_URL",
    "https://reseller.techsellpro.com/wc-api/upi-payment",
).strip()
WEBHOOK_FORWARD_STRICT = os.getenv("WEBHOOK_FORWARD_STRICT", "false").strip().lower() in {"1", "true", "yes", "y"}
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8080"))

PLAN_1 = "1m"
PLAN_6 = "6m"
PLANS = {
    PLAN_1: {"name": "1 Month", "sheet": SHEET_1_MONTH, "price_key": "1_month_price"},
    PLAN_6: {"name": "6 Month", "sheet": SHEET_6_MONTH, "price_key": "6_month_price"},
}

INVENTORY_HEADERS = [
    "item_id",
    "item_value",
    "password_or_pin",
    "added_date",
    "status",
    "sold_to_username",
    "telegram_user_id",
    "order_id",
    "purchase_date",
    "notes",
]
ORDER_HEADERS = [
    "order_id",
    "telegram_user_id",
    "username",
    "plan_id",
    "plan_name",
    "quantity",
    "amount_inr",
    "status",
    "gateway_txn_id",
    "payment_link_url",
    "item_ids",
    "delivered_items",
    "created_at",
    "paid_at",
    "notes",
]
DASHBOARD_HEADERS = ["key", "value", "description"]
DASHBOARD_DEFAULTS = [
    ["1_month_price", "99", "Customer price for one 1 Month inventory item."],
    ["6_month_price", "499", "Customer price for one 6 Month inventory item."],
    ["default_password_or_pin", "ChangeMe123", "Auto-filled for new inventory rows if blank."],
    ["total_sales_amount", "0", "Auto summary, do not edit."],
    ["1_month_sold", "0", "Auto summary, do not edit."],
    ["1_month_remaining", "0", "Auto summary, do not edit."],
    ["6_month_sold", "0", "Auto summary, do not edit."],
    ["6_month_remaining", "0", "Auto summary, do not edit."],
]

flask_app = Flask(__name__)
telegram_app: Optional[Application] = None
bot_loop: Optional[asyncio.AbstractEventLoop] = None
spreadsheet_cache = None
worksheet_cache: dict[str, gspread.Worksheet] = {}
schema_ready = False
plan_cache = (0.0, [])
PLAN_CACHE_SECONDS = 20


@dataclass
class PlanInfo:
    plan_id: str
    name: str
    price_inr: int
    stock: int


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
    global spreadsheet_cache
    if spreadsheet_cache:
        return spreadsheet_cache

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if SERVICE_ACCOUNT_JSON:
        creds = Credentials.from_service_account_info(json.loads(SERVICE_ACCOUNT_JSON), scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    spreadsheet_cache = client.open_by_key(GOOGLE_SHEET_ID)
    return spreadsheet_cache


def column_letter(count: int) -> str:
    result = ""
    while count:
        count, remainder = divmod(count - 1, 26)
        result = chr(65 + remainder) + result
    return result


def get_or_create_worksheet(spreadsheet, title: str, headers: list[str], rows: int = 500):
    try:
        worksheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=title, rows=rows, cols=len(headers))

    first_row = worksheet.row_values(1)
    if first_row[: len(headers)] != headers:
        worksheet.update(range_name=f"A1:{column_letter(len(headers))}1", values=[headers])
        worksheet.format(
            f"A1:{column_letter(len(headers))}1",
            {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.9, "green": 0.94, "blue": 1}},
        )
    return worksheet


def ensure_sheet_schema(force: bool = False):
    global schema_ready, worksheet_cache, plan_cache
    if schema_ready and not force:
        return (
            worksheet_cache[SHEET_1_MONTH],
            worksheet_cache[SHEET_6_MONTH],
            worksheet_cache[DASHBOARD_SHEET],
            worksheet_cache[ORDERS_SHEET],
        )

    spreadsheet = get_spreadsheet()
    one_month = get_or_create_worksheet(spreadsheet, SHEET_1_MONTH, INVENTORY_HEADERS)
    six_month = get_or_create_worksheet(spreadsheet, SHEET_6_MONTH, INVENTORY_HEADERS)
    dashboard = get_or_create_worksheet(spreadsheet, DASHBOARD_SHEET, DASHBOARD_HEADERS, rows=80)
    orders = get_or_create_worksheet(spreadsheet, ORDERS_SHEET, ORDER_HEADERS)
    ensure_dashboard_defaults(dashboard)
    normalize_inventory_sheet(one_month, get_dashboard_value(dashboard, "default_password_or_pin", "ChangeMe123"))
    normalize_inventory_sheet(six_month, get_dashboard_value(dashboard, "default_password_or_pin", "ChangeMe123"))
    update_dashboard_summary(dashboard, one_month, six_month, orders)
    worksheet_cache = {
        SHEET_1_MONTH: one_month,
        SHEET_6_MONTH: six_month,
        DASHBOARD_SHEET: dashboard,
        ORDERS_SHEET: orders,
    }
    schema_ready = True
    plan_cache = (0.0, [])
    return one_month, six_month, dashboard, orders


def row_dicts(worksheet) -> list[dict[str, str]]:
    return worksheet.get_all_records()


def ensure_dashboard_defaults(dashboard) -> None:
    existing = {str(row.get("key", "")).strip() for row in row_dicts(dashboard)}
    append_rows = [row for row in DASHBOARD_DEFAULTS if row[0] not in existing]
    if append_rows:
        dashboard.append_rows(append_rows, value_input_option="USER_ENTERED")


def get_dashboard_value(dashboard, key: str, default: str = "") -> str:
    for row in row_dicts(dashboard):
        if str(row.get("key", "")).strip() == key:
            return str(row.get("value", "")).strip() or default
    return default


def set_dashboard_value(dashboard, key: str, value: str, description: str = "") -> None:
    try:
        cell = dashboard.find(key, in_column=1)
    except gspread.CellNotFound:
        dashboard.append_row([key, value, description], value_input_option="USER_ENTERED")
        return
    dashboard.update_cell(cell.row, 2, value)
    if description:
        dashboard.update_cell(cell.row, 3, description)


def normalize_inventory_sheet(worksheet, default_pin: str) -> None:
    rows = worksheet.get_all_values()
    if len(rows) <= 1:
        return

    batch_updates = []
    for index, row in enumerate(rows[1:], start=2):
        values = row + [""] * (len(INVENTORY_HEADERS) - len(row))
        item_value = values[1].strip()
        if not item_value:
            continue

        if not values[0].strip():
            batch_updates.append({"range": f"A{index}", "values": [["item_" + uuid.uuid4().hex[:10]]]})
        if not values[2].strip():
            batch_updates.append({"range": f"C{index}", "values": [[default_pin]]})
        if not values[3].strip():
            batch_updates.append({"range": f"D{index}", "values": [[now_iso()]]})
        if not values[4].strip():
            batch_updates.append({"range": f"E{index}", "values": [["available"]]})

    if batch_updates:
        worksheet.batch_update(batch_updates, value_input_option="USER_ENTERED")


def inventory_for_plan(plan_id: str):
    one_month, six_month, _, _ = ensure_sheet_schema()
    return one_month if plan_id == PLAN_1 else six_month


def plan_price(dashboard, plan_id: str) -> int:
    raw_price = get_dashboard_value(dashboard, PLANS[plan_id]["price_key"], "0")
    try:
        return int(float(raw_price))
    except ValueError:
        return 0


def available_inventory_rows(worksheet) -> list[tuple[int, dict[str, str]]]:
    rows = row_dicts(worksheet)
    available = []
    for row_num, row in enumerate(rows, start=2):
        item_value = str(row.get("item_value", "")).strip()
        status = str(row.get("status", "")).strip().lower()
        if item_value and status in {"", "available"}:
            available.append((row_num, row))
    return available


def get_plan_info(plan_id: str) -> PlanInfo:
    for plan in all_plan_info():
        if plan.plan_id == plan_id:
            return plan
    raise RuntimeError("Invalid plan")


def all_plan_info() -> list[PlanInfo]:
    global plan_cache
    cached_at, cached_plans = plan_cache
    if cached_plans and time.time() - cached_at < PLAN_CACHE_SECONDS:
        return cached_plans

    one_month, six_month, dashboard, _ = ensure_sheet_schema()
    plans = [
        PlanInfo(
            plan_id=PLAN_1,
            name=PLANS[PLAN_1]["name"],
            price_inr=plan_price(dashboard, PLAN_1),
            stock=len(available_inventory_rows(one_month)),
        ),
        PlanInfo(
            plan_id=PLAN_6,
            name=PLANS[PLAN_6]["name"],
            price_inr=plan_price(dashboard, PLAN_6),
            stock=len(available_inventory_rows(six_month)),
        ),
    ]
    plan_cache = (time.time(), plans)
    return plans


def clear_plan_cache() -> None:
    global plan_cache
    plan_cache = (0.0, [])


def reserve_inventory(plan_id: str, quantity: int, order_id: str, user) -> list[dict[str, str]]:
    worksheet = inventory_for_plan(plan_id)
    available = available_inventory_rows(worksheet)
    if len(available) < quantity:
        raise RuntimeError("Stock kam hai.")

    reserved = []
    batch_updates = []
    for row_num, row in available[:quantity]:
        batch_updates.extend(
            [
                {"range": f"E{row_num}", "values": [["reserved"]]},
                {"range": f"F{row_num}", "values": [[user.username or ""]]},
                {"range": f"G{row_num}", "values": [[str(user.id)]]},
                {"range": f"H{row_num}", "values": [[order_id]]},
            ]
        )
        reserved.append(row)
    worksheet.batch_update(batch_updates, value_input_option="USER_ENTERED")
    clear_plan_cache()
    return reserved


def release_reserved_inventory(plan_id: str, order_id: str) -> None:
    worksheet = inventory_for_plan(plan_id)
    batch_updates = []
    for row_num, row in enumerate(row_dicts(worksheet), start=2):
        if str(row.get("order_id", "")).strip() != order_id:
            continue
        if str(row.get("status", "")).strip().lower() != "reserved":
            continue
        batch_updates.extend(
            [
                {"range": f"E{row_num}", "values": [["available"]]},
                {"range": f"F{row_num}:H{row_num}", "values": [["", "", ""]]},
            ]
        )
    if batch_updates:
        worksheet.batch_update(batch_updates, value_input_option="USER_ENTERED")
        clear_plan_cache()


def mark_reserved_sold(plan_id: str, order_id: str) -> list[dict[str, str]]:
    worksheet = inventory_for_plan(plan_id)
    delivered = []
    batch_updates = []
    for row_num, row in enumerate(row_dicts(worksheet), start=2):
        if str(row.get("order_id", "")).strip() != order_id:
            continue
        batch_updates.extend(
            [
                {"range": f"E{row_num}", "values": [["sold"]]},
                {"range": f"I{row_num}", "values": [[now_iso()]]},
            ]
        )
        delivered.append(row)
    if batch_updates:
        worksheet.batch_update(batch_updates, value_input_option="USER_ENTERED")
        clear_plan_cache()
    return delivered


def append_order(update: Update, plan: PlanInfo, quantity: int, reserved_items: list[dict[str, str]]) -> str:
    _, _, _, orders_ws = ensure_sheet_schema()
    order_id = "ord_" + uuid.uuid4().hex[:12]
    user = update.effective_user
    item_ids = ", ".join(str(item.get("item_id", "")).strip() for item in reserved_items)
    orders_ws.append_row(
        [
            order_id,
            str(user.id),
            user.username or "",
            plan.plan_id,
            plan.name,
            quantity,
            plan.price_inr * quantity,
            "pending",
            "",
            "",
            item_ids,
            "",
            now_iso(),
            "",
            "",
        ],
        value_input_option="USER_ENTERED",
    )
    return order_id


def create_order_with_inventory(update: Update, plan: PlanInfo, quantity: int) -> tuple[str, list[dict[str, str]]]:
    order_id = "ord_" + uuid.uuid4().hex[:12]
    reserved_items = reserve_inventory(plan.plan_id, quantity, order_id, update.effective_user)
    _, _, _, orders_ws = ensure_sheet_schema()
    user = update.effective_user
    item_ids = ", ".join(str(item.get("item_id", "")).strip() for item in reserved_items)
    orders_ws.append_row(
        [
            order_id,
            str(user.id),
            user.username or "",
            plan.plan_id,
            plan.name,
            quantity,
            plan.price_inr * quantity,
            "pending",
            "",
            "",
            item_ids,
            "",
            now_iso(),
            "",
            "",
        ],
        value_input_option="USER_ENTERED",
    )
    return order_id, reserved_items


def extract_payment_url(payment_data: dict[str, str]) -> str:
    for key in ("payment_url", "paymentUrl", "payment_link", "paymentLink", "url", "qr_url", "upi_qr_url"):
        value = payment_data.get(key)
        if value:
            return str(value)
    return ""


def update_order_payment_link(order_id: str, gateway_txn_id: str, payment_link_url: str) -> None:
    _, _, _, orders_ws = ensure_sheet_schema()
    cell = orders_ws.find(order_id, in_column=1)
    if not cell:
        return
    orders_ws.update_cell(cell.row, 9, gateway_txn_id)
    orders_ws.update_cell(cell.row, 10, payment_link_url)


def order_by_id(order_id: str) -> Optional[dict[str, str]]:
    _, _, _, orders_ws = ensure_sheet_schema()
    for row in row_dicts(orders_ws):
        if str(row.get("order_id", "")).strip() == order_id:
            return row
    return None


def update_order_paid(order_id: str, delivered_items: list[dict[str, str]], gateway_txn_id: str = "") -> Optional[int]:
    one_month, six_month, dashboard, orders_ws = ensure_sheet_schema()
    cell = orders_ws.find(order_id, in_column=1)
    if not cell:
        return None

    row_values = orders_ws.row_values(cell.row)
    telegram_user_id = int(row_values[1]) if len(row_values) > 1 and row_values[1].isdigit() else None
    delivered_values = ", ".join(str(item.get("item_value", "")).strip() for item in delivered_items)
    orders_ws.update_cell(cell.row, 8, "paid")
    if gateway_txn_id:
        orders_ws.update_cell(cell.row, 9, gateway_txn_id)
    orders_ws.update_cell(cell.row, 12, delivered_values)
    orders_ws.update_cell(cell.row, 14, now_iso())
    update_dashboard_summary(dashboard, one_month, six_month, orders_ws)
    return telegram_user_id


def list_user_orders(telegram_user_id: int) -> list[dict[str, str]]:
    _, _, _, orders_ws = ensure_sheet_schema()
    return [
        row
        for row in row_dicts(orders_ws)
        if str(row.get("telegram_user_id", "")).strip() == str(telegram_user_id)
    ]


def update_dashboard_summary(dashboard, one_month, six_month, orders_ws) -> None:
    one_available = len(available_inventory_rows(one_month))
    six_available = len(available_inventory_rows(six_month))
    one_sold = sum(1 for row in row_dicts(one_month) if str(row.get("status", "")).strip().lower() == "sold")
    six_sold = sum(1 for row in row_dicts(six_month) if str(row.get("status", "")).strip().lower() == "sold")
    total_sales = 0
    for row in row_dicts(orders_ws):
        if str(row.get("status", "")).strip().lower() == "paid":
            try:
                total_sales += int(float(str(row.get("amount_inr", "0")).strip()))
            except ValueError:
                pass

    set_dashboard_value(dashboard, "1_month_remaining", str(one_available), "Auto summary, do not edit.")
    set_dashboard_value(dashboard, "6_month_remaining", str(six_available), "Auto summary, do not edit.")
    set_dashboard_value(dashboard, "1_month_sold", str(one_sold), "Auto summary, do not edit.")
    set_dashboard_value(dashboard, "6_month_sold", str(six_sold), "Auto summary, do not edit.")
    set_dashboard_value(dashboard, "total_sales_amount", str(total_sales), "Auto summary, do not edit.")


def create_payment_link(order_id: str, update: Update, plan: PlanInfo, quantity: int) -> dict[str, str]:
    user = update.effective_user
    amount = plan.price_inr * quantity
    payload = {
        "customer_mobile": "9999999999",
        "user_token": IMB_USER_TOKEN,
        "amount": str(amount),
        "order_id": order_id,
        "redirect_url": f"{PUBLIC_BASE_URL}/payment/thanks?order_id={order_id}",
        "remark1": f"telegram_user_{user.id}",
        "remark2": f"{plan.plan_id}:{quantity}",
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


def forward_to_existing_website(raw_body: bytes, content_type: str) -> bool:
    if not EXISTING_WEBSITE_WEBHOOK_URL:
        return True

    headers = {"Content-Type": content_type} if content_type else {}
    try:
        response = requests.post(
            EXISTING_WEBSITE_WEBHOOK_URL,
            data=raw_body,
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"Existing website webhook forward failed: {exc}")
        return False


def plans_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for plan in all_plan_info():
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{plan.name} | Rs.{plan.price_inr} | Stock {plan.stock}",
                    callback_data=f"plan:{plan.plan_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(buttons)


def quantity_keyboard(plan_id: str, stock: int) -> InlineKeyboardMarkup:
    quantities = [1, 2, 3, 5, 10]
    buttons = [
        InlineKeyboardButton(str(quantity), callback_data=f"qty:{plan_id}:{quantity}")
        for quantity in quantities
        if quantity <= stock
    ]
    rows = [buttons[index : index + 3] for index in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton("Back", callback_data="back:plans")])
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Namaste! Inventory store ready hai.\n\nPlan select karein:",
        reply_markup=plans_keyboard(),
    )


async def products_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["Available plans"]
    for plan in all_plan_info():
        lines.append(f"{plan.name}: Rs.{plan.price_inr} each | Stock: {plan.stock}")
    lines.append("\nBuy: /buy 1m 2 ya /buy 6m 1")
    await update.message.reply_text("\n".join(lines), reply_markup=plans_keyboard())


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Format: /buy 1m 2 ya /buy 6m 1")
        return
    plan_id = context.args[0].lower()
    if plan_id not in PLANS:
        await update.message.reply_text("Plan invalid hai. Use: 1m ya 6m")
        return
    try:
        quantity = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Quantity number me bhejein.")
        return
    await create_order_and_send_payment(update, plan_id, quantity)


async def create_order_and_send_payment(update: Update, plan_id: str, quantity: int) -> None:
    plan = get_plan_info(plan_id)
    if quantity < 1:
        await update.effective_message.reply_text("Quantity kam se kam 1 honi chahiye.")
        return
    if quantity > plan.stock:
        await update.effective_message.reply_text(f"Stock sirf {plan.stock} bacha hai.")
        return

    order_id = ""
    try:
        order_id, _ = create_order_with_inventory(update, plan, quantity)
        payment_data = create_payment_link(order_id, update, plan, quantity)
        payment_link_url = extract_payment_url(payment_data)
        update_order_payment_link(order_id, payment_data.get("orderId", order_id), payment_link_url)
    except (requests.HTTPError, RuntimeError, requests.RequestException) as exc:
        if order_id:
            release_reserved_inventory(plan.plan_id, order_id)
        await update.effective_message.reply_text(
            "Payment order create nahi ho paya. Thodi der baad retry karein ya admin ko batayein."
        )
        print(f"Order error: {exc}")
        return

    if not payment_link_url:
        release_reserved_inventory(plan.plan_id, order_id)
        await update.effective_message.reply_text("Gateway ne payment link return nahi kiya. Admin ko batayein.")
        print(f"Payment response without link for {order_id}: {payment_data}")
        return

    paytm_link = payment_data.get("paytm_link", "") or payment_data.get("paytmLink", "")
    phonepe_link = payment_data.get("phonepe_link", "") or payment_data.get("phonepeLink", "")
    bhim_link = payment_data.get("bhim_link", "") or payment_data.get("bhimLink", "")
    app_links = "\n".join(
        line
        for line in [
            f"Paytm: {paytm_link}" if paytm_link else "",
            f"PhonePe: {phonepe_link}" if phonepe_link else "",
            f"BHIM/UPI: {bhim_link}" if bhim_link else "",
        ]
        if line
    )

    await update.effective_message.reply_text(
        f"Order ban gaya: `{order_id}`\n"
        f"Plan: *{plan.name}*\n"
        f"Quantity: *{quantity}*\n"
        f"Total: *Rs.{plan.price_inr * quantity}*\n\n"
        f"Payment link:\n{payment_link_url}\n\n"
        f"{app_links}\n\n"
        "Payment successful hote hi inventory items yahin mil jayenge.",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    orders = list_user_orders(update.effective_user.id)
    if not orders:
        await update.message.reply_text("Aapka koi order abhi Sheet me nahi mila.")
        return

    lines = ["Your orders"]
    for order in orders[-10:]:
        lines.append(
            f"{order.get('order_id')} - {order.get('plan_name')} x {order.get('quantity')} - "
            f"Rs.{order.get('amount_inr')} - {order.get('status')}"
        )
    await update.message.reply_text("\n".join(lines))


async def sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_TELEGRAM_IDS:
        await update.message.reply_text("Ye admin command hai.")
        return
    ensure_sheet_schema(force=True)
    await update.message.reply_text("Sheet headers, dashboard aur inventory auto fields synced.")


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_TELEGRAM_IDS:
        await update.message.reply_text("Ye admin command hai.")
        return
    _, _, dashboard, _ = ensure_sheet_schema()
    values = {str(row.get("key", "")): str(row.get("value", "")) for row in row_dicts(dashboard)}
    await update.message.reply_text(
        "Dashboard\n"
        f"1 Month price: Rs.{values.get('1_month_price', '')}\n"
        f"6 Month price: Rs.{values.get('6_month_price', '')}\n"
        f"1 Month sold: {values.get('1_month_sold', '0')}\n"
        f"1 Month remaining: {values.get('1_month_remaining', '0')}\n"
        f"6 Month sold: {values.get('6_month_sold', '0')}\n"
        f"6 Month remaining: {values.get('6_month_remaining', '0')}\n"
        f"Total sales: Rs.{values.get('total_sales_amount', '0')}"
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == "back:plans":
        await query.edit_message_text("Plan select karein:", reply_markup=plans_keyboard())
        return

    if data.startswith("plan:"):
        plan_id = data.split(":", 1)[1]
        plan = get_plan_info(plan_id)
        if plan.stock <= 0:
            await query.edit_message_text(f"{plan.name} ka stock abhi khatam hai.", reply_markup=plans_keyboard())
            return
        await query.edit_message_text(
            f"{plan.name}\nPrice: Rs.{plan.price_inr} each\nStock: {plan.stock}\n\nQuantity select karein:",
            reply_markup=quantity_keyboard(plan_id, plan.stock),
        )
        return

    if data.startswith("qty:"):
        _, plan_id, quantity_text = data.split(":")
        try:
            quantity = int(quantity_text)
        except ValueError:
            await query.edit_message_text("Quantity invalid hai.")
            return
        await query.edit_message_text("Order create ho raha hai...")
        await create_order_and_send_payment(update, plan_id, quantity)


def format_delivery_message(order: dict[str, str], delivered_items: list[dict[str, str]]) -> str:
    plan_name = str(order.get("plan_name", "Plan"))
    lines = [plan_name, ""]
    pin = ""
    for index, item in enumerate(delivered_items, start=1):
        lines.append(f"Item {index}: {str(item.get('item_value', '')).strip()}")
        pin = pin or str(item.get("password_or_pin", "")).strip()
    if pin:
        lines.extend(["", f"PIN/Password: {pin}"])
    return "\n".join(lines)


@flask_app.get("/health")
def health():
    return {"ok": True}


@flask_app.get("/payment/thanks")
def payment_thanks():
    return "Payment response received. Telegram par confirmation check karein."


@flask_app.post("/imb/webhook")
def imb_webhook():
    raw_body = request.get_data()
    forwarded = forward_to_existing_website(raw_body, request.headers.get("Content-Type", ""))
    if WEBHOOK_FORWARD_STRICT and not forwarded:
        return {"ok": False, "error": "website forward failed"}, 502

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

        order = order_by_id(order_id)
        if not order:
            return {"ok": True, "order_found": False}
        if str(order.get("status", "")).strip().lower() == "paid":
            return {"ok": True, "already_paid": True}

        verified_result = verified_status.get("result") or {}
        verified_txn_id = str(verified_result.get("utr") or verified_result.get("orderId") or gateway_txn_id).strip()
        delivered_items = mark_reserved_sold(str(order.get("plan_id", "")), order_id)
        telegram_user_id = update_order_paid(order_id, delivered_items, verified_txn_id)
        if telegram_user_id and telegram_app and bot_loop:
            message = format_delivery_message(order, delivered_items)
            asyncio.run_coroutine_threadsafe(
                telegram_app.bot.send_message(chat_id=telegram_user_id, text=message),
                bot_loop,
            )
    return {"ok": True}


@flask_app.post("/telegram/webhook")
def telegram_webhook():
    if not telegram_app or not bot_loop:
        return {"ok": False, "error": "telegram app not ready"}, 503

    payload = request.get_json(force=True, silent=True)
    if not payload:
        return {"ok": False, "error": "empty update"}, 400

    update = Update.de_json(payload, telegram_app.bot)
    future = asyncio.run_coroutine_threadsafe(telegram_app.process_update(update), bot_loop)
    future.result(timeout=30)
    return {"ok": True}


def run_flask() -> None:
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


def run_bot_loop() -> None:
    if not bot_loop:
        return
    asyncio.set_event_loop(bot_loop)
    bot_loop.run_forever()


def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("products", products_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("sync", sync_command))
    app.add_handler(CommandHandler("dashboard", dashboard_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    return app


def main() -> None:
    global telegram_app, bot_loop
    require_env()
    ensure_sheet_schema(force=True)

    telegram_app = build_app()
    bot_loop = asyncio.new_event_loop()
    threading.Thread(target=run_bot_loop, daemon=True).start()
    asyncio.run_coroutine_threadsafe(telegram_app.initialize(), bot_loop).result(timeout=60)
    asyncio.run_coroutine_threadsafe(telegram_app.start(), bot_loop).result(timeout=60)
    webhook_url = f"{PUBLIC_BASE_URL}/telegram/webhook"
    asyncio.run_coroutine_threadsafe(
        telegram_app.bot.set_webhook(webhook_url, allowed_updates=Update.ALL_TYPES),
        bot_loop,
    ).result(timeout=60)
    asyncio.run_coroutine_threadsafe(
        telegram_app.bot.set_my_commands(
            [
                BotCommand("start", "Start inventory bot"),
                BotCommand("products", "Show plans and stock"),
                BotCommand("buy", "Buy: /buy 1m 1 or /buy 6m 1"),
                BotCommand("orders", "Show your orders"),
                BotCommand("dashboard", "Admin dashboard"),
                BotCommand("sync", "Admin sheet sync"),
            ]
        ),
        bot_loop,
    ).result(timeout=60)
    run_flask()


if __name__ == "__main__":
    main()
