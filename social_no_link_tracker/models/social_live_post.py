# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models


class SocialLivePost(models.Model):
    """Override _compute_message to respect the 'social.disable_link_tracker' system parameter.

    The standard Odoo flow (social/models/social_live_post.py) calls
    ``mail.render.mixin._shorten_links_text`` inside ``_compute_message``.
    That method scans the post message for every URL and replaces it with
    an Odoo-generated short/tracked link (``/r/XXXXXX``).

    When the IR config parameter ``social.disable_link_tracker`` is ``True``
    we skip that call entirely so the user's original URL is preserved.
    """

    _inherit = 'social.live.post'

    def _is_link_tracker_disabled(self):
        """Return True when the 'Disable Auto Link Tracking' setting is active."""
        param = self.env['ir.config_parameter'].sudo().get_param(
            'social.disable_link_tracker', default='False'
        )
        # ir.config_parameter stores everything as strings; handle common truthy values.
        return str(param).strip().lower() in ('1', 'true', 'yes')

    @api.depends(lambda self:
        ['post_id.utm_campaign_id', 'account_id.media_type', 'account_id.utm_medium_id', 'post_id.source_id']
        + [f'post_id.{field}' for field in self.env['social.post']._get_post_message_modifying_fields()]
        + [f'post_id.{field}' for field in self.env['social.post']._message_fields().values()])
    def _compute_message(self):
        """Compute the live-post message.

        * If the system parameter ``social.disable_link_tracker`` is **True**:
          the message is taken verbatim from the parent social.post – no URL
          shortening / UTM injection takes place.

        * Otherwise: delegates entirely to the standard Odoo implementation
          (which calls ``_shorten_links_text`` and then ``_prepare_post_content``).
        """
        if not self._is_link_tracker_disabled():
            # Fallback to the standard Odoo behaviour defined in social module.
            return super()._compute_message()

        # --- Tracking disabled: keep the user's original URLs intact ---
        message_field_per_media = self.env['social.post']._message_fields()

        for live_post in self:
            message_field = message_field_per_media.get(live_post.account_id.media_type)
            if message_field:
                # Use the raw message from the parent post WITHOUT calling _shorten_links_text.
                raw_message = live_post.post_id[message_field]

                # Still call _prepare_post_content so that media-specific
                # post-processing (e.g. YouTube appending a video link) is respected,
                # but we pass the un-shortened message.
                live_post.message = self.env['social.post']._prepare_post_content(
                    raw_message,
                    live_post.account_id.media_type,
                    **{
                        field: live_post.post_id[field]
                        for field in self.env['social.post']._get_post_message_modifying_fields()
                    }
                )
            else:
                live_post.message = False
