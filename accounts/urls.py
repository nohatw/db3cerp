from django.urls import path
from accounts import views

app_name = 'accounts'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # 帳號列表和詳情
    path('account-list/', views.AccountListView.as_view(), name='account_list'),
    path('account/<int:pk>/', views.AccountDetailView.as_view(), name='account_detail'),
    
    # 選擇客戶和取消選擇（注意路徑格式）
    path('select-client/<int:account_id>/', views.select_client_for_order, name='select_client'),
    path('cancel-client-selection/', views.cancel_client_selection, name='cancel_client_selection'),
]