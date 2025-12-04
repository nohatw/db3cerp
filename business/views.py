import json
import csv
import io
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseRedirect
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import CreateView, UpdateView, DetailView, DeleteView
from django.views.generic.list import ListView
from django.views.generic.base import View
from django.urls import reverse_lazy
from django.db.models import Q, Sum
from django.db import transaction
from business.models import Order, OrderProduct, OrderCoupons, Receipt, ReceiptItem, AccountTopUP, AccountTopUPLog, Expense, Income
from business.forms import TopupCreateForm
from business.constant import OrderStatus, PaymentType, OrderSource, ReceiptType, TopupType, IncomeItem, ExpenseItem, CUSTOM_CODE, CUSTOM_AUTH, SUBMIT_ORDER_TYPE, SUBMIT_ORDER_REPLY_TYPE, WAREHOUSE
from accounts.models import CustomUser
from accounts.constant import AccountStatus, AccountRole
from products.models import Supplier, Category, Product, Variant, Stock
from products.constant import VariantStatus, ProductType
from products.views import CatalogueDetailView
from accounts.utils import (
    is_headquarter_admin, 
    is_agent, 
    is_distributor,
    can_manage_users,
    can_topup,
    can_order_for_others,
    get_orderable_accounts,
    get_user_role_display,
    get_variant_display_price,
    get_user_price_field
)
from products.utils import get_variant_price_for_user
from django import forms
import logging
logger = logging.getLogger(__name__)

# 儲值異動記錄列表 TopupLog by user
class TopupListView(LoginRequiredMixin, ListView):
    model = AccountTopUPLog
    template_name = 'business/topup_list.html'
    context_object_name = 'topup_logs'
    paginate_by = 20  # 每頁顯示 20 筆

    def get_queryset(self):
        user = self.request.user
        queryset = AccountTopUPLog.objects.select_related(
            'topup__account',
            'topup__account__parent',
            'order'
        ).all()
        
        # 1. 總公司管理員或超級用戶 - 可以看到所有帳號的儲值異動記錄
        if is_headquarter_admin(user):
            # 不需要過濾，顯示所有
            pass
        
        # 2. 代理商 - 可以看到自己和底下分銷商的儲值異動記錄
        elif is_agent(user):
            # 獲取自己底下的所有分銷商
            distributor_ids = CustomUser.objects.filter(
                parent=user,
                role=AccountRole.DISTRIBUTOR
            ).values_list('id', flat=True)
            
            # 顯示自己和底下分銷商的儲值異動
            queryset = queryset.filter(
                Q(topup__account=user) | Q(topup__account__id__in=distributor_ids)
            )
        
        # 3. 其他用戶 - 只能看到自己的儲值異動記錄
        else:
            queryset = queryset.filter(topup__account=user)
        
        # 搜尋功能
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(topup__account__username__icontains=search_query) |
                Q(topup__account__email__icontains=search_query) |
                Q(topup__account__fullname__icontains=search_query) |
                Q(topup__account__company__icontains=search_query) |
                Q(remark__icontains=search_query)
            )
        
        # 狀態過濾
        selected_status = self.request.GET.get('status')
        if selected_status:
            queryset = queryset.filter(topup__account__status=selected_status)
        
        # 角色過濾
        selected_role = self.request.GET.get('role')
        if selected_role:
            queryset = queryset.filter(topup__account__role=selected_role)
        
        # 異動類型過濾
        selected_log_type = self.request.GET.get('log_type')
        if selected_log_type:
            queryset = queryset.filter(log_type=selected_log_type)
        
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # 傳遞過濾選項
        context['account_statuses'] = AccountStatus.choices
        context['account_roles'] = AccountRole.choices
        context['topup_types'] = TopupType.choices
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_role'] = self.request.GET.get('role', '')
        context['selected_log_type'] = self.request.GET.get('log_type', '')
        context['search_query'] = self.request.GET.get('q', '')
  
        # 計算統計資料（根據權限）
        # 1. 獲取當前用戶可查看的所有 AccountTopUP
        if is_headquarter_admin(user):
            # 總公司管理員：查看所有帳號的儲值
            topup_queryset = AccountTopUP.objects.all()
        elif is_agent(user):
            # 代理商：查看自己和下級分銷商的儲值
            distributor_ids = CustomUser.objects.filter(
                parent=user,
                role=AccountRole.DISTRIBUTOR
            ).values_list('id', flat=True)
            topup_queryset = AccountTopUP.objects.filter(
                Q(account=user) | Q(account__id__in=distributor_ids)
            )
        else:
            # 其他用戶：只查看自己的儲值
            topup_queryset = AccountTopUP.objects.filter(account=user)
        
        # 2. 計算當前儲值餘額總和
        context['total_balance'] = topup_queryset.aggregate(
            total=Sum('balance')
        )['total'] or 0
        
        # 3. 異動記錄統計（用於顯示記錄數量）
        topup_logs = self.get_queryset()
        context['total_logs'] = topup_logs.count()
        context['total_accounts'] = topup_logs.values('topup__account').distinct().count()
        
        return context


