from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from business.models import Order
from business.constant import OrderStatus
from reports.models import DailySalesReport, DailySalesSummary, MonthlySalesReport, MonthlySalesSummary, AnnualSalesReport, AnnualSalesSummary
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Order)
def update_daily_report_on_order_complete(sender, instance, created, **kwargs):
    """
    當訂單狀態變為完成時，即時更新日報表
    
    觸發時機：
    - 訂單狀態變更為 PAID（已付款）
    """
    # 只在訂單完成時更新
    if instance.status == OrderStatus.PAID:
        try:
            # 獲取訂單建立日期
            report_date = instance.created_at.date()
            
            # 更新該用戶的日報表
            DailySalesReport.update_or_create_report(
                user=instance.account,
                report_date=report_date
            )
            
            # 更新當日營業總結
            DailySalesSummary.generate_summary(report_date)
            
            logger.info(
                f"訂單完成，已更新日報表：{instance.id} - "
                f"{instance.account.fullname} - ${instance.total_amount:,}"
            )
            
        except Exception as e:
            logger.error(f"❌ 更新日報表失敗：{instance.id} - {str(e)}", exc_info=True)


@receiver(post_delete, sender=Order)
def update_daily_report_on_order_delete(sender, instance, **kwargs):
    """
    當訂單被刪除時，重新計算日報表
    """
    if instance.status == OrderStatus.PAID:
        try:
            report_date = instance.created_at.date()
            
            # 重新計算該用戶的日報表
            DailySalesReport.update_or_create_report(
                user=instance.account,
                report_date=report_date
            )
            
            # 更新當日營業總結
            DailySalesSummary.generate_summary(report_date)
            
            logger.info(f"訂單刪除，已重新計算日報表：{instance.id}")
            
        except Exception as e:
            logger.error(f"❌ 重新計算日報表失敗：{instance.id} - {str(e)}", exc_info=True)


# 【重要修改】添加條件判斷，避免每次保存都觸發
@receiver(post_save, sender=DailySalesReport)
def update_monthly_report_on_daily_update(sender, instance, created, **kwargs):
    """
    當日報表更新時，自動更新對應的月報表
    
    觸發時機：
    - 日報表建立或更新時
    
    優化：只在必要時更新月報表
    """
    # 【新增】避免不必要的更新：如果是舊數據的小幅更新，可能不需要重算月報表
    # 但為了數據準確性，這裡還是選擇每次都更新
    
    try:
        year = instance.report_date.year
        month = instance.report_date.month
        
        # 更新該用戶的月報表
        MonthlySalesReport.update_or_create_report(
            user=instance.user,
            year=year,
            month=month
        )
        
        # 更新當月營業總結
        MonthlySalesSummary.generate_summary(year, month)
        
        logger.info(
            f"日報表更新，已同步更新月報表：{year}-{month:02d} - "
            f"{instance.user.fullname}"
        )
        
    except Exception as e:
        logger.error(
            f"❌ 更新月報表失敗：{instance.report_date} - "
            f"{instance.user.fullname} - {str(e)}", 
            exc_info=True
        )


@receiver(post_save, sender=MonthlySalesReport)
def update_annual_report_on_monthly_update(sender, instance, created, **kwargs):
    """
    當月報表更新時，自動更新對應的年報表
    
    觸發時機：
    - 月報表建立或更新時
    """
    try:
        year = instance.report_year
        
        # 更新該用戶的年報表
        AnnualSalesReport.update_or_create_report(
            user=instance.user,
            year=year
        )
        
        # 更新當年營業總結
        AnnualSalesSummary.generate_summary(year)
        
        logger.info(
            f"月報表更新，已同步更新年報表：{year}年 - "
            f"{instance.user.fullname}"
        )
        
    except Exception as e:
        logger.error(
            f"❌ 更新年報表失敗：{year}年 - "
            f"{instance.user.fullname} - {str(e)}", 
            exc_info=True
        )