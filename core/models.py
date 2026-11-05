from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError


# ==========================================
# (一) 基础信息模块
# ==========================================

class Organization(models.Model):
    name = models.CharField("组织/学院名称", max_length=100)
    is_active = models.BooleanField("是否启用", default=True)

    def __str__(self): return self.name

    class Meta: verbose_name = "组织机构"; verbose_name_plural = verbose_name


class Teacher(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name="关联账号", null=True, blank=True)
    name = models.CharField("教师姓名", max_length=50)
    card_id = models.CharField("一卡通号", max_length=20, unique=True)
    college = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="所属学院")
    title = models.CharField("职称", max_length=50, blank=True)

    def __str__(self): return f"{self.name} ({self.card_id})"

    class Meta: verbose_name = "教师信息"; verbose_name_plural = verbose_name


class Location(models.Model):
    name = models.CharField("地点名称", max_length=50)
    is_outside = models.BooleanField("是否校外", default=False)

    def __str__(self): return self.name

    class Meta: verbose_name = "教学地点库"; verbose_name_plural = verbose_name


class Course(models.Model):
    # 严格对应附件二分类
    COURSE_TYPES = [
        ('public_heavy', '公共基础(作业量大)'),
        ('public_general', '公共基础(一般)'),
        ('major', '专业/专业基础课'),
        ('public_elective', '公共选修课'),
        ('pe', '体育课'),
        ('foreign', '外语课'),
    ]
    name = models.CharField("课程名称", max_length=100)
    category = models.CharField("课程类别", max_length=20, choices=COURSE_TYPES)
    is_core = models.BooleanField("是否核心课程", default=False)
    is_exam = models.BooleanField("是否考试课", default=False)
    is_new = models.BooleanField("是否开新课", default=False)

    def __str__(self): return self.name

    class Meta: verbose_name = "课程库"; verbose_name_plural = verbose_name


class ClassInfo(models.Model):
    name = models.CharField("班级名称", max_length=50)
    major = models.CharField("所属专业", max_length=50)
    student_count = models.IntegerField("学生人数", validators=[MinValueValidator(0)])
    natural_class_count = models.IntegerField("自然班级数", default=1, validators=[MinValueValidator(1)])
    term = models.CharField("学期", max_length=50, default="2024-2025-1")

    def __str__(self): return f"{self.name} ({self.student_count}人)"

    class Meta: verbose_name = "班级信息"; verbose_name_plural = verbose_name


# ==========================================
# (二) 系数规则模块
# ==========================================

class CoefficientSize(models.Model):
    """选课人数系数 (附件二)"""
    category = models.CharField("适用课程类别", max_length=20, choices=Course.COURSE_TYPES)
    min_count = models.IntegerField("最小人数")
    max_count = models.IntegerField("最大人数")
    k_value = models.FloatField("系数")

    class Meta: verbose_name = "1.选课人数系数(附件二)"; verbose_name_plural = verbose_name; ordering = ['min_count']

    def __str__(self): return f"{self.get_category_display()} [{self.min_count}-{self.max_count}人]: {self.k_value}"

    @classmethod
    def get_k_by_count(cls, category, count):
        rule = cls.objects.filter(category=category, min_count__lte=count, max_count__gte=count).first()
        return rule.k_value if rule else 1.0


class CoefficientInternship(models.Model):
    """实习指导系数 (表2)"""
    name = models.CharField("实习类型及地点", max_length=100, help_text="如：生产实习(市内)")
    value = models.FloatField("指导系数")
    # 核心修正：市内/外地 +2 天
    add_days = models.FloatField("额外补贴天数", default=0, help_text="市内/外地实习填2，其他填0")

    class Meta: verbose_name = "2.实习指导系数(表2)"; verbose_name_plural = verbose_name

    def __str__(self): return f"{self.name}: {self.value} (补{self.add_days}天)"


class CoefficientExperiment(models.Model):
    """实验难度系数 (表3)"""
    category = models.CharField("实验课程类型", max_length=50, help_text="如：专业基础课(电类)")
    value = models.FloatField("难度系数K")

    class Meta: verbose_name = "3.实验难度系数(表3)"; verbose_name_plural = verbose_name

    def __str__(self): return f"{self.category}: {self.value}"


# ==========================================
# (三) 核心业务模块 (录入+计算)
# ==========================================