# 新增儲值 by user
class TopupCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = AccountTopUP
    form_class = TopupCreateForm
    template_name = 'business/topup_create.html'
    success_url = reverse_lazy('business:topup_list')

    def test_func(self):
        """
        權限檢查：使用工具函數
        只有總公司管理員/超級用戶可以為所有人儲值
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.error(self.request, '您沒有權限執行此操作，只有總公司管理員可以新增儲值。')
        return redirect('business:topup_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request_user'] = self.request.user
        # 傳遞從 URL 獲取的 account_id
        kwargs['account_id'] = self.request.GET.get('account_id')
        return kwargs

    def form_valid(self, form):
        try:
            with transaction.atomic():
                account = form.cleaned_data['account']
                amount = form.cleaned_data['amount']
                remark = form.cleaned_data.get('remark', '')

                # 1. 檢查該帳號是否已有儲值記錄
                topup, created = AccountTopUP.objects.get_or_create(
                    account=account,
                    defaults={'balance': 0, 'remark': remark}
                )

                # 2. 記錄異動前的餘額
                balance_before = topup.balance

                # 3. 更新儲值餘額
                topup.balance += amount
                if remark and not created:
                    topup.remark = remark
                topup.save()

                # 4. 新增儲值異動記錄
                AccountTopUPLog.objects.create(
                    topup=topup,
                    amount=amount,
                    balance_before=balance_before,
                    balance_after=topup.balance,
                    log_type=TopupType.DEPOSIT,
                    is_confirmed=True,
                    remark=remark
                )

                messages.success(
                    self.request,
                    f'成功為 {account.fullname or account.username} 儲值 ${amount:,.0f}，'
                    f'目前餘額：${topup.balance:,.0f}'
                )
                
                return redirect(self.success_url)

        except Exception as e:
            messages.error(self.request, f'儲值失敗：{str(e)}')
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 傳遞選中的帳號資訊
        account_id = self.request.GET.get('account_id')
        if account_id:
            try:
                selected_account = CustomUser.objects.get(id=account_id)
                context['selected_account'] = selected_account
                # 取得該帳號的儲值餘額
                try:
                    topup = AccountTopUP.objects.get(account=selected_account)
                    context['current_balance'] = topup.balance
                except AccountTopUP.DoesNotExist:
                    context['current_balance'] = 0
            except CustomUser.DoesNotExist:
                messages.warning(self.request, '找不到指定的帳號')
                context['selected_account'] = None
                context['current_balance'] = 0
        else:
            context['selected_account'] = None
            context['current_balance'] = 0
        
        return context

# 新增購物車項目
@login_required
@require_POST
def add_to_cart(request, variant_id):
    """
    POST: quantity (optional)
    Cookie 'cart' stores JSON: {
        'variant_id': {
            'product_name': str,
            'variant_name': str,
            'quantity': int,
            'unit_price': float
        }
    }
    Returns JSON with cart_count and total
    """
    import logging
    from urllib.parse import quote, unquote
    
    logger = logging.getLogger(__name__)
    
    try:
        # 1. 獲取變體資訊
        variant = get_object_or_404(
            Variant.objects.select_related('product'),
            id=variant_id,
            status=VariantStatus.ACTIVE,
            product__status='ACTIVE'
        )
        
        # 2. 獲取數量（預設為 1）
        quantity = int(request.POST.get('quantity', 1))
        if quantity < 1:
            quantity = 1
        if quantity > 999:
            quantity = 999
        
        # 3. 使用 products/utils.py 的統一定價函數根據用戶角色決定價格
        user = request.user
        display_price, original_price, has_sale = get_variant_price_for_user(variant, user)
        unit_price = float(display_price)
        
        logger.info(f'用戶 {user.username} (角色: {user.get_role_display()}) 的價格：${unit_price}')
        
        if unit_price <= 0:
            return JsonResponse({
                'success': False,
                'error': '此商品暫無價格，請聯絡客服'
            }, status=400, json_dumps_params={'ensure_ascii': False})
        
        # 4. 從 cookie 獲取購物車
        cart = {}
        cart_cookie = request.COOKIES.get('cart', '{}')
        try:
            # 先解碼 URL 編碼
            decoded_cookie = unquote(cart_cookie)
            cart = json.loads(decoded_cookie)
            logger.debug(f'成功解析購物車，共 {len(cart)} 項商品')
        except (json.JSONDecodeError, ValueError) as e:
            cart = {}
            logger.warning(f'購物車 cookie 解析失敗：{str(e)}，將建立新購物車')
        
        # 5. 添加或更新商品
        variant_key = str(variant_id)
        
        # 安全處理名稱（移除特殊字符）
        product_name = str(variant.product.name).replace('\x00', '').replace('\n', ' ').replace('\r', '').strip()
        variant_name = str(variant.name).replace('\x00', '').replace('\n', ' ').replace('\r', '').strip()
        
        if variant_key in cart:
            # 更新數量（累加）
            old_quantity = cart[variant_key]['quantity']
            cart[variant_key]['quantity'] += quantity
            
            # 限制最大數量
            if cart[variant_key]['quantity'] > 999:
                cart[variant_key]['quantity'] = 999
            
            # 更新價格（以防價格有變動）
            cart[variant_key]['unit_price'] = unit_price
            
            action = 'updated'
            logger.info(f'更新購物車：變體 {variant_id}，數量 {old_quantity} → {cart[variant_key]["quantity"]}')
        else:
            # 新增商品
            cart[variant_key] = {
                'product_name': product_name,
                'variant_name': variant_name,
                'quantity': quantity,
                'unit_price': unit_price
            }
            action = 'added'
            logger.info(f'新增至購物車：變體 {variant_id}，數量 {quantity}')
        
        # 6. 計算購物車統計
        cart_count = sum(item['quantity'] for item in cart.values())
        cart_total = sum(item['quantity'] * item['unit_price'] for item in cart.values())
        
        logger.info(f'購物車統計：共 {cart_count} 件商品，總計 ${cart_total:.2f}')
        
        # 7. 準備回應（確保所有值都是可序列化的）
        response_data = {
            'success': True,
            'action': action,
            'cart_count': cart_count,
            'total': float(cart_total),
            'item_quantity': cart[variant_key]['quantity'],
            'message': f'已將 {variant_name} 加入購物車'
        }
        
        # 使用 ensure_ascii=False 處理中文
        response = JsonResponse(response_data, json_dumps_params={'ensure_ascii': False})
        
        # 8. 設定 cookie（30 天過期）
        # 使用 ensure_ascii=False 確保中文正確存儲
        cart_json = json.dumps(cart, ensure_ascii=False)
        
        # 對包含中文的 JSON 進行 URL 編碼
        encoded_cart = quote(cart_json)
        
        response.set_cookie(
            'cart',
            encoded_cart,
            max_age=30*24*60*60,  # 30 天
            httponly=False,  # 允許 JavaScript 讀取
            samesite='Lax'
        )
        
        logger.info(f'成功加入購物車：variant_id={variant_id}, quantity={quantity}, cart_count={cart_count}')
        
        return response
        
    except Variant.DoesNotExist:
        logger.error(f'變體不存在：variant_id={variant_id}')
        return JsonResponse({
            'success': False,
            'error': '商品不存在或已下架'
        }, status=404, json_dumps_params={'ensure_ascii': False})
    except ValueError as e:
        logger.error(f'數量格式錯誤：{str(e)}')
        return JsonResponse({
            'success': False,
            'error': f'數量格式錯誤：{str(e)}'
        }, status=400, json_dumps_params={'ensure_ascii': False})
    except Exception as e:
        logger.error(f'加入購物車失敗：{str(e)}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'加入購物車失敗：{str(e)}'
        }, status=500, json_dumps_params={'ensure_ascii': False})


# 更新購物車（變更數量）
@login_required
@require_POST
def update_cart(request, variant_id):
    """
    更新購物車中商品的數量
    POST: quantity (required)
    """
    from urllib.parse import quote, unquote
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        # 1. 獲取新數量
        quantity = int(request.POST.get('quantity', 1))
        if quantity < 1:
            quantity = 1
        if quantity > 999:
            quantity = 999
        
        # 2. 從 cookie 獲取購物車
        cart = {}
        cart_cookie = request.COOKIES.get('cart', '{}')
        try:
            decoded_cookie = unquote(cart_cookie)
            cart = json.loads(decoded_cookie)
        except (json.JSONDecodeError, ValueError):
            cart = {}
        
        variant_key = str(variant_id)
        
        if variant_key not in cart:
            return JsonResponse({
                'success': False,
                'error': '購物車中沒有此商品'
            }, status=404)
        
        # 3. 獲取變體並更新價格（使用 products/utils.py 的統一定價函數）
        try:
            variant = Variant.objects.select_related('product').get(
                id=variant_id,
                status=VariantStatus.ACTIVE,
                product__status='ACTIVE'
            )
            
            user = request.user
            display_price, original_price, has_sale = get_variant_price_for_user(variant, user)
            unit_price = float(display_price)
            
            # 更新數量和價格
            cart[variant_key]['quantity'] = quantity
            cart[variant_key]['unit_price'] = unit_price
            
            logger.info(f'更新購物車：變體 {variant_id}，數量 {quantity}，單價 ${unit_price}')
            
        except Variant.DoesNotExist:
            logger.warning(f'變體 {variant_id} 已下架，從購物車移除')
            cart.pop(variant_key)
            return JsonResponse({
                'success': False,
                'error': '此商品已下架',
                'removed': True
            }, status=404)
        
        # 4. 計算購物車統計
        item_subtotal = cart[variant_key]['quantity'] * cart[variant_key]['unit_price']
        cart_count = sum(item['quantity'] for item in cart.values())
        cart_total = sum(item['quantity'] * item['unit_price'] for item in cart.values())
        
        # 5. 準備回應
        response = JsonResponse({
            'success': True,
            'cart_count': cart_count,
            'total': cart_total,
            'item_quantity': quantity,
            'item_subtotal': item_subtotal
        })
        
        # 6. 更新 cookie
        cart_json = json.dumps(cart, ensure_ascii=False)
        encoded_cart = quote(cart_json)
        
        response.set_cookie(
            'cart',
            encoded_cart,
            max_age=30*24*60*60,
            httponly=False,
            samesite='Lax'
        )
        
        return response
        
    except ValueError as e:
        logger.error(f'數量格式錯誤：{str(e)}')
        return JsonResponse({
            'success': False,
            'error': f'數量格式錯誤：{str(e)}'
        }, status=400)
    except Exception as e:
        logger.error(f'更新失敗：{str(e)}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'更新失敗：{str(e)}'
        }, status=500)


# 更新購物車單價（僅限總公司管理員）
@login_required
@require_POST
def update_cart_price(request, variant_id):
    """
    更新購物車中商品的單價（僅限總公司管理員）
    POST: unit_price (required)
    
    注意：此功能允許總公司管理員自訂單價，不受角色定價限制
    """
    from urllib.parse import quote, unquote
    import logging
    
    logger = logging.getLogger(__name__)
    
    # 1. 權限檢查
    if not is_headquarter_admin(request.user):
        return JsonResponse({
            'success': False,
            'error': '權限不足：只有總公司管理員可以修改單價'
        }, status=403)
    
    try:
        # 2. 獲取新單價並四捨五入為整數
        unit_price = Decimal(request.POST.get('unit_price', '0'))
        unit_price = unit_price.quantize(Decimal('1'))  # 四捨五入到整數
        
        if unit_price < 0:
            return JsonResponse({
                'success': False,
                'error': '單價不能為負數'
            }, status=400)
        
        # 3. 從 cookie 獲取購物車
        cart = {}
        cart_cookie = request.COOKIES.get('cart', '{}')
        try:
            decoded_cookie = unquote(cart_cookie)
            cart = json.loads(decoded_cookie)
        except (json.JSONDecodeError, ValueError):
            cart = {}
        
        variant_key = str(variant_id)
        
        if variant_key not in cart:
            return JsonResponse({
                'success': False,
                'error': '購物車中沒有此商品'
            }, status=404)
        
        # 4. 更新單價（整數）
        cart[variant_key]['unit_price'] = int(unit_price)  # 儲存為整數
        
        logger.info(f'總公司管理員 {request.user.username} 修改單價：變體 {variant_id}，新單價 ${unit_price}')
        
        # 5. 計算購物車統計
        quantity = cart[variant_key]['quantity']
        item_subtotal = quantity * unit_price
        
        cart_count = sum(item['quantity'] for item in cart.values())
        cart_total = sum(
            item['quantity'] * Decimal(str(item['unit_price'])) 
            for item in cart.values()
        )
        
        # 6. 準備回應（返回整數）
        response = JsonResponse({
            'success': True,
            'cart_count': cart_count,
            'total': int(cart_total),  # 整數
            'item_quantity': quantity,
            'item_subtotal': int(item_subtotal),  # 整數
            'unit_price': int(unit_price)  # 整數
        })
        
        # 7. 更新 cookie
        cart_json = json.dumps(cart, ensure_ascii=False)
        encoded_cart = quote(cart_json)
        
        response.set_cookie(
            'cart',
            encoded_cart,
            max_age=30*24*60*60,
            httponly=False,
            samesite='Lax'
        )
        
        return response
        
    except (ValueError, TypeError) as e:
        logger.error(f'單價格式錯誤：{str(e)}')
        return JsonResponse({
            'success': False,
            'error': f'單價格式錯誤：{str(e)}'
        }, status=400)
    except Exception as e:
        logger.error(f'更新單價失敗：{str(e)}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'更新失敗：{str(e)}'
        }, status=500)


# 移除購物車項目
@login_required
@require_POST
def remove_from_cart(request, variant_id):
    """
    從購物車移除商品
    """
    from urllib.parse import quote, unquote
    
    try:
        # 1. 從 cookie 獲取購物車
        cart = {}
        cart_cookie = request.COOKIES.get('cart', '{}')
        try:
            decoded_cookie = unquote(cart_cookie)
            cart = json.loads(decoded_cookie)
        except (json.JSONDecodeError, ValueError):
            cart = {}
        
        variant_key = str(variant_id)
        
        if variant_key not in cart:
            return JsonResponse({
                'success': False,
                'error': '購物車中沒有此商品'
            }, status=404)
        
        # 2. 移除商品
        removed_item = cart.pop(variant_key)
        
        # 3. 計算購物車統計
        cart_count = sum(item['quantity'] for item in cart.values())
        cart_total = sum(item['quantity'] * item['unit_price'] for item in cart.values())
        
        # 4. 準備回應
        response = JsonResponse({
            'success': True,
            'cart_count': cart_count,
            'total': cart_total,
            'message': f'已移除 {removed_item["variant_name"]}'
        })
        
        # 5. 更新 cookie
        cart_json = json.dumps(cart, ensure_ascii=False)
        encoded_cart = quote(cart_json)
        
        response.set_cookie(
            'cart',
            encoded_cart,
            max_age=30*24*60*60,
            httponly=False,
            samesite='Lax'
        )
        
        return response
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'移除失敗：{str(e)}'
        }, status=500)


# 購物車頁面
@login_required
def cart_view(request):
    """
    購物車頁面
    
    功能：
    1. 顯示購物車商品列表
    2. 可修改商品數量
    3. 總公司管理員可修改單價
    4. 顯示產品類型標識
    """
    import json
    import logging
    from urllib.parse import unquote
    from decimal import Decimal
    
    logger = logging.getLogger(__name__)
    user = request.user
    
    # 從 cookie 獲取購物車
    cart = {}
    cart_cookie = request.COOKIES.get('cart', '{}')
    try:
        decoded_cookie = unquote(cart_cookie)
        cart = json.loads(decoded_cookie)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f'購物車 cookie 解析失敗：{str(e)}')
        cart = {}
    
    # 構建購物車項目列表
    cart_items = []
    total = Decimal('0')
    
    for variant_id, item_data in cart.items():
        try:
            variant = Variant.objects.select_related('product').get(
                id=variant_id,
                status=VariantStatus.ACTIVE,
                product__status='ACTIVE'
            )
            
            quantity = item_data.get('quantity', 1)
            unit_price = Decimal(str(item_data.get('unit_price', 0)))
            subtotal = unit_price * quantity
            
            # 添加產品類型信息
            cart_items.append({
                'variant_id': variant.id,
                'product_name': variant.product.name,
                'variant_name': variant.name,
                'product_type': variant.product_type,  # 產品類型
                'product_type_display': variant.get_product_type_display(),  # ✅ 新增：產品類型顯示名稱
                'quantity': quantity,
                'unit_price': unit_price,
                'subtotal': subtotal,
            })
            
            total += subtotal
            
        except Variant.DoesNotExist:
            logger.warning(f'變體 {variant_id} 不存在或已下架，已從購物車移除')
            continue
        except Exception as e:
            logger.error(f'處理購物車項目 {variant_id} 時出錯：{str(e)}')
            continue
    
    context = {
        'cart_items': cart_items,
        'cart_count': sum(item['quantity'] for item in cart_items),
        'total': total,
        'is_headquarter': is_headquarter_admin(user),
    }
    
    return render(request, 'business/cart_view.html', context)

# 結帳頁面
@login_required
def checkout_view(request):
    """
    結帳頁面
    """
    import logging
    from urllib.parse import unquote
    
    logger = logging.getLogger(__name__)
    
    # 1. 從 cookie 獲取購物車
    cart = {}
    cart_cookie = request.COOKIES.get('cart', '{}')
    try:
        decoded_cookie = unquote(cart_cookie)
        cart = json.loads(decoded_cookie)
    except (json.JSONDecodeError, ValueError):
        cart = {}
    
    # 2. 檢查購物車是否為空
    if not cart:
        messages.warning(request, '購物車是空的，請先添加商品')
        return redirect('products:catalogue_list')
    
    # 3. 準備購物車項目列表（含詳細資訊）
    cart_items = []
    cart_count = 0
    cart_total = Decimal('0')
    invalid_items = []
    
    user = request.user
    
    # 檢查是否有選中的客戶（從 session 獲取）
    order_for_account_id = request.session.get('order_for_account_id')
    order_for_account = None
    
    logger.info(f'結帳頁面：user={user.username}')
    logger.info(f'Session 中的 order_for_account_id={order_for_account_id}')
    
    if order_for_account_id and can_order_for_others(user):
        logger.info(f'嘗試獲取選中的客戶：ID={order_for_account_id}')
        try:
            order_for_account = CustomUser.objects.get(
                id=order_for_account_id,
                status=AccountStatus.ACTIVE
            )
            logger.info(f'成功獲取選中的客戶：{order_for_account.username}')
        except CustomUser.DoesNotExist:
            logger.error(f'選中的客戶不存在：ID={order_for_account_id}')
            # 清除 session
            request.session.pop('order_for_account_id', None)
            request.session.pop('order_for_account_name', None)
            request.session.pop('order_for_account_role', None)
            request.session.pop('order_for_account_balance', None)
            messages.warning(request, '選中的客戶已不存在，將為您自己下單')
    else:
        if order_for_account_id:
            logger.warning(f'有 order_for_account_id 但用戶沒有權限')
        else:
            logger.info('沒有選中客戶，為自己下單')
    
    # 確定當前訂單帳號
    current_order_account = order_for_account if order_for_account else user
    logger.info(f'當前訂單帳號：{current_order_account.username} (角色: {current_order_account.get_role_display()})')
    
    # 4. 使用購物車中的價格（不重新計算）
    for variant_id, item_data in cart.items():
        try:
            variant = Variant.objects.select_related('product').get(
                id=variant_id,
                status=VariantStatus.ACTIVE,
                product__status='ACTIVE'
            )
            
            # ✅ 直接使用購物車中儲存的價格（已經是總公司管理員修改過的價格）
            unit_price = Decimal(str(item_data['unit_price']))
            quantity = item_data['quantity']
            subtotal = quantity * unit_price
            
            logger.info(f'變體 {variant_id}: {variant.name}, 購物車單價 ${unit_price}, 數量 {quantity}, 小計 ${subtotal}')
            
            cart_items.append({
                'variant_id': variant_id,
                'variant': variant,
                'product_name': variant.product.name,
                'variant_name': variant.name,
                'product_code': variant.product_code,
                'product_type': variant.get_product_type_display(),
                'days': variant.days,
                'data_amount': variant.data_amount,
                'quantity': quantity,
                'unit_price': unit_price,
                'subtotal': subtotal
            })
            
            cart_count += quantity
            cart_total += subtotal
            
        except Variant.DoesNotExist:
            logger.warning(f'變體 {variant_id} 已下架')
            invalid_items.append({
                'variant_id': variant_id,
                'name': item_data.get('variant_name', '未知商品')
            })
    
    # 5. 如果有無效商品，顯示警告
    if invalid_items:
        invalid_names = ', '.join([item['name'] for item in invalid_items])
        messages.warning(
            request, 
            f'以下商品已下架或不存在：{invalid_names}，已自動移除'
        )
        
        # 從購物車 cookie 中移除無效商品
        for item in invalid_items:
            cart.pop(str(item['variant_id']), None)
        
        if not cart_items:
            messages.error(request, '購物車中所有商品都已失效，請重新選購')
            response = redirect('products:catalogue_list')
            response.delete_cookie('cart')
            return response
        
        # 更新 cookie（移除無效商品後）
        from urllib.parse import quote
        cart_json = json.dumps(cart, ensure_ascii=False)
        encoded_cart = quote(cart_json)
    
    # 6. 獲取訂單帳號的儲值餘額
    try:
        topup = AccountTopUP.objects.get(account=current_order_account)
        user_balance = topup.balance
        logger.info(f'訂單帳號 {current_order_account.username} 餘額：${user_balance}')
    except AccountTopUP.DoesNotExist:
        user_balance = Decimal('0')
        logger.info(f'訂單帳號 {current_order_account.username} 沒有儲值記錄')
    
    after_balance = user_balance - cart_total
    balance_sufficient = user_balance >= cart_total
    
    logger.info(f'結帳統計：商品總數 {cart_count}，總金額 ${cart_total}，餘額 ${user_balance}，餘額{"足夠" if balance_sufficient else "不足"}')
    
    # 7. 準備 context
    context = {
        'cart_items': cart_items,
        'cart_count': cart_count,
        'cart_total': cart_total,
        'user_balance': user_balance,
        'after_balance': after_balance,
        'balance_sufficient': balance_sufficient,
        'can_order_for_others': can_order_for_others(user),
        'order_for_account': order_for_account,
        'order_for_account_name': request.session.get('order_for_account_name'),
        'order_for_account_role': request.session.get('order_for_account_role'),
        'payment_types': PaymentType.choices,
        'order_sources': OrderSource.choices,
    }
    
    # 如果有移除無效商品，需要更新 cookie
    response = render(request, 'business/checkout.html', context)
    if invalid_items:
        response.set_cookie(
            'cart',
            encoded_cart,
            max_age=30*24*60*60,
            httponly=False,
            samesite='Lax'
        )
    
    return response


# 提交預訂
@login_required
@require_POST
def submit_reservation(request):
    """
    提交預訂請求
    
    預訂訂單特點：
    1. 建立訂單，狀態為 HOLDING（保留中）
    2. 不扣除庫存數量
    3. 不扣除儲值金額
    4. 只記錄訂單和產品資訊
    5. 後續在訂單詳情頁面進行：
       - 確認預訂（扣庫存、扣款、改狀態為 PENDING/PAID）
       - 取消預訂（刪除訂單）
    """
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        with transaction.atomic():
            # 1. 獲取表單資料
            payment_type = request.POST.get('payment_type', PaymentType.TOPUP)
            remark = request.POST.get('remark', '')
            order_source = request.POST.get('order_source', OrderSource.LINE)
            user = request.user
            
            # 2. 從 session 確定訂單帳號
            order_for_account_id = request.session.get('order_for_account_id')
            
            if order_for_account_id and can_order_for_others(user):
                try:
                    order_account = CustomUser.objects.get(
                        id=order_for_account_id,
                        status=AccountStatus.ACTIVE
                    )
                    logger.info(f'為客戶 {order_account.username} 建立預訂')
                except CustomUser.DoesNotExist:
                    messages.error(request, '選擇的帳號不存在或已停用')
                    request.session.pop('order_for_account_id', None)
                    request.session.pop('order_for_account_name', None)
                    request.session.pop('order_for_account_role', None)
                    request.session.pop('order_for_account_balance', None)
                    return redirect('business:checkout')
            else:
                order_account = user
                logger.info(f'為自己 {order_account.username} 建立預訂')
            
            # 3. 從 cookie 獲取購物車
            cart = {}
            cart_cookie = request.COOKIES.get('cart', '{}')
            try:
                from urllib.parse import unquote
                decoded_cookie = unquote(cart_cookie)
                cart = json.loads(decoded_cookie)
            except (json.JSONDecodeError, ValueError):
                messages.error(request, '購物車資料錯誤')
                return redirect('business:cart_view')
            
            if not cart:
                messages.error(request, '購物車是空的')
                return redirect('business:cart_view')
            
            # 4. 驗證購物車商品（不檢查庫存）
            order_items = []
            total_amount = Decimal('0')
            
            for variant_id, item_data in cart.items():
                try:
                    variant = Variant.objects.select_related('product').get(
                        id=variant_id,
                        status=VariantStatus.ACTIVE,
                        product__status='ACTIVE'
                    )
                    
                    # 直接使用購物車中儲存的價格
                    unit_price = Decimal(str(item_data['unit_price']))
                    
                    if unit_price < 0:
                        messages.error(request, f'商品 {variant.name} 價格異常')
                        return redirect('business:checkout')
                    
                    quantity = item_data['quantity']
                    subtotal = unit_price * quantity
                    
                    order_items.append({
                        'variant': variant,
                        'product_code': variant.product_code,
                        'quantity': quantity,
                        'unit_price': unit_price
                    })
                    
                    total_amount += subtotal
                    logger.info(f'預訂項目：{variant.name} x {quantity} @ ${unit_price} = ${subtotal}')
                    
                except Variant.DoesNotExist:
                    messages.error(request, f'商品 {item_data.get("variant_name")} 已下架')
                    return redirect('business:checkout')
            
            logger.info(f'預訂總金額：${total_amount}')
            
            # 5. ✅ 建立預訂訂單（狀態為 HOLDING）
            order = Order.objects.create(
                account=order_account,
                created_by=user,
                payment_type=payment_type,
                order_source=order_source,
                status=OrderStatus.HOLDING,  # 預訂狀態
                remark=remark
            )
            
            logger.info(
                f'✅ 建立預訂訂單 #{order.id}，'
                f'帳號：{order_account.username}，'
                f'創建人：{user.username}，'
                f'來源：{order.get_order_source_display()}，'
                f'狀態：HOLDING（保留中）'
            )

            # 6. ✅ 建立訂單項目（不扣除庫存，不記錄 used_stocks）
            for item in order_items:
                OrderProduct.objects.create(
                    order=order,
                    variant=item['variant'],
                    product_code=item['product_code'],
                    quantity=item['quantity'],
                    unit_price=item['unit_price'],
                    used_stocks=[]  # ✅ 預訂訂單暫不記錄庫存使用
                )
                
                logger.info(
                    f'✅ 建立預訂項目：{item["variant"].name} x {item["quantity"]} 件，'
                    f'單價 ${item["unit_price"]}（未扣庫存）'
                )
            
            # 7. ✅ 不扣除儲值（預訂不扣款）
            logger.info('⚠️ 預訂訂單不扣除儲值，待後續確認')
            
            # 8. 清空購物車和 session
            order_for_name = order_account.fullname or order_account.username
            is_for_others = (order_account != user)
            
            messages.success(
                request,
                f'✅ 預訂訂單 #{order.id} 建立成功！'
                f'{"（為 " + order_for_name + " 預訂）" if is_for_others else ""}'
                f'<br><br>'
                f'📋 預訂資訊：<br>'
                f'• 訂單金額：${order.total_amount:,.0f}<br>'
                f'• 訂單狀態：<strong>保留中（HOLDING）</strong><br>'
                f'• 訂單來源：<strong>{order.get_order_source_display()}</strong><br>' 
                f'• 庫存狀態：<strong>未扣除</strong><br>'
                f'• 儲值狀態：<strong>未扣款</strong><br>'
                f'<br>'
                f'⚠️ 請在訂單詳情頁面進行後續操作：<br>'
                f'• 確認預訂：扣除庫存、扣除儲值、更新訂單狀態<br>'
                f'• 取消預訂：刪除訂單'
            )
            
            logger.info(
                f'✅ 預訂訂單 #{order.id} 提交成功，'
                f'狀態：HOLDING，'
                f'庫存：未扣除，'
                f'儲值：未扣款'
            )
            
            # 清除 session
            request.session.pop('order_for_account_id', None)
            request.session.pop('order_for_account_name', None)
            request.session.pop('order_for_account_role', None)
            request.session.pop('order_for_account_balance', None)
            
            # 清除購物車 cookie 並跳轉到訂單詳情頁
            response = redirect('business:order_detail', pk=order.id)
            response.delete_cookie('cart')
            return response
            
    except Exception as e:
        logger.error(f'❌ 提交預訂失敗：{str(e)}', exc_info=True)
        messages.error(request, f'❌ 提交預訂失敗：{str(e)}')
        return redirect('business:checkout')


# 提交訂單
@login_required
@require_POST
def submit_order(request):
    """
    提交訂單並扣除庫存
    """
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        with transaction.atomic():
            # 1. 獲取表單資料
            payment_type = request.POST.get('payment_type', PaymentType.TOPUP)
            remark = request.POST.get('remark', '')
            order_source = request.POST.get('order_source', OrderSource.LINE)
            user = request.user
            
            # 2. 從 session 確定訂單帳號
            order_for_account_id = request.session.get('order_for_account_id')
            
            if order_for_account_id and can_order_for_others(user):
                try:
                    order_account = CustomUser.objects.get(
                        id=order_for_account_id,
                        status=AccountStatus.ACTIVE
                    )
                    logger.info(f'為客戶 {order_account.username} 下單')
                except CustomUser.DoesNotExist:
                    messages.error(request, '選擇的帳號不存在或已停用')
                    request.session.pop('order_for_account_id', None)
                    request.session.pop('order_for_account_name', None)
                    request.session.pop('order_for_account_role', None)
                    request.session.pop('order_for_account_balance', None)
                    return redirect('business:checkout')
            else:
                order_account = user
                logger.info(f'為自己 {order_account.username} 下單')
            
            # 3. 從 cookie 獲取購物車
            cart = {}
            cart_cookie = request.COOKIES.get('cart', '{}')
            try:
                from urllib.parse import unquote
                decoded_cookie = unquote(cart_cookie)
                cart = json.loads(decoded_cookie)
            except (json.JSONDecodeError, ValueError):
                messages.error(request, '購物車資料錯誤')
                return redirect('business:cart_view')
            
            if not cart:
                messages.error(request, '購物車是空的')
                return redirect('business:cart_view')
            
            # 4. 驗證購物車商品並檢查庫存
            order_items = []
            total_amount = Decimal('0')
            stock_insufficient_items = []  # 記錄庫存不足的商品
            
            for variant_id, item_data in cart.items():
                try:
                    variant = Variant.objects.select_related('product').get(
                        id=variant_id,
                        status=VariantStatus.ACTIVE,
                        product__status='ACTIVE'
                    )
                    
                    # 直接使用購物車中儲存的價格
                    unit_price = Decimal(str(item_data['unit_price']))
                    
                    if unit_price < 0:
                        messages.error(request, f'商品 {variant.name} 價格異常')
                        return redirect('business:checkout')
                    
                    quantity = item_data['quantity']
                    
                    # 檢查庫存（只統計未使用的庫存）
                    available_stock = Stock.objects.filter(
                        product=variant,
                        is_used=False
                    ).aggregate(
                        total=Sum('quantity')
                    )['total'] or 0
                    
                    logger.info(f'變體 {variant.id} ({variant.name}) - 需要數量：{quantity}，可用庫存：{available_stock}')
                    
                    if available_stock < quantity:
                        stock_insufficient_items.append({
                            'name': variant.name,
                            'required': quantity,
                            'available': available_stock
                        })
                        continue
                    
                    subtotal = unit_price * quantity
                    
                    order_items.append({
                        'variant': variant,
                        'product_code': variant.product_code,
                        'quantity': quantity,
                        'unit_price': unit_price
                    })
                    
                    total_amount += subtotal
                    logger.info(f'訂單項目：{variant.name} x {quantity} @ ${unit_price} = ${subtotal}')
                    
                except Variant.DoesNotExist:
                    messages.error(request, f'商品 {item_data.get("variant_name")} 已下架')
                    return redirect('business:checkout')
            
            # 如果有庫存不足的商品，顯示錯誤並終止
            if stock_insufficient_items:
                error_messages = []
                for item in stock_insufficient_items:
                    error_messages.append(
                        f'{item["name"]}：需要 {item["required"]} 件，庫存僅剩 {item["available"]} 件'
                    )
                messages.error(
                    request,
                    f'❌ 以下商品庫存不足，無法下單：<br>' + '<br>'.join(error_messages)
                )
                return redirect('business:checkout')
            
            logger.info(f'訂單總金額：${total_amount}')
            
            # 5. 如果使用儲值支付，檢查餘額
            if payment_type == PaymentType.TOPUP:
                try:
                    topup = AccountTopUP.objects.select_for_update().get(account=order_account)
                    if topup.balance < total_amount:
                        messages.error(
                            request, 
                            f'儲值餘額不足。需要：${total_amount:,.0f}，可用：${topup.balance:,.0f}'
                        )
                        return redirect('business:checkout')
                except AccountTopUP.DoesNotExist:
                    messages.error(request, '帳號未開通儲值功能')
                    return redirect('business:checkout')
            
            # 6. 建立訂單
            order = Order.objects.create(
                account=order_account,
                created_by=user,
                payment_type=payment_type,
                order_source=order_source,
                status=OrderStatus.PENDING,
                remark=remark
            )
            
            logger.info(
                f'建立訂單 #{order.id}，'
                f'帳號：{order_account.username}，'
                f'創建人：{user.username}，'
                f'來源：{order.get_order_source_display()}'
            )

            # 7. 建立訂單項目並扣除庫存
            for item in order_items:
                # 記錄使用的庫存
                used_stocks_data = []
                
                # 扣除庫存（按 FIFO 原則，優先扣除最早的庫存）
                variant = item['variant']
                remaining_quantity = item['quantity']
                
                # 獲取該變體的所有未使用庫存（按建立時間排序）
                stocks = Stock.objects.filter(
                    product=variant,
                    is_used=False,
                    quantity__gt=0
                ).select_for_update().order_by('created_at')
                
                logger.info(f'開始扣除庫存：變體 {variant.id} ({variant.name})，需扣除 {remaining_quantity} 件')
                
                for stock in stocks:
                    if remaining_quantity <= 0:
                        break
                    
                    # 計算本次可扣除的數量
                    deduct_quantity = min(stock.quantity, remaining_quantity)
                    
                    # 記錄使用的庫存（在修改之前）
                    used_stocks_data.append({
                        'stock_id': stock.id,
                        'deducted_quantity': deduct_quantity,
                        'stock_quantity_before': stock.quantity  # 扣除前的數量
                    })
                    
                    # 更新庫存
                    stock.quantity -= deduct_quantity
                    
                    # 如果庫存扣完，標記為已使用
                    if stock.quantity <= 0:
                        stock.is_used = True
                        stock.exchange_time = timezone.now()
                    
                    stock.save()
                    
                    remaining_quantity -= deduct_quantity
                    
                    logger.info(
                        f'庫存 #{stock.id} 扣除 {deduct_quantity} 件，'
                        f'剩餘 {stock.quantity} 件，'
                        f'{"已用完" if stock.is_used else "仍有庫存"}'
                    )
                
                # 檢查是否成功扣除所有庫存
                if remaining_quantity > 0:
                    logger.error(
                        f'庫存扣除失敗：變體 {variant.id} ({variant.name})，'
                        f'仍需扣除 {remaining_quantity} 件'
                    )
                    raise Exception(f'庫存不足：{variant.name}')
                
                # 建立訂單項目（包含使用的庫存記錄）
                OrderProduct.objects.create(
                    order=order,
                    variant=item['variant'],
                    product_code=item['product_code'],
                    quantity=item['quantity'],
                    unit_price=item['unit_price'],
                    used_stocks=used_stocks_data  # 儲存使用的庫存記錄
                )
                
                logger.info(f'✅ 成功扣除庫存：變體 {variant.id} ({variant.name})，共 {item["quantity"]} 件')
                logger.info(f'使用的庫存記錄：{used_stocks_data}')
            
            # 8. 如果使用儲值支付，扣款並記錄
            if payment_type == PaymentType.TOPUP:
                balance_before = topup.balance
                topup.balance -= total_amount
                topup.save()
                
                AccountTopUPLog.objects.create(
                    topup=topup,
                    order=order,
                    amount=-total_amount,
                    balance_before=balance_before,
                    balance_after=topup.balance,
                    log_type=TopupType.CONSUMPTION,
                    is_confirmed=True,
                    remark=f'訂單 #{order.id} 扣款'
                )
                
                # 儲值支付成功後，訂單狀態改為 PAID（已付款）
                order.status = OrderStatus.PAID
                order.save()
                
                logger.info(f'儲值扣款：${total_amount}，餘額 ${balance_before} → ${topup.balance}')
            
            
            # 10. 清空購物車和 session
            order_for_name = order_account.fullname or order_account.username
            is_for_others = (order_account != user)
            
            # 準備成功訊息
            success_message = (
                f'訂單 #{order.id} 建立成功！'
                f'{"（為 " + order_for_name + " 下單）" if is_for_others else ""}'
                f'<br><br>'
                f'訂單資訊：<br>'
                f'• 訂單總額：${order.total_amount:,.0f}<br>'
                f'• 支付方式：{order.get_payment_type_display()}<br>'
                f'• 訂單狀態：{order.get_status_display()}<br>'
            )
            
            if payment_type == PaymentType.TOPUP:
                success_message += f'• 已從儲值扣款並扣除庫存<br>'
            else:
                success_message += f'• 請完成付款<br>'
            
            # 收據會由 Signal 自動創建
            success_message += f'<br>📄 收據將自動生成'
            
            messages.success(request, success_message)
            
            logger.info(f'訂單 #{order.id} 提交成功，已扣除庫存，收據由 Signal 自動生成')
            
            # 清除 session
            request.session.pop('order_for_account_id', None)
            request.session.pop('order_for_account_name', None)
            request.session.pop('order_for_account_role', None)
            request.session.pop('order_for_account_balance', None)
            
            # 清除購物車 cookie 並跳轉到訂單詳情頁
            response = redirect('business:order_detail', pk=order.id)
            response.delete_cookie('cart')
            return response
            
    except Exception as e:
        logger.error(f'提交訂單失敗：{str(e)}', exc_info=True)
        messages.error(request, f'提交訂單失敗：{str(e)}')
        return redirect('business:checkout')


# 更新預訂訂單產品數量
@login_required
@require_POST
def update_reservation_product_quantity(request, order_id, product_id):
    """
    更新預訂訂單產品的數量（僅限 HOLDING 狀態）
    
    AJAX 請求
    POST: quantity (required)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # 權限檢查：只有總公司管理員可以編輯
    if not is_headquarter_admin(request.user):
        return JsonResponse({
            'success': False,
            'error': '權限不足：只有總公司管理員可以編輯預訂訂單'
        }, status=403)
    
    try:
        with transaction.atomic():
            # 1. 獲取訂單
            try:
                order = Order.objects.select_related('account').get(pk=order_id)
            except Order.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': f'訂單 #{order_id} 不存在'
                }, status=404)
            
            # 2. 檢查訂單狀態（只能編輯 HOLDING 狀態的訂單）
            if order.status != OrderStatus.HOLDING:
                return JsonResponse({
                    'success': False,
                    'error': f'只能編輯預訂狀態（HOLDING）的訂單，目前狀態：{order.get_status_display()}'
                }, status=400)
            
            # 3. 獲取訂單產品
            try:
                order_product = OrderProduct.objects.select_related('variant').get(
                    id=product_id,
                    order=order
                )
            except OrderProduct.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': f'訂單產品 #{product_id} 不存在'
                }, status=404)
            
            # 4. 獲取新數量
            try:
                new_quantity = int(request.POST.get('quantity', 1))
                if new_quantity < 1:
                    new_quantity = 1
                if new_quantity > 999:
                    new_quantity = 999
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'error': '數量格式錯誤'
                }, status=400)
            
            # 5. 更新數量
            old_quantity = order_product.quantity
            order_product.quantity = new_quantity
            order_product.save()
            
            # 6. 重新計算訂單總額
            order.refresh_from_db()
            new_subtotal = order_product.amount
            new_total = order.total_amount
            
            logger.info(
                f'✅ 更新預訂產品數量：訂單 #{order.id}，'
                f'產品 {order_product.variant.name}，'
                f'數量 {old_quantity} → {new_quantity}，'
                f'小計 ${new_subtotal}'
            )
            
            return JsonResponse({
                'success': True,
                'quantity': new_quantity,
                'subtotal': float(new_subtotal),
                'total': float(new_total),
                'message': f'已更新數量：{old_quantity} → {new_quantity}'
            })
            
    except Exception as e:
        logger.error(f'❌ 更新預訂產品數量失敗：{str(e)}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'更新失敗：{str(e)}'
        }, status=500)


