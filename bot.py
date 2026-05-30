import asyncio
import html
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
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters


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
CUSTOMERS_SHEET = os.getenv("GOOGLE_WORKSHEET_CUSTOMERS", "Customers")
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
SUPPORT_WHATSAPP = os.getenv("SUPPORT_WHATSAPP", "+91 XXXXX XXXXX")

PLAN_1 = "1m"
PLAN_6 = "6m"
PLANS = {
    PLAN_1: {"name": "1 Month", "sheet": SHEET_1_MONTH, "price_key": "1_month_price"},
    PLAN_6: {"name": "6 Month", "sheet": SHEET_6_MONTH, "price_key": "6_month_price"},
}

INVENTORY_HEADERS = [
    "mail_id",
    "added_date",
    "purchase_date",
    "sold_to_username",
    "telegram_user_id",
    "order_id",
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
    "mail_ids",
    "delivered_items",
    "created_at",
    "paid_at",
    "notes",
]
CUSTOMER_HEADERS = [
    "telegram_user_id",
    "username",
    "first_name",
    "first_seen",
    "last_seen",
    "blocked",
    "notes",
]
DASHBOARD_HEADERS = ["key", "value", "description"]
INVENTORY_HEADER_FORMAT = {
    "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
    "backgroundColor": {"red": 0.1, "green": 0.45, "blue": 0.72},
    "horizontalAlignment": "CENTER",
}
DASHBOARD_HEADER_FORMAT = {
    "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
    "backgroundColor": {"red": 0.12, "green": 0.52, "blue": 0.32},
    "horizontalAlignment": "CENTER",
}
ORDER_HEADER_FORMAT = {
    "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
    "backgroundColor": {"red": 0.47, "green": 0.27, "blue": 0.72},
    "horizontalAlignment": "CENTER",
}
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
RECONCILE_INTERVAL_SECONDS = 90


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


def header_format_for(title: str) -> dict:
    if title in {SHEET_1_MONTH, SHEET_6_MONTH}:
        return INVENTORY_HEADER_FORMAT
    if title == DASHBOARD_SHEET:
        return DASHBOARD_HEADER_FORMAT
    return ORDER_HEADER_FORMAT


def get_or_create_worksheet(spreadsheet, title: str, headers: list[str], rows: int = 500):
    try:
        worksheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=title, rows=rows, cols=len(headers))

    first_row = worksheet.row_values(1)
    if first_row[: len(headers)] != headers:
        worksheet.batch_clear([f"A1:{column_letter(max(worksheet.col_count, len(headers)))}1"])
        worksheet.update(range_name=f"A1:{column_letter(len(headers))}1", values=[headers])
    worksheet.format(f"A1:{column_letter(len(headers))}1", header_format_for(title))
    worksheet.freeze(rows=1)
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
    customers = get_or_create_worksheet(spreadsheet, CUSTOMERS_SHEET, CUSTOMER_HEADERS)
    ensure_dashboard_defaults(dashboard)
    normalize_inventory_sheet(one_month, get_dashboard_value(dashboard, "default_password_or_pin", "ChangeMe123"))
    normalize_inventory_sheet(six_month, get_dashboard_value(dashboard, "default_password_or_pin", "ChangeMe123"))
    update_dashboard_summary(dashboard, one_month, six_month, orders)
    worksheet_cache = {
        SHEET_1_MONTH: one_month,
        SHEET_6_MONTH: six_month,
        DASHBOARD_SHEET: dashboard,
        ORDERS_SHEET: orders,
        CUSTOMERS_SHEET: customers,
    }
    schema_ready = True
    plan_cache = (0.0, [])
    return one_month, six_month, dashboard, orders


def row_dicts(worksheet) -> list[dict[str, str]]:
    return worksheet.get_all_records()


def customers_worksheet():
    ensure_sheet_schema()
    return worksheet_cache[CUSTOMERS_SHEET]


