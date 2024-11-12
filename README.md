# rcb4

## Install

```bash
pip install rcb4
```
## Write firmware

Connect st-link and run the following command.

```bash
rcb4-write-firmware
```

## Change Servo ID

You can use ics-manager command to change servo id.

```bash
ics-manager
```

## Contributing

### Automatic Formatting
This repository uses `ruff` for both linting and formatting which is configured in `pyproject.toml`, you can run with:
```
pip install ruff
ruff format
ruff check --fix .
```

## For JSK Users

### Worm Gear Module Calibration Tool

`armh7-tools` provides a comprehensive solution for calibrating and managing worm gear modules connected via the `ARMH7Interface`.
It facilitates the calibration of worm gears, reading of calibrated sensor data, and real-time display of sensor and worm gear values.
Designed for flexibility, it supports operations like calibration data update and in-place modification of YAML configuration files.

#### YAML Configuration Format

The calibration tool requires an input YAML file for worm gear modules configuration. 
This file contains a list of worm gears with their associated parameters: `worm_id`, `servo_id`, `sensor_id`,
and initial magnetic encoder value `magenc_init`.
Each worm gear is represented by a line in the YAML file with its parameters encapsulated in curly braces and prefixed by a dash, indicating a list item in YAML syntax.

```
 - {worm_id: 0, servo_id: 0, sensor_id: 38, magenc_init: 6502}
 - {worm_id: 1, servo_id: 2, sensor_id: 40, magenc_init: 3039}
 - {worm_id: 3, servo_id: 6, sensor_id: 44, magenc_init: 9502}
```

#### Reading Worm Gear Modules's calibration data

```
armh7-tools read-calib [--device DEVICE] output_file_path
```

`--device`, `-d`: Specify the device port. (Default: None)
`output_file_path`: Path to output the YAML file with calibration data.


##### Example

```
armh7-tools read-calib ./worm_calib.yaml
```

#### Calibrate Worm Gear Modules

```
armh7-tools calibrate [--device DEVICE] file_path [--inplace] [--update] [--output OUTPUT]
```

`--device`, `-d`: Specify the device port. (Default: None)
`file_path`: Path to the input YAML file containing worm gear configurations.
`--inplace`, `-i`: Overwrite the input YAML file with calibration results. (Optional)
`--update`, `-u`: Ignore and overwrite the current magenc_init values in the input YAML. (Optional)
`--output`, `-o`: Specify a path to save the calibrated data if not overwriting in-place. (Optional)

##### Example

When the `update` option is specified, the current posture of the robot will be modified, 
and upon pressing the Enter key, the angle at that moment will be set as the zero point. 
Consequently, the `magenc_init` value will be updated and written to the board, 

```
armh7-tools calibrate ./worm_calib.yaml --update
```

#### Print Sensor Values

This command displays real-time sensor values in a table format.

```
armh7-tools print-sensor
+------|----------|--------------|--------------|--------------|--------------|----------|----------|----------|----------+
|   ID |   Magenc |   Proximity1 |   Proximity2 |   Proximity3 |   Proximity4 |   Force1 |   Force2 |   Force3 |   Force4 |
|------|----------|--------------|--------------|--------------|--------------|----------|----------|----------|----------|
|   19 |     7365 |            0 |            0 |            0 |            0 |     1240 |     1167 |     1083 |     1037 |
|   20 |     3042 |            0 |            0 |            0 |            0 |     1209 |     1106 |     1075 |     1025 |
|   21 |    13800 |            0 |            0 |            0 |            0 |     1230 |     1106 |     1064 |     1003 |
|   22 |     9512 |            0 |            0 |            0 |            0 |     1222 |     1144 |     1123 |     1085 |
|   23 |    14182 |            0 |            0 |            0 |            0 |     1238 |     1179 |     1083 |     1040 |
+------|----------|--------------|--------------|--------------|--------------|----------|----------|----------|----------+
```

#### Print Worm Values

Displays real-time worm gear values in a table format.

```
armh7-tools print-worm
+------------|-------------|---------------|------------------|-----------------+
|   servo_id |   sensor_id |   magenc_init |   magenc_present |   present_angle |
|------------|-------------|---------------|------------------|-----------------|
|          0 |          38 |          6502 |             7368 |      -19.0283   |
|          2 |          40 |          3039 |             3039 |       -0        |
|          6 |          44 |          9502 |             9513 |       -0.241699 |
|          8 |          46 |          9783 |            14170 |      -96.394    |
+------------|-------------|---------------|------------------|-----------------+
```
