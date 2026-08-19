# Meta/Facebook Configuration

Most ongoing configuration is completed from Odoo. A Meta Developer App must still be created once because Meta owns the OAuth credentials and permission approval.

## Meta App setup

1. In Meta for Developers, create a Business-type app and add the Facebook Login and Webhooks capabilities required for Page Lead Ads.
2. Copy the **App ID** and **App Secret** into **Odoo > Facebook Leads > Facebook App Credentials**.
3. In the Meta App's Facebook Login settings, add the exact **OAuth Redirect URL** displayed by Odoo.
4. Ensure the login user can manage the required Facebook Page and its leads.
5. Make these permissions available: `leads_retrieval`, `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`, and `pages_manage_ads`.
6. For production users outside the App roles, switch the app to Live mode and complete Meta App Review/Business Verification where Meta requires it.

Odoo requests the permissions when the administrator clicks **Generate Token**. It retrieves Page tokens, registers the App callback for `leadgen`, and subscribes each authorized Page. The administrator normally does not need to paste Page IDs, Page tokens, Form IDs, callback URLs, or verify tokens manually.

If Meta rejects automatic webhook registration, confirm that the login user is an App administrator/developer, the Page grants the required tasks, the Odoo base URL is public HTTPS, and the app has the required permission access level.
