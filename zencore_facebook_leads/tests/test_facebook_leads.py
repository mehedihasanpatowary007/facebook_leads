from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


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
