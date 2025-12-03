from django import template

register = template.Library()

@register.filter
def div(value, arg):
    """除法運算"""
    try:
        return float(value) / float(arg)
    except (ValueError, ZeroDivisionError):
        return 0

@register.filter
def mul(value, arg):
    """Multiplication operation for templates"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0
