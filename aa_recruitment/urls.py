from django.urls import path

from . import views

app_name = "aa_recruitment"

urlpatterns = [
    path("", views.index, name="index"),
    # Candidate Portal Routes (Standard User / Applicant)
    path("portal/", views.applicant_portal, name="applicant_portal"),
    path("my-applications/", views.my_applications, name="my_applications"),
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
    # Frontend Configuration Routes
    path(
        "config/forms/",
        views.manage_forms,
        name="manage_forms",
    ),
    path(
        "config/forms/create/",
        views.form_create,
        name="form_create",
    ),
    path(
        "config/forms/<int:form_id>/edit/",
        views.form_edit,
        name="form_edit",
    ),
    path(
        "config/forms/<int:form_id>/toggle/",
        views.form_toggle_active,
        name="form_toggle_active",
    ),
    path(
        "config/forms/<int:form_id>/delete/",
        views.form_delete,
        name="form_delete",
    ),
    path(
        "config/forms/<int:form_id>/questions/",
        views.manage_questions,
        name="manage_questions",
    ),
    path(
        "config/forms/<int:form_id>/questions/create/",
        views.question_create,
        name="question_create",
    ),
    path(
        "config/forms/<int:form_id>/questions/<int:question_id>/edit/",
        views.question_edit,
        name="question_edit",
    ),
    path(
        "config/forms/<int:form_id>/questions/<int:question_id>/delete/",
        views.question_delete,
        name="question_delete",
    ),
    # Discord Intel Channels Routes
    path(
        "config/discord-channels/create/",
        views.discord_channel_create,
        name="discord_channel_create",
    ),
    path(
        "config/discord-channels/<int:channel_id>/edit/",
        views.discord_channel_edit,
        name="discord_channel_edit",
    ),
    path(
        "config/discord-channels/<int:channel_id>/delete/",
        views.discord_channel_delete,
        name="discord_channel_delete",
    ),
    path(
        "config/discord-channels/<int:channel_id>/sync/",
        views.discord_channel_sync_now,
        name="discord_channel_sync_now",
    ),
    path(
        "config/discord-channels/<int:channel_id>/backfill/",
        views.discord_channel_backfill,
        name="discord_channel_backfill",
    ),
    # Corp Trends & Activity Tracker Routes
    path(
        "trends/",
        views.corp_trends,
        name="corp_trends",
    ),
    path(
        "trends/<int:corp_id>/",
        views.corp_trends,
        name="corp_trends",
    ),
    path(
        "trends/<int:corp_id>/sync/",
        views.corp_trends_sync,
        name="corp_trends_sync",
    ),
    path(
        "api/corp-search/",
        views.api_corp_search,
        name="api_corp_search",
    ),
]
