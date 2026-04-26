# Jewellery Evaluator - Odoo 17 Module

Production-grade custom Odoo 17 Community module for jewelry and gold businesses with automated pricing, POS enforcement, and live API integration.

## Overview

This module provides comprehensive gold product pricing management for jewelry businesses, including:

- **Automated Price Updates**: Fetches live gold prices from external API every 10 minutes
- **Dynamic Pricing**: Calculates product prices based on weight, purity, and markup
- **POS Price Enforcement**: Prevents sales below minimum price with backend and frontend validation
- **Batch Processing**: Efficient updates for large product catalogs (~1500 products)
- **Precision Calculations**: Uses Decimal arithmetic to avoid floating-point errors

## Module Structure

```
jewellery_evaluator/
├── __init__.py
├── __manifest__.py
├── utils.py                              # Pure helper functions (price parsing, computation)
├── models/
│   ├── __init__.py
│   ├── product_template.py              # Product model extensions
│   ├── gold_price_service.py            # API service and cron logic
│   ├── jewellery_evaluator_config.py    # Configuration settings
│   └── pos_order.py                     # POS backend validation
├── views/
│   ├── jewellery_evaluator_config_views.xml
│   └── product_template_views.xml
├── security/
│   ├── ir.model.access.csv
│   └── jewellery_evaluator_security.xml
├── data/
│   └── jewellery_evaluator_cron.xml     # Cron job definition
└── static/
    └── src/
        └── js/
            └── pos_discount_override.js  # POS frontend patches
```

## Installation

### Prerequisites

- Odoo 17 Community Edition (self-hosted)
- Python 3.10 or higher
- `requests` library (usually included with Odoo)

### Steps

1. **Add the module to Odoo's addons path**

   In `odoo.conf`, add the path to this repo (the directory that contains `__manifest__.py` and `jewellery_evaluator/`) to the `addons_path` option. For example:

   ```ini
   addons_path = /opt/odoo/addons,/path/to/odoo-jewellery-evaluator
   ```

   Or copy that directory into an existing addons directory:

   ```bash
   cp -r /path/to/odoo-jewellery-evaluator /path/to/odoo/addons/
   ```

2. **Update Module List**

   - Log in to Odoo as Administrator
   - Go to **Apps** menu
   - Click **Update Apps List**
   - Remove **Apps** filter to see all modules

3. **Install Module**

   - Search for "Jewellery Evaluator"
   - Click **Install**

4. **Configure Jewellery Evaluator Settings** (Required)

   After installation, configure the module settings:

   - Go to **Settings** → **Jewellery Evaluator** (or search for "Jewellery Evaluator" in Settings)
   - Configure the following:

     **API Configuration:**
     - **Gold API Endpoint**: URL for fetching gold prices (GET request; response must be HTML/text with 200)
     - **Gold 21K Regex Formula**: Regular expression applied to the response to extract the 21K price per gram (use one capturing group for the number)
     - **Fallback Gold Price**: Price per gram when API is unavailable

     **Markup per Gram:**
     - **Jewellery (Local)** / **Jewellery (Foreign)**: One markup per gram each
     - **Bars (by weight tier)**: Eleven tiers (1g, 2.5g, 5g, 10g, 20g, 31g, 50g, 100g, 250g, 500g, 1000g+). Weights not in the list use the closest tier; weight >= 1000g uses the 1000g+ tier.

   **Alternative**: Use Odoo shell to set parameters:

   ```python
   # API Configuration
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.gold_api_endpoint', 'https://your-api.com/gold/price')
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.gold_21k_regex_formula', r'(\\d+(?:\\.\\d+)?)')  # example: one capturing group for the price number
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.fallback_price', '75.0')
   
   # Markup Configuration
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_jewellery_local', '5.0')
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_jewellery_foreign', '7.0')
   # Bars: weight-tiered (EGP per gram). Defaults: 1g/2.5g=200, 5g=125, 10g/20g=120, 31g=115, 50g/100g=100, 250g/500g/1000g+=80
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_bars_1g', '200.0')
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_bars_2_5g', '200.0')
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_bars_5g', '125.0')
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_bars_10g', '120.0')
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_bars_20g', '120.0')
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_bars_31g', '115.0')
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_bars_50g', '100.0')
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_bars_100g', '100.0')
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_bars_250g', '80.0')
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_bars_500g', '80.0')
   self.env['ir.config_parameter'].sudo().set_param('jewellery_evaluator.markup_bars_1000g', '80.0')
   ```

