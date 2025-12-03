from django import template
from decimal import Decimal

register = template.Library()

@register.filter
def currency(value):
    """
    格式化貨幣顯示（千分位）
    用法：{{ 1234567|currency }} → 1,234,567
    """
    try:
        value = Decimal(str(value))
        return f"{value:,.0f}"
    except (ValueError, TypeError):
        return value

@register.filter
def currency_chinese(value):
    """
    將數字轉換為中文大寫金額
    用法：{{ 12345|currency_chinese }} → 壹萬貳仟參佰肆拾伍
    
    支援範圍：0 ~ 999,999,999（億以下）
    """
    try:
        value = int(Decimal(str(value)))
        
        if value == 0:
            return "零"
        
        # 中文數字映射
        chinese_numbers = {
            0: "零", 1: "壹", 2: "貳", 3: "參", 4: "肆",
            5: "伍", 6: "陸", 7: "柒", 8: "捌", 9: "玖"
        }
        
        # 單位映射
        units = ["", "拾", "佰", "仟"]
        big_units = ["", "萬", "億"]
        
        # 將數字拆分為每 4 位一組
        def split_number(num):
            result = []
            while num > 0:
                result.append(num % 10000)
                num //= 10000
            return result
        
        # 處理 4 位數字
        def convert_four_digits(num):
            if num == 0:
                return ""
            
            result = []
            digits = []
            temp = num
            
            # 拆分成個位數字
            for i in range(4):
                digits.append(temp % 10)
                temp //= 10
            
            digits.reverse()
            
            # 處理每一位
            for i, digit in enumerate(digits):
                if digit != 0:
                    result.append(chinese_numbers[digit])
                    result.append(units[3-i])
                elif i < 3 and any(d != 0 for d in digits[i+1:]):
                    # 如果當前是 0，但後面還有非 0 數字，則加"零"
                    if not result or result[-1] != "零":
                        result.append("零")
            
            return "".join(result)
        
        # 分組處理
        groups = split_number(value)
        result = []
        
        for i, group in enumerate(groups):
            if group == 0:
                continue
            
            group_str = convert_four_digits(group)
            
            # 加上大單位（萬、億）
            if i > 0:
                group_str += big_units[i]
            
            result.append(group_str)
        
        result.reverse()
        final_result = "".join(result)
        
        # 處理特殊情況：移除多餘的"零"
        final_result = final_result.replace("零零", "零")
        if final_result.endswith("零"):
            final_result = final_result[:-1]
        
        return final_result
        
    except (ValueError, TypeError, AttributeError):
        return str(value)