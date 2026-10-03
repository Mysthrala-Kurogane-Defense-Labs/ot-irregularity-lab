# Process models

These are low-cost engineering relationships for reproducible dataset generation, not high-fidelity plant or safety models. Each asset has load, actuator, temperature, and vibration states. Regime load is an input to coupled equations; noise perturbs sensor/process values and never replaces the process equations.

- CNC: load drives spindle speed, power, feed, coolant pressure, vibration, and thermal target; temperature follows a first-order lag.
- Pump: RPM drives flow; a simple system curve relates RPM/load to pressure; load and pressure drive current; motor temperature lags its target.
- Compressor: load drives current, pressure, discharge/oil temperatures, and vibration.
- Conveyor: load drives current, speed, temperature, vibration, and photoeye rate.

OFF, IDLE, WARMUP, LOW_LOAD, NORMAL_LOAD, HIGH_LOAD, COOLDOWN, and MAINTENANCE are scenario regime options. The baseline schedule has startup, load transitions/recipe changes, and shutdown. Add validated shift schedules and environmental profiles in the next phase.