# 新增預訂訂單產品
@login_required
@require_POST
def add_reservation_product(request, order_id):
    """
    為預訂訂單新增產品（僅限 HOLDING 狀態）
    
    AJAX 請求
    POST: variant_id (required), quantity (required)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # 權限檢查：只有總公司管理員可以編輯
    if not is_headquarter_admin(request.user):
        return JsonResponse({
            'success': False,
            'error': '權限不足：只有總公司管理員可以編輯預訂訂單'
        }, status=403)
    
    try:
        with transaction.atomic():
            # 1. 獲取訂單
            try:
                order = Order.objects.select_related('account').get(pk=order_id)
            except Order.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': f'訂單 #{order_id} 不存在'
                }, status=404)
            
            # 2. 檢查訂單狀態（只能編輯 HOLDING 狀態的訂單）
            if order.status != OrderStatus.HOLDING:
                return JsonResponse({
                    'success': False,
                    'error': f'只能編輯預訂狀態（HOLDING）的訂單，目前狀態：{order.get_status_display()}'
                }, status=400)
            
            # 3. 獲取產品變體和數量
            try:
                variant_id = int(request.POST.get('variant_id'))
                quantity = int(request.POST.get('quantity', 1))
                
                if quantity < 1:
                    quantity = 1
                if quantity > 999:
                    quantity = 999
                
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'error': '參數格式錯誤'
                }, status=400)
            
            # 4. 獲取變體
            try:
                variant = Variant.objects.select_related('product').get(
                    id=variant_id,
                    status=VariantStatus.ACTIVE,
                    product__status='ACTIVE'
                )
            except Variant.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': '產品不存在或已下架'
                }, status=404)
            
            # 5. 檢查是否已經存在相同產品（如果存在，累加數量）
            existing_product = OrderProduct.objects.filter(
                order=order,
                variant=variant
            ).first()
            
            if existing_product:
                existing_product.quantity += quantity
                existing_product.save()
                
                logger.info(
                    f'✅ 累加預訂產品數量：訂單 #{order.id}，'
                    f'產品 {variant.name}，'
                    f'新增 {quantity} 件，'
                    f'總數 {existing_product.quantity} 件'
                )
                
                # 重新計算訂單總額
                order.refresh_from_db()
                
                return JsonResponse({
                    'success': True,
                    'action': 'updated',
                    'product_id': existing_product.id,
                    'quantity': existing_product.quantity,
                    'subtotal': float(existing_product.amount),
                    'total': float(order.total_amount),
                    'message': f'已累加數量：{variant.name} x {quantity}'
                })
            
            # 6. 獲取價格（使用當前用戶角色對應的價格）
            user = request.user
            display_price, _ = get_variant_display_price(variant, user)
            unit_price = Decimal(str(display_price))
            
            # 7. 建立新的訂單產品
            new_product = OrderProduct.objects.create(
                order=order,
                variant=variant,
                product_code=variant.product_code,
                quantity=quantity,
                unit_price=unit_price,
                used_stocks=[]  # 預訂訂單不記錄庫存
            )
            
            logger.info(
                f'✅ 新增預訂產品：訂單 #{order.id}，'
                f'產品 {variant.name}，'
                f'數量 {quantity} 件，'
                f'單價 ${unit_price}'
            )
            
            # 8. 重新計算訂單總額
            order.refresh_from_db()
            
            # 9. 準備回傳的產品資訊
            product_data = {
                'id': new_product.id,
                'variant_name': variant.name,
                'product_code': variant.product_code,
                'product_type_display': variant.get_product_type_display(),
                'days': variant.days or '',
                'data_amount': variant.data_amount or '',
                'quantity': quantity,
                'unit_price': float(unit_price),
                'subtotal': float(new_product.amount)
            }
            
            return JsonResponse({
                'success': True,
                'action': 'added',
                'product': product_data,
                'total': float(order.total_amount),
                'message': f'已新增產品：{variant.name} x {quantity}'
            })
            
    except Exception as e:
        logger.error(f'❌ 新增預訂產品失敗：{str(e)}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'新增失敗：{str(e)}'
        }, status=500)


# 確認預訂訂單（扣庫存、扣款、改狀態）
@login_required
@require_POST
def confirm_reservation(request, order_id):
    """
    確認預訂訂單
    
    功能：
    1. 檢查庫存是否足夠
    2. 扣除庫存並記錄 used_stocks
    3. 扣除儲值並建立異動記錄
    4. 將訂單狀態從 HOLDING 改為 PAID
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # 權限檢查：只有總公司管理員可以確認
    if not is_headquarter_admin(request.user):
        messages.error(request, '權限不足：只有總公司管理員可以確認預訂訂單')
        return redirect('business:order_detail', pk=order_id)
    
    try:
        with transaction.atomic():
            # 1. 獲取訂單
            try:
                order = Order.objects.select_related('account').prefetch_related(
                    'order_products',
                    'order_products__variant'
                ).get(pk=order_id)
            except Order.DoesNotExist:
                messages.error(request, f'訂單 #{order_id} 不存在')
                return redirect('business:order_list')
            
            # 2. 檢查訂單狀態
            if order.status != OrderStatus.HOLDING:
                messages.error(
                    request,
                    f'只能確認預訂狀態（HOLDING）的訂單，目前狀態：{order.get_status_display()}'
                )
                return redirect('business:order_detail', pk=order_id)
            
            # 3. 檢查庫存
            stock_insufficient_items = []
            
            for order_product in order.order_products.all():
                variant = order_product.variant
                if not variant:
                    continue
                
                # 計算可用庫存
                available_stock = Stock.objects.filter(
                    product=variant,
                    is_used=False
                ).aggregate(total=Sum('quantity'))['total'] or 0
                
                if available_stock < order_product.quantity:
                    stock_insufficient_items.append({
                        'name': variant.name,
                        'required': order_product.quantity,
                        'available': available_stock
                    })
            
            # 如果有庫存不足的商品，顯示錯誤
            if stock_insufficient_items:
                error_messages = []
                for item in stock_insufficient_items:
                    error_messages.append(
                        f'{item["name"]}：需要 {item["required"]} 件，庫存僅剩 {item["available"]} 件'
                    )
                messages.error(
                    request,
                    f'❌ 以下商品庫存不足，無法確認預訂：<br>' + '<br>'.join(error_messages)
                )
                return redirect('business:order_detail', pk=order_id)
            
            # 4. 檢查儲值餘額
            payment_type = order.payment_type
            total_amount = order.total_amount
            order_account = order.account
            
            if payment_type == PaymentType.TOPUP:
                try:
                    topup = AccountTopUP.objects.select_for_update().get(account=order_account)
                    if topup.balance < total_amount:
                        messages.error(
                            request,
                            f'儲值餘額不足。需要：${total_amount:,.0f}，可用：${topup.balance:,.0f}'
                        )
                        return redirect('business:order_detail', pk=order_id)
                except AccountTopUP.DoesNotExist:
                    messages.error(request, '帳號未開通儲值功能')
                    return redirect('business:order_detail', pk=order_id)
            
            # 5. 扣除庫存
            for order_product in order.order_products.all():
                variant = order_product.variant
                if not variant:
                    continue
                
                used_stocks_data = []
                remaining_quantity = order_product.quantity
                
                # 獲取該變體的所有未使用庫存（按 FIFO）
                stocks = Stock.objects.filter(
                    product=variant,
                    is_used=False,
                    quantity__gt=0
                ).select_for_update().order_by('created_at')
                
                for stock in stocks:
                    if remaining_quantity <= 0:
                        break
                    
                    deduct_quantity = min(stock.quantity, remaining_quantity)
                    
                    # 記錄使用的庫存
                    used_stocks_data.append({
                        'stock_id': stock.id,
                        'deducted_quantity': deduct_quantity,
                        'stock_quantity_before': stock.quantity
                    })
                    
                    # 更新庫存
                    stock.quantity -= deduct_quantity
                    if stock.quantity <= 0:
                        stock.is_used = True
                        stock.exchange_time = timezone.now()
                    stock.save()
                    
                    remaining_quantity -= deduct_quantity
                
                # 更新訂單產品的 used_stocks
                order_product.used_stocks = used_stocks_data
                order_product.save()
                
                logger.info(
                    f'✅ 扣除庫存：變體 {variant.id} ({variant.name})，'
                    f'共 {order_product.quantity} 件，'
                    f'使用 {len(used_stocks_data)} 筆庫存'
                )
            
            # 6. 扣除儲值
            if payment_type == PaymentType.TOPUP:
                balance_before = topup.balance
                topup.balance -= total_amount
                topup.save()
                
                AccountTopUPLog.objects.create(
                    topup=topup,
                    order=order,
                    amount=-total_amount,
                    balance_before=balance_before,
                    balance_after=topup.balance,
                    log_type=TopupType.CONSUMPTION,
                    is_confirmed=True,
                    remark=f'預訂訂單 #{order.id} 確認扣款'
                )
                
                logger.info(
                    f'✅ 儲值扣款：${total_amount}，'
                    f'餘額 ${balance_before} → ${topup.balance}'
                )
            
            # 7. 更新訂單狀態
            order.status = OrderStatus.PAID
            order.save()
            
            messages.success(
                request,
                f'✅ 預訂訂單 #{order.id} 已確認！<br>'
                f'• 已扣除庫存<br>'
                f'• 已扣除儲值 ${total_amount:,.0f}<br>'
                f'• 訂單狀態已更新為「已付款」'
            )
            
            logger.info(f'✅ 預訂訂單 #{order.id} 確認成功')
            
            return redirect('business:order_detail', pk=order_id)
            
    except Exception as e:
        logger.error(f'❌ 確認預訂訂單失敗：{str(e)}', exc_info=True)
        messages.error(request, f'❌ 確認預訂失敗：{str(e)}')
        return redirect('business:order_detail', pk=order_id)