5. **Verify Cron Job**

   - Go to **Settings** → **Technical** → **Automation** → **Scheduled Actions**
   - Find "Update Gold Product Prices"
   - Ensure it's **Active** and scheduled to run every 10 minutes

## Usage

### Setting Up Gold Products

1. **Navigate to Products**

   - Go to **Inventory** → **Products** → **Products**

2. **Create or Edit Product**

   - Create a new product or open an existing one
   - Fill in standard product fields (name, category, etc.)

3. **Configure Gold Pricing Fields**

   - **Gold Weight (grams)**: Enter the weight of gold in grams (required)
   - **Gold Purity**: Select purity level (24K, 21K, 18K, 14K, 10K) (required)
   - **Gold Type**: Select type (Jewellery - Local, Jewellery - Foreign, or Bars) (required). Bars use weight-tiered markup.

4. **Automatic Calculations**

   Once weight, purity, and type are set:
   - Markup per gram is from settings: jewellery types use a single value; Bars use the weight-tier table (closest tier; 1000g+ uses 1000g tier)
   - `gold_cost_price` = (GoldPricePerGram × purity_factor) × weight
   - `markup_total` = markup_per_gram (from settings) × weight
   - `list_price` = cost_price + markup_total
   - `gold_min_sale_price` = cost_price + (markup_total × 0.5)
   - `standard_price` = cost_price

   **Note**: Products missing weight, purity, or type will be skipped during price updates.

### Mass Import and Export

Gold fields are standard `product.template` fields and are available in Odoo’s import/export tools by default.

**Recommended columns for import** (product template):
- `gold_weight_g`
- `gold_purity` (use technical values like `24K`, `21K`, `18K`, `14K`, `10K`)
- `gold_type` (use technical values: `jewellery_local`, `jewellery_foreign`, `bars`)
- `diamond_usd_price`

**Computed fields** (exportable but should not be imported):
- `gold_cost_price`
- `gold_min_sale_price`
- `is_gold_product`
- `is_diamond_product`

### Diamond Pricing and Exchange Rate

Diamond price input is in USD and converted to EGP for product prices:

`standard_price` and `list_price` (EGP) = `diamond_usd_price` × USD→EGP rate

Current implementation uses a placeholder USD→EGP rate of `50.0` in
`diamond.price.service.get_usd_to_egp_rate()`.

### Silver Pricing

Silver 999 price is set by the Selenium script (no regex). The script renders dahabmasr.com and reads the price from the XPath element.

- **Silver 999 Price (EGP/g)**: Set by `scripts/selenium_automation.py`. Run with ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD to push to Odoo.
- **Silver Markup per Gram (EGP/g)**: Markup per gram for silver products.

Formulas (same as gold structure):

- `silver_cost_price` = Silver 999 price per gram × weight
- `list_price` = cost + (markup × weight), rounded to nearest 50
- `silver_min_sale_price` = cost + (markup × weight × 0.7), rounded to nearest 50

### Price Updates

Prices are automatically updated every 10 minutes via cron job:

- **Gold**: Fetches latest gold price from configured API; updates all gold products in batches of 100.
- **Diamond**: Updates diamond product prices from USD and exchange rate.
- **Silver**: Uses stored price (set by Selenium script); updates all silver products.
- Logs execution details to Odoo logs.

