# # # from odoo import models


# # # class MailThread(models.AbstractModel):
# # #     _inherit = "mail.thread"

# # #     def message_post(self, **kwargs):

# # #         kwargs["message_type"] = "comment"

# # #         if not kwargs.get("subtype_xmlid"):
# # #             kwargs["subtype_xmlid"] = "mail.mt_comment"

# # #         return super().message_post(**kwargs)
# # from odoo import models


# # class MailThread(models.AbstractModel):
# #     _inherit = "mail.thread"

# #     def message_post(self, **kwargs):

# #         kwargs["message_type"] = "comment"

# #         kwargs["subtype_xmlid"] = "mail.mt_comment"

# #         return super().message_post(**kwargs)
# # -*- coding: utf-8 -*-
# """
# mail_message.py — intentionally minimal.

# The original global message_post() override was removed because it
# incorrectly forced mail.mt_comment onto ALL Odoo models, including:
#   - The inbound controller (which explicitly sets mail.mt_note)
#   - HR, Accounting, Inventory chatter flows

# Frontend subtype is handled by composer_patch.js (mt_comment for agent replies).
# Backend subtype is set explicitly at each call site:
#   - Inbound controller  → subtype_xmlid='mail.mt_note'
#   - Agent reply (UI)    → subtype_xmlid='mail.mt_comment'  (via composer_patch.js)
# """
# from odoo import models  # noqa: F401  (import kept; file referenced by __init__.py)

# -*- coding: utf-8 -*-
"""
mail_message.py

The original global message_post() override that forced mail.mt_comment on
every Odoo model has been removed.

Root cause of removal:
  - It ran on ALL 300+ models (HR, Accounting, Inventory, etc.)
  - It overwrote the inbound controller's explicit subtype_xmlid='mail.mt_note',
    turning internal audit notes into public comments
  - Each call site already sets its own subtype explicitly:
      Inbound controller  → subtype_xmlid='mail.mt_note'   (internal note)
      Agent reply via UI  → subtype_xmlid='mail.mt_comment' (native Odoo default)

No override is needed here.
"""
from odoo import models  # noqa: F401  — file kept; referenced by models/__init__.py