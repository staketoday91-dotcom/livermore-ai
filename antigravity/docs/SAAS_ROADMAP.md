# Antigravity SaaS Roadmap

This document defines the path from the local MVP to a subscription product.

## Product Stages

### Stage 1: Local Founder Terminal

- One user: the owner.
- Local Streamlit dashboard.
- SQLite or local database.
- Unusual Whales API key belongs to the owner.
- Goal: prove that the agents produce useful, auditable trade plans.

### Stage 2: Private Beta

- Backend API with FastAPI.
- PostgreSQL database.
- Login and roles.
- Per-user watchlists and preferences.
- Admin dashboard for system health, rate limits, and agent runs.
- Alerts by email, Discord, or Telegram.

### Stage 3: Paid SaaS

- Stripe billing.
- Tiered subscriptions:
  - Free: delayed macro and educational watchlist.
  - Pro: high-conviction summaries and sector radar.
  - Premium: live flow-derived signals, if licensing allows it.
- Usage metering and rate limiting per user.
- Compliance disclaimers and audit logs.

## Licensing Constraint

Before selling a product that redistributes Unusual Whales data or derived live signals, confirm the allowed usage with Unusual Whales. The public docs mention Enterprise/Professional subscribers should contact support for redistribution or custom solutions.

## Technical Requirements For SaaS

- Move secrets to managed environment variables.
- Use PostgreSQL instead of local SQLite.
- Add user tables:
  - `users`
  - `organizations`
  - `subscriptions`
  - `user_watchlists`
  - `user_alert_preferences`
- Add operational controls:
  - centralized logs
  - health checks
  - agent run monitoring
  - queue-based jobs
  - data retention policies
- Add legal surfaces:
  - terms of service
  - privacy policy
  - no-financial-advice disclosure
  - data vendor licensing disclosure

## Recommended SaaS Stack

- Backend: FastAPI.
- Frontend: Next.js or a production Streamlit alternative after MVP validation.
- Database: PostgreSQL.
- Jobs: APScheduler for MVP, then Celery/RQ/Temporal for scale.
- Billing: Stripe.
- Auth: Clerk, Auth0, Supabase Auth, or custom FastAPI auth.
- Hosting: Railway/Fly.io/Render for MVP; AWS/GCP when scale demands it.