# 全部訂單列表
class OrderListView(LoginRequiredMixin, ListView):
    """
    訂單列表視圖
    
    權限規則：
    1. 總公司管理員（超級用戶）：
       - 可查看所有訂單（默認）
       - 可切換查看自己的訂單（view_mode=my_orders）
    2. 代理商：可查看自己和下級分銷商的訂單
    3. 分銷商：只能查看自己的訂單
    
    功能：
    - 視圖模式切換（僅 HEADQUARTER）：全部訂單/我的訂單
    - 時間篩選：今日/本週/本月/全部訂單（預設今日）
    - 日期篩選：選擇特定日期或日期區間
    - 狀態篩選：PENDING/WAIT/PAID/HOLDING/WAIT_SHIP/SHIPPING/WAIT_PICKUP/DONE/CANCELLED
    - 支付方式篩選：TOPUP/CASH/DIRECT_BANK_TRANSFER
    - 訂單來源篩選：SHOPEE/WEBSITE/LINE/FACEBOOK/HANDOVER/PEER/GIFT/OTHER
    - 搜尋：訂單編號/帳號名稱/產品代碼
    - 排序：按建立時間降序排序
    - 分頁：每頁 20 筆
    """
    model = Order
    template_name = 'business/order_list.html'
    context_object_name = 'orders'
    paginate_by = 20
    
    def get_queryset(self):
        """
        根據用戶權限和篩選條件返回訂單列表
        """
        from datetime import datetime, timedelta
        from django.utils import timezone
        import pytz
        import logging
        
        logger = logging.getLogger(__name__)
        
        user = self.request.user
        queryset = Order.objects.select_related(
            'account',
            'account__parent',
            'created_by'
        ).prefetch_related(
            'order_products',
            'order_products__variant',
            'order_products__variant__product'
        ).all()
        
        # ✅ 1. 權限過濾（新增視圖模式切換）
        view_mode = self.request.GET.get('view_mode', 'all')  # 默認為 'all'
        
        if is_headquarter_admin(user):
            # 總公司管理員：根據 view_mode 決定查看範圍
            if view_mode == 'my_orders':
                # 只查看自己的訂單（account = 當前 HEADQUARTER 用戶）
                queryset = queryset.filter(account=user)
                logger.info(f'HEADQUARTER 用戶 {user.username} 查看自己的訂單')
            else:
                # 默認：查看所有訂單
                logger.info(f'HEADQUARTER 用戶 {user.username} 查看全部訂單')
                pass
        elif is_agent(user):
            # 代理商：查看自己和下級分銷商的訂單
            distributor_ids = CustomUser.objects.filter(
                parent=user,
                role=AccountRole.DISTRIBUTOR,
                status=AccountStatus.ACTIVE
            ).values_list('id', flat=True)
            
            queryset = queryset.filter(
                Q(account=user) | Q(account__id__in=distributor_ids)
            )
        else:
            # 其他用戶（分銷商/PEER/USER）：只能查看自己的訂單
            queryset = queryset.filter(account=user)
        
        # 2. 時間篩選（使用台北時區）
        time_range = self.request.GET.get('time_range', 'today')
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        
        # 使用台北時區
        taipei_tz = pytz.timezone('Asia/Taipei')
        now_taipei = timezone.now().astimezone(taipei_tz)
        today_taipei = now_taipei.date()
        
        # 優先使用日期區間篩選（如果有提供）
        if date_from or date_to:
            try:
                if date_from and date_to:
                    # 日期區間查詢（使用台北時區）
                    start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
                    end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
                    
                    if start_date > end_date:
                        start_date, end_date = end_date, start_date
                    
                    # 轉換為台北時區的 datetime
                    start_datetime = taipei_tz.localize(datetime.combine(start_date, datetime.min.time()))
                    end_datetime = taipei_tz.localize(datetime.combine(end_date, datetime.max.time()))
                    
                    queryset = queryset.filter(
                        created_at__gte=start_datetime,
                        created_at__lte=end_datetime
                    )
                    logger.info(f'日期區間篩選（台北時間）：{start_date} 到 {end_date}')
                    
                elif date_from:
                    start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
                    start_datetime = taipei_tz.localize(datetime.combine(start_date, datetime.min.time()))
                    queryset = queryset.filter(created_at__gte=start_datetime)
                    logger.info(f'開始日期篩選（台北時間）：從 {start_date} 開始')
                    
                elif date_to:
                    end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
                    end_datetime = taipei_tz.localize(datetime.combine(end_date, datetime.max.time()))
                    queryset = queryset.filter(created_at__lte=end_datetime)
                    logger.info(f'結束日期篩選（台北時間）：到 {end_date}')
                    
            except ValueError as e:
                logger.error(f'日期格式錯誤：{str(e)}')
        
        # 如果沒有使用日期區間，則使用快速篩選
        elif time_range != 'all':
            if time_range == 'today':
                # 今日訂單（台北時間 00:00:00 ~ 23:59:59）
                start_datetime = taipei_tz.localize(datetime.combine(today_taipei, datetime.min.time()))
                end_datetime = taipei_tz.localize(datetime.combine(today_taipei, datetime.max.time()))
                
                queryset = queryset.filter(
                    created_at__gte=start_datetime,
                    created_at__lte=end_datetime
                )
                logger.info(f'今日訂單篩選（台北時間）：{today_taipei}')
                
            elif time_range == 'week':
                # 本週訂單（週一到今天，台北時間）
                start_of_week = today_taipei - timedelta(days=today_taipei.weekday())
                start_datetime = taipei_tz.localize(datetime.combine(start_of_week, datetime.min.time()))
                end_datetime = taipei_tz.localize(datetime.combine(today_taipei, datetime.max.time()))
                
                queryset = queryset.filter(
                    created_at__gte=start_datetime,
                    created_at__lte=end_datetime
                )
                logger.info(f'本週訂單篩選（台北時間）：{start_of_week} 到 {today_taipei}')
                
            elif time_range == 'month':
                # 本月訂單（台北時間）
                first_day = today_taipei.replace(day=1)
                start_datetime = taipei_tz.localize(datetime.combine(first_day, datetime.min.time()))
                end_datetime = taipei_tz.localize(datetime.combine(today_taipei, datetime.max.time()))
                
                queryset = queryset.filter(
                    created_at__gte=start_datetime,
                    created_at__lte=end_datetime
                )
                logger.info(f'本月訂單篩選（台北時間）：{today_taipei.year}-{today_taipei.month}')
        
        # 3. 狀態篩選
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        # 4. 支付方式篩選
        payment_type = self.request.GET.get('payment_type')
        if payment_type:
            queryset = queryset.filter(payment_type=payment_type)
        
        # 5. 訂單來源篩選
        order_source = self.request.GET.get('order_source')
        if order_source:
            queryset = queryset.filter(order_source=order_source)
            logger.info(f'訂單來源篩選：{order_source}')
        
        # 6. 搜尋功能（訂單編號、帳號名稱、產品代碼）
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(id__icontains=search_query) |  # 訂單編號
                Q(account__username__icontains=search_query) |  # 帳號
                Q(account__fullname__icontains=search_query) |  # 姓名
                Q(account__company__icontains=search_query) |  # 公司
                Q(order_products__product_code__icontains=search_query) |  # 產品代碼
                Q(order_products__variant__name__icontains=search_query) |  # 產品名稱
                Q(remark__icontains=search_query)  # 備註
            ).distinct()
        
        # 7. 排序（使用 OrderStatus 定義的順序）
        from django.db.models import Case, When, IntegerField
        
        queryset = queryset.annotate(
            status_order=Case(
                When(status=OrderStatus.PENDING, then=1),
                When(status=OrderStatus.WAIT, then=2),
                When(status=OrderStatus.PAID, then=3),
                When(status=OrderStatus.WAIT_SHIP, then=4),
                When(status=OrderStatus.SHIPPING, then=5),
                When(status=OrderStatus.WAIT_PICKUP, then=6),
                When(status=OrderStatus.DONE, then=7),
                When(status=OrderStatus.CANCELLED, then=8),
                default=9,
                output_field=IntegerField(),
            )
        ).order_by('-created_at', 'status_order')
        
        return queryset
    
    def get_context_data(self, **kwargs):
        """
        添加額外的 context 資料
        """
        import pytz
        from django.utils import timezone
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # 傳遞台北時間的今日日期（供日期選擇器使用）
        taipei_tz = pytz.timezone('Asia/Taipei')
        today_taipei = timezone.now().astimezone(taipei_tz).date()
        context['today'] = today_taipei
        
        # ✅ 傳遞視圖模式（僅 HEADQUARTER 可用）
        context['view_mode'] = self.request.GET.get('view_mode', 'all')
        context['can_switch_view'] = is_headquarter_admin(user)  # 只有總公司可以切換
        
        # 1. 傳遞篩選選項
        context['order_statuses'] = OrderStatus.choices
        context['payment_types'] = PaymentType.choices
        context['order_sources'] = OrderSource.choices
        context['time_ranges'] = [
            ('today', '今日訂單'),
            ('week', '本週訂單'),
            ('month', '本月訂單'),
            ('all', '全部訂單'),
        ]
        
        # 2. 傳遞當前篩選條件
        context['selected_time_range'] = self.request.GET.get('time_range', 'today')
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_payment_type'] = self.request.GET.get('payment_type', '')
        context['selected_order_source'] = self.request.GET.get('order_source', '') 
        context['search_query'] = self.request.GET.get('q', '')
        
        # ✅ 傳遞日期篩選條件
        context['date_from'] = self.request.GET.get('date_from', '')
        context['date_to'] = self.request.GET.get('date_to', '')
        
        # 3. 統計資料（根據當前篩選條件）
        orders = self.get_queryset()
        
        context['total_orders'] = orders.count()
        
        # ✅ 按所有狀態統計
        context['holding_count'] = orders.filter(status=OrderStatus.HOLDING).count()  
        context['pending_count'] = orders.filter(status=OrderStatus.PENDING).count()
        context['wait_count'] = orders.filter(status=OrderStatus.WAIT).count()
        context['paid_count'] = orders.filter(status=OrderStatus.PAID).count()
        context['wait_ship_count'] = orders.filter(status=OrderStatus.WAIT_SHIP).count()
        context['shipping_count'] = orders.filter(status=OrderStatus.SHIPPING).count()
        context['wait_pickup_count'] = orders.filter(status=OrderStatus.WAIT_PICKUP).count()
        context['done_count'] = orders.filter(status=OrderStatus.DONE).count()
        context['cancelled_count'] = orders.filter(status=OrderStatus.CANCELLED).count()
        
        # 4. 權限資訊
        context['is_headquarter'] = is_headquarter_admin(user)
        context['is_agent'] = is_agent(user)
        context['is_distributor'] = is_distributor(user)
        
        # 5. 當前用戶資訊
        context['current_user'] = user
        context['user_role_display'] = get_user_role_display(user)
        
        return context


