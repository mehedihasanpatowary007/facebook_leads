# -*- coding: utf-8 -*-
{
    'name': 'Social Marketing - Disable Auto Link Tracking',
    'version': '19.0.1.0.0',
    'category': 'Marketing/Social Marketing',
    'summary': 'Prevent Odoo from auto-replacing URLs in Social Marketing posts with tracked short links.',
    'description': """
Social Marketing - Disable Auto Link Tracking
=============================================

By default, Odoo's Social Marketing module automatically replaces every URL in a post's
message with a tracked short link (e.g. ``https://myodoo.com/r/ABC123``).

This module adds a setting to the General Settings that lets you **keep your own URLs
unchanged** when posting via Social Marketing.

How it works
------------
* A boolean field **"Disable Auto Link Tracking in Social Posts"** is added to
  *Settings → Social Marketing*.
* When the option is **enabled**, the ``_compute_message`` method on
  ``social.live.post`` is overridden so that ``_shorten_links_text`` is **skipped**
  and the original message URL is preserved.
* When the option is **disabled** (default), Odoo's standard behaviour is restored.

Compatibility
-------------
Odoo 19 Community / Enterprise
    """,
    'author': 'Custom',
    'depends': [
        'social',
        'link_tracker',
    ],
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
