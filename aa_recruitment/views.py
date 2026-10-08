import json
from typing import Any, Dict, List, Optional

from allianceauth.eveonline.models import EveCorporationInfo
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import app_settings
from .forms import (
    ApplicationFormConfigForm,
    ApplicationSubmissionForm,
    CommentForm,
    DiscordIntelChannelForm,
    QuestionConfigForm,
    RecruitmentSettingsForm,
    StatusUpdateForm,
)
from .models import (
    Application,
    ApplicationAnswer,
    ApplicationComment,
    ApplicationForm,
    ApplicationLog,
    ApplicationStatus,
    CorpActivitySnapshot,
    CorpCombatStats,
    CorpMemberActivity,
    DiscordIntelChannel,
    MemberActivityStatus,
    Question,
    RecruitmentConfig,
)
from .services.corp_trends import CorpTrendsService
from .services.discord_intel import (
    backfill_channel_history,
    fetch_and_store_channel_messages,
)
from .tasks import (
    notify_applicant_in_app,
    run_applicant_vetting,
    send_recruitment_discord_notification,
)
from .vetting.discord_intel import DiscordIntelAnalyzer
from .vetting.evewho import EveWhoAnalyzer
from .vetting.zkill import ZKillAnalyzer, build_activity_heatmap


@login_required
@permission_required("aa_recruitment.basic_access", raise_exception=True)
def index(request: HttpRequest) -> HttpResponse:
    """Root router directing user to Recruiter Desk or Applicant Portal based on role."""
    if request.user.has_perm("aa_recruitment.manage_recruitment"):
        return redirect("aa_recruitment:recruiter_queue")
    return redirect("aa_recruitment:applicant_portal")


@login_required
@permission_required("aa_recruitment.basic_access", raise_exception=True)
def applicant_portal(request: HttpRequest) -> HttpResponse:
    """Dedicated candidate portal showing open forms and application status."""
    active_forms = ApplicationForm.objects.filter(is_active=True).select_related("corporation")
    user_applications = (
        Application.objects.filter(user=request.user).select_related("form", "reviewer").order_by("-created_at")
    )
    config = RecruitmentConfig.get_solo()
    portal_title = (
        config.portal_menu_title or app_settings.AA_RECRUITMENT_APPLY_MENU_NAME or _("Corporation Applications")
    )
    context = {
        "title": portal_title,
        "active_forms": active_forms,
        "user_applications": user_applications,
    }
    return render(request, "aa_recruitment/portal.html", context)


@login_required
@permission_required("aa_recruitment.basic_access", raise_exception=True)
def my_applications(request: HttpRequest) -> HttpResponse:
    """Dedicated view for candidates to track all their submitted applications."""
    user_applications = (
        Application.objects.filter(user=request.user).select_related("form", "reviewer").order_by("-created_at")
    )
    context = {
        "title": _("My Applications"),
        "user_applications": user_applications,
    }
    return render(request, "aa_recruitment/my_applications.html", context)


@login_required
@permission_required("aa_recruitment.basic_access", raise_exception=True)
def apply_view(request: HttpRequest, slug: str) -> HttpResponse:
    """Apply view for a specific application form."""
    form_instance = get_object_or_404(ApplicationForm, slug=slug, is_active=True)
    config = RecruitmentConfig.get_solo()

    # Verify if multiple applications are permitted
    if not config.allow_multiple_active:
        existing = Application.objects.filter(
            user=request.user,
            form=form_instance,
            status__in=[ApplicationStatus.PENDING, ApplicationStatus.IN_PROGRESS],
        ).first()
        if existing:
            messages.warning(
                request,
                _("You already have an open application (#%(app_id)s) for %(form_title)s.")
                % {"app_id": existing.pk, "form_title": form_instance.title},
            )
            return redirect("aa_recruitment:application_detail", application_id=existing.pk)

    if request.method == "POST":
        form = ApplicationSubmissionForm(request.POST, application_form=form_instance)
        if form.is_valid():
            # Determine main character name from Auth profile if available
            profile = getattr(request.user, "profile", None)
            main_char = getattr(profile, "main_character", None) if profile else None
            main_char_name = main_char.character_name if main_char else request.user.username

            app = Application.objects.create(
                form=form_instance,
                user=request.user,
                main_character_name=main_char_name,
                status=ApplicationStatus.PENDING,
            )

            # Save answers
            questions = form_instance.questions.all()
            for q in questions:
                field_key = f"question_{q.id}"
                raw_answer = form.cleaned_data.get(field_key)
                answer_str = str(raw_answer) if raw_answer is not None else ""
                ApplicationAnswer.objects.create(
                    application=app,
                    question=q,
                    answer_text=answer_str,
                )

            # Audit log
            ApplicationLog.objects.create(
                application=app,
                actor=request.user,
                action=_("Application submitted by applicant"),
            )

            # Trigger background notifications and automated security vetting
            send_recruitment_discord_notification.delay(app.id, event_type="new_application")
            run_applicant_vetting.delay(app.id)

            messages.success(
                request,
                _("Your application for '%(title)s' has been submitted successfully!") % {"title": form_instance.title},
            )
            return redirect("aa_recruitment:application_detail", application_id=app.pk)
    else:
        form = ApplicationSubmissionForm(application_form=form_instance)

    context = {
        "title": _("Apply: %(title)s") % {"title": form_instance.title},
        "application_form": form_instance,
        "form": form,
    }
    return render(request, "aa_recruitment/apply.html", context)


