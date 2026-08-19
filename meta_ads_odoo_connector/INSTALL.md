# Install commands

Example Docker/Odoo deployment:

```bash
# copy module into custom addons
cp -r meta_ads_odoo_connector /mnt/extra-addons/

# restart Odoo container
docker compose restart odoo

# update apps list from Odoo UI, then install the module
```

Example CLI update:

```bash
./odoo-bin -d your_db -u meta_ads_odoo_connector --stop-after-init
```

After installation, activate developer mode and assign groups to your user.