**Manual Update** (if needed):

```python
# Via Odoo shell
self.env['gold.price.service'].update_all_gold_product_prices()
```

### POS Price Enforcement

The module enforces pricing rules at both backend and frontend levels:

**Backend Validation** (Cannot be bypassed):

- Validates order lines before order creation
- Blocks orders with prices below `gold_min_sale_price`
- Prevents discounts exceeding 50% of markup

**Frontend Validation** (User experience):

- Prevents setting prices below minimum
- Limits discount percentage automatically
- Shows clear error messages to POS users

**Discount Rules**:

- Maximum discount = 50% of markup value
- Final price must be ≥ `gold_min_sale_price`
- System automatically adjusts invalid discounts

## API Integration

### Gold Price API

The module fetches the 21K gold price by:

1. Sending a **GET** request to the URL configured in **Gold API Endpoint**
2. On **HTTP 200**, treating the response body as HTML/text
3. Applying the **Gold 21K Regex Formula** from settings to extract the price number (one capturing group recommended, e.g. `(\d+(?:\.\d+)?)` for the 21K price per gram)

No authentication (e.g. cookie) is sent; use a public or pre-authenticated URL if required.

### Error Handling

- If API is unavailable, module uses `jewellery_evaluator.fallback_price`
- All errors are logged to Odoo logs
- Cron job continues even if individual updates fail

## Purity Factors

The module uses the following purity factors:

| Purity | Factor | Description |

|--------|--------|-------------|
| 24K | 0.999 | 99.9% pure gold |
| 21K | 0.875 | 87.5% pure gold |
| 18K | 0.750 | 75.0% pure gold |
| 14K | 0.583 | 58.3% pure gold |
| 10K | 0.417 | 41.7% pure gold |

## Security

### Access Control

- **Jewellery Evaluator User**: Can view jewellery evaluation information
- **Jewellery Evaluator Manager**: Can configure pricing settings
- **System Administrators**: Can view cost prices (hidden from other users)

### Field Visibility

- `gold_cost_price`: Only visible to system administrators
- `gold_min_sale_price`: Visible to all users
- Other gold fields: Visible based on user permissions

## Performance Considerations

- **Batch Updates**: Products updated in batches of 100
- **Stored Computed Fields**: Prices are stored, not computed on-the-fly
- **Decimal Precision**: Uses Python Decimal for accurate calculations
- **Efficient Queries**: Only processes gold products (filtered by `is_gold_product`)

## Troubleshooting

### Prices Not Updating

1. **Check Cron Job Status**
   - Settings → Technical → Automation → Scheduled Actions
   - Verify "Update Gold Product Prices" is active

2. **Check API Configuration**
   - Verify `jewellery_evaluator.gold_api_endpoint` and `jewellery_evaluator.gold_21k_regex_formula` in System Parameters
   - Test API endpoint manually (GET; expect 200 and HTML/text)

3. **Check Logs**
   - Settings → Technical → Logging → Log Entries
   - Filter by "gold.price.service"

### POS Validation Errors

1. **Verify Product Configuration**
   - Ensure weight, purity, and markup are set
   - Check that `gold_min_sale_price` is calculated

2. **Check Discount Limits**
   - Maximum discount = 50% of markup
   - Final price must be ≥ minimum sale price

### API Connection Issues

1. **Test API Manually**

   ```bash
   curl -H "Cookie: YOUR_COOKIE" https://your-api.com/gold/price
   ```

2. **Check Fallback Price**
   - Verify `jewellery_evaluator.fallback_price` is set (optional, default: 75.0)
   - Module will use this if API fails

3. **Review Network Settings**
   - Ensure Odoo server can reach API endpoint
   - Check firewall rules

### Invoice report shows old columns (Type, Purity, etc.)

The invoice layout (Karat, Weight, no Type column) is defined only in `jewellery_evaluator/report/report_invoice_gold.xml`. If you still see old headers or columns after changing that file, Odoo is serving a **cached view** stored in the database; a server restart does not re-load report XML.