@login_required
@permission_required("aa_recruitment.basic_access", raise_exception=True)
def application_detail(request: HttpRequest, application_id: int) -> HttpResponse:
    """Applicant's view of their own submitted application."""
    application = get_object_or_404(
        Application.objects.select_related("form", "user", "reviewer"),
        pk=application_id,
    )

    # Security check: must be owner or have recruiter permissions
    is_recruiter = request.user.has_perm("aa_recruitment.manage_recruitment")
    if application.user != request.user and not is_recruiter:
        raise PermissionDenied(_("No permission to view this application."))

    answers = application.answers.select_related("question").order_by("question__order", "question__id")

    # Applicants only see public comments; recruiters see all comments
    if is_recruiter:
        comments = application.comments.select_related("author").order_by("created_at")
    else:
        comments = application.comments.filter(is_internal=False).select_related("author").order_by("created_at")

    comment_form = CommentForm()

    context = {
        "title": _("Application #%(pk)s - %(title)s") % {"pk": application.pk, "title": application.form.title},
        "application": application,
        "answers": answers,
        "comments": comments,
        "comment_form": comment_form,
        "is_recruiter": is_recruiter,
    }
    return render(request, "aa_recruitment/application_detail.html", context)


@login_required
@permission_required("aa_recruitment.manage_recruitment", raise_exception=True)
def recruiter_queue(request: HttpRequest) -> HttpResponse:
    """Recruitment officer review queue with filters."""
    applications = Application.objects.select_related("form", "user", "reviewer").order_by("-created_at")

    status_filter = request.GET.get("status")
    form_filter = request.GET.get("form_id")
    search_query = request.GET.get("q", "").strip()

    if status_filter:
        applications = applications.filter(status=status_filter)
    else:
        # Default to open applications (pending and in_progress)
        applications = applications.filter(status__in=[ApplicationStatus.PENDING, ApplicationStatus.IN_PROGRESS])

    if form_filter:
        applications = applications.filter(form_id=form_filter)

    if search_query:
        applications = applications.filter(user__username__icontains=search_query) | applications.filter(
            main_character_name__icontains=search_query
        )

    active_forms = ApplicationForm.objects.all().order_by("title")

    context = {
        "title": _("Recruitment Review Queue"),
        "applications": applications,
        "status_filter": status_filter or "open",
        "form_filter": (int(form_filter) if form_filter and form_filter.isdigit() else None),
        "search_query": search_query,
        "active_forms": active_forms,
        "status_choices": ApplicationStatus.choices,
    }
    return render(request, "aa_recruitment/recruiter_queue.html", context)


@login_required
@permission_required("aa_recruitment.manage_recruitment", raise_exception=True)
def recruiter_detail(request: HttpRequest, application_id: int) -> HttpResponse:
    """Detailed recruiter dossier with applicant overview, answers, notes and actions."""
    application = get_object_or_404(
        Application.objects.select_related("form", "user", "reviewer"),
        pk=application_id,
    )

    answers = application.answers.select_related("question").order_by("question__order", "question__id")
    comments = application.comments.select_related("author").order_by("created_at")
    logs = application.logs.select_related("actor").order_by("-created_at")

    # Linked EVE characters from Alliance Auth
    characters = []
    ownerships = getattr(application.user, "character_ownerships", None)
    if ownerships:
        characters = ownerships.select_related("character").all()

    status_form = StatusUpdateForm(initial={"status": application.status, "reviewer": application.reviewer})
    comment_form = CommentForm()

    vetting_report = getattr(application, "vetting_report", None)
    vetting_findings = vetting_report.findings.all() if vetting_report else []
    zkill_data = getattr(vetting_report, "zkill_data", {}) if vetting_report else {}

    # Activity Heatmap Matrix
    heatmap = None
    activity_dict = zkill_data.get("activity") if zkill_data else None
    if activity_dict:
        heatmap = build_activity_heatmap(activity_dict)
    elif not zkill_data:
        profile = getattr(application.user, "profile", None)
        main_char = getattr(profile, "main_character", None) if profile else None
        main_char_id = getattr(main_char, "character_id", None) if main_char else None
        if main_char_id:
            try:
                zk = ZKillAnalyzer(main_char_id)
                zk_stats = zk.fetch_stats()
                if zk_stats and "activity" in zk_stats:
                    zkill_data = zk.get_summary_dict()
                    heatmap = build_activity_heatmap(zk_stats.get("activity"))
                    if vetting_report:
                        vetting_report.zkill_data = zkill_data
                        vetting_report.save(update_fields=["zkill_data"])
            except Exception:
                pass

    # Corporation History (EVEWho)
    corp_history = getattr(vetting_report, "corp_history", []) if vetting_report else []
    if not corp_history:
        profile = getattr(application.user, "profile", None)
        main_char = getattr(profile, "main_character", None) if profile else None
        main_char_id = getattr(main_char, "character_id", None) if main_char else None
        if main_char_id:
            try:
                ew = EveWhoAnalyzer(main_char_id)
                corp_history = ew.get_history_list()
                if vetting_report and corp_history:
                    vetting_report.corp_history = corp_history
                    vetting_report.save(update_fields=["corp_history"])
            except Exception:
                pass

    # Discord Intel Matches for Candidate & Known Alts
    known_char_names = []
    if application.main_character_name:
        known_char_names.append(application.main_character_name)

    profile = getattr(application.user, "profile", None)
    main_char = getattr(profile, "main_character", None) if profile else None
    if main_char and main_char.character_name:
        known_char_names.append(main_char.character_name)

    if characters:
        for co in characters:
            if getattr(co, "character", None) and co.character.character_name:
                known_char_names.append(co.character.character_name)

    known_char_names = list(dict.fromkeys(known_char_names))
    discord_analyzer = DiscordIntelAnalyzer(known_char_names)
    discord_matches = discord_analyzer.get_detailed_matches()

    context = {
        "title": _("Candidate Dossier #%(pk)s: %(username)s")
        % {"pk": application.pk, "username": application.user.username},
        "application": application,
        "answers": answers,
        "comments": comments,
        "logs": logs,
        "characters": characters,
        "status_form": status_form,
        "comment_form": comment_form,
        "status_choices": ApplicationStatus.choices,
        "vetting_report": vetting_report,
        "vetting_findings": vetting_findings,
        "zkill_data": zkill_data,
        "heatmap": heatmap,
        "corp_history": corp_history,
        "discord_matches": discord_matches,
    }
    return render(request, "aa_recruitment/recruiter_detail.html", context)


