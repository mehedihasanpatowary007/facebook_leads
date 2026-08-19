# Odoo Configuration

## Prerequisites

- Odoo 19 with CRM installed
- A public HTTPS `web.base.url`
- Sales Administrator/Manager access
- A configured Meta Developer App

## Guided setup

1. Upgrade/install **Zencore Facebook Leads**.
2. Open the standalone **Facebook Leads** application.
3. Go to **Facebook App Credentials > New**.
4. Enter the connection name, Meta App ID, App Secret, and Graph API version.
5. Copy the OAuth Redirect URL to Meta, then click **Generate Token**.
6. Review imported records under **Facebook Pages**.
7. If a Page shows webhook as inactive, open it and click **Subscribe Webhook**.
8. Click **Fetch Lead Forms**.
9. Review every form's CRM mapping and set the default sales team/salesperson on its Page.
10. Run **Test Connection**, then submit a Meta Lead Ads test lead.

The webhook URL is generated from `web.base.url` and ends with `/meta_lead_ads/webhook`. If the Odoo domain changes, set the correct base URL, refresh Pages from the Connection, and subscribe the webhook again.

The backup cron imports missed leads, the queue cron processes webhook notifications, and the cleanup cron removes logs according to the configured retention period. Facebook Lead ID uniqueness prevents duplicate CRM leads.

Page and Form imports follow Meta pagination, so accounts with more than 100 authorized records are supported. OAuth requests expire after 15 minutes and are bound to the Odoo administrator who initiated the connection.