class BaseWorkload(models.Model):
    STATUS_CHOICES = [('pending', '待审核'), ('verified', '已审核'), ('rejected', '驳回')]
    term = models.CharField("学期", max_length=50, default="2024-2025-1")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, verbose_name="教师姓名")
    course_name = models.CharField("课程名称", max_length=100)
    student_count = models.IntegerField("学生人数", validators=[MinValueValidator(0)])
    natural_class_count = models.IntegerField("自然班级数", default=1, validators=[MinValueValidator(1)])
    status = models.CharField("审核状态", max_length=10, choices=STATUS_CHOICES, default='pending')
    total_workload = models.FloatField("核算工作量", default=0.0, editable=False)

    class Meta: abstract = True


# === 1. 课堂教学 ===
class TheoryWorkload(BaseWorkload):
    category = models.CharField("课程类型", max_length=20, choices=Course.COURSE_TYPES)
    # === 这一行必须有！ ===
    classes = models.ManyToManyField(ClassInfo, verbose_name="授课班级", blank=True)

    plan_hours = models.FloatField("计划学时", validators=[MinValueValidator(0)])

    ASSESSMENT_CHOICES = [('exam', '考试'), ('check', '考查')]
    assessment_mode = models.CharField("考核方式", max_length=10, choices=ASSESSMENT_CHOICES, default='exam')

    # 准备工作量
    is_new = models.BooleanField("是否开新课", default=False)
    new_course_proof = models.FileField("开新课凭证", upload_to='proofs/', blank=True, null=True)
    is_bilingual = models.BooleanField("是否双语教学", default=False)

    # 上机
    has_lab = models.BooleanField("是否含上机", default=False)
    lab_hours = models.FloatField("计划上机学时", default=0, validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = "4.课堂与公选课录入"; verbose_name_plural = verbose_name

    def clean(self):
        if self.is_new and not self.new_course_proof:
            raise ValidationError({'new_course_proof': '合规校验：开新课必须上传凭证。'})

    def calculate(self):
        """
                核心计算逻辑：依据《电气学院本科教学工作量计算办法》
                公式模型：P = (计划学时+补贴) × 班级数 × k + 开新课准备工作量
                                                        开新课准备工作量＝计划学时 × 0.5；
                """
        # 1. 获取系数 K (查表)
        k_value = CoefficientSize.get_k_by_count(self.category, self.student_count)

        # 2. 获取计算用班级数 (合班规则：超4按4)
        calc_class_count = 4 if self.natural_class_count > 4 else self.natural_class_count

        # 步骤 3：确定有效计算学时 (对应 图1 注1)
        # 规则：计划学时是指培养计划规定的学时，若为考试课另外加 2 学时
        # 解析：这 2 学时作为出卷/阅卷补贴，应视为基础学时的增量，参与后续 k 值乘法
        effective_hours = self.plan_hours  # 定义有效计算学时
        if self.assessment_mode == 'exam':
            effective_hours += 2.0

        # ---------------------------------------------------------
        # 步骤 4：计算基础课堂工作量 (对应 图1 主公式前半部分)
        # ---------------------------------------------------------
        # 公式：计划学时 × 自然班级数 × k
        result = effective_hours * k_value * calc_class_count

        # 4. 上机工作量 (图2规则1：机时 * 0.7 * 班级)
        # 上机通常单独计算，不享受考试课的+2
        if self.has_lab and self.lab_hours > 0:
            result += self.lab_hours * 0.7 * calc_class_count

        # 5. 准备工作量 (图2规则4：计划学时 * 0.5) 看是否开新课 不开新课
        # 注意：准备工作量通常基于“授课内容”，所以用原始的 plan_hours
        if self.is_new:
            result += self.plan_hours * 0.5
        #判断是否双语教学
        if self.is_bilingual:
            result += self.plan_hours * 0.5

        return round(result, 2)

    def save(self, *args, **kwargs):
        self.total_workload = self.calculate()
        super().save(*args, **kwargs)

# 辅助方法：获取班级名称字符串（给导出用）
    def get_class_names(self):
        return "; ".join([c.name for c in self.classes.all()])
# === 2. 实践教学 ===
class PracticeWorkload(BaseWorkload):
    PRACTICE_TYPES = [
        ('internship', '实习类'),
        ('design', '课程设计'),
        ('thesis', '毕业设计(论文)'),
        ('lab_intern', '上机实习'),
    ]
    practice_type = models.CharField("实践类型", max_length=20, choices=PRACTICE_TYPES)

    # 系数与地点
    internship_rule = models.ForeignKey(CoefficientInternship, on_delete=models.SET_NULL, null=True, blank=True,
                                        verbose_name="实习类型(匹配系数)")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="实习地点")

    # ★★★ 新增：关联具体班级 ★★★
    classes = models.ManyToManyField(ClassInfo, verbose_name="指导班级", blank=True)

    days_weeks = models.FloatField("计划天数/周数", default=0, validators=[MinValueValidator(0)])

    # 毕设系数
    THESIS_CATS = [('science', '理工类(1.3)'), ('arts', '文法经管(1.1)'), ('edu', '教师教育(1.2)')]
    thesis_category = models.CharField("毕设类别", max_length=20, choices=THESIS_CATS, blank=True, null=True)

    # 附件
    lab_card_proof = models.FileField("上机卡扫描件", upload_to='lab_cards/', blank=True, null=True)

    class Meta:
        verbose_name = "5.实践环节录入"; verbose_name_plural = verbose_name

    def clean(self):
        if self.practice_type == 'lab_intern' and not self.lab_card_proof:
            raise ValidationError({'lab_card_proof': '合规校验：上机实习需上传上机卡。'})

    def calculate(self):
        if self.practice_type == 'lab_intern':
            return self.days_weeks * self.natural_class_count * 0.7
        if self.practice_type == 'design':
            return self.days_weeks * self.natural_class_count * 3.3
        if self.practice_type == 'internship' and self.internship_rule:
            real_days = self.days_weeks + self.internship_rule.add_days
            return real_days * self.natural_class_count * self.internship_rule.value
        if self.practice_type == 'thesis':
            coeff_map = {'science': 1.3, 'arts': 1.1, 'edu': 1.2}
            c = coeff_map.get(self.thesis_category, 1.0)
            return self.days_weeks * self.student_count * c
        return 0.0

    def save(self, *args, **kwargs):
        self.total_workload = self.calculate()
        super().save(*args, **kwargs)

    # ★★★ 新增：获取班级名称字符串（用于导出） ★★★
    def get_class_names(self):
        return "; ".join([c.name for c in self.classes.all()])
