# Meta Ads Odoo Connector for Odoo 19

Production-oriented starter module for integrating Meta/Facebook Ads backend data with Odoo 19.

## What this v1 module includes

- Meta API connection configuration
- Secure token fields restricted to Meta Ads Administrator group
- Ad Account sync model
- Campaign sync model
- Ad Set sync model
- Ad and Creative sync model
- Daily Ads Insights storage with pivot/graph views
- CRM Lead attribution fields for Meta Lead Ads
- Lead Form mapping model and extension point for webhook/polling
- Conversions API event queue with hashing helper
- API logs with request/response storage without access token logging
- Multi-company record rules
- Cron placeholders for sync and Conversion API sending

## What this v1 intentionally does not do

- It does not create/update/pause live campaigns from Odoo.
- It does not include the full OAuth redirect controller.
- It does not include Meta webhook controller yet.

This is intentional. For production safety, start with reporting, CRM attribution and conversion tracking before allowing Odoo users to change live ad spend.

## Installation

1. Copy `meta_ads_odoo_connector` into your Odoo custom addons path.
2. Restart Odoo.
3. Update Apps List.
4. Install **Meta Ads Odoo Connector**.
5. Assign user groups:
   - Meta Ads User
   - Meta Ads Manager
   - Meta Ads Administrator
   - Meta Ads Technical
6. Go to **Meta Ads > Configuration > Meta Connections**.
7. Create a connection and add:
   - API Version, default `v25.0`
   - App ID
   - App Secret
   - Access Token
   - Company
8. Click **Test Connection**.
9. Click **Sync All**.

## Recommended Meta permissions

For reporting/sync:

- `ads_read`

For future campaign management:

- `ads_management`

For business asset access:

- `business_management`

For lead retrieval/webhooks, your Meta app must be approved for the relevant Lead Ads permissions.

## Production hardening checklist

Before using with real clients:

- Replace manual access token entry with OAuth controller.
- Store secrets in an external secret manager when possible.
- Add webhook endpoint for Lead Ads real-time import.
- Add queue_job or a custom queue worker for high-volume ad accounts.
- Add retry backoff for rate limits.
- Add consent storage before sending CAPI events.
- Add automated tests for sync/parsing logic.
- Add indexes if your insight table grows into millions of rows.

## Main models

- `meta.ads.config`
- `meta.ad.account`
- `meta.campaign`
- `meta.ad.set`
- `meta.ad`
- `meta.ad.creative`
- `meta.ads.insight`
- `meta.lead.form`
- `meta.conversion.event`
- `meta.api.log`

## Senior implementation roadmap

1. Install this connector and verify read-only sync.
2. Add OAuth login/connect flow.
3. Add Lead Ads webhook controller.
4. Add Conversions API event generation from CRM/Sales/Accounting workflows.
5. Add product catalog export for eCommerce.
6. Add campaign creation only after approval workflow and budget guardrails are implemented.
