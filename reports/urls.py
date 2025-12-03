from django.urls import path, include
from reports import views
from reports.views import (
    DailySalesReportListView, 
    DailySalesReportDetailView,
    DailySalesDashboardView,
    MonthlySalesReportListView,
    MonthlySalesReportDetailView,
    MonthlySalesDashboardView
)

app_name = 'reports'

urlpatterns = [
    # 日報表
    path('daily/', views.DailySalesReportListView.as_view(), name='daily_list'),
    path('daily/<int:pk>/', views.DailySalesReportDetailView.as_view(), name='daily_detail'),
    path('daily/dashboard/', views.DailySalesDashboardView.as_view(), name='daily_dashboard'),

    # 月報表
    path('monthly/', views.MonthlySalesReportListView.as_view(), name='monthly_list'),
    path('monthly/<int:pk>/', views.MonthlySalesReportDetailView.as_view(), name='monthly_detail'),
    path('monthly/dashboard/', views.MonthlySalesDashboardView.as_view(), name='monthly_dashboard'),
]