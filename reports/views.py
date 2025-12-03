from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, DetailView
from django.contrib import messages
from django.urls import reverse_lazy
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import datetime, timedelta
import logging

from reports.models import (
    DailySalesReport, 
    DailySalesSummary,
    MonthlySalesReport,
    AnnualSalesReport
)
from accounts.utils import is_headquarter_admin, is_agent
from accounts.constant import AccountRole

logger = logging.getLogger(__name__)


# ==================== 日報表 Views ====================
class DailySalesReportListView(LoginRequiredMixin, ListView):
    """
    日報表列表視圖
    
    權限：
    - 總公司管理員：查看所有用戶的日報表
    - 代理商：查看自己和下線分銷商的日報表
    - 其他用戶：只能查看自己的日報表
    
    功能：
    - 日期篩選
    - 用戶角色篩選
    - 用戶搜尋
    - 業績排名顯示
    """
    model = DailySalesReport
    template_name = 'reports/daily_sales_report_list.html'
    context_object_name = 'reports'
    paginate_by = 20
    
    def get_queryset(self):
        user = self.request.user
        
        # 獲取日期參數
        date_str = self.request.GET.get('date')
        if date_str:
            try:
                report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                report_date = timezone.now().date()
        else:
            report_date = timezone.now().date()
        
        # 根據權限獲取可查看的報表
        queryset = DailySalesReport.get_accessible_reports(user, report_date)
        
        # 用戶角色篩選
        role = self.request.GET.get('role')
        if role and is_headquarter_admin(user):
            queryset = queryset.filter(user__role=role)
        
        # 用戶搜尋
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(user__fullname__icontains=search_query) |
                Q(user__username__icontains=search_query) |
                Q(user__company__icontains=search_query)
            )
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # 當前日期
        date_str = self.request.GET.get('date')
        if date_str:
            try:
                report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                report_date = timezone.now().date()
        else:
            report_date = timezone.now().date()
        
        context['report_date'] = report_date
        context['today'] = timezone.now().date()
        
        # 獲取當日營業總結
        daily_summary = DailySalesSummary.objects.filter(
            report_date=report_date
        ).first()
        context['daily_summary'] = daily_summary
        
        # 統計資料
        reports = self.get_queryset()
        context['total_users'] = reports.count()
        context['total_revenue'] = reports.aggregate(
            total=Sum('total_revenue')
        )['total'] or 0
        context['total_orders'] = reports.aggregate(
            total=Sum('total_orders')
        )['total'] or 0
        
        # 篩選條件
        context['selected_role'] = self.request.GET.get('role', '')
        context['search_query'] = self.request.GET.get('q', '')
        
        # 角色選項（僅總公司管理員可見）
        if is_headquarter_admin(user):
            context['role_choices'] = AccountRole.choices
        
        # 權限資訊
        context['is_headquarter_admin'] = is_headquarter_admin(user)
        context['is_agent'] = is_agent(user)
        
        # 日期導航
        context['prev_date'] = report_date - timedelta(days=1)
        context['next_date'] = report_date + timedelta(days=1)
        context['can_next'] = report_date < timezone.now().date()
        
        return context


