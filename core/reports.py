"""Shared Excel builders. All official reports include verified records only."""
from django.db.models import Sum
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

from .models import CoefficientSize, ExperimentWorkload, PracticeWorkload, TheoryWorkload


def total(queryset, field='total_workload'):
    return round(queryset.aggregate(value=Sum(field))['value'] or 0, 2)


def sheet(workbook, name, title, headers, rows):
    ws = workbook.create_sheet(name)
    ws.append([title])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    ws.append(headers)
    for row in rows:
        ws.append(row)
    side = Side(style='thin', color='CCCCCC')
    border = Border(left=side, right=side, top=side, bottom=side)
    for row in ws:
        for cell in row:
            # Treat user-provided strings as text, never Excel formulas.
            if isinstance(cell.value, str):
                cell.data_type = 's'
            cell.alignment = Alignment(vertical='center', wrap_text=True)
            cell.border = border
    for cell in ws[2]:
        cell.font = Font(bold=True)
    ws['A1'].font = Font(size=16, bold=True)
    for column in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(column)].width = 18
    ws.freeze_panes = 'A3'
    ws.auto_filter.ref = f'A2:{get_column_letter(len(headers))}{ws.max_row}'
    return ws


def workload_sheet(workbook, kind, queryset, prefix=''):
    queryset = queryset.filter(status='verified').select_related('teacher__college').prefetch_related('classes').order_by('pk')
    if kind in ('theory', 'public'):
        queryset = (queryset.filter(category='public_elective') if kind == 'public'
                    else queryset.exclude(category='public_elective'))
        headers = ['学期', '学院', '课程名称', '课程类别', '教师', '授课班级', '自然班级数', '学生人数',
                   '计划学时', '考核方式', '当前人数系数', '课堂工作量（含准备增量）', '上机学时', '上机工作量', '核算总工作量']
        rows = []
        for obj in queryset:
            lab = round(obj.lab_hours * 0.7 * min(obj.natural_class_count, 4), 2) if obj.has_lab else 0
            rows.append([obj.term, str(obj.teacher.college), obj.course_name, obj.get_category_display(),
                         obj.teacher.name, obj.get_class_names(), obj.natural_class_count, obj.student_count,
                         obj.plan_hours, obj.get_assessment_mode_display(),
                         CoefficientSize.get_k_by_count(obj.category, obj.student_count),
                         round(obj.total_workload - lab, 2), obj.lab_hours if obj.has_lab else 0, lab, obj.total_workload])
        name = '表5-公选课' if kind == 'public' else '表2-课堂教学'
    elif kind == 'practice':
        headers = ['学期', '学院', '教师', '课程名称', '实践类型', '指导班级', '自然班级数', '学生人数',
                   '计划天数/周数/机时', '实习规则', '地点', '核算工作量']
        rows = ([obj.term, str(obj.teacher.college), obj.teacher.name, obj.course_name,
                 obj.get_practice_type_display(), obj.get_class_names(), obj.natural_class_count,
                 obj.student_count, obj.days_weeks, str(obj.internship_rule) if obj.internship_rule else '',
                 str(obj.location) if obj.location else '', obj.total_workload]
                for obj in queryset.select_related('internship_rule', 'location'))
        name = '表3-实践环节'
    else:
        headers = ['学期', '学院', '教师', '课程名称', '实验项目', '参加班级', '当前难度系数K',
                   '批次系数P', '学时数G', '班级数N', '按当前规则计算的实验当量KPGN', '补贴', '核算工作量', '实验发生地']
        rows = []
        for obj in queryset.select_related('difficulty_rule'):
            k = obj.difficulty_rule.value if obj.difficulty_rule else 1.0
            p = dict(((1, 1.3), (2, 2.0), (3, 2.6), (4, 3.0), (5, 3.4))).get(obj.batch_count, 1.3)
            rows.append([obj.term, str(obj.teacher.college), obj.teacher.name, obj.course_name,
                         obj.project_name, obj.get_class_names(), k, p, obj.hours, obj.class_count,
                         round(k * p * obj.hours * obj.class_count, 2), obj.subsidy, obj.total_workload, obj.location])
        name = '表4-实验工作量'
    return sheet(workbook, prefix + name, name + '（已审核；实验公式：KPGN×0.8+补贴）' if kind == 'experiment'
                 else name + '（已审核）', headers, rows)


def response(workbook, filename):
    if not workbook.worksheets:
        sheet(workbook, '无数据', '未选择组织或没有可导出的数据', ['说明'], [])
    result = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    result['Content-Disposition'] = f'attachment; filename="{filename}"'
    workbook.save(result)
    return result


def export_workload(kind, queryset):
    workbook = Workbook()
    workbook.remove(workbook.active)
    workload_sheet(workbook, kind, queryset)
    return response(workbook, f'{kind}_workload.xlsx')


def export_organizations(organizations):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for org in organizations.order_by('pk'):
        prefix = f'{org.pk}-'
        theory = TheoryWorkload.objects.filter(teacher__college=org, status='verified')
        practice = PracticeWorkload.objects.filter(teacher__college=org, status='verified')
        experiment = ExperimentWorkload.objects.filter(teacher__college=org, status='verified')
        # Missing location is treated as on-campus, matching the former default.
        outside = practice.filter(location__is_outside=True)
        inside = practice.exclude(location__is_outside=True)
        thesis = practice.filter(practice_type='thesis')
        theory_total, practice_total, experiment_total = total(theory), total(practice), total(experiment)
        sheet(workbook, prefix + '表1-学院汇总', f'{org.name} 教学工作量汇总（已审核，全部学期）',
              ['学院', '课堂（不含公选课）', '公选课', '校内实践（含未填地点）', '校外实践', '毕业设计（实践子项）',
               '其他实践（实践子项）', '实验教学', '总工作量'],
              [[org.name, total(theory.exclude(category='public_elective')), total(theory.filter(category='public_elective')),
                total(inside), total(outside), total(thesis), total(practice.exclude(practice_type='thesis')),
                experiment_total, round(theory_total + practice_total + experiment_total, 2)]])
        workload_sheet(workbook, 'theory', theory, prefix)
        workload_sheet(workbook, 'practice', practice, prefix)
        workload_sheet(workbook, 'experiment', experiment, prefix)
        workload_sheet(workbook, 'public', theory, prefix)
        rows = []
        for teacher in org.teacher_set.order_by('pk'):
            t, p, e = theory.filter(teacher=teacher), practice.filter(teacher=teacher), experiment.filter(teacher=teacher)
            rows.append([org.name, teacher.card_id, teacher.name, total(t),
                         total(p.filter(practice_type='thesis')), total(p.exclude(practice_type='thesis')),
                         total(e), round(total(t) + total(p) + total(e), 2), total(t, 'plan_hours')])
        sheet(workbook, prefix + '表6-教师汇总', f'{org.name} 教师汇总（已审核，全部学期）',
              ['学院', '一卡通号', '姓名', '课堂（含公选课）', '毕业设计', '其他实践', '实验教学', '总计', '理论计划学时'], rows)
    return response(workbook, 'Final_Report.xlsx')
