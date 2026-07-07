# GCP Billing Export Tables

Reference documentation for BigQuery billing export table schemas.

## Standard Billing Export

**Table**: `ksu-live.tech_billing_data.gcp_billing_export_v1_01F770_268BC9_B9A577`

### Key Columns

| Column | Type | Description |
|--------|------|-------------|
| `billing_account_id` | STRING | Billing account identifier |
| `service.id` | STRING | Service ID (e.g., "6F81-5844-456A") |
| `service.description` | STRING | Service name (e.g., "Cloud Run") |
| `sku.id` | STRING | SKU identifier |
| `sku.description` | STRING | SKU name (e.g., "Services CPU (Request-based billing)") |
| `usage_start_time` | TIMESTAMP | Start of usage period |
| `usage_end_time` | TIMESTAMP | End of usage period |
| `project.id` | STRING | GCP project ID |
| `project.name` | STRING | GCP project name |
| `cost` | FLOAT | Gross cost before credits |
| `currency` | STRING | Currency code (USD) |
| `credits` | ARRAY | Applied credits (promotions, discounts) |
| `usage.amount` | FLOAT | Usage quantity |
| `usage.unit` | STRING | Usage unit (bytes, requests, seconds) |
| `invoice.month` | STRING | Invoice month (YYYYMM) |
| `cost_type` | STRING | Type of cost (regular, tax, adjustment) |

### Credits Structure

```sql
-- Access credits array
SELECT
  cost,
  (SELECT SUM(c.amount) FROM UNNEST(credits) c) AS total_credits,
  cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0) AS net_cost
FROM billing_table
```

### Common Queries

```sql
-- Total costs by service for a period
SELECT
  service.description AS service,
  ROUND(SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS net_cost
FROM `ksu-live.tech_billing_data.gcp_billing_export_v1_01F770_268BC9_B9A577`
WHERE usage_start_time >= "2026-01-01"
  AND usage_start_time < "2026-01-08"
GROUP BY service
ORDER BY net_cost DESC;

-- Daily costs
SELECT
  DATE(usage_start_time) AS date,
  ROUND(SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS net_cost
FROM `ksu-live.tech_billing_data.gcp_billing_export_v1_01F770_268BC9_B9A577`
WHERE usage_start_time >= "2026-01-01"
GROUP BY date
ORDER BY date;
```

## Resource-Level Billing Export

**Table**: `ksu-live.tech_billing_data.gcp_billing_export_resource_v1_01F770_268BC9_B9A577`

Includes all columns from standard export plus resource-level attribution.

### Additional Columns

| Column | Type | Description |
|--------|------|-------------|
| `resource.name` | STRING | Full resource name/path |
| `resource.global_name` | STRING | Global resource identifier |
| `labels` | ARRAY | Resource labels |
| `system_labels` | ARRAY | System-assigned labels |
| `location.location` | STRING | Resource location |
| `location.region` | STRING | Resource region |
| `location.zone` | STRING | Resource zone |

### Resource Name Patterns

| Service | Resource Name Pattern |
|---------|----------------------|
| Cloud Run | `//run.googleapis.com/namespaces/{project}/services/{service}` |
| Cloud SQL | `//sqladmin.googleapis.com/projects/{project}/instances/{instance}` |
| GCE | `//compute.googleapis.com/projects/{project}/zones/{zone}/instances/{instance}` |
| GCS | `//storage.googleapis.com/buckets/{bucket}` |

### Extracting Service Names

```sql
-- Extract Cloud Run service name from resource
SELECT
  REGEXP_EXTRACT(resource.name, r"//run.googleapis.com/namespaces/[^/]+/services/(.+)") AS service_name,
  SUM(cost) AS cost
FROM resource_billing_table
WHERE service.description = "Cloud Run"
GROUP BY service_name;
```

## Common Service Identifiers

| Service | service.description | Common SKUs |
|---------|---------------------|-------------|
| Cloud Run | "Cloud Run" | Services CPU, Services Memory, Requests |
| Cloud Logging | "Cloud Logging" | Log Storage cost |
| Cloud Trace | "Cloud Trace" | Spans ingested |
| Cloud SQL | "Cloud SQL" | DB instance, Storage |
| Firestore | "App Engine" | Cloud Firestore Read/Write Ops |
| GCS | "Cloud Storage" | Standard Storage, Network Transfer |
| GCE | "Compute Engine" | Instance Core, Instance Ram, Network |

## Data Freshness

- **Export frequency**: Hourly incremental updates
- **Typical lag**: 24-48 hours for complete data
- **Check freshness**:

```sql
SELECT
  MAX(export_time) AS latest_export,
  MAX(usage_start_time) AS latest_usage
FROM `ksu-live.tech_billing_data.gcp_billing_export_v1_01F770_268BC9_B9A577`
WHERE usage_start_time >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY);
```

## Cost Calculation Notes

1. **Net Cost** = `cost` + `SUM(credits.amount)`
2. Credits are typically negative values
3. Some SKUs have $0 cost with usage (free tier)
4. Resource-level table may have rows where `resource.name` is NULL (aggregate entries)
