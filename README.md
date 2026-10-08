# AA Recruitment

Recruitment and Application Management Plugin for **Alliance Auth**.

Manage corporation and alliance recruitment workflows directly within Alliance Auth: customizable application forms, dynamic questionnaires, applicant dossiers, multi-stage status reviews, and Discord alerts.

---

## Features

- **Custom Application Forms:** Create corporation or division-specific recruitment postings with custom requirements and guidelines.
- **Dynamic Questionnaires:** Configure question types (short text, multi-line text, dropdown choices, checkboxes, numbers) with custom ordering.
- **Applicant Dashboard:** Users can submit applications, monitor their status, view recruiter feedback, and respond to inquiries.
- **Recruiter Workflow:**
  - Dedicated review queue with status and form filters.
  - Candidate dossier displaying Auth profile, linked characters, and submitted answers.
  - Reviewer assignment and status transitions (`Pending Review` → `Under Review` → `Accepted` / `Rejected`).
  - Internal recruiter notes (hidden from applicants) alongside public applicant feedback.
- **Audit Log:** Complete history of status changes, reviewer assignments, and actions.
- **Discord & In-App Alerts:** Webhook embed notifications for new applications and status updates, plus Alliance Auth native notifications.

---

## Installation

### 1. Install the package
In your Alliance Auth virtual environment:

```bash
pip install -e /path/to/plugins/aa-recruitment
```

### 2. Configure Alliance Auth
Add `'aa_recruitment'` to `INSTALLED_APPS` in your `local.py`:

```python
INSTALLED_APPS += [
    "aa_recruitment",
]
```

### 3. Run Migrations & Collect Static
```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

### 4. Restart Services
```bash
sudo supervisorctl restart all
```

---

## Permissions

| Permission | Codename | Description |
| :--- | :--- | :--- |
| **Basic Access** | `aa_recruitment.basic_access` | View recruitment forms, submit applications, and track own status. |
| **Recruitment Officer** | `aa_recruitment.manage_recruitment` | Access review queue, manage applications, add comments, assign reviewers, update status. |
| **Recruitment Administrator** | `aa_recruitment.admin_recruitment` | Create and edit application forms, questions, and global plugin configuration. |

---

## Celery Tasks

Add periodic tasks to `CELERYBEAT_SCHEDULE` if using scheduled maintenance (optional):

```python
# Optional periodic cleanup or reminder tasks
```

---

## License
MIT License.
