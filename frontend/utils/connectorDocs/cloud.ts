// Connection-setup documentation for cloud warehouses / BI / SaaS connectors.
// Authored against the REAL field_names in
// backend/app/schemas/data_sources/configs.py (config + the default credential
// variant). Keyed by connector TYPE (the registry / filename stem).
//
// Each field key below is an EXACT field_name the connect form posts. The form
// merges config-schema fields and credential-schema fields into one flat object,
// so both are documented here under `fields`.
import type { ConnectorDocMap } from './types'

export default {
  // ---------------------------------------------------------------------------
  // Google BigQuery — service-account JSON key (default) or delegated OAuth.
  // config: project_id, dataset, maximum_bytes_billed, use_query_cache
  // creds:  credentials_json, oauth_client_id, oauth_client_secret
  // ---------------------------------------------------------------------------
  bigquery: {
    overview:
      'Google BigQuery is queried with a Google Cloud service account. You create a ' +
      'service account, give it the BigQuery Data Viewer + Job User roles, download its ' +
      'JSON key, and paste the WHOLE key here. (Optional delegated OAuth lets each user ' +
      'sign in with their own Google account instead.)',
    prerequisites: [
      'A GCP project with the BigQuery API enabled.',
      'A service account in that project: GCP Console → IAM & Admin → Service Accounts → Create service account.',
      'Grant it roles: BigQuery Data Viewer (read tables) + BigQuery Job User (run queries) on the project — IAM & Admin → IAM → Grant access.',
      'Create a JSON key for it: Service Accounts → (your SA) → Keys → Add key → Create new key → JSON, and download the file.',
    ],
    fields: {
      project_id: {
        what: 'The GCP project that holds the datasets you want to query (this is the BILLING/compute project — queries run and are billed here).',
        where: 'GCP Console → top project picker, or Dashboard → "Project ID" (NOT the project NAME/number).',
        example: 'my-analytics-prod',
        gotcha: 'Use the project ID (lowercase, may have a -number suffix), not the friendly project name.',
        required: true,
      },
      dataset: {
        what: 'The BigQuery dataset(s) to expose. A dataset is the schema/namespace that contains tables.',
        where: 'BigQuery Studio → Explorer pane → under your project, each dataset is listed.',
        example: 'analytics_prod  (or comma-separated: sales,marketing)',
        gotcha: 'Comma-separated is allowed for multiple datasets; the first is the primary.',
        required: true,
      },
      credentials_json: {
        what: 'The ENTIRE service-account JSON key file, pasted as text (it contains private_key, client_email, project_id, etc.).',
        where: 'GCP Console → IAM & Admin → Service Accounts → (your SA) → Keys → Add key → Create new key → JSON → open the downloaded file and copy ALL of it.',
        steps: [
          'IAM & Admin → Service Accounts → Create service account (or pick an existing one).',
          'Grant roles BigQuery Data Viewer + BigQuery Job User.',
          'Open the SA → Keys → Add key → Create new key → JSON → download.',
          'Open the .json file in a text editor and paste the full contents into this field.',
        ],
        example: '{"type":"service_account","project_id":"my-analytics-prod","private_key":"-----BEGIN PRIVATE KEY-----\\n...","client_email":"bq-reader@my-analytics-prod.iam.gserviceaccount.com", ...}',
        gotcha: 'Paste the COMPLETE JSON (starts with { and includes the multi-line private_key). A path or just the client_email will fail.',
        required: true,
      },
      maximum_bytes_billed: {
        what: 'Optional hard cap on bytes scanned per query — a cost guardrail. Queries exceeding it are rejected by BigQuery.',
        example: '1000000000  (≈ 1 GB)',
        gotcha: 'Leave blank to disable the cap. Value is in bytes.',
        required: false,
      },
      use_query_cache: {
        what: 'Whether to allow BigQuery to return cached results when the same query was run recently (faster, cheaper).',
        example: 'true',
        required: false,
      },
      oauth_client_id: {
        what: 'Optional. Google OAuth 2.0 Client ID, only if you want users to sign in with their own Google account (delegated access) instead of the service account.',
        where: 'GCP Console → APIs & Services → Credentials → OAuth 2.0 Client IDs.',
        required: false,
      },
      oauth_client_secret: {
        what: 'Optional. The OAuth 2.0 Client Secret paired with the OAuth Client ID above (delegated sign-in only).',
        where: 'GCP Console → APIs & Services → Credentials → (your OAuth client) → Client secret.',
        required: false,
      },
    },
    troubleshooting: [
      '403 "Access Denied: ... permission bigquery.jobs.create" → the service account is missing the BigQuery Job User role.',
      '403 on a specific table/dataset → grant BigQuery Data Viewer on that dataset (or the project).',
      '"Could not parse credentials" / invalid JSON → you pasted a partial key or a file path; paste the whole JSON.',
      'Dataset not found → check the dataset is in the SAME project as project_id, or qualify it.',
      '"Quota exceeded: bytes billed" → your maximum_bytes_billed cap is too low for the query.',
    ],
    docsUrl: 'https://cloud.google.com/iam/docs/keys-create-delete',
  },

  // ---------------------------------------------------------------------------
  // Snowflake — username/password (default) or key-pair.
  // config: account, warehouse, database, schema, role
  // creds (userpass): user, password
  // creds (keypair):  user, private_key_pem, private_key_passphrase
  // ---------------------------------------------------------------------------
  snowflake: {
    overview:
      'Snowflake is queried with a user that has a role granting access to a warehouse, ' +
      'database and schema. Authenticate with username/password, or (more secure) an RSA ' +
      'key pair. Best practice: create a dedicated read-only role + user with ACCOUNTADMIN.',
    prerequisites: [
      'Find your account identifier (account locator or org-account) — see the account field.',
      'A running warehouse the user can USE (compute).',
      'A role granting USAGE on the warehouse/database/schema and SELECT on the tables. As ACCOUNTADMIN: CREATE ROLE analytics_ro; GRANT USAGE ON WAREHOUSE … / DATABASE … / SCHEMA … TO ROLE analytics_ro; GRANT SELECT ON ALL TABLES IN SCHEMA … TO ROLE analytics_ro; then GRANT ROLE analytics_ro TO USER …',
      'For key-pair auth: generate an RSA key, ALTER USER … SET RSA_PUBLIC_KEY=… (see private_key_pem).',
    ],
    fields: {
      account: {
        what: 'The Snowflake account identifier — the unique part of your Snowflake URL.',
        where: 'Snowsight → bottom-left account menu → Account → "Account/Server URL"; or the host in your login URL https://<account>.snowflakecomputing.com.',
        example: 'ABCDEF-GH12345   (org-account)   or   xy12345.us-east-1 (legacy locator+region)',
        gotcha: 'Preferred format is ORG-ACCOUNT (e.g. MYORG-MYACCT). Do NOT include .snowflakecomputing.com. If using a legacy locator, append the region/cloud (e.g. xy12345.us-east-1).',
        required: true,
      },
      warehouse: {
        what: 'The virtual warehouse (compute) used to run queries. The user must have USAGE on it.',
        where: 'Snowsight → Admin → Warehouses; or run SHOW WAREHOUSES.',
        example: 'ANALYTICS_WH',
        required: true,
      },
      database: {
        what: 'The database to query.',
        where: 'Snowsight → Data → Databases; or SHOW DATABASES.',
        example: 'PROD_DB',
        required: true,
      },
      schema: {
        what: 'The schema inside the database that holds the tables.',
        where: 'Snowsight → Data → (database) → Schemas; or SHOW SCHEMAS IN DATABASE PROD_DB.',
        example: 'PUBLIC   (or comma-separated: SALES,MARKETING)',
        gotcha: 'A comma-separated list of schemas is allowed.',
        required: true,
      },
      role: {
        what: 'Optional. The Snowflake role to assume for this connection (controls what is visible/queryable).',
        where: 'Snowsight → Admin → Users & Roles → Roles; or SHOW ROLES.',
        example: 'ANALYTICS_RO',
        gotcha: 'If blank, the user’s DEFAULT role is used — which may not have access to the warehouse/database above.',
        required: false,
      },
      user: {
        what: 'The Snowflake login name of the service/user account (username/password auth).',
        example: 'SVC_ANALYTICS',
        required: true,
      },
      password: {
        what: 'That user’s password (username/password auth).',
        gotcha: 'If your org enforces MFA/SSO on this user, password auth may be blocked — use key-pair auth instead.',
        required: true,
      },
      private_key_pem: {
        what: 'Key-pair auth only. The PEM-encoded RSA PRIVATE key for the user.',
        where: 'Generate with openssl: openssl genrsa 2048 → derive the public key → ALTER USER <user> SET RSA_PUBLIC_KEY=\'<pubkey>\'. Paste the matching PRIVATE key here.',
        example: '-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----',
        gotcha: 'Use this INSTEAD of password. The user’s RSA_PUBLIC_KEY in Snowflake must match this private key.',
        required: false,
      },
      private_key_passphrase: {
        what: 'Key-pair auth only. The passphrase that decrypts the private key, if it was generated encrypted.',
        gotcha: 'Leave blank if the private key is unencrypted.',
        required: false,
      },
    },
    troubleshooting: [
      '"Incorrect username or password" → wrong user/password, or MFA/SSO is enforced (switch to key-pair).',
      '250001 "Could not connect ... account" → wrong account format; use ORG-ACCOUNT or locator.region, no .snowflakecomputing.com.',
      '"Object does not exist or not authorized" → the role lacks USAGE/SELECT; grant on warehouse, database, schema and tables.',
      '"No active warehouse selected" → set the warehouse field and ensure the role has USAGE on it.',
      'JWT/key errors on key-pair → the user’s RSA_PUBLIC_KEY does not match the private key you pasted.',
    ],
    docsUrl: 'https://docs.snowflake.com/en/user-guide/admin-account-identifier',
  },

  // ---------------------------------------------------------------------------
  // AWS Redshift — userpass (default) / IAM keys / assume-role.
  // config: host, port, database, schema, region, cluster_identifier, ssl_mode, timeout
  // creds (userpass): user, password
  // creds (iam):      user, access_key, secret_key
  // creds (arn):      user, role_arn
  // ---------------------------------------------------------------------------
  aws_redshift: {
    overview:
      'Amazon Redshift is queried over its Postgres-compatible endpoint. Authenticate with ' +
      'a database username/password, or with AWS IAM (access keys, or an assumed role) to ' +
      'get temporary DB credentials. Use a read-only DB user/group.',
    prerequisites: [
      'The cluster endpoint host + port (default 5439) — AWS Console → Redshift → Clusters → (cluster) → General information → Endpoint.',
      'A database + a DB user with SELECT (CREATE USER analytics PASSWORD …; GRANT USAGE ON SCHEMA public TO analytics; GRANT SELECT ON ALL TABLES IN SCHEMA public TO analytics;).',
      'Network reachability: the cluster security group must allow inbound from this server’s IP, and (if private) the cluster must be reachable.',
      'For IAM auth: an IAM user/role with redshift:GetClusterCredentials, plus the region + cluster identifier.',
    ],
    fields: {
      host: {
        what: 'The Redshift cluster (or serverless workgroup) endpoint hostname.',
        where: 'AWS Console → Redshift → Clusters → (cluster) → General information → Endpoint (the part before :5439/db).',
        example: 'my-cluster.abc123xyz.us-east-1.redshift.amazonaws.com',
        gotcha: 'Host only — drop the :5439 and /dbname that AWS shows in the full endpoint string.',
        required: true,
      },
      port: {
        what: 'The Redshift port.',
        example: '5439',
        required: true,
      },
      database: {
        what: 'The database name to connect to.',
        where: 'Redshift query editor; or the database created at cluster setup (often "dev").',
        example: 'analytics',
        required: true,
      },
      schema: {
        what: 'The schema holding the tables.',
        example: 'public',
        required: true,
      },
      region: {
        what: 'AWS region of the cluster. Required for IAM/assume-role auth (used to fetch temporary credentials).',
        where: 'AWS Console top-right region selector, or in the endpoint host (…us-east-1.redshift…).',
        example: 'us-east-1',
        gotcha: 'Optional for plain username/password; REQUIRED for IAM and assume-role auth.',
        required: false,
      },
      cluster_identifier: {
        what: 'The cluster identifier (the short cluster name), used by IAM auth to call GetClusterCredentials.',
        where: 'AWS Console → Redshift → Clusters → the "Cluster" name column.',
        example: 'my-cluster',
        gotcha: 'Only needed for IAM/assume-role auth.',
        required: false,
      },
      ssl_mode: {
        what: 'TLS mode for the connection.',
        example: 'require',
        gotcha: 'Keep "require" unless you have a specific reason; Redshift supports TLS by default.',
        required: false,
      },
      timeout: {
        what: 'Connection timeout in seconds.',
        example: '30',
        required: false,
      },
      user: {
        what: 'The Redshift database username (all auth modes use this — for IAM it is the DB user the temporary credentials are issued for).',
        example: 'analytics',
        required: true,
      },
      password: {
        what: 'The database user’s password (username/password auth).',
        gotcha: 'Not used for IAM / assume-role auth.',
        required: true,
      },
      access_key: {
        what: 'IAM auth. AWS access key ID of an IAM user allowed to call redshift:GetClusterCredentials.',
        where: 'AWS Console → IAM → Users → (user) → Security credentials → Access keys.',
        example: 'AKIAIOSFODNN7EXAMPLE',
        required: false,
      },
      secret_key: {
        what: 'IAM auth. The AWS secret access key paired with the access key above.',
        where: 'Shown ONCE when you create the access key in IAM → save it then.',
        required: false,
      },
      role_arn: {
        what: 'Assume-role auth. The ARN of an IAM role to assume for temporary credentials.',
        where: 'AWS Console → IAM → Roles → (role) → ARN.',
        example: 'arn:aws:iam::123456789012:role/redshift-reader',
        required: false,
      },
    },
    troubleshooting: [
      'Connection timeout → the cluster security group doesn’t allow this server’s IP on port 5439, or the cluster is in a private subnet.',
      '"password authentication failed" → wrong DB user/password.',
      'IAM "not authorized to perform redshift:GetClusterCredentials" → attach that permission and set region + cluster_identifier.',
      '"database … does not exist" → wrong database name (often it’s "dev", not the friendly name).',
      'SSL errors → keep ssl_mode = require.',
    ],
    docsUrl: 'https://docs.aws.amazon.com/redshift/latest/mgmt/generating-iam-credentials-cli-api.html',
  },

  // ---------------------------------------------------------------------------
  // AWS Athena — default IAM chain (no creds) or access keys.
  // config: region, database, workgroup, s3_output_location, data_source
  // creds (default): none
  // creds (key):     access_key, secret_key, role_arn
  // ---------------------------------------------------------------------------
  aws_athena: {
    overview:
      'Amazon Athena runs SQL over data in S3 via the Glue Data Catalog. By default it uses ' +
      'the server’s ambient AWS credentials (instance profile / env / IRSA); or supply AWS ' +
      'access keys + a role to assume. Athena MUST have a place in S3 to write query results.',
    prerequisites: [
      'A Glue/Athena database + tables (the AwsDataCatalog) — AWS Console → Athena → Query editor → Database dropdown.',
      'An S3 bucket for query results, and Athena permission to write there (set it on the workgroup, or in s3_output_location).',
      'IAM permissions: athena:StartQueryExecution/GetQueryResults, glue:Get* on the catalog, and s3:GetObject/PutObject on the data + output buckets.',
      'For access-key auth: an IAM user’s access key/secret (and optionally a role ARN to assume).',
    ],
    fields: {
      region: {
        what: 'AWS region where Athena, the Glue catalog and the data live.',
        where: 'AWS Console top-right region selector.',
        example: 'us-east-1',
        required: true,
      },
      database: {
        what: 'The Athena/Glue database (schema) that contains your tables.',
        where: 'AWS Console → Athena → Query editor → Database dropdown.',
        example: 'analytics_db',
        required: true,
      },
      workgroup: {
        what: 'The Athena workgroup to run queries in (controls output location, limits, and billing).',
        where: 'AWS Console → Athena → Workgroups.',
        example: 'primary',
        gotcha: 'Defaults to "primary". If the workgroup enforces an output location, you may leave s3_output_location blank.',
        required: false,
      },
      s3_output_location: {
        what: 'The S3 URI where Athena writes query results.',
        where: 'Pick any bucket/prefix Athena can write to: s3://<your-bucket>/athena-results/.',
        example: 's3://my-athena-results/queries/',
        gotcha: 'REQUIRED unless your workgroup already has a default result location configured. Athena fails every query without an output location somewhere.',
        required: false,
      },
      data_source: {
        what: 'The Athena data source / catalog name.',
        example: 'AwsDataCatalog',
        gotcha: 'Leave as AwsDataCatalog unless you use a federated/custom catalog.',
        required: false,
      },
      access_key: {
        what: 'Access-key auth only. AWS access key ID of an IAM user with Athena/Glue/S3 permissions.',
        where: 'AWS Console → IAM → Users → (user) → Security credentials → Access keys.',
        example: 'AKIAIOSFODNN7EXAMPLE',
        gotcha: 'Omit entirely to use the server’s default AWS credential chain (instance profile / env vars / IRSA).',
        required: false,
      },
      secret_key: {
        what: 'Access-key auth only. The secret access key paired with the access key above.',
        where: 'Shown once at access-key creation in IAM.',
        required: false,
      },
      role_arn: {
        what: 'Access-key auth. The IAM role ARN to assume after authenticating with the keys (scoped Athena access).',
        where: 'AWS Console → IAM → Roles → (role) → ARN.',
        example: 'arn:aws:iam::123456789012:role/athena-reader',
        required: false,
      },
    },
    troubleshooting: [
      '"No output location provided" / InvalidRequestException → set s3_output_location, or configure a default on the workgroup.',
      'AccessDenied on s3:PutObject → the identity can’t write to the results bucket.',
      '"Database does not exist" → wrong database name or wrong region (the Glue catalog is regional).',
      'glue:GetTable AccessDenied → add Glue catalog read permissions to the IAM identity.',
      'Default-chain auth returns no credentials → either run on an instance/role with a profile, or switch to the access-key auth variant.',
    ],
    docsUrl: 'https://docs.aws.amazon.com/athena/latest/ug/querying.html',
  },

  // ---------------------------------------------------------------------------
  // Databricks SQL — Personal Access Token.
  // config: server_hostname, http_path, catalog, schema
  // creds:  access_token
  // ---------------------------------------------------------------------------
  databricks_sql: {
    overview:
      'Databricks SQL connects to a SQL Warehouse using a Personal Access Token (PAT). You ' +
      'point it at the workspace hostname + the warehouse’s HTTP path, pick a Unity Catalog, ' +
      'and authenticate with a PAT minted by a user that can use the warehouse.',
    prerequisites: [
      'A running SQL Warehouse — Databricks workspace → SQL → SQL Warehouses.',
      'A Personal Access Token — Settings → Developer → Access tokens → Generate new token.',
      'The token’s user must have CAN USE on the warehouse and SELECT on the catalog/schema (Unity Catalog grants).',
    ],
    fields: {
      server_hostname: {
        what: 'The Databricks workspace hostname.',
        where: 'Workspace URL (https://<hostname>), or SQL Warehouses → (warehouse) → Connection details → Server hostname.',
        example: 'abc-12345678-9abc.cloud.databricks.com',
        gotcha: 'Host only — no https:// prefix, no path.',
        required: true,
      },
      http_path: {
        what: 'The HTTP path of the specific SQL Warehouse to query.',
        where: 'SQL → SQL Warehouses → (warehouse) → Connection details → HTTP path.',
        example: '/sql/1.0/warehouses/abc123def456',
        gotcha: 'This must be a SQL Warehouse path (starts with /sql/1.0/warehouses/), not an all-purpose cluster path.',
        required: true,
      },
      catalog: {
        what: 'The Unity Catalog to query (the top level of catalog.schema.table).',
        where: 'SQL editor → Catalog dropdown, or Catalog Explorer.',
        example: 'main',
        required: true,
      },
      schema: {
        what: 'Optional. The schema inside the catalog. Leave blank to discover all schemas in the catalog.',
        example: 'default   (or comma-separated: sales,marketing)',
        gotcha: 'Comma-separated list allowed; empty = all schemas.',
        required: false,
      },
      access_token: {
        what: 'A Databricks Personal Access Token (the credential).',
        where: 'Databricks → Settings → Developer → Access tokens → Generate new token (copy it immediately).',
        steps: [
          'Click your avatar → Settings.',
          'Developer → Access tokens → Manage → Generate new token.',
          'Set a comment + lifetime, generate, and copy the dapi… value.',
        ],
        example: 'dapiXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX',
        gotcha: 'Shown only once. Starts with "dapi". If "Personal access tokens" is disabled by the admin, enable it in workspace settings first.',
        required: true,
      },
    },
    troubleshooting: [
      '403 / "Invalid access token" → token expired or revoked; generate a new PAT.',
      '"HTTP path" errors → you used a cluster path; use the SQL Warehouse HTTP path.',
      'Warehouse cold-start → first query may be slow while the warehouse starts; it then speeds up.',
      'Table not found / permission denied → grant the token’s user SELECT on the catalog/schema in Unity Catalog.',
      'Hostname errors → drop https:// and any trailing path; host only.',
    ],
    docsUrl: 'https://docs.databricks.com/en/integrations/compute-details.html',
  },

  // ---------------------------------------------------------------------------
  // Microsoft Fabric — Service Principal (default) or delegated OAuth.
  // config: server_hostname, database, schema
  // creds:  tenant_id, client_id, client_secret, oauth_client_id, oauth_client_secret
  // (detail mirrors mockup-connector-help.html)
  // ---------------------------------------------------------------------------
  ms_fabric: {
    overview:
      'Microsoft Fabric (Warehouse / Lakehouse SQL analytics endpoint) authenticates with a ' +
      'Service Principal — an Entra ID (Azure AD) app registration. Register the app once to ' +
      'get Tenant ID, Client ID and Client Secret, then grant that app access to the Fabric ' +
      'workspace and fill the 3 connection fields. (Optional delegated OAuth lets each user ' +
      'sign in with Microsoft instead.)',
    prerequisites: [
      'Register an app: Azure portal → Microsoft Entra ID → App registrations → New registration. This yields the Tenant ID, Client ID and (after adding one) a Client Secret.',
      'Grant the app access in Fabric: open the workspace → Manage access → add the app as Member/Contributor.',
      'A Fabric admin must enable the tenant setting "Service principals can use Fabric APIs" (Fabric/Power BI Admin portal → Tenant settings).',
      'Have your Warehouse/Lakehouse name + its SQL analytics endpoint host ready.',
    ],
    fields: {
      server_hostname: {
        what: 'The SQL analytics endpoint host of your Warehouse / Lakehouse.',
        where: 'Fabric portal → open your Warehouse (or Lakehouse) → Settings (⚙) → SQL analytics endpoint → copy the host from the SQL connection string.',
        example: 'abc123xyz.datawarehouse.fabric.microsoft.com',
        gotcha: 'Use only the host — drop any ,1433 port or database suffix that the connection string includes.',
        required: true,
      },
      database: {
        what: 'The Warehouse or Lakehouse name, exactly as it appears in your Fabric workspace.',
        where: 'Fabric workspace → the item name next to the Warehouse/Lakehouse icon.',
        example: 'SalesWarehouse',
        required: true,
      },
      schema: {
        what: 'Optional. A schema, or comma-separated list of schemas, to expose. Empty = discover all schemas.',
        example: 'dbo   (or: dbo,staging)',
        required: false,
      },
      tenant_id: {
        what: 'Your Azure / Entra directory (tenant) GUID.',
        where: 'Azure portal → Microsoft Entra ID → Overview → Tenant ID (also on your app’s Overview as "Directory (tenant) ID").',
        example: '72f988bf-86f1-41af-91ab-2d7cd011db47',
        required: true,
      },
      client_id: {
        what: 'The app registration’s Application (client) ID.',
        where: 'Azure portal → Microsoft Entra ID → App registrations → (your app) → Overview → Application (client) ID.',
        example: '11111111-2222-3333-4444-555555555555',
        required: true,
      },
      client_secret: {
        what: 'A client secret VALUE for the app registration (the service-principal password).',
        where: 'Azure portal → App registrations → (your app) → Certificates & secrets → Client secrets → New client secret → copy the Value.',
        steps: [
          'App registrations → (your app) → Certificates & secrets → New client secret → copy the VALUE (not the Secret ID).',
          'Then grant access in Fabric: Workspace → Manage access → add the app as Member/Contributor.',
          'A Fabric admin enables tenant setting "Service principals can use Fabric APIs".',
        ],
        gotcha: 'Copy the secret VALUE immediately — it is hidden after you leave the page. 90% of Test Connection failures are the SP not being granted workspace access, or that tenant setting being off.',
        required: true,
      },
      oauth_client_id: {
        what: 'Optional. App Registration Client ID used for delegated user sign-in (authorization code flow). Falls back to Client ID above if blank.',
        where: 'Same App registrations Overview as client_id (can be a separate app for user sign-in).',
        required: false,
      },
      oauth_client_secret: {
        what: 'Optional. The secret for the delegated-sign-in app. Falls back to Client Secret above if blank.',
        where: 'Certificates & secrets of the OAuth app registration.',
        required: false,
      },
    },
    troubleshooting: [
      'Test Connection fails → 90% of the time the service principal was not granted access to the workspace/warehouse (Manage access), or the tenant setting "Service principals can use Fabric APIs" is off.',
      'AADSTS7000215 "Invalid client secret" → you pasted the Secret ID instead of the secret Value, or it expired.',
      'Login/host errors → use only the SQL analytics endpoint host (no ,1433 port, no database suffix).',
      'AADSTS700016 "application not found in directory" → wrong tenant_id or client_id.',
      'Schema empty → confirm the SP has access to objects in the warehouse/lakehouse, not just the workspace.',
    ],
    docsUrl: 'https://learn.microsoft.com/en-us/fabric/data-warehouse/entra-id-authentication',
  },

  // ---------------------------------------------------------------------------
  // Azure Data Explorer (Kusto) — Service Principal.
  // config: cluster_url, database
  // creds:  client_id, client_secret, tenant_id
  // ---------------------------------------------------------------------------
  azure_data_explorer: {
    overview:
      'Azure Data Explorer (Kusto) authenticates with a Service Principal — an Entra ID app ' +
      'registration (Client ID + Secret + Tenant ID). Register the app, grant it the Viewer ' +
      'role on the database, then point at the cluster URL + database.',
    prerequisites: [
      'Register an app: Azure portal → Microsoft Entra ID → App registrations → New registration (gives Client ID, Tenant ID; add a Client Secret).',
      'Grant it database access: in your ADX database run .add database <db> viewers (\'aadapp=<client_id>;<tenant_id>\'), or use the Azure portal Permissions blade.',
      'Have the cluster URL handy (Azure portal → your ADX cluster → Overview → URI).',
    ],
    fields: {
      cluster_url: {
        what: 'The Azure Data Explorer cluster URL (the query endpoint).',
        where: 'Azure portal → your Data Explorer cluster → Overview → URI.',
        example: 'https://mycluster.eastus.kusto.windows.net',
        gotcha: 'Include the https:// and the full region host.',
        required: true,
      },
      database: {
        what: 'The Kusto database name to query.',
        where: 'Azure portal → cluster → Databases; or the database picker in the Kusto/ADX web UI.',
        example: 'TelemetryDB',
        required: true,
      },
      client_id: {
        what: 'The Entra ID app registration’s Application (Client) ID (the service principal).',
        where: 'Azure portal → Microsoft Entra ID → App registrations → (your app) → Overview → Application (client) ID.',
        example: '11111111-2222-3333-4444-555555555555',
        required: true,
      },
      client_secret: {
        what: 'A client secret VALUE for the app registration.',
        where: 'Azure portal → App registrations → (your app) → Certificates & secrets → New client secret → copy the Value.',
        gotcha: 'Copy the Value immediately (hidden afterward). The app must also be granted the Viewer role on the database.',
        required: true,
      },
      tenant_id: {
        what: 'Your Azure / Entra directory (tenant) GUID.',
        where: 'Azure portal → Microsoft Entra ID → Overview → Tenant ID.',
        example: '72f988bf-86f1-41af-91ab-2d7cd011db47',
        required: true,
      },
    },
    troubleshooting: [
      '"Unauthorized" / Forbidden on the database → the service principal wasn’t granted the Viewer role: .add database <db> viewers (\'aadapp=<client_id>;<tenant_id>\').',
      'AADSTS7000215 → invalid client secret (pasted Secret ID, or expired).',
      'Cluster not reachable → wrong cluster_url region/host, or network/firewall restrictions on the cluster.',
      'AADSTS700016 → wrong tenant_id or client_id.',
    ],
    docsUrl: 'https://learn.microsoft.com/en-us/azure/data-explorer/provision-azure-ad-app',
  },

  // ---------------------------------------------------------------------------
  // Trino — username/password.
  // config: host, port, catalog, schema, protocol
  // creds:  user, password
  // ---------------------------------------------------------------------------
  trino: {
    overview:
      'Trino is a distributed SQL engine. Connect to the coordinator host/port, pick a ' +
      'catalog + schema, and authenticate with a username (password is only needed over ' +
      'HTTPS). Choose the http or https protocol to match the coordinator.',
    prerequisites: [
      'The Trino coordinator host + port (default 8080 for http, often 8443 for https).',
      'A catalog name (the configured connector, e.g. hive, postgresql) and a schema within it.',
      'A username Trino accepts; if the coordinator enforces password auth (HTTPS), also a password.',
    ],
    fields: {
      host: {
        what: 'The Trino coordinator hostname.',
        example: 'trino.internal.example.com',
        required: true,
      },
      port: {
        what: 'The Trino coordinator port.',
        example: '8080  (http)  /  8443 (https, common)',
        required: true,
      },
      catalog: {
        what: 'The Trino catalog — a configured data source connector (e.g. hive, postgresql, iceberg).',
        where: 'Run SHOW CATALOGS in Trino.',
        example: 'hive',
        required: true,
      },
      schema: {
        what: 'The schema within the catalog.',
        where: 'Run SHOW SCHEMAS FROM <catalog>.',
        example: 'analytics',
        required: true,
      },
      protocol: {
        what: 'http or https — must match how the coordinator is exposed.',
        example: 'http',
        gotcha: 'Use https when the coordinator has TLS / requires password auth; password is only honored over https.',
        required: false,
      },
      user: {
        what: 'The Trino username (used for authorization and query attribution).',
        example: 'analytics',
        required: true,
      },
      password: {
        what: 'Password — only required when the coordinator uses password auth over HTTPS.',
        gotcha: 'Leave blank for plain http coordinators with no password authenticator.',
        required: false,
      },
    },
    troubleshooting: [
      '"Authentication failed" → coordinator requires password auth; set protocol=https and supply the password.',
      'Connection refused → wrong host/port, or the coordinator isn’t exposed to this server.',
      '"Catalog does not exist" → check SHOW CATALOGS; the catalog must be configured on the cluster.',
      'TLS handshake errors → protocol mismatch (http vs https) or an untrusted certificate.',
    ],
    docsUrl: 'https://trino.io/docs/current/security/authentication-types.html',
  },

  // ---------------------------------------------------------------------------
  // Presto — username/password.
  // config: host, port, catalog, schema, protocol
  // creds:  user, password
  // ---------------------------------------------------------------------------
  presto: {
    overview:
      'Presto is a distributed SQL engine (the predecessor of Trino). Connect to the ' +
      'coordinator host/port, choose a catalog + schema, and authenticate with a username ' +
      '(password only over HTTPS). Select the http or https protocol.',
    prerequisites: [
      'The Presto coordinator host + port (default 8080).',
      'A catalog (configured connector, e.g. hive) and a schema within it.',
      'A username Presto accepts; a password only if the coordinator enforces password auth over HTTPS.',
    ],
    fields: {
      host: {
        what: 'The Presto coordinator hostname.',
        example: 'presto.internal.example.com',
        required: true,
      },
      port: {
        what: 'The Presto coordinator port.',
        example: '8080',
        required: true,
      },
      catalog: {
        what: 'The Presto catalog — a configured connector (e.g. hive, mysql).',
        where: 'Run SHOW CATALOGS.',
        example: 'hive',
        required: true,
      },
      schema: {
        what: 'The schema within the catalog.',
        where: 'Run SHOW SCHEMAS FROM <catalog>.',
        example: 'default',
        required: true,
      },
      protocol: {
        what: 'http or https — must match the coordinator.',
        example: 'http',
        gotcha: 'Use https when the coordinator requires password auth; password is only sent over https.',
        required: false,
      },
      user: {
        what: 'The Presto username (authorization + query attribution).',
        example: 'analytics',
        required: true,
      },
      password: {
        what: 'Password — only needed when the coordinator uses password auth over HTTPS.',
        gotcha: 'Leave blank for plain http coordinators.',
        required: false,
      },
    },
    troubleshooting: [
      '"Authentication failed" → coordinator needs password auth; use protocol=https and a password.',
      'Connection refused → wrong host/port or coordinator not reachable.',
      '"Catalog does not exist" → catalog not configured; verify with SHOW CATALOGS.',
      'TLS errors → http/https mismatch or untrusted certificate.',
    ],
    docsUrl: 'https://prestodb.io/docs/current/security/authentication.html',
  },

  // ---------------------------------------------------------------------------
  // Salesforce — username + password + security token.
  // config: sandbox, domain
  // creds:  username, password, security_token
  // ---------------------------------------------------------------------------
  salesforce: {
    overview:
      'Salesforce connects via the SOAP/REST API using a username, password and a Security ' +
      'Token (appended to the password). Use a dedicated integration user with API access. ' +
      'Set sandbox / domain to point at the right org instance.',
    prerequisites: [
      'A Salesforce user with the "API Enabled" permission.',
      'That user’s Security Token: Salesforce → (avatar) → Settings → My Personal Information → Reset My Security Token (it’s emailed to the user).',
      'Know whether the org is Production/Developer (domain "login") or a Sandbox (domain "test").',
    ],
    fields: {
      sandbox: {
        what: 'Whether this org is a Salesforce Sandbox (vs a production/developer org).',
        example: 'false',
        gotcha: 'Set true for sandbox orgs; this and/or the domain field route to the correct login endpoint.',
        required: false,
      },
      domain: {
        what: 'The login domain: "login" for production/developer orgs, "test" for sandboxes (or your My Domain).',
        where: 'Setup → My Domain shows your org’s domain.',
        example: 'login   (sandbox: test)',
        gotcha: 'Defaults to "login". Use "test" for sandbox if not using the sandbox flag.',
        required: false,
      },
      username: {
        what: 'The Salesforce login username (an email-style login).',
        example: 'integration@yourcompany.com',
        required: true,
      },
      password: {
        what: 'The user’s Salesforce password.',
        gotcha: 'The Security Token is a SEPARATE field here — do not concatenate it onto the password yourself.',
        required: true,
      },
      security_token: {
        what: 'The user’s Salesforce Security Token, required for API logins from unknown IPs.',
        where: 'Salesforce → Settings → My Personal Information → Reset My Security Token (emailed to the user).',
        example: 'aBcD1234eFgH5678ijkl',
        gotcha: 'Resets each time the password changes, and whenever you click Reset. If your IP is allow-listed (Trusted IP Ranges) a token may not be needed, but supply it to be safe.',
        required: true,
      },
    },
    troubleshooting: [
      'INVALID_LOGIN "invalid username, password, security token; or user locked out" → wrong token, or token out of date after a password change.',
      'API_DISABLED_FOR_ORG / no API access → the user’s profile lacks "API Enabled".',
      'Login works in browser but not here → you’re missing the security token, or hitting the wrong domain (login vs test).',
      'Sandbox login fails → set sandbox=true or domain=test.',
    ],
    docsUrl: 'https://help.salesforce.com/s/articleView?id=sf.user_security_token.htm',
  },

  // ---------------------------------------------------------------------------
  // Google Analytics (GA4) — service-account JSON + property ID.
  // config: (none)
  // creds:  service_account_file, property_id
  // ---------------------------------------------------------------------------
  google_analytics: {
    overview:
      'Google Analytics (GA4) is queried through the Analytics Data API with a Google Cloud ' +
      'service account. Create the service account, enable the Analytics Data API, add the ' +
      'service account’s email as a Viewer on the GA4 property, and provide its JSON key + ' +
      'the numeric GA4 Property ID.',
    prerequisites: [
      'A GCP project with the "Google Analytics Data API" enabled (APIs & Services → Library).',
      'A service account + JSON key — GCP Console → IAM & Admin → Service Accounts → Keys → Add key (JSON).',
      'In GA4: Admin → Property Access Management → add the service account’s client_email with at least Viewer.',
      'Your GA4 Property ID (numeric) — GA4 Admin → Property Settings → Property ID.',
    ],
    fields: {
      service_account_file: {
        what: 'The service-account JSON key (paste the whole key contents) used to call the GA4 Data API.',
        where: 'GCP Console → IAM & Admin → Service Accounts → (your SA) → Keys → Add key → Create new key → JSON → open the file and paste all of it.',
        example: '{"type":"service_account","project_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\\n...","client_email":"ga-reader@project.iam.gserviceaccount.com", ...}',
        gotcha: 'Despite the name, paste the JSON key CONTENTS (not a file path). The service account’s client_email must be added as a Viewer on the GA4 property.',
        required: true,
      },
      property_id: {
        what: 'The numeric GA4 Property ID identifying which property to query.',
        where: 'GA4 → Admin → Property Settings → Property ID (top of the page, a number).',
        example: '123456789',
        gotcha: 'Use the GA4 PROPERTY ID (numeric), NOT a Universal Analytics view ID, the Measurement ID (G-XXXX), or the account ID.',
        required: true,
      },
    },
    troubleshooting: [
      '403 PERMISSION_DENIED → the service account email isn’t added to the GA4 property (Admin → Property Access Management → Viewer).',
      'API not enabled → enable "Google Analytics Data API" in the GCP project.',
      'INVALID_ARGUMENT on property → you used a UA view ID or Measurement ID; use the numeric GA4 Property ID.',
      '"Could not parse credentials" → paste the full JSON key, not a path or partial key.',
    ],
    docsUrl: 'https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart-client-libraries',
  },

  // ---------------------------------------------------------------------------
  // Tableau — Personal Access Token (PAT).
  // config: server_url, site_name, verify_ssl, timeout_sec, default_project_id, api_version
  // creds:  pat_name, pat_token
  // ---------------------------------------------------------------------------
  tableau: {
    overview:
      'Tableau connects with a Personal Access Token (PAT) to the Metadata API + VizQL Data ' +
      'Service. Point at the Tableau Server / Cloud URL, the site, and a PAT created by a ' +
      'user with access to the data sources you want to query.',
    prerequisites: [
      'PATs enabled on the server — Tableau Server/Cloud → Settings (admin may need to turn on Personal Access Tokens).',
      'Create a PAT — Tableau → My Account Settings → Personal Access Tokens → Create new token → copy the secret.',
      'Know your site name (the content URL segment after /site/), or leave blank for the Default site.',
    ],
    fields: {
      server_url: {
        what: 'The base URL of your Tableau Server or Tableau Cloud.',
        where: 'Your Tableau address bar (the host before /#/site/...).',
        example: 'https://10ay.online.tableau.com   (or https://tableau.yourco.com)',
        gotcha: 'Include https://; do not include the /#/site/... path.',
        required: true,
      },
      site_name: {
        what: 'The Tableau site’s content URL name (the segment after /site/ in the URL). Blank = the Default site.',
        where: 'In the URL: https://…/#/site/<site_name>/… → use <site_name>.',
        example: 'marketing   (blank for Default)',
        gotcha: 'Use the content URL name, not the friendly display name. On Tableau Cloud this is required; on a single-site Server leave blank.',
        required: false,
      },
      verify_ssl: {
        what: 'Whether to verify the server’s TLS certificate.',
        example: 'true',
        gotcha: 'Disable only for an internal server with a self-signed certificate.',
        required: false,
      },
      timeout_sec: {
        what: 'Request timeout in seconds.',
        example: '30',
        required: false,
      },
      default_project_id: {
        what: 'Optional. A Tableau project ID to scope discovery to.',
        where: 'Tableau → the project → its ID appears in the URL / via the REST API.',
        required: false,
      },
      api_version: {
        what: 'Tableau REST API version to use.',
        example: '3.21',
        gotcha: 'Leave at the default unless you run an older on-prem Tableau Server that needs a lower version.',
        required: false,
      },
      pat_name: {
        what: 'The NAME you gave the Personal Access Token when you created it.',
        where: 'Tableau → My Account Settings → Personal Access Tokens → the token’s name.',
        example: 'cityagent-readonly',
        required: true,
      },
      pat_token: {
        what: 'The Personal Access Token SECRET value.',
        where: 'Tableau → My Account Settings → Personal Access Tokens → Create new token → copy the secret immediately.',
        gotcha: 'Shown only once at creation. PATs expire after a period of inactivity (e.g. 15 days) — regenerate if it goes stale.',
        required: true,
      },
    },
    troubleshooting: [
      '401 "Signin error" → wrong pat_name/pat_token, expired/idle PAT, or wrong site_name.',
      '"Personal access tokens are not enabled" → an admin must enable PATs in server settings.',
      'SSL certificate errors → set verify_ssl=false only for a trusted self-signed internal server.',
      'No data sources found → the PAT user lacks access to them, or default_project_id is too narrow.',
      'API version errors on old Server → lower api_version to one the server supports.',
    ],
    docsUrl: 'https://help.tableau.com/current/server/en-us/security_personal_access_tokens.htm',
  },

  // ---------------------------------------------------------------------------
  // Power BI — Service Principal (default) or delegated OAuth.
  // config: (none — auto-discovers workspaces/datasets)
  // creds:  tenant_id, client_id, client_secret, oauth_client_id, oauth_client_secret
  // ---------------------------------------------------------------------------
  powerbi: {
    overview:
      'Power BI queries semantic models via DAX using a Service Principal — an Entra ID ' +
      '(Azure AD) app registration (Tenant ID + Client ID + Client Secret). Register the app, ' +
      'enable service-principal access in the Power BI tenant settings, add the app to the ' +
      'workspaces, and it auto-discovers the workspaces/datasets it can see. (Optional ' +
      'delegated OAuth lets users sign in with Microsoft.)',
    prerequisites: [
      'Register an app: Azure portal → Microsoft Entra ID → App registrations → New registration (yields Tenant ID + Client ID; add a Client Secret).',
      'Power BI admin: enable "Allow service principals to use Power BI APIs" for a security group containing the app (Power BI Admin portal → Tenant settings → Developer settings).',
      'Add the service principal to each workspace as a Member/Admin (Power BI workspace → Access).',
      'No config fields — Power BI auto-discovers everything the SP can access.',
    ],
    fields: {
      tenant_id: {
        what: 'Your Azure / Entra directory (tenant) GUID.',
        where: 'Azure portal → Microsoft Entra ID → Overview → Tenant ID.',
        example: '72f988bf-86f1-41af-91ab-2d7cd011db47',
        required: true,
      },
      client_id: {
        what: 'The app registration’s Application (client) ID (the service principal).',
        where: 'Azure portal → Microsoft Entra ID → App registrations → (your app) → Overview → Application (client) ID.',
        example: '11111111-2222-3333-4444-555555555555',
        required: true,
      },
      client_secret: {
        what: 'A client secret VALUE for the app registration.',
        where: 'Azure portal → App registrations → (your app) → Certificates & secrets → New client secret → copy the Value.',
        steps: [
          'App registrations → (your app) → Certificates & secrets → New client secret → copy the VALUE.',
          'Power BI Admin portal → Tenant settings → enable service principals to use Power BI APIs (for a group containing the app).',
          'Add the SP to each Power BI workspace’s Access as Member/Admin.',
        ],
        gotcha: 'Copy the secret VALUE immediately (hidden afterward). The SP must be enabled in the Power BI tenant setting AND added to the workspaces, or discovery returns nothing.',
        required: true,
      },
      oauth_client_id: {
        what: 'Optional. App Registration Client ID for delegated user sign-in (authorization code flow). Falls back to Client ID above.',
        where: 'Same App registrations Overview as client_id.',
        required: false,
      },
      oauth_client_secret: {
        what: 'Optional. The secret for the delegated-sign-in app. Falls back to Client Secret above.',
        where: 'Certificates & secrets of the OAuth app registration.',
        required: false,
      },
    },
    troubleshooting: [
      'No workspaces/datasets discovered → the SP isn’t added to any workspace, or the tenant setting "service principals can use Power BI APIs" is off.',
      'AADSTS7000215 "Invalid client secret" → pasted the Secret ID instead of the Value, or it expired.',
      'AADSTS700016 "application not found" → wrong tenant_id or client_id.',
      'DAX query fails on a model → the SP needs at least Viewer/Build on that semantic model’s workspace.',
    ],
    docsUrl: 'https://learn.microsoft.com/en-us/power-bi/developer/embedded/embed-service-principal',
  },

  // ---------------------------------------------------------------------------
  // Spreadsheet (Excel/CSV upload) — no auth, server-side file.
  // config: file_id, sheet_names, path
  // creds:  none
  // ---------------------------------------------------------------------------
  spreadsheet: {
    overview:
      'Upload a local Excel (.xlsx/.xls) or CSV file and query it as a Data Agent — each ' +
      'sheet becomes a table via an in-memory DuckDB engine. There is no credential: the ' +
      'file is uploaded to the server first, and this connector references it by file_id. ' +
      'The UI’s Upload flow fills these fields for you.',
    prerequisites: [
      'Upload the file first via POST /api/files (the connect modal’s drag-and-drop does this) — it returns a file_id.',
      'For the easiest path, use the in-app "Upload File / Spreadsheet" tile or the Studio "Upload file" button instead of filling these fields by hand.',
    ],
    fields: {
      file_id: {
        what: 'The ID of the already-uploaded File backing this data source.',
        where: 'Returned by POST /api/files when you upload the spreadsheet (the Upload modal sets this automatically).',
        example: 'f4c2a1e0-8b3d-4e9a-9c12-7a6b5c4d3e2f',
        gotcha: 'You normally never type this — the Upload Spreadsheet flow captures it for you. The file must already be uploaded to this org.',
        required: true,
      },
      sheet_names: {
        what: 'Optional. A subset of Excel sheet names to load. Omit to load all sheets (or the single CSV).',
        example: '["Sales", "Targets"]',
        gotcha: 'Only applies to multi-sheet Excel files; ignored for CSV.',
        required: false,
      },
      path: {
        what: 'The server-side path of the uploaded file. Set automatically by the create flow — not user-supplied.',
        gotcha: 'Leave blank; the backend resolves and fills this from file_id.',
        required: false,
      },
    },
    troubleshooting: [
      '"File not found in organization" → the file_id doesn’t belong to this org, or wasn’t uploaded; re-upload via the Upload modal.',
      'Unreadable / unsupported file → only .xlsx, .xls, .csv are supported; check the file isn’t corrupt or password-protected.',
      'Tables created but empty → the sheet had no parseable header/rows; verify the first row is a header.',
      'Duplicate data source name → pick a different name (409 conflict).',
    ],
    docsUrl: 'https://duckdb.org/docs/data/overview',
  },
} as ConnectorDocMap
