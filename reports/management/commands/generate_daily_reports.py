from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from datetime import datetime, timedelta
from reports.models import DailySalesReport, DailySalesSummary
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '生成營業收入日報表'
    
    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help='指定日期（格式：YYYY-MM-DD）')
        parser.add_argument('--days', type=int, default=1, help='生成過去N天的報表')
        parser.add_argument('--force', action='store_true', help='強制重新生成')
        parser.add_argument('--skip-cascade', action='store_true', help='跳過級聯更新（月報表/年報表）')
    
    def handle(self, *args, **options):
        if options['date']:
            try:
                end_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(self.style.ERROR('日期格式錯誤'))
                return
        else:
            end_date = timezone.now().date()
        
        days = options['days']
        skip_cascade = options['skip_cascade']
        
        self.stdout.write(f"開始生成報表...")
        self.stdout.write(f"結束日期：{end_date}")
        self.stdout.write(f"生成天數：{days}天")
        
        total_reports = 0
        
        # 【優化】使用事務批量處理
        with transaction.atomic():
            for i in range(days):
                report_date = end_date - timedelta(days=i)
                
                self.stdout.write(f"\n處理 {report_date} 的報表...")
                
                # 生成用戶日報表（不觸發Signal）
                from django.db.models.signals import post_save
                from reports.signals import update_monthly_report_on_daily_update
                
                if skip_cascade:
                    # 暫時斷開Signal
                    post_save.disconnect(update_monthly_report_on_daily_update, sender=DailySalesReport)
                
                count = DailySalesReport.generate_all_reports(report_date)
                total_reports += count
                
                if skip_cascade:
                    # 重新連接Signal
                    post_save.connect(update_monthly_report_on_daily_update, sender=DailySalesReport)
                
                self.stdout.write(
                    self.style.SUCCESS(f"✅ {report_date}: 生成 {count} 筆用戶報表")
                )
                
                # 生成營業總結
                summary = DailySalesSummary.generate_summary(report_date)
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✅ {report_date}: 總收入 ${summary.total_revenue:,}，"
                        f"訂單 {summary.total_orders} 筆"
                    )
                )
        
        # 【新增】批量生成後，統一更新月報表和年報表
        if not skip_cascade:
            self.stdout.write(self.style.WARNING("\n開始級聯更新月報表和年報表..."))
            
            # 獲取涉及的年月
            date_range = [end_date - timedelta(days=i) for i in range(days)]
            year_months = set((d.year, d.month) for d in date_range)
            years = set(d.year for d in date_range)
            
            # 批量更新月報表
            from reports.models import MonthlySalesReport, MonthlySalesSummary
            for year, month in sorted(year_months):
                MonthlySalesReport.generate_all_reports(year, month)
                MonthlySalesSummary.generate_summary(year, month)
                self.stdout.write(f"✅ 更新 {year}-{month:02d} 月報表")
            
            # 批量更新年報表
            from reports.models import AnnualSalesReport, AnnualSalesSummary
            for year in sorted(years):
                AnnualSalesReport.generate_all_reports(year)
                AnnualSalesSummary.generate_summary(year)
                self.stdout.write(f"✅ 更新 {year} 年報表")
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\n🎉 報表生成完成！共生成 {total_reports} 筆用戶報表"
            )
        )