from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .forms import (
    ApplicationSubmissionForm,
    CommentForm,
    StatusUpdateForm,
)
from .models import (
    Application,
    ApplicationAnswer,
    ApplicationComment,
    ApplicationForm,
    ApplicationLog,
    ApplicationStatus,
    RecruitmentConfig,
)
from .tasks import (
    notify_applicant_in_app,
    run_applicant_vetting,
    send_recruitment_discord_notification,
)


@login_required
@permission_required("aa_recruitment.basic_access", raise_exception=True)
def index(request: HttpRequest) -> HttpResponse:
    """Dashboard view showing active application forms and applicant's own submissions."""
    active_forms = ApplicationForm.objects.filter(is_active=True).select_related(
        "corporation"
    )
    user_applications = (
        Application.objects.filter(user=request.user)
        .select_related("form", "reviewer")
        .order_by("-created_at")
    )

    is_recruiter = request.user.has_perm("aa_recruitment.manage_recruitment")
    recruiter_stats = {}
    recent_queue = []

    if is_recruiter:
        pending_count = Application.objects.filter(
            status=ApplicationStatus.PENDING
        ).count()
        in_progress_count = Application.objects.filter(
            status=ApplicationStatus.IN_PROGRESS
        ).count()
        accepted_count = Application.objects.filter(
            status=ApplicationStatus.ACCEPTED
        ).count()
        rejected_count = Application.objects.filter(
            status=ApplicationStatus.REJECTED
        ).count()

        recruiter_stats = {
            "pending": pending_count,
            "in_progress": in_progress_count,
            "active_total": pending_count + in_progress_count,
            "accepted": accepted_count,
            "rejected": rejected_count,
        }
        recent_queue = (
            Application.objects.filter(
                status__in=[ApplicationStatus.PENDING, ApplicationStatus.IN_PROGRESS]
            )
            .select_related("user", "form", "reviewer")
            .order_by("-created_at")[:8]
        )

    context = {
        "title": _("Recruitment & Applications"),
        "active_forms": active_forms,
        "user_applications": user_applications,
        "is_recruiter": is_recruiter,
        "recruiter_stats": recruiter_stats,
        "recent_queue": recent_queue,
    }
    return render(request, "aa_recruitment/index.html", context)


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
                _(
                    "You already have an open application (#%(app_id)s) for %(form_title)s."
                )
                % {"app_id": existing.pk, "form_title": form_instance.title},
            )
            return redirect(
                "aa_recruitment:application_detail", application_id=existing.pk
            )

    if request.method == "POST":
        form = ApplicationSubmissionForm(
            request.POST, application_form=form_instance
        )
        if form.is_valid():
            # Determine main character name from Auth profile if available
            profile = getattr(request.user, "profile", None)
            main_char = (
                getattr(profile, "main_character", None) if profile else None
            )
            main_char_name = (
                main_char.character_name if main_char else request.user.username
            )

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
            send_recruitment_discord_notification.delay(
                app.id, event_type="new_application"
            )
            run_applicant_vetting.delay(app.id)

            messages.success(
                request,
                _(
                    "Your application for '%(title)s' has been submitted successfully!"
                )
                % {"title": form_instance.title},
            )
            return redirect(
                "aa_recruitment:application_detail", application_id=app.pk
            )
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

    answers = application.answers.select_related("question").order_by(
        "question__order", "question__id"
    )

    # Applicants only see public comments; recruiters see all comments
    if is_recruiter:
        comments = application.comments.select_related("author").order_by(
            "created_at"
        )
    else:
        comments = (
            application.comments.filter(is_internal=False)
            .select_related("author")
            .order_by("created_at")
        )

    comment_form = CommentForm()

    context = {
        "title": _("Application #%(pk)s - %(title)s")
        % {"pk": application.pk, "title": application.form.title},
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
    applications = Application.objects.select_related(
        "form", "user", "reviewer"
    ).order_by("-created_at")

    status_filter = request.GET.get("status")
    form_filter = request.GET.get("form_id")
    search_query = request.GET.get("q", "").strip()

    if status_filter:
        applications = applications.filter(status=status_filter)
    else:
        # Default to open applications (pending and in_progress)
        applications = applications.filter(
            status__in=[ApplicationStatus.PENDING, ApplicationStatus.IN_PROGRESS]
        )

    if form_filter:
        applications = applications.filter(form_id=form_filter)

    if search_query:
        applications = applications.filter(
            user__username__icontains=search_query
        ) | applications.filter(main_character_name__icontains=search_query)

    active_forms = ApplicationForm.objects.all().order_by("title")

    context = {
        "title": _("Recruitment Review Queue"),
        "applications": applications,
        "status_filter": status_filter or "open",
        "form_filter": (
            int(form_filter) if form_filter and form_filter.isdigit() else None
        ),
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

    answers = application.answers.select_related("question").order_by(
        "question__order", "question__id"
    )
    comments = application.comments.select_related("author").order_by(
        "created_at"
    )
    logs = application.logs.select_related("actor").order_by("-created_at")

    # Linked EVE characters from Alliance Auth
    characters = []
    ownerships = getattr(application.user, "character_ownerships", None)
    if ownerships:
        characters = ownerships.select_related("character").all()

    status_form = StatusUpdateForm(
        initial={"status": application.status, "reviewer": application.reviewer}
    )
    comment_form = CommentForm()

    vetting_report = getattr(application, "vetting_report", None)
    vetting_findings = (
        vetting_report.findings.all() if vetting_report else []
    )

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
        _(
            "Security vetting audit queued for Application #%(pk)s. Refresh shortly to see updated findings."
        )
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

        log_msg = _(
            "Status changed from '%(old)s' to '%(new)s'"
        ) % {"old": old_status, "new": application.get_status_display()}
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
                message=_(
                    "The status of your application for %(title)s has been updated to '%(status)s'."
                )
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
            _(
                "Application #%(pk)s successfully updated to '%(status)s'."
            )
            % {"pk": application.pk, "status": application.get_status_display()},
        )

    return redirect(
        "aa_recruitment:recruiter_detail", application_id=application.pk
    )


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
            action=_("%(tag)s added by %(user)s")
            % {"tag": tag, "user": request.user.username},
        )

        # Notify other party if public comment
        if not is_internal:
            if request.user == application.user and application.reviewer:
                notify_applicant_in_app.delay(
                    application.id,
                    title=_("New message from applicant"),
                    message=_(
                        "%(user)s replied on application #%(pk)s."
                    )
                    % {"user": request.user.username, "pk": application.pk},
                    level="info",
                )
            elif is_recruiter:
                notify_applicant_in_app.delay(
                    application.id,
                    title=_("New message from Recruitment"),
                    message=_(
                        "A new comment has been posted on your application #%(pk)s."
                    )
                    % {"pk": application.pk},
                    level="info",
                )

        messages.success(request, _("Comment saved successfully."))

    if is_recruiter:
        return redirect(
            "aa_recruitment:recruiter_detail", application_id=application.pk
        )
    return redirect(
        "aa_recruitment:application_detail", application_id=application.pk
    )


@login_required
@permission_required("aa_recruitment.basic_access", raise_exception=True)
@require_POST
def withdraw_application(request: HttpRequest, application_id: int) -> HttpResponse:
    """Withdraw an active application."""
    application = get_object_or_404(
        Application, pk=application_id, user=request.user
    )

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
            _("Application #%(pk)s has been successfully withdrawn.")
            % {"pk": application.pk},
        )

    return redirect("aa_recruitment:index")


@login_required
@permission_required("aa_recruitment.manage_recruitment", raise_exception=True)
def api_queue_stats(request: HttpRequest) -> JsonResponse:
    """JSON API returning queue counts for widgets or bots."""
    pending = Application.objects.filter(status=ApplicationStatus.PENDING).count()
    in_progress = Application.objects.filter(
        status=ApplicationStatus.IN_PROGRESS
    ).count()
    return JsonResponse(
        {
            "status": "success",
            "pending": pending,
            "in_progress": in_progress,
            "total_open": pending + in_progress,
        }
    )
