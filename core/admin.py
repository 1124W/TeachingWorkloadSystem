from django.contrib import admin
from django.db.models import Sum
from django.http import HttpResponse
from import_export.admin import ImportExportModelAdmin
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from .models import *


# ==========================================
# 🔧 工具函数：样式设置
# ==========================================
def style_excel_sheet(ws):
    thin = Side(border_style="thin", color="000000")
    border = Border(top=thin, left=thin, right=thin, bottom=thin)
    font = Font(name='宋体', size=10)
    align = Alignment(horizontal='center', vertical='center', wrap_text=True)

    for row in ws.iter_rows():
        for cell in row:
            cell.border = border
            cell.alignment = align
            cell.font = font

    for i in range(1, ws.max_column + 1):
        col_letter = get_column_letter(i)
        ws.column_dimensions[col_letter].width = 13

    # 特别调整列宽
    ws.column_dimensions['C'].width = 20
    ws.column_dimensions['D'].width = 25


# ==========================================
# 0. 审核动作
# ==========================================
@admin.action(description='【审核通过】所选工作量')
def make_verified(modeladmin, request, queryset):
    queryset.update(status='verified')


@admin.action(description='【驳回】所选工作量')
def make_rejected(modeladmin, request, queryset):
    queryset.update(status='rejected')