@login_required
@permission_required("aa_recruitment.manage_recruitment", raise_exception=True)
def trigger_vetting(request: HttpRequest, application_id: int) -> HttpResponse:
    """Manually re-run automated security vetting audit."""
    application = get_object_or_404(Application, pk=application_id)
    run_applicant_vetting.delay(application.id)
    messages.info(
        request,
        _("Security vetting audit queued for Application #%(pk)s. Refresh shortly to see updated findings.")
        % {"pk": application.pk},
    )
    return redirect("aa_recruitment:recruiter_detail", application_id=application.pk)


@login_required
@permission_required("aa_recruitment.manage_recruitment", raise_exception=True)
@require_POST
def update_status(request: HttpRequest, application_id: int) -> HttpResponse:
    """Update application review status and reviewer assignment."""
    application = get_object_or_404(Application, pk=application_id)
    form = StatusUpdateForm(request.POST)

    if form.is_valid():
        old_status = application.get_status_display()
        new_status = form.cleaned_data["status"]
        reviewer = form.cleaned_data["reviewer"]
        note = form.cleaned_data["note"]

        application.status = new_status
        application.reviewer = reviewer
        application.save(update_fields=["status", "reviewer", "updated_at"])

        log_msg = _("Status changed from '%(old)s' to '%(new)s'") % {
            "old": old_status,
            "new": application.get_status_display(),
        }
        if note:
            log_msg += f" ({_('Note')}: {note})"
        ApplicationLog.objects.create(
            application=application,
            actor=request.user,
            action=log_msg,
        )

        config = RecruitmentConfig.get_solo()
        if config.notify_on_status_change:
            notify_applicant_in_app.delay(
                application.id,
                title=_("Application Status Update"),
                message=_("The status of your application for %(title)s has been updated to '%(status)s'.")
                % {
                    "title": application.form.title,
                    "status": application.get_status_display(),
                },
                level="info",
            )

        send_recruitment_discord_notification.delay(
            application.id,
            event_type="status_update",
            actor_username=request.user.username,
            note=note,
        )

        messages.success(
            request,
            _("Application #%(pk)s successfully updated to '%(status)s'.")
            % {"pk": application.pk, "status": application.get_status_display()},
        )

    return redirect("aa_recruitment:recruiter_detail", application_id=application.pk)


