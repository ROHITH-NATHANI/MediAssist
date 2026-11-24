# Architecture

Browser → React / TypeScript → FastAPI authorization and validation → SQLAlchemy → PostgreSQL (SQLite development fallback).

Chat API → urgent keyword guard → supervisor → selected health/report/appointment/medication roles → safety role → structured response and trace. The selected roles share a plan, accumulated findings and completed-role metadata. CrewAI reasoning in online mode only receives allowlisted role metadata. The local orchestration layer controls actual read operations and write confirmation. Database actions are separate authenticated API calls. The safety role is a guardrail, not clinical validation.

## API overview

- `/api/auth/register`, `/api/auth/login`, `/api/me`: patient signup, token, profile.
- `/api/doctors`, `/api/slots`: verified doctors, future open slots.
- `/api/doctor/slots`: doctor availability creation.
- `/api/appointments`: list or confirm a slot; `/api/appointments/{id}/cancel`, `/complete`.
- `/api/reports`: list/upload; `/api/reports/{id}/download`, DELETE `/api/reports/{id}`.
- `/api/medications`: daily reminder creation and list; `/api/medications/{id}/taken`, DELETE archive.
- `/api/chat`: orchestrate agent roles; no automatic writes.
- `/api/admin/stats`, `/api/admin/doctors`: aggregate stats, create and verify doctor accounts.
- `/api/health`: liveness and configured agent mode.

See OpenAPI at `/docs` on the backend.

## Data and concurrency

Users own reports and reminders. Appointment slots belong to doctors; appointments link a patient to a slot. Conditional SQL updates reserve an available slot atomically and ensure only active appointments can be cancelled/completed. Unique constraints prevent duplicate availability and duplicate adherence records. Audit records contain action labels and actor IDs, not report text. Knowledge entries contain brief educational paraphrases and source URLs. PostgreSQL uses parameterized full-text search. SQLite uses local token overlap.

## Deployment

Compose provides a persistent PostgreSQL volume, FastAPI service and nginx-served React UI, bound to local interfaces. For a private staging environment use secrets management, TLS reverse proxy, separate database credentials, `DEMO_SEED=false` and `APP_ENV=production` with a strong JWT secret. Provision the first admin through a controlled database/bootstrap process; no public admin signup. Do not expose this prototype for actual clinical use.
