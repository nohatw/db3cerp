from django.db import models
from products.constant import ProductStatus, VariantStatus, ProductType
from accounts.models import CustomUser as User
import os

# 自定義上傳路徑函數
def stock_qr_image_path(instance, filename):
    """
    根據產品類型和 SKU 動態生成圖片存儲路徑
    
    對於 ESIMIMG:
        media/esimimg/{sku}/{filename}
    """
    if instance.product and instance.product.product_type == ProductType.ESIMIMG:
        # 使用 variant 的 sku 作為資料夾名稱
        sku = instance.product.sku or 'default'
        # 移除 SKU 中的特殊字元，避免路徑問題
        sku = "".join(c for c in sku if c.isalnum() or c in ('-', '_'))
        return f'esimimg/{sku}/{filename}'

# 供應商
class Supplier(models.Model):
    name = models.CharField(max_length=100, verbose_name="供應商名稱")
    description = models.TextField(blank=True, verbose_name="供應商描述")
    supplier_code = models.CharField(max_length=50, unique=True, verbose_name="供應商代碼")
    sort_order = models.IntegerField(default=0)  # 排序欄位
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = [id]
        verbose_name = "supplier"
        verbose_name_plural = "suppliers"

    def __str__(self):
        return self.name + ' - ' + self.supplier_code

# 產品分類
class Category(models.Model):
    name = models.CharField(max_length=100, verbose_name="分類名稱")
    description = models.TextField(blank=True, verbose_name="分類描述")
    sort_order = models.IntegerField(default=0)  # 排序欄位
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "category"
        verbose_name_plural = "categories"
        ordering = ['sort_order']

    def __str__(self):
        return self.name

# 產品模型
class Product(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=200, verbose_name="產品名稱")
    description = models.TextField(blank=True, verbose_name="產品描述")
    category = models.ForeignKey(
        'Category', 
        on_delete=models.CASCADE, 
        related_name='products', 
        verbose_name="產品分類"
    )
    status = models.CharField(
        max_length=20, 
        choices=ProductStatus.choices, 
        default=ProductStatus.INACTIVE, 
        verbose_name="產品狀態"
    )
    sort_order = models.IntegerField(default=0)  # 排序欄位
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order']
        verbose_name = "product"
        verbose_name_plural = "products"

    def __str__(self):
        return self.name

# 產品變體模型
class Variant(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=200, verbose_name="產品變體名稱")
    description = models.TextField(blank=True, verbose_name="變體描述")
    status = models.CharField(
        max_length=20, 
        choices=VariantStatus.choices, 
        default=VariantStatus.ACTIVE, 
        verbose_name="產品變體狀態"
    )
    product_type = models.CharField(
        max_length=20, 
        choices=ProductType.choices, 
        default=ProductType.ESIM, 
        verbose_name="產品類型"
    )
    product = models.ForeignKey(
        'Product', 
        on_delete=models.CASCADE, 
        related_name='variants', 
        verbose_name="產品"
    )
    supplier = models.ForeignKey(
        'Supplier', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='variants', 
        verbose_name="供應商"
    )
    product_code = models.CharField(max_length=255, blank=True) # 產品代碼
    sku = models.CharField(max_length=255, blank=True, verbose_name="SKU")
    days = models.CharField(max_length=100, verbose_name="方案天數")  # e.g., '1-3 天', '3-5 天', '5-7 天', '7-10 天', '10-14 天', '14-20 天', '20-30 天', '30-60 天', '60-90 天', '90-120 天'
    data_amount = models.CharField(max_length=50, verbose_name='方案規格')  # e.g., '5G', '10G', 'Unlimited'
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        null=True, blank=True, 
        verbose_name="一般價"
    ) # 一般價
    price_sales = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        null=True, 
        blank=True, 
        verbose_name="一般特價"
    ) # 一般特價
    price_agent = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        null=True, blank=True, 
        verbose_name="代理商拿貨價"
    ) # 代理商拿貨價
    price_sales_agent = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        null=True, 
        blank=True, 
        verbose_name="代理商拿貨特價"
    ) # 代理商拿貨特價
    price_peer = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        null=True, blank=True,
        verbose_name="同業價"
    ) # 同業價
    price_sales_peer = models.DecimalField(
        max_digits=10, 
        decimal_places=0, 
        null=True, 
        blank=True, 
        verbose_name="同業特價"
    )# 同業特價
    sort_order = models.IntegerField(default=0)  # 排序欄位
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order']
        verbose_name = "variant"
        verbose_name_plural = "variants"
    
    def __str__(self):
        return f"{self.product.name} - {self.name}"


# 經銷價格：讓每個 AGENT 都能自訂給自己下線 DISTRIBUTOR 的價格
class AgentDistributorPricing(models.Model):
    variant = models.ForeignKey(Variant, on_delete=models.CASCADE, related_name='agent_pricings')
    agent = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'role': 'AGENT'})
    
    price_distr = models.DecimalField(max_digits=10, decimal_places=0, verbose_name="經銷價格") # 經銷價格
    price_sales_distr = models.DecimalField(max_digits=10, decimal_places=0, blank=True, null=True, verbose_name="經銷特價") # 經銷特價
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('variant', 'agent')  # 一個 AGENT 對一個 Variant 只能設一次價格
        verbose_name_plural = "代理商自訂經銷價格"
    
    def __str__(self):
        return f"{self.agent} → {self.variant} (經銷價: {self.price_distr})"


# 產品庫存
class Stock(models.Model):
    name = models.CharField(max_length=200, verbose_name="庫存名稱")
    description = models.TextField(blank=True, verbose_name="庫存描述")
    product = models.ForeignKey('Variant', on_delete=models.CASCADE, related_name='stocks', verbose_name="產品")
    code = models.CharField(max_length=255, blank=True, null=True)
    qr_img = models.ImageField(
        upload_to=stock_qr_image_path,
        blank=True, 
        null=True, 
        verbose_name='二維碼圖片'
    )
    initial_quantity = models.IntegerField(default=0, verbose_name="初始庫存數量")
    quantity = models.IntegerField(default=0, verbose_name="庫存數量")
    expire_date = models.DateTimeField(null=True, blank=True, verbose_name="過期時間")
    is_used = models.BooleanField(default=False, verbose_name="是否已使用")
    # related_order = models.ForeignKey(
    #     'business.Order',
    #     on_delete=models.SET_NULL,
    #     null=True,
    #     blank=True,
    #     related_name='related_stocks',
    #     verbose_name='關聯訂單'
    # )
    exchange_time = models.DateTimeField(null=True, blank=True, verbose_name="兌換時間")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "stock"
        verbose_name_plural = "stocks"
        indexes = [
            models.Index(fields=['product', 'is_used', 'quantity']),  # 查詢可用庫存
            models.Index(fields=['code']),  # 根據 code 搜尋
            models.Index(fields=['expire_date']),  # 過期時間排序
        ]

    # 獲取圖片存儲資料夾
    def get_image_folder(self):
        """返回該庫存圖片應該存儲的資料夾路徑"""
        if self.product and self.product.product_type == ProductType.ESIMIMG:
            sku = self.product.sku or 'default'
            sku = "".join(c for c in sku if c.isalnum() or c in ('-', '_'))
            return f'esimimg/{sku}/'
        return 'stocks/qr_images/'

    def __str__(self):
        return f"{self.product.name} - {self.name} (Qty: {self.quantity})"