# 訂單詳細
class OrderDetailView(LoginRequiredMixin, DetailView):
    """
    訂單詳細視圖
    
    權限規則：
    1. 總公司管理員（超級用戶）：可查看所有訂單
    2. 代理商：可查看自己和下級分銷商的訂單
    3. 分銷商：只能查看自己的訂單
    
    顯示內容：
    1. 訂單基本資訊（訂單編號、狀態、支付方式、建立時間等）
    2. 訂單帳號資訊（帳號名稱、角色、公司等）
    3. 訂單產品列表（產品名稱、規格、數量、單價、小計）
    4. 金額統計（商品總額、運費、訂單總額）
    5. 備註資訊（客戶備註、管理員備註）
    6. Joytel 相關參數（如果有）
    """
    model = Order
    template_name = 'business/order_detail.html'
    context_object_name = 'order'
    
    def get_queryset(self):
        """
        根據用戶權限過濾可查看的訂單
        """
        user = self.request.user
        queryset = Order.objects.select_related(
            'account',
            'account__parent',
            'created_by'
        ).prefetch_related(
            'order_products',
            'order_products__variant',
            'order_products__variant__product'
        ).all()
        
        # 權限過濾
        if is_headquarter_admin(user):
            # 總公司管理員：查看所有訂單
            pass
        elif is_agent(user):
            # 代理商：查看自己和下級分銷商的訂單
            distributor_ids = CustomUser.objects.filter(
                parent=user,
                role=AccountRole.DISTRIBUTOR,
                status=AccountStatus.ACTIVE
            ).values_list('id', flat=True)
            
            queryset = queryset.filter(
                Q(account=user) | Q(account__id__in=distributor_ids)
            )
        else:
            # 其他用戶（分銷商）：只能查看自己的訂單
            queryset = queryset.filter(account=user)
        
        return queryset
    
    def get_object(self, queryset=None):
        """
        獲取訂單對象，如果用戶無權限則返回 403
        """
        obj = super().get_object(queryset)
        user = self.request.user
        
        # 二次權限檢查
        if not is_headquarter_admin(user):
            if is_agent(user):
                # 代理商：檢查是否為自己或下級分銷商的訂單
                if obj.account != user:
                    distributor_ids = CustomUser.objects.filter(
                        parent=user,
                        role=AccountRole.DISTRIBUTOR,
                        status=AccountStatus.ACTIVE
                    ).values_list('id', flat=True)
                    
                    if obj.account.id not in distributor_ids:
                        messages.error(self.request, '您沒有權限查看此訂單')
                        return redirect('business:order_list')
            else:
                # 分銷商：只能查看自己的訂單
                if obj.account != user:
                    messages.error(self.request, '您沒有權限查看此訂單')
                    return redirect('business:order_list')
        
        return obj
    
    def get_context_data(self, **kwargs):
        """
        添加額外的 context 資料
        """
        context = super().get_context_data(**kwargs)
        order = self.object
        user = self.request.user
        
        # 1. 訂單產品列表
        order_products = order.order_products.all()
        
        # 按產品類型分類（處理 variant 可能為 None 的情況）
        esimimg_products = []
        rechargeable_products = []
        physical_products = []
        
        for item in order_products:
            # 檢查 variant 是否存在，並從 variant 獲取 product_type
            if item.variant and hasattr(item.variant, 'product_type'):
                product_type = item.variant.product_type
                if product_type == ProductType.ESIMIMG:
                    esimimg_products.append(item)
                elif product_type == ProductType.RECHARGEABLE:
                    rechargeable_products.append(item)
                elif product_type == ProductType.PHYSICAL:
                    physical_products.append(item)
        
        context['esimimg_products'] = esimimg_products
        context['rechargeable_products'] = rechargeable_products
        context['physical_products'] = physical_products
        
        # 2. 金額統計
        context['product_total'] = order.amount  # 商品總額（不含運費）
        context['shipping_fee'] = order.shipping_fee or 0
        context['order_total'] = order.total_amount  # 訂單總額（含運費）
        
        # 3. 訂單狀態資訊
        context['status_display'] = order.get_status_display()
        context['payment_type_display'] = order.get_payment_type_display()
        
        # 4. 儲值扣款記錄（如果使用儲值支付）
        if order.payment_type == PaymentType.TOPUP:
            topup_log = AccountTopUPLog.objects.filter(
                order=order,
                log_type=TopupType.CONSUMPTION
            ).first()
            context['topup_log'] = topup_log
        else:
            context['topup_log'] = None
        
        # 5. 權限資訊
        context['is_headquarter'] = is_headquarter_admin(user)
        context['is_agent'] = is_agent(user)
        context['is_distributor'] = is_distributor(user)
        
        # 6. 判斷是否可以修改訂單
        context['can_edit'] = is_headquarter_admin(user) and order.status in [
            OrderStatus.PENDING,
            OrderStatus.WAIT
        ]
        
        # 7. 判斷是否可以取消訂單
        context['can_delete_product'] = is_headquarter_admin(user) and order.status in [
            OrderStatus.PENDING,
            OrderStatus.PAID,
            OrderStatus.WAIT
        ]
        
        # 8. 建立人資訊
        context['is_created_by_others'] = (
            order.created_by and 
            order.created_by != order.account
        )

        # 9. 如果是預訂訂單且用戶有權限，傳遞可用產品列表
        if order.status == OrderStatus.HOLDING and is_headquarter_admin(user):
            context['all_variants'] = Variant.objects.filter(
                status=VariantStatus.ACTIVE,
                product__status='ACTIVE'
            ).select_related('product').order_by('product__name', 'sort_order')
        
        # 10. 修改：獲取該訂單的所有資金異動記錄（包含扣款與退款）
        # 假設 AccountTopUPLog 模型有 order 欄位關聯到 Order
        
        
        context['transaction_logs'] = AccountTopUPLog.objects.filter(
            order=self.object
        ).order_by('created_at')  # 按時間順序排列
        
        return context


# 訂單產品詳細
class OrderProductDetailView(LoginRequiredMixin, DetailView):
    """
    訂單產品詳細視圖
    
    顯示單一訂單產品的詳細資訊，包含：
    1. 產品基本資料（變體、代碼、價格）
    2. 兌換狀態（正常、失敗等）
    3. 庫存使用記錄
    4. ESIMIMG：QR Code 圖片、Code、順序編號等
    """
    model = OrderProduct
    template_name = 'business/order_product_detail.html'
    context_object_name = 'order_product'
    pk_url_kwarg = 'product_id'
    
    def get_queryset(self):
        """
        權限控制：確保用戶只能查看自己權限內的訂單產品
        """
        user = self.request.user
        queryset = OrderProduct.objects.select_related(
            'order',
            'order__account',
            'variant',
            'variant__product'
        ).all()

        # 確保產品屬於 URL 指定的訂單（資料一致性檢查）
        order_id = self.kwargs.get('order_id')
        if order_id:
            queryset = queryset.filter(order__id=order_id)
        
        # 權限過濾 (邏輯同 OrderDetailView)
        if is_headquarter_admin(user):
            pass
        elif is_agent(user):
            distributor_ids = CustomUser.objects.filter(
                parent=user,
                role=AccountRole.DISTRIBUTOR,
                status=AccountStatus.ACTIVE
            ).values_list('id', flat=True)
            
            queryset = queryset.filter(
                Q(order__account=user) | Q(order__account__id__in=distributor_ids)
            )
        else:
            queryset = queryset.filter(order__account=user)
            
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_product = self.object
        
        # 傳遞權限資訊
        user = self.request.user
        context['is_headquarter'] = is_headquarter_admin(user)
        
        # 解析 used_stocks JSON 資料，獲取詳細庫存資訊
        used_stocks_details = []
        if order_product.used_stocks:
            for stock_record in order_product.used_stocks:
                stock_id = stock_record.get('stock_id')
                try:
                    stock = Stock.objects.get(id=stock_id)
                    used_stocks_details.append({
                        'stock': stock,
                        'deducted_quantity': stock_record.get('deducted_quantity'),
                        'stock_quantity_before': stock_record.get('stock_quantity_before')
                    })
                except Stock.DoesNotExist:
                    # 如果庫存已被刪除，顯示基本資訊
                    used_stocks_details.append({
                        'stock': None,
                        'stock_id': stock_id,
                        'deducted_quantity': stock_record.get('deducted_quantity'),
                        'note': '庫存記錄已刪除'
                    })
        
        context['used_stocks_details'] = used_stocks_details
        
        # 如果是 ESIMIMG 類型，提取 QR Code 資訊
        if order_product.variant and order_product.variant.product_type == ProductType.ESIMIMG:
            esimimg_details = []
            
            # 從 used_stocks 中獲取每個庫存的詳細資訊
            for idx, stock_record in enumerate(order_product.used_stocks, start=1):
                stock_id = stock_record.get('stock_id')
                deducted_quantity = stock_record.get('deducted_quantity', 0)
                
                try:
                    stock = Stock.objects.get(id=stock_id)
                    
                    # ESIMIMG 每個 Stock 應該對應一張圖片 (quantity=1)
                    # 但為了相容舊資料，還是檢查 deducted_quantity
                    for _ in range(int(deducted_quantity)):
                        esimimg_details.append({
                            'sequence': len(esimimg_details) + 1,  # 全域順序編號
                            'stock': stock,
                            'code': stock.code,  # QR Code 代碼
                            'qr_img_url': stock.qr_img.url if stock.qr_img else None,  # QR 圖片 URL
                            'product_name': order_product.variant.product.name,  # Product.name
                            'variant_name': order_product.variant.name,  # Variant.name
                            'exchange_time': stock.exchange_time,  # 兌換時間
                            'is_used': stock.is_used,  # 是否已使用
                        })
                        
                except Stock.DoesNotExist:
                    # 庫存已刪除，顯示佔位符
                    for _ in range(int(deducted_quantity)):
                        esimimg_details.append({
                            'sequence': len(esimimg_details) + 1,
                            'stock': None,
                            'code': f'已刪除 (ID: {stock_id})',
                            'qr_img_url': None,
                            'product_name': order_product.variant.product.name if order_product.variant else '未知',
                            'variant_name': order_product.variant.name if order_product.variant else '未知',
                            'exchange_time': None,
                            'is_used': False,
                        })
            
            context['esimimg_details'] = esimimg_details
            context['is_esimimg'] = True
            
            # 計算統計數據（在 Python 中計算，不要在模板中使用 Jinja2 過濾器）
            total_qr_count = len(esimimg_details)
            used_count = sum(1 for item in esimimg_details if item.get('is_used', False))
            unused_count = total_qr_count - used_count
            
            context['total_qr_count'] = total_qr_count
            context['used_qr_count'] = used_count
            context['unused_qr_count'] = unused_count
        else:
            context['esimimg_details'] = []
            context['is_esimimg'] = False
            context['total_qr_count'] = 0
            context['used_qr_count'] = 0
            context['unused_qr_count'] = 0
        
        return context


# RECHARGEABLE 卡號管理視圖
class RechargeableCodesManageView(LoginRequiredMixin, DetailView):
    """
    RECHARGEABLE 產品卡號管理視圖
    
    功能：
    1. 顯示訂單產品的所有卡號（OrderCoupons）
    2. 允許總公司管理員填寫/編輯 sn_code
    3. 每個 sn_code 對應一張實體卡
    4. 儲存後不會立即推送到 API（需手動觸發兌換）
    """
    model = OrderProduct
    template_name = 'business/rechargeable_codes_manage.html'
    context_object_name = 'order_product'
    pk_url_kwarg = 'product_id'
    
    def get_queryset(self):
        """權限控制"""
        user = self.request.user
        queryset = OrderProduct.objects.select_related(
            'order',
            'order__account',
            'variant',
            'variant__product'
        ).all()

        # 確保產品屬於 URL 指定的訂單
        order_id = self.kwargs.get('order_id')
        if order_id:
            queryset = queryset.filter(order__id=order_id)
        
        # 權限過濾
        if is_headquarter_admin(user):
            pass
        elif is_agent(user):
            distributor_ids = CustomUser.objects.filter(
                parent=user,
                role=AccountRole.DISTRIBUTOR,
                status=AccountStatus.ACTIVE
            ).values_list('id', flat=True)
            
            queryset = queryset.filter(
                Q(order__account=user) | Q(order__account__id__in=distributor_ids)
            )
        else:
            queryset = queryset.filter(order__account=user)
            
        return queryset
    
    def get_object(self, queryset=None):
        """獲取訂單產品並檢查是否為 RECHARGEABLE 類型"""
        obj = super().get_object(queryset)
        
        # 檢查產品類型
        if not obj.variant or obj.variant.product_type != ProductType.RECHARGEABLE:
            messages.error(
                self.request,
                '此功能僅適用於充值卡（RECHARGEABLE）類型的產品'
            )
            raise Http404('Product type mismatch')
        
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_product = self.object
        
        # 傳遞權限資訊
        user = self.request.user
        context['is_headquarter'] = is_headquarter_admin(user)
        
        # 獲取或建立 OrderCoupons（根據訂單產品數量）
        existing_coupons = OrderCoupons.objects.filter(
            order_product=order_product
        ).order_by('id')
        
        # 如果現有 Coupon 數量不足，自動建立缺少的 Coupon
        existing_count = existing_coupons.count()
        needed_count = order_product.quantity
        
        if existing_count < needed_count:
            # 建立缺少的 OrderCoupons
            for i in range(needed_count - existing_count):
                OrderCoupons.objects.create(
                    order=order_product.order,
                    order_product=order_product,
                    sn_code=''  # 初始為空，等待填寫
                )
            
            # 重新查詢
            existing_coupons = OrderCoupons.objects.filter(
                order_product=order_product
            ).order_by('id')
        
        # 準備卡號列表（帶序號）
        coupon_list = []
        for idx, coupon in enumerate(existing_coupons, start=1):
            coupon_list.append({
                'sequence': idx,
                'coupon': coupon,
                'sn_code': coupon.sn_code or '',
                'has_code': bool(coupon.sn_code and coupon.sn_code.strip()),
            })
        
        context['coupon_list'] = coupon_list
        context['total_codes'] = len(coupon_list)
        context['filled_codes'] = sum(1 for c in coupon_list if c['has_code'])
        context['empty_codes'] = context['total_codes'] - context['filled_codes']
        
        return context


# 批量儲存 RECHARGEABLE 卡號
@login_required
@require_POST
def save_rechargeable_codes(request, order_id, product_id):
    """
    批量儲存 RECHARGEABLE 產品的卡號
    
    POST 參數：
    - coupon_id_[N]: OrderCoupons ID
    - sn_code_[N]: 卡號
    """
    logger = logging.getLogger(__name__)
    
    # 權限檢查：只有總公司管理員可以編輯
    if not is_headquarter_admin(request.user):
        messages.error(request, '權限不足：只有總公司管理員可以編輯卡號')
        return redirect('business:order_product_detail', order_id=order_id, product_id=product_id)
    
    try:
        with transaction.atomic():
            # 1. 獲取訂單產品
            try:
                order_product = OrderProduct.objects.select_related(
                    'order',
                    'variant'
                ).get(
                    id=product_id,
                    order__id=order_id
                )
            except OrderProduct.DoesNotExist:
                messages.error(request, f'訂單產品不存在')
                return redirect('business:order_detail', pk=order_id)
            
            # 2. 檢查產品類型
            if not order_product.variant or order_product.variant.product_type != ProductType.RECHARGEABLE:
                messages.error(request, '此功能僅適用於充值卡（RECHARGEABLE）類型的產品')
                return redirect('business:order_product_detail', order_id=order_id, product_id=product_id)
            
            # 3. 解析 POST 資料
            updated_count = 0
            duplicate_codes = []
            
            for key, value in request.POST.items():
                if key.startswith('sn_code_'):
                    # 提取 coupon_id
                    coupon_id = key.replace('sn_code_', '')
                    sn_code = value.strip()
                    
                    try:
                        coupon = OrderCoupons.objects.get(
                            id=coupon_id,
                            order_product=order_product
                        )
                        
                        # 檢查 sn_code 是否重複（如果有填寫）
                        if sn_code:
                            # 檢查是否與其他 Coupon 重複（排除自己）
                            duplicate = OrderCoupons.objects.filter(
                                sn_code=sn_code
                            ).exclude(id=coupon.id).exists()
                            
                            if duplicate:
                                duplicate_codes.append(sn_code)
                                continue
                        
                        # 更新 sn_code
                        if coupon.sn_code != sn_code:
                            coupon.sn_code = sn_code
                            coupon.save()
                            updated_count += 1
                            
                    except OrderCoupons.DoesNotExist:
                        logger.warning(f'OrderCoupon {coupon_id} 不存在')
                        continue
            
            # 4. 顯示結果訊息
            if duplicate_codes:
                messages.warning(
                    request,
                    f'⚠️ 以下卡號重複，未儲存：{", ".join(duplicate_codes)}'
                )
            
            if updated_count > 0:
                messages.success(
                    request,
                    f'✅ 已成功儲存 {updated_count} 個卡號'
                )
            else:
                messages.info(request, '沒有變更任何卡號')
            
            logger.info(
                f'✅ RECHARGEABLE 卡號儲存完成：'
                f'訂單 #{order_id}，產品 #{product_id}，'
                f'更新 {updated_count} 筆'
            )
            
            return redirect('business:rechargeable_codes_manage', order_id=order_id, product_id=product_id)
            
    except Exception as e:
        logger.error(f'❌ 儲存 RECHARGEABLE 卡號失敗：{str(e)}', exc_info=True)
        messages.error(request, f'❌ 儲存失敗：{str(e)}')
        return redirect('business:rechargeable_codes_manage', order_id=order_id, product_id=product_id)


