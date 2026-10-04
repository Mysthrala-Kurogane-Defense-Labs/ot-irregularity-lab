# AI4EU robotic pump source review

## Scope

Assess whether a public pump dataset can support calibration of OT Irregularity Lab process profiles without treating a narrow demonstrator trace as a general industrial pump model.

## Sources

- [AI4EU robotic pump dataset (Zenodo DOI 10.5281/zenodo.5729187)](https://doi.org/10.5281/zenodo.5729187), metadata and dataset documentation. Zenodo metadata identifies CC BY 4.0, 34 files and 18.9 GB total.
- The dataset documentation describes a hydraulic pump demonstrator used for paint, controlled speed patterns, vibration at 6.14 kHz, and lower-rate channels including actual flow, rpm, torque, motor temperature, voltage and inlet/outlet pressure. The lower-rate process channels are interpolated to the vibration timestamps; some initial channel values are intentionally missing.
- A local sample inspection of `pump_export_20201125.csv.gz` (5,539,255 compressed bytes; not retained in the repository) found 122,880 rows across ten transition intervals. Each interval had 12,288 vibration samples and lasted about 12.92–12.97 s. The patterns covered 0→300, 300→0, 0→500, 500→0, 0→50 and 50→500 rpm. The sample contains missing lower-rate channels and timestamps about 163 microseconds apart, consistent with the documented high-rate vibration stream. This one file contains transition intervals only; it is not a representative survey of the full record.
- [DOE Variable Speed Pumping guide](https://www.energy.gov/sites/prod/files/2014/05/f16/variable_speed_pumping.pdf) explains affinity-law behavior for rotodynamic pumps and warns that proportional affinity approximations can be substantially wrong in systems with high static head.
- A separate [University of Oviedo cavitation dataset (Zenodo DOI 10.5281/zenodo.18500146)](https://doi.org/10.5281/zenodo.18500146) has a 69.4 MB record with pump curves, head/flow/NPSH and acoustic spectra. Its Zenodo API metadata says CC BY 4.0, but its included README says CC BY-NC-SA. This unresolved license conflict means it is excluded from calibration and redistribution until the rights holder or repository resolves it.

## Assessment

- The AI4EU record is an experimentally measured, versioned public source with a clear license declaration and several related sensor channels. It can inform later study of speed transitions and vibration behavior for this paint-pump demonstrator.
- It is not a centrifugal water-pump curve dataset, contains no labeled fault events, and the inspected file covers only ten controlled transitions. Lower-rate values are interpolated, so apparent sample count does not imply equivalent measurement bandwidth across tags.
- No source data or downloaded artifacts were copied into this repository. No pump profile parameters or anomaly behavior were changed from this review. Existing `centrifugal_vfd` affinity-law settings remain explicitly illustrative; DOE guidance reinforces the need to model system static head and operating curves before claiming calibrated behavior.

## Follow-up

Before deriving a profile from AI4EU, inspect the documentation and metadata for the remaining recording days, quantify operating-regime and missingness coverage across the complete public record, distinguish measured from interpolated channels, and fit transition dynamics only within the demonstrator's documented operating envelope. Keep the paint pump as a separately named profile if the data support it. Obtain clarification for the cavitation dataset license before adapting or redistributing anything derived from it.
