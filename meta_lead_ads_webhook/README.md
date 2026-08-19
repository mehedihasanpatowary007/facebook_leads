# Meta Lead Ads Webhook CRM for Odoo 19

This addon imports Meta/Facebook Lead Ads into Odoo CRM using Meta Webhooks.

## What it does

- Exposes a public webhook endpoint: `/meta_lead_ads/webhook`
- Handles Meta webhook verification with `hub.verify_token`
- Receives `leadgen` webhook events in near real time
- Stores all incoming webhook payloads as audit logs
- Queues each `leadgen_id` safely
- Can process the queue immediately during the webhook request for real-time CRM creation
- Fetches full lead details from Meta Graph API
- Creates `crm.lead` with Meta attribution fields
- Supports lead form mapping for team, salesperson, UTM, tags, and custom questions
- Supports retry processing using `ir.cron`
- Supports optional `X-Hub-Signature-256` validation

## Required Meta setup

Your Meta app/page must have the correct permissions and Page access token for Lead Ads retrieval.
Usually you need permissions such as:

- `leads_retrieval`
- `pages_read_engagement`
- `pages_show_list`
- business/page access configured correctly in Meta Business settings

Exact permissions may depend on your app type, app review state, and asset ownership.

## Odoo setup

1. Copy this addon folder into your Odoo custom addons path.
2. Restart Odoo.
3. Update Apps List.
4. Install **Meta Lead Ads Webhook CRM**.
5. Go to **Meta Lead Ads > Configuration > Meta Connections**.
6. Create a connection:
   - Page ID
   - App ID
   - App Secret
   - Page Access Token
   - Webhook Verify Token
   - API Version, for example `v25.0`
7. Copy the generated webhook URL.
8. Configure it in Meta Developers Webhooks.
9. Subscribe the page/app to the `leadgen` field.

## Webhook URL

If your Odoo domain is:

```text
https://erp.example.com
```

The callback URL is:

```text
https://erp.example.com/meta_lead_ads/webhook
```

This URL must be public HTTPS. Meta cannot reach `localhost:8019`.

## Recommended Nginx/Odoo settings

Odoo config:

```ini
proxy_mode = True
```

Nginx should proxy HTTPS traffic to Odoo. Example:

```nginx
location / {
    proxy_pass http://127.0.0.1:8019;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}
```

## Processing design

By default the webhook stores the event, queues the lead, and immediately tries to fetch full lead data and create the CRM lead. The queue/log remains available for retries. For very high-volume production systems, disable **Process Immediately During Webhook** on the connection and let the cron process the queue shortly after.

## Important notes

- Keep tokens and app secrets private.
- Do not expose Odoo over HTTP for production webhooks.
- Use signature validation in production.
- If a webhook arrives but no CRM lead is created, check **Meta Lead Ads > Lead Queue** and **Webhook Events**.
