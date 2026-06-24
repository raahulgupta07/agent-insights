from contextlib import contextmanager
from typing import Generator, Optional

import pyodbc

from app.data_sources.clients.ms_fabric_client import (
    MsFabricClient,
    _connect_with_retry,
)


class MsFabricUserClient(MsFabricClient):
    """Microsoft Fabric SQL endpoint via Entra USER login (email + password).

    Uses the ODBC driver's built-in ``Authentication=ActiveDirectoryPassword``
    (ROPC) flow — no Azure AD app registration, no Client ID, no secret. The
    user's Entra email + password are passed straight to the driver.

    LIMITATION (Microsoft, not our code): ActiveDirectoryPassword fails when the
    account has MFA or Conditional Access enabled, is federated (ADFS), or the
    tenant is set service-principal-only for Fabric APIs. In those cases the
    service-principal connector (``ms_fabric``) is the supported path.

    Reuses all schema/table/query logic from MsFabricClient; only ``connect()``
    differs (password auth string instead of a fetched bearer token).
    """

    def __init__(
        self,
        server_hostname: str,
        database: str,
        username: str = None,
        password: str = None,
        schema: Optional[str] = None,
        tenant_id: str = None,
        **kwargs,
    ):
        # Base sets up server/database/schema parsing; SP fields stay None.
        super().__init__(
            server_hostname=server_hostname,
            database=database,
            tenant_id=tenant_id,
            schema=schema,
        )
        self.username = username
        self.password = password

    @contextmanager
    def connect(self) -> Generator:
        """Yield a connection using Entra ActiveDirectoryPassword auth."""
        conn = None
        try:
            # Explicit ,1433 + a generous login timeout are required: without the
            # port the ODBC 18 driver throws 08001/(26) "error during handshakes
            # before login" against Fabric's redirect-policy endpoint.
            host = self.server_hostname
            if "," not in host:
                host = f"{host},1433"
            conn_str = (
                f"DRIVER={{ODBC Driver 18 for SQL Server}};"
                f"SERVER={host};"
                f"DATABASE={self.database};"
                f"Encrypt=yes;"
                f"TrustServerCertificate=no;"
                f"Connection Timeout=30;"
                f"Authentication=ActiveDirectoryPassword;"
                f"UID={self.username};"
                f"PWD={self.password};"
            )
            conn = _connect_with_retry(conn_str)
            yield conn
        except Exception as e:
            raise RuntimeError(f"Error connecting to Microsoft Fabric (user login): {e}")
        finally:
            if conn is not None:
                conn.close()

    @property
    def description(self) -> str:
        base = super().description
        return base.replace(
            "Microsoft Fabric SQL Endpoint",
            "Microsoft Fabric SQL Endpoint (user login)",
        )