class DailySalesReportDetailView(LoginRequiredMixin, DetailView):
    """
    日報表詳情視圖
    
    權限：
    - 總公司管理員：可查看所有用戶
    - 代理商：可查看自己和下線分銷商
    - 其他用戶：只能查看自己
    
    功能：
    - 顯示詳細銷售數據
    - 產品類型分析
    - 訂單來源分析
    - 排名資訊
    """
    model = DailySalesReport
    template_name = 'reports/daily_sales_report_detail.html'
    context_object_name = 'report'
    
    def get_queryset(self):
        user = self.request.user
        queryset = DailySalesReport.objects.select_related('user').all()
        
        if is_headquarter_admin(user):
            return queryset
        elif is_agent(user):
            return queryset.filter(
                Q(user=user) | Q(user__parent=user, user__role=AccountRole.DISTRIBUTOR)
            )
        else:
            return queryset.filter(user=user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        report = self.object
        user = self.request.user
        
        # 獲取當日營業總結
        daily_summary = DailySalesSummary.objects.filter(
            report_date=report.report_date
        ).first()
        context['daily_summary'] = daily_summary
        
        # 排名資訊
        context['overall_rank'] = report.get_rank()
        context['role_rank'] = report.get_role_rank()
        
        # 同角色用戶總數
        context['role_total_users'] = DailySalesReport.objects.filter(
            report_date=report.report_date,
            user__role=report.user.role
        ).count()
        
        # 產品類型統計（轉換為列表）
        product_breakdown = []
        for product_type, data in report.product_breakdown.items():
            product_breakdown.append({
                'type': product_type,
                'quantity': data['quantity'],
                'revenue': data['revenue'],
                'percentage': (data['revenue'] / float(report.total_revenue) * 100) if report.total_revenue > 0 else 0
            })
        product_breakdown.sort(key=lambda x: x['revenue'], reverse=True)
        context['product_breakdown'] = product_breakdown

        # 訂單來源統計（轉換為列表）
        order_source_breakdown = []
        for source, data in report.order_source_breakdown.items():
            order_source_breakdown.append({
                'source': source,
                'orders': data['orders'],
                'revenue': data['revenue'],
                'percentage': (data['revenue'] / float(report.total_revenue) * 100) if report.total_revenue > 0 else 0
            })
        order_source_breakdown.sort(key=lambda x: x['revenue'], reverse=True)
        context['order_source_breakdown'] = order_source_breakdown
        
        # 平均訂單金額
        context['avg_order_amount'] = (
            report.total_revenue / report.total_orders 
            if report.total_orders > 0 else 0
        )
        
        # 權限資訊
        context['is_headquarter_admin'] = is_headquarter_admin(user)
        
        # 日期導航
        context['prev_date'] = report.report_date - timedelta(days=1)
        context['next_date'] = report.report_date + timedelta(days=1)
        context['can_next'] = report.report_date < timezone.now().date()
        
        # 查詢前後日期的報表
        prev_report = DailySalesReport.objects.filter(
            user=report.user,
            report_date=context['prev_date']
        ).first()
        next_report = DailySalesReport.objects.filter(
            user=report.user,
            report_date=context['next_date']
        ).first() if context['can_next'] else None
        
        context['has_prev_report'] = prev_report is not None
        context['has_next_report'] = next_report is not None
        
        if prev_report:
            context['prev_report_id'] = prev_report.id
        if next_report:
            context['next_report_id'] = next_report.id
        
        return context


class DailySalesDashboardView(LoginRequiredMixin, ListView):
    """
    日報表儀表板視圖
    
    功能：
    - 顯示今日營業總覽
    - Top 10 業績排名
    - 各角色業績統計
    - 趨勢圖表數據
    """
    model = DailySalesReport
    template_name = 'reports/daily_sales_dashboard.html'
    context_object_name = 'top_reports'
    
    def get_queryset(self):
        user = self.request.user
        
        # 獲取日期參數
        date_str = self.request.GET.get('date')
        if date_str:
            try:
                report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                report_date = timezone.now().date()
        else:
            report_date = timezone.now().date()
        
        # 獲取 Top 10
        queryset = DailySalesReport.get_accessible_reports(user, report_date)
        return queryset[:10]
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # 當前日期
        date_str = self.request.GET.get('date')
        if date_str:
            try:
                report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                report_date = timezone.now().date()
        else:
            report_date = timezone.now().date()
        
        context['report_date'] = report_date
        context['today'] = timezone.now().date()
        
        # 獲取當日營業總結
        daily_summary = DailySalesSummary.objects.filter(
            report_date=report_date
        ).first()
        context['daily_summary'] = daily_summary
        
        # 按角色統計
        if daily_summary:
            role_stats = []
            for role, revenue in daily_summary.revenue_by_role.items():
                role_display = dict(AccountRole.choices).get(role, role)
                role_stats.append({
                    'role': role,
                    'role_display': role_display,
                    'revenue': revenue,
                    'percentage': (revenue / float(daily_summary.total_revenue) * 100) 
                                if daily_summary.total_revenue > 0 else 0
                })
            role_stats.sort(key=lambda x: x['revenue'], reverse=True)
            context['role_stats'] = role_stats
        
        # 產品類型統計
        if daily_summary:
            context['product_types'] = daily_summary.top_product_types
        
        # 近7日趨勢
        trend_data = []
        for i in range(6, -1, -1):
            date = report_date - timedelta(days=i)
            summary = DailySalesSummary.objects.filter(report_date=date).first()
            trend_data.append({
                'date': date.strftime('%m/%d'),
                'revenue': float(summary.total_revenue) if summary else 0,
                'orders': summary.total_orders if summary else 0
            })
        context['trend_data'] = trend_data
        
        # 用戶自己的報表
        my_report = DailySalesReport.objects.filter(
            user=user,
            report_date=report_date
        ).first()
        context['my_report'] = my_report
        
        if my_report:
            context['my_rank'] = my_report.get_rank()
            context['my_role_rank'] = my_report.get_role_rank()
        
        # 權限資訊
        context['is_headquarter_admin'] = is_headquarter_admin(user)
        
        # 日期導航
        context['prev_date'] = report_date - timedelta(days=1)
        context['next_date'] = report_date + timedelta(days=1)
        context['can_next'] = report_date < timezone.now().date()
        
        return context


# ==================== 月報表 Views ====================
class MonthlySalesReportListView(LoginRequiredMixin, ListView):
    """
    月報表列表視圖
    
    權限：
    - 總公司管理員：查看所有用戶的月報表
    - 代理商：查看自己和下線分銷商的月報表
    - 其他用戶：只能查看自己的月報表
    
    功能：
    - 年月篩選
    - 用戶角色篩選
    - 用戶搜尋
    - 業績排名顯示
    """
    model = MonthlySalesReport
    template_name = 'reports/monthly_sales_report_list.html'
    context_object_name = 'reports'
    paginate_by = 20
    
    def get_queryset(self):
        user = self.request.user
        
        # 獲取年月參數
        year_str = self.request.GET.get('year')
        month_str = self.request.GET.get('month')
        
        if year_str and month_str:
            try:
                year = int(year_str)
                month = int(month_str)
            except ValueError:
                now = timezone.now()
                year = now.year
                month = now.month
        else:
            now = timezone.now()
            year = now.year
            month = now.month
        
        # 根據權限獲取可查看的報表
        queryset = MonthlySalesReport.get_accessible_reports(user, year, month)
        
        # 用戶角色篩選
        role = self.request.GET.get('role')
        if role and is_headquarter_admin(user):
            queryset = queryset.filter(user__role=role)
        
        # 用戶搜尋
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(user__fullname__icontains=search_query) |
                Q(user__username__icontains=search_query) |
                Q(user__company__icontains=search_query)
            )
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # 當前年月
        year_str = self.request.GET.get('year')
        month_str = self.request.GET.get('month')
        
        if year_str and month_str:
            try:
                year = int(year_str)
                month = int(month_str)
            except ValueError:
                now = timezone.now()
                year = now.year
                month = now.month
        else:
            now = timezone.now()
            year = now.year
            month = now.month
        
        context['report_year'] = year
        context['report_month'] = month
        context['current_year'] = timezone.now().year
        context['current_month'] = timezone.now().month
        
        # 獲取當月營業總結
        from reports.models import MonthlySalesSummary
        monthly_summary = MonthlySalesSummary.objects.filter(
            report_year=year,
            report_month=month
        ).first()
        context['monthly_summary'] = monthly_summary
        
        # 統計資料
        reports = self.get_queryset()
        context['total_users'] = reports.count()
        context['total_revenue'] = reports.aggregate(
            total=Sum('total_revenue')
        )['total'] or 0
        context['total_orders'] = reports.aggregate(
            total=Sum('total_orders')
        )['total'] or 0
        
        # 篩選條件
        context['selected_role'] = self.request.GET.get('role', '')
        context['search_query'] = self.request.GET.get('q', '')
        
        # 角色選項（僅總公司管理員可見）
        if is_headquarter_admin(user):
            context['role_choices'] = AccountRole.choices
        
        # 權限資訊
        context['is_headquarter_admin'] = is_headquarter_admin(user)
        context['is_agent'] = is_agent(user)
        
        # 月份導航
        prev_month = month - 1
        prev_year = year
        if prev_month < 1:
            prev_month = 12
            prev_year = year - 1
        
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year = year + 1
        
        context['prev_year'] = prev_year
        context['prev_month'] = prev_month
        context['next_year'] = next_year
        context['next_month'] = next_month
        
        # 判斷是否可以查看下個月
        now = timezone.now()
        context['can_next'] = (next_year < now.year) or (next_year == now.year and next_month <= now.month)
        
        return context


