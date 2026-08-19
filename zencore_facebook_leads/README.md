# Zencore Facebook Leads

Standalone, OAuth-enabled Odoo 19 CRM connector for Meta/Facebook Lead Ads. Administrators connect Facebook, import Pages and Forms, subscribe webhooks, map fields, and monitor synchronization from the **Facebook Leads** application. Imported records continue to use the standard **CRM > Leads** workflow.

## Guided onboarding

1. Enter a Meta App ID and App Secret under **Facebook Leads > Facebook App Credentials**.
2. Click **Generate Token** and authorize the required Pages.
3. Odoo retrieves Page tokens and attempts App callback and Page `leadgen` subscriptions automatically.
4. Import each Page's Lead Forms and review the generated CRM field mappings.

OAuth requests use a short-lived, user-bound state token. Page/Form discovery supports Graph API pagination, credentials are restricted to Sales Managers, and multi-company record rules isolate configuration and logs.

## Production flow

1. Meta sends a signed `leadgen` notification to `/meta_lead_ads/webhook`.
2. Odoo validates the signature, stores one idempotent pending log, and immediately acknowledges Meta.
3. The one-minute queue cron retrieves full lead data and creates the standard CRM lead.
4. Failed requests use exponential backoff and can also be retried manually.
5. The backup cron incrementally discovers notifications missed by the webhook.

See [FACEBOOK_CONFIGURATION.md](FACEBOOK_CONFIGURATION.md), [ODOO_CONFIGURATION.md](ODOO_CONFIGURATION.md), and [USER_MANUAL.md](USER_MANUAL.md).
