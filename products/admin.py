from django.contrib import admin
from products.models import Supplier, Category, Product, Variant, AgentDistributorPricing, Stock

# Register your models here.
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'supplier_code', 'sort_order')
    search_fields = ('name', 'supplier_code')
    ordering = ('id',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Supplier Info', {'fields': ('name', 'description', 'supplier_code', 'sort_order')}),
    )

class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'sort_order')
    search_fields = ('name', 'description')
    ordering = ('sort_order',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Category Info', {'fields': ('name', 'description', 'sort_order')}),
    )

class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'category', 'status')
    search_fields = ('name', 'description', 'category')
    list_filter = ('category', 'status')
    ordering = ('id',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Product Info', {'fields': ('name', 'description', 'category', 'status', 'created_at', 'updated_at')}),
    )

class VariantAdmin(admin.ModelAdmin):
    list_display = ('name', 'id', 'status', 'product', 'product_code', 'price', 'price_sales')
    search_fields = ('name', 'description', 'product', 'product_code')
    list_filter = ('product', 'product_type', 'status')
    ordering = ('id',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Variant Info', {'fields': ('name', 'description', 'status', 'product_type', 'sku', 'product', 'product_code', 'days', 'data_amount', 'price', 'price_sales', 'price_agent', 'price_sales_agent', 'sort_order', 'created_at', 'updated_at')}),
    )

class AgentDistributorPricingAdmin(admin.ModelAdmin):
    list_display = ('variant', 'agent', 'price_distr', 'price_sales_distr')
    search_fields = ('variant', 'agent')
    list_filter = ('variant', 'agent')
    ordering = ('id',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Agent Distributor Pricing', {'fields': ('variant', 'agent', 'price_distr', 'price_sales_distr')}),
    )

class StockAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'product', 'code', 'initial_quantity', 'quantity', 'exchange_time', 'created_at')
    search_fields = ('name', 'description', 'product', 'code')
    list_filter = ('product', 'is_used')
    ordering = ('id',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Stock Info', {'fields': ('name', 'description', 'product', 'code', 'qr_img', 'initial_quantity', 'quantity', 'expire_date', 'is_used', 'exchange_time', 'created_at', 'updated_at')}),
    )

admin.site.register(Supplier, SupplierAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Product, ProductAdmin)
admin.site.register(Variant, VariantAdmin)
admin.site.register(AgentDistributorPricing, AgentDistributorPricingAdmin)
admin.site.register(Stock, StockAdmin)
