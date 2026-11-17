"""Корневые URL Backoffice с административной панелью Django."""

from django.contrib import admin
from django.urls import path

from backoffice_admin.analytics_views import analytics_view
from backoffice_admin.billing_views import billing_view, reconcile_view, refund_view
from backoffice_admin.sso_views import admin_logout, sso_csrf, sso_login
from backoffice_admin.student_class_views import add_student_to_class_view
from backoffice_admin.student_period_views import change_student_class_view
from backoffice_admin.teacher_class_views import (
    search_teachers_view,
    teacher_classes_view,
)
from backoffice_admin.user_views import (
    edit_user_name_view,
    list_users_view,
    search_students_view,
)
from backoffice_admin.views import create_user_view, link_parent_student_view

urlpatterns = [
    path("admin/logout/", admin_logout, name="backoffice-logout"),
    path("admin/sso/csrf/", sso_csrf, name="backoffice-sso-csrf"),
    path("admin/sso/", sso_login, name="backoffice-sso"),
    path(
        "admin/payments/<int:payment_id>/reconcile/",
        admin.site.admin_view(reconcile_view),
        name="backoffice-reconcile",
    ),
    path(
        "admin/payments/<int:payment_id>/refund/",
        admin.site.admin_view(refund_view),
        name="backoffice-refund",
    ),
    path(
        "admin/payments/",
        admin.site.admin_view(billing_view),
        name="backoffice-billing",
    ),
    path(
        "admin/analytics/",
        admin.site.admin_view(analytics_view),
        name="backoffice-analytics",
    ),
    path(
        "admin/teachers/search/",
        admin.site.admin_view(search_teachers_view),
        name="backoffice-search-teachers",
    ),
    path(
        "admin/teacher-classes/",
        admin.site.admin_view(teacher_classes_view),
        name="backoffice-teacher-classes",
    ),
    path(
        "admin/students/<uuid:student_id>/class/",
        admin.site.admin_view(change_student_class_view),
        name="backoffice-change-student-class",
    ),
    path(
        "admin/users/search/",
        admin.site.admin_view(search_students_view),
        name="backoffice-search-students",
    ),
    path(
        "admin/users/",
        admin.site.admin_view(list_users_view),
        name="backoffice-list-users",
    ),
    path(
        "admin/users/<uuid:user_id>/name/",
        admin.site.admin_view(edit_user_name_view),
        name="backoffice-edit-user-name",
    ),
    path(
        "admin/add-student-to-class/",
        admin.site.admin_view(add_student_to_class_view),
        name="backoffice-add-student-to-class",
    ),
    path(
        "admin/create-user/",
        admin.site.admin_view(create_user_view),
        name="backoffice-create-user",
    ),
    path(
        "admin/link-parent-student/",
        admin.site.admin_view(link_parent_student_view),
        name="backoffice-link-parent-student",
    ),
    path("admin/", admin.site.urls),
]
