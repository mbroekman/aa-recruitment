from django import forms
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from .models import (
    ApplicationForm,
    ApplicationStatus,
    Question,
    QuestionType,
    RecruitmentConfig,
)


class ApplicationSubmissionForm(forms.Form):
    """Dynamic form generating input fields for each question in an ApplicationForm."""

    def __init__(self, *args, application_form: ApplicationForm, **kwargs):
        super().__init__(*args, **kwargs)
        self.application_form = application_form

        questions = application_form.questions.all().order_by("order", "id")
        for question in questions:
            field_name = f"question_{question.id}"
            self.fields[field_name] = self._build_field(question)

    def _build_field(self, question: Question) -> forms.Field:
        label = question.question_text
        help_text = question.help_text or ""
        required = question.is_required

        if question.question_type == QuestionType.TEXTAREA:
            return forms.CharField(
                label=label,
                help_text=help_text,
                required=required,
                widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            )
        elif question.question_type == QuestionType.CHOICE:
            choices = [("", str(_("--- Select an option ---")))] + [
                (c, c) for c in question.get_choice_list()
            ]
            return forms.ChoiceField(
                label=label,
                help_text=help_text,
                required=required,
                choices=choices,
                widget=forms.Select(attrs={"class": "form-control"}),
            )
        elif question.question_type == QuestionType.CHECKBOX:
            return forms.BooleanField(
                label=label,
                help_text=help_text,
                required=required,
                widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
            )
        elif question.question_type == QuestionType.INTEGER:
            return forms.IntegerField(
                label=label,
                help_text=help_text,
                required=required,
                widget=forms.NumberInput(attrs={"class": "form-control"}),
            )
        else:  # Default to short text
            return forms.CharField(
                label=label,
                help_text=help_text,
                required=required,
                max_length=255,
                widget=forms.TextInput(attrs={"class": "form-control"}),
            )


class CommentForm(forms.Form):
    """Form to submit a recruiter note or applicant response."""

    comment = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": _(
                    "Enter your comment, feedback, or interview note..."
                ),
            }
        ),
        label=_("Message / Note"),
    )
    is_internal = forms.BooleanField(
        required=False,
        initial=True,
        label=_("Internal note (only visible to recruitment staff)"),
    )


class StatusUpdateForm(forms.Form):
    """Form for recruitment staff to transition status and assign a reviewer."""

    status = forms.ChoiceField(
        choices=ApplicationStatus.choices,
        widget=forms.Select(attrs={"class": "form-control"}),
        label=_("Status"),
    )
    reviewer = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("username"),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
        label=_("Assigned Reviewer"),
    )
    note = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": _("Optional log note explaining this change"),
            }
        ),
        label=_("Log Note"),
    )


class ApplicationFormConfigForm(forms.ModelForm):
    """Frontend management form for creating and editing recruitment application forms."""

    class Meta:
        model = ApplicationForm
        fields = [
            "title",
            "slug",
            "corporation",
            "description",
            "is_active",
            "reviewers_group",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("e.g. Main Fleet Corp Recruitment"),
                }
            ),
            "slug": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("e.g. main-corp-recruitment"),
                }
            ),
            "corporation": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": _(
                        "Requirements, instructions, and guidelines for applicants..."
                    ),
                }
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "reviewers_group": forms.Select(attrs={"class": "form-select"}),
        }


class QuestionConfigForm(forms.ModelForm):
    """Frontend management form for adding and editing questions on a form."""

    class Meta:
        model = Question
        fields = [
            "question_text",
            "help_text",
            "question_type",
            "choices",
            "is_required",
            "order",
        ]
        widgets = {
            "question_text": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _(
                        "e.g. What is your primary timezone / play schedule?"
                    ),
                }
            ),
            "help_text": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Optional helper text shown below question"),
                }
            ),
            "question_type": forms.Select(attrs={"class": "form-select"}),
            "choices": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _(
                        "Option 1, Option 2, Option 3 (for Single Choice only)"
                    ),
                }
            ),
            "is_required": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "order": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
        }


class RecruitmentSettingsForm(forms.ModelForm):
    """Frontend management form for global recruitment and portal settings."""

    class Meta:
        model = RecruitmentConfig
        fields = [
            "portal_menu_title",
            "recruiter_menu_title",
            "allow_multiple_active",
            "notify_on_status_change",
        ]
        widgets = {
            "portal_menu_title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Default: Apply (e.g. 'Solliciteren', 'Join Us')"),
                }
            ),
            "recruiter_menu_title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Default: Recruitment (e.g. 'Werving', 'Desk')"),
                }
            ),
            "allow_multiple_active": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "notify_on_status_change": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
        }
        labels = {
            "portal_menu_title": _("Candidate Portal Menu Title"),
            "recruiter_menu_title": _("Recruiter Desk Menu Title"),
            "allow_multiple_active": _("Allow Multiple Active Applications"),
            "notify_on_status_change": _("In-App Status Notifications"),
        }
        help_texts = {
            "portal_menu_title": _(
                "Custom label for the Candidate / Apply portal in the navigation sidebar (e.g. 'Apply', 'Join Us', 'Solliciteren'). Leave blank to use default."
            ),
            "recruiter_menu_title": _(
                "Custom label for the Recruiter desk in the navigation sidebar (e.g. 'Recruitment', 'Werving'). Leave blank to use default."
            ),
            "allow_multiple_active": _(
                "Allow applicants to submit applications to multiple open corporations simultaneously."
            ),
            "notify_on_status_change": _(
                "Send in-app notifications to candidates when their dossier status changes."
            ),
        }