# 批量匯入 RECHARGEABLE 卡號（CSV）
@login_required
@require_POST
def import_rechargeable_codes_csv(request, order_id, product_id):
    """
    透過 CSV 批量匯入 RECHARGEABLE 產品的卡號
    
    CSV 格式：
    - 第一欄：序號（可選）
    - 第二欄：卡號 (sn_code)
    
    範例：
    1,ABC123456789
    2,DEF987654321
    3,GHI456789123
    
    或簡化版（只有卡號）：
    ABC123456789
    DEF987654321
    GHI456789123
    """
    logger = logging.getLogger(__name__)
    
    # 權限檢查：只有總公司管理員可以編輯
    # if not is_headquarter_admin(request.user):
    #     return JsonResponse({
    #         'success': False,
    #         'error': '權限不足：只有總公司管理員可以匯入卡號'
    #     }, status=403)
    
    # 檢查是否有上傳檔案
    if 'csv_file' not in request.FILES:
        return JsonResponse({
            'success': False,
            'error': '請選擇 CSV 檔案'
        }, status=400)
    
    csv_file = request.FILES['csv_file']
    
    # 檢查檔案類型
    if not csv_file.name.endswith('.csv'):
        return JsonResponse({
            'success': False,
            'error': '請上傳 CSV 格式的檔案'
        }, status=400)
    
    try:
        with transaction.atomic():
            # 1. 獲取訂單產品
            try:
                order_product = OrderProduct.objects.select_related(
                    'order',
                    'variant'
                ).get(
                    id=product_id,
                    order__id=order_id
                )
            except OrderProduct.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': f'訂單產品不存在'
                }, status=404)
            
            # 2. 檢查產品類型
            if not order_product.variant or order_product.variant.product_type != ProductType.RECHARGEABLE:
                return JsonResponse({
                    'success': False,
                    'error': '此功能僅適用於充值卡（RECHARGEABLE）類型的產品'
                }, status=400)
            
            # 3. 讀取 CSV 檔案
            try:
                # 嘗試使用 UTF-8 編碼讀取
                decoded_file = csv_file.read().decode('utf-8')
            except UnicodeDecodeError:
                try:
                    # 如果 UTF-8 失敗，嘗試 Big5（繁體中文 Excel 常用）
                    csv_file.seek(0)
                    decoded_file = csv_file.read().decode('big5')
                except UnicodeDecodeError:
                    return JsonResponse({
                        'success': False,
                        'error': 'CSV 檔案編碼錯誤，請使用 UTF-8 或 Big5 編碼'
                    }, status=400)
            
            # 4. 解析 CSV
            csv_reader = csv.reader(io.StringIO(decoded_file))
            
            # 讀取所有 sn_code（過濾空白行）
            sn_codes = []
            for row_num, row in enumerate(csv_reader, start=1):
                if not row:  # 跳過空行
                    continue
                
                # 檢查是否為標題行（包含 "序號" 或 "卡號" 等關鍵字）
                if row_num == 1 and any(keyword in str(row).lower() for keyword in ['序號', '卡號', 'sn_code', 'sequence']):
                    logger.info('跳過 CSV 標題行')
                    continue
                
                # 提取卡號（支援兩種格式）
                if len(row) >= 2:
                    # 格式 1：序號,卡號
                    sn_code = row[1].strip()
                elif len(row) >= 1:
                    # 格式 2：只有卡號
                    sn_code = row[0].strip()
                else:
                    continue
                
                if sn_code:
                    sn_codes.append(sn_code)
            
            if not sn_codes:
                return JsonResponse({
                    'success': False,
                    'error': 'CSV 檔案中沒有有效的卡號'
                }, status=400)
            
            logger.info(f'從 CSV 讀取到 {len(sn_codes)} 個卡號')
            
            # 5. 獲取所有 OrderCoupons（按序號排序）
            coupons = OrderCoupons.objects.filter(
                order_product=order_product
            ).order_by('id')
            
            # 6. 檢查數量是否匹配
            coupon_count = coupons.count()
            if len(sn_codes) > coupon_count:
                return JsonResponse({
                    'success': False,
                    'error': f'CSV 中的卡號數量（{len(sn_codes)}）超過訂單產品數量（{coupon_count}）'
                }, status=400)
            
            # 7. 檢查卡號重複
            duplicate_codes = []
            for sn_code in sn_codes:
                # 檢查是否與現有 Coupon 重複（排除即將更新的 Coupon）
                existing_coupon = OrderCoupons.objects.filter(
                    sn_code=sn_code
                ).exclude(
                    order_product=order_product
                ).first()
                
                if existing_coupon:
                    duplicate_codes.append(sn_code)
            
            if duplicate_codes:
                return JsonResponse({
                    'success': False,
                    'error': f'以下卡號已存在於其他訂單：{", ".join(duplicate_codes[:5])}{"..." if len(duplicate_codes) > 5 else ""}'
                }, status=400)
            
            # 8. 批量更新卡號（按順序匹配）
            updated_count = 0
            for idx, coupon in enumerate(coupons):
                if idx < len(sn_codes):
                    new_sn_code = sn_codes[idx]
                    
                    # 只更新有變化的卡號
                    if coupon.sn_code != new_sn_code:
                        coupon.sn_code = new_sn_code
                        coupon.save()
                        updated_count += 1
            
            logger.info(
                f'✅ CSV 批量匯入完成：訂單 #{order_id}，產品 #{product_id}，'
                f'更新 {updated_count} 筆卡號'
            )
            
            return JsonResponse({
                'success': True,
                'updated_count': updated_count,
                'total_codes': len(sn_codes),
                'message': f'成功匯入 {len(sn_codes)} 個卡號，更新 {updated_count} 筆'
            })
            
    except Exception as e:
        logger.error(f'❌ CSV 匯入失敗：{str(e)}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'匯入失敗：{str(e)}'
        }, status=500)


