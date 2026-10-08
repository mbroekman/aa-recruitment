# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-08

### Added
- Initial project architecture and foundation for `aa-recruitment`.
- Core data models: `RecruitmentConfig`, `ApplicationForm`, `Question`, `Application`, `ApplicationAnswer`, `ApplicationComment`, `ApplicationLog`.
- Dynamic application forms supporting text, textarea, select choices, checkboxes, and number inputs.
- Status workflow (`Pending`, `Under Review`, `Accepted`, `Rejected`, `Withdrawn`).
- Alliance Auth hooks (`MenuItemHook`, `UrlHook`) with granular permissions (`basic_access`, `manage_recruitment`, `admin_recruitment`).
- Recruiter workflow dashboard: candidate review queue, applicant dossier, reviewer assignment, internal recruiter notes vs public feedback.
- Asynchronous Celery tasks for Discord webhook notifications and Alliance Auth in-app notifications.
- Django Admin configuration with nested inlines.
- Full internationalization (i18n) support with English (`en`) as default base and Dutch (`nl`) compiled translations (`django.po` and `django.mo`).
- Automated Security Vetting Engine (`aa_recruitment.vetting`) inspired by the 3Gods recruitment intelligence tool:
  - Models: `VettingReport` and `VettingFinding` with aggregate risk scoring (capped bucket algorithm) and verdict determination (`REJECT`, `ACCEPT_HIGH`, `ACCEPT_MED`, `ACCEPT_LOW`).
  - Analysis modules: INIT blacklist checker (`blacklist.py`), ESI / EVEWho corporation history and hostile affiliations (`evewho.py`), zKillboard combat activity & fleet session clustering (`zkill.py`), character disclosure cross-checking and playstyle consistency (`consistency.py`), and multi-signal undisclosed alt detection (`altdetect.py`).
  - Automated interview question generation and recruiter action prompts per detected risk anomaly (`recommendation.py`).
  - Asynchronous background execution via Celery task `run_applicant_vetting`.
  - Recruiter UI integration in candidate dossier with visual risk badges, findings breakdown, generated questions, and copyable AI review context packages.
- Corporation Combat Activity & Member Participation Tracker (`Corp Trends` / `Activity Tracker`):
  - Models: `CorpCombatStats`, `CorpActivitySnapshot`, and `CorpMemberActivity` with periodic snapshots and member status classification (`Active`, `Low`, `Inactive`, `Dormant`).
  - Dual synchronized monthly trend line charts powered by zKillboard API: "Kills and losses per month" and "ISK destroyed and lost per month" with dashed indicators for in-progress calendar months and collapsible table breakdowns.
  - Historical stacked bar chart: "Members by status, per update" graphing team composition over time.
  - Interactive member tracker: dynamic 30-day / 90-day time horizons, real-time client-side status filter pills, live name/alt search, 6 summary stat cards (Members shown, % Active, Kills, Losses, ISK destroyed, ISK lost), instant CSV export, and member details table with quick links to zKillboard and EVEWho.
  - Support for both internal Alliance Auth member corporations and any external EVE Online corporation via ESI name/ID search and EVEWho member roster integration.