**To force the new layout:**

1. **Upgrade the module** so Odoo re-loads the report view:
   - **From the UI**: Apps → search "Jewellery Evaluator" → ⋮ menu → **Upgrade**.
   - **From the command line** (with Odoo stopped):  
     `odoo -u jewellery_evaluator -d YOUR_DATABASE --stop-after-init`  
     then start Odoo as usual.

2. **Optional**: Clear the report view cache for your database (Technical → User Interface → Views → search `report_invoice_document_gold`, open and Save to retrigger merge), or use **Settings → Technical → Database Structure → Views**, find the view and ensure it has the latest `arch` (upgrading the module does this).

3. Hard-refresh the browser (Ctrl+Shift+R or Cmd+Shift+R) when opening an invoice PDF so the browser does not serve an old copy.

## Pre-Deployment Checks

Before deploying to production, run the automated checks to ensure code quality:

### Quick Start

1. **Install development dependencies:**
   ```bash
   make install-dev
   # or
   pip install -r requirements-dev.txt
   ```

2. **Install git hooks (recommended):**
   ```bash
   ./scripts/install-git-hooks.sh
   ```
   This installs a pre-push hook that automatically runs checks before pushing.

3. **Run all checks manually:**
   ```bash
   make check
   # or
   ./scripts/ci.sh
   ```

### What Gets Checked

- **Linting**: Code style and common errors (via `ruff`)
- **Tests**: Unit tests for price parsing and computation logic (via `pytest`)
- **Type Checking**: Type annotations validation (via `mypy`)

### Manual Deployment Workflow

1. Make your changes locally
2. Run `make check` to verify everything passes
3. Commit and push to `main` branch
4. SSH into EC2 instance
5. Navigate to module directory: `cd /path/to/odoo/addons/jewellery_evaluator`
6. Pull latest changes: `git pull origin main`
7. Restart Odoo service (method depends on your setup)

### Automated Deployment (CI/CD)

The repository includes a GitHub Actions workflow (`.github/workflows/deploy.yml`) that:
1. Runs all checks on every push and pull request
2. Automatically deploys to EC2 when checks pass on `main` branch

#### Setup Instructions

1. **Configure GitHub Secrets** (Settings → Secrets and variables → Actions):
   - `EC2_HOST`: Your EC2 instance hostname or IP (e.g., `ec2-xxx.compute.amazonaws.com`)
   - `EC2_USER`: SSH username (e.g., `ec2-user`, `ubuntu`, `admin`)
   - `EC2_SSH_KEY`: Private SSH key content for EC2 access
   - `EC2_GIT_REPO_PATH`: Path to the repo on the server (where we pull and run the module), e.g. `/opt/odoo/custom-addons/jewellery_evaluator`
   **Deploy user sudo (required for auto upgrade + restart):** The remote script runs `sudo -u odoo odoo -u jewellery_evaluator --stop-after-init -c /etc/odoo.conf` then `sudo systemctl restart odoo`. On the EC2 instance, allow the deploy user to run these without a password:
   ```bash
   sudo visudo
   ```
   Add (adjust `ubuntu`, `odoo`, and paths if your setup differs):
   ```
   ubuntu ALL=(odoo) NOPASSWD: /usr/bin/odoo
   ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl restart odoo
   ```
   If `odoo` is not at `/usr/bin/odoo`, use the full path (e.g. `/opt/odoo/venv/bin/odoo`). Save and exit.

