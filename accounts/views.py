from django.shortcuts import render, redirect
from django.utils import timezone
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import CreateView, UpdateView, DetailView, DeleteView
from django.views.generic.list import ListView
from django.db.models import Q, Sum, OuterRef, Subquery
from accounts.models import CustomUser
from accounts.constant import AccountStatus, AccountRole
from accounts.utils import is_headquarter_admin, is_agent, get_accessible_accounts
from business.models import AccountTopUP
# Create your views here.

def dashboard(request):
    template_name = 'pages/dashboard.html'
    return render(request, template_name)

# 選擇客戶（為客戶下單）
@login_required
@require_POST
def select_client_for_order(request, account_id):
    """
    總公司管理員選擇要為其下單的客戶
    """
    from accounts.utils import can_order_for_others
    from business.models import AccountTopUP
    import logging
    import json
    
    logger = logging.getLogger(__name__)
    user = request.user
    
    logger.info(f'收到選擇客戶請求：user={user.username}, account_id={account_id}')
    
    # 權限檢查：只有總公司管理員可以為他人下單
    if not can_order_for_others(user):
        logger.warning(f'用戶 {user.username} 嘗試為他人下單但沒有權限')
        return JsonResponse({
            'success': False,
            'error': '您沒有權限為他人下單'
        }, status=403)
    
    try:
        # 獲取目標客戶
        target_account = CustomUser.objects.get(
            id=account_id,
            status=AccountStatus.ACTIVE
        )
        
        logger.info(f'找到目標客戶：{target_account.username} (ID: {target_account.id})')
        
        # 獲取客戶餘額
        try:
            topup = AccountTopUP.objects.get(account=target_account)
            balance = float(topup.balance)
            logger.info(f'客戶餘額：{balance}')
        except AccountTopUP.DoesNotExist:
            balance = 0
            logger.info('客戶沒有儲值記錄，餘額為 0')
        
        # ✅ 將選中的客戶資訊儲存到 session
        request.session['order_for_account_id'] = target_account.id
        request.session['order_for_account_name'] = target_account.fullname or target_account.username
        request.session['order_for_account_role'] = target_account.get_role_display()
        request.session['order_for_account_balance'] = balance
        
        # ✅ 強制保存 session
        request.session.modified = True
        
        # ✅ 驗證 session 是否設定成功
        saved_id = request.session.get('order_for_account_id')
        logger.info(f'Session 設定完成：order_for_account_id={saved_id}')
        
        if saved_id != target_account.id:
            logger.error(f'Session 設定失敗！期望 {target_account.id}，實際 {saved_id}')
            return JsonResponse({
                'success': False,
                'error': 'Session 設定失敗，請重試'
            }, status=500)
        
        return JsonResponse({
            'success': True,
            'account_id': target_account.id,
            'account_name': target_account.fullname or target_account.username,
            'account_role': target_account.get_role_display(),
            'balance': balance,
            'message': f'已選擇為「{target_account.fullname or target_account.username}」下單'
        })
        
    except CustomUser.DoesNotExist:
        logger.error(f'客戶 ID {account_id} 不存在或已停用')
        return JsonResponse({
            'success': False,
            'error': '客戶不存在或已停用'
        }, status=404)
    except Exception as e:
        logger.error(f'選擇客戶失敗：{str(e)}', exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'選擇客戶失敗：{str(e)}'
        }, status=500)


# 取消選擇客戶（恢復為自己下單）
@login_required
@require_POST
def cancel_client_selection(request):
    """
    取消選擇的客戶，恢復為自己下單
    """
    # 清除 session 中的選中客戶資訊
    request.session.pop('order_for_account_id', None)
    request.session.pop('order_for_account_name', None)
    request.session.pop('order_for_account_role', None)
    request.session.pop('order_for_account_balance', None)
    
    messages.info(request, '已取消為他人下單，將為您自己下單')
    
    return JsonResponse({
        'success': True,
        'message': '已取消為他人下單'
    })


