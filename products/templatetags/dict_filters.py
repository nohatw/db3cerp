from django import template

register = template.Library()

@register.filter
def lookup(dictionary, key):
    """
    在模板中查找字典值
    用法: {{ cart|lookup:variant_id_str|lookup:"quantity" }}
    """
    if isinstance(dictionary, dict):
        return dictionary.get(str(key))
    return None