from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponseRedirect
from django.views.generic import CreateView, UpdateView, DetailView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic.list import ListView
from django.urls import reverse_lazy
from django.contrib import messages
from django.db.models import Q, Prefetch, Count, Min, Sum
from products.models import Supplier, Product, Variant, Category, Stock, AgentDistributorPricing
from products.constant import ProductStatus, VariantStatus, ProductType
from django.db import transaction
from products.forms import StockCreateForm, AgentDistributorPricingForm
from accounts.utils import (
    is_headquarter_admin, 
    is_agent, 
    is_distributor,
    get_variant_display_price,
    get_user_price_field,
    is_distributor,
    is_peer,
)
from products.utils import get_variant_price_for_user

# 產品目錄列表 Catalogue List
class CatalogueView(ListView):
    model = Product
    template_name = 'products/catalogue_list.html'
    context_object_name = 'products'
    paginate_by = 20  # 每頁顯示 20 個產品
    
    def get_queryset(self):
        """
        獲取產品列表，根據以下條件：
        1. 產品狀態必須是 ACTIVE 上架
        2. 至少有一個變體狀態是 ACTIVE 上架
        3. 按照 sort_order 由小到大排序
        4. 支援分類篩選
        5. 支援產品類型篩選
        """
        # 基礎查詢：只顯示上架的產品
        queryset = Product.objects.filter(
            status=ProductStatus.ACTIVE
        ).select_related('category').prefetch_related(
            Prefetch(
                'variants',
                queryset=Variant.objects.filter(
                    status=VariantStatus.ACTIVE
                ).order_by('sort_order')
            )
        )
        
        # 只顯示至少有一個上架變體的產品
        queryset = queryset.annotate(
            active_variants_count=Count(
                'variants',
                filter=Q(variants__status=VariantStatus.ACTIVE)
            )
        ).filter(active_variants_count__gt=0)
        
        # 分類篩選
        category_id = self.request.GET.get('category')
        if category_id:
            try:
                queryset = queryset.filter(category_id=int(category_id))
            except (ValueError, TypeError):
                pass
        
        # 產品類型篩選
        product_type = self.request.GET.get('type')
        if product_type and product_type in dict(ProductType.choices):
            queryset = queryset.filter(
                variants__product_type=product_type,
                variants__status=VariantStatus.ACTIVE
            ).distinct()
        
        # 搜尋功能
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(description__icontains=search_query) |
                Q(variants__name__icontains=search_query) |
                Q(variants__description__icontains=search_query)
            ).distinct()
        
        # 排序：按照 sort_order 由小到大
        queryset = queryset.order_by('sort_order', 'id')
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # 傳遞分類列表
        context['categories'] = Category.objects.filter(
            products__status=ProductStatus.ACTIVE,
            products__variants__status=VariantStatus.ACTIVE
        ).distinct().order_by('sort_order')
        
        # 傳遞產品類型選項
        context['product_types'] = ProductType.choices
        
        # 傳遞當前篩選條件
        context['selected_category'] = self.request.GET.get('category', '')
        context['selected_type'] = self.request.GET.get('type', '')
        context['search_query'] = self.request.GET.get('q', '')
        
        # 統計資料
        context['total_products'] = self.get_queryset().count()
        
        # ✅ 為每個產品添加最低價格（使用統一函數）
        for product in context['products']:
            active_variants = product.variants.filter(status=VariantStatus.ACTIVE)
            if active_variants.exists():
                prices = []
                for variant in active_variants:
                    display_price, _ = get_variant_display_price(variant, user)
                    if display_price:
                        prices.append(display_price)
                
                if prices:
                    product.min_price = min(prices)
                else:
                    product.min_price = None
            else:
                product.min_price = None
        
        return context


