import os
from django.db import models

# 產品狀態
class ProductStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "上架"
    INACTIVE = "INACTIVE", "下架"
    ARCHIVED = "ARCHIVED", "封存"

# 產品變體狀態
class VariantStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "上架"
    INACTIVE = "INACTIVE", "下架"
    ARCHIVED = "ARCHIVED", "封存"

# 產品類型
class ProductType(models.TextChoices):
    ESIM = "esim", "eSIM"
    ESIMIMG = "esimimg", "圖庫eSIM"
    RECHARGEABLE = "rechargeable", "充值卡"
    PHYSICAL = "physical", "成品卡"

# 庫存類型
class StockType(models.TextChoices):
    PHYSICAL = "physical", "實體庫存"
    ESIMIMG = "esimimg", "eSIM圖庫庫存"


