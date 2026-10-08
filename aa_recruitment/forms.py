from django import forms
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from .models import (
    ApplicationForm,
    ApplicationStatus,
    Question,
    QuestionType,
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