def remember_customer(user) -> None:
    if not user:
        return
    worksheet = customers_worksheet()
    user_id = str(user.id)
    timestamp = now_iso()
    try:
        cell = worksheet.find(user_id, in_column=1)
    except gspread.CellNotFound:
        worksheet.append_row(
            [
                user_id,
                getattr(user, "username", "") or "",
                getattr(user, "first_name", "") or "",
                timestamp,
                timestamp,
                "",
                "",
            ],
            value_input_option="USER_ENTERED",
        )
        return

    worksheet.update_cell(cell.row, 2, getattr(user, "username", "") or "")
    worksheet.update_cell(cell.row, 3, getattr(user, "first_name", "") or "")
    worksheet.update_cell(cell.row, 5, timestamp)


def remember_customer_async(user) -> None:
    if not user:
        return

    snapshot = {
        "id": getattr(user, "id", ""),
        "username": getattr(user, "username", "") or "",
        "first_name": getattr(user, "first_name", "") or "",
    }

    class UserSnapshot:
        id = snapshot["id"]
        username = snapshot["username"]
        first_name = snapshot["first_name"]

    def worker() -> None:
        try:
            remember_customer(UserSnapshot)
        except Exception as exc:
            print(f"Customer save failed: {exc}")

    threading.Thread(target=worker, daemon=True).start()


def active_customer_ids() -> list[int]:
    ids = []
    for row in row_dicts(customers_worksheet()):
        if str(row.get("blocked", "")).strip().lower() in {"yes", "true", "1", "blocked"}:
            continue
        raw_id = str(row.get("telegram_user_id", "")).strip()
        if raw_id.isdigit():
            ids.append(int(raw_id))
    return sorted(set(ids))


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