# ==========================================
# ★★★ 终极导出 (含所有修复) ★★★
# ==========================================
@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    actions = ['export_all_in_one']

    @admin.action(description='🔥 终极导出：一键生成所有表格 (6合1)')
    def export_all_in_one(self, request, queryset):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        for org in queryset:
            teachers = Teacher.objects.filter(college=org)

            # --- Sheet 1: 学院汇总 ---
            ws1 = wb.create_sheet("表1-学院汇总")
            ws1.merge_cells('A1:E1')
            ws1['A1'] = f"江苏大学京江学院2025年度工作量核算学院汇总表"
            ws1['A1'].font = Font(size=16, bold=True)
            ws1['A1'].alignment = Alignment(horizontal='center')

            ws1.merge_cells('A3:E3')
            ws1['A3'] = "校本部及校外工作量"
            ws1['A3'].font = Font(bold=True)
            ws1.append(['', '', '', '', ''])
            ws1['A4'] = "系 (教研室)"
            ws1['B4'] = "实践教学"
            ws1.merge_cells('B4:C4')
            ws1['D4'] = "合计"
            ws1.merge_cells('D4:D5')
            ws1['B5'] = "校本部实践教学\n(包含毕业设计或论文)"
            ws1['C5'] = "校外实践教学"
            ws1.merge_cells('A4:A5')

            p_in = PracticeWorkload.objects.filter(teacher__in=teachers, status='verified').exclude(
                practice_type__contains='外地').aggregate(Sum('total_workload'))['total_workload__sum'] or 0
            p_out = PracticeWorkload.objects.filter(teacher__in=teachers, status='verified',
                                                    practice_type__contains='外地').aggregate(Sum('total_workload'))[
                        'total_workload__sum'] or 0
            ws1.append([org.name, p_in, p_out, p_in + p_out])
            ws1.append(['合计', p_in, p_out, p_in + p_out])

            start_row = ws1.max_row + 2
            ws1.merge_cells(f'A{start_row}:E{start_row}')
            ws1[f'A{start_row}'] = "京江新校区工作量"
            ws1[f'A{start_row}'].font = Font(bold=True)
            h_row = start_row + 1
            ws1.cell(row=h_row, column=1, value="系 (教研室)")
            ws1.cell(row=h_row, column=2, value="课堂教学")
            ws1.cell(row=h_row, column=3, value="实践教学")
            ws1.merge_cells(f'C{h_row}:D{h_row}')
            ws1.cell(row=h_row, column=5, value="校公选课教学")
            ws1.cell(row=h_row, column=6, value="合计")

            h_row2 = h_row + 1
            ws1.cell(row=h_row2, column=3, value="毕业设计(论文)")
            ws1.cell(row=h_row2, column=4, value="其他实践教学")
            ws1.merge_cells(f'A{h_row}:A{h_row2}')
            ws1.merge_cells(f'B{h_row}:B{h_row2}')
            ws1.merge_cells(f'E{h_row}:E{h_row2}')
            ws1.merge_cells(f'F{h_row}:F{h_row2}')

            t_load = TheoryWorkload.objects.filter(teacher__in=teachers, status='verified').exclude(
                category='public_elective').aggregate(Sum('total_workload'))['total_workload__sum'] or 0
            pub_load = TheoryWorkload.objects.filter(teacher__in=teachers, status='verified',
                                                     category='public_elective').aggregate(Sum('total_workload'))[
                           'total_workload__sum'] or 0
            ws1.append([org.name, t_load, 0, 0, pub_load, t_load + pub_load])
            ws1.append(['合计', t_load, 0, 0, pub_load, t_load + pub_load])
            style_excel_sheet(ws1)

            # --- Sheet 2: 课堂教学 ---
            ws2 = wb.create_sheet("表2-课堂教学")
            ws2.merge_cells('A1:P1')
            ws2['A1'] = f"江苏大学京江学院2025年度课堂教学工作量核算表"
            ws2['A1'].font = Font(size=16, bold=True)
            ws2['A1'].alignment = Alignment(horizontal='center')
            ws2.append(
                ['上/下半年', '系 (教研室)', '课程名称', '课程类别', '教师姓名', '授课班级', '自然班级数', '学生人数',
                 '课堂教学', '', '', '', '指导上机', '', '', '备注'])
            ws2.append(
                ['', '', '', '', '', '', '', '', '计划学时', '考核方式', '系数', '工作量', '计划学时', '系数', '工作量',
                 ''])
            for c in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'P']:
                ws2.merge_cells(f'{c}2:{c}3')
            ws2.merge_cells('I2:L2')
            ws2.merge_cells('M2:O2')

            theory_qs = TheoryWorkload.objects.filter(teacher__in=teachers).exclude(category='public_elective')
            for obj in theory_qs:
                k = CoefficientSize.get_k_by_count(obj.category, obj.student_count)
                calc_class = 4 if obj.natural_class_count > 4 else obj.natural_class_count
                lab_load = round(obj.lab_hours * 0.7 * calc_class, 2) if obj.has_lab else 0
                theory_load = round(obj.total_workload - lab_load, 2)
                ws2.append([
                    obj.term, str(obj.teacher.college), obj.course_name, obj.get_category_display(), obj.teacher.name,
                    obj.get_class_names(),
                    obj.natural_class_count, obj.student_count, obj.plan_hours, obj.get_assessment_mode_display(), k,
                    theory_load,
                    obj.lab_hours if obj.has_lab else '', 0.7 if obj.has_lab else '', lab_load if obj.has_lab else '',
                    ''
                ])
            style_excel_sheet(ws2)

            # --- Sheet 3: 实践环节 ---
            ws3 = wb.create_sheet("表3-实践环节")
            ws3.merge_cells('A1:S1')
            ws3['A1'] = f"江苏大学京江学院2025年度实践环节教学工作量核算表"
            ws3['A1'].font = Font(size=16, bold=True)
            ws3['A1'].alignment = Alignment(horizontal='center')
            ws3.append(['上/下半年', '系(教研室)', '实践环节名称', '教师姓名', '指导班级', '自然班级数', '学生人数',
                        '指导课程设计', '', '', '指导实习', '', '', '指导毕业设计(论文)', '', '', '上机实习', '', '',
                        '地点'])
            ws3.append(['', '', '', '', '', '', '',
                        '计划天数', '系数', '工作当量', '计划天数', '系数', '工作当量', '计划周数', '系数', '工作当量',
                        '机时', '自然班*0.7', '工作当量', ''])
            cols = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'T']
            for c in cols:
                ws3.merge_cells(f'{c}2:{c}3')
            ws3.merge_cells('H2:J2')
            ws3.merge_cells('K2:M2')
            ws3.merge_cells('N2:P2')
            ws3.merge_cells('Q2:S2')

            practice_qs = PracticeWorkload.objects.filter(teacher__in=teachers)
            for obj in practice_qs:
                row = [obj.term, str(obj.teacher.college), obj.get_practice_type_display(), obj.teacher.name,
                       obj.get_class_names(), obj.natural_class_count, obj.student_count]
                extras = [''] * 13
                if obj.practice_type == 'design':
                    extras[0] = obj.days_weeks;
                    extras[1] = 3.3;
                    extras[2] = obj.total_workload
                elif obj.practice_type == 'internship':
                    c = obj.internship_rule.value if obj.internship_rule else ''
                    extras[3] = obj.days_weeks;
                    extras[4] = c;
                    extras[5] = obj.total_workload
                elif obj.practice_type == 'thesis':
                    c_map = {'science': 1.3, 'arts': 1.1, 'edu': 1.2}
                    c = c_map.get(obj.thesis_category, 1.0)
                    extras[6] = obj.days_weeks;
                    extras[7] = c;
                    extras[8] = obj.total_workload
                elif obj.practice_type == 'lab_intern':
                    extras[9] = obj.days_weeks;
                    extras[10] = obj.natural_class_count * 0.7;
                    extras[11] = obj.total_workload
                extras[12] = obj.location.name if obj.location else ''
                ws3.append(row + extras)
            style_excel_sheet(ws3)

            # --- Sheet 4: 实验工作量 ---
            ws4 = wb.create_sheet("表4-实验工作量")
            ws4.merge_cells('A1:R1')
            ws4['A1'] = f"实验室2025年度实验教学工作量计算表"
            ws4['A1'].font = Font(size=16, bold=True)
            ws4['A1'].alignment = Alignment(horizontal='center')
            ws4.append(['上/下半年', '课程名称', '实验项目', '参加班级', '难度系数K', '批次系数P', '学时数G', '班级数N',
                        '实验当量T21=∑K×P×G×N',
                        '实验室常规T22', '', '', '', '活动补贴T23', '教学工作量', '实验发生地'])
            ws4.append(['', '', '', '', '', '', '', '', 'T21=KPGN',
                        '资产数', 'Q1', '人数', 'Q2', '开放补贴', '', 'T0=(T21+T22+T23)*0.8', ''])
            for c in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'O', 'P', 'Q']:
                ws4.merge_cells(f'{c}2:{c}3')
            ws4.merge_cells('J2:N2')

            exp_qs = ExperimentWorkload.objects.filter(teacher__in=teachers)
            for obj in exp_qs:
                k = obj.difficulty_rule.value if obj.difficulty_rule else 1.0
                p = {1: 1.3, 2: 2.0, 3: 2.6, 4: 3.0, 5: 3.4}.get(obj.batch_count, 1.3)
                t21 = k * p * obj.hours * obj.class_count
                ws4.append([
                    obj.term, obj.course_name, obj.project_name, obj.get_class_names(), k, p, obj.hours,
                    obj.class_count, round(t21, 2),
                    '', '', '', '', '', obj.subsidy, obj.total_workload, obj.location
                ])
            style_excel_sheet(ws4)

            # --- Sheet 5: 公选课 ---
            ws5 = wb.create_sheet("表5-公选课")
            ws5.merge_cells('A1:I1')
            ws5['A1'] = f"{org.name}2025年度公共选修课工作量核算表"
            ws5['A1'].font = Font(size=16, bold=True)
            ws5['A1'].alignment = Alignment(horizontal='center')
            ws5.append(['上/下半年', '课程名称', '授课教师', '上课班级', '选课人数', '课堂教学', '', '', '备注'])
            ws5.append(['', '', '', '', '', '计划学时', '系数', '工作量', ''])
            ws5.merge_cells('A2:A3');
            ws5.merge_cells('B2:B3');
            ws5.merge_cells('C2:C3');
            ws5.merge_cells('D2:D3');
            ws5.merge_cells('E2:E3');
            ws5.merge_cells('I2:I3')
            ws5.merge_cells('F2:H2')
            public_qs = TheoryWorkload.objects.filter(teacher__in=teachers, category='public_elective')
            for obj in public_qs:
                k = CoefficientSize.get_k_by_count(obj.category, obj.student_count)
                ws5.append([obj.term, obj.course_name, obj.teacher.name, obj.get_class_names(), obj.student_count,
                            obj.plan_hours, k, obj.total_workload, ''])
            style_excel_sheet(ws5)

            # --- Sheet 6: 教师汇总 ---
            ws6 = wb.create_sheet("表6-教师汇总")
            ws6.merge_cells('A1:K1')
            ws6['A1'] = f"{org.name}2025年度教师教学工作量汇总表"
            ws6['A1'].font = Font(size=16, bold=True)
            ws6['A1'].alignment = Alignment(horizontal='center')
            ws6.append(
                ['学院(单位)', '序号', '一卡通号', '姓名', '新校区理论', '毕业设计', '其他实践', '实验教学', '总计',
                 '理伦学时总计', '核算人签字'])
            ws6.append(['', '', '', '', '教学', '(论文)', '(除毕设)', '(校本部)', '', '总计', '签字'])
            for i in range(1, 12):
                col = get_column_letter(i)
                ws6.merge_cells(f'{col}2:{col}3')
            idx = 1
            for teacher in teachers:
                t_load = \
                TheoryWorkload.objects.filter(teacher=teacher, status='verified').aggregate(Sum('total_workload'))[
                    'total_workload__sum'] or 0
                p_load = \
                PracticeWorkload.objects.filter(teacher=teacher, status='verified').aggregate(Sum('total_workload'))[
                    'total_workload__sum'] or 0
                e_load = \
                ExperimentWorkload.objects.filter(teacher=teacher, status='verified').aggregate(Sum('total_workload'))[
                    'total_workload__sum'] or 0
                total = t_load + p_load + e_load
                t_hours = \
                TheoryWorkload.objects.filter(teacher=teacher, status='verified').aggregate(Sum('plan_hours'))[
                    'plan_hours__sum'] or 0
                thesis_load = \
                PracticeWorkload.objects.filter(teacher=teacher, status='verified', practice_type='thesis').aggregate(
                    Sum('total_workload'))['total_workload__sum'] or 0
                other_practice = p_load - thesis_load
                ws6.append(
                    [str(teacher.college), idx, teacher.card_id, teacher.name, t_load, thesis_load, other_practice,
                     e_load, t_load + p_load + e_load, t_hours, ''])
                idx += 1
            style_excel_sheet(ws6)

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="Final_Report_Official.xlsx"'
        wb.save(response)
        return response