# 產品詳情頁 Catalogue Detail
class CatalogueDetailView(DetailView):
    """
    產品詳情頁
    """
    model = Product
    template_name = 'products/product_detail.html'
    context_object_name = 'product'
    
    def get_queryset(self):
        return Product.objects.filter(
            status=ProductStatus.ACTIVE
        ).select_related('category').prefetch_related(
            Prefetch(
                'variants',
                queryset=Variant.objects.filter(
                    status=VariantStatus.ACTIVE
                ).order_by('sort_order')
            )
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # ✅ 簡化角色判斷
        context['is_headquarter'] = is_headquarter_admin(user)
        context['is_agent'] = is_agent(user)
        context['is_distributor'] = is_distributor(user)
        
        # 獲取所有上架的變體
        variants = self.object.variants.filter(
            status=VariantStatus.ACTIVE
        ).order_by('sort_order')
        
        context['variants'] = variants
        
        # 提取所有唯一的天數選項
        days_set = set()
        for variant in variants:
            if variant.days:
                days_set.add(variant.days)
        context['days_options'] = sorted(list(days_set), key=lambda x: self._parse_days(x))
        
        # 提取所有唯一的流量規格選項
        data_amount_set = set()
        for variant in variants:
            if variant.data_amount:
                data_amount_set.add(variant.data_amount)
        context['data_amount_options'] = sorted(list(data_amount_set), key=lambda x: self._parse_data_amount(x))
        
        # ✅ 使用統一的價格獲取函數
        # 建立變體映射表
        variant_map = {}
        for variant in variants:
            display_price, original_price = get_variant_display_price(variant, user)
            
            key = f"{variant.days}|{variant.data_amount}"
            variant_map[key] = {
                'id': variant.id,
                'name': variant.name,
                'description': variant.description,
                'product_type': variant.product_type,
                'product_type_display': variant.get_product_type_display(),
                'product_code': variant.product_code,
                'days': variant.days,
                'data_amount': variant.data_amount,
                'display_price': float(display_price),
                'original_price': float(original_price) if original_price else None,
                # 保留原始價格欄位以便需要時使用
                'price': float(variant.price) if variant.price else None,
                'price_sales': float(variant.price_sales) if variant.price_sales else None,
                'price_agent': float(variant.price_agent) if variant.price_agent else None,
                'price_sales_agent': float(variant.price_sales_agent) if variant.price_sales_agent else None,
            }
        
        import json
        context['variant_map_json'] = json.dumps(variant_map)
        
        # 相關產品
        context['related_products'] = Product.objects.filter(
            category=self.object.category,
            status=ProductStatus.ACTIVE
        ).exclude(
            id=self.object.id
        ).annotate(
            active_variants_count=Count(
                'variants',
                filter=Q(variants__status=VariantStatus.ACTIVE)
            )
        ).filter(
            active_variants_count__gt=0
        ).order_by('sort_order')[:6]
        
        # ✅ 為相關產品計算最低價格（使用統一函數）
        for related in context['related_products']:
            related_variants = related.variants.filter(status=VariantStatus.ACTIVE)
            if related_variants.exists():
                prices = []
                for rv in related_variants:
                    display_price, _ = get_variant_display_price(rv, user)
                    if display_price:
                        prices.append(display_price)
                related.min_price = min(prices) if prices else None
            else:
                related.min_price = None
        
        return context
    
    def _parse_days(self, days_str):
        """解析天數字串"""
        try:
            return int(days_str.split('-')[0].strip())
        except:
            return 999
    
    def _parse_data_amount(self, data_str):
        """解析流量字串"""
        data_str = data_str.upper().strip()
        if 'UNLIMITED' in data_str or '無限' in data_str:
            return 999999
        try:
            import re
            match = re.search(r'(\d+)', data_str)
            if match:
                num = int(match.group(1))
                if 'MB' in data_str:
                    return num / 1024
                return num
        except:
            pass
        return 0


# 產品目錄列表給批發商看 Catalogue List for Agents
class CatalogueViewForAgents(LoginRequiredMixin, ListView):
    """
    代理商/分銷商批量選購介面
    """
    model = Product
    template_name = 'products/catalogue_agents.html'
    context_object_name = 'products'
    paginate_by = 50
    
    def dispatch(self, request, *args, **kwargs):
        user = request.user
        # 允許所有已登入用戶訪問（包含 PEER 和 USER）
        if not user.is_authenticated:
            messages.warning(request, '請先登入')
            return redirect('accounts:login')
        return super().dispatch(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = Product.objects.filter(
            status=ProductStatus.ACTIVE
        ).select_related('category').prefetch_related(
            Prefetch(
                'variants',
                queryset=Variant.objects.filter(
                    status=VariantStatus.ACTIVE
                ).order_by('sort_order')
            )
        )
        
        queryset = queryset.annotate(
            active_variants_count=Count(
                'variants',
                filter=Q(variants__status=VariantStatus.ACTIVE)
            )
        ).filter(active_variants_count__gt=0)
        
        # 分類篩選
        category_id = self.request.GET.get('category')
        if category_id:
            try:
                queryset = queryset.filter(category_id=int(category_id))
            except (ValueError, TypeError):
                pass
        
        # 產品類型篩選
        product_type = self.request.GET.get('type')
        if product_type and product_type in dict(ProductType.choices):
            queryset = queryset.filter(
                variants__product_type=product_type,
                variants__status=VariantStatus.ACTIVE
            ).distinct()
        
        # 搜尋功能
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(description__icontains=search_query) |
                Q(variants__name__icontains=search_query) |
                Q(variants__product_code__icontains=search_query)
            ).distinct()
        
        return queryset.order_by('sort_order', 'id')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        import logging
        import json
        from urllib.parse import unquote
        logger = logging.getLogger(__name__)
        
        # 傳遞角色判斷
        context['is_headquarter'] = is_headquarter_admin(user)
        context['is_agent'] = is_agent(user)
        context['is_distributor'] = is_distributor(user)
        context['is_peer'] = is_peer(user)
        context['is_superuser'] = user.is_superuser
        
        # 傳遞分類列表
        context['categories'] = Category.objects.filter(
            products__status=ProductStatus.ACTIVE,
            products__variants__status=VariantStatus.ACTIVE
        ).distinct().order_by('sort_order')
        
        # 傳遞產品類型選項
        context['product_types'] = ProductType.choices
        
        # 傳遞當前篩選條件
        context['selected_category'] = self.request.GET.get('category', '')
        context['selected_type'] = self.request.GET.get('type', '')
        context['search_query'] = self.request.GET.get('q', '')
        
        # 統計資料
        context['total_products'] = self.get_queryset().count()
        
        # 從 cookie 獲取購物車
        cart = {}
        cart_cookie = self.request.COOKIES.get('cart', '{}')
        try:
            decoded_cookie = unquote(cart_cookie)
            cart = json.loads(decoded_cookie)
            logger.info(f'購物車內容：{cart}')
        except json.JSONDecodeError:
            cart = {}
            logger.warning('購物車 JSON 解析失敗')

        # 使用 products.utils 的統一價格獲取函數
        for product in context['products']:
            active_variants = product.variants.all()
            
            for variant in active_variants:
                # 使用新的統一價格函數
                display_price, original_price, has_sale = get_variant_price_for_user(variant, user)
                variant.display_price = display_price
                variant.display_original_price = original_price
                variant.has_sale = has_sale
                
                # 計算庫存數量（只統計未使用的庫存）
                stock_total = Stock.objects.filter(
                    product=variant,
                    is_used=False
                ).aggregate(
                    total=Sum('quantity')
                )['total'] or 0
                
                variant.stock_quantity = stock_total
                variant.has_stock = stock_total > 0
                
                logger.info(f'變體 {variant.id} [{user.role}] - 顯示價格：{display_price}, 原價：{original_price}, 有特價：{has_sale}, 庫存：{stock_total}')
                
                # 添加購物車數量
                variant_id_str = str(variant.id)
                if variant_id_str in cart:
                    variant.cart_quantity = cart[variant_id_str].get('quantity', 0)
                    logger.info(f'變體 {variant.id} 在購物車中，數量：{variant.cart_quantity}')
                else:
                    variant.cart_quantity = 0
        
        context['cart'] = cart
        return context


# 產品變體詳情 Variant Detail (AJAX)
# from django.http import JsonResponse
# from django.views import View

# class VariantDetailView(View):
#     """
#     用於 AJAX 獲取變體詳細資訊
#     """
#     def get(self, request, pk):
#         try:
#             variant = Variant.objects.select_related('product').get(
#                 pk=pk,
#                 status=VariantStatus.ACTIVE,
#                 product__status=ProductStatus.ACTIVE
#             )
            
#             data = {
#                 'id': variant.id,
#                 'name': variant.name,
#                 'description': variant.description,
#                 'product_type': variant.product_type,
#                 'product_type_display': variant.get_product_type_display(),
#                 'product_code': variant.product_code,
#                 'days': variant.days,
#                 'data_amount': variant.data_amount,
#                 'price': float(variant.price) if variant.price else None,
#                 'price_sales': float(variant.price_sales) if variant.price_sales else None,
#                 'price_agent': float(variant.price_agent) if variant.price_agent else None,
#                 'price_sales_agent': float(variant.price_sales_agent) if variant.price_sales_agent else None,
#             }
            
#             return JsonResponse(data)
#         except Variant.DoesNotExist:
#             return JsonResponse({'error': '產品變體不存在或已下架'}, status=404)


# 庫存列表
class StockListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    """
    庫存列表視圖
    
    功能：
    1. 顯示所有庫存項目
    2. 支援篩選：產品變體、使用狀態
    3. 支援搜尋：庫存名稱、代碼
    """
    model = Stock
    template_name = 'products/stock_list.html'
    context_object_name = 'stocks'
    paginate_by = 20
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以查看庫存列表
        """
        return is_headquarter_admin(self.request.user)
    
    def get_queryset(self):
        queryset = Stock.objects.select_related(
            'product',              # Variant
            'product__product'      # Product
        ).all()
        
        # 1. 搜尋功能 (名稱、代碼)
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(code__icontains=search_query) |
                Q(product__name__icontains=search_query) |
                Q(product__product_code__icontains=search_query)
            )
            
        # 2. 篩選：產品變體
        variant_id = self.request.GET.get('variant')
        if variant_id:
            queryset = queryset.filter(product_id=variant_id)
            
        # 3. 篩選：使用狀態
        status = self.request.GET.get('status')
        if status == 'used':
            queryset = queryset.filter(is_used=True)
        elif status == 'unused':
            queryset = queryset.filter(is_used=False)
            
        # 4. 篩選：庫存類型 (透過 Variant 的 product_type)
        product_type = self.request.GET.get('type')
        if product_type:
            queryset = queryset.filter(product__product_type=product_type)

        return queryset.order_by('-created_at')
        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 傳遞篩選選項
        context['variants'] = Variant.objects.filter(
            status=VariantStatus.ACTIVE
        ).select_related('product').order_by('product__name', 'name')
        
        context['product_types'] = ProductType.choices
        
        # 保持搜尋參數
        context['search_query'] = self.request.GET.get('q', '')
        context['selected_variant'] = self.request.GET.get('variant', '')
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_type'] = self.request.GET.get('type', '')
        
        # 統計數據
        queryset = self.get_queryset()
        context['total_count'] = queryset.count()
        context['unused_count'] = queryset.filter(is_used=False).count()
        
        return context

# 庫存新增
class StockCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = Stock
    form_class = StockCreateForm
    template_name = 'products/stock_form.html'
    success_url = reverse_lazy('products:stock_list')

    def test_func(self):
        return is_headquarter_admin(self.request.user)

    def form_valid(self, form):
        import os
        import logging
        
        logger = logging.getLogger(__name__)
        
        # 暫停儲存，先獲取資料
        stock = form.save(commit=False)
        variant = stock.product
        product_type = variant.product_type
        
        # 獲取額外欄位資料
        qr_images = self.request.FILES.getlist('qr_images')
        
        created_count = 0
        failed_count = 0
        failed_files = []
        
        try:
            with transaction.atomic():
                # 情況 A: ESIMIMG (圖庫) - 依圖片數量建立多筆
                if product_type == ProductType.ESIMIMG and qr_images:
                    # ✅ 檢查 variant 是否有 SKU
                    if not variant.sku:
                        messages.error(
                            self.request, 
                            f'❌ 該產品變體未設定 SKU，無法上傳 ESIMIMG 圖片。請先在產品管理中設定 SKU。'
                        )
                        return self.form_invalid(form)
                    
                    logger.info(f'開始批量建立 ESIMIMG 庫存，目標 SKU 資料夾：{variant.sku}')
                    
                    for img in qr_images:
                        try:
                            # 從檔名提取 code（去除副檔名）
                            filename = img.name
                            code = os.path.splitext(filename)[0]  # 例如：'10000001.png' → '10000001'
                            
                            # ✅ 驗證檔名格式（可選，確保檔名符合預期）
                            if not code.strip():
                                logger.warning(f'檔案 {filename} 的檔名無效，跳過')
                                failed_count += 1
                                failed_files.append(filename)
                                continue
                            
                            # 建立庫存記錄
                            # Django 會自動調用 stock_qr_image_path 函數來決定存儲路徑
                            stock_instance = Stock.objects.create(
                                product=variant,
                                name=f"{stock.name} - {code}",  # 使用 code 作為名稱一部分
                                description=stock.description,
                                qr_img=img,  # Django 會自動處理文件上傳和路徑
                                code=code,  # 儲存從檔名提取的 code
                                initial_quantity=1,
                                quantity=1,
                                expire_date=stock.expire_date,
                                is_used=False
                            )
                            created_count += 1
                            
                            logger.info(
                                f'✅ 成功建立庫存：ID={stock_instance.id}, '
                                f'Code={code}, 圖片路徑={stock_instance.qr_img.name}'
                            )
                            
                        except Exception as e:
                            logger.error(f'❌ 處理檔案 {img.name} 時發生錯誤：{str(e)}')
                            failed_count += 1
                            failed_files.append(img.name)
                            continue
                    
                    # 顯示結果訊息
                    if created_count > 0:
                        success_msg = f'✅ 已成功建立 {created_count} 筆 ESIMIMG 庫存'
                        if failed_count > 0:
                            success_msg += f'，{failed_count} 筆失敗'
                        messages.success(self.request, success_msg)
                        
                        if failed_files:
                            messages.warning(
                                self.request, 
                                f'失敗的檔案：{", ".join(failed_files[:5])}' + 
                                (f' 等 {len(failed_files)} 個檔案' if len(failed_files) > 5 else '')
                            )
                    else:
                        messages.error(self.request, '❌ 所有圖片上傳失敗，請檢查檔案格式')
                        return self.form_invalid(form)
                    
                    return redirect(self.success_url)

                # 情況 B: 其他所有類型 - 建立單筆
                else:
                    stock.initial_quantity = stock.quantity
                    stock.save()
                    
                    logger.info(
                        f'✅ 建立標準庫存：ID={stock.id}, '
                        f'產品={stock.product.name}, 數量={stock.quantity}'
                    )
                    
                    messages.success(
                        self.request, 
                        f'✅ 已建立庫存：{stock.name} (數量: {stock.quantity})'
                    )
                    return redirect(self.success_url)

        except Exception as e:
            logger.error(f'❌ 庫存建立過程發生錯誤：{str(e)}')
            messages.error(self.request, f'❌ 建立失敗：{str(e)}')
            return self.form_invalid(form)


# 供應商列表
class SupplierListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    """
    供應商列表視圖
    
    權限：只有總公司管理員可以查看
    
    功能：
    1. 顯示所有供應商
    2. 支援搜尋：供應商名稱、代碼
    3. 支援排序：按 sort_order 排序
    4. 分頁：每頁 20 筆
    """
    model = Supplier
    template_name = 'products/supplier_list.html'
    context_object_name = 'suppliers'
    paginate_by = 20
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以查看供應商列表
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.warning(self.request, '權限不足：只有總公司管理員可以查看供應商列表')
        return redirect('products:catalogue_list')
    
    def get_queryset(self):
        """
        獲取供應商列表，支援搜尋和排序
        """
        queryset = Supplier.objects.all()
        
        # 搜尋功能
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(supplier_code__icontains=search_query) |
                Q(description__icontains=search_query)
            )
        
        # 排序
        return queryset.order_by('sort_order', 'id')
    
    def get_context_data(self, **kwargs):
        """
        添加額外的 context 資料
        """
        context = super().get_context_data(**kwargs)
        
        # 統計資料
        context['total_suppliers'] = self.get_queryset().count()
        
        # 保持搜尋參數
        context['search_query'] = self.request.GET.get('q', '')
        
        # 權限資訊
        context['is_headquarter'] = is_headquarter_admin(self.request.user)
        
        return context


# 供應商新增
class SupplierCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    """
    新增供應商視圖
    """
    model = Supplier
    template_name = 'products/supplier_form.html'
    fields = ['name', 'supplier_code', 'description', 'sort_order']
    success_url = reverse_lazy('products:supplier_list')
    
    def test_func(self):
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        messages.warning(self.request, '權限不足：只有總公司管理員可以新增供應商')
        return redirect('products:supplier_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'✅ 供應商「{form.instance.name}」建立成功！')
        return super().form_valid(form)


# 供應商編輯
class SupplierUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    """
    編輯供應商視圖
    """
    model = Supplier
    template_name = 'products/supplier_form.html'
    fields = ['name', 'supplier_code', 'description', 'sort_order']
    success_url = reverse_lazy('products:supplier_list')
    
    def test_func(self):
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        messages.warning(self.request, '權限不足：只有總公司管理員可以編輯供應商')
        return redirect('products:supplier_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'✅ 供應商「{form.instance.name}」更新成功！')
        return super().form_valid(form)


# 供應商刪除
class SupplierDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    """
    刪除供應商視圖
    """
    model = Supplier
    template_name = 'products/supplier_confirm_delete.html'
    success_url = reverse_lazy('products:supplier_list')
    
    def test_func(self):
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        messages.warning(self.request, '權限不足：只有總公司管理員可以刪除供應商')
        return redirect('products:supplier_list')
    
    def delete(self, request, *args, **kwargs):
        supplier = self.get_object()
        messages.success(request, f'✅ 供應商「{supplier.name}」已刪除')
        return super().delete(request, *args, **kwargs)


# 產品分類列表
class CategoryListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    """
    產品分類列表視圖
    
    權限：只有總公司管理員可以查看
    
    功能：
    1. 顯示所有產品分類
    2. 支援搜尋：分類名稱、描述
    3. 支援排序：按 sort_order 排序
    4. 顯示每個分類的產品數量
    5. 分頁：每頁 20 筆
    """
    model = Category
    template_name = 'products/category_list.html'
    context_object_name = 'categories'
    paginate_by = 20
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以查看分類列表
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.warning(self.request, '權限不足：只有總公司管理員可以查看產品分類列表')
        return redirect('products:catalogue_list')
    
    def get_queryset(self):
        """
        獲取分類列表，支援搜尋和排序
        """
        queryset = Category.objects.annotate(
            product_count=Count('products', distinct=True),
            active_product_count=Count(
                'products',
                filter=Q(products__status=ProductStatus.ACTIVE),
                distinct=True
            )
        )
        
        # 搜尋功能
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(description__icontains=search_query)
            )
        
        # 排序
        return queryset.order_by('sort_order', 'id')
    
    def get_context_data(self, **kwargs):
        """
        添加額外的 context 資料
        """
        context = super().get_context_data(**kwargs)
        
        # 統計資料
        context['total_categories'] = self.get_queryset().count()
        
        # 保持搜尋參數
        context['search_query'] = self.request.GET.get('q', '')
        
        # 權限資訊
        context['is_headquarter'] = is_headquarter_admin(self.request.user)
        
        return context


# 產品分類新增
class CategoryCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    """
    新增產品分類視圖
    """
    model = Category
    template_name = 'products/category_form.html'
    fields = ['name', 'description', 'sort_order']
    success_url = reverse_lazy('products:category_list')
    
    def test_func(self):
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        messages.warning(self.request, '權限不足：只有總公司管理員可以新增產品分類')
        return redirect('products:category_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'✅ 產品分類「{form.instance.name}」建立成功！')
        return super().form_valid(form)


# 產品分類編輯
class CategoryUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    """
    編輯產品分類視圖
    """
    model = Category
    template_name = 'products/category_form.html'
    fields = ['name', 'description', 'sort_order']
    success_url = reverse_lazy('products:category_list')
    
    def test_func(self):
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        messages.warning(self.request, '權限不足：只有總公司管理員可以編輯產品分類')
        return redirect('products:category_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'✅ 產品分類「{form.instance.name}」更新成功！')
        return super().form_valid(form)


# 產品分類刪除
class CategoryDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    """
    刪除產品分類視圖
    """
    model = Category
    template_name = 'products/category_confirm_delete.html'
    success_url = reverse_lazy('products:category_list')
    
    def test_func(self):
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        messages.warning(self.request, '權限不足：只有總公司管理員可以刪除產品分類')
        return redirect('products:category_list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 檢查是否有產品使用此分類
        category = self.get_object()
        context['product_count'] = category.products.count()
        context['has_products'] = context['product_count'] > 0
        
        return context
    
    def delete(self, request, *args, **kwargs):
        category = self.get_object()
        
        # 檢查是否有產品使用此分類
        if category.products.exists():
            messages.error(
                request,
                f'❌ 無法刪除分類「{category.name}」：'
                f'此分類下還有 {category.products.count()} 個產品。'
                f'請先移除或重新分類這些產品。'
            )
            return redirect('products:category_list')
        
        messages.success(request, f'✅ 產品分類「{category.name}」已刪除')
        return super().delete(request, *args, **kwargs)


# 產品列表
class ProductListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    """
    產品列表視圖（後台管理）
    
    權限：只有總公司管理員可以查看
    
    功能：
    1. 顯示所有產品（包含上架/下架）
    2. 支援搜尋：產品名稱、描述
    3. 支援篩選：分類、狀態、產品類型
    4. 顯示每個產品的變體數量
    5. 分頁：每頁 20 筆
    """
    model = Product
    template_name = 'products/product_list.html'
    context_object_name = 'products'
    paginate_by = 20
    
    def test_func(self):
        """
        權限檢查：只有總公司管理員可以查看產品列表
        """
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.warning(self.request, '權限不足：只有總公司管理員可以查看產品列表')
        return redirect('products:catalogue_list')
    
    def get_queryset(self):
        """
        獲取產品列表，支援搜尋和篩選
        """
        queryset = Product.objects.select_related('category').annotate(
            variant_count=Count('variants', distinct=True),
            active_variant_count=Count(
                'variants',
                filter=Q(variants__status=VariantStatus.ACTIVE),
                distinct=True
            )
        )
        
        # 搜尋功能
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(description__icontains=search_query) |
                Q(variants__name__icontains=search_query) |
                Q(variants__product_code__icontains=search_query)
            ).distinct()
        
        # 分類篩選
        category_id = self.request.GET.get('category')
        if category_id:
            try:
                queryset = queryset.filter(category_id=int(category_id))
            except (ValueError, TypeError):
                pass
        
        # 狀態篩選
        status = self.request.GET.get('status')
        if status and status in dict(ProductStatus.choices):
            queryset = queryset.filter(status=status)
        
        # ✅ 產品類型篩選
        product_type = self.request.GET.get('type')
        if product_type and product_type in dict(ProductType.choices):
            queryset = queryset.filter(
                variants__product_type=product_type
            ).distinct()
        
        # 排序
        return queryset.order_by('sort_order', 'id')
    
    def get_context_data(self, **kwargs):
        """
        添加額外的 context 資料
        """
        context = super().get_context_data(**kwargs)
        
        # 統計資料
        context['total_products'] = self.get_queryset().count()
        context['active_products'] = Product.objects.filter(
            status=ProductStatus.ACTIVE
        ).count()
        context['inactive_products'] = Product.objects.filter(
            status=ProductStatus.INACTIVE
        ).count()
        
        # 傳遞分類列表
        context['categories'] = Category.objects.all().order_by('sort_order')
        
        # 傳遞產品狀態選項
        context['product_statuses'] = ProductStatus.choices
        
        # ✅ 傳遞產品類型選項
        context['product_types'] = ProductType.choices
        
        # 保持搜尋參數
        context['search_query'] = self.request.GET.get('q', '')
        context['selected_category'] = self.request.GET.get('category', '')
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_type'] = self.request.GET.get('type', '')  # ✅ 新增
        
        # 權限資訊
        context['is_headquarter'] = is_headquarter_admin(self.request.user)
        
        return context


# 產品詳情（後台管理）
class ProductDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    """
    產品詳情視圖（後台管理）
    
    顯示：
    1. 產品基本資訊
    2. 所有變體列表（包含上架/下架）
    3. 庫存統計
    """
    model = Product
    template_name = 'products/product_detail_admin.html'
    context_object_name = 'product'
    
    def test_func(self):
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        messages.warning(self.request, '權限不足：只有總公司管理員可以查看產品詳情')
        return redirect('products:catalogue_list')
    
    def get_context_data(self, **kwargs):
        from django.db.models import Sum
        
        context = super().get_context_data(**kwargs)
        
        # 獲取所有變體（包含上架/下架）
        variants = self.object.variants.all().order_by('sort_order')
        context['variants'] = variants
        
        # 為每個變體計算庫存
        for variant in variants:
            variant.total_stock = Stock.objects.filter(
                product=variant,
                is_used=False
            ).aggregate(total=Sum('quantity'))['total'] or 0
        
        # 統計資料
        context['total_variants'] = variants.count()
        context['active_variants'] = variants.filter(
            status=VariantStatus.ACTIVE
        ).count()
        
        context['is_headquarter'] = is_headquarter_admin(self.request.user)
        
        return context


# 產品新增
class ProductCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    """
    新增產品視圖
    """
    model = Product
    template_name = 'products/product_form.html'
    fields = ['name', 'description', 'category', 'status', 'sort_order']
    success_url = reverse_lazy('products:product_list')
    
    def test_func(self):
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        messages.warning(self.request, '權限不足：只有總公司管理員可以新增產品')
        return redirect('products:product_list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all().order_by('sort_order')
        context['product_statuses'] = ProductStatus.choices
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'✅ 產品「{form.instance.name}」建立成功！')
        return super().form_valid(form)


# 產品編輯
class ProductUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    """
    編輯產品視圖
    """
    model = Product
    template_name = 'products/product_form.html'
    fields = ['name', 'description', 'category', 'status', 'sort_order']
    success_url = reverse_lazy('products:product_list')
    
    def test_func(self):
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        messages.warning(self.request, '權限不足：只有總公司管理員可以編輯產品')
        return redirect('products:product_list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all().order_by('sort_order')
        context['product_statuses'] = ProductStatus.choices
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'✅ 產品「{form.instance.name}」更新成功！')
        return super().form_valid(form)


# 產品刪除
class ProductDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    """
    刪除產品視圖
    """
    model = Product
    template_name = 'products/product_confirm_delete.html'
    success_url = reverse_lazy('products:product_list')
    
    def test_func(self):
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        messages.warning(self.request, '權限不足：只有總公司管理員可以刪除產品')
        return redirect('products:product_list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 檢查是否有變體
        product = self.get_object()
        context['variant_count'] = product.variants.count()
        context['has_variants'] = context['variant_count'] > 0
        
        return context
    
    def delete(self, request, *args, **kwargs):
        product = self.get_object()
        
        # 檢查是否有變體
        if product.variants.exists():
            messages.error(
                request,
                f'❌ 無法刪除產品「{product.name}」：'
                f'此產品下還有 {product.variants.count()} 個變體。'
                f'請先刪除所有變體後再刪除產品。'
            )
            return redirect('products:product_list')
        
        messages.success(request, f'✅ 產品「{product.name}」已刪除')
        return super().delete(request, *args, **kwargs)


# 產品變體列表
class VariantListView(LoginRequiredMixin, ListView):
    """
    產品變體列表視圖（後台管理）
    
    權限：總公司管理員和代理商可以查看
    
    功能：
    1. 顯示所有變體（包含上架/下架）
    2. 支援搜尋：變體名稱、產品代碼、SKU
    3. 支援篩選：產品、產品類型、狀態
    4. 顯示庫存資訊
    5. AGENT 可查看自己設定的經銷價格
    6. 分頁：每頁 30 筆
    """
    model = Variant
    template_name = 'products/variant_list.html'
    context_object_name = 'variants'
    paginate_by = 30
    
    def test_func(self):
        """
        權限檢查：總公司管理員和代理商可以查看變體列表
        """
        return is_headquarter_admin(self.request.user) or is_agent(self.request.user)
    
    def handle_no_permission(self):
        """
        當用戶沒有權限時的處理
        """
        messages.warning(self.request, '權限不足：只有總公司管理員和代理商可以查看變體列表')
        return redirect('products:catalogue_list')
    
    def get_queryset(self):
        """
        獲取變體列表，支援搜尋和篩選
        """
        from django.db.models import Sum
        
        queryset = Variant.objects.select_related(
            'product',
            'product__category'
        ).all()
        
        # 搜尋功能
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(product_code__icontains=search_query) |
                Q(sku__icontains=search_query) |
                Q(product__name__icontains=search_query) |
                Q(days__icontains=search_query) |
                Q(data_amount__icontains=search_query)
            )
        
        # 產品篩選
        product_id = self.request.GET.get('product')
        if product_id:
            try:
                queryset = queryset.filter(product_id=int(product_id))
            except (ValueError, TypeError):
                pass
        
        # 產品類型篩選
        product_type = self.request.GET.get('type')
        if product_type and product_type in dict(ProductType.choices):
            queryset = queryset.filter(product_type=product_type)
        
        # 狀態篩選
        status = self.request.GET.get('status')
        if status and status in dict(VariantStatus.choices):
            queryset = queryset.filter(status=status)
        
        # 排序
        return queryset.order_by('product__sort_order', 'sort_order', 'id')
    
    def get_context_data(self, **kwargs):
        """
        添加額外的 context 資料
        """
        from django.db.models import Sum
        
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # 為每個變體計算庫存和添加價格資訊
        for variant in context['variants']:
            # 計算庫存
            variant.total_stock = Stock.objects.filter(
                product=variant,
                is_used=False
            ).aggregate(total=Sum('quantity'))['total'] or 0
            
            # 如果是代理商，獲取其設定的經銷價格
            if is_agent(user):
                try:
                    agent_pricing = AgentDistributorPricing.objects.get(
                        variant=variant,
                        agent=user
                    )
                    variant.agent_price_distr = agent_pricing.price_distr
                    variant.agent_price_sales_distr = agent_pricing.price_sales_distr
                    variant.has_agent_pricing = True
                except AgentDistributorPricing.DoesNotExist:
                    variant.agent_price_distr = None
                    variant.agent_price_sales_distr = None
                    variant.has_agent_pricing = False
        
        # 統計資料
        all_variants = Variant.objects.all()
        context['total_variants'] = all_variants.count()
        context['active_variants'] = all_variants.filter(
            status=VariantStatus.ACTIVE
        ).count()
        context['inactive_variants'] = all_variants.filter(
            status=VariantStatus.INACTIVE
        ).count()
        
        # 按產品類型統計
        context['esim_count'] = all_variants.filter(
            product_type=ProductType.ESIM
        ).count()
        context['esimimg_count'] = all_variants.filter(
            product_type=ProductType.ESIMIMG
        ).count()
        context['rechargeable_count'] = all_variants.filter(
            product_type=ProductType.RECHARGEABLE
        ).count()
        context['physical_count'] = all_variants.filter(
            product_type=ProductType.PHYSICAL
        ).count()
        
        # 傳遞產品列表
        context['products'] = Product.objects.all().order_by('sort_order', 'name')
        
        # 傳遞產品類型選項
        context['product_types'] = ProductType.choices
        
        # 傳遞狀態選項
        context['variant_statuses'] = VariantStatus.choices
        
        # 保持搜尋參數
        context['search_query'] = self.request.GET.get('q', '')
        context['selected_product'] = self.request.GET.get('product', '')
        context['selected_type'] = self.request.GET.get('type', '')
        context['selected_status'] = self.request.GET.get('status', '')
        
        # 權限資訊
        context['is_headquarter'] = is_headquarter_admin(user)
        context['is_agent'] = is_agent(user)
        
        # 如果是代理商，統計已設定經銷價格的變體數量
        if is_agent(user):
            context['agent_priced_variants'] = AgentDistributorPricing.objects.filter(
                agent=user
            ).count()
        
        return context


# 產品變體新增
class VariantCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    """
    新增產品變體視圖
    
    權限：只有總公司管理員可以新增
    
    功能：
    1. 新增產品變體
    2. 支援從產品詳情頁跳轉並自動選擇產品
    3. 完整的價格設定
    4. SKU 和產品代碼管理
    """
    model = Variant
    template_name = 'products/variant_form.html'
    fields = [
        'product', 'name', 'description', 'product_type', 'status',
        'product_code', 'sku', 'days', 'data_amount',
        'price', 'price_sales', 'price_agent', 'price_sales_agent',
        'price_peer', 'price_sales_peer',  # 新增同業價格欄位
        'sort_order'
    ]
    
    def test_func(self):
        return is_headquarter_admin(self.request.user)
    
    def handle_no_permission(self):
        messages.warning(self.request, '權限不足：只有總公司管理員可以新增產品變體')
        return redirect('products:variant_list')
    
    def get_success_url(self):
        # 成功後返回該產品的詳情頁
        return reverse_lazy('products:product_detail', kwargs={'pk': self.object.product.id})
    
    def get_initial(self):
        """
        設定初始值：如果 URL 包含 product_id，自動選擇該產品
        """
        initial = super().get_initial()
        product_id = self.request.GET.get('product_id')
        if product_id:
            try:
                initial['product'] = Product.objects.get(pk=product_id)
            except Product.DoesNotExist:
                pass
        return initial
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 傳遞產品列表
        context['products'] = Product.objects.all().order_by('sort_order', 'name')
        
        # 傳遞產品類型選項
        context['product_types'] = ProductType.choices
        
        # 傳遞變體狀態選項
        context['variant_statuses'] = VariantStatus.choices
        
        # 如果是從產品詳情頁跳轉過來的，傳遞產品資訊
        product_id = self.request.GET.get('product_id')
        if product_id:
            try:
                context['selected_product'] = Product.objects.get(pk=product_id)
            except Product.DoesNotExist:
                pass
        
        return context
    
    def form_valid(self, form):
        messages.success(
            self.request, 
            f'變體「{form.instance.name}」建立成功！'
            f'所屬產品：{form.instance.product.name}'
        )
        return super().form_valid(form)


# 產品變體更新
class VariantUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    """
    編輯產品變體視圖
    
    權限：總公司管理員或代理商可以編輯
    
    功能：
    1. 總公司管理員：可以編輯所有欄位
    2. 代理商：只能編輯自己的經銷價格（price_distr, price_sales_distr）
    3. 成功後返回產品詳情頁
    """
    model = Variant
    template_name = 'products/variant_form.html'
    fields = [
        'product', 'name', 'description', 'product_type', 'status',
        'product_code', 'sku', 'days', 'data_amount',
        'price', 'price_sales', 'price_agent', 'price_sales_agent',
        'price_peer', 'price_sales_peer',
        'sort_order'
    ]
    
    def test_func(self):
        # 允許總公司管理員或代理商訪問
        return is_headquarter_admin(self.request.user) or is_agent(self.request.user)
    
    def handle_no_permission(self):
        messages.warning(self.request, '權限不足：只有總公司管理員或代理商可以編輯產品變體')
        return redirect('products:variant_list')
    
    def get_success_url(self):
        # 成功後返回該產品的詳情頁
        return reverse_lazy('products:product_detail', kwargs={'pk': self.object.product.id})
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 傳遞產品列表
        context['products'] = Product.objects.all().order_by('sort_order', 'name')
        
        # 傳遞產品類型選項
        context['product_types'] = ProductType.choices
        
        # 傳遞變體狀態選項
        context['variant_statuses'] = VariantStatus.choices
        
        # 傳遞當前變體所屬的產品
        context['selected_product'] = self.object.product
        
        # 如果是代理商，獲取或創建其經銷價格記錄
        if is_agent(self.request.user):
            try:
                agent_pricing = AgentDistributorPricing.objects.get(
                    variant=self.object,
                    agent=self.request.user
                )
                context['agent_pricing_form'] = AgentDistributorPricingForm(
                    instance=agent_pricing,
                    prefix='agent_pricing'
                )
            except AgentDistributorPricing.DoesNotExist:
                # 如果不存在，創建一個空表單
                context['agent_pricing_form'] = AgentDistributorPricingForm(
                    prefix='agent_pricing'
                )
            
            context['has_agent_pricing'] = AgentDistributorPricing.objects.filter(
                variant=self.object,
                agent=self.request.user
            ).exists()
        
        return context
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        
        # 如果是代理商，處理經銷價格表單
        if is_agent(request.user):
            agent_pricing_form = AgentDistributorPricingForm(
                request.POST,
                prefix='agent_pricing'
            )
            
            if agent_pricing_form.is_valid():
                # 獲取或創建 AgentDistributorPricing 記錄
                agent_pricing, created = AgentDistributorPricing.objects.update_or_create(
                    variant=self.object,
                    agent=request.user,
                    defaults={
                        'price_distr': agent_pricing_form.cleaned_data['price_distr'],
                        'price_sales_distr': agent_pricing_form.cleaned_data.get('price_sales_distr'),
                    }
                )
                
                action = '建立' if created else '更新'
                messages.success(
                    request,
                    f'✅ 經銷價格{action}成功！價格：NT$ {agent_pricing.price_distr:,.0f}'
                )
                return redirect(self.get_success_url())
            else:
                # 表單驗證失敗
                messages.error(request, '經銷價格設定失敗，請檢查輸入')
                context = self.get_context_data()
                context['agent_pricing_form'] = agent_pricing_form
                return self.render_to_response(context)
        
        # 如果是總公司管理員，使用原來的邏輯
        return super().post(request, *args, **kwargs)
    
    def form_valid(self, form):
        # 只有總公司管理員才會執行到這裡
        messages.success(
            self.request,
            f'✅ 變體「{form.instance.name}」更新成功！'
        )
        return super().form_valid(form)