@login_required
@permission_required("aa_recruitment.basic_access", raise_exception=True)
@require_POST
def add_comment(request: HttpRequest, application_id: int) -> HttpResponse:
    """Add a recruiter note or applicant response."""
    application = get_object_or_404(Application, pk=application_id)
    is_recruiter = request.user.has_perm("aa_recruitment.manage_recruitment")

    # Ensure applicant only comments on own application
    if application.user != request.user and not is_recruiter:
        raise PermissionDenied(_("No permission to comment."))

    form = CommentForm(request.POST)
    if form.is_valid():
        comment_text = form.cleaned_data["comment"]
        # Applicants can NEVER make internal recruiter notes
        is_internal = form.cleaned_data["is_internal"] if is_recruiter else False

        ApplicationComment.objects.create(
            application=application,
            author=request.user,
            comment=comment_text,
            is_internal=is_internal,
        )

        tag = _("Internal note") if is_internal else _("Public comment")
        ApplicationLog.objects.create(
            application=application,
            actor=request.user,
            action=_("%(tag)s added by %(user)s") % {"tag": tag, "user": request.user.username},
        )

        # Notify other party if public comment
        if not is_internal:
            if request.user == application.user and application.reviewer:
                notify_applicant_in_app.delay(
                    application.id,
                    title=_("New message from applicant"),
                    message=_("%(user)s replied on application #%(pk)s.")
                    % {"user": request.user.username, "pk": application.pk},
                    level="info",
                )
            elif is_recruiter:
                notify_applicant_in_app.delay(
                    application.id,
                    title=_("New message from Recruitment"),
                    message=_("A new comment has been posted on your application #%(pk)s.") % {"pk": application.pk},
                    level="info",
                )

        messages.success(request, _("Comment saved successfully."))

    if is_recruiter:
        return redirect("aa_recruitment:recruiter_detail", application_id=application.pk)
    return redirect("aa_recruitment:application_detail", application_id=application.pk)


@login_required
@permission_required("aa_recruitment.basic_access", raise_exception=True)
@require_POST
def withdraw_application(request: HttpRequest, application_id: int) -> HttpResponse:
    """Withdraw an active application."""
    application = get_object_or_404(Application, pk=application_id, user=request.user)

    if application.status in [ApplicationStatus.PENDING, ApplicationStatus.IN_PROGRESS]:
        application.status = ApplicationStatus.WITHDRAWN
        application.save(update_fields=["status", "updated_at"])

        ApplicationLog.objects.create(
            application=application,
            actor=request.user,
            action=_("Application withdrawn by applicant"),
        )

        send_recruitment_discord_notification.delay(
            application.id,
            event_type="status_update",
            actor_username=request.user.username,
            note=_("Application withdrawn by applicant."),
        )

        messages.info(
            request,
            _("Application #%(pk)s has been successfully withdrawn.") % {"pk": application.pk},
        )

    return redirect("aa_recruitment:index")


@login_required
@permission_required("aa_recruitment.manage_recruitment", raise_exception=True)
def api_queue_stats(request: HttpRequest) -> JsonResponse:
    """JSON API returning queue counts for widgets or bots."""
    pending = Application.objects.filter(status=ApplicationStatus.PENDING).count()
    in_progress = Application.objects.filter(status=ApplicationStatus.IN_PROGRESS).count()
    return JsonResponse(
        {
            "status": "success",
            "pending": pending,
            "in_progress": in_progress,
            "total_open": pending + in_progress,
        }
    )


# -----------------------------------------------------------------------------
# Frontend Configuration Views (Forms & Questionnaire Questions)
# -----------------------------------------------------------------------------


@login_required
def manage_forms(request: HttpRequest) -> HttpResponse:
    """Dashboard to manage recruitment application forms and portal settings from the frontend."""
    if not (
        request.user.has_perm("aa_recruitment.admin_recruitment")
        or request.user.has_perm("aa_recruitment.manage_recruitment")
    ):
        raise PermissionDenied

    config = RecruitmentConfig.get_solo()

    if request.method == "POST" and "save_discord_token" in request.POST:
        if not request.user.has_perm("aa_recruitment.admin_recruitment"):
            raise PermissionDenied
        new_token = request.POST.get("global_discord_user_token", "").strip()
        config.discord_user_token = new_token
        config.save()
        messages.success(request, _("Global Discord user token saved successfully!"))
        return redirect(f"{reverse('aa_recruitment:manage_forms')}?tab=discord")

    if request.method == "POST" and "save_settings" in request.POST:
        if not request.user.has_perm("aa_recruitment.admin_recruitment"):
            raise PermissionDenied
        settings_form = RecruitmentSettingsForm(request.POST, instance=config)
        if settings_form.is_valid():
            settings_form.save()
            messages.success(
                request,
                _("Recruitment portal and menu settings saved successfully!"),
            )
            return redirect(f"{reverse('aa_recruitment:manage_forms')}?tab=settings")
    else:
        settings_form = RecruitmentSettingsForm(instance=config)

    forms = (
        ApplicationForm.objects.all()
        .annotate(
            num_questions=Count("questions", distinct=True),
            num_applications=Count("applications", distinct=True),
        )
        .select_related("corporation", "reviewers_group")
        .order_by("-is_active", "title")
    )
    discord_channels = DiscordIntelChannel.objects.all().order_by("name")
    context = {
        "title": _("Recruitment Forms & Settings"),
        "forms": forms,
        "settings_form": settings_form,
        "config": config,
        "discord_channels": discord_channels,
    }
    return render(request, "aa_recruitment/manage_forms.html", context)


@login_required
def form_create(request: HttpRequest) -> HttpResponse:
    """Create a new recruitment application form from the frontend."""
    if not (
        request.user.has_perm("aa_recruitment.admin_recruitment")
        or request.user.has_perm("aa_recruitment.manage_recruitment")
    ):
        raise PermissionDenied

    if request.method == "POST":
        form = ApplicationFormConfigForm(request.POST)
        if form.is_valid():
            app_form = form.save()
            messages.success(
                request,
                _("Application form '%(title)s' created successfully! You can now configure questionnaire questions.")
                % {"title": app_form.title},
            )
            return redirect("aa_recruitment:manage_questions", form_id=app_form.pk)
    else:
        form = ApplicationFormConfigForm()

    context = {
        "title": _("Create New Application Form"),
        "form": form,
        "is_create": True,
    }
    return render(request, "aa_recruitment/form_edit.html", context)


