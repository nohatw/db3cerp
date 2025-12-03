import os
import qrcode
from django.core.exceptions import ValidationError
from django.db import models
from products.models import Supplier, Category, Product, Variant, Stock
from business.constant import OrderStatus, PaymentType, OrderSource, OrderProductStatus, ReceiptType, TopupType, IncomeItem, ExpenseItem, CUSTOM_CODE, CUSTOM_AUTH, SUBMIT_ORDER_TYPE, SUBMIT_ORDER_REPLY_TYPE, \
    SUBMIT_ORDER_REPLY_TYPE
from business.utils import gen_order_tid, get_timestamp_by_datetime, sha1_encrypt
from accounts.models import CustomUser
from products.constant import ProductType
from django.utils import timezone


# 訂單
class Order(models.Model):
    id = models.CharField(
        max_length=255, 
        primary_key=True, 
        unique=True, 
        default=gen_order_tid, 
        verbose_name="訂單編號"
    )
    account = models.ForeignKey(
        'accounts.CustomUser', 
        on_delete=models.CASCADE, 
        related_name='orders', 
        verbose_name="訂單帳號"
    )
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_orders',
        verbose_name="建立人"
    )
    warehouse = models.CharField(max_length=255, blank=True) # Joytel 庫存編號
    order_type = models.IntegerField(default=SUBMIT_ORDER_TYPE) # Joytel 參數
    reply_type = models.IntegerField(default=SUBMIT_ORDER_REPLY_TYPE) # Joytel 參數
    order_code = models.CharField(
        max_length=255, 
        null=True, 
        verbose_name="Joytel Order Code") # Joytel 參數
    tradeno = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        verbose_name="Payment Trade No") # Joytel 參數
    shipping_fee = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        null=True, 
        blank=True, 
        default=0,
        verbose_name="運費")
    payment_type = models.CharField(
        max_length=50, 
        choices=PaymentType.choices, 
        default=PaymentType.TOPUP, 
        verbose_name="支付類型")
    order_source = models.CharField(
        max_length=50,
        choices=OrderSource.choices,
        null=True,
        blank=True,
        verbose_name="訂單來源")
    status = models.CharField(
        max_length=20, 
        choices=OrderStatus.choices, 
        default=OrderStatus.PENDING, 
        verbose_name="訂單狀態")
    remark = models.TextField(blank=True, verbose_name="訂單備註")
    remark_admin = models.TextField(blank=True, verbose_name="管理員備註")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # class Meta:
    #     ordering = ['-created_at']

    def __str__(self):
        return self.id

    # @property
    # def auto_graph(self):
    #     joytel_products = self.joytel_products
    #     origin_str = f"{CUSTOM_CODE}{CUSTOM_AUTH}{self.warehouse}{self.order_type}{self.order_tid}{self.user.fullname}{self.user.mobilephone}{self.order_time_stamp}{''.join([f'{p.variant.product_code}{p.quantity}' for p in joytel_products])}"
    #     return sha1_encrypt(origin_str)

    @property
    def order_tid(self):
        return f"{CUSTOM_CODE}{self.id}"

    @property
    def order_products(self):
        return self.order_products.all()
    
    @property
    def esimimg_products(self):
        # 圖庫式
        return self.filter_product_by_type(ProductType.ESIMIMG)
    
    @property
    def rechargeable_products(self):
        # 充值卡
        return self.filter_product_by_type(ProductType.RECHARGEABLE)

    @property
    def physical_products(self):
        # 實體卡
        return self.filter_product_by_type(ProductType.PHYSICAL)

    @property
    def joytel_products(self):
        pass
    
    @property
    def diysim_products(self):
        pass

    def filter_product_by_type(self, product_type):
        return self.order_products.filter(variant__product__product_type=product_type)

    @property
    def amount(self):
        # 訂單總額
        return sum([p.unit_price * p.quantity for p in self.order_products.all()])

    @property
    def total_amount(self):
        # 訂單總額(含運費)
        shipping = self.shipping_fee if self.shipping_fee is not None else 0
        return self.amount + shipping

    @property
    def order_time_stamp(self):
        return get_timestamp_by_datetime(self.created_at)

