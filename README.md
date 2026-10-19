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


## V3.2 compact UI
Reduced typography, statistics cards, date headers, and calendar period tiles. Visual-only change; booking and branch logic untouched.


## V3.3 booking card navigation
Click or press Enter/Space on a booking card in the period popup to open the existing ycc.appointment form. Navigation waits for modal close; no new booking is created. Booking capacity logic unchanged.


## V3.4 — calendar visual improvements
Date navigation now displays Gregorian and Hijri ranges in two distinct lines with clear previous/next controls and a Today button. Confirmed appointment KPI is blue/purple rather than green (green remains available booking slots). No changes to appointment logic, capacity, or branch data.


## V3.5 Vehicle catalogs
Appointment form uses V3 `wo.car.manufactory` and `wo.car.types` with `header_id` domain and create context. Old `vehicle_model` remains nullable and read-only in the form for legacy records. Validation allows old text-only bookings, but new records must have either a selected type or legacy vehicle description (server-side compatibility). No changes to V3 models.


## V3.6 — Unfiltered vehicle types
All `wo.car.types` are visible, even those with no `header_id`. Creating a new type from the appointment passes `default_header_id` from the selected manufacturer. No automatic clearing or mismatched-manufacturer constraint is imposed on existing records.


## V3.7 Contact history
Contact history appears above Notes on the appointment form. Add Contact opens a popup
wizard which saves a new contact entry and updates the read-only next follow-up
date. Contact date/time is the actual communication timestamp; next follow-up
is a separate optional field. Existing records are retained.


## V4.1 QWeb hotfix
Compute spanCount in calendar.js rather than calling an inline JavaScript function from QWeb XML. Fixes QWeb2 SyntaxError Unexpected token [ on Odoo 13.


## V4.2 — automatic calendar updates and compact occupancy cards
The calendar re-queries the server every 10 seconds while visible and immediately
when the browser window regains focus. It only redraws on changed data, preserving
the calendar scroll position. The timer and focus handler are removed when the
calendar action is destroyed. Changes saved by other users also appear without
manually refreshing the browser (within the polling interval).
Statistics tiles are shorter. Occupied slot cells use their full width to
display a compact booking name and an extended-booking chip on one line.
This is a frontend-only change; appointment and capacity logic is unchanged.


## V4.3 — selected card design 12
Occupied calendar cards now use the modern white panel with a blue car icon, occupancy, customer chip, extra-booking count and extended booking indicator. Empty periods retain original color coding. Click action and 10-second refresh are unchanged.


V4.4: Restored week/month switch, and placed style 12 only inside the row.cells loop. Fixes undefined cell.css.


## V4.5 — approved lifecycle policy
- Arrived (`done`) bookings remain in occupancy and show a purple 'وصلت' badge
  on occupied calendar cards and in the period details popup.
- Past-period confirmed/arrived bookings remain visible for historical review.
- Cancelled, no-show and expired provisional bookings are excluded from
  occupancy display, while their database records and contact history remain.
- Confirmed KPI counts confirmed only (not arrived); arrived is shown separately
  in the period popup.
- Extended bookings follow these rules for each covered slot.
- Existing 10-second automatic refresh picks up changes without manual reload.
No changes to appointment state transitions, stored data or server-side capacity
rules were necessary because those already implement this policy.

## V4.6 — branch-wide capacity and multi-day bookings
- `ycc.branch.capacity` is the single authoritative branch capacity, editable in
  the configuration form header. Slot rows show this as a readonly related field.
- Existing slot capacity values are no longer authoritative; on upgrade all
  slot rows reflect the branch capacity (default 4 until configured).
- `ycc.appointment.end_date` is optional; empty means the same day as `date`.
- A booking occupies every configured working slot from its starting slot/date
  through its inclusive ending slot/date, including days in between. Non-working
  dates without configured slots do not create artificial capacity.
- The calendar fetches appointments that overlap the visible date range and
  renders a booking in each occupied date/slot cell. The modal shows the range.
- Capacity checks are serialized per branch to protect overlapping multi-day
  bookings from concurrent requests. Closed slots/dates cannot be newly booked.
- Lowering capacity below existing active occupancy is rejected.
- Existing single-day bookings remain compatible; no data migration required.


V4.7: Fixed missing ycc.exception.end_date field in config view; made appointment scheduling/vehicle/service optional while requiring customer and phone. Added read-only forecast buttons to appointment form and calendar popup. Work order forecast requires verified model/field mapping via ir.config_parameter keys: ycc.installation_order_model, ycc.installation_delivery_field, ycc.installation_state_field, ycc.installation_branch_field, ycc.installation_completed_values. Until configured the forecast explicitly warns that order data is unavailable; it does not falsely claim zero unfinished cars.


V4.8: Forecast directly uses qimamhd_wo_v3 model wo.installation.order.mst and fields delivery_date, order_date, state, branch_id, car_panel_no. Excludes completed/cancelled/draft orders; flags undated orders and warns about possible cross-system duplicates. No configurable model mapping required.


## V4.9 Customer-based occupancy forecast
The WO forecast uses `partner_id`/normalized customer names only, never car plates. It shows an order-by-order summary in the calendar popup, preserves overdue and undated active orders, and flags multiple active orders for the same customer instead of merging cars. The appointment form notification also shows aggregate counts. Matching a customer across modules is advisory and never automatically frees capacity.


V5: forecast now limits primary results to order_date <= selected day <= delivery_date; overdue and undated work orders are separated behind expandable details. Customer-name matching only; no plate matching. Forecast button is prominent in the calendar modal and appointment form. The appointment form opens a dedicated summary wizard instead of a long toast.


V5.1: Highlight selected-day delivery orders, collapse later-delivery orders in both calendar popup and appointment form forecast; overdue orders remain collapsed.


## V5.2 — forecast UI refinement
- Removed overdue and undated orders from forecast results, including their count queries and popup sections.
- Selected-day delivery stays visible with a subtle one-pixel border.
- Future delivery orders remain collapsed.
- Forecast summary and counters now describe only selected-day/future deliveries and arrivals.
