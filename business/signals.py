from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from business.models import Order, Receipt, ReceiptItem
from business.constant import OrderStatus, ReceiptType
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Order)
def create_receipt_for_order(sender, instance, created, **kwargs):
    """
    訂單建立時自動產生收據
    
    觸發條件：
    - 訂單建立時（created=True）
    - 不論訂單狀態
    
    注意：使用 transaction.on_commit() 確保在訂單產品都創建完成後才生成收據
    """
    if created:
        def create_receipt():
            try:
                # 獲取訂單帳號的統一編號（優先使用 tax_id）
                taxid = ''
                if hasattr(instance.account, 'tax_id') and instance.account.tax_id:
                    taxid = instance.account.tax_id
                
                # 1. 建立收據主表
                receipt = Receipt.objects.create(
                    order=instance,
                    receipt_to=instance.account.company or instance.account.fullname or instance.account.username,
                    taxid=taxid,
                    date=instance.created_at.date(),
                    remark=f'訂單 #{instance.id}',
                    created_by=instance.created_by,
                    receipt_type=ReceiptType.ORDER
                )
                
                logger.info(
                    f'自動建立收據：{receipt.receipt_number}（訂單 #{instance.id}），'
                    f'類型：{receipt.get_receipt_type_display()}，'
                    f'抬頭：{receipt.receipt_to}，'
                    f'統編：{taxid or "無"}'
                )
                
                # 2. 建立收據明細（從訂單產品）
                created_count = 0
                for order_product in instance.order_products.all():
                    # 獲取產品名稱
                    if order_product.variant:
                        product_name = f"{order_product.variant.product.name} - {order_product.variant.name}"
                    else:
                        product_name = f"產品代碼: {order_product.product_code}"
                    
                    ReceiptItem.objects.create(
                        receipt=receipt,
                        order_product=order_product,
                        product_name=product_name,
                        product_code=order_product.product_code or '',
                        quantity=order_product.quantity,
                        unit_price=order_product.unit_price
                    )
                    created_count += 1
                
                # 3. 如果有運費，也加入收據明細
                if instance.shipping_fee and instance.shipping_fee > 0:
                    ReceiptItem.objects.create(
                        receipt=receipt,
                        order_product=None,
                        product_name='運費',
                        product_code='SHIPPING',
                        quantity=1,
                        unit_price=instance.shipping_fee
                    )
                    created_count += 1
                    logger.info(f'添加運費項目：${instance.shipping_fee}')
                
                logger.info(
                    f'收據 {receipt.receipt_number} 建立了 {created_count} 筆明細，'
                    f'總額：${receipt.total_amount:,.0f}'
                )
                
            except Exception as e:
                logger.error(f'自動建立收據失敗：{str(e)}', exc_info=True)
        
        # ✅ 在 transaction 提交後才執行（確保 OrderProduct 都已創建）
        transaction.on_commit(create_receipt)