# 訂單產品
class OrderProduct(models.Model):
    id = models.AutoField(primary_key=True)
    order = models.ForeignKey(
        'Order', 
        on_delete=models.CASCADE, 
        related_name='order_products', 
        verbose_name="訂單"
    )
    variant = models.ForeignKey(
        'products.Variant', 
        on_delete=models.SET_NULL, 
        null=True, 
        verbose_name="產品變體"
    ) # 引用實際產品
    product_code = models.CharField(
        max_length=255, 
        blank=True, null=True, 
        verbose_name="產品代碼"
    ) # 實際產品代碼(快照代碼)
    unit_price = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        verbose_name='訂單產品價格'
    ) # 訂單時的價格(快照價格)
    quantity = models.IntegerField(verbose_name='訂單產品數量')
    used_stocks = models.JSONField(
        default=list,
        blank=True,
        verbose_name='使用的庫存記錄'
    ) # 使用 JSON 格式儲存：[{'stock_id': 1, 'quantity': 5}, {'stock_id': 2, 'quantity': 3}]
    status = models.CharField(
        max_length=20, 
        choices=OrderProductStatus.choices,
        default=OrderProductStatus.NORMAL,
        verbose_name='訂單產品狀態'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
    
    @property
    def amount(self):
        # 訂單產品總額
        return self.unit_price * self.quantity
    
# 訂單兌換二維碼
class OrderCoupons(models.Model):
    id = models.AutoField(primary_key=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, null=True, blank=True)
    order_product = models.ForeignKey(
        'OrderProduct', 
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='coupons',
        verbose_name="關聯訂單產品"
    )
    sn_pin = models.CharField(max_length=255, null=True, blank=True)
    sn_code = models.CharField(max_length=255, null=True, blank=True)
    product_expire_date = models.DateTimeField(null=True, blank=True, verbose_name="產品過期時間")
    # product = models.ForeignKey('products.Variant', on_delete=models.CASCADE)
    trans_id = models.CharField(max_length=255, null=True, blank=True)
    qrcode = models.CharField(max_length=255, null=True, blank=True)
    pin1 = models.CharField(max_length=255, null=True, blank=True)
    pin2 = models.CharField(max_length=255, null=True, blank=True)
    puk1 = models.CharField(max_length=255, null=True, blank=True)
    puk2 = models.CharField(max_length=255, null=True, blank=True)
    sale_plan_name = models.CharField(max_length=255, null=True, blank=True)
    sale_plan_days = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)


# 收據
class Receipt(models.Model):
    """
    收據主表
    
    功能：
    1. 記錄收據基本資訊（編號、抬頭、日期等）
    2. 可關聯訂單（如果是訂單產生的收據）
    3. 可手動建立（不關聯訂單，用於其他收入）
    """
    id = models.AutoField(primary_key=True)
    order = models.ForeignKey(
        'Order',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name='receipts',
        verbose_name="關聯訂單"
    )
    receipt_number = models.CharField(
        max_length=255,
        unique=True,
        verbose_name="收據編號"
    )  # 例如：R20251118001
    receipt_to = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="收據抬頭"
    )
    taxid = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="統一編號"
    )
    date = models.DateField(
        verbose_name="收據日期"
    )
    receipt_type = models.CharField(
        max_length=20,
        choices=ReceiptType.choices,
        default=ReceiptType.ORDER,
        verbose_name='收據類型',
        help_text='訂單收據或手動建立'
    )
    remark = models.TextField(
        blank=True,
        verbose_name="備註"
    )
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_receipts',
        verbose_name="建立人"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name = "收據"
        verbose_name_plural = "收據"
    
    def __str__(self):
        return f"{self.receipt_number} - {self.receipt_to or '（無抬頭）'}"
    
    @property
    def total_amount(self):
        """收據總金額"""
        return sum(item.subtotal for item in self.items.all())
    
    @property
    def item_count(self):
        """收據項目數"""
        return self.items.count()
    
    def generate_receipt_number(self):
        """
        自動生成收據編號
        格式：R + YYYYMMDD + 流水號（3位）
        例如：R20251118001
        """
        from django.utils import timezone
        from datetime import datetime
        
        today = timezone.now().date()
        date_str = today.strftime('%Y%m%d')
        
        # 查詢今日最後一筆收據編號
        last_receipt = Receipt.objects.filter(
            receipt_number__startswith=f'R{date_str}'
        ).order_by('-receipt_number').first()
        
        if last_receipt:
            # 取得最後的流水號並 +1
            last_number = int(last_receipt.receipt_number[-3:])
            new_number = last_number + 1
        else:
            new_number = 1
        
        return f'R{date_str}{new_number:03d}'
    
    def save(self, *args, **kwargs):
        """
        儲存前自動生成收據編號（如果沒有）
        """
        if not self.receipt_number:
            from django.utils import timezone
            from django.db.models import Max
            
            # 獲取今天的日期
            today = timezone.now().date()
            date_str = today.strftime('%Y%m%d')
            
            # 查找今天最大的流水號
            max_receipt = Receipt.objects.filter(
                receipt_number__startswith=f'R{date_str}'
            ).aggregate(
                max_number=Max('receipt_number')
            )['max_number']
            
            if max_receipt:
                # 提取流水號並加 1
                last_seq = int(max_receipt[-3:])
                new_seq = last_seq + 1
            else:
                new_seq = 1
            
            # 生成新的收據編號
            self.receipt_number = f'R{date_str}{new_seq:03d}'
        
        super().save(*args, **kwargs)


