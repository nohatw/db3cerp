from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import AbstractUser, BaseUserManager, PermissionsMixin, Group, Permission
from accounts.constant import AccountStatus, AccountRole

# 用戶管理器
class CustomUserManager(BaseUserManager):
    def create_user(self, email, username=None, password=None, **extra_fields):
        """
        Create and return a regular user with an email and password.
        """
        if not email:
            raise ValueError('The Email field must be set')
        if not username:
            username = email.split('@')[0]  # Use email as default username if not provided
        
        # 確保 username 是唯一的
        base_username = username
        counter = 1
        while self.model.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        email = self.normalize_email(email)
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, username, password=None, **extra_fields):
        """
        Create and return a superuser with an email and password.
        """
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_admin', True)
        extra_fields.setdefault('is_verified', True)
        extra_fields.setdefault('is_superuser', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        username = extra_fields.get('username', email.split('@')[0])  # Use email as default username if not provided
        return self.create_user(email=email, username=username, password=password, **extra_fields)

# 自定義用戶模型
class CustomUser(AbstractUser):
    username = models.CharField(max_length=255, unique=True) # username as a defult login field
    fullname = models.CharField(max_length=255, blank=True, null=True, verbose_name='姓名', help_text='姓名')
    role = models.CharField(max_length=20, choices=AccountRole.choices, default=AccountRole.DISTRIBUTOR, verbose_name='用戶角色', help_text='用戶角色')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children', verbose_name='上層用戶', help_text='上層用戶')
    # on_delete=SET_NULL：如果上層被刪除，下層 parent 設為 None，保留用戶
    status = models.CharField(max_length=20, choices=AccountStatus.choices, default=AccountStatus.ACTIVE, verbose_name='用戶狀態', help_text='用戶狀態')
    company = models.CharField(max_length=200, blank=True, null=True, verbose_name='公司名稱', help_text='公司名稱')
    tax_id = models.CharField(max_length=20, blank=True, null=True, verbose_name='統一編號')
    email = models.EmailField(unique=True, verbose_name='電子郵件', help_text='電子郵件')
    mobilephone = models.CharField(unique=True, blank=True, null=True, max_length=20, verbose_name='手機號碼')
    birthdate = models.DateField(null=True, blank=True, verbose_name='生日')
    address = models.TextField(max_length=255, blank=True, null=True, verbose_name='地址')
    note = models.TextField(max_length=500, blank=True, null=True, verbose_name='備註')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_verified = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)

    groups = models.ManyToManyField(
        Group,
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.',
        related_name="customuser_groups",  # Unique related_name for groups
        related_query_name="customuser",
    )
    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name="customuser_permissions",  # Unique related_name for user_permissions
        related_query_name="customuser",
    )

    objects = CustomUserManager()
    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email' # email as a defult login field
    REQUIRED_FIELDS = ['username'] # 這個一定要有，不然會報錯

    def __str__(self):
        return f"ID:{self.id} - 帳號：{self.username} - 姓名：{self.fullname}"
    
    class Meta:
        verbose_name = _('account')
        verbose_name_plural = _('accounts')
        ordering = ['id']

