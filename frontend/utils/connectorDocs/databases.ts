// Connection-setup documentation for self-managed / classic SQL & NoSQL databases.
// Field keys MUST match the backend config/credential schemas in
// backend/app/schemas/data_sources/configs.py (verified against each Config/Credentials
// pydantic model) and the client constructors in
// backend/app/data_sources/clients/<type>_client.py.
//
// Map keys are the connector TYPE strings the registry uses (the client filename stem):
//   postgresql, mysql, mariadb, mssql, oracledb, sybase, teradata, vertica,
//   clickhouse, sqlite, mongodb
import type { ConnectorDocMap } from './types'

// A read-only-user snippet reused (with per-engine tweaks) across the SQL connectors.
const READONLY_INTRO =
  'Create a dedicated least-privilege login for the analyst instead of reusing an admin/root account.'

export default {
  // ───────────────────────────── PostgreSQL ─────────────────────────────
  postgresql: {
    overview:
      'Connects to a PostgreSQL server (self-hosted, RDS/Aurora, Cloud SQL, Supabase, Neon, etc.) ' +
      'over a standard TCP connection. Auth is a database username + password; the analyst only ever runs read queries.',
    prerequisites: [
      'Network reachability: the app host must be allowed to reach the DB port (security group / firewall / pg_hba.conf). On RDS, add the app IP/SG to the instance security group.',
      `${READONLY_INTRO} A SELECT-only role is enough.`,
      'Know which database and (optionally) schema(s) hold the tables you want analyzed.',
    ],
    fields: {
      host: {
        what: 'Hostname or IP of the PostgreSQL server.',
        where: 'From your DBA, or the cloud console (RDS "Endpoint", Cloud SQL "Public/Private IP", Supabase "Host").',
        example: 'db.internal.example.com  (or  mydb.abc1234.us-east-1.rds.amazonaws.com)',
        gotcha: 'Use the host only — do NOT include the port or a "postgresql://" prefix here.',
        required: true,
      },
      port: {
        what: 'TCP port PostgreSQL listens on.',
        where: 'Default unless your DBA changed it.',
        example: '5432',
        gotcha: 'Default is 5432. Cloud poolers (e.g. Supabase/PgBouncer) often use 6543 — check the console.',
        required: true,
      },
      database: {
        what: 'The specific database (catalog) to connect to.',
        where: 'Run `\\l` in psql, or ask your DBA. This is the DB name, not the server name.',
        example: 'analytics',
        gotcha: 'PostgreSQL identifiers are case-sensitive when quoted; match the exact name.',
        required: true,
      },
      schema: {
        what: 'Optional schema, or comma-separated list of schemas, to expose. Leave blank to use the default search_path.',
        where: 'Run `SELECT schema_name FROM information_schema.schemata;` or ask your DBA.',
        example: 'public, sales',
        gotcha: 'Omitting this discovers all non-system schemas. Provide a list to narrow what the agent sees.',
        required: false,
      },
      user: {
        what: 'Database login name (role) used to connect.',
        where: 'The read-only role you (or your DBA) created.',
        steps: [
          'Connect as a superuser/admin (psql).',
          "CREATE USER analytics WITH PASSWORD 'strong-password';",
          'GRANT CONNECT ON DATABASE analytics TO analytics;',
          'GRANT USAGE ON SCHEMA public TO analytics;',
          'GRANT SELECT ON ALL TABLES IN SCHEMA public TO analytics;',
          'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO analytics;',
        ],
        example: 'analytics',
        required: true,
      },
      password: {
        what: 'Password for the database user. May be blank only for trust-auth deployments.',
        where: 'The password you set when creating the role.',
        example: 'S0me-Strong-Passw0rd',
        gotcha: 'Stored encrypted. If the server enforces SSL, ensure the host certificate is reachable (see troubleshooting).',
        required: false,
      },
    },
    troubleshooting: [
      'Connection timeout / refused → the app IP is not allowed through the security group/firewall, or the wrong port (5432 vs a pooler port like 6543).',
      'FATAL: no pg_hba.conf entry → server rejects your host/SSL mode; add a pg_hba rule or enable SSL on the client.',
      'FATAL: database "x" does not exist → you put the server name in the database field; use the real DB (catalog) name.',
      'Permission denied for relation / no tables visible → the role lacks USAGE on the schema or SELECT on the tables; re-run the GRANTs above (and ALTER DEFAULT PRIVILEGES for future tables).',
      'Authentication failed → wrong user/password, or the role requires SCRAM and the client is sending an old MD5 hash.',
    ],
    docsUrl: 'https://www.postgresql.org/docs/current/libpq-connect.html',
  },

  // ─────────────────────────────── MySQL ────────────────────────────────
  mysql: {
    overview:
      'Connects to a MySQL server (self-hosted, RDS/Aurora MySQL, Cloud SQL, PlanetScale, etc.) over TCP. ' +
      'Auth is a username + password (both optional for anonymous-access servers); queries are read-only.',
    prerequisites: [
      'Network reachability: allow the app host to reach the MySQL port (security group / firewall / bind-address).',
      `${READONLY_INTRO} A SELECT grant on the target database is enough.`,
      'The MySQL user must be allowed to connect from the app host (the host part of \'user\'@\'host\').',
    ],
    fields: {
      host: {
        what: 'Hostname or IP of the MySQL server.',
        where: 'From your DBA, or the cloud console endpoint (RDS "Endpoint", Cloud SQL IP).',
        example: 'mysql.internal.example.com',
        gotcha: 'Host only — no port, no "mysql://" prefix.',
        required: true,
      },
      port: {
        what: 'TCP port MySQL listens on.',
        where: 'Default unless changed.',
        example: '3306',
        gotcha: 'Default is 3306. PlanetScale/Vitess and some proxies use a different port — check your provider.',
        required: true,
      },
      database: {
        what: 'The schema/database to connect to (in MySQL "database" and "schema" are the same thing).',
        where: 'Run `SHOW DATABASES;` or ask your DBA.',
        example: 'sales',
        gotcha: 'On Linux servers, database names are case-sensitive (lower_case_table_names=0).',
        required: true,
      },
      user: {
        what: 'MySQL login name. Leave blank only for anonymous-access servers.',
        where: 'The read-only account you created.',
        steps: [
          "CREATE USER 'analytics'@'%' IDENTIFIED BY 'strong-password';",
          "GRANT SELECT ON sales.* TO 'analytics'@'%';",
          'FLUSH PRIVILEGES;',
        ],
        example: 'analytics',
        gotcha: "The host part ('analytics'@'%' vs @'10.0.%') controls where the user may connect from; '%' allows any host.",
        required: false,
      },
      password: {
        what: 'Password for the MySQL user. Leave blank for anonymous/empty-password access.',
        where: 'Set when creating the user.',
        example: 'S0me-Strong-Passw0rd',
        gotcha: 'If you supply a password you MUST also supply a user (the form rejects password-without-user).',
        required: false,
      },
    },
    troubleshooting: [
      "Can't connect / timeout → app IP not allowed, wrong port (3306), or the server bind-address is 127.0.0.1 (local-only).",
      "Access denied for user 'x'@'host' → the user is not permitted from the app host, or wrong password; check the host part of the grant.",
      'Unknown database → wrong database name (case-sensitive on Linux).',
      'No tables visible → the user has CONNECT but no SELECT grant on the target database.',
      "caching_sha2_password / auth plugin error → older clients need mysql_native_password; ALTER USER ... IDENTIFIED WITH mysql_native_password.",
    ],
    docsUrl: 'https://dev.mysql.com/doc/refman/8.0/en/connecting.html',
  },

  // ────────────────────────────── MariaDB ───────────────────────────────
  mariadb: {
    overview:
      'Connects to a MariaDB server (the MySQL-compatible fork) over TCP using a username + password. ' +
      'Wire-protocol-compatible with MySQL; queries are read-only.',
    prerequisites: [
      'Network reachability: allow the app host to reach the MariaDB port.',
      `${READONLY_INTRO} A SELECT grant on the target database is enough.`,
      'The MariaDB user must be permitted to connect from the app host.',
    ],
    fields: {
      host: {
        what: 'Hostname or IP of the MariaDB server.',
        where: 'From your DBA or hosting console.',
        example: 'mariadb.internal.example.com',
        gotcha: 'Host only — no port or scheme prefix.',
        required: true,
      },
      port: {
        what: 'TCP port MariaDB listens on.',
        where: 'Default unless changed.',
        example: '3306',
        gotcha: 'Default is 3306 (same as MySQL).',
        required: true,
      },
      database: {
        what: 'The database/schema to connect to.',
        where: 'Run `SHOW DATABASES;` or ask your DBA.',
        example: 'inventory',
        gotcha: 'Case-sensitivity depends on the server OS, same as MySQL.',
        required: true,
      },
      user: {
        what: 'MariaDB login name.',
        where: 'The read-only account you created.',
        steps: [
          "CREATE USER 'analytics'@'%' IDENTIFIED BY 'strong-password';",
          "GRANT SELECT ON inventory.* TO 'analytics'@'%';",
          'FLUSH PRIVILEGES;',
        ],
        example: 'analytics',
        required: true,
      },
      password: {
        what: 'Password for the MariaDB user.',
        where: 'Set when creating the user.',
        example: 'S0me-Strong-Passw0rd',
        gotcha: 'A password without a user is rejected.',
        required: true,
      },
    },
    troubleshooting: [
      'Connection refused / timeout → firewall/security-group blocks the port, or wrong port (3306), or bind-address is local-only.',
      "Access denied for user → wrong credentials or the user can't connect from the app host.",
      'Unknown database → wrong/mis-cased database name.',
      'No tables visible → missing SELECT grant on the database.',
      'Auth plugin mismatch (ed25519/unix_socket) → switch the user to mysql_native_password for TCP password auth.',
    ],
    docsUrl: 'https://mariadb.com/kb/en/connecting-to-mariadb/',
  },

  // ─────────────────────── Microsoft SQL Server ─────────────────────────
  mssql: {
    overview:
      'Connects to Microsoft SQL Server (on-prem, Azure SQL Database, Azure SQL Managed Instance) via ODBC ' +
      '(Microsoft ODBC Driver 17/18). Auth is SQL Server username + password; the connection is encrypted by default.',
    prerequisites: [
      'Network reachability: allow the app host to reach the SQL Server port; Azure SQL needs a firewall rule for the app IP.',
      'The Microsoft ODBC Driver (17 or 18) — bundled in the app image. Driver 18 encrypts by default and validates the server certificate.',
      `${READONLY_INTRO} Create a login + a db_datareader user.`,
    ],
    fields: {
      host: {
        what: 'Hostname, IP, or Azure SQL server FQDN.',
        where: 'From your DBA, or the Azure portal ("Server name", e.g. myserver.database.windows.net).',
        example: 'myserver.database.windows.net  (or  sql01.corp.local)',
        gotcha: 'For a named instance, use the host here and the instance port in the port field — instance\\name strings are not parsed here.',
        required: true,
      },
      port: {
        what: 'TCP port SQL Server listens on.',
        where: 'Default unless a named instance / custom port is used.',
        example: '1433',
        gotcha: 'Default is 1433. Named instances often use a dynamic port — set a static port or find it via SQL Server Configuration Manager.',
        required: true,
      },
      database: {
        what: 'The database to connect to.',
        where: 'Run `SELECT name FROM sys.databases;` or ask your DBA.',
        example: 'Sales',
        gotcha: 'Defaulting to master usually shows no business tables — point at the real DB.',
        required: true,
      },
      schema: {
        what: 'Optional schema, or comma-separated list, to expose. Leave blank to discover all schemas.',
        where: 'Run `SELECT name FROM sys.schemas;` or ask your DBA.',
        example: 'dbo, sales',
        gotcha: 'SQL Server objects are usually under dbo; narrow with a list if there are many schemas.',
        required: false,
      },
      odbc_driver: {
        what: 'ODBC driver major version to use (17 or 18).',
        where: 'Pick 18 (default) for modern servers; 17 for SQL Server 2008 / legacy TLS compatibility.',
        example: '18',
        gotcha: 'Driver 18 enforces encryption + certificate trust by default; if you hit certificate errors on an internal server, use 17 or set encrypt off.',
        required: false,
      },
      encrypt: {
        what: 'Whether to encrypt the connection (TLS).',
        where: 'Leave on for Azure SQL and modern servers; turn off only for an old SQL Server 2008 without TLS.',
        example: 'true',
        gotcha: 'With driver 18 + encrypt on, a self-signed/internal server cert can cause "certificate chain not trusted" — use driver 17, or add the CA via additional_params (TrustServerCertificate=yes).',
        required: false,
      },
      additional_params: {
        what: 'Extra ODBC keywords sent as-is (key/value pairs), e.g. ApplicationIntent=ReadOnly.',
        where: 'Optional — for advanced ODBC tuning.',
        example: 'ApplicationIntent=ReadOnly',
        gotcha: 'Security keywords (Encrypt, credentials, driver) are ignored here and cannot be overridden.',
        required: false,
      },
      user: {
        what: 'SQL Server login name.',
        where: 'The read-only login you created.',
        steps: [
          "CREATE LOGIN analytics WITH PASSWORD = 'Strong-Passw0rd!';",
          'USE Sales;',
          'CREATE USER analytics FOR LOGIN analytics;',
          'ALTER ROLE db_datareader ADD MEMBER analytics;',
        ],
        example: 'analytics',
        gotcha: 'On Azure SQL use the bare login name (do NOT append @servername unless using Azure AD).',
        required: true,
      },
      password: {
        what: 'Password for the SQL Server login.',
        where: 'Set when creating the login.',
        example: 'Strong-Passw0rd!',
        gotcha: 'Must satisfy the server password policy (length + complexity), or CREATE LOGIN fails.',
        required: true,
      },
    },
    troubleshooting: [
      'Login timeout / cannot reach server → firewall/security group, missing Azure SQL firewall rule, or wrong port (1433 / dynamic named-instance port).',
      'SSL/Certificate "chain not trusted" → ODBC driver 18 enforces cert trust; switch to driver 17, disable encrypt, or trust the server cert (TrustServerCertificate=yes via additional_params).',
      'Login failed for user → wrong credentials, or the login has no USER mapped in the target database.',
      'Cannot open database requested → the login lacks access to that DB, or you pointed at master instead of the business DB.',
      'No tables visible → the user is not a member of db_datareader (or lacks SELECT on the schema).',
    ],
    docsUrl: 'https://learn.microsoft.com/en-us/sql/connect/odbc/dsn-connection-string-attribute',
  },

  // ────────────────────────────── Oracle ────────────────────────────────
  oracledb: {
    overview:
      'Connects to an Oracle Database (on-prem, Oracle Cloud, RDS for Oracle) via the python-oracledb thin client. ' +
      'Auth is an Oracle username + password; connection is made by service name (not SID).',
    prerequisites: [
      'Network reachability: allow the app host to reach the Oracle listener port.',
      'The connection uses the SERVICE NAME (not the legacy SID) — confirm the service name with your DBA.',
      `${READONLY_INTRO} Grant CREATE SESSION + SELECT on the target tables.`,
    ],
    fields: {
      host: {
        what: 'Hostname or IP of the Oracle listener.',
        where: 'From your DBA, or the cloud console (RDS endpoint / OCI connection string).',
        example: 'oracle.internal.example.com',
        gotcha: 'Host only — no port, no full Easy-Connect string.',
        required: true,
      },
      port: {
        what: 'TCP port the Oracle listener uses.',
        where: 'Default unless changed.',
        example: '1521',
        gotcha: 'Default is 1521.',
        required: true,
      },
      service_name: {
        what: 'Oracle service name to connect to (NOT the SID).',
        where: 'Ask your DBA, or run `SELECT value FROM v$parameter WHERE name = \'service_names\';` / `lsnrctl services`.',
        example: 'ORCLPDB1  (or  salespdb.example.com)',
        gotcha: 'Service name ≠ SID. Using a SID here will fail with ORA-12514 (service not known to listener).',
        required: true,
      },
      schema: {
        what: 'Optional schema (Oracle user/owner), or comma-separated list, to expose. Leave blank to discover accessible schemas.',
        where: 'In Oracle a schema = a user; ask your DBA which owner holds the tables.',
        example: 'SALES, HR',
        gotcha: 'Oracle uppercases unquoted identifiers — schema names are typically UPPERCASE.',
        required: false,
      },
      user: {
        what: 'Oracle username used to connect.',
        where: 'The read-only account you created.',
        steps: [
          'CREATE USER analytics IDENTIFIED BY "Strong-Passw0rd";',
          'GRANT CREATE SESSION TO analytics;',
          'GRANT SELECT ON sales.orders TO analytics;  -- repeat per table, or use a read-only role',
        ],
        example: 'ANALYTICS',
        gotcha: 'Usernames are case-insensitive unless created with quotes; commonly entered uppercase.',
        required: true,
      },
      password: {
        what: 'Password for the Oracle user.',
        where: 'Set when creating the user.',
        example: 'Strong-Passw0rd',
        gotcha: 'If the password contains special characters and you also create the user with quotes, keep them consistent.',
        required: true,
      },
    },
    troubleshooting: [
      'ORA-12514 (service not known) → you used a SID instead of the service name, or the wrong service name.',
      'ORA-12541 / TNS no listener → wrong host/port (1521) or the listener is down / firewalled.',
      'ORA-01017 invalid username/password → wrong credentials, or the account is locked/expired.',
      'ORA-00942 table or view does not exist → the user lacks SELECT on those tables, or the schema/owner is wrong (check UPPERCASE).',
      'No tables visible → grant SELECT on the target schema or assign a read-only role.',
    ],
    docsUrl: 'https://python-oracledb.readthedocs.io/en/latest/user_guide/connection_handling.html',
  },

  // ─────────────────────── SAP / Sybase SQL Anywhere ────────────────────
  sybase: {
    overview:
      'Connects to a Sybase / SAP SQL Anywhere database over TCP using a username + password. Queries are read-only.',
    prerequisites: [
      'Network reachability: allow the app host to reach the SQL Anywhere database server port.',
      'The SQL Anywhere database server must be running and listening on TCP (the dbsrv/dbeng "-x tcpip" option).',
      `${READONLY_INTRO} Grant SELECT on the target tables.`,
    ],
    fields: {
      host: {
        what: 'Hostname or IP of the Sybase / SQL Anywhere server.',
        where: 'From your DBA.',
        example: 'sybase.internal.example.com',
        gotcha: 'Host only — no port or connection-string fragments.',
        required: true,
      },
      port: {
        what: 'TCP port the database server listens on.',
        where: 'Default unless changed.',
        example: '2638',
        gotcha: 'Default SQL Anywhere TCP port is 2638.',
        required: true,
      },
      database: {
        what: 'The database name to connect to.',
        where: 'Ask your DBA (the running database/"server name").',
        example: 'demo',
        gotcha: 'A SQL Anywhere server can host multiple databases — name the right one.',
        required: true,
      },
      user: {
        what: 'Database login name.',
        where: 'The read-only account you created.',
        steps: [
          "CREATE USER analytics IDENTIFIED BY 'Strong-Passw0rd';",
          'GRANT SELECT ON DBA.Orders TO analytics;  -- repeat per table',
        ],
        example: 'analytics',
        required: true,
      },
      password: {
        what: 'Password for the database user.',
        where: 'Set when creating the user.',
        example: 'Strong-Passw0rd',
        required: true,
      },
    },
    troubleshooting: [
      'Connection error / database not found → wrong host/port (2638) or the server is not listening on TCP/IP.',
      'Invalid user ID or password → wrong credentials.',
      'Permission denied → the user lacks SELECT on the target tables.',
      'No tables visible → grant SELECT (or a read-only group/role) on the schema owner (often DBA).',
      'Driver/ODBC errors → ensure the SQL Anywhere client libraries are available in the app environment.',
    ],
    docsUrl: 'https://help.sap.com/docs/SAP_SQL_Anywhere',
  },

  // ───────────────────────────── Teradata ───────────────────────────────
  teradata: {
    overview:
      'Connects to a Teradata system via the official teradatasql driver. Auth is a username + password with a ' +
      'configurable logon mechanism (TD2 for native users; LDAP/KRB5/TDNEGO for directory logon).',
    prerequisites: [
      'Network reachability: allow the app host to reach the Teradata gateway port.',
      'Know your logon mechanism: TD2 for native Teradata users, or LDAP/KRB5/TDNEGO for directory-based logon (common on-prem).',
      `${READONLY_INTRO} Grant SELECT on the target database(s).`,
    ],
    fields: {
      host: {
        what: 'Teradata system hostname or IP (the TPA / COP name).',
        where: 'From your DBA — typically the COP entry (e.g. system-cop1).',
        example: 'teradata-cop1.example.com',
        gotcha: 'Host only — no port or logon string.',
        required: true,
      },
      port: {
        what: 'Teradata listener (gateway) port.',
        where: 'Default unless changed.',
        example: '1025',
        gotcha: 'Default is 1025 (NOT a SQL-typical port).',
        required: true,
      },
      database: {
        what: 'Database to query. In Teradata a "database" is the namespace (≈ schema). Can be a comma-separated list.',
        where: 'Ask your DBA which database holds the tables.',
        example: 'SALES_DB, DIM_DB',
        gotcha: 'Teradata "database" = schema/namespace, not a separate catalog like in PostgreSQL.',
        required: true,
      },
      logmech: {
        what: 'Authentication (logon) mechanism: TD2, LDAP, KRB5, or TDNEGO.',
        where: 'Ask your DBA / security team. TD2 = native Teradata users; LDAP/KRB5/TDNEGO = directory logon.',
        example: 'TD2',
        gotcha: 'Default is TD2. Using TD2 against an LDAP-only account (or vice-versa) fails authentication.',
        required: false,
      },
      user: {
        what: 'Teradata username.',
        where: 'The read-only account / directory user.',
        steps: [
          'CREATE USER analytics AS PERMANENT = 0, PASSWORD = StrongPassw0rd;',
          'GRANT SELECT ON SALES_DB TO analytics;',
        ],
        example: 'analytics',
        gotcha: 'For LDAP/KRB5 logon, use the directory username your security team provides, not a native Teradata user.',
        required: true,
      },
      password: {
        what: 'Password for the user (per the chosen logon mechanism).',
        where: 'Set when creating the user, or your directory password for LDAP/KRB5.',
        example: 'StrongPassw0rd',
        required: true,
      },
    },
    troubleshooting: [
      'Cannot connect / timeout → wrong host/port (1025) or the gateway is firewalled.',
      'The UserId, Password or Account is invalid → wrong credentials, or the wrong logmech for the account type (TD2 vs LDAP).',
      'Logon mechanism not enabled → the system is not configured for the chosen logmech; confirm with your DBA.',
      'Object does not exist / no tables → the user lacks SELECT on the named database(s).',
      'Slow first query → Teradata parses against the database list; narrow the database field to the needed namespaces.',
    ],
    docsUrl: 'https://github.com/Teradata/python-driver',
  },

  // ────────────────────────────── Vertica ───────────────────────────────
  vertica: {
    overview:
      'Connects to a Vertica analytics database over TCP using a username + password. Defaults to the "public" schema.',
    prerequisites: [
      'Network reachability: allow the app host to reach the Vertica port.',
      `${READONLY_INTRO} Grant USAGE on the schema + SELECT on the tables.`,
      'Know which schema holds your tables (defaults to public).',
    ],
    fields: {
      host: {
        what: 'Hostname or IP of a Vertica node.',
        where: 'From your DBA (any node in the cluster).',
        example: 'vertica.internal.example.com',
        gotcha: 'Host only — no port or scheme.',
        required: true,
      },
      port: {
        what: 'TCP port Vertica listens on.',
        where: 'Default unless changed.',
        example: '5433',
        gotcha: 'Default is 5433 (NOT 5432 — that is PostgreSQL; mixing them up is a common error).',
        required: true,
      },
      database: {
        what: 'The Vertica database name.',
        where: 'Ask your DBA (the cluster database name).',
        example: 'VMart',
        gotcha: 'One Vertica cluster typically hosts a single database.',
        required: true,
      },
      schema: {
        what: 'Schema to expose.',
        where: 'Run `SELECT schema_name FROM v_catalog.schemata;` or ask your DBA.',
        example: 'public',
        gotcha: 'Defaults to "public"; set this if your tables live in a different schema.',
        required: false,
      },
      user: {
        what: 'Vertica login name.',
        where: 'The read-only account you created.',
        steps: [
          "CREATE USER analytics IDENTIFIED BY 'Strong-Passw0rd';",
          'GRANT USAGE ON SCHEMA public TO analytics;',
          'GRANT SELECT ON ALL TABLES IN SCHEMA public TO analytics;',
        ],
        example: 'analytics',
        required: true,
      },
      password: {
        what: 'Password for the Vertica user.',
        where: 'Set when creating the user.',
        example: 'Strong-Passw0rd',
        required: true,
      },
    },
    troubleshooting: [
      'Connection refused / timeout → wrong host/port (5433, not 5432) or firewall.',
      'Authentication failed → wrong credentials, or a server auth record (CREATE AUTHENTICATION) blocks the host.',
      'Permission denied for schema → grant USAGE on the schema and SELECT on the tables.',
      'No tables visible → tables are in a schema other than public; set the schema field.',
      'Pool / too many sessions → Vertica enforces per-user connection limits; coordinate with your DBA.',
    ],
    docsUrl: 'https://docs.vertica.com/latest/en/connecting-to/client-libraries/',
  },

  // ───────────────────────────── ClickHouse ─────────────────────────────
  clickhouse: {
    overview:
      'Connects to a ClickHouse server (self-hosted or ClickHouse Cloud) over the HTTP interface using a ' +
      'username + password. "Secure" toggles HTTPS.',
    prerequisites: [
      'Network reachability: allow the app host to reach the ClickHouse HTTP(S) port.',
      `${READONLY_INTRO} Create a user with a readonly profile + GRANT SELECT.`,
      'Decide HTTP vs HTTPS (Secure) — ClickHouse Cloud requires HTTPS.',
    ],
    fields: {
      host: {
        what: 'Hostname or IP of the ClickHouse server.',
        where: 'From your DBA, or the ClickHouse Cloud console ("Host" on the connection panel).',
        example: 'abc123.us-east-1.aws.clickhouse.cloud  (or  clickhouse.internal.example.com)',
        gotcha: 'Host only — no port, no http(s):// prefix.',
        required: true,
      },
      port: {
        what: 'ClickHouse HTTP interface port.',
        where: 'Default depends on HTTP vs HTTPS.',
        example: '8123 (HTTP)  /  8443 (HTTPS, ClickHouse Cloud)',
        gotcha: 'Default field value is 8123 (plain HTTP). For ClickHouse Cloud / HTTPS use 8443 and turn Secure on. Note: 9000 is the native TCP port, NOT the HTTP port used here.',
        required: true,
      },
      database: {
        what: 'Database to use. Can be a comma-separated list. Leave blank to use all databases.',
        where: 'Run `SHOW DATABASES;` or ask your DBA.',
        example: 'default, analytics',
        gotcha: 'Omitting this exposes all databases; provide a list to narrow scope.',
        required: false,
      },
      secure: {
        what: 'Use HTTPS instead of plain HTTP.',
        where: 'On for ClickHouse Cloud / any TLS-terminated endpoint; off for a local HTTP server.',
        example: 'true',
        gotcha: 'Default is on (HTTPS). If Secure is on but the server only speaks HTTP on 8123, the connection fails — match Secure to the port (8443→on, 8123→off).',
        required: false,
      },
      user: {
        what: 'ClickHouse username.',
        where: 'The read-only account you created.',
        steps: [
          "CREATE USER analytics IDENTIFIED BY 'Strong-Passw0rd' SETTINGS PROFILE 'readonly';",
          'GRANT SELECT ON analytics.* TO analytics;',
        ],
        example: 'analytics',
        gotcha: 'The built-in "default" user often has no password locally but is locked down in Cloud.',
        required: true,
      },
      password: {
        what: 'Password for the ClickHouse user.',
        where: 'Set when creating the user / from the Cloud console.',
        example: 'Strong-Passw0rd',
        required: true,
      },
    },
    troubleshooting: [
      'Connection refused / TLS handshake error → Secure does not match the port (8443+Secure-on vs 8123+Secure-off).',
      'Wrong port → using 9000 (native TCP) instead of the HTTP port 8123/8443.',
      'Authentication failed → wrong user/password, or the user is restricted to specific source IPs (HOST IP clause).',
      'Not enough privileges → grant SELECT on the target databases, or the readonly profile blocks the query.',
      'No tables visible → the database list is too narrow, or the user lacks SELECT on it.',
    ],
    docsUrl: 'https://clickhouse.com/docs/en/interfaces/http',
  },

  // ────────────────────────────── SQLite ────────────────────────────────
  sqlite: {
    overview:
      'Reads a local SQLite database file (.db/.sqlite) directly from the app server. No network, host, or ' +
      'credentials — just a file path. Primarily for dev/test workflows.',
    prerequisites: [
      'The SQLite file must already exist on the app server / be uploaded — SQLite is a local file, not a network service.',
      'The app process must have read access to the file path.',
    ],
    fields: {
      database: {
        what: 'Absolute path to the SQLite .db/.sqlite file on the server.',
        where: 'The path where the file lives on the app host (or where an upload placed it).',
        example: '/data/mydb.sqlite',
        gotcha: 'Must be an absolute path the server can read; a path on your laptop will not resolve. ":memory:" creates an empty throwaway DB.',
        required: true,
      },
    },
    troubleshooting: [
      'Unable to open database file → wrong path, the file does not exist on the server, or no read permission.',
      'Empty / no tables → you pointed at :memory: or an empty file; use the real .sqlite file.',
      'Path on your machine does not work → the path must be on the app server, not your local computer.',
      'Locked database → another process holds a write lock; SQLite is single-writer.',
    ],
    docsUrl: 'https://www.sqlite.org/uri.html',
  },

  // ────────────────────────────── MongoDB ───────────────────────────────
  mongodb: {
    overview:
      'Connects to MongoDB (self-hosted replica set or MongoDB Atlas) using a username + password. Supports ' +
      'standard host:port connections and Atlas SRV (mongodb+srv) connections, with optional TLS.',
    prerequisites: [
      'Network reachability: allow the app host to reach the MongoDB port; on Atlas add the app IP to the IP Access List.',
      `${READONLY_INTRO} Create a user with the built-in "read" role on the target database.`,
      'Decide standard vs Atlas/SRV: Atlas uses a mongodb+srv cluster host (enable "Use Atlas/SRV").',
    ],
    fields: {
      host: {
        what: 'MongoDB host (e.g. localhost) or Atlas cluster host (e.g. cluster0.abc.mongodb.net).',
        where: 'From your DBA, or the Atlas console "Connect" dialog (the host after mongodb+srv://).',
        example: 'cluster0.abc.mongodb.net  (or  mongo.internal.example.com)',
        gotcha: 'For Atlas, use the cluster host and turn on "Use Atlas/SRV"; do NOT paste the full mongodb+srv:// URI here.',
        required: true,
      },
      port: {
        what: 'MongoDB port. Ignored for Atlas/SRV connections (SRV resolves the port).',
        where: 'Default unless changed.',
        example: '27017',
        gotcha: 'Default is 27017. When "Use Atlas/SRV" is on, the port is ignored.',
        required: false,
      },
      database: {
        what: 'The database to connect to.',
        where: 'From your DBA, or the Atlas "Browse Collections" view.',
        example: 'app_production',
        gotcha: 'This is the data database; it can differ from the auth database (see Auth Database).',
        required: true,
      },
      auth_source: {
        what: 'The database to authenticate against. Defaults to "admin". Ignored for Atlas.',
        where: 'Usually "admin" (where the user was created); ask your DBA if the user lives elsewhere.',
        example: 'admin',
        gotcha: 'If the user was created in a specific DB rather than admin, set this to that DB or auth fails. Atlas ignores this.',
        required: false,
      },
      tls: {
        what: 'Enable TLS/SSL for the connection.',
        where: 'On for TLS-secured self-hosted deployments. (Atlas/SRV already implies TLS.)',
        example: 'false',
        gotcha: 'Default is off. Turn on only if your self-hosted server requires TLS; mismatching causes handshake errors.',
        required: false,
      },
      use_srv: {
        what: 'Use an Atlas/SRV (mongodb+srv) connection — DNS resolves the cluster nodes.',
        where: 'On for MongoDB Atlas; off for a plain host:port server.',
        example: 'true',
        gotcha: 'When on, the port and auth_source are ignored and TLS is implied — set the host to the SRV cluster host only.',
        required: false,
      },
      user: {
        what: 'MongoDB username. Leave blank for unauthenticated (local/dev) servers.',
        where: 'The read-only database user you created.',
        steps: [
          'use admin',
          'db.createUser({ user: "analytics", pwd: "Strong-Passw0rd", roles: [{ role: "read", db: "app_production" }] })',
        ],
        example: 'analytics',
        required: false,
      },
      password: {
        what: 'Password for the MongoDB user.',
        where: 'Set when creating the user / from the Atlas Database Access page.',
        example: 'Strong-Passw0rd',
        gotcha: 'If the password has URL-special characters, that is fine here (it is not embedded in a URI by you).',
        required: false,
      },
    },
    troubleshooting: [
      'Server selection timeout → app IP not on the Atlas IP Access List, wrong host/port (27017), or SRV mismatch (use_srv off for an Atlas cluster).',
      'Authentication failed → wrong credentials, or the wrong Auth Database (the user lives in admin or a specific DB).',
      'TLS handshake error → tls setting does not match the server (off vs required); Atlas/SRV always uses TLS.',
      'No collections / database not found → wrong database name, or the user lacks the "read" role on it.',
      'mongodb+srv resolution fails → DNS cannot resolve the SRV record; verify the cluster host and that use_srv is on.',
    ],
    docsUrl: 'https://www.mongodb.com/docs/manual/reference/connection-string/',
  },
} as ConnectorDocMap
