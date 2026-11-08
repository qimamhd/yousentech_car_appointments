# V6.63

- Fixed delivery-date changes from the appointment wizard by passing the explicit `ycc_delivery_change_reason` context expected by the installation-order write guard.
- Replaced free-text delivery-change reason with two required choices: customer delay and branch postponement.
- Added a stale-date check to prevent overwriting a delivery date changed by another user while the wizard was open.
- Kept all changes inside `yousentech_car_appointments`; `qimamhd_wo_v3` is not modified.
