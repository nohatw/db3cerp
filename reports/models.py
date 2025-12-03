
from django.db import models
from django.utils import timezone
from django.db.models import Sum, Count, Q
from accounts.models import CustomUser
from accounts.constant import AccountRole
from business.models import Order
from business.constant import OrderStatus
import logging

logger = logging.getLogger(__name__)

# 日營業收入報表
class DailySalesReport(models.Model):
    """
    營業收入日報表
    
    功能：
    1. 每日自動生成營業收入統計
    2. 記錄每個用戶角色的銷售數據
    3. 支援權限控制的數據查詢
    
    數據來源：Order 訂單表（已完成訂單）
    更新方式：訂單完成時即時更新 + 每日結算任務確保數據完整性
    """
    
    # 基本資訊
    report_date = models.DateField(
        verbose_name="報表日期",
        db_index=True
    )
    
    # 用戶資訊
    user = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='daily_sales_reports',
        verbose_name="用戶",
        db_index=True
    )
    
    # 銷售數據
    total_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        verbose_name="總收入"
    )
    
    total_orders = models.IntegerField(
        default=0,
        verbose_name="訂單數量"
    )
    
    total_products_sold = models.IntegerField(
        default=0,
        verbose_name="銷售產品數量"
    )
    
    # 產品類型統計（JSON格式存儲詳細數據）
    product_breakdown = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="產品類型明細",
        help_text="格式：{'esim': {'quantity': 10, 'revenue': 5000}, 'esimimg': {...}}"
    )
    
    # 訂單來源統計
    order_source_breakdown = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="訂單來源明細",
        help_text="格式：{'ERP': {'orders': 5, 'revenue': 3000}, 'SHOPEE': {...}}"
    )
    
    # 狀態追蹤
    is_finalized = models.BooleanField(
        default=False,
        verbose_name="是否已結算",
        help_text="每日結算後設為True，防止重複計算"
    )
    
    last_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="最後更新時間"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="建立時間"
    )
    
    class Meta:
        verbose_name = "營業收入日報表"
        verbose_name_plural = "營業收入日報表"
        ordering = ['-report_date', '-total_revenue']
        unique_together = ('report_date', 'user')  # 每個用戶每天只有一筆報表
        indexes = [
            models.Index(fields=['report_date', 'user']),
            models.Index(fields=['report_date', '-total_revenue']),
            models.Index(fields=['user', '-report_date']),
        ]
    
    def __str__(self):
        return f"{self.report_date} - {self.user.fullname} - ${self.total_revenue:,}"
    
    @classmethod
    def update_or_create_report(cls, user, report_date=None):
        """
        更新或建立用戶的日報表
        
        Args:
            user: CustomUser 實例
            report_date: 報表日期，預設為今天
            
        Returns:
            DailySalesReport 實例
        """
        from django.db import transaction
        if report_date is None:
            report_date = timezone.now().date()
        
        # 使用 select_for_update 加鎖
        with transaction.atomic():
            # 嘗試獲取現有報表並加鎖
            try:
                report = cls.objects.select_for_update().get(
                    user=user,
                    report_date=report_date
                )
            except cls.DoesNotExist:
                report = None

            # 查詢該用戶在指定日期的已完成訂單
            orders = Order.objects.filter(
                account=user,
                status=OrderStatus.PAID,
                created_at__date=report_date
            ).select_related('account').prefetch_related('order_products__variant__product')
            
            # 計算總收入
            total_revenue = sum(order.total_amount for order in orders)
            total_orders = orders.count()
            
            # 計算總銷售產品數量
            total_products_sold = sum(
                order.order_products.aggregate(
                    total=Sum('quantity')
                )['total'] or 0
                for order in orders
            )
            
            # 產品類型明細統計
            product_breakdown = {}
            for order in orders:
                for order_product in order.order_products.all():
                    variant = order_product.variant
                    if variant and variant.product:
                        product_type = variant.product_type
                        
                        if product_type not in product_breakdown:
                            product_breakdown[product_type] = {
                                'quantity': 0,
                                'revenue': 0
                            }
                        
                        product_breakdown[product_type]['quantity'] += order_product.quantity
                        product_breakdown[product_type]['revenue'] += float(order_product.amount)
            
            # 訂單來源統計
            order_source_breakdown = {}
            for order in orders:
                source = order.order_source or 'OTHER'
                
                if source not in order_source_breakdown:
                    order_source_breakdown[source] = {
                        'orders': 0,
                        'revenue': 0
                    }
                
                order_source_breakdown[source]['orders'] += 1
                order_source_breakdown[source]['revenue'] += float(order.total_amount)
            
            # 更新或建立報表
            report, created = cls.objects.update_or_create(
                user=user,
                report_date=report_date,
                defaults={
                    'total_revenue': total_revenue,
                    'total_orders': total_orders,
                    'total_products_sold': total_products_sold,
                    'product_breakdown': product_breakdown,
                    'order_source_breakdown': order_source_breakdown,
                }
            )
            
            action = "建立" if created else "更新"
            logger.info(
                f"✅ {action}日報表：{report_date} - {user.fullname} - "
                f"收入：${total_revenue:,}，訂單：{total_orders}筆"
            )
            if report:
                # 更新現有報表
                report.total_revenue = total_revenue
                report.total_orders = total_orders
                total_products_sold = total_products_sold
                product_breakdown = product_breakdown
                order_source_breakdown = order_source_breakdown
                report.save()
                created = False
            else:
                # 建立新報表
                report = cls.objects.create(
                    user=user,
                    report_date=report_date,
                    total_revenue=total_revenue,
                    total_orders=total_orders,
                    total_products_sold=total_products_sold,
                    product_breakdown=product_breakdown,
                    order_source_breakdown=order_source_breakdown,
                )
                created = True
            
            return report
    
    @classmethod
    def generate_all_reports(cls, report_date=None):
        """
        生成所有有訂單用戶的日報表
        
        Args:
            report_date: 報表日期，預設為今天
            
        Returns:
            生成的報表數量
        """
        if report_date is None:
            report_date = timezone.now().date()
        
        # 查詢該日期有完成訂單的所有用戶
        users_with_orders = CustomUser.objects.filter(
            orders__status=OrderStatus.PAID,
            orders__created_at__date=report_date
        ).distinct()
        
        count = 0
        for user in users_with_orders:
            cls.update_or_create_report(user, report_date)
            count += 1
        
        logger.info(f"✅ 生成 {report_date} 日報表完成，共 {count} 位用戶")
        return count
    
    @classmethod
    def get_ranking(cls, report_date=None, role=None, limit=10):
        """
        獲取業績排名
        
        Args:
            report_date: 報表日期，預設為今天
            role: 用戶角色篩選（AccountRole），None 表示所有角色
            limit: 返回前幾名，None 表示全部
            
        Returns:
            QuerySet: 排序後的日報表
        """
        if report_date is None:
            report_date = timezone.now().date()
        
        queryset = cls.objects.filter(
            report_date=report_date
        ).select_related('user')
        
        if role:
            queryset = queryset.filter(user__role=role)
        
        queryset = queryset.order_by('-total_revenue')
        
        if limit:
            queryset = queryset[:limit]
        
        return queryset
    
    @classmethod
    def get_accessible_reports(cls, user, report_date=None):
        """
        根據用戶權限獲取可查看的報表
        
        Args:
            user: CustomUser 實例
            report_date: 報表日期，預設為今天
            
        Returns:
            QuerySet: 可查看的報表
        """
        from accounts.utils import is_headquarter_admin, is_agent
        
        if report_date is None:
            report_date = timezone.now().date()
        
        queryset = cls.objects.filter(report_date=report_date)
        
        if is_headquarter_admin(user):
            # 總公司管理員：查看所有報表
            return queryset.select_related('user').order_by('-total_revenue')
        elif is_agent(user):
            # 代理商：查看自己和下線分銷商的報表
            return queryset.filter(
                Q(user=user) | Q(user__parent=user, user__role=AccountRole.DISTRIBUTOR)
            ).select_related('user').order_by('-total_revenue')
        else:
            # 其他用戶：只能查看自己的報表
            return queryset.filter(user=user).select_related('user')
    
    def get_rank(self):
        """
        獲取該報表在當天所有用戶中的排名
        
        Returns:
            int: 排名（從1開始）
        """
        higher_revenue_count = DailySalesReport.objects.filter(
            report_date=self.report_date,
            total_revenue__gt=self.total_revenue
        ).count()
        
        return higher_revenue_count + 1
    
    def get_role_rank(self):
        """
        獲取該報表在同角色用戶中的排名
        
        Returns:
            int: 排名（從1開始）
        """
        higher_revenue_count = DailySalesReport.objects.filter(
            report_date=self.report_date,
            user__role=self.user.role,
            total_revenue__gt=self.total_revenue
        ).count()
        
        return higher_revenue_count + 1

