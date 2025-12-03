import os
from django.db import models

# 用戶狀態
class AccountStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "上架"
    INACTIVE = "INACTIVE", "下架"
    ARCHIVED = "ARCHIVED", "封存"

# 用戶角色 
class AccountRole(models.TextChoices):
    HEADQUARTER = "HEADQUARTER", "總公司"
    AGENT = "AGENT", "代理商"
    DISTRIBUTOR = "DISTRIBUTOR", "分銷商"
    PEER = "PEER", "同業"
    USER = "USER", "用戶"