def normalize_inventory_sheet(worksheet, default_pin: str = "") -> None:
    rows = worksheet.get_all_values()
    if len(rows) <= 1:
        return

    batch_updates = []
    for index, row in enumerate(rows[1:], start=2):
        values = row + [""] * (len(INVENTORY_HEADERS) - len(row))
        mail_id = values[0].strip()
        if not mail_id:
            continue

        if not values[1].strip():
            batch_updates.append({"range": f"B{index}", "values": [[now_iso()]]})

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
        mail_id = str(row.get("mail_id", "")).strip()
        purchase_date = str(row.get("purchase_date", "")).strip()
        order_id = str(row.get("order_id", "")).strip()
        if mail_id and not purchase_date and not order_id:
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
                {"range": f"D{row_num}", "values": [[user.username or ""]]},
                {"range": f"E{row_num}", "values": [[str(user.id)]]},
                {"range": f"F{row_num}", "values": [[order_id]]},
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
        if str(row.get("purchase_date", "")).strip():
            continue
        batch_updates.extend(
            [
                {"range": f"D{row_num}:F{row_num}", "values": [["", "", ""]]},
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
                {"range": f"C{row_num}", "values": [[now_iso()]]},
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
    item_ids = ", ".join(str(item.get("mail_id", "")).strip() for item in reserved_items)
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
    item_ids = ", ".join(str(item.get("mail_id", "")).strip() for item in reserved_items)
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
    delivered_values = ", ".join(str(item.get("mail_id", "")).strip() for item in delivered_items)
    orders_ws.update_cell(cell.row, 8, "paid")
    if gateway_txn_id:
        orders_ws.update_cell(cell.row, 9, gateway_txn_id)
    orders_ws.update_cell(cell.row, 12, delivered_values)
    orders_ws.update_cell(cell.row, 14, now_iso())
    update_dashboard_summary(dashboard, one_month, six_month, orders_ws)
    return telegram_user_id


def send_delivery_message(telegram_user_id: int, message: str) -> None:
    if telegram_app and bot_loop:
        asyncio.run_coroutine_threadsafe(
            telegram_app.bot.send_message(chat_id=telegram_user_id, text=message, parse_mode=ParseMode.HTML),
            bot_loop,
        )
        return

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": telegram_user_id, "text": message, "parse_mode": "HTML"},
        timeout=30,
    ).raise_for_status()


def fulfill_paid_order(order_id: str, gateway_txn_id: str = "") -> bool:
    order = order_by_id(order_id)
    if not order:
        return False
    if str(order.get("status", "")).strip().lower() == "paid":
        return True

    delivered_items = mark_reserved_sold(str(order.get("plan_id", "")), order_id)
    telegram_user_id = update_order_paid(order_id, delivered_items, gateway_txn_id)
    if telegram_user_id:
        send_delivery_message(telegram_user_id, format_delivery_message(order, delivered_items))
    return True


def list_user_orders(telegram_user_id: int) -> list[dict[str, str]]:
    _, _, _, orders_ws = ensure_sheet_schema()
    return [
        row
        for row in row_dicts(orders_ws)
        if str(row.get("telegram_user_id", "")).strip() == str(telegram_user_id)
    ]


def reconcile_pending_paid_orders(limit: int = 20) -> int:
    _, _, _, orders_ws = ensure_sheet_schema()
    pending_orders = [
        row
        for row in row_dicts(orders_ws)
        if str(row.get("status", "")).strip().lower() == "pending"
    ][-limit:]

    delivered_count = 0
    for order in pending_orders:
        order_id = str(order.get("order_id", "")).strip()
        if not order_id:
            continue
        try:
            status = check_imb_order_status(order_id)
        except requests.RequestException as exc:
            print(f"Pending reconcile failed for {order_id}: {exc}")
            continue
        if not is_imb_status_paid(status):
            continue
        result = status.get("result") or {}
        gateway_txn_id = str(result.get("utr") or result.get("orderId") or order_id).strip()
        if fulfill_paid_order(order_id, gateway_txn_id):
            delivered_count += 1
    return delivered_count


def update_dashboard_summary(dashboard, one_month, six_month, orders_ws) -> None:
    one_available = len(available_inventory_rows(one_month))
    six_available = len(available_inventory_rows(six_month))
    one_sold = sum(1 for row in row_dicts(one_month) if str(row.get("purchase_date", "")).strip())
    six_sold = sum(1 for row in row_dicts(six_month) if str(row.get("purchase_date", "")).strip())
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
                    f"🛒 {plan.name} | 💰 Rs.{plan.price_inr} | 📦 Stock {plan.stock}",
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
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back:plans")])
    return InlineKeyboardMarkup(rows)


def welcome_message() -> str:
    return (
        "<b>🙏 Namaste! ✨</b>\n"
        "<b>📦 Inventory Store Ready Hai ✅</b>\n\n"
        "<b>🛒 Apna Plan Select Karein 👇</b>"
    )


def plans_message() -> str:
    lines = ["<b>📦 Available Plans ✅</b>", ""]
    for plan in all_plan_info():
        lines.extend(
            [
                f"<b>🛒 {html.escape(plan.name)}</b>",
                f"<b>💰 Amount: Rs.{plan.price_inr}</b>",
                f"<b>📦 Stock: {plan.stock}</b>",
                "",
            ]
        )
    lines.append("<b>🧾 Buy Command: /buy 1m 1 ya /buy 6m 1</b>")
    return "\n".join(lines)


def order_confirmation_message(
    order_id: str,
    plan: PlanInfo,
    quantity: int,
    payment_link_url: str,
) -> str:
    return (
        "<b>🎉 𝗢𝗥𝗗𝗘𝗥 𝗖𝗢𝗡𝗙𝗜𝗥𝗠𝗘𝗗 🎉</b>\n\n"
        "<b>━━━━━━━━━━━━━━━</b>\n"
        "<b>🧾 Order Details</b>\n"
        "<b>━━━━━━━━━━━━━━━</b>\n\n"
        f"<b>🆔 Order ID: <code>{html.escape(order_id)}</code></b>\n"
        f"<b>📦 Plan: {html.escape(plan.name)}</b>\n"
        f"<b>🛒 Quantity: {quantity}</b>\n"
        f"<b>💰 Total Amount: ₹{plan.price_inr * quantity} Only</b>\n\n"
        "<b>━━━━━━━━━━━━━━━</b>\n"
        "<b>💳 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘 𝗬𝗢𝗨𝗥 𝗣𝗔𝗬𝗠𝗘𝗡𝗧</b>\n"
        "<b>━━━━━━━━━━━━━━━</b>\n\n"
        f"<b>🔗 Payment Link:</b>\n{html.escape(payment_link_url)}\n\n"
        "<b>━━━━━━━━━━━━━━━</b>\n"
        "<b>⚡ 𝗔𝘂𝘁𝗼 𝗗𝗲𝗹𝗶𝘃𝗲𝗿𝘆 𝗘𝗻𝗮𝗯𝗹𝗲𝗱 ⚡</b>\n"
        "<b>Payment successful hote hi aapke inventory items isi chat me automatically deliver ho jayenge ✅</b>\n"
        "<b>━━━━━━━━━━━━━━━</b>\n\n"
        "<b>🙏 Thanks for choosing Techsellpro 🚀</b>"
    )


def payment_button_url(payment_data: dict[str, str], payment_link_url: str) -> str:
    for key in ("paytm_link", "paytmLink", "payment_url", "paymentUrl", "payment_link", "paymentLink"):
        value = str(payment_data.get(key) or "").strip()
        if value.startswith(("https://", "http://")):
            return value
    return payment_link_url


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_customer_async(update.effective_user)
    await update.message.reply_text(
        welcome_message(),
        parse_mode=ParseMode.HTML,
        reply_markup=plans_keyboard(),
    )


async def products_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_customer_async(update.effective_user)
    await update.message.reply_text(
        plans_message(),
        parse_mode=ParseMode.HTML,
        reply_markup=plans_keyboard(),
    )


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_customer_async(update.effective_user)
    if len(context.args) < 2:
        await update.message.reply_text("<b>🧾 Format: /buy 1m 2 ya /buy 6m 1</b>", parse_mode=ParseMode.HTML)
        return
    plan_id = context.args[0].lower()
    if plan_id not in PLANS:
        await update.message.reply_text("<b>❌ Plan invalid hai. Use: 1m ya 6m</b>", parse_mode=ParseMode.HTML)
        return
    try:
        quantity = int(context.args[1])
    except ValueError:
        await update.message.reply_text("<b>🔢 Quantity number me bhejein.</b>", parse_mode=ParseMode.HTML)
        return
    await create_order_and_send_payment(update, plan_id, quantity)


async def create_order_and_send_payment(update: Update, plan_id: str, quantity: int) -> None:
    plan = get_plan_info(plan_id)
    if quantity < 1:
        await update.effective_message.reply_text("<b>🔢 Quantity kam se kam 1 honi chahiye.</b>", parse_mode=ParseMode.HTML)
        return
    if quantity > plan.stock:
        await update.effective_message.reply_text(
            f"<b>📦 Stock sirf {plan.stock} bacha hai.</b>",
            parse_mode=ParseMode.HTML,
        )
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
            "<b>⚠️ Payment order create nahi ho paya. Thodi der baad retry karein ya admin ko batayein.</b>",
            parse_mode=ParseMode.HTML,
        )
        print(f"Order error: {exc}")
        return

    if not payment_link_url:
        release_reserved_inventory(plan.plan_id, order_id)
        await update.effective_message.reply_text(
            "<b>⚠️ Gateway ne payment link return nahi kiya. Admin ko batayein.</b>",
            parse_mode=ParseMode.HTML,
        )
        print(f"Payment response without link for {order_id}: {payment_data}")
        return

    pay_now_url = payment_button_url(payment_data, payment_link_url)
    await update.effective_message.reply_text(
        order_confirmation_message(order_id, plan, quantity, payment_link_url),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("💳 Pay Now", url=pay_now_url)]]
        ),
    )


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_customer_async(update.effective_user)
    orders = list_user_orders(update.effective_user.id)
    if not orders:
        await update.message.reply_text("<b>📭 Aapka koi order abhi Sheet me nahi mila.</b>", parse_mode=ParseMode.HTML)
        return

    lines = ["<b>🧾 Your Orders</b>", ""]
    for order in orders[-10:]:
        lines.append(
            f"<b>🆔 {html.escape(str(order.get('order_id')))}</b>\n"
            f"<b>🛒 {html.escape(str(order.get('plan_name')))} x {html.escape(str(order.get('quantity')))}</b>\n"
            f"<b>💰 Rs.{html.escape(str(order.get('amount_inr')))} | 📌 {html.escape(str(order.get('status')))}</b>\n"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


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


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_TELEGRAM_IDS:
        await update.message.reply_text("<b>⛔ Ye admin command hai.</b>", parse_mode=ParseMode.HTML)
        return

    message = " ".join(context.args).strip()
    if not message:
        await update.message.reply_text(
            "<b>📝 Format:</b>\n<code>/broadcast Your message here</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    sent = 0
    failed = 0
    blocked = 0
    for chat_id in active_customer_ids():
        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as exc:
            failed += 1
            if "blocked" in str(exc).lower() or "forbidden" in str(exc).lower():
                blocked += 1

    await update.message.reply_text(
        "<b>📣 Broadcast Complete ✅</b>\n\n"
        f"<b>👥 Total:</b> {sent + failed}\n"
        f"<b>✅ Sent:</b> {sent}\n"
        f"<b>❌ Failed:</b> {failed}\n"
        f"<b>🚫 Blocked:</b> {blocked}",
        parse_mode=ParseMode.HTML,
    )


async def addstock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_TELEGRAM_IDS:
        await update.message.reply_text("<b>⛔ Ye admin command hai.</b>", parse_mode=ParseMode.HTML)
        return
    if not context.args or context.args[0].lower() not in PLANS:
        await update.message.reply_text(
            "<b>📝 Format:</b>\n<code>/addstock 1m</code>\n<code>/addstock 6m</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    plan_id = context.args[0].lower()
    context.user_data["awaiting_stock_plan"] = plan_id
    await update.message.reply_text(
        f"<b>📥 {html.escape(PLANS[plan_id]['name'])} ke mail IDs bhejein.</b>\n\n"
        "<b>Ek line me ek mail ID:</b>\n"
        "<code>mail1@example.com\nmail2@example.com\nmail3@example.com</code>",
        parse_mode=ParseMode.HTML,
    )


async def stock_bulk_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    plan_id = context.user_data.get("awaiting_stock_plan")
    if not plan_id:
        return
    if update.effective_user.id not in ADMIN_TELEGRAM_IDS:
        context.user_data.pop("awaiting_stock_plan", None)
        return

    raw_lines = (update.message.text or "").splitlines()
    mail_ids = []
    seen = set()
    for line in raw_lines:
        value = line.strip()
        if not value or value in seen:
            continue
        mail_ids.append(value)
        seen.add(value)

    if not mail_ids:
        await update.message.reply_text("<b>⚠️ Koi valid mail ID nahi mila.</b>", parse_mode=ParseMode.HTML)
        return

    worksheet = inventory_for_plan(plan_id)
    existing = {str(row.get("mail_id", "")).strip().lower() for row in row_dicts(worksheet)}
    rows = []
    skipped = 0
    timestamp = now_iso()
    for mail_id in mail_ids:
        if mail_id.lower() in existing:
            skipped += 1
            continue
        rows.append([mail_id, timestamp, "", "", "", ""])

    if rows:
        worksheet.append_rows(rows, value_input_option="USER_ENTERED")
        clear_plan_cache()
    context.user_data.pop("awaiting_stock_plan", None)

    await update.message.reply_text(
        f"<b>✅ Stock Added</b>\n\n"
        f"<b>📦 Plan:</b> {html.escape(PLANS[plan_id]['name'])}\n"
        f"<b>➕ Added:</b> {len(rows)}\n"
        f"<b>⏭ Skipped Duplicate:</b> {skipped}",
        parse_mode=ParseMode.HTML,
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    remember_customer_async(query.from_user)

    if data == "back:plans":
        await query.edit_message_text(welcome_message(), parse_mode=ParseMode.HTML, reply_markup=plans_keyboard())
        return

    if data.startswith("plan:"):
        plan_id = data.split(":", 1)[1]
        plan = get_plan_info(plan_id)
        if plan.stock <= 0:
            await query.edit_message_text(
                f"<b>📦 {html.escape(plan.name)} ka stock abhi khatam hai.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=plans_keyboard(),
            )
            return
        await query.edit_message_text(
            f"<b>🛒 {html.escape(plan.name)}</b>\n"
            f"<b>💰 Amount: Rs.{plan.price_inr}</b>\n"
            f"<b>📦 Stock: {plan.stock}</b>\n\n"
            f"<b>🔢 Quantity Select Karein 👇</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=quantity_keyboard(plan_id, plan.stock),
        )
        return

    if data.startswith("qty:"):
        _, plan_id, quantity_text = data.split(":")
        try:
            quantity = int(quantity_text)
        except ValueError:
            await query.edit_message_text("<b>❌ Quantity invalid hai.</b>", parse_mode=ParseMode.HTML)
            return
        await query.edit_message_text("<b>⏳ Order create ho raha hai...</b>", parse_mode=ParseMode.HTML)
        await create_order_and_send_payment(update, plan_id, quantity)


def format_delivery_message(order: dict[str, str], delivered_items: list[dict[str, str]]) -> str:
    ensure_sheet_schema()
    plan_name = str(order.get("plan_name", "Plan"))
    purchase_date = datetime.now().strftime("%d/%m/%Y")
    default_pin = get_dashboard_value(worksheet_cache[DASHBOARD_SHEET], "default_password_or_pin", "ChangeMe123")
    lines = [
        "📦 𝗔𝗖𝗖𝗢𝗨𝗡𝗧 𝗗𝗘𝗧𝗔𝗜𝗟𝗦 📦",
        "",
        "━━━━━━━━━━━━━━━",
        "",
        f"🗓 Plan: {plan_name}",
        "",
        f"📅 Purchase Date: {purchase_date}",
        "",
    ]

    for index, item in enumerate(delivered_items, start=1):
        item_value = str(item.get("mail_id", "")).strip()
        label = "📧 Mail ID" if len(delivered_items) == 1 else f"📧 Mail ID {index}"
        lines.extend(
            [
                f"{label}: {item_value}",
                "",
                f"🔑 Password: {default_pin}",
                "",
            ]
        )

    lines.extend(
        [
            "",
            f"📱 WhatsApp Number: {SUPPORT_WHATSAPP}",
        ]
    )
    return "\n".join(f"<b>{html.escape(line)}</b>" if line else "" for line in lines)


@flask_app.get("/health")
def health():
    return {"ok": True}


@flask_app.get("/payment/thanks")
def payment_thanks():
    order_id = request.args.get("order_id", "").strip()
    safe_order = order_id if order_id else "Processing"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Payment Received</title>
  <style>
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: Arial, Helvetica, sans-serif;
      font-weight: 700;
      background: #f6f8fb;
      color: #16202a;
      display: grid;
      place-items: center;
      padding: 20px;
    }}
    .page {{
      width: 100%;
      max-width: 520px;
      background: #ffffff;
      border: 1px solid #e1e7ef;
      border-radius: 18px;
      padding: 28px 22px;
      text-align: center;
      box-shadow: 0 16px 45px rgba(21, 33, 48, 0.12);
    }}
    .icon {{
      width: 72px;
      height: 72px;
      margin: 0 auto 18px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: #e9f9ef;
      color: #157347;
      font-size: 38px;
      line-height: 1;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 28px;
      line-height: 1.2;
    }}
    p {{
      margin: 10px 0;
      font-size: 16px;
      line-height: 1.55;
      color: #435064;
    }}
    .order {{
      margin: 18px 0;
      padding: 12px;
      border-radius: 12px;
      background: #f1f5f9;
      font-size: 14px;
      color: #283548;
      word-break: break-word;
    }}
    .steps {{
      text-align: left;
      margin: 20px 0 22px;
      padding: 0;
      list-style: none;
    }}
    .steps li {{
      display: flex;
      gap: 10px;
      align-items: flex-start;
      padding: 10px 0;
      border-top: 1px solid #edf1f6;
      color: #2f3b4d;
      line-height: 1.45;
    }}
    .steps li:first-child {{
      border-top: 0;
    }}
    .btn {{
      display: block;
      width: 100%;
      text-decoration: none;
      border-radius: 12px;
      padding: 15px 16px;
      background: #2481cc;
      color: #ffffff;
      font-weight: 700;
      font-size: 16px;
    }}
    .note {{
      margin-top: 14px;
      font-size: 14px;
      color: #16202a;
      background: #fff2bf;
      border: 1px solid #f4d35e;
      border-radius: 12px;
      padding: 12px;
    }}
    .highlight {{
      margin: 18px 0;
      padding: 14px;
      border-radius: 12px;
      background: #e9f9ef;
      border: 1px solid #9de4b6;
      color: #0f5132;
    }}
    @media (max-width: 420px) {{
      .page {{
        padding: 24px 16px;
        border-radius: 16px;
      }}
      h1 {{
        font-size: 24px;
      }}
      p, .btn {{
        font-size: 15px;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <div class="icon">✅</div>
    <h1>Thank You! 🎉</h1>
    <p>Payment receive ho gaya hai. Aapki ID / pass details Telegram bot me automatically mil jayengi.</p>
    <div class="order">🧾 Order ID: <strong>{html.escape(safe_order)}</strong></div>
    <div class="highlight">⏳ Credentials milne main 1-2 minutes ka time lag sakta hai.</div>
    <ul class="steps">
      <li><span>🔍</span><span>Bot payment verify karega.</span></li>
      <li><span>🤖</span><span>Details aapke Telegram chat me send ho jayengi.</span></li>
    </ul>
    <a class="btn" href="https://t.me/Santhot8432_bot">Open Telegram Bot 🚀</a>
    <p class="note">⚠️ Agar message turant na aaye, Telegram bot me /orders check karein.</p>
  </main>
</body>
</html>"""


@flask_app.post("/imb/webhook")
def imb_webhook():
    raw_body = request.get_data()
    content_type = request.headers.get("Content-Type", "")

    payload = request.form.to_dict(flat=True) or (request.get_json(silent=True) or {})
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    status = str(payload.get("status") or result.get("txnStatus") or result.get("status") or "").upper()
    order_id = str(payload.get("order_id") or result.get("orderId") or "").strip()
    gateway_txn_id = str(result.get("utr") or result.get("orderId") or order_id).strip()
    handled = False

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
        handled = fulfill_paid_order(order_id, verified_txn_id)

    if WEBHOOK_FORWARD_STRICT:
        forwarded = forward_to_existing_website(raw_body, content_type)
        if not forwarded:
            return {"ok": False, "error": "website forward failed"}, 502
    else:
        threading.Thread(
            target=forward_to_existing_website,
            args=(raw_body, content_type),
            daemon=True,
        ).start()
    return {"ok": True, "handled": handled}


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


def run_reconcile_worker() -> None:
    while True:
        try:
            delivered = reconcile_pending_paid_orders()
            if delivered:
                print(f"Reconciled and delivered {delivered} paid order(s).")
        except Exception as exc:
            print(f"Pending reconcile worker error: {exc}")
        time.sleep(RECONCILE_INTERVAL_SECONDS)


def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("products", products_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("sync", sync_command))
    app.add_handler(CommandHandler("dashboard", dashboard_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("addstock", addstock_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, stock_bulk_message))
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
            ]
        ),
        bot_loop,
    ).result(timeout=60)
    threading.Thread(target=run_reconcile_worker, daemon=True).start()
    run_flask()


if __name__ == "__main__":
    main()