@login_required
def form_edit(request: HttpRequest, form_id: int) -> HttpResponse:
    """Edit an existing recruitment application form from the frontend."""
    if not (
        request.user.has_perm("aa_recruitment.admin_recruitment")
        or request.user.has_perm("aa_recruitment.manage_recruitment")
    ):
        raise PermissionDenied

    app_form = get_object_or_404(ApplicationForm, pk=form_id)

    if request.method == "POST":
        form = ApplicationFormConfigForm(request.POST, instance=app_form)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                _("Application form '%(title)s' has been updated.") % {"title": app_form.title},
            )
            return redirect("aa_recruitment:manage_forms")
    else:
        form = ApplicationFormConfigForm(instance=app_form)

    context = {
        "title": _("Edit Form: %(title)s") % {"title": app_form.title},
        "form": form,
        "app_form": app_form,
        "is_create": False,
    }
    return render(request, "aa_recruitment/form_edit.html", context)


@login_required
@require_POST
def form_toggle_active(request: HttpRequest, form_id: int) -> HttpResponse:
    """Toggle a form between active (open) and inactive (closed) with one click."""
    if not (
        request.user.has_perm("aa_recruitment.admin_recruitment")
        or request.user.has_perm("aa_recruitment.manage_recruitment")
    ):
        raise PermissionDenied

    app_form = get_object_or_404(ApplicationForm, pk=form_id)
    app_form.is_active = not app_form.is_active
    app_form.save(update_fields=["is_active", "updated_at"])

    status_str = _("activated (open)") if app_form.is_active else _("deactivated (closed)")
    messages.info(
        request,
        _("Application form '%(title)s' has been %(status)s.") % {"title": app_form.title, "status": status_str},
    )
    return redirect("aa_recruitment:manage_forms")


@login_required
@require_POST
def form_delete(request: HttpRequest, form_id: int) -> HttpResponse:
    """Delete a form (only permitted if no submitted applications exist)."""
    if not (
        request.user.has_perm("aa_recruitment.admin_recruitment")
        or request.user.has_perm("aa_recruitment.manage_recruitment")
    ):
        raise PermissionDenied

    app_form = get_object_or_404(ApplicationForm, pk=form_id)
    if app_form.applications.exists():
        messages.error(
            request,
            _(
                "Cannot delete form '%(title)s' because candidate applications have already been submitted for it. Deactivate it instead to close it."
            )
            % {"title": app_form.title},
        )
    else:
        app_form.delete()
        messages.success(
            request,
            _("Application form '%(title)s' has been deleted.") % {"title": app_form.title},
        )
    return redirect("aa_recruitment:manage_forms")


@login_required
def manage_questions(request: HttpRequest, form_id: int) -> HttpResponse:
    """Manage the questionnaire questions for a specific application form."""
    if not (
        request.user.has_perm("aa_recruitment.admin_recruitment")
        or request.user.has_perm("aa_recruitment.manage_recruitment")
    ):
        raise PermissionDenied

    app_form = get_object_or_404(ApplicationForm, pk=form_id)
    questions = app_form.questions.all().order_by("order", "id")

    context = {
        "title": _("Questionnaire: %(title)s") % {"title": app_form.title},
        "app_form": app_form,
        "questions": questions,
    }
    return render(request, "aa_recruitment/manage_questions.html", context)


@login_required
def question_create(request: HttpRequest, form_id: int) -> HttpResponse:
    """Add a new question to a form's questionnaire."""
    if not (
        request.user.has_perm("aa_recruitment.admin_recruitment")
        or request.user.has_perm("aa_recruitment.manage_recruitment")
    ):
        raise PermissionDenied

    app_form = get_object_or_404(ApplicationForm, pk=form_id)

    if request.method == "POST":
        form = QuestionConfigForm(request.POST)
        if form.is_valid():
            question = form.save(commit=False)
            question.form = app_form
            question.save()
            messages.success(request, _("Question added successfully."))
            return redirect("aa_recruitment:manage_questions", form_id=app_form.pk)
    else:
        next_order = (app_form.questions.order_by("-order").values_list("order", flat=True).first() or 0) + 1
        form = QuestionConfigForm(initial={"order": next_order, "is_required": True})

    context = {
        "title": _("Add Question &mdash; %(title)s") % {"title": app_form.title},
        "app_form": app_form,
        "form": form,
        "is_create": True,
    }
    return render(request, "aa_recruitment/question_edit.html", context)