# 刪除訂單
class DeleteOrderView(LoginRequiredMixin, UserPassesTestMixin, View):
    """
    刪除訂單視圖
    
    權限規則：
    - 只有總公司管理員可以刪除訂單
    
    刪除邏輯：
    1. 檢查訂單狀態（只能刪除 PENDING 或 CANCELLED 狀態的訂單）
    2. 恢復庫存數量（將已扣除的庫存補回）
    3. 如果使用儲值支付，退款並記錄異動
    4. 刪除訂單及相關資料
    """
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以刪除訂單
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.error(self.request, '您沒有權限刪除訂單，只有總公司管理員可以執行此操作。')
        return redirect('business:order_list')
    
    def post(self, request, pk):
        """
        處理 POST 請求：刪除訂單
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            with transaction.atomic():
                # 1. 獲取訂單
                try:
                    order = Order.objects.select_related(
                        'account'
                    ).prefetch_related(
                        'order_products',
                        'order_products__variant'
                    ).get(pk=pk)
                except Order.DoesNotExist:
                    messages.error(request, f'訂單 #{pk} 不存在')
                    return redirect('business:order_list')
                
                logger.info(f'準備刪除訂單 #{order.id}，狀態：{order.status}')
                
                # 2. 檢查訂單狀態（只能刪除特定狀態的訂單）
                deletable_statuses = [
                    OrderStatus.PENDING,
                    OrderStatus.CANCELLED,
                    OrderStatus.PAID
                ]
                
                if order.status not in deletable_statuses:
                    messages.error(
                        request,
                        f'無法刪除訂單 #{order.id}：'
                        f'只能刪除「待處理」或「已取消」狀態的訂單。'
                        f'目前狀態：{order.get_status_display()}'
                    )
                    return redirect('business:order_detail', pk=order.id)
                
                # 3. 記錄訂單資訊（用於日誌）
                order_account = order.account
                order_total = order.total_amount
                payment_type = order.payment_type
                
                # 4. 恢復庫存（根據 used_stocks 記錄）
                restored_stocks = []
                
                for order_product in order.order_products.all():
                    variant = order_product.variant
                    
                    if not variant:
                        logger.warning(f'訂單產品 #{order_product.id} 的變體已被刪除，跳過庫存恢復')
                        continue
                    
                    # 從 used_stocks 獲取使用的庫存記錄
                    used_stocks_data = order_product.used_stocks
                    
                    if not used_stocks_data:
                        logger.warning(
                            f'訂單產品 #{order_product.id} 沒有庫存使用記錄，'
                            f'可能是舊資料，跳過庫存恢復'
                        )
                        continue
                    
                    logger.info(
                        f'準備恢復庫存：變體 {variant.id} ({variant.name})，'
                        f'共 {len(used_stocks_data)} 筆庫存記錄'
                    )
                    
                    # 按記錄逐一恢復庫存
                    for stock_data in used_stocks_data:
                        stock_id = stock_data['stock_id']
                        deducted_quantity = stock_data['deducted_quantity']
                        
                        try:
                            stock = Stock.objects.select_for_update().get(id=stock_id)
                            
                            # 恢復庫存數量
                            stock.quantity += deducted_quantity
                            
                            # 如果庫存恢復到大於 0，取消已使用標記
                            if stock.quantity > 0:
                                stock.is_used = False
                                stock.exchange_time = None
                            
                            stock.save()
                            
                            restored_stocks.append({
                                'stock_id': stock.id,
                                'variant_name': variant.name,
                                'restored_quantity': deducted_quantity,
                                'current_quantity': stock.quantity
                            })
                            
                            logger.info(
                                f'庫存 #{stock.id} 恢復 {deducted_quantity} 件，'
                                f'當前數量：{stock.quantity} 件'
                            )
                            
                        except Stock.DoesNotExist:
                            logger.warning(
                                f'❌ 庫存 #{stock_id} 已被刪除，無法恢復 {deducted_quantity} 件'
                            )
                            continue
                
                # 5. 如果使用儲值支付，退款並記錄異動
                refund_log = None
                if payment_type == PaymentType.TOPUP:
                    try:
                        topup = AccountTopUP.objects.select_for_update().get(
                            account=order_account
                        )
                        
                        # 記錄退款前餘額
                        balance_before = topup.balance
                        
                        # 退款
                        topup.balance += order_total
                        topup.save()
                        
                        # 記錄異動
                        refund_log = AccountTopUPLog.objects.create(
                            topup=topup,
                            order=order,
                            amount=order_total,
                            balance_before=balance_before,
                            balance_after=topup.balance,
                            log_type=TopupType.REFUND,
                            is_confirmed=True,
                            remark=f'訂單 #{order.id} 刪除退款'
                        )
                        
                        logger.info(
                            f'儲值退款：訂單 #{order.id}，'
                            f'金額 ${order_total}，'
                            f'餘額 ${balance_before} → ${topup.balance}'
                        )
                        
                    except AccountTopUP.DoesNotExist:
                        logger.error(
                            f'訂單 #{order.id} 使用儲值支付，'
                            f'但找不到帳號 {order_account.username} 的儲值記錄'
                        )
                
                # 6. 刪除訂單相關資料
                # 先刪除儲值異動記錄（如果有）
                AccountTopUPLog.objects.filter(order=order).delete()
                
                # 刪除訂單產品
                order.order_products.all().delete()
                
                # 刪除訂單
                order_id = order.id
                order.delete()
                
                # 7. 成功訊息
                success_message = f'✅ 訂單 #{order_id} 已成功刪除'
                
                if restored_stocks:
                    success_message += f'，已恢復 {len(restored_stocks)} 筆庫存'
                
                if payment_type == PaymentType.TOPUP and refund_log:
                    success_message += f'，已退款 ${order_total:,.0f} 至帳號 {order_account.username}'
                
                messages.success(request, success_message)
                
                logger.info(
                    f'✅ 訂單 #{order_id} 刪除成功，'
                    f'恢復庫存 {len(restored_stocks)} 筆，'
                    f'{"已退款" if refund_log else "無需退款"}'
                )
                
                return redirect('business:order_list')
                
        except Exception as e:
            logger.error(f'刪除訂單失敗：{str(e)}', exc_info=True)
            messages.error(request, f'刪除訂單失敗：{str(e)}')
            return redirect('business:order_detail', pk=pk)
    
    def get(self, request, pk):
        """
        處理 GET 請求：顯示確認刪除頁面
        """
        try:
            order = Order.objects.select_related(
                'account'
            ).prefetch_related(
                'order_products',
                'order_products__variant'
            ).get(pk=pk)
        except Order.DoesNotExist:
            messages.error(request, f'訂單 #{pk} 不存在')
            return redirect('business:order_list')
        
        # 檢查是否可刪除
        deletable = order.status in [OrderStatus.PENDING, OrderStatus.CANCELLED, OrderStatus.PAID]
        
        context = {
            'order': order,
            'deletable': deletable,
            'will_restore_stock': order.order_products.exists(),
            'will_refund': order.payment_type == PaymentType.TOPUP,
        }
        
        return render(request, 'business/order_delete_confirm.html', context)

# 刪除訂單產品
@login_required
@require_POST
def delete_order_product(request, order_id, product_id):
    """
    刪除訂單中的單一產品
    
    功能：
    1. 刪除訂單產品
    2. 恢復庫存數量（按 FIFO）
    3. 退回儲值金額（如果使用儲值支付）
    4. 重新計算訂單總額
    5. 如果訂單沒有產品，自動刪除訂單
    """
    import logging
    logger = logging.getLogger(__name__)

    # 添加詳細的調試日誌
    logger.info(f'='*50)
    logger.info(f'刪除訂單產品請求')
    logger.info(f'接收到的 order_id: "{order_id}" (類型: {type(order_id).__name__}, 長度: {len(order_id)})')
    logger.info(f'接收到的 product_id: {product_id} (類型: {type(product_id).__name__})')
    logger.info(f'請求路徑: {request.path}')
    logger.info(f'='*50)
    
    # 1. 權限檢查：只有總公司管理員可以刪除訂單產品
    if not is_headquarter_admin(request.user):
        messages.error(request, '您沒有權限執行此操作，只有總公司管理員可以刪除訂單產品。')
        return redirect('business:order_detail', pk=order_id)
    
    try:
        with transaction.atomic():
            # 2. 獲取訂單（確保 order_id 是字串類型）
            try:
                # 強制轉換為字串並去除空白
                clean_order_id = str(order_id).strip()
                
                logger.info(f'🔍 清理後的 order_id: "{clean_order_id}" (長度: {len(clean_order_id)})')
                
                # 先查詢資料庫中實際的訂單 ID
                all_orders = Order.objects.values_list('id', flat=True)
                logger.info(f'📊 資料庫中的訂單數量: {len(all_orders)}')
                
                # 查找包含部分 ID 的訂單
                matching_orders = [oid for oid in all_orders if clean_order_id in str(oid)]
                if matching_orders:
                    logger.info(f'找到匹配的訂單: {matching_orders}')
                    clean_order_id = matching_orders[0]
                
                order = Order.objects.select_related(
                    'account'
                ).prefetch_related(
                    'order_products',
                    'order_products__variant'
                ).get(pk=clean_order_id)
                
                logger.info(f'成功獲取訂單: {order.id}')
                
            except Order.DoesNotExist:
                logger.error(f'❌ 訂單不存在: {order_id}')
                
                # 嘗試查找相似的訂單 ID
                similar_orders = Order.objects.filter(
                    id__contains=str(order_id)[-10:]  # 使用後 10 位數字
                )
                
                if similar_orders.exists():
                    logger.warning(f'⚠️ 找到相似的訂單: {[o.id for o in similar_orders]}')
                    messages.error(
                        request, 
                        f'訂單 #{order_id} 不存在，但找到相似訂單：{[o.id for o in similar_orders]}'
                    )
                else:
                    messages.error(request, f'訂單 #{order_id} 不存在')
                
                return redirect('business:order_list')
            
            # 3. 檢查訂單狀態（只能編輯特定狀態的訂單）
            editable_statuses = [
                OrderStatus.PENDING,
                OrderStatus.PAID,
                OrderStatus.WAIT,
                OrderStatus.HOLDING
            ]
            
            if order.status not in editable_statuses:
                messages.error(
                    request,
                    f'無法編輯訂單 #{order.id}：'
                    f'只能編輯「待處理」、「已付款」、「待付款」或「保留中」狀態的訂單。'
                    f'目前狀態：{order.get_status_display()}'
                )
                return redirect('business:order_detail', pk=order.id)
            
            # 4. 獲取訂單產品
            try:
                order_product = OrderProduct.objects.select_related(
                    'variant'
                ).get(
                    id=product_id,
                    order=order
                )
            except OrderProduct.DoesNotExist:
                messages.error(request, f'訂單產品 #{product_id} 不存在')
                return redirect('business:order_detail', pk=order.id)
            
            logger.info(
                f'準備刪除訂單產品：訂單 #{order.id}，'
                f'產品 {order_product.variant.name if order_product.variant else "已下架"}，'
                f'數量 {order_product.quantity}，'
                f'金額 ${order_product.amount}'
            )
            
            # 5. 記錄訂單原始資訊
            order_account = order.account
            payment_type = order.payment_type
            product_amount = order_product.amount
            
            # 6. 恢復庫存（根據 used_stocks 記錄）
            variant = order_product.variant
            used_stocks_data = order_product.used_stocks
            restored_stocks = []
            
            if variant and used_stocks_data:
                logger.info(
                    f'準備恢復庫存：變體 {variant.id} ({variant.name})，'
                    f'共 {len(used_stocks_data)} 筆庫存記錄'
                )
                
                # 按記錄逐一恢復庫存
                for stock_data in used_stocks_data:
                    stock_id = stock_data['stock_id']
                    deducted_quantity = stock_data['deducted_quantity']
                    
                    try:
                        stock = Stock.objects.select_for_update().get(id=stock_id)
                        
                        # 恢復庫存數量
                        stock.quantity += deducted_quantity
                        
                        # 如果庫存恢復到大於 0，取消已使用標記
                        if stock.quantity > 0:
                            stock.is_used = False
                            stock.exchange_time = None
                        
                        stock.save()
                        
                        restored_stocks.append({
                            'stock_id': stock.id,
                            'variant_name': variant.name,
                            'restored_quantity': deducted_quantity,
                            'current_quantity': stock.quantity
                        })
                        
                        logger.info(
                            f'✅ 庫存 #{stock.id} 恢復 {deducted_quantity} 件，'
                            f'當前數量：{stock.quantity} 件'
                        )
                        
                    except Stock.DoesNotExist:
                        logger.warning(
                            f'❌ 庫存 #{stock_id} 已被刪除，無法恢復 {deducted_quantity} 件'
                        )
                        continue
            else:
                if not variant:
                    logger.warning(f'訂單產品的變體已被刪除，跳過庫存恢復')
                if not used_stocks_data:
                    logger.warning(f'訂單產品沒有庫存使用記錄，跳過庫存恢復')
            
            # 7. 刪除訂單產品
            product_name = order_product.variant.name if order_product.variant else "已下架商品"
            order_product.delete()
            
            logger.info(f'✅ 已刪除訂單產品：{product_name}')
            
            # 8. 重新計算訂單總額
            order.refresh_from_db()
            remaining_products = order.order_products.count()
            
            if remaining_products == 0:
                # 如果訂單沒有產品了，刪除整個訂單
                logger.info(f'訂單 #{order.id} 沒有產品了，準備刪除訂單')
                
                # 如果使用儲值支付，退回全部金額
                if payment_type == PaymentType.TOPUP:
                    try:
                        topup = AccountTopUP.objects.select_for_update().get(
                            account=order_account
                        )
                        
                        # 查找原始扣款記錄
                        original_log = AccountTopUPLog.objects.filter(
                            order=order,
                            log_type=TopupType.CONSUMPTION
                        ).first()
                        
                        if original_log:
                            refund_amount = abs(original_log.amount)
                            balance_before = topup.balance
                            
                            # 退款
                            topup.balance += refund_amount
                            topup.save()
                            
                            # 記錄退款
                            AccountTopUPLog.objects.create(
                                topup=topup,
                                order=order,
                                amount=refund_amount,
                                balance_before=balance_before,
                                balance_after=topup.balance,
                                log_type=TopupType.REFUND,
                                is_confirmed=True,
                                remark=f'訂單 #{order.id} 產品全部刪除，退款'
                            )
                            
                            logger.info(
                                f'✅ 儲值退款：${refund_amount}，'
                                f'餘額 ${balance_before} → ${topup.balance}'
                            )
                    except AccountTopUP.DoesNotExist:
                        logger.warning(f'找不到帳號 {order_account.username} 的儲值記錄')
                
                # 刪除儲值異動記錄
                AccountTopUPLog.objects.filter(order=order).delete()
                
                # 刪除訂單
                order.delete()
                
                messages.success(
                    request,
                    f'✅ 訂單產品 {product_name} 已刪除。'
                    f'訂單 #{order_id} 已無產品，已自動刪除訂單。'
                    f'{"已退款" if payment_type == PaymentType.TOPUP else ""}'
                )
                
                return redirect('business:order_list')
            
            # 9. 如果還有產品，更新訂單金額和儲值記錄
            new_order_amount = order.amount
            
            logger.info(
                f'訂單 #{order.id} 還有 {remaining_products} 個產品，'
                f'新總額：${new_order_amount}'
            )
            
            # 10. 如果使用儲值支付，調整儲值記錄
            if payment_type == PaymentType.TOPUP:
                try:
                    topup = AccountTopUP.objects.select_for_update().get(
                        account=order_account
                    )
                    
                    # 查找原始扣款記錄
                    original_log = AccountTopUPLog.objects.filter(
                        order=order,
                        log_type=TopupType.CONSUMPTION
                    ).first()
                    
                    if original_log:
                        # 退回此產品的金額
                        balance_before = topup.balance
                        topup.balance += product_amount
                        topup.save()
                        
                        # 記錄退款
                        AccountTopUPLog.objects.create(
                            topup=topup,
                            order=order,
                            amount=product_amount,
                            balance_before=balance_before,
                            balance_after=topup.balance,
                            log_type=TopupType.REFUND,
                            is_confirmed=True,
                            remark=f'訂單 #{order.id} 刪除產品 {product_name}，退款'
                        )
                        
                        logger.info(
                            f'✅ 儲值退款：${product_amount}，'
                            f'餘額 ${balance_before} → ${topup.balance}'
                        )
                        
                except AccountTopUP.DoesNotExist:
                    logger.warning(f'找不到帳號 {order_account.username} 的儲值記錄')
            
            # 11. 成功訊息
            success_message = f'✅ 訂單產品 {product_name} 已成功刪除'
            
            if restored_stocks:
                success_message += f'，已恢復 {len(restored_stocks)} 筆庫存'
            
            if payment_type == PaymentType.TOPUP:
                success_message += f'，已退款 ${product_amount:,.0f}'
            
            messages.success(request, success_message)
            
            logger.info(
                f'✅ 訂單產品刪除成功：訂單 #{order.id}，'
                f'產品 {product_name}，'
                f'恢復庫存 {len(restored_stocks)} 筆，'
                f'{"已退款" if payment_type == PaymentType.TOPUP else "無需退款"}'
            )
            
            return redirect('business:order_detail', pk=order_id)
            
    except Exception as e:
        logger.error(f'❌ 刪除訂單產品失敗：{str(e)}', exc_info=True)
        messages.error(request, f'❌ 刪除訂單產品失敗：{str(e)}')
        return redirect('business:order_detail', pk=order_id)



# 收據列表
class ReceiptListView(LoginRequiredMixin, ListView):
    """
    收據列表視圖
    
    權限：
    - 總公司管理員：查看所有收據
    - 代理商：查看自己和下級分銷商的收據
    - 分銷商：只能查看自己的收據
    """
    model = Receipt
    template_name = 'business/receipt_list.html'
    context_object_name = 'receipts'
    paginate_by = 20
    
    def get_queryset(self):
        user = self.request.user
        queryset = Receipt.objects.select_related(
            'order',
            'order__account',
            'created_by'
        ).prefetch_related(
            'items'
        ).all()
        
        # 權限過濾（與 OrderListView 相同邏輯）
        if is_headquarter_admin(user):
            pass
        elif is_agent(user):
            distributor_ids = CustomUser.objects.filter(
                parent=user,
                role=AccountRole.DISTRIBUTOR,
                status=AccountStatus.ACTIVE
            ).values_list('id', flat=True)
            
            # 只顯示自己和下級分銷商的收據
            queryset = queryset.filter(
                Q(order__account=user) | 
                Q(order__account__id__in=distributor_ids) |
                Q(order__isnull=True, created_by=user)  # 手動建立的收據
            )
        else:
            # 分銷商：只能查看自己的收據
            queryset = queryset.filter(
                Q(order__account=user) |
                Q(order__isnull=True, created_by=user)
            )
        
        # 搜尋功能
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(receipt_number__icontains=search_query) |
                Q(receipt_to__icontains=search_query) |
                Q(taxid__icontains=search_query) |
                Q(order__id__icontains=search_query)
            ).distinct()
        
        # ✅ 收據類型篩選
        receipt_type = self.request.GET.get('receipt_type')
        if receipt_type:
            queryset = queryset.filter(receipt_type=receipt_type)
        
        # 日期篩選
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        
        return queryset.order_by('-date', '-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 統計資料
        receipts = self.get_queryset()
        context['total_receipts'] = receipts.count()
        context['total_amount'] = sum(r.total_amount for r in receipts)
        
        # ✅ 按收據類型統計
        context['order_receipt_count'] = receipts.filter(receipt_type=ReceiptType.ORDER).count()
        context['manual_receipt_count'] = receipts.filter(receipt_type=ReceiptType.MANUAL).count()
        
        # ✅ 傳遞篩選選項
        context['receipt_types'] = ReceiptType.choices
        context['selected_receipt_type'] = self.request.GET.get('receipt_type', '')
        
        # 傳遞篩選條件
        context['search_query'] = self.request.GET.get('q', '')
        context['date_from'] = self.request.GET.get('date_from', '')
        context['date_to'] = self.request.GET.get('date_to', '')
        
        # 權限資訊
        context['is_headquarter_admin'] = is_headquarter_admin(self.request.user)
        
        return context


# 收據詳情
class ReceiptDetailView(LoginRequiredMixin, DetailView):
    """
    收據詳情視圖
    """
    model = Receipt
    template_name = 'business/receipt_detail2.html'
    context_object_name = 'receipt'
    
    def get_queryset(self):
        # 與 ReceiptListView 相同的權限邏輯
        user = self.request.user
        queryset = Receipt.objects.select_related(
            'order',
            'order__account',
            'created_by'
        ).prefetch_related(
            'items',
            'items__order_product'
        ).all()
        
        if is_headquarter_admin(user):
            pass
        elif is_agent(user):
            distributor_ids = CustomUser.objects.filter(
                parent=user,
                role=AccountRole.DISTRIBUTOR
            ).values_list('id', flat=True)
            
            queryset = queryset.filter(
                Q(order__account=user) |
                Q(order__account__id__in=distributor_ids) |
                Q(order__isnull=True, created_by=user)
            )
        else:
            queryset = queryset.filter(
                Q(order__account=user) |
                Q(order__isnull=True, created_by=user)
            )
        
        return queryset


# 金額轉大寫中文數字函數
def convert_amount_to_chinese(amount):
    """
    將金額轉換為大寫中文數字
    
    Args:
        amount: Decimal 或 int，金額數字
        
    Returns:
        dict: 包含每個位數的中文字
        {
            'qian_wan': '零',  # 仟萬位
            'bai_wan': '零',   # 佰萬位
            'shi_wan': '零',   # 拾萬位
            'wan': '零',       # 萬位
            'qian': '零',      # 仟位
            'bai': '零',       # 佰位
            'shi': '零',       # 拾位
            'yuan': '零',      # 元位
            'full_text': '零元整'  # 完整文字
        }
    """
    # 中文數字對應
    chinese_numbers = ['零', '壹', '貳', '參', '肆', '伍', '陸', '柒', '捌', '玖']
    
    # 確保金額是整數
    amount = int(amount)
    
    # 如果金額為 0
    if amount == 0:
        return {
            'qian_wan': '零',
            'bai_wan': '零',
            'shi_wan': '零',
            'wan': '零',
            'qian': '零',
            'bai': '零',
            'shi': '零',
            'yuan': '零',
            'full_text': '零元整'
        }
    
    # 轉換為字串並補齊到 8 位數（最大到 9999 萬 9999 元）
    amount_str = str(amount).zfill(8)
    
    # 提取每個位數
    digits = [int(d) for d in amount_str]
    
    # 轉換為中文
    result = {
        'qian_wan': chinese_numbers[digits[0]],  # 仟萬位
        'bai_wan': chinese_numbers[digits[1]],   # 佰萬位
        'shi_wan': chinese_numbers[digits[2]],   # 拾萬位
        'wan': chinese_numbers[digits[3]],       # 萬位
        'qian': chinese_numbers[digits[4]],      # 仟位
        'bai': chinese_numbers[digits[5]],       # 佰位
        'shi': chinese_numbers[digits[6]],       # 拾位
        'yuan': chinese_numbers[digits[7]],      # 元位
    }
    
    # 生成完整文字（處理零的顯示規則）
    full_text = ''
    
    # 萬位段（仟萬到萬）
    wan_part = ''
    if digits[0] > 0:
        wan_part += chinese_numbers[digits[0]] + '仟'
    if digits[1] > 0:
        wan_part += chinese_numbers[digits[1]] + '佰'
    elif digits[0] > 0 and (digits[2] > 0 or digits[3] > 0):
        wan_part += '零'
    if digits[2] > 0:
        wan_part += chinese_numbers[digits[2]] + '拾'
    elif (digits[0] > 0 or digits[1] > 0) and digits[3] > 0:
        wan_part += '零'
    if digits[3] > 0:
        wan_part += chinese_numbers[digits[3]]
    
    if wan_part:
        full_text += wan_part + '萬'
    
    # 元位段（仟到元）
    yuan_part = ''
    if digits[4] > 0:
        yuan_part += chinese_numbers[digits[4]] + '仟'
    elif (digits[0] > 0 or digits[1] > 0 or digits[2] > 0 or digits[3] > 0) and (digits[5] > 0 or digits[6] > 0 or digits[7] > 0):
        yuan_part += '零'
    if digits[5] > 0:
        yuan_part += chinese_numbers[digits[5]] + '佰'
    elif digits[4] > 0 and (digits[6] > 0 or digits[7] > 0):
        yuan_part += '零'
    if digits[6] > 0:
        yuan_part += chinese_numbers[digits[6]] + '拾'
    elif (digits[4] > 0 or digits[5] > 0) and digits[7] > 0:
        yuan_part += '零'
    if digits[7] > 0:
        yuan_part += chinese_numbers[digits[7]]
    
    full_text += yuan_part + '元整'
    
    result['full_text'] = full_text
    
    return result

# 收據列印
class ReceiptPrintView(ReceiptDetailView, DetailView):
    """
    收據列印視圖
    
    將金額轉換為大寫中文數字
    """
    template_name = 'business/receipt_detail3.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 獲取收據總額並轉換為大寫中文數字
        receipt = self.object
        total_amount = receipt.total_amount
        
        # 轉換為大寫中文數字
        chinese_amount = convert_amount_to_chinese(total_amount)
        
        # 添加到 context
        context['chinese_amount'] = chinese_amount
        context['total_amount_number'] = total_amount  # 保留原始數字
        
        # 記錄日誌
        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            f'收據 {receipt.receipt_number} 金額轉換：'
            f'${total_amount:,} → {chinese_amount["full_text"]}'
        )
        
        return context

# 手動建立收據
class ReceiptCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    """
    手動建立收據視圖
    
    權限：只有總公司管理員可以手動建立收據
    """
    model = Receipt
    template_name = 'business/receipt_update.html'
    fields = ['receipt_to', 'taxid', 'date', 'remark']
    success_url = reverse_lazy('business:receipt_list')
    
    def test_func(self):
        return is_headquarter_admin(self.request.user)
    
    def form_valid(self, form):
        with transaction.atomic():
            # 建立收據
            receipt = form.save(commit=False)
            receipt.created_by = self.request.user
            receipt.receipt_type = ReceiptType.MANUAL
            receipt.save()
            
            # 從 POST 資料獲取產品明細
            product_names = self.request.POST.getlist('product_name[]')
            product_codes = self.request.POST.getlist('product_code[]')
            quantities = self.request.POST.getlist('quantity[]')
            unit_prices = self.request.POST.getlist('unit_price[]')
            
            # 建立收據明細
            created_count = 0
            for i in range(len(product_names)):
                if product_names[i] and quantities[i] and unit_prices[i]:
                    ReceiptItem.objects.create(
                        receipt=receipt,
                        product_name=product_names[i],
                        product_code=product_codes[i] if i < len(product_codes) else '',
                        quantity=int(quantities[i]),
                        unit_price=Decimal(unit_prices[i])
                    )
                    created_count += 1
            
            messages.success(
                self.request,
                f'✅ 收據 {receipt.receipt_number} 建立成功！'
                f'<br>• 收據類型：手動建立'
                f'<br>• 產品項目：{created_count} 項'
                f'<br>• 收據總額：${receipt.total_amount:,.0f}'
            )
            
            logger.info(
                f'✅ 手動收據建立成功：{receipt.receipt_number}，'
                f'共 {created_count} 項產品'
            )
            
            return redirect(self.success_url)

# 更新手動收據
class ReceiptUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    """
    更新手動建立的收據視圖
    
    需求：
    1. 只能更新手動建立的收據（order 為 None）
    2. 權限：只有總公司管理員可以更新收據
    3. 共用 receipt_update.html 模板
    4. 可以修改收據抬頭、統編、日期、備註
    5. 可以新增/修改/刪除產品明細
    """
    model = Receipt
    template_name = 'business/receipt_update.html'
    fields = ['receipt_to', 'taxid', 'date', 'remark']
    success_url = reverse_lazy('business:receipt_list')
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以編輯收據
        """
        return is_headquarter_admin(self.request.user)
    
    def get_object(self, queryset=None):
        """
        獲取收據對象，並檢查是否為手動建立的收據
        """
        obj = super().get_object(queryset)
        
        # 只能編輯手動建立的收據（沒有關聯訂單的收據）
        if obj.order is not None:
            messages.error(
                self.request,
                f'無法編輯收據 {obj.receipt_number}：'
                f'此收據由訂單自動生成，無法手動編輯。'
            )
            # 返回 None 會導致 404，所以我們重定向
            raise Http404('只能編輯手動建立的收據')
        
        return obj
    
    def get_context_data(self, **kwargs):
        """
        傳遞收據明細到模板
        """
        context = super().get_context_data(**kwargs)
        
        # 獲取現有的收據明細
        receipt = self.object
        context['receipt_items'] = receipt.items.all().order_by('id')
        
        return context
    
    def form_valid(self, form):
        """
        處理表單提交
        """
        logger = logging.getLogger(__name__)
        
        try:
            with transaction.atomic():
                # 1. 更新收據基本資訊
                receipt = form.save(commit=False)
                receipt.updated_at = timezone.now()
                receipt.save()
                
                logger.info(f'更新收據基本資訊：{receipt.receipt_number}')
                
                # 2. 刪除所有現有的收據明細
                receipt.items.all().delete()
                logger.info(f'已刪除收據 {receipt.receipt_number} 的所有舊明細')
                
                # 3. 從 POST 資料獲取新的產品明細
                product_names = self.request.POST.getlist('product_name[]')
                product_codes = self.request.POST.getlist('product_code[]')
                quantities = self.request.POST.getlist('quantity[]')
                unit_prices = self.request.POST.getlist('unit_price[]')
                
                # 4. 建立新的收據明細
                created_count = 0
                for i in range(len(product_names)):
                    if product_names[i] and quantities[i] and unit_prices[i]:
                        try:
                            ReceiptItem.objects.create(
                                receipt=receipt,
                                product_name=product_names[i].strip(),
                                product_code=product_codes[i].strip() if i < len(product_codes) else '',
                                quantity=int(quantities[i]),
                                unit_price=Decimal(unit_prices[i])
                            )
                            created_count += 1
                            logger.info(
                                f'建立收據明細：{product_names[i]} x {quantities[i]} @ ${unit_prices[i]}'
                            )
                        except (ValueError, TypeError) as e:
                            logger.error(f'建立收據明細失敗：{str(e)}')
                            raise ValueError(f'第 {i+1} 項產品資料格式錯誤：{str(e)}')
                
                # 5. 檢查是否至少有一項產品
                if created_count == 0:
                    raise ValueError('收據必須至少包含一項產品')
                
                # 6. 成功訊息
                messages.success(
                    self.request,
                    f'收據 {receipt.receipt_number} 更新成功！'
                    f'<br>• 已更新 {created_count} 項產品明細'
                    f'<br>• 收據總額：${receipt.total_amount:,.0f}'
                )
                
                logger.info(
                    f'收據 {receipt.receipt_number} 更新成功，'
                    f'共 {created_count} 項產品，總額 ${receipt.total_amount}'
                )
                
                return redirect(self.success_url)
                
        except ValueError as e:
            logger.error(f'更新收據失敗（數據驗證錯誤）：{str(e)}')
            messages.error(self.request, f'更新收據失敗：{str(e)}')
            return self.form_invalid(form)
        except Exception as e:
            logger.error(f'更新收據失敗（系統錯誤）：{str(e)}', exc_info=True)
            messages.error(self.request, f'更新收據失敗：{str(e)}')
            return self.form_invalid(form)

