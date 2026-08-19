from odoo import _, fields, http
from odoo.http import request


class FacebookLeadOAuth(http.Controller):

    @http.route("/facebook_leads/oauth/callback", type="http", auth="user", methods=["GET"], csrf=False)
    def callback(self, **params):
        state = params.get("state")
        account = request.env["facebook.lead.account"].sudo().search([
            ("oauth_state", "=", state), ("oauth_user_id", "=", request.env.user.id)
        ], limit=1)
        if not state or not account or not account.oauth_state_expires_at or account.oauth_state_expires_at < fields.Datetime.now():
            return request.make_response(_("Invalid or expired Facebook connection request."), status=403)
        if params.get("error"):
            account.write({"oauth_state": False, "oauth_state_expires_at": False, "oauth_user_id": False})
            return request.redirect("/odoo/action-zencore_facebook_leads.action_facebook_lead_account?facebook_error=access_denied")
        code = params.get("code")
        if not code:
            return request.make_response(_("Facebook did not return an authorization code."), status=400)
        account._exchange_code(code)
        return request.redirect("/odoo/action-zencore_facebook_leads.action_facebook_lead_account/%s" % account.id)
