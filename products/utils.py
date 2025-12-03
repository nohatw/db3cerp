from decimal import Decimal
from accounts.constant import AccountRole
from accounts.utils import is_headquarter_admin, is_agent, is_distributor, is_peer


def format_price(price, show_currency=True):
    """
    格式化價格顯示
    
    Args:
        price: Decimal 或 None
        show_currency: bool，是否顯示貨幣符號
        
    Returns:
        str: 格式化的價格字串
    """
    if price is None or price == 0:
        return "—"
    
    # 移除小數點，因為價格是整數
    price_str = f"{int(price):,}"
    
    if show_currency:
        return f"NT$ {price_str}"
    
    return price_str


def get_headquarter_price(variant):
    """
    獲取總公司角色的價格
    
    總公司自己訂購時：使用 price, price_sales
    
    Args:
        variant: Variant 實例
        
    Returns:
        tuple: (顯示價格, 原價, 是否有特價)
    """
    display_price = variant.price_sales or variant.price or 0
    original_price = variant.price if variant.price_sales else None
    has_sale = bool(variant.price_sales and variant.price and variant.price_sales < variant.price)
    
    return display_price, original_price, has_sale


def get_agent_price(variant):
    """
    獲取代理商角色的價格
    
    代理商自己訂購時：使用 price_agent, price_sales_agent
    這些價格由 HEADQUARTER 定義
    
    Args:
        variant: Variant 實例
        
    Returns:
        tuple: (顯示價格, 原價, 是否有特價)
    """
    display_price = variant.price_sales_agent or variant.price_agent or 0
    original_price = variant.price_agent if variant.price_sales_agent else None
    has_sale = bool(variant.price_sales_agent and variant.price_agent and variant.price_sales_agent < variant.price_agent)
    
    return display_price, original_price, has_sale


def get_distributor_price(variant, distributor_user):
    """
    獲取經銷商角色的價格
    
    經銷商自己訂購時：使用 price_distr, price_sales_distr
    這些價格由該經銷商的上級 AGENT 定義（透過 AgentDistributorPricing）
    
    Args:
        variant: Variant 實例
        distributor_user: CustomUser 實例（必須是 DISTRIBUTOR 角色）
        
    Returns:
        tuple: (顯示價格, 原價, 是否有特價)
    """
    from products.models import AgentDistributorPricing
    
    # 確認用戶角色
    if distributor_user.role != AccountRole.DISTRIBUTOR:
        return 0, None, False
    
    # 獲取該經銷商的上級 AGENT
    agent = distributor_user.parent
    if not agent or agent.role != AccountRole.AGENT:
        return 0, None, False
    
    try:
        # 查找該 AGENT 為此 Variant 設定的經銷價格
        pricing = AgentDistributorPricing.objects.get(variant=variant, agent=agent)
        
        display_price = pricing.price_sales_distr or pricing.price_distr or 0
        original_price = pricing.price_distr if pricing.price_sales_distr else None
        has_sale = bool(pricing.price_sales_distr and pricing.price_distr and pricing.price_sales_distr < pricing.price_distr)
        
        return display_price, original_price, has_sale
    
    except AgentDistributorPricing.DoesNotExist:
        # 如果 AGENT 尚未設定價格，返回 0
        return 0, None, False


def get_peer_price(variant):
    """
    獲取同業角色的價格
    
    同業自己訂購時：使用 price_peer, price_sales_peer
    這些價格由 HEADQUARTER 定義
    
    Args:
        variant: Variant 實例
        
    Returns:
        tuple: (顯示價格, 原價, 是否有特價)
    """
    display_price = variant.price_sales_peer or variant.price_peer or 0
    original_price = variant.price_peer if variant.price_sales_peer else None
    has_sale = bool(variant.price_sales_peer and variant.price_peer and variant.price_sales_peer < variant.price_peer)
    
    return display_price, original_price, has_sale


def get_user_price(variant):
    """
    獲取一般用戶角色的價格
    
    一般用戶訂購時：使用 price, price_sales
    這些價格由 HEADQUARTER 定義
    
    Args:
        variant: Variant 實例
        
    Returns:
        tuple: (顯示價格, 原價, 是否有特價)
    """
    display_price = variant.price_sales or variant.price or 0
    original_price = variant.price if variant.price_sales else None
    has_sale = bool(variant.price_sales and variant.price and variant.price_sales < variant.price)
    
    return display_price, original_price, has_sale


def get_variant_price_for_user(variant, user):
    """
    根據用戶角色獲取變體的顯示價格（統一入口）
    
    Args:
        variant: Variant 實例
        user: CustomUser 實例
        
    Returns:
        tuple: (顯示價格, 原價, 是否有特價)
               如果沒有特價則原價為 None
    """
    if not user.is_authenticated:
        # 未登入用戶：使用一般價格
        return get_user_price(variant)
    
    if user.role == AccountRole.HEADQUARTER:
        return get_headquarter_price(variant)
    
    elif user.role == AccountRole.AGENT:
        return get_agent_price(variant)
    
    elif user.role == AccountRole.DISTRIBUTOR:
        return get_distributor_price(variant, user)
    
    elif user.role == AccountRole.PEER:
        return get_peer_price(variant)
    
    elif user.role == AccountRole.USER:
        return get_user_price(variant)
    
    else:
        # 未知角色：使用一般價格
        return get_user_price(variant)