class MonthlySalesReportDetailView(LoginRequiredMixin, DetailView):
    """
    月報表詳情視圖
    
    權限：
    - 總公司管理員：可查看所有用戶
    - 代理商：可查看自己和下線分銷商
    - 其他用戶：只能查看自己
    
    功能：
    - 顯示詳細月度銷售數據
    - 每日明細分析
    - 產品類型分析
    - 訂單來源分析
    - 同比環比數據
    - 排名資訊
    """
    model = MonthlySalesReport
    template_name = 'reports/monthly_sales_report_detail.html'
    context_object_name = 'report'
    
    def get_queryset(self):
        user = self.request.user
        queryset = MonthlySalesReport.objects.select_related('user').all()
        
        if is_headquarter_admin(user):
            return queryset
        elif is_agent(user):
            return queryset.filter(
                Q(user=user) | Q(user__parent=user, user__role=AccountRole.DISTRIBUTOR)
            )
        else:
            return queryset.filter(user=user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        report = self.object
        user = self.request.user
        
        # 獲取當月營業總結
        from reports.models import MonthlySalesSummary
        monthly_summary = MonthlySalesSummary.objects.filter(
            report_year=report.report_year,
            report_month=report.report_month
        ).first()
        context['monthly_summary'] = monthly_summary
        
        # 排名資訊
        context['overall_rank'] = report.get_rank()
        context['role_rank'] = report.get_role_rank()
        
        # 同角色用戶總數
        context['role_total_users'] = MonthlySalesReport.objects.filter(
            report_year=report.report_year,
            report_month=report.report_month,
            user__role=report.user.role
        ).count()
        
        # 產品類型統計（轉換為列表）
        product_breakdown = []
        for product_type, data in report.product_breakdown.items():
            product_breakdown.append({
                'type': product_type,
                'quantity': data['quantity'],
                'revenue': data['revenue'],
                'percentage': (data['revenue'] / float(report.total_revenue) * 100) if report.total_revenue > 0 else 0
            })
        product_breakdown.sort(key=lambda x: x['revenue'], reverse=True)
        context['product_breakdown'] = product_breakdown

        # 訂單來源統計（轉換為列表）
        order_source_breakdown = []
        for source, data in report.order_source_breakdown.items():
            order_source_breakdown.append({
                'source': source,
                'orders': data['orders'],
                'revenue': data['revenue'],
                'percentage': (data['revenue'] / float(report.total_revenue) * 100) if report.total_revenue > 0 else 0
            })
        order_source_breakdown.sort(key=lambda x: x['revenue'], reverse=True)
        context['order_source_breakdown'] = order_source_breakdown
        
        # 每日明細（轉換為列表並排序）
        daily_details = sorted(report.daily_details, key=lambda x: x['date'])
        context['daily_details'] = daily_details
        
        # 平均訂單金額
        context['avg_order_amount'] = (
            report.total_revenue / report.total_orders 
            if report.total_orders > 0 else 0
        )
        
        # 同比數據（去年同月）
        prev_year_report = MonthlySalesReport.objects.filter(
            user=report.user,
            report_year=report.report_year - 1,
            report_month=report.report_month
        ).first()
        
        if prev_year_report:
            context['prev_year_report'] = prev_year_report
            context['yoy_revenue_change'] = report.total_revenue - prev_year_report.total_revenue
            context['yoy_orders_change'] = report.total_orders - prev_year_report.total_orders
        
        # 環比數據（上個月）
        prev_month = report.report_month - 1
        prev_month_year = report.report_year
        if prev_month < 1:
            prev_month = 12
            prev_month_year = report.report_year - 1
        
        prev_month_report = MonthlySalesReport.objects.filter(
            user=report.user,
            report_year=prev_month_year,
            report_month=prev_month
        ).first()
        
        if prev_month_report:
            context['prev_month_report'] = prev_month_report
            context['mom_revenue_change'] = report.total_revenue - prev_month_report.total_revenue
            context['mom_orders_change'] = report.total_orders - prev_month_report.total_orders
        
        # 權限資訊
        context['is_headquarter_admin'] = is_headquarter_admin(user)
        
        # 月份導航
        prev_nav_month = report.report_month - 1
        prev_nav_year = report.report_year
        if prev_nav_month < 1:
            prev_nav_month = 12
            prev_nav_year = report.report_year - 1
        
        next_nav_month = report.report_month + 1
        next_nav_year = report.report_year
        if next_nav_month > 12:
            next_nav_month = 1
            next_nav_year = report.report_year + 1
        
        context['prev_year'] = prev_nav_year
        context['prev_month'] = prev_nav_month
        context['next_year'] = next_nav_year
        context['next_month'] = next_nav_month
        
        # 判斷是否可以查看下個月
        now = timezone.now()
        context['can_next'] = (next_nav_year < now.year) or (next_nav_year == now.year and next_nav_month <= now.month)
        
        # 查詢前後月份的報表
        prev_report = MonthlySalesReport.objects.filter(
            user=report.user,
            report_year=prev_nav_year,
            report_month=prev_nav_month
        ).first()
        
        next_report = None
        if context['can_next']:
            next_report = MonthlySalesReport.objects.filter(
                user=report.user,
                report_year=next_nav_year,
                report_month=next_nav_month
            ).first()
        
        context['has_prev_report'] = prev_report is not None
        context['has_next_report'] = next_report is not None
        
        if prev_report:
            context['prev_report_id'] = prev_report.id
        if next_report:
            context['next_report_id'] = next_report.id
        
        return context


class MonthlySalesDashboardView(LoginRequiredMixin, ListView):
    """
    月報表儀表板視圖
    
    功能：
    - 顯示當月營業總覽
    - Top 10 業績排名
    - 各角色業績統計
    - 季度對比
    - 12個月趨勢圖表數據
    """
    model = MonthlySalesReport
    template_name = 'reports/monthly_sales_dashboard.html'
    context_object_name = 'top_reports'
    
    def get_queryset(self):
        user = self.request.user
        
        # 獲取年月參數
        year_str = self.request.GET.get('year')
        month_str = self.request.GET.get('month')
        
        if year_str and month_str:
            try:
                year = int(year_str)
                month = int(month_str)
            except ValueError:
                now = timezone.now()
                year = now.year
                month = now.month
        else:
            now = timezone.now()
            year = now.year
            month = now.month
        
        # 獲取 Top 10
        queryset = MonthlySalesReport.get_accessible_reports(user, year, month)
        return queryset[:10]
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # 當前年月
        year_str = self.request.GET.get('year')
        month_str = self.request.GET.get('month')
        
        if year_str and month_str:
            try:
                year = int(year_str)
                month = int(month_str)
            except ValueError:
                now = timezone.now()
                year = now.year
                month = now.month
        else:
            now = timezone.now()
            year = now.year
            month = now.month
        
        context['report_year'] = year
        context['report_month'] = month
        context['current_year'] = timezone.now().year
        context['current_month'] = timezone.now().month
        
        # 獲取當月營業總結
        from reports.models import MonthlySalesSummary
        monthly_summary = MonthlySalesSummary.objects.filter(
            report_year=year,
            report_month=month
        ).first()
        context['monthly_summary'] = monthly_summary
        
        # 按角色統計
        if monthly_summary and monthly_summary.revenue_by_role:
            role_stats = []
            for role, revenue in monthly_summary.revenue_by_role.items():
                role_display = dict(AccountRole.choices).get(role, role)
                role_stats.append({
                    'role': role,
                    'role_display': role_display,
                    'revenue': revenue,
                    'percentage': (revenue / float(monthly_summary.total_revenue) * 100) 
                                if monthly_summary.total_revenue > 0 else 0
                })
            role_stats.sort(key=lambda x: x['revenue'], reverse=True)
            context['role_stats'] = role_stats
        
        # 季度對比數據
        if monthly_summary and monthly_summary.quarterly_comparison:
            context['quarterly_comparison'] = monthly_summary.quarterly_comparison
        
        # 近12個月趨勢
        trend_data = []
        for i in range(11, -1, -1):
            # 計算月份
            target_month = month - i
            target_year = year
            while target_month < 1:
                target_month += 12
                target_year -= 1
            
            summary = MonthlySalesSummary.objects.filter(
                report_year=target_year,
                report_month=target_month
            ).first()
            
            trend_data.append({
                'year': target_year,
                'month': target_month,
                'label': f"{target_year}/{target_month:02d}",
                'revenue': float(summary.total_revenue) if summary else 0,
                'orders': summary.total_orders if summary else 0
            })
        context['trend_data'] = trend_data
        
        # 用戶自己的報表
        my_report = MonthlySalesReport.objects.filter(
            user=user,
            report_year=year,
            report_month=month
        ).first()
        context['my_report'] = my_report
        
        if my_report:
            context['my_rank'] = my_report.get_rank()
            context['my_role_rank'] = my_report.get_role_rank()
        
        # 權限資訊
        context['is_headquarter_admin'] = is_headquarter_admin(user)
        
        # 月份導航
        prev_month = month - 1
        prev_year = year
        if prev_month < 1:
            prev_month = 12
            prev_year = year - 1
        
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year = year + 1
        
        context['prev_year'] = prev_year
        context['prev_month'] = prev_month
        context['next_year'] = next_year
        context['next_month'] = next_month
        
        # 判斷是否可以查看下個月
        now = timezone.now()
        context['can_next'] = (next_year < now.year) or (next_year == now.year and next_month <= now.month)
        
        return context