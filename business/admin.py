from django.contrib import admin
from django.utils.html import format_html
from business.models import Order, OrderProduct, OrderCoupons, Receipt, ReceiptItem, AccountTopUP, AccountTopUPLog, Expense, Income

# 訂單產品 Inline（在訂單頁面中顯示）
class OrderProductInline(admin.TabularInline):
    model = OrderProduct
    extra = 0
    readonly_fields = ('variant', 'product_code', 'unit_price', 'quantity', 'amount_display', 'created_at')
    fields = ('variant', 'product_code', 'unit_price', 'quantity', 'amount_display')
    can_delete = False
    
    def amount_display(self, obj):
        """顯示小計"""
        if obj.id:
            return f'${obj.amount:,.0f}'
        return '-'
    amount_display.short_description = '小計'

# 訂單
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'account', 'created_by', 'status', 'amount_display', 'total_amount_display', 'payment_type', 'created_at')
    search_fields = ('id', 'account__username', 'account__fullname', 'remark', 'remark_admin')
    list_filter = ('status', 'payment_type', 'order_source', 'created_at')
    ordering = ('-created_at',)
    readonly_fields = ('id', 'amount_display', 'total_amount_display', 'order_products_display', 'created_at', 'updated_at')
    inlines = [OrderProductInline]
    
    fieldsets = (
        ('訂單資訊', {
            'fields': ('id', 'account', 'created_by', 'status', 'payment_type', 'order_source')
        }),
        ('金額資訊', {
            'fields': ('amount_display', 'shipping_fee', 'total_amount_display')
        }),
        ('備註', {
            'fields': ('remark', 'remark_admin')
        }),
        ('Joytel 參數', {
            'fields': ('warehouse', 'order_type', 'reply_type', 'order_code', 'tradeno'),
            'classes': ('collapse',)
        }),
        ('時間資訊', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def amount_display(self, obj):
        """顯示訂單金額（不含運費）"""
        if obj.id:
            return f'${obj.amount:,.0f}'
        return '-'
    amount_display.short_description = '訂單金額'
    
    def total_amount_display(self, obj):
        """顯示訂單總額（含運費）"""
        if obj.id:
            # 先格式化數值，再傳給 format_html
            amount_str = f'{obj.total_amount:,.0f}'
            return format_html(
                '<strong style="color: #417505; font-size: 16px;">${}</strong>',
                amount_str
            )
        return '-'
    total_amount_display.short_description = '訂單總額'
    
    def order_products_display(self, obj):
        """顯示訂單產品列表"""
        if obj.id:
            products = obj.order_products.all()
            if products:
                html = '<table style="width: 100%; border-collapse: collapse;">'
                html += '<tr style="background: #f5f5f5; font-weight: bold;">'
                html += '<th style="padding: 8px; text-align: left;">產品</th>'
                html += '<th style="padding: 8px; text-align: right;">單價</th>'
                html += '<th style="padding: 8px; text-align: right;">數量</th>'
                html += '<th style="padding: 8px; text-align: right;">小計</th>'
                html += '</tr>'
                
                for p in products:
                    html += '<tr style="border-bottom: 1px solid #ddd;">'
                    html += f'<td style="padding: 8px;">{p.variant.name if p.variant else p.product_code}</td>'
                    html += f'<td style="padding: 8px; text-align: right;">${p.unit_price:,.0f}</td>'
                    html += f'<td style="padding: 8px; text-align: right;">{p.quantity}</td>'
                    html += f'<td style="padding: 8px; text-align: right;">${p.amount:,.0f}</td>'
                    html += '</tr>'
                
                html += '</table>'
                return format_html(html)
            return '無產品'
        return '-'
    order_products_display.short_description = '訂單產品'

# 訂單產品
class OrderProductAdmin(admin.ModelAdmin):
    list_display = ('order', 'id', 'variant', 'product_code', 'unit_price', 'quantity', 'amount_display', 'created_at')
    search_fields = ('order__id', 'variant__name', 'product_code')
    list_filter = ('created_at',)
    ordering = ('-created_at',)
    readonly_fields = ('amount_display', 'created_at', 'updated_at')

    fieldsets = (
        ('訂單產品資訊', {
            'fields': ('order', 'variant', 'product_code', 'unit_price', 'quantity', 'used_stocks', 'status', 'amount_display')
        }),
        ('時間資訊', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def amount_display(self, obj):
        """顯示小計"""
        if obj.id:
            return f'${obj.amount:,.0f}'
        return '-'
    amount_display.short_description = '小計'

# 訂單兌換二維碼
class OrderCouponsAdmin(admin.ModelAdmin):
    list_display = ('id', 'sn_pin', 'sn_code', 'product_expire_date', 'qrcode', 'pin1', 'pin2', 'puk1', 'puk2', 'sale_plan_name', 'sale_plan_days', 'created_at')
    search_fields = ('sn_pin', 'sn_code', 'qrcode', 'pin1', 'pin2', 'puk1', 'puk2', 'sale_plan_name', 'sale_plan_days')
    list_filter = ('created_at',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('訂單兌換二維碼', {
            'fields': ('order', 'order_product', 'sn_pin', 'sn_code', 'product_expire_date', 'qrcode', 'pin1', 'pin2', 'puk1', 'puk2', 'sale_plan_name', 'sale_plan_days')
        }),
        ('時間資訊', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# 收據明細
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'receipt_to', 'date', 'receipt_type', 'remark', 'created_at')
    search_fields = ('receipt_number', 'receipt_to', 'remark')
    list_filter = ('receipt_type', 'date', 'created_at')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('收據資訊', {
            'fields': ('receipt_number', 'receipt_to', 'date', 'receipt_type', 'remark')
        }),
        ('時間資訊', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    

# 收據產品
class ReceiptItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'receipt', 'order_product', 'product_name', 'product_code', 'quantity', 'unit_price', 'subtotal', 'created_at')
    search_fields = ('receipt__receipt_number', 'receipt__receipt_to', 'product_name', 'product_code', 'remark')
    list_filter = ('created_at',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('收據明細資訊', {
            'fields': ('receipt', 'order_product', 'product_name', 'product_code', 'quantity', 'unit_price')
        }),
        ('小計', {
            'fields': ('subtotal',)
        }),
        ('時間資訊', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def subtotal(self, obj):
        """顯示小計"""
        if obj.id:
            return f'${obj.subtotal:,.0f}'
        return '-'


# 儲值
class AccountTopUPAdmin(admin.ModelAdmin):
    list_display = ('account', 'balance_display', 'remark', 'created_at')
    search_fields = ('account__username', 'account__fullname', 'remark')
    list_filter = ('created_at',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('儲值資訊', {
            'fields': ('account', 'balance', 'remark')
        }),
        ('時間資訊', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def balance_display(self, obj):
        """顯示餘額"""
        return f'${obj.balance:,.0f}'
    balance_display.short_description = '剩餘金額'

# 儲值異動紀錄 Inline
class AccountTopUPLogInline(admin.TabularInline):
    model = AccountTopUPLog
    extra = 0
    readonly_fields = ('amount', 'balance_before', 'balance_after', 'order', 'log_type', 'is_confirmed', 'remark', 'created_at')
    fields = ('amount', 'balance_before', 'balance_after', 'log_type', 'is_confirmed', 'order', 'remark')
    can_delete = False

# 儲值異動紀錄
class AccountTopUPLogAdmin(admin.ModelAdmin):
    list_display = ('topup', 'amount_display', 'balance_before_display', 'balance_after_display', 'log_type', 'order', 'is_confirmed', 'created_at')
    search_fields = ('topup__account__username', 'topup__account__fullname', 'remark', 'order__id')
    list_filter = ('log_type', 'is_confirmed', 'created_at')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('儲值異動資訊', {
            'fields': ('topup', 'amount', 'balance_before', 'balance_after', 'log_type', 'is_confirmed')
        }),
        ('相關訂單', {
            'fields': ('order',)
        }),
        ('備註', {
            'fields': ('remark',)
        }),
        ('時間資訊', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def amount_display(self, obj):
        """顯示異動金額"""
        # 先格式化數值，再傳給 format_html
        amount_str = f'{abs(obj.amount):,.0f}'
        if obj.amount >= 0:
            return format_html('<span style="color: green;">+${}</span>', amount_str)
        return format_html('<span style="color: red;">-${}</span>', amount_str)
    amount_display.short_description = '異動金額'
    
    def balance_before_display(self, obj):
        """顯示異動前金額"""
        return f'${obj.balance_before:,.0f}'
    balance_before_display.short_description = '異動前金額'
    
    def balance_after_display(self, obj):
        """顯示異動後金額"""
        return f'${obj.balance_after:,.0f}'
    balance_after_display.short_description = '異動後金額'

# 支出
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'date', 'amount_display', 'item', 'remark', 'created_at')
    search_fields = ('name', 'remark')
    list_filter = ('item', 'date', 'created_at')
    ordering = ('-date', '-created_at')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('支出資訊', {
            'fields': ('name', 'date', 'amount', 'item', 'remark')
        }),
        ('時間資訊', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def amount_display(self, obj):
        """顯示支出金額"""
        return f'${obj.amount:,.0f}'
    amount_display.short_description = '支出金額'

# 收入
class IncomeAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'date', 'amount_display', 'remark', 'created_at')
    search_fields = ('name', 'remark')
    list_filter = ('date', 'created_at')
    ordering = ('-date', '-created_at')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('收入資訊', {
            'fields': ('name', 'date', 'amount', 'remark')
        }),
        ('時間資訊', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def amount_display(self, obj):
        """顯示收入金額"""
        # 先格式化數值，再傳給 format_html
        amount_str = f'{obj.amount:,.0f}'
        return format_html('<span style="color: green;">${}</span>', amount_str)
    amount_display.short_description = '收入金額'

admin.site.register(OrderProduct, OrderProductAdmin)
admin.site.register(Order, OrderAdmin)
admin.site.register(OrderCoupons, OrderCouponsAdmin)
admin.site.register(Receipt, ReceiptAdmin)
admin.site.register(ReceiptItem, ReceiptItemAdmin)
admin.site.register(AccountTopUP, AccountTopUPAdmin)
admin.site.register(AccountTopUPLog, AccountTopUPLogAdmin)
admin.site.register(Expense, ExpenseAdmin)
admin.site.register(Income, IncomeAdmin)