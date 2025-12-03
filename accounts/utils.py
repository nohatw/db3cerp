from accounts.constant import AccountStatus, AccountRole


def is_headquarter_admin(user):
    """
    檢查用戶是否為總公司管理員
    
    Args:
        user: CustomUser 實例
        
    Returns:
        bool: 如果是總公司管理員且有管理員或超級用戶權限則返回 True
    """
    return (
        user.is_authenticated and
        user.role == AccountRole.HEADQUARTER and 
        (user.is_admin or user.is_superuser)
    )


def is_agent(user):
    """
    檢查用戶是否為代理商
    
    Args:
        user: CustomUser 實例
        
    Returns:
        bool: 如果是代理商則返回 True
    """
    return user.is_authenticated and user.role == AccountRole.AGENT


def is_distributor(user):
    """
    檢查用戶是否為分銷商
    
    Args:
        user: CustomUser 實例
        
    Returns:
        bool: 如果是分銷商則返回 True
    """
    return user.is_authenticated and user.role == AccountRole.DISTRIBUTOR


def is_peer(user):
    """
    檢查用戶是否為同業商
    
    Args:
        user: CustomUser 實例
        
    Returns:
        bool: 如果是同業商則返回 True
    """
    return user.is_authenticated and user.role == AccountRole.PEER


def can_manage_users(user):
    """
    檢查用戶是否有管理其他用戶的權限
    總公司管理員和代理商可以管理用戶
    
    Args:
        user: CustomUser 實例
        
    Returns:
        bool: 如果有管理用戶權限則返回 True
    """
    return is_headquarter_admin(user) or is_agent(user)


def can_topup(user):
    """
    檢查用戶是否可以執行儲值操作
    只有總公司管理員可以儲值
    
    Args:
        user: CustomUser 實例
        
    Returns:
        bool: 如果可以儲值則返回 True
    """
    return is_headquarter_admin(user)


def can_order_for_others(user):
    """
    檢查用戶是否可以為其他人下單
    只有總公司管理員可以為所有人下單
    
    Args:
        user: CustomUser 實例
        
    Returns:
        bool: 如果可以為他人下單則返回 True
    """
    return is_headquarter_admin(user)


def get_accessible_accounts(user):
    """
    獲取用戶可以查看的所有帳號
    
    Args:
        user: CustomUser 實例
        
    Returns:
        QuerySet: 可查看的帳號查詢集
    """
    from accounts.models import CustomUser
    from django.db.models import Q
    
    if is_headquarter_admin(user):
        # 總公司管理員：可以查看所有帳號
        return CustomUser.objects.filter(status=AccountStatus.ACTIVE)
    elif is_agent(user):
        # 代理商：可以查看自己和下級分銷商
        return CustomUser.objects.filter(
            Q(id=user.id) | Q(parent=user, role=AccountRole.DISTRIBUTOR),
            status=AccountStatus.ACTIVE
        )
    else:
        # 其他用戶：只能查看自己
        return CustomUser.objects.filter(id=user.id, status=AccountStatus.ACTIVE)


def get_orderable_accounts(user):
    """
    獲取用戶可以為其下單的帳號列表
    
    Args:
        user: CustomUser 實例
        
    Returns:
        QuerySet: 可下單的帳號查詢集
    """
    from accounts.models import CustomUser
    from django.db.models import Q
    
    if is_headquarter_admin(user):
        # 總公司管理員：可以為所有人下單
        return CustomUser.objects.filter(status=AccountStatus.ACTIVE).exclude(id=user.id)
    else:
        # 代理商和分銷商：只能為自己下單（返回空集）
        return CustomUser.objects.none()


def get_user_role_display(user):
    """
    獲取用戶角色的顯示名稱
    
    Args:
        user: CustomUser 實例
        
    Returns:
        str: 角色顯示名稱
    """
    if not user.is_authenticated:
        return "訪客"
    
    role_map = {
        AccountRole.HEADQUARTER: "總公司",
        AccountRole.AGENT: "代理商",
        AccountRole.DISTRIBUTOR: "分銷商",
    }
    
    role_name = role_map.get(user.role, "未知")
    
    if user.is_superuser:
        return f"{role_name} (超級管理員)"
    elif user.is_admin:
        return f"{role_name} (管理員)"
    
    return role_name


def get_variant_display_price(variant, user):
    """
    根據用戶角色獲取變體的顯示價格
    
    Args:
        variant: Variant 實例
        user: CustomUser 實例
        
    Returns:
        tuple: (顯示價格, 原價) 
               如果沒有特價則原價為 None
    """
    if is_distributor(user):
        # 分銷商：顯示代理商特價 或 代理商原價
        display_price = variant.price_sales_agent or variant.price_agent or 0
        original_price = variant.price_agent if variant.price_sales_agent else None
    elif is_agent(user) or is_headquarter_admin(user):
        # 代理商或總公司：顯示一般特價 或 一般原價
        display_price = variant.price_sales or variant.price or 0
        original_price = variant.price if variant.price_sales else None
    else:
        # 其他用戶（未登入或一般用戶）：顯示一般特價 或 一般原價
        display_price = variant.price_sales or variant.price or 0
        original_price = variant.price if variant.price_sales else None
    
    return display_price, original_price


def get_user_price_field(user):
    """
    根據用戶角色獲取應該使用的價格欄位名稱
    
    Args:
        user: CustomUser 實例
        
    Returns:
        tuple: (特價欄位名, 原價欄位名)
    """
    if is_distributor(user):
        return ('price_sales_agent', 'price_agent')
    elif is_agent(user) or is_headquarter_admin(user):
        return ('price_sales', 'price')
    else:
        return ('price_sales', 'price')