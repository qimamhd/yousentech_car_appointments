# Yousen Car Care Appointments — Odoo 13 (V2)

Independent addon. Requires installed `qimamhd_wo_v3` and its dependency `custom_branch_13`.

## Changes
- Appointment configuration references the existing `custom.branches` branch; one configuration per existing branch.
- Service is informational: no price field.
- Calendar shows days vertically and time slots horizontally, colored occupancy and colored statistics.
- Arabic/English layout direction follows the Odoo user language.
- A booking may cover one or more consecutive time slots using **Start Period** and **End Period**. All occupied slots are counted and capacity-checked atomically on the server. Multi-period bookings are marked in the calendar and shown in each occupied slot.
- Existing Odoo 13 car-care operations and settings menus are reused.

## Install
Extract the folder `yousentech_car_appointments` to the Odoo 13 addons path. Restart Odoo, update Apps and upgrade/install the module on a **test database first**.

## Important
This package has passed static Python, JavaScript syntax and XML parsing checks, but has NOT been tested on a live Odoo 13 database. Validate views, ACLs, reservations, simultaneous bookings and UI before production use.

If upgrading a prior version that has data in the old standalone `ycc.branch` table, do not upgrade directly: the new `branch_id` required field needs a migration mapping to `custom.branches`. Take a database backup and migrate those records first.

## V3.1 — Branch consistency fix
The canonical branch is `custom.branches` from V3. `ycc.branch` is only
per-branch appointment configuration, with a unique Many2one `branch_id`
pointing to `custom.branches`. The calendar reads the branch display label
from `config.branch_id.display_name`, never from a nonexistent `ycc.branch.name`.
The booking displays the canonical V3 branch using `custom_branch_id`
(a related field); it still stores its appointment configuration reference
for backward compatibility with existing reservations and slots.
After updating files, upgrade the addon with `-u yousentech_car_appointments`
and restart Odoo / refresh assets. Do not uninstall the addon.