# ==========================================
# 1. 基础信息管理
# ==========================================
@admin.register(Teacher)
class TeacherAdmin(ImportExportModelAdmin):
    list_display = ('name', 'card_id', 'college', 'user')
    search_fields = ('name', 'card_id')
    list_filter = ('college',)

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser or request.user.groups.filter(name='TeachingAdmin').exists():
            return []
        return ['card_id', 'college', 'user', 'title']


@admin.register(ClassInfo)
class ClassInfoAdmin(ImportExportModelAdmin):
    list_display = ('name', 'major', 'student_count', 'natural_class_count', 'term')
    list_filter = ('major', 'term')


@admin.register(Course)
class CourseAdmin(ImportExportModelAdmin):
    list_display = ('name', 'category')
    search_fields = ('name',)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin): pass


# ==========================================
# 2. 系数管理
# ==========================================
class CoefficientAdmin(ImportExportModelAdmin):
    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.groups.filter(name='TeachingAdmin').exists()


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


# ==========================================
# 3. 业务录入管理
# ==========================================
class BaseWorkloadAdmin(ImportExportModelAdmin):
    actions = [make_verified, make_rejected]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser: return qs
        if request.user.groups.filter(name__in=['TeachingAdmin', 'CollegeAdmin']).exists(): return qs
        if hasattr(request.user, 'teacher'): return qs.filter(teacher=request.user.teacher)
        return qs.none()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "teacher":
            if not request.user.is_superuser and not request.user.groups.filter(
                    name__in=['TeachingAdmin', 'CollegeAdmin']).exists():
                if hasattr(request.user, 'teacher'):
                    kwargs["queryset"] = Teacher.objects.filter(id=request.user.teacher.id)
                    kwargs["initial"] = request.user.teacher
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        readonly = ['total_workload']
        if not request.user.is_superuser and not request.user.groups.filter(
                name__in=['TeachingAdmin', 'CollegeAdmin']).exists():
            readonly.append('status')
            if obj and obj.status == 'verified': return [f.name for f in self.model._meta.fields]
        return readonly


