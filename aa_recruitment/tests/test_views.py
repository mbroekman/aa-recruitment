from unittest.mock import patch

from allianceauth.tests.auth_utils import AuthUtils
from django.test import Client, TestCase
from django.urls import reverse

from aa_recruitment.models import (
    Application,
    ApplicationForm,
    ApplicationStatus,
    Question,
    QuestionType,
)


class RecruitmentViewTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Regular user with basic_access and main character
        self.user = AuthUtils.create_user("test_applicant")
        AuthUtils.add_main_character_2(
            self.user,
            "Applicant Pilot",
            90002,
            corp_id=1002,
            corp_name="App Corp",
            corp_ticker="APP",
        )
        AuthUtils.add_permissions_to_user_by_name(["aa_recruitment.basic_access"], self.user)

        # Recruiter user with manage_recruitment & basic_access
        self.recruiter = AuthUtils.create_user("test_recruiter")
        AuthUtils.add_main_character_2(
            self.recruiter,
            "Recruiter Pilot",
            90003,
            corp_id=1003,
            corp_name="Rec Corp",
            corp_ticker="REC",
        )
        AuthUtils.add_permissions_to_user_by_name(
            ["aa_recruitment.basic_access", "aa_recruitment.manage_recruitment"],
            self.recruiter,
        )

        # Application form setup
        self.form = ApplicationForm.objects.create(
            title="Capital Wing Application",
            slug="capital-wing-app",
            description="Requirements for supercapital pilots.",
            is_active=True,
        )
        self.question = Question.objects.create(
            form=self.form,
            question_text="Which dreadnought hulls can you fly?",
            question_type=QuestionType.TEXT,
            order=1,
            is_required=True,
        )

    def test_anonymous_redirects_to_login(self):
        url = reverse("aa_recruitment:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_applicant_index_view(self):
        self.client.force_login(self.user)
        url = reverse("aa_recruitment:index")
        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Capital Wing Application")

    @patch("aa_recruitment.tasks.run_applicant_vetting.delay")
    @patch("aa_recruitment.tasks.send_recruitment_discord_notification.delay")
    def test_submit_application(self, mock_notify, mock_vetting):
        self.client.force_login(self.user)
        url = reverse("aa_recruitment:apply", kwargs={"slug": self.form.slug})

        # GET form
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # POST submission
        post_data = {
            f"question_{self.question.id}": "Naglfar and Revelation with T2 Siege",
        }
        response = self.client.post(url, data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Verify application created
        app = Application.objects.filter(user=self.user, form=self.form).first()
        self.assertIsNotNone(app)
        self.assertEqual(app.status, ApplicationStatus.PENDING)
        self.assertEqual(app.answers.count(), 1)
        self.assertEqual(app.answers.first().answer_text, "Naglfar and Revelation with T2 Siege")
        mock_notify.assert_called_once()

    def test_recruiter_queue_permission_enforcement(self):
        # Regular user should be forbidden
        self.client.force_login(self.user)
        queue_url = reverse("aa_recruitment:recruiter_queue")
        response = self.client.get(queue_url)
        self.assertEqual(response.status_code, 403)

        # Recruiter should have access
        self.client.force_login(self.recruiter)
        response = self.client.get(queue_url)
        self.assertEqual(response.status_code, 200)

    @patch("aa_recruitment.tasks.send_recruitment_discord_notification.delay")
    @patch("aa_recruitment.tasks.notify_applicant_in_app.delay")
    def test_recruiter_status_update(self, mock_in_app, mock_discord):
        app = Application.objects.create(
            form=self.form,
            user=self.user,
            main_character_name="Test Pilot",
            status=ApplicationStatus.PENDING,
        )

        self.client.force_login(self.recruiter)
        update_url = reverse("aa_recruitment:update_status", kwargs={"application_id": app.pk})

        response = self.client.post(
            update_url,
            data={
                "status": ApplicationStatus.IN_PROGRESS,
                "reviewer": self.recruiter.pk,
                "note": "Scheduled voice interview on Mumble",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.IN_PROGRESS)
        self.assertEqual(app.reviewer, self.recruiter)
        self.assertEqual(app.logs.count(), 1)