@login_required
def question_edit(request: HttpRequest, form_id: int, question_id: int) -> HttpResponse:
    """Edit an existing question on a form's questionnaire."""
    if not (
        request.user.has_perm("aa_recruitment.admin_recruitment")
        or request.user.has_perm("aa_recruitment.manage_recruitment")
    ):
        raise PermissionDenied

    app_form = get_object_or_404(ApplicationForm, pk=form_id)
    question = get_object_or_404(Question, pk=question_id, form=app_form)

    if request.method == "POST":
        form = QuestionConfigForm(request.POST, instance=question)
        if form.is_valid():
            form.save()
            messages.success(request, _("Question updated successfully."))
            return redirect("aa_recruitment:manage_questions", form_id=app_form.pk)
    else:
        form = QuestionConfigForm(instance=question)

    context = {
        "title": _("Edit Question &mdash; %(title)s") % {"title": app_form.title},
        "app_form": app_form,
        "question": question,
        "form": form,
        "is_create": False,
    }
    return render(request, "aa_recruitment/question_edit.html", context)


@login_required
@require_POST
def question_delete(request: HttpRequest, form_id: int, question_id: int) -> HttpResponse:
    """Delete a question from a questionnaire."""
    if not (
        request.user.has_perm("aa_recruitment.admin_recruitment")
        or request.user.has_perm("aa_recruitment.manage_recruitment")
    ):
        raise PermissionDenied

    app_form = get_object_or_404(ApplicationForm, pk=form_id)
    question = get_object_or_404(Question, pk=question_id, form=app_form)
    question.delete()
    messages.success(request, _("Question deleted successfully."))
    return redirect("aa_recruitment:manage_questions", form_id=app_form.pk)


@login_required
def discord_channel_create(request: HttpRequest) -> HttpResponse:
    """Add a new monitored Discord channel."""
    if not request.user.has_perm("aa_recruitment.admin_recruitment"):
        raise PermissionDenied

    if request.method == "POST":
        form = DiscordIntelChannelForm(request.POST)
        if form.is_valid():
            ch = form.save()
            messages.success(
                request,
                _("Discord intel channel '#%(name)s' added successfully!") % {"name": ch.name},
            )
            return redirect(f"{reverse('aa_recruitment:manage_forms')}?tab=discord")
    else:
        form = DiscordIntelChannelForm()

    context = {
        "title": _("Add Monitored Discord Channel"),
        "form": form,
        "is_create": True,
    }
    return render(request, "aa_recruitment/discord_channel_edit.html", context)


@login_required
def discord_channel_edit(request: HttpRequest, channel_id: int) -> HttpResponse:
    """Edit an existing monitored Discord channel."""
    if not request.user.has_perm("aa_recruitment.admin_recruitment"):
        raise PermissionDenied

    channel = get_object_or_404(DiscordIntelChannel, pk=channel_id)

    if request.method == "POST":
        form = DiscordIntelChannelForm(request.POST, instance=channel)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                _("Discord intel channel '#%(name)s' updated successfully!") % {"name": channel.name},
            )
            return redirect(f"{reverse('aa_recruitment:manage_forms')}?tab=discord")
    else:
        form = DiscordIntelChannelForm(instance=channel)

    context = {
        "title": _("Edit Discord Channel: #%(name)s") % {"name": channel.name},
        "form": form,
        "channel": channel,
        "is_create": False,
    }
    return render(request, "aa_recruitment/discord_channel_edit.html", context)


@login_required
@require_POST
def discord_channel_delete(request: HttpRequest, channel_id: int) -> HttpResponse:
    """Delete a monitored Discord channel and its archived messages."""
    if not request.user.has_perm("aa_recruitment.admin_recruitment"):
        raise PermissionDenied

    channel = get_object_or_404(DiscordIntelChannel, pk=channel_id)
    name = channel.name
    channel.delete()
    messages.warning(
        request,
        _("Discord intel channel '#%(name)s' and its archived messages have been removed.") % {"name": name},
    )
    return redirect(f"{reverse('aa_recruitment:manage_forms')}?tab=discord")


@login_required
@require_POST
def discord_channel_sync_now(request: HttpRequest, channel_id: int) -> HttpResponse:
    """Immediately trigger synchronization for a monitored Discord channel."""
    if not (
        request.user.has_perm("aa_recruitment.admin_recruitment")
        or request.user.has_perm("aa_recruitment.manage_recruitment")
    ):
        raise PermissionDenied

    channel = get_object_or_404(DiscordIntelChannel, pk=channel_id)
    count, err = fetch_and_store_channel_messages(channel)
    if err:
        messages.error(
            request,
            _("Failed to sync Discord channel '#%(name)s': %(err)s") % {"name": channel.name, "err": err},
        )
    else:
        messages.success(
            request,
            _(
                "Successfully synchronized Discord channel '#%(name)s'! %(count)d new message(s) stored "
                "(Total archived: %(total)d)."
            )
            % {"name": channel.name, "count": count, "total": channel.total_messages_stored},
        )
    return redirect(f"{reverse('aa_recruitment:manage_forms')}?tab=discord")