# 收據明細
class ReceiptItem(models.Model):
    """
    收據明細
    
    功能：
    1. 記錄收據中的每一筆產品明細
    2. 可關聯訂單產品（如果是訂單產生的收據）
    3. 可手動填入（如果是手動建立的收據）
    """
    id = models.AutoField(primary_key=True)
    receipt = models.ForeignKey(
        'Receipt',
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="收據"
    )
    order_product = models.ForeignKey(
        'OrderProduct',
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='receipt_items',
        verbose_name="關聯訂單產品"
    )
    product_name = models.CharField(
        max_length=255,
        verbose_name="產品名稱"
    )
    product_code = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="產品代碼"
    )
    quantity = models.IntegerField(
        verbose_name="數量"
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        verbose_name="單價"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']
        verbose_name = "收據明細"
        verbose_name_plural = "收據明細"
    
    def __str__(self):
        return f"{self.product_name} x {self.quantity}"
    
    @property
    def subtotal(self):
        """小計"""
        return self.quantity * self.unit_price


# 儲值 ACCOUNT TOPUP
class AccountTopUP(models.Model):
    """
    客戶儲值資料
    """
    account = models.ForeignKey(
        'accounts.CustomUser', 
        on_delete=models.CASCADE, 
        related_name='topups', 
        verbose_name="用戶"
    )
    balance = models.DecimalField(
        max_digits=10, 
        decimal_places=0,
        verbose_name='剩餘金額'
    )
    remark = models.TextField(null=True, blank=True, verbose_name='備註')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "topup"
        verbose_name_plural = "topups"
        ordering = ['-created_at']

    def __str__(self):
        return f" {self.account} - 剩餘金額: {self.balance}"

# 儲值異動紀錄 TOPUP LOG
class AccountTopUPLog(models.Model):
    """
    客戶儲值金額異動紀錄，記錄每一筆消費或儲值的變更
    """
    topup = models.ForeignKey(
        'AccountTopUP', 
        on_delete=models.CASCADE, 
        related_name='logs', 
        verbose_name="儲值"
    )
    amount = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        verbose_name='金額'
    )
    balance_before = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        verbose_name='異動前金額'
    )
    balance_after = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        verbose_name='異動後金額'
    )
    order = models.ForeignKey(
        'Order', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='topup_logs', 
        verbose_name="相關訂單"
    )
    log_type = models.CharField(
        max_length=20, 
        choices=TopupType.choices, 
        default=TopupType.DEPOSIT, 
        verbose_name='異動類型'
    )
    is_confirmed = models.BooleanField(
        default=False, 
        verbose_name='已確認'
    )
    remark = models.TextField(null=True, blank=True, verbose_name='備註')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "topup log"
        verbose_name_plural = "topup logs"
        ordering = ['-created_at']

    def __str__(self):
        return f" {self.topup.account.fullname} - 異動金額: {self.amount}"

# 支出 Expense
class Expense(models.Model):
    name = models.CharField(max_length=100, verbose_name='名稱')
    date = models.DateField(
        null=True, 
        blank=True, 
        verbose_name='日期'
    )
    amount = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        verbose_name='支出金額'
    ) 
    item = models.CharField(
        max_length=20, 
        choices=ExpenseItem.choices, 
        default=ExpenseItem.OTHER, 
        verbose_name='支出項目'
    )
    remark = models.TextField(null=True, blank=True, verbose_name='備註')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "expense"
        verbose_name_plural = "expenses"
        ordering = ['-created_at']

# 收入 Income
class Income(models.Model):
    name = models.CharField(max_length=100, verbose_name='名稱')
    date = models.DateField(
        null=True, blank=True, 
        verbose_name='日期'
    )
    amount = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        verbose_name='收入金額'
    )
    item = models.CharField(
        max_length=20, 
        choices=IncomeItem.choices, 
        default=IncomeItem.OTHER, 
        verbose_name='收入項目'
    )
    remark = models.TextField(null=True, blank=True, verbose_name='備註')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'income'
        verbose_name_plural = 'income'
        ordering = ['-created_at']