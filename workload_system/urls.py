from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView  # <--- 1. 必须引入这个工具

# ==========================================
# 界面“装修”
# ==========================================
admin.site.site_header = '电气学院教学工作量计算系统'
admin.site.site_title = '教务核算'
admin.site.index_title = '系统管理控制台'

urlpatterns = [
    # 1. 后台管理地址
    path('admin/', admin.site.urls),

    # 2. 【关键修改】把首页 '' 自动跳转到 '/admin/'
    path('', RedirectView.as_view(url='/admin/', permanent=False)),
]

# 3. 附件图片访问配置
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)