# 每日營業總結表
class DailySalesSummary(models.Model):
    """
    每日營業總結表
    
    功能：
    1. 記錄每日整體營業數據
    2. 按用戶角色統計總收入
    3. 提供快速的總覽數據查詢
    
    更新方式：每日結算時自動生成
    """
    
    report_date = models.DateField(
        unique=True,
        verbose_name="報表日期",
        db_index=True
    )
    
    # 總體統計
    total_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        verbose_name="總收入"
    )
    
    total_orders = models.IntegerField(
        default=0,
        verbose_name="總訂單數"
    )
    
    total_products_sold = models.IntegerField(
        default=0,
        verbose_name="總銷售產品數"
    )
    
    # 按角色統計
    revenue_by_role = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="按角色統計收入",
        help_text="格式：{'AGENT': 50000, 'DISTRIBUTOR': 30000, ...}"
    )
    
    # 熱門產品類型
    top_product_types = models.JSONField(
        default=list,
        blank=True,
        verbose_name="熱門產品類型",
        help_text="格式：[{'type': 'esim', 'quantity': 100, 'revenue': 50000}, ...]"
    )
    
    # 狀態
    is_finalized = models.BooleanField(
        default=False,
        verbose_name="是否已結算"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="建立時間"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新時間"
    )
    
    class Meta:
        verbose_name = "每日營業總結"
        verbose_name_plural = "每日營業總結"
        ordering = ['-report_date']
    
    def __str__(self):
        return f"{self.report_date} - 總收入：${self.total_revenue:,}"
    
    @classmethod
    def generate_summary(cls, report_date=None):
        """
        生成每日營業總結
        
        Args:
            report_date: 報表日期，預設為今天
            
        Returns:
            DailySalesSummary 實例
        """
        if report_date is None:
            report_date = timezone.now().date()
        
        # 從 DailySalesReport 彙總數據
        daily_reports = DailySalesReport.objects.filter(report_date=report_date)
        
        # 總體統計
        total_revenue = daily_reports.aggregate(
            total=Sum('total_revenue')
        )['total'] or 0
        
        total_orders = daily_reports.aggregate(
            total=Sum('total_orders')
        )['total'] or 0
        
        total_products_sold = daily_reports.aggregate(
            total=Sum('total_products_sold')
        )['total'] or 0
        
        # 按角色統計
        revenue_by_role = {}
        for role_choice in AccountRole.choices:
            role = role_choice[0]
            role_revenue = daily_reports.filter(
                user__role=role
            ).aggregate(total=Sum('total_revenue'))['total'] or 0
            
            if role_revenue > 0:
                revenue_by_role[role] = float(role_revenue)
        
        # 彙總產品類型統計
        product_type_stats = {}
        for report in daily_reports:
            for product_type, data in report.product_breakdown.items():
                if product_type not in product_type_stats:
                    product_type_stats[product_type] = {
                        'quantity': 0,
                        'revenue': 0
                    }
                product_type_stats[product_type]['quantity'] += data['quantity']
                product_type_stats[product_type]['revenue'] += data['revenue']
        
        # 轉換為列表並排序
        top_product_types = [
            {
                'type': ptype,
                'quantity': data['quantity'],
                'revenue': data['revenue']
            }
            for ptype, data in product_type_stats.items()
        ]
        top_product_types.sort(key=lambda x: x['revenue'], reverse=True)
        
        # 更新或建立總結
        summary, created = cls.objects.update_or_create(
            report_date=report_date,
            defaults={
                'total_revenue': total_revenue,
                'total_orders': total_orders,
                'total_products_sold': total_products_sold,
                'revenue_by_role': revenue_by_role,
                'top_product_types': top_product_types,
            }
        )
        
        action = "建立" if created else "更新"
        logger.info(
            f"✅ {action}每日營業總結：{report_date} - "
            f"總收入：${total_revenue:,}，訂單：{total_orders}筆"
        )
        
        return summary

