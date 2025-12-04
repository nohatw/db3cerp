from django.urls import path, include
from business import views
from products.views import (
    CatalogueView, CatalogueDetailView, CatalogueViewForAgents, 
    StockListView, StockCreateView, StockUpdateView, StockDeleteView,
    SupplierListView, SupplierCreateView, SupplierUpdateView, SupplierDeleteView,
    CategoryListView, CategoryCreateView, CategoryUpdateView, CategoryDeleteView,
    ProductListView, ProductDetailView, ProductCreateView, ProductUpdateView, ProductDeleteView,
    VariantListView, VariantCreateView, VariantUpdateView
)

app_name = 'products'

urlpatterns = [
    path('catalogue/', CatalogueView.as_view(), name='catalogue_list'),
    path('catalogue/<int:pk>/', CatalogueDetailView.as_view(), name='catalogue_detail'),
    path('catalogue-agents/', CatalogueViewForAgents.as_view(), name='catalogue_agents'),
    path('stocks/', StockListView.as_view(), name='stock_list'),
    path('stocks/create/', StockCreateView.as_view(), name='stock_create'),
    path('stocks/<int:pk>/edit/', StockUpdateView.as_view(), name='stock_update'),
    path('stocks/<int:pk>/delete/', StockDeleteView.as_view(), name='stock_delete'),

    # 供應商管理
    path('suppliers/', SupplierListView.as_view(), name='supplier_list'),
    path('suppliers/create/', SupplierCreateView.as_view(), name='supplier_create'),
    path('suppliers/<int:pk>/edit/', SupplierUpdateView.as_view(), name='supplier_update'),
    path('suppliers/<int:pk>/delete/', SupplierDeleteView.as_view(), name='supplier_delete'),

    # 產品分類管理
    path('categories/', CategoryListView.as_view(), name='category_list'),
    path('categories/create/', CategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/edit/', CategoryUpdateView.as_view(), name='category_update'),
    path('categories/<int:pk>/delete/', CategoryDeleteView.as_view(), name='category_delete'),

    # 產品管理
    path('products/', ProductListView.as_view(), name='product_list'),
    path('products/create/', ProductCreateView.as_view(), name='product_create'),
    path('products/<int:pk>/', ProductDetailView.as_view(), name='product_detail'),
    path('products/<int:pk>/edit/', ProductUpdateView.as_view(), name='product_update'),
    path('products/<int:pk>/delete/', ProductDeleteView.as_view(), name='product_delete'),

    # 產品變體管理
    path('variants/', VariantListView.as_view(), name='variant_list'),
    path('variants/create/', VariantCreateView.as_view(), name='variant_create'),
    path('variants/<int:pk>/edit/', VariantUpdateView.as_view(), name='variant_update'),
]