from django.urls import path

from . import views

app_name = "aa_recruitment"

urlpatterns = [
    path("", views.index, name="index"),
    path("apply/<slug:slug>/", views.apply_view, name="apply"),
    path(
        "application/<int:application_id>/",
        views.application_detail,
        name="application_detail",
    ),
    path(
        "application/<int:application_id>/withdraw/",
        views.withdraw_application,
        name="withdraw_application",
    ),
    path(
        "application/<int:application_id>/comment/",
        views.add_comment,
        name="add_comment",
    ),
    path(
        "recruiter/queue/",
        views.recruiter_queue,
        name="recruiter_queue",
    ),
    path(
        "recruiter/application/<int:application_id>/",
        views.recruiter_detail,
        name="recruiter_detail",
    ),
    path(
        "recruiter/application/<int:application_id>/status/",
        views.update_status,
        name="update_status",
    ),
    path(
        "recruiter/application/<int:application_id>/vetting/",
        views.trigger_vetting,
        name="trigger_vetting",
    ),
    path(
        "api/queue-stats/",
        views.api_queue_stats,
        name="api_queue_stats",
    ),
]