# === 3. 实验教学 ===
# === 3. 实验教学 ===
class ExperimentWorkload(models.Model):
    term = models.CharField("学期", max_length=50, default="2024-2025-1")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, verbose_name="教师")
    course_name = models.CharField("课程名称", max_length=100)
    project_name = models.CharField("实验项目", max_length=100)

    # ★★★ 新增：关联具体班级 (多选) ★★★
    classes = models.ManyToManyField(ClassInfo, verbose_name="参加实验班级", blank=True)

    location = models.CharField("实验发生地", max_length=50, default="校本部", help_text="必填，例如：校本部、新校区")
    difficulty_rule = models.ForeignKey(CoefficientExperiment, on_delete=models.SET_NULL, null=True,
                                        verbose_name="难度系数K")

    BATCH_CHOICES = [(1, '1批(1.3)'), (2, '2批(2.0)'), (3, '3批(2.6)'), (4, '4批(3.0)'), (5, '5批(3.4)')]
    batch_count = models.IntegerField("批次", choices=BATCH_CHOICES, default=1)

    hours = models.FloatField("学时数")
    class_count = models.IntegerField("班级数")
    subsidy = models.FloatField("补贴金额", default=0.0)

    status = models.CharField("审核状态", max_length=10, choices=BaseWorkload.STATUS_CHOICES, default='pending')
    total_workload = models.FloatField("核算工作量", default=0.0, editable=False)

    class Meta: verbose_name = "6.实验教学录入"; verbose_name_plural = verbose_name

    def calculate(self):
        k = self.difficulty_rule.value if self.difficulty_rule else 1.0
        p_map = {1: 1.3, 2: 2.0, 3: 2.6, 4: 3.0, 5: 3.4}
        p = p_map.get(self.batch_count, 1.3)
        t21 = k * p * self.hours * self.class_count
        return round(t21 * 0.8 + self.subsidy, 2)

    def save(self, *args, **kwargs):
        self.total_workload = self.calculate()
        super().save(*args, **kwargs)

    # ★★★ 新增：获取班级名称字符串 ★★★
    def get_class_names(self):
        return "; ".join([c.name for c in self.classes.all()])