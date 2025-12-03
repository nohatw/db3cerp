from django.core.management.base import BaseCommand
from django.utils import timezone
from reports.models import AnnualSalesReport, AnnualSalesSummary
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '生成營業收入年報表'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            help='指定年份，預設為當前年份'
        )
        
        parser.add_argument(
            '--years',
            type=int,
            default=1,
            help='生成過去N年的報表，預設為1年'
        )
        
        parser.add_argument(
            '--force',
            action='store_true',
            help='強制重新生成已結算的報表'
        )
    
    def handle(self, *args, **options):
        now = timezone.now()
        
        # 解析參數
        year = options['year'] or now.year
        years_count = options['years']
        force = options['force']
        
        self.stdout.write(f"開始生成年報表...")
        self.stdout.write(f"起始年份：{year}")
        self.stdout.write(f"生成年數：{years_count}年")
        
        total_reports = 0
        
        for i in range(years_count):
            current_year = year - i
            
            self.stdout.write(f"\n處理 {current_year} 年的年報表...")
            
            # 生成用戶年報表
            count = AnnualSalesReport.generate_all_reports(current_year)
            total_reports += count
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"{current_year}年: 生成 {count} 筆用戶報表"
                )
            )
            
            # 生成年度營業總結
            summary = AnnualSalesSummary.generate_summary(current_year)
            
            if summary:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{current_year}年: "
                        f"總收入 ${summary.total_revenue:,}，"
                        f"訂單 {summary.total_orders} 筆，"
                        f"活躍用戶 {summary.active_users_count} 人"
                    )
                )
                
                # 顯示業績亮點
                if summary.highlights:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"📊 業績亮點："
                        )
                    )
                    if 'peak_month' in summary.highlights:
                        self.stdout.write(
                            f"• 最高月份：{summary.highlights['peak_month']}月 "
                            f"(${summary.highlights['peak_month_revenue']:,.0f})"
                        )
                    if 'top_user' in summary.highlights:
                        self.stdout.write(
                            f"• 最佳用戶：{summary.highlights['top_user']} "
                            f"(${summary.highlights['top_user_revenue']:,.0f})"
                        )
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\n🎉 年報表生成完成！共生成 {total_reports} 筆用戶報表"
            )
        )