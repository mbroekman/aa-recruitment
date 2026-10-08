from django.contrib.auth.models import User
from django.test import TestCase

from aa_recruitment.models import (
    Application,
    ApplicationAnswer,
    ApplicationComment,
    ApplicationForm,
    ApplicationLog,
    ApplicationStatus,
    Question,
    QuestionType,
    RecruitmentConfig,
)


class RecruitmentModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="candidate1", password="password123")
        self.recruiter = User.objects.create_user(username="recruiter1", password="password123")
        self.form = ApplicationForm.objects.create(
            title="Main Corp Recruitment",
            slug="main-corp-recruitment",
            description="Requirements and guidelines for pilots.",
            is_active=True,
        )
        self.question_text = Question.objects.create(
            form=self.form,
            question_text="What is your main timezone?",
            question_type=QuestionType.TEXT,
            order=1,
        )
        self.question_choice = Question.objects.create(
            form=self.form,
            question_text="Select primary activity",
            question_type=QuestionType.CHOICE,
            choices="PvP, Industry, Mining",
            order=2,
        )

    def test_config_singleton(self):
        config1 = RecruitmentConfig.get_solo()
        config2 = RecruitmentConfig.get_solo()
        self.assertEqual(config1.pk, config2.pk)
        self.assertFalse(config1.allow_multiple_active)

    def test_application_form_creation(self):
        self.assertEqual(str(self.form), "Main Corp Recruitment")
        self.assertEqual(self.form.questions.count(), 2)

    def test_question_choice_list(self):
        choices = self.question_choice.get_choice_list()
        self.assertEqual(choices, ["PvP", "Industry", "Mining"])

    def test_application_lifecycle(self):
        app = Application.objects.create(
            form=self.form,
            user=self.user,
            main_character_name="Candidate Pilot",
            status=ApplicationStatus.PENDING,
        )
        self.assertTrue(app.is_open)
        self.assertEqual(app.status, ApplicationStatus.PENDING)

        # Add answer
        ans = ApplicationAnswer.objects.create(
            application=app,
            question=self.question_text,
            answer_text="EU Prime (18:00 - 23:00 EVE)",
        )
        self.assertEqual(ans.answer_text, "EU Prime (18:00 - 23:00 EVE)")
        self.assertEqual(app.answers.count(), 1)
        self.assertIn("candidate1", str(app))

        # Add comments (Internal vs Public)
        internal_comment = ApplicationComment.objects.create(
            application=app,
            author=self.recruiter,
            comment="Candidate looks solid, combat history verified.",
            is_internal=True,
        )
        public_comment = ApplicationComment.objects.create(
            application=app,
            author=self.recruiter,
            comment="Welcome! Are you ready for an interview on Discord?",
            is_internal=False,
        )
        self.assertTrue(internal_comment.is_internal)
        self.assertFalse(public_comment.is_internal)

        # Audit log
        log = ApplicationLog.objects.create(
            application=app,
            actor=self.recruiter,
            action="Status updated to Under Review",
        )
        self.assertEqual(app.logs.count(), 1)
        self.assertEqual(log.actor, self.recruiter)

        # Status transition to ACCEPTED
        app.status = ApplicationStatus.ACCEPTED
        app.save()
        self.assertFalse(app.is_open)
