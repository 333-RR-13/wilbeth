from app.models.abwesenheit import Abwesenheit, AbwesenheitQuelle, AbwesenheitTyp
from app.models.assignment import Assignment, AssignmentSource, AssignmentTyp
from app.models.betreuer import Betreuer, BetreuerTrainee
from app.models.department import Department, DepartmentKategorie  # DepartmentKategorie ist jetzt eine DB-Tabelle
from app.models.einsatz_vorschlag import EinsatzVorschlag
from app.models.feedback_bogen import FeedbackBogen
from app.models.school_holiday import SchoolHoliday
from app.models.school_plan import SchoolPlan, SchoolPlanWeek, SchoolWeekTyp
from app.models.schoolyear import Schoolyear
from app.models.trainee import Trainee, TraineeRolle
from app.models.trainee_class import TraineeClass, UnterrichtsTyp
from app.models.trainee_class_membership import TraineeClassMembership
from app.models.trainee_notiz import TraineeNotiz
from app.models.trainee_wish import TraineeWish

__all__ = [
    "Abwesenheit",
    "AbwesenheitQuelle",
    "AbwesenheitTyp",
    "Assignment",
    "AssignmentSource",
    "AssignmentTyp",
    "Betreuer",
    "BetreuerTrainee",
    "Department",
    "DepartmentKategorie",
    "EinsatzVorschlag",
    "FeedbackBogen",
    "SchoolHoliday",
    "SchoolPlan",
    "SchoolPlanWeek",
    "SchoolWeekTyp",
    "Schoolyear",
    "Trainee",
    "TraineeRolle",
    "TraineeClass",
    "TraineeClassMembership",
    "TraineeNotiz",
    "TraineeWish",
    "UnterrichtsTyp",
]
