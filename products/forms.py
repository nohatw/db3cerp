from django import forms
from django.core.exceptions import ValidationError
from accounts.constant import AccountRole
from .models import Stock, Variant, AgentDistributorPricing
from .constant import ProductType

# 自定義支援多選且不強制驗證的 Widget
class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True
    
    def value_from_datadict(self, data, files, name):
        """
        覆寫此方法，讓沒有檔案時返回 None 而不是拋出錯誤
        """
        upload = files.getlist(name)
        if not upload:
            return None
        return upload

# 自定義 FileField，允許空值且不驗證檔案格式
class OptionalMultipleFileField(forms.FileField):
    """
    可選的多檔案上傳欄位
    - 如果沒有上傳檔案，返回 None
    - 不進行預設的檔案驗證
    """
    def to_python(self, data):
        """
        覆寫驗證邏輯：
        - 如果沒有檔案，返回 None
        - 如果有檔案，直接返回（跳過預設驗證）
        """
        if data in self.empty_values:
            return None
        return data
    
    def validate(self, value):
        """
        覆寫驗證方法：不進行任何驗證
        """
        pass

class StockCreateForm(forms.ModelForm):
    # ✅ 使用自定義的 FileField
    qr_images = OptionalMultipleFileField(
        widget=MultipleFileInput(attrs={
            'multiple': True,
            'class': 'form-control',
            'accept': 'image/*'
        }),
        label='批量上傳 QR 圖片',
        required=False,
        help_text='支援多選，適用於 ESIMIMG 類型'
    )

    class Meta:
        model = Stock
        fields = ['product', 'name', 'description', 'quantity', 'expire_date']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '例如：2025-01 進貨批次'
            }),
            'expire_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'description': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'placeholder': '可記錄進貨來源、供應商資訊、注意事項等'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': '請輸入數量'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 讓產品變體選單顯示更清楚
        self.fields['product'].queryset = Variant.objects.select_related('product').all()
        
        # ✅ 設定所有欄位為非必填（在 clean() 中根據產品類型動態驗證）
        self.fields['quantity'].required = False
        self.fields['expire_date'].required = False
        self.fields['qr_images'].required = False
    
    def clean(self):
        """
        自定義驗證邏輯：根據產品類型決定必填欄位
        """
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        
        if not product:
            raise ValidationError('請選擇產品變體')
        
        product_type = product.product_type
        qr_images = self.files.getlist('qr_images')
        quantity = cleaned_data.get('quantity')
        
        # 情況 A: ESIMIMG - 必須上傳圖片
        if product_type == ProductType.ESIMIMG:
            if not qr_images or len(qr_images) == 0:
                raise ValidationError('ESIMIMG 類型必須上傳至少一張 QR 圖片')
            
            # 檢查 SKU
            if not product.sku:
                raise ValidationError(
                    f'產品變體「{product.name}」未設定 SKU，無法上傳 ESIMIMG 圖片。'
                    f'請先在產品管理中設定 SKU。'
                )
            
            # ✅ 自動設定數量為圖片數量
            cleaned_data['quantity'] = len(qr_images)
        
        # 情況 B: 其他類型 - 必須填寫數量
        else:
            if not quantity or quantity < 1:
                raise ValidationError('請輸入有效的庫存數量（至少為 1）')
        
        return cleaned_data

class AgentDistributorPricingForm(forms.ModelForm):
    """
    代理商設定經銷價格的表單
    """
    class Meta:
        model = AgentDistributorPricing
        fields = ['price_distr', 'price_sales_distr']
        widgets = {
            'price_distr': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0',
                'min': '0',
                'step': '1'
            }),
            'price_sales_distr': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0',
                'min': '0',
                'step': '1'
            }),
        }
        labels = {
            'price_distr': '經銷價格',
            'price_sales_distr': '經銷特價',
        }
        help_texts = {
            'price_distr': '設定給您下線經銷商的拿貨價格',
            'price_sales_distr': '設定給您下線經銷商的促銷價格（可選）',
        }
