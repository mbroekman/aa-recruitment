# AA-Recruitment - AI Agent Guidelines

Dit project maakt integraal onderdeel uit van de Workbench 001 workspace en erft alle bindende richtlijnen van het centrale hoofd-instructiedocument:
👉 **[Centrale AGENTS.md](file:///g:/My%20Drive/Workbench%20001/AGENTS.md)**

Lees tevens altijd eerst [.agent/memory.md](file:///g:/My%20Drive/Workbench%20001/.agent/memory.md) vóór analyse of modificatie (Regel 1 van AGENTS.md).

---

## 1. Project Context & Backlog Directory

- **Plugin:** `aa-recruitment` (Django App: `aa_recruitment`)
- **Backlog Map:** `plugins/aa-recruitment/backlog/`
- **Directory Context (CRITICAL):** Alle `backlog` CLI commando's en MCP interacties **MOETEN** worden uitgevoerd met de werkmap ingesteld op `plugins/aa-recruitment` (bijv. `cd plugins/aa-recruitment` of via de `Cwd` parameter in toolcalls), zodat taken correct in de backlog van `aa-recruitment` worden geplaatst en beheerd.

---

## 2. Bindende Centrale Regels (Inherited from Master AGENTS.md)

Alle standaarden uit de centrale [AGENTS.md](file:///g:/My%20Drive/Workbench%20001/AGENTS.md) zijn hier onverkort van toepassing:

- **Taakbeheer via Backlog.md:** Eerst taak registreren/WIP zetten in `backlog-md` vóór het schrijven of wijzigen van code. Afronden pas na testen, linting en type-checks.
- **Tooling & Omgeving:** `uv` voor package management, `Ruff` (line-length 120 conform Alliance Auth standaard), `mypy` strict met `django-stubs`, `pytest` en `pytest-django`.
- **Alliance Auth UI & Bootstrap 5:** Altijd `{% extends "allianceauth/base-bs5.html" %}`, uitsluitend Bootstrap 5 componenten (`card`, `badge bg-*`, `d-flex`, `btn-sm`). Nooit Bootstrap 3 componenten (`panel`, `label`, `pull-right`). Geen eigen `{% if messages %}` block toevoegen (reeds in `base-bs5.html`).
- **Architectuur: Sollicitant vs Recruiter (ADR-007):** Strikte scheiding tussen kandidaat-portaal ('Apply', `basic_access`) en recruiter-beheer ('Recruitment', `manage_recruitment`, `admin_recruitment`).
- **Frontend Configuratiesuite (ADR-006):** Formulieren, vragenlijsten, categorieën en instellingen volledig in frontend UI beheren, niet in `/admin/`.
- **Discord Intel Archiving & Vetting (ADR-008):** REST-api sync, multi-guild support, historische 'before' backfill en incrementele 'after' scan.
- **Corp Combat Trends & Member Tracker (ADR-009):** zKillboard data pipeline (cumulatieve invarianten, periode totalen, dynamische stat-cards, dark theme contrast).
- **Pre-Commit Verificatie:** Update `CHANGELOG.md` en user docs vóór taakafronding. Nooit automatische releases of tags.
