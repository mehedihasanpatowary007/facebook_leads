# Zencore Facebook Leads - User Manual

## One-time connection

1. Open **Facebook Leads > Facebook App Credentials**.
2. Create a connection and enter the Meta App ID and App Secret.
3. Copy the **OAuth Redirect URL** into the Meta App's valid OAuth redirect URIs.
4. Click **Generate Token**, sign in to Facebook, and authorize the required Pages.
5. Odoo imports the authorized Pages and attempts to register the `leadgen` webhook automatically.
6. If necessary, click **Fetch Facebook Pages**. Then open **Facebook Leads > Facebook Pages**, select a Page, and click **Fetch Lead Forms**.
7. Open each imported form and review **CRM Field Mapping**. Common contact fields are mapped automatically when matching CRM fields exist.
8. Click **Fetch Leads** on a form to import accessible historical leads. New submissions arrive through the webhook.

## New ad or form

- A new ad using an already imported form needs no Odoo change.
- For a new Instant Form, open its Page and click **Fetch Lead Forms**, then review its mapping.
- For a new Facebook Page, open **Facebook App Credentials** and click **Fetch Facebook Pages**.
- A new Meta App requires a new Connection and OAuth authorization.

## Monitoring

- **Sync Logs** shows queued, successful, retrying, and failed submissions.
- Use **Retry** on a failed log after correcting credentials or mapping.
- **Sync Backlog Now** on a Page queues historical leads accessible to the Page token.
- A failed automatic webhook subscription is shown on the Page's **Monitoring** tab; correct the Meta permission/domain issue and click **Subscribe Webhook** again.
- **Test Connection** validates the current OAuth user token. **Disconnect** removes that user token from Odoo but does not revoke existing permissions or Page tokens at Meta.

## Contacts and duplicate protection

- Every imported Facebook submission creates or links an Odoo Contact and sets it as the CRM Lead's Customer.
- Existing Contacts are matched first by normalized email, then by normalized phone within the same company (including shared Contacts).
- Archived matching Contacts are reactivated and reused.
- Database-level Facebook Lead ID uniqueness prevents the same submission from creating a second CRM Lead.
- Transaction locks prevent webhook, cron, and manual fetch jobs from creating the same Contact concurrently.
- If both email and phone are missing, Odoo creates a Contact for the submission but does not merge by name alone, because different people can have the same name.

Only users with Odoo Sales Administrator/Manager access can manage connections, credentials, Pages, forms, and mappings. Multi-company record rules limit each administrator to their currently allowed companies.