# 支出列表
class ExpenseListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    """
    支出列表視圖
    
    權限：
    - 僅總公司管理員可查看所有支出記錄
    """
    model = Expense
    template_name = 'business/expense_list.html'
    context_object_name = 'expenses'
    paginate_by = 20
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以查看支出記錄
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.error(self.request, '您沒有權限查看支出記錄，只有總公司管理員可以查看。')
        return redirect('products:catalogue_list')
    
    def get_queryset(self):
        queryset = Expense.objects.all()
        
        # 搜尋功能
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(remark__icontains=search_query)
            )
        
        # 支出項目篩選
        expense_item = self.request.GET.get('item')
        if expense_item:
            queryset = queryset.filter(item=expense_item)
        
        # 日期篩選
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        
        return queryset.order_by('-date', '-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 統計資料
        expenses = self.get_queryset()
        context['total_expenses'] = expenses.count()
        context['total_amount'] = expenses.aggregate(total=Sum('amount'))['total'] or 0
        
        # 按支出項目統計
        expense_items_stats = expenses.values('item').annotate(
            count=Sum('id'),
            amount=Sum('amount')
        )
        context['expense_items_stats'] = expense_items_stats
        
        # 傳遞篩選選項
        context['expense_items'] = ExpenseItem.choices
        context['selected_item'] = self.request.GET.get('item', '')
        
        # 傳遞篩選條件
        context['search_query'] = self.request.GET.get('q', '')
        context['date_from'] = self.request.GET.get('date_from', '')
        context['date_to'] = self.request.GET.get('date_to', '')
        
        # 權限資訊
        context['is_headquarter_admin'] = is_headquarter_admin(self.request.user)
        
        return context

# 新增支出
class ExpenseCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    """
    新增支出視圖
    
    權限：
    - 僅總公司管理員可以新增支出記錄
    """
    model = Expense
    template_name = 'business/expense_form.html'
    fields = ['name', 'date', 'amount', 'item', 'remark']
    success_url = reverse_lazy('business:expense_list')
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以新增支出
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.error(self.request, '您沒有權限新增支出記錄，只有總公司管理員可以操作。')
        return redirect('business:expense_list')
    
    def form_valid(self, form):
        """
        處理表單提交
        """
        logger = logging.getLogger(__name__)
        
        try:
            expense = form.save()
            
            messages.success(
                self.request,
                f'支出記錄新增成功！'
                f'<br>• 名稱：{expense.name}'
                f'<br>• 支出項目：{expense.get_item_display()}'
                f'<br>• 金額：${expense.amount:,.0f}'
            )
            
            logger.info(
                f'支出記錄新增成功：{expense.name}，'
                f'項目：{expense.get_item_display()}，金額：${expense.amount}'
            )
            
            return redirect(self.success_url)
            
        except Exception as e:
            logger.error(f'新增支出記錄失敗：{str(e)}', exc_info=True)
            messages.error(self.request, f'新增支出記錄失敗：{str(e)}')
            return self.form_invalid(form)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_title'] = '新增支出記錄'
        context['submit_text'] = '新增支出'
        return context

# 更新支出
class ExpenseUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    """
    更新支出視圖
    
    權限：
    - 僅總公司管理員可以更新支出記錄
    """
    model = Expense
    template_name = 'business/expense_form.html'
    fields = ['name', 'date', 'amount', 'item', 'remark']
    success_url = reverse_lazy('business:expense_list')
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以更新支出
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.error(self.request, '您沒有權限編輯支出記錄，只有總公司管理員可以操作。')
        return redirect('business:expense_list')
    
    def get_form(self, form_class=None):
        """
        自定義表單配置，確保日期欄位正確顯示
        """
        form = super().get_form(form_class)
        
        # 配置日期欄位的 widget，使用 HTML5 date input
        from django import forms
        form.fields['date'].widget = forms.DateInput(
            attrs={'type': 'date', 'class': 'form-control'},
            format='%Y-%m-%d'
        )
        form.fields['date'].required = False  # 設為非必填，允許空白提交
        
        return form
    
    def form_valid(self, form):
        """
        處理表單提交，保留原始日期如果沒有異動
        """
        logger = logging.getLogger(__name__)
        
        try:
            # 如果日期欄位為空，保留原始日期
            if not form.cleaned_data.get('date'):
                expense = form.save(commit=False)
                original_expense = Expense.objects.get(pk=expense.pk)
                expense.date = original_expense.date
                expense.save()
            else:
                expense = form.save()
            
            messages.success(
                self.request,
                f'支出記錄更新成功！'
                f'<br>• 名稱：{expense.name}'
                f'<br>• 支出項目：{expense.get_item_display()}'
                f'<br>• 金額：${expense.amount:,.0f}'
            )
            
            logger.info(
                f'支出記錄更新成功：{expense.name}，'
                f'項目：{expense.get_item_display()}，金額：${expense.amount}'
            )
            
            return redirect(self.success_url)
            
        except Exception as e:
            logger.error(f'❌ 更新支出記錄失敗：{str(e)}', exc_info=True)
            messages.error(self.request, f'❌ 更新支出記錄失敗：{str(e)}')
            return self.form_invalid(form)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_title'] = '編輯支出記錄'
        context['submit_text'] = '更新支出'
        return context

# 刪除支出
class ExpenseDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    """
    刪除支出視圖
    
    權限：
    - 僅總公司管理員可以刪除支出記錄
    """
    model = Expense
    template_name = 'business/expense_delete_confirm.html'
    success_url = reverse_lazy('business:expense_list')
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以刪除支出
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.error(self.request, '您沒有權限刪除支出記錄，只有總公司管理員可以操作。')
        return redirect('business:expense_list')
    
    def delete(self, request, *args, **kwargs):
        """
        處理刪除請求
        """
        logger = logging.getLogger(__name__)
        
        try:
            expense = self.get_object()
            expense_name = expense.name
            expense_amount = expense.amount
            
            # 執行刪除
            response = super().delete(request, *args, **kwargs)
            
            messages.success(
                self.request,
                f'支出記錄已刪除！'
                f'<br>• 名稱：{expense_name}'
                f'<br>• 金額：${expense_amount:,.0f}'
            )
            
            logger.info(f'支出記錄已刪除：{expense_name}，金額：${expense_amount}')
            
            return response
            
        except Exception as e:
            logger.error(f'刪除支出記錄失敗：{str(e)}', exc_info=True)
            messages.error(self.request, f'刪除支出記錄失敗：{str(e)}')
            return redirect('business:expense_list')

# 收入列表
class IncomeListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    """
    收入列表視圖
    
    權限：
    - 僅總公司管理員可查看所有收入記錄
    """
    model = Income
    template_name = 'business/income_list.html'
    context_object_name = 'incomes'
    paginate_by = 20
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以查看收入記錄
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.error(self.request, '您沒有權限查看收入記錄，只有總公司管理員可以查看。')
        return redirect('products:catalogue_list')
    
    def get_queryset(self):
        queryset = Income.objects.all()
        
        # 搜尋功能
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(remark__icontains=search_query)
            )
        
        # 收入項目篩選
        income_item = self.request.GET.get('item')
        if income_item:
            queryset = queryset.filter(item=income_item)
        
        # 日期篩選
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        
        return queryset.order_by('-date', '-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 統計資料
        incomes = self.get_queryset()
        context['total_incomes'] = incomes.count()
        context['total_amount'] = incomes.aggregate(total=Sum('amount'))['total'] or 0
        
        # 按收入項目統計
        income_items_stats = incomes.values('item').annotate(
            count=Sum('id'),
            amount=Sum('amount')
        )
        context['income_items_stats'] = income_items_stats
        
        # 傳遞篩選選項
        context['income_items'] = IncomeItem.choices
        context['selected_item'] = self.request.GET.get('item', '')
        
        # 傳遞篩選條件
        context['search_query'] = self.request.GET.get('q', '')
        context['date_from'] = self.request.GET.get('date_from', '')
        context['date_to'] = self.request.GET.get('date_to', '')
        
        # 權限資訊
        context['is_headquarter_admin'] = is_headquarter_admin(self.request.user)
        
        return context

# 新增收入
class IncomeCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    """
    新增收入視圖
    
    權限：
    - 僅總公司管理員可以新增收入記錄
    """
    model = Income
    template_name = 'business/income_form.html'
    fields = ['name', 'date', 'amount', 'item', 'remark']
    success_url = reverse_lazy('business:income_list')
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以新增收入
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.error(self.request, '您沒有權限新增收入記錄，只有總公司管理員可以操作。')
        return redirect('business:income_list')
    
    def form_valid(self, form):
        """
        處理表單提交
        """
        logger = logging.getLogger(__name__)
        
        try:
            income = form.save()
            
            messages.success(
                self.request,
                f'收入記錄新增成功！'
                f'<br>• 名稱：{income.name}'
                f'<br>• 收入項目：{income.get_item_display()}'
                f'<br>• 金額：${income.amount:,.0f}'
            )
            
            logger.info(
                f'收入記錄新增成功：{income.name}，'
                f'項目：{income.get_item_display()}，金額：${income.amount}'
            )
            
            return redirect(self.success_url)
            
        except Exception as e:
            logger.error(f'新增收入記錄失敗：{str(e)}', exc_info=True)
            messages.error(self.request, f'新增收入記錄失敗：{str(e)}')
            return self.form_invalid(form)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_title'] = '新增收入記錄'
        context['submit_text'] = '新增收入'
        return context

# 更新收入
class IncomeUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    """
    更新收入視圖
    
    權限：
    - 僅總公司管理員可以更新收入記錄
    """
    model = Income
    template_name = 'business/income_form.html'
    fields = ['name', 'date', 'amount', 'item', 'remark']
    success_url = reverse_lazy('business:income_list')
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以更新收入
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.error(self.request, '您沒有權限編輯收入記錄，只有總公司管理員可以操作。')
        return redirect('business:income_list')
    
    def get_form(self, form_class=None):
        """
        自訂表單，設定 date 欄位的 widget
        """
        form = super().get_form(form_class)
        
        # 設定 date 欄位的 widget 為 DateInput，並指定格式
        form.fields['date'].widget = forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'form-control'
            },
            format='%Y-%m-%d'
        )
        
        # 設定 date 欄位為非必填
        form.fields['date'].required = False
        
        return form
    
    def form_valid(self, form):
        """
        處理表單提交
        """
        logger = logging.getLogger(__name__)
        
        try:
            # 如果 date 欄位為空，保留原有日期
            if not form.cleaned_data.get('date'):
                income = form.save(commit=False)
                # 從資料庫重新取得原有的日期
                original_income = Income.objects.get(pk=income.pk)
                income.date = original_income.date
                income.save()
            else:
                income = form.save()
            
            messages.success(
                self.request,
                f'收入記錄更新成功！'
                f'<br>• 名稱：{income.name}'
                f'<br>• 收入項目：{income.get_item_display()}'
                f'<br>• 金額：${income.amount:,.0f}'
            )
            
            logger.info(
                f'收入記錄更新成功：{income.name}，'
                f'項目：{income.get_item_display()}，金額：${income.amount}'
            )
            
            return redirect(self.success_url)
            
        except Exception as e:
            logger.error(f'更新收入記錄失敗：{str(e)}', exc_info=True)
            messages.error(self.request, f'更新收入記錄失敗：{str(e)}')
            return self.form_invalid(form)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_title'] = '編輯收入記錄'
        context['submit_text'] = '更新收入'
        return context


# 刪除收入
class IncomeDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    """
    刪除收入視圖
    
    權限：
    - 僅總公司管理員可以刪除收入記錄
    """
    model = Income
    template_name = 'business/income_delete_confirm.html'
    success_url = reverse_lazy('business:income_list')
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以刪除收入
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.error(self.request, '您沒有權限刪除收入記錄，只有總公司管理員可以操作。')
        return redirect('business:income_list')
    
    def delete(self, request, *args, **kwargs):
        """
        處理刪除請求
        """
        logger = logging.getLogger(__name__)
        
        try:
            income = self.get_object()
            income_name = income.name
            income_amount = income.amount
            
            # 執行刪除
            response = super().delete(request, *args, **kwargs)
            
            messages.success(
                self.request,
                f'收入記錄已刪除！'
                f'<br>• 名稱：{income_name}'
                f'<br>• 金額：${income_amount:,.0f}'
            )
            
            logger.info(f'收入記錄已刪除：{income_name}，金額：${income_amount}')
            
            return response
            
        except Exception as e:
            logger.error(f'刪除收入記錄失敗：{str(e)}', exc_info=True)
            messages.error(self.request, f'刪除收入記錄失敗：{str(e)}')
            return redirect('business:income_list')