# All accounts list 所有帳戶列表
class AccountListView(LoginRequiredMixin, ListView):
    model = CustomUser
    template_name = 'account/account_list.html'
    context_object_name = 'accounts'
    paginate_by = 10  # 每頁顯示 10 個用戶

    def get_queryset(self):
        user = self.request.user
        
        # 根據用戶權限獲取可查看的帳號
        if is_headquarter_admin(user):
            # 總公司管理員：查看所有帳號
            queryset = CustomUser.objects.all()
        elif is_agent(user):
            # 代理商：查看自己和下級分銷商
            queryset = CustomUser.objects.filter(
                Q(id=user.id) | Q(parent=user, role=AccountRole.DISTRIBUTOR)
            )
        else:
            # 其他用戶：只能查看自己
            queryset = CustomUser.objects.filter(id=user.id)
        
        # 使用 Subquery 獲取每個帳號的儲值餘額
        topup_balance = AccountTopUP.objects.filter(
            account=OuterRef('pk')
        ).values('balance')
        
        queryset = queryset.annotate(
            topup_balance=Subquery(topup_balance)
        )
        
        # 搜尋功能
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(username__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(fullname__icontains=search_query) |
                Q(company__icontains=search_query) |
                Q(mobilephone__icontains=search_query)
            )

        # 狀態過濾
        selected_status = self.request.GET.get('status')
        if selected_status:
            queryset = queryset.filter(status=selected_status)
        
        # 角色過濾
        selected_role = self.request.GET.get('role')
        if selected_role:
            queryset = queryset.filter(role=selected_role)
        
        return queryset.order_by('-date_joined')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 傳遞過濾選項
        context['account_statuses'] = AccountStatus.choices
        context['account_roles'] = AccountRole.choices
        context['selected_status'] = self.request.GET.get('status', '')
        context['selected_role'] = self.request.GET.get('role', '')
        context['search_query'] = self.request.GET.get('q', '')
        
        # 統計資料
        user = self.request.user
        if is_headquarter_admin(user):
            context['total_accounts'] = CustomUser.objects.count()
            context['total_agents'] = CustomUser.objects.filter(role=AccountRole.AGENT).count()
            context['total_distributors'] = CustomUser.objects.filter(role=AccountRole.DISTRIBUTOR).count()
            # 計算所有帳號的儲值總額
            context['total_balance'] = AccountTopUP.objects.aggregate(
                total=Sum('balance')
            )['total'] or 0
        elif is_agent(user):
            accessible_accounts = CustomUser.objects.filter(
                Q(id=user.id) | Q(parent=user, role=AccountRole.DISTRIBUTOR)
            )
            context['total_accounts'] = accessible_accounts.count()
            context['total_agents'] = 1  # 只有自己
            context['total_distributors'] = CustomUser.objects.filter(
                parent=user, role=AccountRole.DISTRIBUTOR
            ).count()
            # 計算可見帳號的儲值總額
            context['total_balance'] = AccountTopUP.objects.filter(
                account__in=accessible_accounts
            ).aggregate(total=Sum('balance'))['total'] or 0
        else:
            context['total_accounts'] = 1  # 只有自己
            context['total_agents'] = 0
            context['total_distributors'] = 0
            # 只計算自己的儲值
            try:
                topup = AccountTopUP.objects.get(account=user)
                context['total_balance'] = topup.balance
            except AccountTopUP.DoesNotExist:
                context['total_balance'] = 0
        
        return context

# Account detail view 用戶詳情
class AccountDetailView(LoginRequiredMixin, DetailView):
    model = CustomUser
    template_name = 'account/account_detail.html'
    context_object_name = 'account'

    def get_queryset(self):
        """
        限制用戶只能查看有權限的帳號詳情
        """
        user = self.request.user
        
        if is_headquarter_admin(user):
            # 總公司管理員：可以查看所有帳號
            return CustomUser.objects.all()
        elif is_agent(user):
            # 代理商：可以查看自己和下級分銷商
            return CustomUser.objects.filter(
                Q(id=user.id) | Q(parent=user, role=AccountRole.DISTRIBUTOR)
            )
        else:
            # 其他用戶：只能查看自己
            return CustomUser.objects.filter(id=user.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        context['account_statuses'] = AccountStatus.choices
        context['account_roles'] = AccountRole.choices
        
        # 獲取該帳號的儲值餘額
        try:
            topup = AccountTopUP.objects.get(account=self.object)
            context['account_balance'] = topup.balance
        except AccountTopUP.DoesNotExist:
            context['account_balance'] = 0
        
        # 獲取該用戶的下級用戶（根據權限）
        if is_headquarter_admin(user) or (is_agent(user) and self.object == user):
            # 總公司管理員可以看所有下級，代理商可以看自己的下級
            context['children'] = self.object.children.all()
        elif is_agent(user) and self.object.parent == user:
            # 代理商查看自己下級分銷商的詳情時，可以看該分銷商的下級
            context['children'] = self.object.children.all()
        else:
            # 其他情況不顯示下級
            context['children'] = CustomUser.objects.none()
        
        # 獲取用戶的統計資料
        context['total_children'] = context['children'].count()
        
        # 檢查當前用戶是否可以編輯此帳號
        context['can_edit'] = self._can_edit_account(user, self.object)
        
        return context
    
    def _can_edit_account(self, current_user, target_account):
        """
        檢查當前用戶是否可以編輯目標帳號
        """
        if is_headquarter_admin(current_user):
            # 總公司管理員可以編輯所有帳號
            return True
        elif is_agent(current_user):
            # 代理商可以編輯自己和下級分銷商
            return (
                target_account == current_user or 
                (target_account.parent == current_user and target_account.role == AccountRole.DISTRIBUTOR)
            )
        else:
            # 其他用戶只能編輯自己
            return target_account == current_user