@admin.register(TheoryWorkload)
class TheoryWorkloadAdmin(BaseWorkloadAdmin):
    filter_horizontal = ('classes',)
    list_display = ('term', 'teacher', 'course_name', 'get_class_names', 'student_count', 'total_workload', 'status')
    list_filter = ('status', 'term', 'category')
    search_fields = ('course_name', 'teacher__name')

    def get_class_names(self, obj):
        return obj.get_class_names()

    get_class_names.short_description = "授课班级"

    # --- 表2 单独导出 ---
    actions = ['export_table_2_theory']

    @admin.action(description='导出【表2：课堂教学核算表】')
    def export_table_2_theory(self, request, queryset):
        queryset = queryset.exclude(category='public_elective')
        wb = openpyxl.Workbook();
        ws = wb.active
        ws.title = "课堂教学"
        ws.merge_cells('A1:P1')
        ws['A1'] = "江苏大学京江学院2025年度课堂教学工作量核算表"
        ws['A1'].font = Font(size=16, bold=True);
        ws['A1'].alignment = Alignment(horizontal='center')
        ws.append(['上/下半年', '系 (教研室)', '课程名称', '课程类别', '教师姓名', '授课班级', '自然班级数', '学生人数',
                   '课堂教学', '', '', '', '指导上机', '', '', '备注'])
        ws.append(
            ['', '', '', '', '', '', '', '', '计划学时', '考核方式', '系数', '工作量', '计划学时', '系数', '工作量',
             ''])
        for c in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'P']: ws.merge_cells(f'{c}2:{c}3')
        ws.merge_cells('I2:L2');
        ws.merge_cells('M2:O2')
        for obj in queryset:
            k = CoefficientSize.get_k_by_count(obj.category, obj.student_count)
            calc_class = 4 if obj.natural_class_count > 4 else obj.natural_class_count
            lab_load = round(obj.lab_hours * 0.7 * calc_class, 2) if obj.has_lab else 0
            theory_load = round(obj.total_workload - lab_load, 2)
            ws.append([
                obj.term, str(obj.teacher.college), obj.course_name, obj.get_category_display(), obj.teacher.name,
                obj.get_class_names(),
                obj.natural_class_count, obj.student_count, obj.plan_hours, obj.get_assessment_mode_display(), k,
                theory_load,
                obj.lab_hours if obj.has_lab else '', 0.7 if obj.has_lab else '', lab_load if obj.has_lab else '', ''
            ])
        style_excel_sheet(ws)
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="Table2_Theory.xlsx"'
        wb.save(response)
        return response

    # --- 表5 单独导出 ---
    actions += ['export_table_5_public']

    @admin.action(description='导出【表5：公选课核算表】')
    def export_table_5_public(self, request, queryset):
        queryset = queryset.filter(category='public_elective')
        wb = openpyxl.Workbook();
        ws = wb.active
        ws.title = "公选课"
        ws.merge_cells('A1:I1')
        ws['A1'] = "江苏大学京江学院2025年度公共选修课工作量核算表"
        ws['A1'].font = Font(size=16, bold=True);
        ws['A1'].alignment = Alignment(horizontal='center')
        ws.append(['上/下半年', '课程名称', '授课教师', '上课班级', '选课人数', '课堂教学', '', '', '备注'])
        ws.append(['', '', '', '', '', '计划学时', '系数', '工作量', ''])
        ws.merge_cells('A2:A3');
        ws.merge_cells('B2:B3');
        ws.merge_cells('C2:C3');
        ws.merge_cells('D2:D3');
        ws.merge_cells('E2:E3');
        ws.merge_cells('I2:I3')
        ws.merge_cells('F2:H2')
        for obj in queryset:
            k = CoefficientSize.get_k_by_count(obj.category, obj.student_count)
            ws.append(
                [obj.term, obj.course_name, obj.teacher.name, obj.get_class_names(), obj.student_count, obj.plan_hours,
                 k, obj.total_workload, ''])
        style_excel_sheet(ws)
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="Table5_Public.xlsx"'
        wb.save(response)
        return response