# 營業收入月報表   
class MonthlySalesReport(models.Model):
    """
    營業收入月報表
    
    功能：
    1. 每月彙總用戶的銷售數據
    2. 提供月度業績排名
    3. 支援同比、環比分析
    
    數據來源：DailySalesReport 日報表
    更新方式：每日更新當月數據 + 月底結算
    """
    
    # 基本資訊
    report_year = models.IntegerField(
        verbose_name="報表年份",
        db_index=True
    )
    
    report_month = models.IntegerField(
        verbose_name="報表月份",
        db_index=True
    )
    
    # 用戶資訊
    user = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='monthly_sales_reports',
        verbose_name="用戶",
        db_index=True
    )
    
    # 銷售數據
    total_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        verbose_name="總收入"
    )
    
    total_orders = models.IntegerField(
        default=0,
        verbose_name="訂單數量"
    )
    
    total_products_sold = models.IntegerField(
        default=0,
        verbose_name="銷售產品數量"
    )
    
    # 日均數據
    avg_daily_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="日均收入"
    )
    
    avg_daily_orders = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="日均訂單數"
    )
    
    # 活躍天數
    active_days = models.IntegerField(
        default=0,
        verbose_name="活躍天數",
        help_text="有訂單的天數"
    )
    
    # 產品類型統計
    product_breakdown = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="產品類型明細",
        help_text="格式：{'esim': {'quantity': 300, 'revenue': 150000}, ...}"
    )
    
    # 訂單來源統計
    order_source_breakdown = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="訂單來源明細",
        help_text="格式：{'ERP': {'orders': 50, 'revenue': 30000}, ...}"
    )
    
    # 每日明細（用於趨勢圖）
    daily_details = models.JSONField(
        default=list,
        blank=True,
        verbose_name="每日明細",
        help_text="格式：[{'date': '2025-12-01', 'revenue': 5000, 'orders': 10}, ...]"
    )
    
    # 同比數據（去年同月）
    yoy_revenue_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="同比收入增長率(%)",
        help_text="與去年同月相比的增長率"
    )
    
    yoy_order_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="同比訂單增長率(%)"
    )
    
    # 環比數據（上個月）
    mom_revenue_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="環比收入增長率(%)",
        help_text="與上月相比的增長率"
    )
    
    mom_order_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="環比訂單增長率(%)"
    )
    
    # 狀態追蹤
    is_finalized = models.BooleanField(
        default=False,
        verbose_name="是否已結算",
        help_text="月底結算後設為True"
    )
    
    last_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="最後更新時間"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="建立時間"
    )
    
    class Meta:
        verbose_name = "營業收入月報表"
        verbose_name_plural = "營業收入月報表"
        ordering = ['-report_year', '-report_month', '-total_revenue']
        unique_together = ('report_year', 'report_month', 'user')
        indexes = [
            models.Index(fields=['report_year', 'report_month', 'user']),
            models.Index(fields=['report_year', 'report_month', '-total_revenue']),
            models.Index(fields=['user', '-report_year', '-report_month']),
        ]
    
    def __str__(self):
        return f"{self.report_year}-{self.report_month:02d} - {self.user.fullname} - ${self.total_revenue:,}"
    
    @classmethod
    def update_or_create_report(cls, user, year=None, month=None):
        """
        更新或建立用戶的月報表
        
        Args:
            user: CustomUser 實例
            year: 報表年份，預設為當前年份
            month: 報表月份，預設為當前月份
            
        Returns:
            MonthlySalesReport 實例
        """
        if year is None or month is None:
            now = timezone.now()
            year = year or now.year
            month = month or now.month
        
        # 查詢該月的所有日報表
        daily_reports = DailySalesReport.objects.filter(
            user=user,
            report_date__year=year,
            report_date__month=month
        ).order_by('report_date')
        
        if not daily_reports.exists():
            logger.warning(f"⚠️ 用戶 {user.fullname} 在 {year}-{month:02d} 沒有日報表數據")
            return None
        
        # 彙總數據
        total_revenue = daily_reports.aggregate(
            total=Sum('total_revenue')
        )['total'] or 0
        
        total_orders = daily_reports.aggregate(
            total=Sum('total_orders')
        )['total'] or 0
        
        total_products_sold = daily_reports.aggregate(
            total=Sum('total_products_sold')
        )['total'] or 0
        
        # 活躍天數
        active_days = daily_reports.count()
        
        # 計算日均數據
        avg_daily_revenue = total_revenue / active_days if active_days > 0 else 0
        avg_daily_orders = total_orders / active_days if active_days > 0 else 0
        
        # 彙總產品類型統計
        product_breakdown = {}
        for report in daily_reports:
            for product_type, data in report.product_breakdown.items():
                if product_type not in product_breakdown:
                    product_breakdown[product_type] = {
                        'quantity': 0,
                        'revenue': 0
                    }
                product_breakdown[product_type]['quantity'] += data['quantity']
                product_breakdown[product_type]['revenue'] += data['revenue']
        
        # 彙總訂單來源統計
        order_source_breakdown = {}
        for report in daily_reports:
            for source, data in report.order_source_breakdown.items():
                if source not in order_source_breakdown:
                    order_source_breakdown[source] = {
                        'orders': 0,
                        'revenue': 0
                    }
                order_source_breakdown[source]['orders'] += data['orders']
                order_source_breakdown[source]['revenue'] += data['revenue']
        
        # 每日明細
        daily_details = [
            {
                'date': report.report_date.strftime('%Y-%m-%d'),
                'revenue': float(report.total_revenue),
                'orders': report.total_orders,
                'products': report.total_products_sold
            }
            for report in daily_reports
        ]
        
        # 計算同比增長率（去年同月）
        last_year_report = cls.objects.filter(
            user=user,
            report_year=year - 1,
            report_month=month
        ).first()
        
        yoy_revenue_growth = None
        yoy_order_growth = None
        if last_year_report and last_year_report.total_revenue > 0:
            yoy_revenue_growth = (
                (total_revenue - last_year_report.total_revenue) / 
                last_year_report.total_revenue * 100
            )
        if last_year_report and last_year_report.total_orders > 0:
            yoy_order_growth = (
                (total_orders - last_year_report.total_orders) / 
                last_year_report.total_orders * 100
            )
        
        # 計算環比增長率（上個月）
        last_month_year = year if month > 1 else year - 1
        last_month = month - 1 if month > 1 else 12
        
        last_month_report = cls.objects.filter(
            user=user,
            report_year=last_month_year,
            report_month=last_month
        ).first()
        
        mom_revenue_growth = None
        mom_order_growth = None
        if last_month_report and last_month_report.total_revenue > 0:
            mom_revenue_growth = (
                (total_revenue - last_month_report.total_revenue) / 
                last_month_report.total_revenue * 100
            )
        if last_month_report and last_month_report.total_orders > 0:
            mom_order_growth = (
                (total_orders - last_month_report.total_orders) / 
                last_month_report.total_orders * 100
            )
        
        # 更新或建立報表
        report, created = cls.objects.update_or_create(
            user=user,
            report_year=year,
            report_month=month,
            defaults={
                'total_revenue': total_revenue,
                'total_orders': total_orders,
                'total_products_sold': total_products_sold,
                'avg_daily_revenue': avg_daily_revenue,
                'avg_daily_orders': avg_daily_orders,
                'active_days': active_days,
                'product_breakdown': product_breakdown,
                'order_source_breakdown': order_source_breakdown,
                'daily_details': daily_details,
                'yoy_revenue_growth': yoy_revenue_growth,
                'yoy_order_growth': yoy_order_growth,
                'mom_revenue_growth': mom_revenue_growth,
                'mom_order_growth': mom_order_growth,
            }
        )
        
        action = "建立" if created else "更新"
        logger.info(
            f"✅ {action}月報表：{year}-{month:02d} - {user.fullname} - "
            f"收入：${total_revenue:,}，訂單：{total_orders}筆"
        )
        
        return report
    
    @classmethod
    def generate_all_reports(cls, year=None, month=None):
        """
        生成所有有日報表的用戶的月報表
        
        Args:
            year: 報表年份，預設為當前年份
            month: 報表月份，預設為當前月份
            
        Returns:
            生成的報表數量
        """
        if year is None or month is None:
            now = timezone.now()
            year = year or now.year
            month = month or now.month
        
        # 查詢該月有日報表的所有用戶
        users_with_reports = CustomUser.objects.filter(
            daily_sales_reports__report_date__year=year,
            daily_sales_reports__report_date__month=month
        ).distinct()
        
        count = 0
        for user in users_with_reports:
            report = cls.update_or_create_report(user, year, month)
            if report:
                count += 1
        
        logger.info(f"✅ 生成 {year}-{month:02d} 月報表完成，共 {count} 位用戶")
        return count
    
    @classmethod
    def get_ranking(cls, year=None, month=None, role=None, limit=10):
        """
        獲取月度業績排名
        
        Args:
            year: 報表年份，預設為當前年份
            month: 報表月份，預設為當前月份
            role: 用戶角色篩選（AccountRole），None 表示所有角色
            limit: 返回前幾名，None 表示全部
            
        Returns:
            QuerySet: 排序後的月報表
        """
        if year is None or month is None:
            now = timezone.now()
            year = year or now.year
            month = month or now.month
        
        queryset = cls.objects.filter(
            report_year=year,
            report_month=month
        ).select_related('user')
        
        if role:
            queryset = queryset.filter(user__role=role)
        
        queryset = queryset.order_by('-total_revenue')
        
        if limit:
            queryset = queryset[:limit]
        
        return queryset
    
    @classmethod
    def get_accessible_reports(cls, user, year=None, month=None):
        """
        根據用戶權限獲取可查看的月報表
        
        Args:
            user: CustomUser 實例
            year: 報表年份，預設為當前年份
            month: 報表月份，預設為當前月份
            
        Returns:
            QuerySet: 可查看的報表
        """
        from accounts.utils import is_headquarter_admin, is_agent
        
        if year is None or month is None:
            now = timezone.now()
            year = year or now.year
            month = month or now.month
        
        queryset = cls.objects.filter(
            report_year=year,
            report_month=month
        )
        
        if is_headquarter_admin(user):
            # 總公司管理員：查看所有報表
            return queryset.select_related('user').order_by('-total_revenue')
        elif is_agent(user):
            # 代理商：查看自己和下線分銷商的報表
            return queryset.filter(
                Q(user=user) | Q(user__parent=user, user__role=AccountRole.DISTRIBUTOR)
            ).select_related('user').order_by('-total_revenue')
        else:
            # 其他用戶：只能查看自己的報表
            return queryset.filter(user=user).select_related('user')
    
    def get_rank(self):
        """
        獲取該報表在當月所有用戶中的排名
        
        Returns:
            int: 排名（從1開始）
        """
        higher_revenue_count = MonthlySalesReport.objects.filter(
            report_year=self.report_year,
            report_month=self.report_month,
            total_revenue__gt=self.total_revenue
        ).count()
        
        return higher_revenue_count + 1
    
    def get_role_rank(self):
        """
        獲取該報表在同角色用戶中的排名
        
        Returns:
            int: 排名（從1開始）
        """
        higher_revenue_count = MonthlySalesReport.objects.filter(
            report_year=self.report_year,
            report_month=self.report_month,
            user__role=self.user.role,
            total_revenue__gt=self.total_revenue
        ).count()
        
        return higher_revenue_count + 1
    
    @property
    def report_period(self):
        """返回報表期間的顯示字串"""
        return f"{self.report_year}年{self.report_month}月"

