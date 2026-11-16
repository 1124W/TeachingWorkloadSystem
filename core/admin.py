from django.contrib import admin
from django.core.exceptions import PermissionDenied
from import_export.admin import ImportExportModelAdmin
from import_export.resources import modelresource_factory

from .models import (
    ClassInfo, CoefficientExperiment, CoefficientInternship, CoefficientSize,
    Course, ExperimentWorkload, Location, Organization, PracticeWorkload,
    Teacher, TheoryWorkload,
)
from .reports import export_organizations, export_workload


def is_teaching_admin(user):
    return user.is_superuser or user.groups.filter(name='TeachingAdmin').exists()


def is_manager(user):
    return is_teaching_admin(user) or user.groups.filter(name='CollegeAdmin').exists()


def visible_teachers(user):
    qs = Teacher.objects.all()
    if is_teaching_admin(user):
        return qs
    teacher = getattr(user, 'teacher', None)
    if teacher is None:
        return qs.none()
    if user.groups.filter(name='CollegeAdmin').exists():
        return qs.filter(college_id=teacher.college_id)
    return qs.filter(pk=teacher.pk)


class ValidatedImportExportAdmin(ImportExportModelAdmin):
    def has_import_permission(self, request):
        # Global import can update existing IDs; restrict it to global managers.
        return is_teaching_admin(request.user) and super().has_change_permission(request)

    def get_resource_classes(self, request):
        return [modelresource_factory(self.model, meta_options={'clean_model_instances': True})]


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    actions = ['export_all_in_one']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_teaching_admin(request.user):
            return qs
        if is_manager(request.user):
            return qs.filter(pk__in=visible_teachers(request.user).values('college_id'))
        return qs.none()

    def has_add_permission(self, request):
        return is_teaching_admin(request.user) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return is_teaching_admin(request.user) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return is_teaching_admin(request.user) and super().has_delete_permission(request, obj)

    @admin.action(description='导出六类核算报表（已审核、全部学期）', permissions=['view'])
    def export_all_in_one(self, request, queryset):
        if not is_manager(request.user) or not self.has_view_permission(request):
            raise PermissionDenied
        return export_organizations(queryset.filter(pk__in=self.get_queryset(request).values('pk')))


@admin.register(Teacher)
class TeacherAdmin(ValidatedImportExportAdmin):
    list_display = ('name', 'card_id', 'college', 'user')
    search_fields = ('name', 'card_id')
    list_filter = ('college',)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(pk__in=visible_teachers(request.user).values('pk'))

    def get_readonly_fields(self, request, obj=None):
        return [] if is_teaching_admin(request.user) else ['card_id', 'college', 'user', 'title']

    def has_add_permission(self, request):
        return is_teaching_admin(request.user) and super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return is_teaching_admin(request.user) and super().has_delete_permission(request, obj)


@admin.register(ClassInfo)
class ClassInfoAdmin(ValidatedImportExportAdmin):
    list_display = ('name', 'major', 'student_count', 'natural_class_count', 'term')
    list_filter = ('major', 'term')


@admin.register(Course)
class CourseAdmin(ValidatedImportExportAdmin):
    list_display = ('name', 'category')
    search_fields = ('name',)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    pass


class CoefficientAdmin(ValidatedImportExportAdmin):
    def has_add_permission(self, request):
        return is_teaching_admin(request.user) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return is_teaching_admin(request.user) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return is_teaching_admin(request.user) and super().has_delete_permission(request, obj)


@admin.register(CoefficientSize)
class SizeCoefAdmin(CoefficientAdmin):
    list_display = ('category', 'min_count', 'max_count', 'k_value')
    list_filter = ('category',)


@admin.register(CoefficientInternship)
class InternshipCoefAdmin(CoefficientAdmin):
    list_display = ('name', 'value', 'add_days')


@admin.register(CoefficientExperiment)
class ExperimentCoefAdmin(CoefficientAdmin):
    list_display = ('category', 'value')


