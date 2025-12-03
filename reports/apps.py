from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reports'
    verbose_name = '報表管理'
    
    def ready(self):
        """
        註冊 signal 處理器
        """
        import reports.signals
