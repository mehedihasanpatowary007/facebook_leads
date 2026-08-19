# Zencore Facebook Leads

Supportive Odoo 19 CRM connector for Meta/Facebook Lead Ads. The addon does not create a separate application. Configuration and logs are available below **CRM → Configuration**, while imported records use the standard **CRM → Leads** workflow.

## Production flow

1. Meta sends a signed `leadgen` notification to `/meta_lead_ads/webhook`.
2. Odoo validates the signature, stores one idempotent pending log, and immediately acknowledges Meta.
3. The one-minute queue cron retrieves full lead data and creates the standard CRM lead.
4. Failed requests use exponential backoff and can also be retried manually.
5. The backup cron incrementally discovers notifications missed by the webhook.

See [FACEBOOK_CONFIGURATION.md](FACEBOOK_CONFIGURATION.md), [ODOO_CONFIGURATION.md](ODOO_CONFIGURATION.md), and [USER_MANUAL.md](USER_MANUAL.md).