@login_required
@require_POST
def discord_channel_backfill(request: HttpRequest, channel_id: int) -> HttpResponse:
    """Trigger on-demand historical message backfill backwards in time."""
    if not (
        request.user.has_perm("aa_recruitment.admin_recruitment")
        or request.user.has_perm("aa_recruitment.manage_recruitment")
    ):
        raise PermissionDenied

    channel = get_object_or_404(DiscordIntelChannel, pk=channel_id)
    try:
        max_messages = int(request.POST.get("max_messages", 1000))
    except (ValueError, TypeError):
        max_messages = 1000

    max_messages = max(100, min(max_messages, 10000))

    count, err = backfill_channel_history(channel, max_messages=max_messages)
    if err:
        messages.error(
            request,
            _("Error during historical backfill for '#%(name)s': %(err)s") % {"name": channel.name, "err": err},
        )
    else:
        messages.success(
            request,
            _(
                "Historical backfill complete for '#%(name)s': %(count)d older message(s) archived! "
                "Total archive size: %(total)d messages."
            )
            % {
                "name": channel.name,
                "count": count,
                "total": channel.total_messages_stored,
            },
        )
    return redirect(f"{reverse('aa_recruitment:manage_forms')}?tab=discord")


@login_required
@permission_required("aa_recruitment.manage_recruitment")
def corp_trends(request: HttpRequest, corp_id: Optional[int] = None) -> HttpResponse:
    """Corporation combat trends, monthly activity graphs, and member participation tracker."""
    auth_corps = EveCorporationInfo.objects.all().order_by("corporation_name")
    monitored_corps = CorpCombatStats.objects.filter(is_auth_corp=False).order_by("corporation_name")

    # Determine targeted corporation ID
    target_corp_id = corp_id or request.GET.get("corp_id")
    if target_corp_id:
        try:
            target_corp_id = int(target_corp_id)
        except (ValueError, TypeError):
            target_corp_id = None

    if not target_corp_id:
        # Default to user's main character corporation if it is an auth corp
        try:
            profile = getattr(request.user, "profile", None)
            if profile and profile.main_character and profile.main_character.corporation_id:
                user_corp_id = profile.main_character.corporation_id
                if auth_corps.filter(corporation_id=user_corp_id).exists():
                    target_corp_id = user_corp_id
        except Exception:
            pass

    if not target_corp_id:
        first_auth = auth_corps.first()
        if first_auth:
            target_corp_id = first_auth.corporation_id
        elif monitored_corps.exists():
            target_corp_id = monitored_corps.first().corporation_id

    stats: Optional[CorpCombatStats] = None
    snapshots: List[CorpActivitySnapshot] = []
    members: List[CorpMemberActivity] = []
    monthly_table: List[Dict[str, Any]] = []
    chart_data: Dict[str, Any] = {}
    members_data: List[Dict[str, Any]] = []

    summary = {
        "total_members": 0,
        "active_count": 0,
        "low_count": 0,
        "inactive_count": 0,
        "dormant_count": 0,
        "active_pct": 0,
        "kills_30d": 0,
        "losses_30d": 0,
        "isk_destroyed_30d": 0,
        "isk_lost_30d": 0,
        "kills_90d": 0,
        "losses_90d": 0,
        "isk_destroyed_90d": 0,
        "isk_lost_90d": 0,
    }

    if target_corp_id:
        stats = CorpCombatStats.objects.filter(corporation_id=target_corp_id).first()
        if not stats:
            try:
                stats = CorpTrendsService().sync_corporation(target_corp_id)
            except Exception as exc:
                messages.error(
                    request, _("Unable to fetch corporation stats from zKillboard: %(err)s") % {"err": str(exc)}
                )

        if stats:
            snapshots = list(
                CorpActivitySnapshot.objects.filter(corporation_id=target_corp_id).order_by("snapshot_date")
            )
            members = list(
                CorpMemberActivity.objects.filter(corporation_id=target_corp_id).order_by(
                    "-kills_30d", "character_name"
                )
            )

            # Build monthly records
            months_dict = stats.months_data or {}
            sorted_keys = sorted(months_dict.keys())
            for k in sorted_keys:
                monthly_table.append(months_dict[k])

            # Prepare Chart.js arrays
            chart_labels = [m["label"] for m in monthly_table]
            chart_kills = [m["kills"] for m in monthly_table]
            chart_losses = [m["losses"] for m in monthly_table]
            chart_isk_destroyed = [m["isk_destroyed"] for m in monthly_table]
            chart_isk_lost = [m["isk_lost"] for m in monthly_table]

            # Index of current month for dashed visualization
            curr_idx = -1
            for idx, m in enumerate(monthly_table):
                if m.get("is_current"):
                    curr_idx = idx

            snapshot_labels = [s.snapshot_date.strftime("%m-%d") for s in snapshots]
            snapshot_active = [s.active_count for s in snapshots]
            snapshot_low = [s.low_count for s in snapshots]
            snapshot_inactive = [s.inactive_count for s in snapshots]
            snapshot_dormant = [s.dormant_count for s in snapshots]

            chart_data = {
                "monthly_labels": chart_labels,
                "kills": chart_kills,
                "losses": chart_losses,
                "isk_destroyed": chart_isk_destroyed,
                "isk_lost": chart_isk_lost,
                "current_month_index": curr_idx,
                "snapshot_labels": snapshot_labels,
                "snapshot_active": snapshot_active,
                "snapshot_low": snapshot_low,
                "snapshot_inactive": snapshot_inactive,
                "snapshot_dormant": snapshot_dormant,
            }

            # Calculate summary stats from member objects
            total_m = len(members)
            act_m = sum(1 for m in members if m.status == MemberActivityStatus.ACTIVE)
            low_m = sum(1 for m in members if m.status == MemberActivityStatus.LOW)
            inact_m = sum(1 for m in members if m.status == MemberActivityStatus.INACTIVE)
            dorm_m = sum(1 for m in members if m.status == MemberActivityStatus.DORMANT)

            summary = {
                "total_members": total_m,
                "active_count": act_m,
                "low_count": low_m,
                "inactive_count": inact_m,
                "dormant_count": dorm_m,
                "active_pct": round((act_m / total_m * 100), 1) if total_m > 0 else 0,
                "kills_30d": sum(m.kills_30d for m in members),
                "losses_30d": sum(m.losses_30d for m in members),
                "isk_destroyed_30d": sum(m.isk_destroyed_30d for m in members),
                "isk_lost_30d": sum(m.isk_lost_30d for m in members),
                "kills_90d": sum(m.kills_90d for m in members),
                "losses_90d": sum(m.losses_90d for m in members),
                "isk_destroyed_90d": sum(m.isk_destroyed_90d for m in members),
                "isk_lost_90d": sum(m.isk_lost_90d for m in members),
                "kills_120d": sum(m.kills_120d for m in members),
                "losses_120d": sum(m.losses_120d for m in members),
                "isk_destroyed_120d": sum(m.isk_destroyed_120d for m in members),
                "isk_lost_120d": sum(m.isk_lost_120d for m in members),
                "kills_alltime": sum(m.kills_alltime for m in members),
                "losses_alltime": sum(m.losses_alltime for m in members),
                "isk_destroyed_alltime": sum(m.isk_destroyed_alltime for m in members),
                "isk_lost_alltime": sum(m.isk_lost_alltime for m in members),
            }

            # Serialize members data for client-side live filtering
            for m in members:
                members_data.append(
                    {
                        "character_id": m.character_id,
                        "character_name": m.character_name,
                        "main_character_name": m.main_character_name or m.character_name,
                        "is_main": m.is_main,
                        "status": m.status,
                        "kills_30d": m.kills_30d,
                        "losses_30d": m.losses_30d,
                        "isk_destroyed_30d": m.isk_destroyed_30d,
                        "isk_lost_30d": m.isk_lost_30d,
                        "kills_90d": m.kills_90d,
                        "losses_90d": m.losses_90d,
                        "isk_destroyed_90d": m.isk_destroyed_90d,
                        "isk_lost_90d": m.isk_lost_90d,
                        "kills_120d": m.kills_120d,
                        "losses_120d": m.losses_120d,
                        "isk_destroyed_120d": m.isk_destroyed_120d,
                        "isk_lost_120d": m.isk_lost_120d,
                        "kills_alltime": m.kills_alltime,
                        "losses_alltime": m.losses_alltime,
                        "isk_destroyed_alltime": m.isk_destroyed_alltime,
                        "isk_lost_alltime": m.isk_lost_alltime,
                        "last_activity": m.last_activity_date.strftime("%Y-%m-%d %H:%M")
                        if m.last_activity_date
                        else "",
                    }
                )

    context = {
        "title": f"{stats.corporation_name if stats else _('Corporation')} Trend",
        "auth_corps": auth_corps,
        "monitored_corps": monitored_corps,
        "selected_corp_id": target_corp_id,
        "stats": stats,
        "summary": summary,
        "snapshots": snapshots,
        "members": members,
        "monthly_table": list(reversed(monthly_table)),
        "chart_data_json": json.dumps(chart_data),
        "members_data_json": json.dumps(members_data),
    }
    return render(request, "aa_recruitment/corp_trends.html", context)


@login_required
@permission_required("aa_recruitment.manage_recruitment")
@require_POST
def corp_trends_sync(request: HttpRequest, corp_id: int) -> HttpResponse:
    """Trigger on-demand synchronization of zKillboard combat trends and member activity for a corp."""
    try:
        service = CorpTrendsService()
        stats = service.sync_corporation(corp_id)
        messages.success(
            request,
            _("Successfully refreshed combat statistics and member activity for '%(name)s' from zKillboard.")
            % {"name": stats.corporation_name},
        )
    except Exception as exc:
        messages.error(
            request,
            _("Error refreshing corporation data: %(err)s") % {"err": str(exc)},
        )
    return redirect("aa_recruitment:corp_trends", corp_id=corp_id)


@login_required
@permission_required("aa_recruitment.manage_recruitment")
def api_corp_search(request: HttpRequest) -> JsonResponse:
    """API endpoint to search corporations across Alliance Auth and CCP ESI."""
    query = request.GET.get("q", "").strip()
    results = CorpTrendsService.search_corporation(query)
    return JsonResponse({"results": results})