# 每月營業總結表
class MonthlySalesSummary(models.Model):
    """
    每月營業總結表
    
    功能：
    1. 記錄每月整體營業數據
    2. 按用戶角色統計總收入
    3. 提供月度趨勢分析
    
    更新方式：每日更新當月數據 + 月底結算
    """
    
    report_year = models.IntegerField(
        verbose_name="報表年份",
        db_index=True
    )
    
    report_month = models.IntegerField(
        verbose_name="報表月份",
        db_index=True
    )
    
    # 總體統計
    total_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        verbose_name="總收入"
    )
    
    total_orders = models.IntegerField(
        default=0,
        verbose_name="總訂單數"
    )
    
    total_products_sold = models.IntegerField(
        default=0,
        verbose_name="總銷售產品數"
    )
    
    # 日均數據
    avg_daily_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="日均收入"
    )
    
    # 活躍用戶數
    active_users_count = models.IntegerField(
        default=0,
        verbose_name="活躍用戶數",
        help_text="本月有訂單的用戶數"
    )
    
    # 按角色統計
    revenue_by_role = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="按角色統計收入",
        help_text="格式：{'AGENT': 500000, 'DISTRIBUTOR': 300000, ...}"
    )
    
    # 熱門產品類型
    top_product_types = models.JSONField(
        default=list,
        blank=True,
        verbose_name="熱門產品類型",
        help_text="格式：[{'type': 'esim', 'quantity': 1000, 'revenue': 500000}, ...]"
    )
    
    # 每日趨勢
    daily_trend = models.JSONField(
        default=list,
        blank=True,
        verbose_name="每日收入趨勢",
        help_text="格式：[{'date': '2025-12-01', 'revenue': 50000}, ...]"
    )
    
    # 同比數據
    yoy_revenue_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="同比收入增長率(%)"
    )
    
    # 環比數據
    mom_revenue_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="環比收入增長率(%)"
    )
    
    # 狀態
    is_finalized = models.BooleanField(
        default=False,
        verbose_name="是否已結算"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="建立時間"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新時間"
    )
    
    class Meta:
        verbose_name = "每月營業總結"
        verbose_name_plural = "每月營業總結"
        ordering = ['-report_year', '-report_month']
        unique_together = ('report_year', 'report_month')
        indexes = [
            models.Index(fields=['report_year', 'report_month']),
        ]
    
    def __str__(self):
        return f"{self.report_year}-{self.report_month:02d} - 總收入：${self.total_revenue:,}"
    
    @classmethod
    def generate_summary(cls, year=None, month=None):
        """
        生成每月營業總結
        
        Args:
            year: 報表年份，預設為當前年份
            month: 報表月份，預設為當前月份
            
        Returns:
            MonthlySalesSummary 實例
        """
        if year is None or month is None:
            now = timezone.now()
            year = year or now.year
            month = month or now.month
        
        # 從 MonthlySalesReport 彙總數據
        monthly_reports = MonthlySalesReport.objects.filter(
            report_year=year,
            report_month=month
        )
        
        if not monthly_reports.exists():
            logger.warning(f"⚠️ {year}-{month:02d} 沒有月報表數據")
            return None
        
        # 總體統計
        total_revenue = monthly_reports.aggregate(
            total=Sum('total_revenue')
        )['total'] or 0
        
        total_orders = monthly_reports.aggregate(
            total=Sum('total_orders')
        )['total'] or 0
        
        total_products_sold = monthly_reports.aggregate(
            total=Sum('total_products_sold')
        )['total'] or 0
        
        # 活躍用戶數
        active_users_count = monthly_reports.count()
        
        # 計算日均收入（從日報表統計）
        from datetime import date
        import calendar
        
        # 獲取該月的天數
        _, days_in_month = calendar.monthrange(year, month)
        
        # 查詢該月的日報表總和
        daily_summaries = DailySalesSummary.objects.filter(
            report_date__year=year,
            report_date__month=month
        )
        
        if daily_summaries.exists():
            avg_daily_revenue = daily_summaries.aggregate(
                avg=models.Avg('total_revenue')
            )['avg'] or 0
        else:
            avg_daily_revenue = 0
        
        # 按角色統計
        revenue_by_role = {}
        for role_choice in AccountRole.choices:
            role = role_choice[0]
            role_revenue = monthly_reports.filter(
                user__role=role
            ).aggregate(total=Sum('total_revenue'))['total'] or 0
            
            if role_revenue > 0:
                revenue_by_role[role] = float(role_revenue)
        
        # 彙總產品類型統計
        product_type_stats = {}
        for report in monthly_reports:
            for product_type, data in report.product_breakdown.items():
                if product_type not in product_type_stats:
                    product_type_stats[product_type] = {
                        'quantity': 0,
                        'revenue': 0
                    }
                product_type_stats[product_type]['quantity'] += data['quantity']
                product_type_stats[product_type]['revenue'] += data['revenue']
        
        # 轉換為列表並排序
        top_product_types = [
            {
                'type': ptype,
                'quantity': data['quantity'],
                'revenue': data['revenue']
            }
            for ptype, data in product_type_stats.items()
        ]
        top_product_types.sort(key=lambda x: x['revenue'], reverse=True)
        
        # 每日趨勢（從日報表彙總）
        daily_trend = []
        for summary in daily_summaries.order_by('report_date'):
            daily_trend.append({
                'date': summary.report_date.strftime('%Y-%m-%d'),
                'revenue': float(summary.total_revenue),
                'orders': summary.total_orders
            })
        
        # 計算同比增長率
        last_year_summary = cls.objects.filter(
            report_year=year - 1,
            report_month=month
        ).first()
        
        yoy_revenue_growth = None
        if last_year_summary and last_year_summary.total_revenue > 0:
            yoy_revenue_growth = (
                (total_revenue - last_year_summary.total_revenue) / 
                last_year_summary.total_revenue * 100
            )
        
        # 計算環比增長率
        last_month_year = year if month > 1 else year - 1
        last_month = month - 1 if month > 1 else 12
        
        last_month_summary = cls.objects.filter(
            report_year=last_month_year,
            report_month=last_month
        ).first()
        
        mom_revenue_growth = None
        if last_month_summary and last_month_summary.total_revenue > 0:
            mom_revenue_growth = (
                (total_revenue - last_month_summary.total_revenue) / 
                last_month_summary.total_revenue * 100
            )
        
        # 更新或建立總結
        summary, created = cls.objects.update_or_create(
            report_year=year,
            report_month=month,
            defaults={
                'total_revenue': total_revenue,
                'total_orders': total_orders,
                'total_products_sold': total_products_sold,
                'avg_daily_revenue': avg_daily_revenue,
                'active_users_count': active_users_count,
                'revenue_by_role': revenue_by_role,
                'top_product_types': top_product_types,
                'daily_trend': daily_trend,
                'yoy_revenue_growth': yoy_revenue_growth,
                'mom_revenue_growth': mom_revenue_growth,
            }
        )
        
        action = "建立" if created else "更新"
        logger.info(
            f"{action}每月營業總結：{year}-{month:02d} - "
            f"總收入：${total_revenue:,}，訂單：{total_orders}筆"
        )
        
        return summary
    
    @property
    def report_period(self):
        """返回報表期間的顯示字串"""
        return f"{self.report_year}年{self.report_month}月"

