# AL3 Configuration Export Module

Powerful configuration snapshot and migration tool for Odoo. Export your entire Odoo instance configuration to Excel and/or installable modules.

## Features

### 📊 Excel Export
- **Menu-driven, 100% data-driven**: One sheet per Odoo root app (Sales, Accounting, Inventory…). Content is read live from the database by walking each app's **Configuration** menu branch — for every menu that opens a record list, the records of that model are dumped. Nothing is hard-coded per module, so the export reflects whatever is actually installed and configured.
- **Menu path included**: Each row carries the exact Odoo menu path (e.g. `Sales > Configuration > Sales Teams`) taken straight from the menu tree, plus the technical model name in the Notes column.
- **Live settings**: Each app's `res.config.settings` toggles are read live and attributed to the owning app only (no duplicate "Settings" sheets).
- **Cover Sheet**: Professional summary page with metadata
- **Data Validation**: Pre-configured dropdowns for Status, Migration Required, and Owner
- **Auto status**: `Done` when a value/record exists, `Not Started` when empty — ready for go-live tracking.

### 📦 Odoo Module Generation (XML-only)
- **Plug-and-Play Installation**: Export as an installable Odoo module (.zip) that can be installed on any Odoo instance
- **Odoo Online Compatible**: Pure XML data, no Python code — installable on Odoo Online
- **Smart Dependencies**: Auto-detects installed modules and includes them in generated module dependencies
- **Multiple Data Captures**:
  - Company settings (name, VAT, country, currency, etc.)
  - System parameters (ir.config_parameter)
  - res.config.settings live values
  - Accounting: Payment terms, Fiscal positions, Chart of Accounts
  - Sales: Order templates, Pricelists, Sales teams
  - Purchase: Vendor templates
  - Inventory: Warehouses, Locations, Product Categories, Operation Types, UoM
  - Manufacturing: BOMs, Workcenters, Routings
  - CRM: Stages, Lost reasons
  - Project: Task stages
  - HR: Leave types, Departments, Job positions
  - And more...

### 🎯 Optional Exports
- **Partners (Customers/Vendors)**: Export up to 200 customers and 200 vendors with full contact details
- **Products**: Export product templates with attributes (up to 500 products)

## Installation

```bash
pip install openpyxl
```

Then install the module via Apps menu: `Config Export`

## Usage

### 1. Open Config Export Wizard
Settings → Config Export → Export Configuration

### 2. Configure Export
- **Company**: Select which company to export (default: current company)
- **Include Cover Sheet**: Toggle for professional summary page
- **Export Partners**: Optionally include customer/vendor master data
- **Export Products**: Optionally include product catalog
- **Configuration Areas**: Auto-detected based on installed modules

### 3. Auto-Detect or Customize
- **🔍 Re-detect Installed Modules**: Re-scan for new modules
- **✔ Select All**: Include all available areas
- **✖ Clear All**: Deselect all areas

### 4. Generate Outputs

#### Generate Excel
- Click **📊 Generate Excel**
- Review in spreadsheet with formatted sheets per area
- Each row is a configuration item with:
  - Current value (read from database)
  - Best practice/recommendation
  - Data migration required? (Yes/No/Partial/TBD)
  - Owner (assignee)
  - Status (Not Started/In Progress/Done/N/A/Blocked)
  - Notes column

#### Generate Odoo Module
- Click **📦 Generate Module (XML)**
- Module is generated as ready-to-install .zip
- Can be installed on:
  - ✅ Self-hosted Odoo
  - ✅ Odoo Online
  - ✅ Multi-company Odoo instances
  - ✅ Different Odoo 19 databases

### 5. Download

- **Excel**: Click ⬇ Download Excel
- **Module**: Click ⬇ Download Module (.zip)

## Generated Module Structure

