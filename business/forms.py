from django import forms
from business.models import AccountTopUP, AccountTopUPLog
from accounts.models import CustomUser
from accounts.constant import AccountRole, AccountStatus
from business.constant import TopupType


class TopupCreateForm(forms.ModelForm):
    """儲值新增表單 - 僅供總公司管理員使用"""
    
    account = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        label='儲值帳號',
        widget=forms.HiddenInput(),  # 改為隱藏欄位
        required=True
    )
    
    amount = forms.DecimalField(
        label='儲值金額',
        max_digits=10,
        decimal_places=0,
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '請輸入儲值金額',
            'required': True,
            'min': '1'
        }),
        help_text='請輸入要儲值的金額（必須大於 0）'
    )
    
    remark = forms.CharField(
        label='備註',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': '請輸入備註（選填）'
        }),
        help_text='可以輸入此次儲值的相關備註'
    )

    class Meta:
        model = AccountTopUP
        fields = ['account', 'remark']

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('request_user', None)
        account_id = kwargs.pop('account_id', None)
        super().__init__(*args, **kwargs)
        
        # 只有總公司管理員可以訪問
        if self.request_user and \
           self.request_user.role == AccountRole.HEADQUARTER and \
           (self.request_user.is_admin or self.request_user.is_superuser):
            
            # 設定可選擇的帳號範圍
            self.fields['account'].queryset = CustomUser.objects.filter(
                is_active=True,
                status=AccountStatus.ACTIVE
            ).select_related('parent')
            
            # 如果有傳入 account_id，設定預設值
            if account_id:
                try:
                    selected_account = CustomUser.objects.get(
                        id=account_id,
                        is_active=True,
                        status=AccountStatus.ACTIVE
                    )
                    self.fields['account'].initial = selected_account
                except CustomUser.DoesNotExist:
                    pass
        else:
            # 非總公司管理員不應該能訪問此表單
            self.fields['account'].queryset = CustomUser.objects.none()
            self.fields['amount'].widget.attrs['disabled'] = True
            self.fields['remark'].widget.attrs['disabled'] = True

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is None or amount <= 0:
            raise forms.ValidationError('儲值金額必須大於 0')
        return amount
    
    def clean_account(self):
        account = self.cleaned_data.get('account')
        if not account:
            raise forms.ValidationError('請選擇要儲值的帳號')
        if not account.is_active or account.status != AccountStatus.ACTIVE:
            raise forms.ValidationError('此帳號無法進行儲值（帳號未啟用或已停用）')
        return account
    
    def clean(self):
        cleaned_data = super().clean()
        
        # 再次確認操作者權限
        if self.request_user:
            if not (self.request_user.role == AccountRole.HEADQUARTER and 
                   (self.request_user.is_admin or self.request_user.is_superuser)):
                raise forms.ValidationError('您沒有權限執行此操作，只有總公司管理員可以新增儲值。')
        
        return cleaned_data