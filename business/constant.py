import os
from django.db import models

CUSTOM_CODE = os.getenv('CUSTOM_CODE', '10052-2')
CUSTOM_AUTH = os.getenv('CUSTOM_AUTH', '38005A99cF')

# DIYSIM API 設定
DIYSIM_BASE_URL = os.getenv('DIYSIM_BASE_URL', 'https://diysim.com.hk')
DIYSIM_ACCESS_KEY = os.getenv('DIYSIM_ACCESS_KEY', 'f89d7e1d28caa76251f4280d6a256dbc')
DIYSIM_ACCESS_SECRET = os.getenv('DIYSIM_ACCESS_SECRET', '9506bbff6848b52a2db3158de406166e')
RSP_APP_ID = os.getenv('RSP_APP_ID', 'EYtUrerv38X6')
RSP_APP_SECRET = os.getenv('RSP_AP_SECRET', '74140F7B981446DE968C473477ECE56F')

# JOYTEL API 設定
# BASE_URL = "https://api.joytelshop.com/customerApi/" # For server outside China
BASE_URL = "https://api.joytelshop.net/customerApi/"  # For server outside China
# WAREHOUSE_BASE_URL = "https://api.joytel.vip/joyRechargeApi/"
WAREHOUSE_BASE_URL = "https://api.joytelshop.com/joyRechargeApi/" # For server outside China
RSP_API_BASE_URL = "https://esim.joytelecom.com/openapi/"
SUBMIT_ORDER_TYPE = 3
SUBMIT_ORDER_REPLY_TYPE = 1
SITE_HOST = "https://db3c.net"
WAREHOUSE = "上海仓库"

# 訂單狀態
class OrderStatus(models.TextChoices):
    HOLDING = "HOLDING", "保留中"
    PENDING = "PENDING", "待處理"
    WAIT = "WAIT", "待付款"
    PAID = "PAID", "已付款"
    WAIT_SHIP = "WAIT_SHIP", "待發貨"  # FAMI、FAMIC2C 300, UNIMART 300, HILIFE、HILIFEC2C 300, TCAT 300, POST 320
    SHIPPING = "SHIPPING", "已發貨"  # FAMI、FAMIC2C 3032, UNIMARTC2C 2068, HILIFE、HILIFEC2C 3006, TCAT 3006, POST 3301
    WAIT_PICKUP = "WAIT_PICKUP", "等待取貨"  # FAMI、FAMIC2C 3018, UNIMARTC2C 2073, HILIFE、HILIFEC2C 2073, TCAT 3003, POST 3308
    DONE = "DONE", "已完成"  # FAMI、FAMIC2C 3022, UNIMARTC2C 2067, HILIFE、HILIFEC2C 2067, TCAT 3016, POST 3309
    CANCELLED = "CANCELLED", "已取消"

# 支付類型
class PaymentType(models.TextChoices):
    # ECPAY = "ECPAY", "ECPAY"
    # LINEPAY = "LINEPAY", "LINEPAY"
    # JKPAY = "JKPAY", "JKPAY"
    TOPUP = "TOPUP", "儲值"
    CASH = "CASH", "現金"
    DIRECT_BANK_TRANSFER = "DIRECT_BANK_TRANSFER", "銀行轉帳"

# 訂單來源
class OrderSource(models.TextChoices):
    ERP = "ERP", "ERP系統"
    SHOPEE = "SHOPEE", "蝦皮商城"
    COUPANG = "COUPANG", "酷澎"
    WEBSITE = "WEBSITE", "官網"
    LINE = "LINE", "LINE"
    HANDOVER = "HANDOVER", "面交"
    PEER = "PEER", "同業"
    OTHER = "OTHER", "其他"

# 訂單產品狀態
class OrderProductStatus(models.TextChoices):
    NORMAL = "NORMAL", "正常"
    FAILED = "FAILED", "失敗"
    CANCELED = "CANCELED", "已取消"
    RETURNED = "RETURNED", "已退貨"
    DAMAGED = "DAMAGED", "損壞"

# 收據類型 ReceiptType
class ReceiptType(models.TextChoices):
    ORDER = "ORDER", "訂單"
    MANUAL = "MANUAL", "手動"

# 儲值類型 TopupType
class TopupType(models.TextChoices):
    DEPOSIT = "DEPOSIT", "儲值"
    CONSUMPTION = "CONSUMPTION", "消費"
    REFUND = "REFUND", "退款"

# 收入項目 Income Item
class IncomeItem(models.TextChoices):
    SALES = "SALES", "銷售收入"
    SERVICE_FEE = "SERVICE_FEE", "服務費收入"
    INVESTMENT = "INVESTMENT", "投資收入"
    RENT = "RENT", "租金收入"
    OTHER = "OTHER", "其他"

# 支出項目 Expense Item
class ExpenseItem(models.TextChoices):
    TAX = "TAX", "稅務"
    SALARY = "SALARY", "薪金"
    RENT = "RENT", "租金"
    TRAVEL = "TRAVEL", "旅費"
    ADVERTISEMENT = "ADVERTISEMENT", "廣告宣傳"
    OFFICE_SUPPLIES = "OFFICE_SUPPLIES", "辦公用品"
    UTILITY_BILLS = "UTILITY_BILLS", "水電費"
    BONUSES = "BONUSES", "獎金"
    SERVICE_FEE = "SERVICE_FEE", "勞務費"
    OTHER = "OTHER", "其他"