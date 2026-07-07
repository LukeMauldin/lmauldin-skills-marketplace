# Product Roadmap Custom Fields

Custom fields defined on the Product Roadmap list (`900600273627`).

## Apps Field

Primary field for filtering by application/team.

| Property | Value |
|----------|-------|
| Field Name | `👥 Apps` |
| Field ID | `039b4b60-e29b-4edc-a126-f465908feded` |
| Type | `drop_down` |

### Options

| Option | Option ID | Order |
|--------|-----------|-------|
| KS Coach | `fa89f94a-c15d-424c-a22c-1fd4280ee13a` | 0 |
| KSTV | `8d274314-9b65-4503-a60a-f692fe0c36b4` | 1 |
| KS Parent | `a5c027e8-17dd-46ef-8599-6aa8d4db2f61` | 2 |
| **Server** | `90ca02d6-0a54-4e1b-92ff-5463c56ba501` | 3 |
| Lighthouse | `e9774825-fad0-474d-81b4-3d6c9326d045` | 4 |
| After Class Email | `02e0df4f-edf3-4bc5-9458-796dab657500` | 5 |

**API Filter Example (Server):**
```json
{"field_id": "039b4b60-e29b-4edc-a126-f465908feded", "operator": "=", "value": "90ca02d6-0a54-4e1b-92ff-5463c56ba501"}
```

## Quarter Field

| Property | Value |
|----------|-------|
| Field Name | `🛠 Quarter` |
| Field ID | `c59a97ae-1ecc-44d4-9d7d-ca2009aaaf8b` |
| Type | `drop_down` |

### Options

| Option | Option ID | Order |
|--------|-----------|-------|
| Quarter 1 | `c5fc228a-ce9f-44cd-b7b3-68e87d1f2857` | 0 |
| Quarter 2 | `46dfcda3-b13c-4fa7-b2a0-f684921a96e9` | 1 |
| Quarter 3 | `81e38530-a3e5-4606-8cca-e6137ce4c67d` | 2 |
| Quarter 4 | `40ff1541-da0b-47f6-ac0f-09767ba6734a` | 3 |

## Stage Field

| Property | Value |
|----------|-------|
| Field Name | `🛠 Stage` |
| Field ID | `9a960487-3a1f-42e3-9578-91d9d66d158f` |
| Type | `drop_down` |

### Options

| Option | Option ID | Order |
|--------|-----------|-------|
| Planning | `473b00a4-3f02-490c-9ea9-c44f117c620c` | 0 |
| Design | `02f67bf1-e65a-4736-85ff-1c0871da17fe` | 1 |
| Picked Up | `f1fb1f59-42e8-4db2-90ae-4cf2bf4fdd0c` | 2 |
| Engineering | `3533e01a-ad8b-4d48-9a4e-3c54fe492b7e` | 3 |
| QA | `b201b0ae-f562-4d67-9dc5-8743b8247147` | 4 |
| Pending Release | `4091209a-30d1-4c8e-9392-4e01473f329e` | 5 |
| Released | `fe2a1cdf-c4ef-4bba-acd1-19781a196a24` | 6 |

## Year Field

| Property | Value |
|----------|-------|
| Field Name | `Year` |
| Field ID | `5482e720-7597-47cd-a56a-bb507afd67cb` |
| Type | `drop_down` |

### Options

| Option | Option ID | Order |
|--------|-----------|-------|
| 2024 | `4fdee6d1-5a0f-4181-af42-9d04a0379c0f` | 0 |
| 2025 | `afab50aa-f9e7-41d8-9a7a-42b5a8443ba5` | 1 |
| 2026 | `97eb520a-5719-4cfe-94e2-fff059b30a4e` | 2 |

## Uncertainty Rating Field

| Property | Value |
|----------|-------|
| Field Name | `Uncertainty Rating` |
| Field ID | `ab4e6b31-9145-4e0c-9a0e-988a7ae8be1e` |
| Type | `drop_down` |

### Options

| Option | Option ID | Order |
|--------|-----------|-------|
| Low | `4d06d571-35cd-4e22-b14d-6bd4048ccf8c` | 0 |
| Medium | `adaf251c-e351-4aef-805b-4a7767d2b73f` | 1 |
| High | `35ca39f5-b6f7-481c-994f-f958dc589bee` | 2 |
| Very High | `9e42c2e2-ff5a-4384-86c2-d5402d5430c0` | 3 |

## Bug Severity Field

| Property | Value |
|----------|-------|
| Field Name | `Bug Severity` |
| Field ID | `2d58aa4d-0219-4e91-8333-b57e1d324a3a` |
| Type | `drop_down` |

### Options

| Option | Option ID | Order |
|--------|-----------|-------|
| Low | `3203966e-b638-4b94-8aba-31be7b0b888a` | 0 |
| Medium | `ad0d327d-d3f1-41ed-88f9-9aede43da2a4` | 1 |
| High | `fd1e696b-1d14-4319-8496-10b32fb86068` | 2 |
| Urgent | `e73e5c89-278b-4ceb-8ebd-4ee6a10642dd` | 3 |

## QA Test Field

| Property | Value |
|----------|-------|
| Field Name | `QA Test` |
| Field ID | `1badac91-a8bf-49a6-aa1f-f1bcdbd5cb56` |
| Type | `drop_down` |

### Options

| Option | Option ID | Order |
|--------|-----------|-------|
| Pass | `4884722b-87d5-4b58-91f7-4b22dd7cf57f` | 0 |
| Fail | `c1419bef-6e2e-46ed-a45e-9b81950c4be5` | 1 |

## Text Fields

| Field Name | Field ID | Type |
|------------|----------|------|
| Rock | `9a32f8d2-bcf7-429d-86a0-6a95086f9c18` | `short_text` |
| Introduced Version | `3cfdbcc1-7935-4770-8e89-d951c2168e09` | `short_text` |
| Partner Department | `258d6d29-45db-415d-88d4-a4a8984234b5` | `short_text` |
| Release Version | `68088048-cf80-4221-8e46-fa7d71598836` | `short_text` |

## Reading Custom Field Values

When a task has a dropdown custom field set, the `value` property contains the **orderindex** (integer), not the option ID.

```python
def get_custom_field_value(task, field_name):
    """Extract custom field value by name."""
    for cf in task.get("custom_fields", []):
        # Strip emoji prefixes from field names
        cf_name = cf.get("name", "").replace("👥 ", "").replace("🛠 ", "")
        if cf_name.lower() == field_name.lower():
            value = cf.get("value")
            if value is None:
                return None

            # For dropdowns, value is orderindex - look up option name
            options = cf.get("type_config", {}).get("options", [])
            for opt in options:
                if opt.get("orderindex") == value:
                    return opt.get("name")

            return value
    return None

# Usage
apps_value = get_custom_field_value(task, "Apps")  # Returns "Server"
quarter = get_custom_field_value(task, "Quarter")  # Returns "Quarter 1"
```

## Setting Custom Field Values via API

When creating/updating tasks with custom fields:

```python
custom_fields = [
    {
        "id": "039b4b60-e29b-4edc-a126-f465908feded",  # Apps
        "value": "90ca02d6-0a54-4e1b-92ff-5463c56ba501"  # Server option ID
    },
    {
        "id": "c59a97ae-1ecc-44d4-9d7d-ca2009aaaf8b",  # Quarter
        "value": "c5fc228a-ce9f-44cd-b7b3-68e87d1f2857"  # Quarter 1 option ID
    }
]
```

Note: Use **option ID** (UUID) when setting values, but you'll receive **orderindex** (integer) when reading values.
