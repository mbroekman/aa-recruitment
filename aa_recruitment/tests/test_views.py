from unittest.mock import patch

from django.contrib.auth.models import Permission, User
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

        # Regular user with basic_access
        self.user = User.objects.create_user(username="test_applicant", password="password123")
        perm_basic = Permission.objects.get(codename="basic_access", content_type__app_label="aa_recruitment")
        self.user.user_permissions.add(perm_basic)

        # Recruiter user with manage_recruitment & basic_access
        self.recruiter = User.objects.create_user(username="test_recruiter", password="password123")
        perm_manage = Permission.objects.get(codename="manage_recruitment", content_type__app_label="aa_recruitment")
        self.recruiter.user_permissions.add(perm_basic, perm_manage)

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
        self.client.login(username="test_applicant", password="password123")
        url = reverse("aa_recruitment:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Capital Wing Application")

    @patch("aa_recruitment.tasks.send_recruitment_discord_notification.delay")
    def test_submit_application(self, mock_notify):
        self.client.login(username="test_applicant", password="password123")
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
        self.client.login(username="test_applicant", password="password123")
        queue_url = reverse("aa_recruitment:recruiter_queue")
        response = self.client.get(queue_url)
        self.assertEqual(response.status_code, 403)

        # Recruiter should have access
        self.client.login(username="test_recruiter", password="password123")
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

        self.client.login(username="test_recruiter", password="password123")
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
