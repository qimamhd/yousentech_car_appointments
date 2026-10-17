# Yousen Car Care Appointments — Odoo 13

Standalone addon for PPF, tinting and detailing bookings, integrated with the existing `qimamhd_wo_v3` navigation.

## Installation

Place the **yousentech_car_appointments** folder directly under an Odoo 13 addons directory. Install `qimamhd_wo_v3` first, then update the Apps list and install this addon.

Menus:
- العناية بالسيارات → العمليات → تقويم المواعيد / المواعيد
- العناية بالسيارات → تهيئة النظام → تهيئة نظام المواعيد / خدمات المواعيد

The provisional hold defaults to 120 minutes. A scheduled job expires holds every 5 minutes. Calendar shows Gregorian/Hijri dates and period occupancy; clicking an open period displays the booked cars.

**Testing status:** Source package validated for Python/XML syntax only. Odoo 13 installation, UI and concurrency have not been runtime tested. Install on a test database before production.