class BaseWorkloadAdmin(ValidatedImportExportAdmin):
    actions = ['make_verified', 'make_rejected']
    filter_horizontal = ('classes',)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(teacher__in=visible_teachers(request.user))

    def has_review_permission(self, request):
        return is_manager(request.user) and super().has_change_permission(request)

    def has_add_permission(self, request):
        return super().has_add_permission(request) and visible_teachers(request.user).exists()

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request, obj):
            return False
        if obj is None:
            return True
        if not visible_teachers(request.user).filter(pk=obj.teacher_id).exists():
            return False
        return is_manager(request.user) or obj.status != 'verified'

    def has_delete_permission(self, request, obj=None):
        if not super().has_delete_permission(request, obj):
            return False
        return obj is None or self.has_change_permission(request, obj)

    def delete_queryset(self, request, queryset):
        if not is_manager(request.user) and queryset.filter(status='verified').exists():
            raise PermissionDenied('已审核记录不能删除。')
        super().delete_queryset(request, queryset)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'teacher':
            kwargs['queryset'] = visible_teachers(request.user)
            if not is_manager(request.user):
                kwargs['initial'] = getattr(request.user, 'teacher', None)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        fields = ['total_workload']
        if not is_manager(request.user):
            fields.append('status')
            if obj and obj.status == 'verified':
                return [f.name for f in self.model._meta.fields] + ['classes']
        return fields

    def save_model(self, request, obj, form, change):
        if not visible_teachers(request.user).filter(pk=obj.teacher_id).exists():
            raise PermissionDenied
        if not is_manager(request.user):
            if change and not self.has_change_permission(request, self.model.objects.get(pk=obj.pk)):
                raise PermissionDenied
            obj.status = 'pending'
        super().save_model(request, obj, form, change)

    def review(self, request, queryset, status):
        if not self.has_review_permission(request):
            raise PermissionDenied
        queryset.filter(pk__in=self.get_queryset(request).values('pk')).update(status=status)

    @admin.action(description='审核通过所选工作量', permissions=['review'])
    def make_verified(self, request, queryset):
        self.review(request, queryset, 'verified')

    @admin.action(description='驳回所选工作量', permissions=['review'])
    def make_rejected(self, request, queryset):
        self.review(request, queryset, 'rejected')

    @admin.display(description='关联班级')
    def get_class_names(self, obj):
        return obj.get_class_names()

    def export_report(self, request, queryset, kind):
        if not self.has_view_permission(request):
            raise PermissionDenied
        return export_workload(kind, queryset.filter(pk__in=self.get_queryset(request).values('pk')))


@admin.register(TheoryWorkload)
class TheoryWorkloadAdmin(BaseWorkloadAdmin):
    list_display = ('term', 'teacher', 'course_name', 'get_class_names', 'student_count', 'total_workload', 'status')
    list_filter = ('status', 'term', 'category')
    search_fields = ('course_name', 'teacher__name')
    actions = BaseWorkloadAdmin.actions + ['export_table_2_theory', 'export_table_5_public']

    @admin.action(description='导出表2：课堂教学（已审核）', permissions=['view'])
    def export_table_2_theory(self, request, queryset):
        return self.export_report(request, queryset, 'theory')

    @admin.action(description='导出表5：公选课（已审核）', permissions=['view'])
    def export_table_5_public(self, request, queryset):
        return self.export_report(request, queryset, 'public')


@admin.register(PracticeWorkload)
class PracticeWorkloadAdmin(BaseWorkloadAdmin):
    list_display = ('term', 'teacher', 'practice_type', 'get_class_names', 'days_weeks', 'total_workload', 'status')
    list_filter = ('status', 'term', 'practice_type')
    search_fields = ('course_name', 'teacher__name')
    actions = BaseWorkloadAdmin.actions + ['export_table_3_practice']

    @admin.action(description='导出表3：实践环节（已审核）', permissions=['view'])
    def export_table_3_practice(self, request, queryset):
        return self.export_report(request, queryset, 'practice')


@admin.register(ExperimentWorkload)
class ExperimentWorkloadAdmin(BaseWorkloadAdmin):
    list_display = ('term', 'project_name', 'teacher', 'get_class_names', 'hours', 'total_workload', 'status')
    list_filter = ('status', 'term')
    search_fields = ('course_name', 'project_name', 'teacher__name')
    # Edit through the form so approved records cannot be altered via list_editable.
    actions = BaseWorkloadAdmin.actions + ['export_table_4_experiment']

    @admin.action(description='导出表4：实验教学（已审核）', permissions=['view'])
    def export_table_4_experiment(self, request, queryset):
        return self.export_report(request, queryset, 'experiment')
