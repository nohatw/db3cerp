from django.urls import path, include
from business import views
from business.views import (
    TopupListView, TopupCreateView, cart_view, 
    add_to_cart, update_cart, update_cart_price, remove_from_cart, 
    checkout_view, submit_order, OrderListView, OrderDetailView, OrderProductDetailView, 
    RechargeableCodesManageView, save_rechargeable_codes, DeleteOrderView,
    submit_reservation, ReceiptListView, ReceiptDetailView, ReceiptPrintView, ReceiptCreateView, 
    ReceiptUpdateView, ExpenseListView, ExpenseListView, ExpenseCreateView, ExpenseUpdateView, ExpenseDeleteView,
    IncomeListView, IncomeCreateView, IncomeUpdateView, IncomeDeleteView
)

app_name = 'business'

urlpatterns = [
    # 儲值相關
    path('topup/', TopupListView.as_view(), name='topup_list'),
    path('topup/create/', TopupCreateView.as_view(), name='topup_create'),
    
    # 購物車相關
    path('cart/', views.cart_view, name='cart_view'),
    path('cart/add/<int:variant_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/update/<int:variant_id>/', views.update_cart, name='update_cart'),
    path('cart/update-price/<int:variant_id>/', views.update_cart_price, name='cart_update_price'),
    path('cart/remove/<int:variant_id>/', views.remove_from_cart, name='remove_from_cart'),
    
    # 結帳相關
    path('checkout/', views.checkout_view, name='checkout'),
    path('checkout/submit/', views.submit_order, name='submit_order'),

    # 提交預訂
    path('submit-reservation/', views.submit_reservation, name='submit_reservation'),

    # 預訂訂單相關
    path('orders/<str:order_id>/reservation/confirm/', 
         views.confirm_reservation, 
         name='confirm_reservation'),
    
    # 訂單列表
    path('orders/', views.OrderListView.as_view(), name='order_list'),

    # 訂單詳情
    path('orders/<str:pk>/', views.OrderDetailView.as_view(), name='order_detail'),
    path('orders/<str:order_id>/products/<int:product_id>/', 
         views.OrderProductDetailView.as_view(), 
         name='order_product_detail'),
     
    # RECHARGEABLE 卡號管理
    path(
        'orders/<str:order_id>/products/<int:product_id>/rechargeable-codes/',
        views.RechargeableCodesManageView.as_view(),
        name='rechargeable_codes_manage'
    ),
    path(
        'orders/<str:order_id>/products/<int:product_id>/rechargeable-codes/save/',
        views.save_rechargeable_codes,
        name='save_rechargeable_codes'
    ),
    # CSV 批量匯入
    path(
        'orders/<str:order_id>/products/<int:product_id>/rechargeable-codes/import-csv/',
        views.import_rechargeable_codes_csv,
        name='import_rechargeable_codes_csv'
    ),

    # 刪除訂單產品
    path('orders/<str:order_id>/products/<int:product_id>/delete/', 
         views.delete_order_product, 
         name='delete_order_product'),
    
    # 更新預訂產品數量
    path('orders/<str:order_id>/reservation/products/<int:product_id>/update/', 
         views.update_reservation_product_quantity, 
         name='update_reservation_product_quantity'),
    
    # 新增預訂產品
    path('orders/<str:order_id>/reservation/products/add/', 
         views.add_reservation_product, 
         name='add_reservation_product'),

    # 刪除訂單
    path('orders/<str:pk>/delete/', views.DeleteOrderView.as_view(), name='order_delete'),

    # 收據相關（調整順序）
    path('receipts/', ReceiptListView.as_view(), name='receipt_list'),
    path('receipts/create/', ReceiptCreateView.as_view(), name='receipt_create'),
    path('receipts/<int:pk>/edit/', ReceiptUpdateView.as_view(), name='receipt_update'),

    # 動態路徑放在後面
    path('receipts/<str:pk>/', ReceiptDetailView.as_view(), name='receipt_detail'),
    path('receipts/<str:pk>/print/', ReceiptPrintView.as_view(), name='receipt_print'),

    # 支出記錄
    path('expenses/', ExpenseListView.as_view(), name='expense_list'),
    path('expenses/create/', ExpenseCreateView.as_view(), name='expense_create'),
    path('expenses/<int:pk>/edit/', ExpenseUpdateView.as_view(), name='expense_update'),
    path('expenses/<int:pk>/delete/', ExpenseDeleteView.as_view(), name='expense_delete'),

    # 收入記錄
    path('incomes/', IncomeListView.as_view(), name='income_list'),
    path('incomes/create/', IncomeCreateView.as_view(), name='income_create'),
    path('incomes/<int:pk>/edit/', IncomeUpdateView.as_view(), name='income_update'),
    path('incomes/<int:pk>/delete/', IncomeDeleteView.as_view(), name='income_delete'),
]