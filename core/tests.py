from io import BytesIO

from django.contrib import admin
from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse
from openpyxl import load_workbook
from tablib import Dataset

from .models import (
    CoefficientExperiment, CoefficientInternship, CoefficientSize, ExperimentWorkload,
    Location, Organization, PracticeWorkload, Teacher, TheoryWorkload,
)
from .reports import export_organizations


class WorkloadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='电气学院')
        cls.other_org = Organization.objects.create(name='其他学院')
        cls.teacher_user = User.objects.create_user('teacher', is_staff=True)
        cls.college_user = User.objects.create_user('college', is_staff=True)
        cls.manager = User.objects.create_user('manager', is_staff=True)
        cls.unlinked = User.objects.create_user('unlinked', is_staff=True)
        cls.superuser = User.objects.create_superuser('root', password='test-only-password')
        cls.teacher = Teacher.objects.create(name='甲', card_id='1', college=cls.org, user=cls.teacher_user)
        cls.college_teacher = Teacher.objects.create(name='乙', card_id='2', college=cls.org, user=cls.college_user)
        cls.other_teacher = Teacher.objects.create(name='丙', card_id='3', college=cls.other_org)
        cls.manager.groups.add(Group.objects.create(name='TeachingAdmin'))
        cls.college_user.groups.add(Group.objects.create(name='CollegeAdmin'))
        # Intentionally grant broad model permissions: application boundaries must still hold.
        permissions = Permission.objects.filter(content_type__app_label='core')
        for user in [cls.teacher_user, cls.college_user, cls.manager, cls.unlinked]:
            user.user_permissions.set(permissions)
        cls.factory = RequestFactory()
        cls.rule = CoefficientExperiment.objects.create(category='电类', value=1.2)

    def request(self, user, method='get', data=None):
        request = getattr(self.factory, method)('/admin/', data=data or {})
        request.user = user
        return request

    def theory(self, **kwargs):
        values = dict(teacher=self.teacher, course_name='电路', category='major', student_count=30,
                      plan_hours=32, natural_class_count=1)
        values.update(kwargs)
        return TheoryWorkload.objects.create(**values)

    def practice(self, **kwargs):
        values = dict(teacher=self.teacher, course_name='设计', student_count=30,
                      practice_type='design', days_weeks=2, natural_class_count=1)
        values.update(kwargs)
        return PracticeWorkload.objects.create(**values)

    def experiment(self, **kwargs):
        values = dict(teacher=self.teacher, course_name='电路', project_name='实验',
                      difficulty_rule=self.rule, hours=10, class_count=2, subsidy=5)
        values.update(kwargs)
        return ExperimentWorkload.objects.create(**values)

    def workbook(self, response):
        self.assertEqual(response.status_code, 200)
        return load_workbook(BytesIO(response.content))

    def test_theory_formula_and_class_cap(self):
        CoefficientSize.objects.create(category='major', min_count=0, max_count=100, k_value=1.2)
        obj = self.theory(natural_class_count=5, has_lab=True, lab_hours=10,
                          is_new=True, new_course_proof='proof.pdf', is_bilingual=True)
        self.assertEqual(obj.total_workload, round(34 * 1.2 * 4 + 10 * .7 * 4 + 32, 2))

    def test_theory_check_course(self):
        self.assertEqual(self.theory(assessment_mode='check').total_workload, 32)

    def test_missing_new_course_proof_rejected(self):
        obj = self.theory(is_new=True)
        with self.assertRaises(ValidationError):
            obj.full_clean()

    def test_partial_save_recalculates_stored_total(self):
        for obj, field, value in [(self.theory(), 'plan_hours', 40),
                                  (self.practice(), 'days_weeks', 4),
                                  (self.experiment(), 'hours', 20)]:
            with self.subTest(model=type(obj).__name__):
                setattr(obj, field, value)
                obj.save(update_fields=[field])
                expected = obj.calculate()
                obj.refresh_from_db()
                self.assertEqual(obj.total_workload, expected)

    def test_coefficient_ranges_reject_overlap_and_invalid_bounds(self):
        CoefficientSize.objects.create(category='major', min_count=0, max_count=30, k_value=1)
        for low, high, k in [(30, 50, 1), (-1, 5, 1), (20, 10, 1), (31, 50, 0)]:
            with self.subTest(low=low, high=high, k=k), self.assertRaises(ValidationError):
                CoefficientSize(category='major', min_count=low, max_count=high, k_value=k).full_clean()
        CoefficientSize(category='major', min_count=31, max_count=50, k_value=1.2).full_clean()

    def test_internship_and_thesis_validation(self):
        for obj in [self.practice(practice_type='internship'), self.practice(practice_type='thesis'),
                    self.practice(practice_type='lab_intern')]:
            with self.subTest(type=obj.practice_type), self.assertRaises(ValidationError):
                obj.full_clean()

    def test_practice_formulas(self):
        rule = CoefficientInternship.objects.create(name='外地', value=2, add_days=2)
        self.assertEqual(self.practice(practice_type='internship', internship_rule=rule).total_workload, 8)
        self.assertEqual(self.practice(practice_type='thesis', thesis_category='science').total_workload, 78)
        self.assertEqual(self.practice(practice_type='lab_intern', lab_card_proof='card.pdf').total_workload, 2 * .7)

    def test_experiment_validation(self):
        for changes in [dict(hours=-1), dict(class_count=0), dict(subsidy=-1)]:
            obj = self.experiment(**changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                obj.full_clean()

    def test_review_actions_present_only_for_managers(self):
        for model in [TheoryWorkload, PracticeWorkload, ExperimentWorkload]:
            modeladmin = admin.site._registry[model]
            for user in [self.manager, self.college_user, self.superuser]:
                self.assertIn('make_verified', modeladmin.get_actions(self.request(user)))
                self.assertIn('make_rejected', modeladmin.get_actions(self.request(user)))
            self.assertNotIn('make_verified', modeladmin.get_actions(self.request(self.teacher_user)))

    def test_teacher_cannot_invoke_review_directly(self):
        obj = self.theory()
        with self.assertRaises(PermissionDenied):
            admin.site._registry[TheoryWorkload].make_verified(self.request(self.teacher_user), TheoryWorkload.objects.all())
        obj.refresh_from_db()
        self.assertEqual(obj.status, 'pending')

    def test_college_review_cannot_affect_other_college(self):
        ours, theirs = self.theory(), self.theory(teacher=self.other_teacher)
        modeladmin = admin.site._registry[TheoryWorkload]
        modeladmin.make_verified(self.request(self.college_user), TheoryWorkload.objects.all())
        ours.refresh_from_db()
        theirs.refresh_from_db()
        self.assertEqual(ours.status, 'verified')
        self.assertEqual(theirs.status, 'pending')

    def test_review_requires_model_change_permission(self):
        user = User.objects.create_user('no_perms', is_staff=True)
        user.groups.add(Group.objects.get(name='TeachingAdmin'))
        self.assertNotIn('make_verified', admin.site._registry[TheoryWorkload].get_actions(self.request(user)))

    def test_teacher_and_college_querysets_are_scoped(self):
        own = self.theory()
        college = self.theory(teacher=self.college_teacher)
        self.theory(teacher=self.other_teacher)
        modeladmin = admin.site._registry[TheoryWorkload]
        for user, ids in [(self.teacher_user, [own.pk]), (self.college_user, [own.pk, college.pk]), (self.unlinked, [])]:
            self.assertCountEqual(modeladmin.get_queryset(self.request(user)).values_list('pk', flat=True), ids)
        teacheradmin = admin.site._registry[Teacher]
        self.assertCountEqual(teacheradmin.get_queryset(self.request(self.teacher_user)), [self.teacher])

    def test_unlinked_user_cannot_select_or_create_for_any_teacher(self):
        modeladmin = admin.site._registry[TheoryWorkload]
        request = self.request(self.unlinked)
        self.assertFalse(modeladmin.has_add_permission(request))
        field = modeladmin.formfield_for_foreignkey(TheoryWorkload._meta.get_field('teacher'), request)
        self.assertFalse(field.queryset.exists())

    def test_import_restricted_to_global_managers(self):
        for model in [Teacher, TheoryWorkload, PracticeWorkload, ExperimentWorkload, CoefficientSize]:
            modeladmin = admin.site._registry[model]
            for user in [self.teacher_user, self.college_user, self.unlinked]:
                self.assertFalse(modeladmin.has_import_permission(self.request(user)))
            self.assertTrue(modeladmin.has_import_permission(self.request(self.manager)))

    def test_import_validates_rule_ranges(self):
        modeladmin = admin.site._registry[CoefficientSize]
        resource = modeladmin.get_resource_classes(self.request(self.manager))[0]()
        result = resource.import_data(Dataset(['', 'major', 10, 1, 1],
                                     headers=['id', 'category', 'min_count', 'max_count', 'k_value']), dry_run=True)
        self.assertTrue(result.has_validation_errors())
        self.assertEqual(CoefficientSize.objects.count(), 0)

    def test_coefficient_mutations_require_global_manager(self):
        modeladmin = admin.site._registry[CoefficientSize]
        for user in [self.teacher_user, self.college_user]:
            request = self.request(user)
            self.assertFalse(modeladmin.has_add_permission(request))
            self.assertFalse(modeladmin.has_change_permission(request))
            self.assertFalse(modeladmin.has_delete_permission(request))

    def test_verified_record_cannot_be_changed_or_deleted_by_teacher(self):
        for obj in [self.theory(status='verified'), self.practice(status='verified'), self.experiment(status='verified')]:
            modeladmin = admin.site._registry[type(obj)]
            request = self.request(self.teacher_user)
            self.assertFalse(modeladmin.has_change_permission(request, obj))
            self.assertFalse(modeladmin.has_delete_permission(request, obj))
            self.assertIn('classes', modeladmin.get_readonly_fields(request, obj))
            with self.assertRaises(PermissionDenied):
                modeladmin.delete_queryset(request, type(obj).objects.filter(pk=obj.pk))

    def test_teacher_post_to_verified_record_is_forbidden(self):
        obj = self.theory(status='verified')
        self.client.force_login(self.teacher_user)
        url = reverse('admin:core_theoryworkload_change', args=[obj.pk])
        self.assertEqual(self.client.post(url, {'plan_hours': 999}).status_code, 403)
        obj.refresh_from_db()
        self.assertEqual(obj.plan_hours, 32)

    def test_cross_teacher_change_page_is_inaccessible(self):
        obj = self.theory(teacher=self.other_teacher)
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse('admin:core_theoryworkload_change', args=[obj.pk]))
        self.assertIn(response.status_code, [302, 403, 404])
        self.assertNotContains(response, 'name="plan_hours"', status_code=response.status_code)

    def test_teacher_import_endpoint_is_forbidden(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse('admin:core_theoryworkload_import')).status_code, 403)

    def test_manager_can_review_through_changelist_post(self):
        obj = self.theory()
        self.client.force_login(self.manager)
        url = reverse('admin:core_theoryworkload_changelist')
        response = self.client.post(url, {'action': 'make_verified', '_selected_action': [obj.pk]})
        self.assertEqual(response.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.status, 'verified')
        response = self.client.post(url, {'action': 'make_rejected', '_selected_action': [obj.pk]})
        obj.refresh_from_db()
        self.assertEqual(obj.status, 'rejected')

    def test_teacher_review_post_does_not_change_status(self):
        obj = self.theory()
        self.client.force_login(self.teacher_user)
        self.client.post(reverse('admin:core_theoryworkload_changelist'),
                         {'action': 'make_verified', '_selected_action': [obj.pk]})
        obj.refresh_from_db()
        self.assertEqual(obj.status, 'pending')

    def test_admin_pages_and_export_views_render(self):
        self.client.force_login(self.superuser)
        self.assertRedirects(self.client.get('/'), '/admin/', fetch_redirect_response=False)
        for model in [Teacher, TheoryWorkload, PracticeWorkload, ExperimentWorkload, CoefficientSize, Organization]:
            name = model._meta.model_name
            for suffix in ['changelist', 'add']:
                response = self.client.get(reverse(f'admin:core_{name}_{suffix}'))
                self.assertEqual(response.status_code, 200, (name, suffix))
        self.assertEqual(self.client.get(reverse('admin:core_theoryworkload_export')).status_code, 200)

    def test_six_reports_use_verified_records_and_correct_summary(self):
        self.theory(status='verified')
        self.theory(status='pending', course_name='不可导出')
        self.theory(status='verified', category='public_elective')
        outside = Location.objects.create(name='校外', is_outside=True)
        self.practice(status='verified', location=outside)  # 6.6
        self.practice(status='verified')  # 6.6
        self.practice(status='verified', practice_type='thesis', thesis_category='science')  # 78
        self.experiment(status='verified')  # 29.96
        wb = self.workbook(export_organizations(Organization.objects.filter(pk=self.org.pk)))
        self.assertEqual(len(wb.sheetnames), 6)
        values = list(wb[f'{self.org.pk}-表1-学院汇总'].values)[2]
        self.assertEqual(values[1:8], (34, 34, 84.6, 6.6, 78, 13.2, 29.96))
        self.assertAlmostEqual(values[8], 189.16)
        self.assertNotIn('不可导出', str(list(wb[f'{self.org.pk}-表2-课堂教学'].values)))
        self.assertEqual(wb[f'{self.org.pk}-表6-教师汇总'].cell(3, 8).value, 189.16)

    def test_single_exports_filter_status_and_kind(self):
        theory = self.theory(status='verified')
        self.theory(status='pending')
        self.theory(status='verified', category='public_elective')
        practice = self.practice(status='verified')
        self.practice(status='rejected')
        experiment = self.experiment(status='verified')
        self.experiment(status='pending')
        for model, action in [(TheoryWorkload, 'export_table_2_theory'), (TheoryWorkload, 'export_table_5_public'),
                              (PracticeWorkload, 'export_table_3_practice'), (ExperimentWorkload, 'export_table_4_experiment')]:
            with self.subTest(action=action):
                modeladmin = admin.site._registry[model]
                wb = self.workbook(getattr(modeladmin, action)(self.request(self.manager), model.objects.all()))
                self.assertEqual(wb.active.max_row, 3)
        self.assertEqual(experiment.total_workload, 29.96)

    def test_export_cannot_leak_other_teacher_records(self):
        self.theory(status='verified')
        self.theory(teacher=self.other_teacher, status='verified', course_name='私密课程')
        modeladmin = admin.site._registry[TheoryWorkload]
        wb = self.workbook(modeladmin.export_table_2_theory(self.request(self.teacher_user), TheoryWorkload.objects.all()))
        self.assertNotIn('私密课程', str(list(wb.active.values)))
        orgadmin = admin.site._registry[Organization]
        wb = self.workbook(orgadmin.export_all_in_one(self.request(self.college_user), Organization.objects.all()))
        self.assertEqual(len(wb.sheetnames), 6)
        with self.assertRaises(PermissionDenied):
            orgadmin.export_all_in_one(self.request(self.teacher_user), Organization.objects.all())

    def test_multiple_and_empty_organization_exports_are_valid(self):
        wb = self.workbook(export_organizations(Organization.objects.all()))
        self.assertEqual(len(wb.sheetnames), 12)
        self.assertEqual(len(set(wb.sheetnames)), 12)
        self.assertEqual(len(self.workbook(export_organizations(Organization.objects.none())).sheetnames), 1)

    def test_excel_does_not_execute_user_text_as_formulas(self):
        self.theory(status='verified', course_name='=HYPERLINK("https://example.com")')
        wb = self.workbook(export_organizations(Organization.objects.filter(pk=self.org.pk)))
        cell = wb[f'{self.org.pk}-表2-课堂教学'].cell(3, 3)
        self.assertTrue(cell.value.startswith('='))
        self.assertEqual(cell.data_type, 's')

    def test_empty_partial_save_does_not_write_changes(self):
        obj = self.theory()
        obj.plan_hours = 999
        obj.save(update_fields=[])
        obj.refresh_from_db()
        self.assertEqual(obj.plan_hours, 32)
        self.assertEqual(obj.total_workload, 34)

    def test_incomplete_coefficient_form_returns_validation_errors(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse('admin:core_coefficientsize_add'), {'category': 'major'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'errorlist')