def get_variant_price_for_target_user(variant, target_user):
    """
    獲取「為特定用戶訂購」時應該使用的價格
    
    使用場景：
    - HEADQUARTER 幫其他人訂購時，購物車顯示對應用戶角色的價格
    
    Args:
        variant: Variant 實例
        target_user: CustomUser 實例（被訂購者）
        
    Returns:
        tuple: (顯示價格, 原價, 是否有特價)
    """
    return get_variant_price_for_user(variant, target_user)


def can_purchase_variant(variant, user):
    """
    檢查用戶是否可以購買該變體（是否有價格設定）
    
    Args:
        variant: Variant 實例
        user: CustomUser 實例
        
    Returns:
        bool: True 表示可以購買（有價格設定且大於 0）
    """
    display_price, _, _ = get_variant_price_for_user(variant, user)
    return display_price > 0


def get_price_field_names_for_user(user):
    """
    根據用戶角色獲取應該使用的價格欄位名稱
    
    Args:
        user: CustomUser 實例
        
    Returns:
        tuple: (特價欄位名, 原價欄位名)
    """
    if not user.is_authenticated:
        return ('price_sales', 'price')
    
    if user.role == AccountRole.HEADQUARTER:
        return ('price_sales', 'price')
    
    elif user.role == AccountRole.AGENT:
        return ('price_sales_agent', 'price_agent')
    
    elif user.role == AccountRole.DISTRIBUTOR:
        # 經銷商價格來自 AgentDistributorPricing，不是直接欄位
        return ('price_sales_distr', 'price_distr')
    
    elif user.role == AccountRole.PEER:
        return ('price_sales_peer', 'price_peer')
    
    elif user.role == AccountRole.USER:
        return ('price_sales', 'price')
    
    else:
        return ('price_sales', 'price')


def get_all_prices_for_variant(variant):
    """
    獲取變體的所有價格資訊（用於管理後台顯示）
    
    Args:
        variant: Variant 實例
        
    Returns:
        dict: 包含所有角色的價格資訊
    """
    return {
        'headquarter': {
            'price': variant.price,
            'price_sales': variant.price_sales,
        },
        'agent': {
            'price': variant.price_agent,
            'price_sales': variant.price_sales_agent,
        },
        'peer': {
            'price': variant.price_peer,
            'price_sales': variant.price_sales_peer,
        },
        'user': {
            'price': variant.price,
            'price_sales': variant.price_sales,
        },
    }


def set_agent_distributor_pricing(variant, agent, price_distr, price_sales_distr=None):
    """
    設定或更新 AGENT 為特定 Variant 設定的經銷價格
    
    Args:
        variant: Variant 實例
        agent: CustomUser 實例（必須是 AGENT 角色）
        price_distr: Decimal，經銷價格
        price_sales_distr: Decimal 或 None，經銷特價
        
    Returns:
        AgentDistributorPricing: 創建或更新的定價實例
    """
    from products.models import AgentDistributorPricing
    
    if agent.role != AccountRole.AGENT:
        raise ValueError("只有 AGENT 角色可以設定經銷價格")
    
    pricing, created = AgentDistributorPricing.objects.update_or_create(
        variant=variant,
        agent=agent,
        defaults={
            'price_distr': price_distr,
            'price_sales_distr': price_sales_distr,
        }
    )
    
    return pricing


def get_agent_distributor_pricing(variant, agent):
    """
    獲取 AGENT 為特定 Variant 設定的經銷價格
    
    Args:
        variant: Variant 實例
        agent: CustomUser 實例（必須是 AGENT 角色）
        
    Returns:
        AgentDistributorPricing 或 None
    """
    from products.models import AgentDistributorPricing
    
    if agent.role != AccountRole.AGENT:
        return None
    
    try:
        return AgentDistributorPricing.objects.get(variant=variant, agent=agent)
    except AgentDistributorPricing.DoesNotExist:
        return None


def validate_price_hierarchy(variant):
    """
    驗證價格層級是否合理（特價 < 原價）
    
    Args:
        variant: Variant 實例
        
    Returns:
        dict: 包含驗證結果的字典
    """
    errors = []
    
    # 檢查一般價格
    if variant.price_sales and variant.price and variant.price_sales >= variant.price:
        errors.append("一般特價必須低於一般價格")
    
    # 檢查代理商價格
    if variant.price_sales_agent and variant.price_agent and variant.price_sales_agent >= variant.price_agent:
        errors.append("代理商特價必須低於代理商價格")
    
    # 檢查同業價格
    if variant.price_sales_peer and variant.price_peer and variant.price_sales_peer >= variant.price_peer:
        errors.append("同業特價必須低於同業價格")
    
    return {
        'is_valid': len(errors) == 0,
        'errors': errors
    }