@admin.register(PracticeWorkload)
class PracticeWorkloadAdmin(BaseWorkloadAdmin):
    filter_horizontal = ('classes',)
    list_display = ('term', 'teacher', 'practice_type', 'get_class_names', 'days_weeks', 'total_workload', 'status')
    list_filter = ('status', 'practice_type')
    search_fields = ('teacher__name',)

    def get_class_names(self, obj):
        return obj.get_class_names()

    get_class_names.short_description = "指导班级"

    # --- 表3 单独导出 ---
    actions = ['export_table_3_practice']

    @admin.action(description='导出【表3：实践环节核算表】')
    def export_table_3_practice(self, request, queryset):
        wb = openpyxl.Workbook();
        ws = wb.active
        ws.title = "实践环节"
        ws.merge_cells('A1:S1')
        ws['A1'] = "江苏大学京江学院2025年度实践环节教学工作量核算表"
        ws['A1'].font = Font(size=16, bold=True);
        ws['A1'].alignment = Alignment(horizontal='center')
        ws.append(['上/下半年', '系(教研室)', '实践环节名称', '教师姓名', '指导班级', '自然班级数', '学生人数',
                   '指导课程设计', '', '', '指导实习', '', '', '指导毕业设计(论文)', '', '', '上机实习', '', '',
                   '地点'])
        ws.append(['', '', '', '', '', '', '',
                   '计划天数', '系数', '工作当量', '计划天数', '系数', '工作当量', '计划周数', '系数', '工作当量',
                   '机时', '自然班*0.7', '工作当量', ''])
        cols = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'T']
        for c in cols: ws.merge_cells(f'{c}2:{c}3')
        ws.merge_cells('H2:J2');
        ws.merge_cells('K2:M2');
        ws.merge_cells('N2:P2');
        ws.merge_cells('Q2:S2')
        for obj in queryset:
            # 修复：此处变量名已从 ws3 改为 ws，避免报错
            row = [obj.term, str(obj.teacher.college), obj.get_practice_type_display(), obj.teacher.name,
                   obj.get_class_names(), obj.natural_class_count, obj.student_count]
            extras = [''] * 13
            if obj.practice_type == 'design':
                extras[0] = obj.days_weeks;
                extras[1] = 3.3;
                extras[2] = obj.total_workload
            elif obj.practice_type == 'internship':
                c = obj.internship_rule.value if obj.internship_rule else ''
                extras[3] = obj.days_weeks;
                extras[4] = c;
                extras[5] = obj.total_workload
            elif obj.practice_type == 'thesis':
                c_map = {'science': 1.3, 'arts': 1.1, 'edu': 1.2}
                c = c_map.get(obj.thesis_category, 1.0)
                extras[6] = obj.days_weeks;
                extras[7] = c;
                extras[8] = obj.total_workload
            elif obj.practice_type == 'lab_intern':
                extras[9] = obj.days_weeks;
                extras[10] = obj.natural_class_count * 0.7;
                extras[11] = obj.total_workload
            extras[12] = obj.location.name if obj.location else ''
            ws.append(row + extras)
        style_excel_sheet(ws)
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="Table3_Practice.xlsx"'
        wb.save(response)
        return response