# 營業收入年報表
class AnnualSalesReport(models.Model):
    """
    營業收入年報表
    
    功能：
    1. 每年彙總用戶的銷售數據
    2. 提供年度業績排名
    3. 支援多年度比較分析
    
    數據來源：MonthlySalesReport 月報表
    更新方式：每月更新當年數據 + 年底結算
    """
    
    # 基本資訊
    report_year = models.IntegerField(
        verbose_name="報表年份",
        db_index=True
    )
    
    # 用戶資訊
    user = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='annual_sales_reports',
        verbose_name="用戶",
        db_index=True
    )
    
    # 銷售數據
    total_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        verbose_name="總收入"
    )
    
    total_orders = models.IntegerField(
        default=0,
        verbose_name="訂單數量"
    )
    
    total_products_sold = models.IntegerField(
        default=0,
        verbose_name="銷售產品數量"
    )
    
    # 月均數據
    avg_monthly_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="月均收入"
    )
    
    avg_monthly_orders = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="月均訂單數"
    )
    
    # 活躍月數
    active_months = models.IntegerField(
        default=0,
        verbose_name="活躍月數",
        help_text="有訂單的月數"
    )
    
    # 最高月份記錄
    peak_month = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="業績最高月份"
    )
    
    peak_month_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        null=True,
        blank=True,
        verbose_name="最高月份收入"
    )
    
    # 最低月份記錄（排除零收入）
    lowest_month = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="業績最低月份"
    )
    
    lowest_month_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        null=True,
        blank=True,
        verbose_name="最低月份收入"
    )
    
    # 產品類型統計
    product_breakdown = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="產品類型明細",
        help_text="格式：{'esim': {'quantity': 3600, 'revenue': 1800000}, ...}"
    )
    
    # 訂單來源統計
    order_source_breakdown = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="訂單來源明細",
        help_text="格式：{'ERP': {'orders': 600, 'revenue': 360000}, ...}"
    )
    
    # 每月明細（用於趨勢圖）
    monthly_details = models.JSONField(
        default=list,
        blank=True,
        verbose_name="每月明細",
        help_text="格式：[{'month': 1, 'revenue': 50000, 'orders': 100}, ...]"
    )
    
    # 季度統計
    quarterly_stats = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="季度統計",
        help_text="格式：{'Q1': {'revenue': 150000, 'orders': 300}, ...}"
    )
    
    # 同比數據（去年）
    yoy_revenue_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="同比收入增長率(%)",
        help_text="與去年相比的增長率"
    )
    
    yoy_order_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="同比訂單增長率(%)"
    )
    
    # 增長趨勢分析
    revenue_trend = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name="收入趨勢",
        help_text="GROWING/STABLE/DECLINING"
    )
    
    # 狀態追蹤
    is_finalized = models.BooleanField(
        default=False,
        verbose_name="是否已結算",
        help_text="年底結算後設為True"
    )
    
    last_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="最後更新時間"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="建立時間"
    )
    
    class Meta:
        verbose_name = "營業收入年報表"
        verbose_name_plural = "營業收入年報表"
        ordering = ['-report_year', '-total_revenue']
        unique_together = ('report_year', 'user')
        indexes = [
            models.Index(fields=['report_year', 'user']),
            models.Index(fields=['report_year', '-total_revenue']),
            models.Index(fields=['user', '-report_year']),
        ]
    
    def __str__(self):
        return f"{self.report_year}年 - {self.user.fullname} - ${self.total_revenue:,}"
    
    @classmethod
    def update_or_create_report(cls, user, year=None):
        """
        更新或建立用戶的年報表
        
        Args:
            user: CustomUser 實例
            year: 報表年份，預設為當前年份
            
        Returns:
            AnnualSalesReport 實例
        """
        if year is None:
            year = timezone.now().year
        
        # 查詢該年的所有月報表
        monthly_reports = MonthlySalesReport.objects.filter(
            user=user,
            report_year=year
        ).order_by('report_month')
        
        if not monthly_reports.exists():
            logger.warning(f"⚠️ 用戶 {user.fullname} 在 {year} 年沒有月報表數據")
            return None
        
        # 彙總數據
        total_revenue = monthly_reports.aggregate(
            total=Sum('total_revenue')
        )['total'] or 0
        
        total_orders = monthly_reports.aggregate(
            total=Sum('total_orders')
        )['total'] or 0
        
        total_products_sold = monthly_reports.aggregate(
            total=Sum('total_products_sold')
        )['total'] or 0
        
        # 活躍月數
        active_months = monthly_reports.count()
        
        # 計算月均數據
        avg_monthly_revenue = total_revenue / active_months if active_months > 0 else 0
        avg_monthly_orders = total_orders / active_months if active_months > 0 else 0
        
        # 找出業績最高和最低的月份
        peak_report = monthly_reports.order_by('-total_revenue').first()
        peak_month = peak_report.report_month if peak_report else None
        peak_month_revenue = peak_report.total_revenue if peak_report else None
        
        # 最低月份（排除零收入）
        lowest_report = monthly_reports.filter(
            total_revenue__gt=0
        ).order_by('total_revenue').first()
        lowest_month = lowest_report.report_month if lowest_report else None
        lowest_month_revenue = lowest_report.total_revenue if lowest_report else None
        
        # 彙總產品類型統計
        product_breakdown = {}
        for report in monthly_reports:
            for product_type, data in report.product_breakdown.items():
                if product_type not in product_breakdown:
                    product_breakdown[product_type] = {
                        'quantity': 0,
                        'revenue': 0
                    }
                product_breakdown[product_type]['quantity'] += data['quantity']
                product_breakdown[product_type]['revenue'] += data['revenue']
        
        # 彙總訂單來源統計
        order_source_breakdown = {}
        for report in monthly_reports:
            for source, data in report.order_source_breakdown.items():
                if source not in order_source_breakdown:
                    order_source_breakdown[source] = {
                        'orders': 0,
                        'revenue': 0
                    }
                order_source_breakdown[source]['orders'] += data['orders']
                order_source_breakdown[source]['revenue'] += data['revenue']
        
        # 每月明細
        monthly_details = [
            {
                'month': report.report_month,
                'revenue': float(report.total_revenue),
                'orders': report.total_orders,
                'products': report.total_products_sold
            }
            for report in monthly_reports
        ]
        
        # 季度統計
        quarterly_stats = {
            'Q1': {'revenue': 0, 'orders': 0, 'months': []},
            'Q2': {'revenue': 0, 'orders': 0, 'months': []},
            'Q3': {'revenue': 0, 'orders': 0, 'months': []},
            'Q4': {'revenue': 0, 'orders': 0, 'months': []}
        }
        
        for report in monthly_reports:
            month = report.report_month
            if month in [1, 2, 3]:
                quarter = 'Q1'
            elif month in [4, 5, 6]:
                quarter = 'Q2'
            elif month in [7, 8, 9]:
                quarter = 'Q3'
            else:
                quarter = 'Q4'
            
            quarterly_stats[quarter]['revenue'] += float(report.total_revenue)
            quarterly_stats[quarter]['orders'] += report.total_orders
            quarterly_stats[quarter]['months'].append(month)
        
        # 計算同比增長率（去年）
        last_year_report = cls.objects.filter(
            user=user,
            report_year=year - 1
        ).first()
        
        yoy_revenue_growth = None
        yoy_order_growth = None
        if last_year_report and last_year_report.total_revenue > 0:
            yoy_revenue_growth = (
                (total_revenue - last_year_report.total_revenue) / 
                last_year_report.total_revenue * 100
            )
        if last_year_report and last_year_report.total_orders > 0:
            yoy_order_growth = (
                (total_orders - last_year_report.total_orders) / 
                last_year_report.total_orders * 100
            )
        
        # 分析收入趨勢
        revenue_trend = cls._analyze_revenue_trend(monthly_details)
        
        # 更新或建立報表
        report, created = cls.objects.update_or_create(
            user=user,
            report_year=year,
            defaults={
                'total_revenue': total_revenue,
                'total_orders': total_orders,
                'total_products_sold': total_products_sold,
                'avg_monthly_revenue': avg_monthly_revenue,
                'avg_monthly_orders': avg_monthly_orders,
                'active_months': active_months,
                'peak_month': peak_month,
                'peak_month_revenue': peak_month_revenue,
                'lowest_month': lowest_month,
                'lowest_month_revenue': lowest_month_revenue,
                'product_breakdown': product_breakdown,
                'order_source_breakdown': order_source_breakdown,
                'monthly_details': monthly_details,
                'quarterly_stats': quarterly_stats,
                'yoy_revenue_growth': yoy_revenue_growth,
                'yoy_order_growth': yoy_order_growth,
                'revenue_trend': revenue_trend,
            }
        )
        
        action = "建立" if created else "更新"
        logger.info(
            f"✅ {action}年報表：{year}年 - {user.fullname} - "
            f"收入：${total_revenue:,}，訂單：{total_orders}筆"
        )
        
        return report
    
    @staticmethod
    def _analyze_revenue_trend(monthly_details):
        """
        分析收入趨勢
        
        Args:
            monthly_details: 月度明細列表
            
        Returns:
            str: GROWING/STABLE/DECLINING
        """
        if len(monthly_details) < 3:
            return 'STABLE'
        
        # 計算前半年和後半年的平均收入
        mid_point = len(monthly_details) // 2
        first_half_avg = sum(
            m['revenue'] for m in monthly_details[:mid_point]
        ) / mid_point
        
        second_half_avg = sum(
            m['revenue'] for m in monthly_details[mid_point:]
        ) / (len(monthly_details) - mid_point)
        
        if first_half_avg == 0:
            return 'GROWING' if second_half_avg > 0 else 'STABLE'
        
        growth_rate = (second_half_avg - first_half_avg) / first_half_avg * 100
        
        if growth_rate > 10:
            return 'GROWING'
        elif growth_rate < -10:
            return 'DECLINING'
        else:
            return 'STABLE'
    
    @classmethod
    def generate_all_reports(cls, year=None):
        """
        生成所有有月報表的用戶的年報表
        
        Args:
            year: 報表年份，預設為當前年份
            
        Returns:
            生成的報表數量
        """
        if year is None:
            year = timezone.now().year
        
        # 查詢該年有月報表的所有用戶
        users_with_reports = CustomUser.objects.filter(
            monthly_sales_reports__report_year=year
        ).distinct()
        
        count = 0
        for user in users_with_reports:
            report = cls.update_or_create_report(user, year)
            if report:
                count += 1
        
        logger.info(f"✅ 生成 {year} 年報表完成，共 {count} 位用戶")
        return count
    
    @classmethod
    def get_ranking(cls, year=None, role=None, limit=10):
        """
        獲取年度業績排名
        
        Args:
            year: 報表年份，預設為當前年份
            role: 用戶角色篩選（AccountRole），None 表示所有角色
            limit: 返回前幾名，None 表示全部
            
        Returns:
            QuerySet: 排序後的年報表
        """
        if year is None:
            year = timezone.now().year
        
        queryset = cls.objects.filter(
            report_year=year
        ).select_related('user')
        
        if role:
            queryset = queryset.filter(user__role=role)
        
        queryset = queryset.order_by('-total_revenue')
        
        if limit:
            queryset = queryset[:limit]
        
        return queryset
    
    @classmethod
    def get_accessible_reports(cls, user, year=None):
        """
        根據用戶權限獲取可查看的年報表
        
        Args:
            user: CustomUser 實例
            year: 報表年份，預設為當前年份
            
        Returns:
            QuerySet: 可查看的報表
        """
        from accounts.utils import is_headquarter_admin, is_agent
        
        if year is None:
            year = timezone.now().year
        
        queryset = cls.objects.filter(report_year=year)
        
        if is_headquarter_admin(user):
            # 總公司管理員：查看所有報表
            return queryset.select_related('user').order_by('-total_revenue')
        elif is_agent(user):
            # 代理商：查看自己和下線分銷商的報表
            return queryset.filter(
                Q(user=user) | Q(user__parent=user, user__role=AccountRole.DISTRIBUTOR)
            ).select_related('user').order_by('-total_revenue')
        else:
            # 其他用戶：只能查看自己的報表
            return queryset.filter(user=user).select_related('user')
    
    @classmethod
    def get_multi_year_comparison(cls, user, years=5):
        """
        獲取多年比較數據
        
        Args:
            user: CustomUser 實例
            years: 比較年數，預設5年
            
        Returns:
            list: 年度比較數據列表
        """
        current_year = timezone.now().year
        comparison_data = []
        
        for i in range(years):
            year = current_year - i
            report = cls.objects.filter(
                user=user,
                report_year=year
            ).first()
            
            if report:
                comparison_data.append({
                    'year': year,
                    'revenue': float(report.total_revenue),
                    'orders': report.total_orders,
                    'products': report.total_products_sold,
                    'yoy_growth': float(report.yoy_revenue_growth) if report.yoy_revenue_growth else None,
                    'trend': report.revenue_trend
                })
            else:
                comparison_data.append({
                    'year': year,
                    'revenue': 0,
                    'orders': 0,
                    'products': 0,
                    'yoy_growth': None,
                    'trend': None
                })
        
        return comparison_data
    
    def get_rank(self):
        """
        獲取該報表在當年所有用戶中的排名
        
        Returns:
            int: 排名（從1開始）
        """
        higher_revenue_count = AnnualSalesReport.objects.filter(
            report_year=self.report_year,
            total_revenue__gt=self.total_revenue
        ).count()
        
        return higher_revenue_count + 1
    
    def get_role_rank(self):
        """
        獲取該報表在同角色用戶中的排名
        
        Returns:
            int: 排名（從1開始）
        """
        higher_revenue_count = AnnualSalesReport.objects.filter(
            report_year=self.report_year,
            user__role=self.user.role,
            total_revenue__gt=self.total_revenue
        ).count()
        
        return higher_revenue_count + 1
    
    @property
    def report_period(self):
        """返回報表期間的顯示字串"""
        return f"{self.report_year}年"
    
    @property
    def revenue_volatility(self):
        """
        計算收入波動性（標準差）
        
        Returns:
            float: 收入標準差
        """
        if not self.monthly_details or len(self.monthly_details) < 2:
            return 0
        
        revenues = [m['revenue'] for m in self.monthly_details]
        mean = sum(revenues) / len(revenues)
        variance = sum((r - mean) ** 2 for r in revenues) / len(revenues)
        
        return variance ** 0.5

