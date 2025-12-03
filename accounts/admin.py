from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from accounts.models import CustomUser

# Register your models here.
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'id', 'email', 'fullname', 'role', 'status', 'is_verified', 'created_at')
    search_fields = ('username', 'email', 'fullname', 'company', 'mobilephone', 'tax_id')
    ordering = ('id',)
    list_filter = ('role', 'status', 'is_verified')

    filter_horizontal = ('groups', 'user_permissions',)
    readonly_fields = ('last_login','created_at', 'updated_at')

    fieldsets = (
        ('Account', {'fields': ('email', 'username')}),
        ('Password', {'fields': ('password',)}),
        ('Personal Info', {'fields': ('fullname', 'role', 'parent', 'status', 'company', 'tax_id', 'mobilephone', 'birthdate', 'address', 'note')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_admin', 'is_superuser', 'is_verified')}),
        ('Important dates', {'fields': ('last_login', 'created_at', 'updated_at')}),
    )

    # 新增用戶/修改用戶密碼
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2'),
        }),
    )

admin.site.register(CustomUser, CustomUserAdmin)