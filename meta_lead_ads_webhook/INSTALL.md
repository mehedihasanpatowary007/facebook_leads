# Installation Guide

## Linux/server install

```bash
cd /opt/odoo19/custom-addons
unzip meta_lead_ads_webhook_odoo19.zip -d /opt/odoo19/custom-addons/
chown -R odoo:odoo /opt/odoo19/custom-addons/meta_lead_ads_webhook
systemctl restart odoo19
```

Install from terminal:

```bash
/opt/odoo19/odoo-bin \
  -c /opt/odoo19/odoo.conf \
  -d your_db_name \
  -i meta_lead_ads_webhook \
  --stop-after-init
```

Upgrade after code changes:

```bash
/opt/odoo19/odoo-bin \
  -c /opt/odoo19/odoo.conf \
  -d your_db_name \
  -u meta_lead_ads_webhook \
  --stop-after-init
```

## Docker install

```bash
unzip meta_lead_ads_webhook_odoo19.zip -d ./custom-addons/
docker compose restart odoo
```

Then inside Odoo:

```text
Apps > Update Apps List > search: Meta Lead Ads Webhook CRM > Install
```

## If menu does not show

Go to:

```text
Settings > Users & Companies > Users > Your User
```

Enable:

```text
Meta Lead Ads: Technical Administrator
```

Settings administrators should receive this access automatically through the System group, but assign it manually if needed.
