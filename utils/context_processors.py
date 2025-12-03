import json
from accounts.utils import (
    is_headquarter_admin, 
    is_agent, 
    is_distributor,
    get_user_role_display
)


def user_permissions(request):
    """
    將用戶權限添加到所有模板的 context 中
    """
    if request.user.is_authenticated:
        return {
            'is_headquarter_admin': is_headquarter_admin(request.user),
            'is_agent': is_agent(request.user),
            'is_distributor': is_distributor(request.user),
            'user_role_display': get_user_role_display(request.user),
        }
    return {
        'is_headquarter_admin': False,
        'is_agent': False,
        'is_distributor': False,
        'user_role_display': '訪客',
    }

def cart_processor(request):
    """
    全局購物車資訊 context processor
    讓所有模板都能訪問購物車數據
    """
    try:
        # 從 cookie 獲取購物車數據
        cart_cookie = request.COOKIES.get('cart', '{}')
        cart = json.loads(cart_cookie)
        
        # 計算商品總數
        cart_count = sum(
            int(item.get('quantity', 0)) 
            for item in cart.values()
        )
        
        # 計算總金額
        cart_total = sum(
            int(item.get('quantity', 0)) * float(item.get('unit_price', 0))
            for item in cart.values()
        )
        
        return {
            'cart_count': cart_count,
            'cart_total': cart_total,
            'cart_items_count': len(cart)  # 購物車商品種類數
        }
    except Exception as e:
        return {
            'cart_count': 0,
            'cart_total': 0,
            'cart_items_count': 0
        }