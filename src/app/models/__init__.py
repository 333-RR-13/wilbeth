from app.models.assignment import Assignment, AssignmentSource, AssignmentTyp
from app.models.department import Department, DepartmentKategorie  # DepartmentKategorie ist jetzt eine DB-Tabelle
from app.models.school_holiday import SchoolHoliday
from app.models.school_plan import SchoolPlan, SchoolPlanWeek, SchoolWeekTyp
from app.models.schoolyear import Schoolyear
from app.models.trainee import Trainee, TraineeRolle
from app.models.trainee_class import TraineeClass, UnterrichtsTyp
from app.models.trainee_class_membership import TraineeClassMembership
from app.models.trainee_wish import TraineeWish

__all__ = [
    "Assignment",
    "AssignmentSource",
    "AssignmentTyp",
    "Department",
    "DepartmentKategorie",
    "SchoolHoliday",
    "SchoolPlan",
    "SchoolPlanWeek",
    "SchoolWeekTyp",
    "Schoolyear",
    "Trainee",
    "TraineeRolle",
    "TraineeClass",
    "TraineeClassMembership",
    "TraineeWish",
    "UnterrichtsTyp",
]
