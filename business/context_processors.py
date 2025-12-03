import json
from urllib.parse import unquote


def cart_processor(request):
    """
    全局購物車 Context Processor
    在所有模板中提供 cart_count
    """
    cart_count = 0
    
    try:
        # 從 cookie 獲取購物車
        cart_cookie = request.COOKIES.get('cart', '{}')
        decoded_cookie = unquote(cart_cookie)
        cart = json.loads(decoded_cookie)
        
        # 計算總數量
        cart_count = sum(item.get('quantity', 0) for item in cart.values())
        
    except (json.JSONDecodeError, ValueError, AttributeError):
        cart_count = 0
    
    return {
        'cart_count': cart_count
    }