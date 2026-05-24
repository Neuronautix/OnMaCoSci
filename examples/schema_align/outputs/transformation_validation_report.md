# Schema Alignment Review Report

**Pipeline Run**: example-sa-001
**Generated**: 2026-05-22T17:25:00.979091
**Total field mappings**: 27

**Coverage**: 100.0% (9/9 fields)
**Unmapped fields**: 0

---

## Field Mappings

### `<constant>` -> `measurements.bodyWeight.unit`

- **Operation**: `constant_assignment`
- **Confidence**: 0.80
- **Validation**: passed
- **Types**: None -> string
- **Constant value**: `g`

---

### `ActivityCount` -> `measurements.activity.date`

- **Operation**: `nested_path`
- **Confidence**: 0.51
- **Validation**: passed
- **Types**: integer -> string

**Warnings:**
- Datatype mismatch: source=integer, target=string. Conversion required.

**Adversarial Review**: medium -- review
- [medium] datatype_mismatch: Type mismatch: source=integer, target=string. Explicit conversion rule required.
- [medium] ambiguous_measurement: Field 'ActivityCount' appears to be a measurement count or index. Its definition, sampling context, and units require clarification before safe reuse.

---

### `Cage` -> `housing.cageIdentifier`

- **Operation**: `nested_path`
- **Confidence**: 0.90
- **Validation**: passed
- **Types**: string -> string

---

### `DeviceSerial` -> `animal.biologicalAttributes.sex`

- **Operation**: `nested_path`
- **Confidence**: 0.60
- **Validation**: passed
- **Types**: string -> string

---

### `Group` -> `study.experimentalGroup`

- **Operation**: `nested_path`
- **Confidence**: 0.90
- **Validation**: passed
- **Types**: string -> string

---

### `MouseID` -> `animal.biologicalAttributes.sex`

- **Operation**: `nested_path`
- **Confidence**: 0.60
- **Validation**: passed
- **Types**: string -> string

---

### `RecordingDate` -> `measurements.activity.date`

- **Operation**: `nested_path`
- **Confidence**: 0.90
- **Validation**: passed
- **Types**: string -> string

---

### `Sex` -> `animal.biologicalAttributes.sex`

- **Operation**: `nested_path`
- **Confidence**: 1.00
- **Validation**: passed
- **Types**: string -> string

---

### `Strain` -> `animal.biologicalAttributes.strain`

- **Operation**: `nested_path`
- **Confidence**: 1.00
- **Validation**: passed
- **Types**: string -> string

---

### `Weight_g` -> `housing.cageIdentifier`

- **Operation**: `nested_path`
- **Confidence**: 0.43
- **Validation**: passed
- **Types**: number -> string

**Warnings:**
- Datatype mismatch: source=number, target=string. Conversion required.

**Adversarial Review**: medium -- review
- [medium] datatype_mismatch: Type mismatch: source=number, target=string. Explicit conversion rule required.

---
