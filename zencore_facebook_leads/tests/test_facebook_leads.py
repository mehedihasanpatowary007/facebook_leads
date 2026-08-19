from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from unittest.mock import patch


class TestFacebookLeads(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env["facebook.lead.config"].create({
            "name": "Test Page", "page_id": "10001", "page_access_token": "token",
            "verify_token": "verify", "app_secret": "secret",
            "webhook_url": "https://example.test/meta_lead_ads/webhook",
        })
        model = cls.env["ir.model"]._get("crm.lead")
        fields_by_name = {
            item.name: item for item in cls.env["ir.model.fields"].search([
                ("model_id", "=", model.id), ("name", "in", ("contact_name", "phone", "email_from"))
            ])
        }
        for sequence, (facebook_name, odoo_name) in enumerate((
            ("full_name", "contact_name"), ("phone_number", "phone"), ("email", "email_from")
        ), 1):
            cls.env["facebook.lead.mapping"].create({
                "sequence": sequence, "config_id": cls.config.id, "facebook_form_id": "20002",
                "facebook_form_name": "Admissions", "facebook_field_name": facebook_name,
                "odoo_field_id": fields_by_name[odoo_name].id,
            })

    def test_process_lead_with_optional_email_missing(self):
        log = self.env["facebook.lead.log"].create({
            "config_id": self.config.id, "facebook_lead_id": "30003",
            "facebook_form_id": "20002", "facebook_form_name": "Admissions",
        })
        lead = log._process(lead_data={
            "id": "30003", "form_id": "20002", "created_time": "2026-06-24T11:36:41+06:00",
            "field_data": [
                {"name": "full_name", "values": ["Test Student"]},
                {"name": "phone_number", "values": ["+8801700000000"]},
            ],
        })
        self.assertTrue(lead)
        self.assertEqual(lead.contact_name, "Test Student")
        self.assertEqual(lead.phone, "+8801700000000")
        self.assertEqual(log.status, "success")

    def test_webhook_url_validation(self):
        with self.assertRaises(ValidationError):
            self.config.webhook_url = "http://example.test/wrong"

    def test_account_oauth_url_contains_required_permissions(self):
        account = self.env["facebook.lead.account"].create({
            "name": "Test Meta App", "app_id": "123456", "app_secret": "secret",
        })
        action = account.action_connect_facebook()
        self.assertIn("dialog/oauth", action["url"])
        self.assertIn("leads_retrieval", action["url"])
        self.assertIn("pages_manage_metadata", action["url"])
        self.assertIn("pages_manage_ads", action["url"])
        self.assertTrue(account.oauth_state)
        self.assertEqual(account.oauth_user_id, self.env.user)

    def test_invalid_graph_api_version_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["facebook.lead.account"].create({
                "name": "Invalid Meta App", "app_id": "654321",
                "app_secret": "secret", "api_version": "25",
            })

    def test_direct_window_actions_use_odoo_19_views_format(self):
        account = self.env["facebook.lead.account"].create({
            "name": "Action Test", "app_id": "987654", "app_secret": "secret",
        })
        account_action = account.action_open_pages()
        page_action = self.config.action_open_forms()
        self.assertEqual(account_action["views"], [(False, "list"), (False, "form")])
        self.assertEqual(page_action["views"], [(False, "list"), (False, "form")])

    def test_granular_scope_page_discovery_fallback(self):
        account = self.env["facebook.lead.account"].create({
            "name": "Granular Scope Test", "app_id": "246810", "app_secret": "secret",
            "user_access_token": "user-token",
        })
        with patch.object(type(account), "_iter_graph_data", return_value=iter(())), patch.object(
            type(account), "_request", side_effect=[
                {"data": {"granular_scopes": [{"scope": "pages_show_list", "target_ids": ["93708949971"]}]}},
                {"id": "93708949971", "name": "World University of Bangladesh", "access_token": "page-token"},
            ]
        ):
            pages = account._get_authorized_pages()
        self.assertEqual(pages[0]["id"], "93708949971")
        self.assertEqual(pages[0]["access_token"], "page-token")

    def test_unmapped_form_question_is_safe(self):
        form = self.env["facebook.lead.form"].create({
            "name": "Admissions", "config_id": self.config.id, "facebook_form_id": "20003",
        })
        mapping = self.env["facebook.lead.mapping"].create({
            "config_id": self.config.id, "form_id": form.id,
            "facebook_form_id": form.facebook_form_id, "facebook_form_name": form.name,
            "facebook_field_name": "custom_question",
        })
        self.assertFalse(mapping.odoo_field_id)