# 每年營業總結表
class AnnualSalesSummary(models.Model):
    """
    每年營業總結表
    
    功能：
    1. 記錄每年整體營業數據
    2. 按用戶角色統計總收入
    3. 提供年度趨勢分析
    
    更新方式：每月更新當年數據 + 年底結算
    """
    
    report_year = models.IntegerField(
        unique=True,
        verbose_name="報表年份",
        db_index=True
    )
    
    # 總體統計
    total_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        verbose_name="總收入"
    )
    
    total_orders = models.IntegerField(
        default=0,
        verbose_name="總訂單數"
    )
    
    total_products_sold = models.IntegerField(
        default=0,
        verbose_name="總銷售產品數"
    )
    
    # 月均數據
    avg_monthly_revenue = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="月均收入"
    )
    
    # 活躍用戶數
    active_users_count = models.IntegerField(
        default=0,
        verbose_name="活躍用戶數",
        help_text="本年有訂單的用戶數"
    )
    
    # 新增用戶數
    new_users_count = models.IntegerField(
        default=0,
        verbose_name="新增用戶數",
        help_text="本年首次下單的用戶數"
    )
    
    # 按角色統計
    revenue_by_role = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="按角色統計收入",
        help_text="格式：{'AGENT': 6000000, 'DISTRIBUTOR': 3600000, ...}"
    )
    
    # 熱門產品類型
    top_product_types = models.JSONField(
        default=list,
        blank=True,
        verbose_name="熱門產品類型",
        help_text="格式：[{'type': 'esim', 'quantity': 12000, 'revenue': 6000000}, ...]"
    )
    
    # 每月趨勢
    monthly_trend = models.JSONField(
        default=list,
        blank=True,
        verbose_name="每月收入趨勢",
        help_text="格式：[{'month': 1, 'revenue': 500000}, ...]"
    )
    
    # 季度比較
    quarterly_comparison = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="季度比較",
        help_text="格式：{'Q1': 1500000, 'Q2': 1800000, ...}"
    )
    
    # 同比數據
    yoy_revenue_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="同比收入增長率(%)"
    )
    
    yoy_user_growth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="同比用戶增長率(%)"
    )
    
    # 業績亮點
    highlights = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="業績亮點",
        help_text="格式：{'peak_month': 12, 'peak_revenue': 800000, 'top_user': 'xxx', ...}"
    )
    
    # 狀態
    is_finalized = models.BooleanField(
        default=False,
        verbose_name="是否已結算"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="建立時間"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新時間"
    )
    
    class Meta:
        verbose_name = "每年營業總結"
        verbose_name_plural = "每年營業總結"
        ordering = ['-report_year']
    
    def __str__(self):
        return f"{self.report_year}年 - 總收入：${self.total_revenue:,}"
    
    @classmethod
    def generate_summary(cls, year=None):
        """
        生成每年營業總結
        
        Args:
            year: 報表年份，預設為當前年份
            
        Returns:
            AnnualSalesSummary 實例
        """
        if year is None:
            year = timezone.now().year
        
        # 從 AnnualSalesReport 彙總數據
        annual_reports = AnnualSalesReport.objects.filter(report_year=year)
        
        if not annual_reports.exists():
            logger.warning(f"⚠️ {year} 年沒有年報表數據")
            return None
        
        # 總體統計
        total_revenue = annual_reports.aggregate(
            total=Sum('total_revenue')
        )['total'] or 0
        
        total_orders = annual_reports.aggregate(
            total=Sum('total_orders')
        )['total'] or 0
        
        total_products_sold = annual_reports.aggregate(
            total=Sum('total_products_sold')
        )['total'] or 0
        
        # 活躍用戶數
        active_users_count = annual_reports.count()
        
        # 新增用戶數（本年首次有年報表的用戶）
        previous_year_users = set(
            AnnualSalesReport.objects.filter(
                report_year=year - 1
            ).values_list('user_id', flat=True)
        )
        current_year_users = set(
            annual_reports.values_list('user_id', flat=True)
        )
        new_users_count = len(current_year_users - previous_year_users)
        
        # 計算月均收入（從月報表統計）
        from datetime import date
        monthly_summaries = MonthlySalesSummary.objects.filter(
            report_year=year
        )
        
        if monthly_summaries.exists():
            avg_monthly_revenue = monthly_summaries.aggregate(
                avg=models.Avg('total_revenue')
            )['avg'] or 0
        else:
            avg_monthly_revenue = 0
        
        # 按角色統計
        revenue_by_role = {}
        for role_choice in AccountRole.choices:
            role = role_choice[0]
            role_revenue = annual_reports.filter(
                user__role=role
            ).aggregate(total=Sum('total_revenue'))['total'] or 0
            
            if role_revenue > 0:
                revenue_by_role[role] = float(role_revenue)
        
        # 彙總產品類型統計
        product_type_stats = {}
        for report in annual_reports:
            for product_type, data in report.product_breakdown.items():
                if product_type not in product_type_stats:
                    product_type_stats[product_type] = {
                        'quantity': 0,
                        'revenue': 0
                    }
                product_type_stats[product_type]['quantity'] += data['quantity']
                product_type_stats[product_type]['revenue'] += data['revenue']
        
        # 轉換為列表並排序
        top_product_types = [
            {
                'type': ptype,
                'quantity': data['quantity'],
                'revenue': data['revenue']
            }
            for ptype, data in product_type_stats.items()
        ]
        top_product_types.sort(key=lambda x: x['revenue'], reverse=True)
        
        # 每月趨勢（從月總結彙總）
        monthly_trend = []
        for summary in monthly_summaries.order_by('report_month'):
            monthly_trend.append({
                'month': summary.report_month,
                'revenue': float(summary.total_revenue),
                'orders': summary.total_orders
            })
        
        # 季度比較
        quarterly_comparison = {
            'Q1': 0, 'Q2': 0, 'Q3': 0, 'Q4': 0
        }
        
        for summary in monthly_summaries:
            month = summary.report_month
            revenue = float(summary.total_revenue)
            
            if month in [1, 2, 3]:
                quarterly_comparison['Q1'] += revenue
            elif month in [4, 5, 6]:
                quarterly_comparison['Q2'] += revenue
            elif month in [7, 8, 9]:
                quarterly_comparison['Q3'] += revenue
            else:
                quarterly_comparison['Q4'] += revenue
        
        # 計算同比增長率
        last_year_summary = cls.objects.filter(
            report_year=year - 1
        ).first()
        
        yoy_revenue_growth = None
        yoy_user_growth = None
        if last_year_summary:
            if last_year_summary.total_revenue > 0:
                yoy_revenue_growth = (
                    (total_revenue - last_year_summary.total_revenue) / 
                    last_year_summary.total_revenue * 100
                )
            if last_year_summary.active_users_count > 0:
                yoy_user_growth = (
                    (active_users_count - last_year_summary.active_users_count) / 
                    last_year_summary.active_users_count * 100
                )
        
        # 業績亮點
        highlights = {}
        
        # 找出業績最高的月份
        if monthly_summaries.exists():
            peak_month_summary = monthly_summaries.order_by('-total_revenue').first()
            highlights['peak_month'] = peak_month_summary.report_month
            highlights['peak_month_revenue'] = float(peak_month_summary.total_revenue)
        
        # 找出業績最高的用戶
        top_user_report = annual_reports.order_by('-total_revenue').first()
        if top_user_report:
            highlights['top_user'] = top_user_report.user.fullname
            highlights['top_user_revenue'] = float(top_user_report.total_revenue)
        
        # 找出業績最高的季度
        if quarterly_comparison:
            peak_quarter = max(quarterly_comparison, key=quarterly_comparison.get)
            highlights['peak_quarter'] = peak_quarter
            highlights['peak_quarter_revenue'] = quarterly_comparison[peak_quarter]
        
        # 更新或建立總結
        summary, created = cls.objects.update_or_create(
            report_year=year,
            defaults={
                'total_revenue': total_revenue,
                'total_orders': total_orders,
                'total_products_sold': total_products_sold,
                'avg_monthly_revenue': avg_monthly_revenue,
                'active_users_count': active_users_count,
                'new_users_count': new_users_count,
                'revenue_by_role': revenue_by_role,
                'top_product_types': top_product_types,
                'monthly_trend': monthly_trend,
                'quarterly_comparison': quarterly_comparison,
                'yoy_revenue_growth': yoy_revenue_growth,
                'yoy_user_growth': yoy_user_growth,
                'highlights': highlights,
            }
        )
        
        action = "建立" if created else "更新"
        logger.info(
            f"✅ {action}每年營業總結：{year}年 - "
            f"總收入：${total_revenue:,}，訂單：{total_orders}筆"
        )
        
        return summary
    
    @property
    def report_period(self):
        """返回報表期間的顯示字串"""
        return f"{self.report_year}年"
    
    @property
    def best_quarter(self):
        """返回業績最好的季度"""
        if not self.quarterly_comparison:
            return None
        return max(self.quarterly_comparison, key=self.quarterly_comparison.get)