2. **Give the deploy user access to the repo path** (avoids "Permission denied" on `cd`):
   CI runs as `EC2_USER` (e.g. `ubuntu`) and must be able to `cd` into `EC2_GIT_REPO_PATH` and run `git pull` there.
   - **Option A (recommended):** On the EC2 instance, make the deploy user owner of the repo directory:
     ```bash
     sudo chmod o+x /opt /opt/odoo /opt/odoo/custom-addons
     sudo chown -R ubuntu:ubuntu /opt/odoo/custom-addons/jewellery_evaluator
     ```
   - **Option B (use sudo):** Run the remote deploy script with sudo so it can cd into a root-owned path (e.g. pass the script to `sudo bash -s`). Ensure the Odoo process user can read the files after update.

3. **Generate SSH Key** (if needed):
   ```bash
   ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_deploy
   # Add public key to EC2: ~/.ssh/github_deploy.pub → ~/.ssh/authorized_keys on EC2
   # Add private key to GitHub Secrets: EC2_SSH_KEY
   ```

4. **Test the Workflow**:
   - Push a small change to `main`
   - Check Actions tab in GitHub to see deployment progress
   - Verify deployment on EC2

#### Module install and upgrade

- **First install:** The module has `auto_install: False`. Install it once from Odoo **Apps** (Update Apps List, then install "Jewellery Evaluator"). Deploy only copies files; it does not install the module.
- **After deploy:** The script runs a module upgrade (`odoo -u jewellery_evaluator --stop-after-init`) then restarts Odoo (`systemctl restart odoo`) so code and manifest/data changes are applied.

#### Deployment Process

The automated deployment:
- Runs all pre-deployment checks first; deploys only if they pass
- SSHs to the server, `cd`s to `EC2_GIT_REPO_PATH`, runs `git pull --ff-only` (or rebase on failure)
- Stops Odoo, runs module upgrade (`odoo -u <module_name> --stop-after-init`), then restarts Odoo

#### Disabling Auto-Deploy

To disable automatic deployment but keep checks:
- Edit `.github/workflows/deploy.yml`
- Comment out or remove the `deploy` job
- Checks will still run on every push/PR

## Development

### Extending the Module

**Add Custom Purity Levels**:

Edit `models/product_template.py`:

```python
gold_purity = fields.Selection(
    selection=[
        # ... existing options ...
        ('22K', '22K (91.7% pure)'),
    ],
    # ...
)
```

Update purity factors in `_compute_gold_prices` and `update_gold_prices` methods.

**Modify Pricing Formula**:

Edit calculation logic in:

- `models/product_template.py` → `_compute_gold_prices()`
- `models/product_template.py` → `update_gold_prices()`

**Custom API Integration**:

Set **Gold API Endpoint** and **Gold 21K Regex Formula** in Settings to match your API (GET, 200 HTML). Use a regex with one capturing group for the 21K price number; no code change required.

## Testing

### Manual Testing Checklist

- [ ] Create gold product with weight, purity, markup
- [ ] Verify prices are calculated correctly
- [ ] Test cron job execution (manual trigger)
- [ ] Test POS order with valid price
- [ ] Test POS order with price below minimum (should fail)
- [ ] Test discount application (should respect limits)
- [ ] Verify cost price is hidden from non-admin users
- [ ] Test API fallback when API is unavailable

## Support

For issues or questions:

1. Check Odoo logs: Settings → Technical → Logging
2. Review cron job execution history
3. Verify API configuration and connectivity
4. Test with fallback price to isolate API issues

## License

**PROPRIETARY - ALL RIGHTS RESERVED**

This software is proprietary and confidential. All rights reserved.

Copyright (c) 2026 Revenax Digital Services, Mohamed A. Abdallah

See [LICENSE](LICENSE) file for full terms and conditions.

**Restrictions:**

- No copying, modification, or distribution without explicit written permission
- No reverse engineering or decompilation
- No removal of copyright notices
- Use is restricted to authorized installations only

## Version

17.0.2.0.0

## Author

**Mohamed A. Abdallah**  
Revenax Digital Services  
Website: <https://www.revenax.com/>

---

**Note**: This module is designed for self-hosted Odoo 17 installations. It is not compatible with Odoo Online or Odoo.sh without modifications.