```
config_[company]_exported_YYYYMMDD_HHMM.zip
├── config_[company]_exported/
│   ├── __manifest__.py          # Module manifest (auto-generated)
│   ├── __init__.py              # (empty)
│   └── data/
│       ├── 01_company.xml       # Company settings
│       ├── 02_config_params.xml # System parameters
│       ├── 05_partners.xml      # Customers/vendors (optional)
│       ├── 06_products.xml      # Products (optional)
│       ├── 07_uom.xml           # Units of Measure
│       ├── 10_account.xml       # Payment terms, fiscal positions
│       ├── 20_sale.xml          # Sales templates
│       ├── 25_purchase.xml      # Purchase templates
│       ├── 30_stock.xml         # Warehouses, locations, categories
│       ├── 40_crm.xml           # CRM stages, lost reasons
│       ├── 50_project.xml       # Project task stages
│       ├── 60_leave.xml         # Leave types
│       ├── 70_maintenance.xml   # Maintenance teams
│       ├── 80_mrp.xml           # Workcenters, routings
│       └── 90_settings.xml      # res.config.settings values
```

## Data Exported by Area

### General
- Company legal name, CIPC registration, VAT number
- Country, currency, phone, email, website, address
- Timezone, active languages
- Internal users, 2FA policy
- Outgoing mail servers
- Installed applications

### Accounting
- Chart of accounts
- Tax rates (VAT, income tax, withholding)
- Journals (Bank, Cash, Sales, Purchase, Misc)
- Bank accounts
- Payment terms
- Fiscal positions / tax mapping
- Active currencies
- Period lock dates

### Sales
- Pricelists
- Sales teams
- Quotation templates
- Confirmed sales orders (count)

### Purchase
- Vendors (if export_partners=True)
- PO approval thresholds
- Purchase agreements

### Inventory
- Warehouses
- Internal locations (bins, storage areas)
- Product categories
- Product tracking (lot/serial)
- Reorder rules (min/max)
- Barcode status

### Manufacturing
- Bills of Materials
- Workcenters with capacity/efficiency
- Routings

### CRM
- Sales pipelines / teams
- Pipeline stages
- Lost reasons
- Leads/opportunities

### HR & Payroll
- Employee count
- Departments
- Job positions
- Contract types
- Active contracts
- Salary structures
- Salary rules (PAYE/UIF/SDL)
- Working schedules

### And more...
- Leave types, public holidays
- Expense categories
- Fleet vehicles, contracts
- Maintenance teams, equipment
- POS terminals
- Barcode/WMS status

## Use Cases

### 1. **Go-Live Preparation**
Export configuration from sandbox to staging/production with cover sheet tracking what's been configured.

### 2. **Multi-Site Rollout**
Export a reference site's configuration as a module, install on other sites to standardize setup.

### 3. **Disaster Recovery**
Keep configuration snapshots as versioned modules for quick restoration.

### 4. **Change Control**
Excel export serves as documentation for audit trail and approval workflows.

### 5. **Knowledge Transfer**
Hand off configuration to client with recommendations and best practices noted in Excel.

## Permissions

- **Users** (base.group_user): Can run export and read areas
- **System Administrators**: Full access to manage configuration areas
- **No Accounting/Sales Restrictions**: Uses `sudo()` to read across company boundaries where needed

## Technical Details

- **Dependencies**: base, mail + dynamic per installed modules
- **Models**: 
  - `al3.config.export` (TransientModel) - Wizard
  - `al3.config.area` (Model) - Configuration grouping
- **Safe Mode**: Reads only, never modifies data during export
- **Large Data Handling**: Graceful limits (max 200 partners, 500 products, 100 locations per export)
- **Error Handling**: Errors in one area don't block export; logged in Status column

## Troubleshooting

### Module Export Is Empty
1. Check "Installed Apps" count on form
2. Ensure areas are selected
3. Check error logs for SQL/permissions issues

### Excel Export Missing Data
1. Verify company is selected
2. Re-run "Re-detect Installed Modules"
3. Check SQL error logs

### Generated Module Won't Install
- Ensure Odoo version matches (19.0)
- Check module naming is valid (alphanumeric + underscores)
- Verify all dependencies are installed in target system

## Roadmap

- [ ] Template-based custom extractors per module
- [ ] Config comparison (before/after)
- [ ] Partial exports by area
- [ ] History tracking (timestamped versions)
- [ ] Excel → Module reverse import (read-back)

## License

LGPL-3

## Author

Muhammad Bintang
AL3 Team