@admin.register(ExperimentWorkload)
class ExperimentWorkloadAdmin(BaseWorkloadAdmin):
    filter_horizontal = ('classes',)
    list_display = ('project_name', 'teacher', 'get_class_names', 'hours', 'total_workload', 'status')
    list_filter = ('status',)
    list_editable = ('hours',)

    # --- 表4 单独导出 ---
    actions = ['export_table_4_experiment']

    @admin.action(description='导出【表4：实验工作量计算表】')
    def export_table_4_experiment(self, request, queryset):
        wb = openpyxl.Workbook();
        ws = wb.active
        ws.title = "实验工作量"
        ws.merge_cells('A1:R1')
        ws['A1'] = f"实验室2025年度实验教学工作量计算表"
        ws['A1'].font = Font(size=16, bold=True);
        ws['A1'].alignment = Alignment(horizontal='center')
        ws.append(['上/下半年', '课程名称', '实验项目', '参加班级', '难度系数K', '批次系数P', '学时数G', '班级数N',
                   '实验当量',
                   '实验室常规T22', '', '', '', '活动补贴T23', '教学工作量', '实验发生地'])
        ws.append(['', '', '', '', '', '', '', '', 'T21=KPGN',
                   '资产数', 'Q1', '人数', 'Q2', '开放补贴', '', 'T0=(T21+T22+T23)*0.8', ''])
        for c in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'O', 'P', 'Q']: ws.merge_cells(f'{c}2:{c}3')
        ws.merge_cells('J2:N2')
        for obj in queryset:
            k = obj.difficulty_rule.value if obj.difficulty_rule else 1.0
            p = {1: 1.3, 2: 2.0, 3: 2.6, 4: 3.0, 5: 3.4}.get(obj.batch_count, 1.3)
            t21 = k * p * obj.hours * obj.class_count
            ws.append([
                obj.term, obj.course_name, obj.project_name, obj.get_class_names(), k, p, obj.hours, obj.class_count,
                round(t21, 2),
                '', '', '', '', '', obj.subsidy, obj.total_workload, obj.location
            ])
        style_excel_sheet(ws)
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="Table4_Experiment.xlsx"'
        wb.save(response)
        return response