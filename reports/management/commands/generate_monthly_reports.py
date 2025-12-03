from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime
from reports.models import MonthlySalesReport, MonthlySalesSummary
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '生成營業收入月報表'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            help='指定年份，預設為當前年份'
        )
        
        parser.add_argument(
            '--month',
            type=int,
            help='指定月份（1-12），預設為當前月份'
        )
        
        parser.add_argument(
            '--months',
            type=int,
            default=1,
            help='生成過去N個月的報表，預設為1個月'
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
        month = options['month'] or now.month
        months_count = options['months']
        force = options['force']
        
        self.stdout.write(f"開始生成月報表...")
        self.stdout.write(f"起始月份：{year}-{month:02d}")
        self.stdout.write(f"生成月數：{months_count}個月")
        
        total_reports = 0
        
        for i in range(months_count):
            # 計算當前處理的年月
            current_month = month - i
            current_year = year
            
            while current_month < 1:
                current_month += 12
                current_year -= 1
            
            self.stdout.write(f"\n處理 {current_year}-{current_month:02d} 的月報表...")
            
            # 生成用戶月報表
            count = MonthlySalesReport.generate_all_reports(
                current_year, 
                current_month
            )
            total_reports += count
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"{current_year}-{current_month:02d}: "
                    f"生成 {count} 筆用戶報表"
                )
            )
            
            # 生成月度營業總結
            summary = MonthlySalesSummary.generate_summary(
                current_year, 
                current_month
            )
            
            if summary:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✅ {current_year}-{current_month:02d}: "
                        f"總收入 ${summary.total_revenue:,}，"
                        f"訂單 {summary.total_orders} 筆"
                    )
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\n🎉 月報表生成完成！共生成 {total_reports} 筆用戶報表"
            )
        )