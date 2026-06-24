"""Read-only probe for the Microsoft Fabric connector.

Run inside ca-app:
  docker cp scripts/fabric_probe.py ca-app:/tmp/fabric_probe.py
  docker exec -e FAB_TENANT=... -e FAB_CLIENT=... -e FAB_SECRET=... \
      ca-app /opt/venv/bin/python /tmp/fabric_probe.py

Writes nothing, creates no DB row. Just test_connection() + get_tables().
"""
import os
import sys

sys.path.insert(0, "/app/backend")

from app.data_sources.clients.ms_fabric_client import MsFabricClient

client = MsFabricClient(
    server_hostname="frhyucu26ckupeg6zzmno4bsde-utccgytlptlefo5yizfdykvaly.datawarehouse.fabric.microsoft.com",
    database="CityPlatforms",
    schema="ods",
    tenant_id=os.environ["FAB_TENANT"],
    client_id=os.environ["FAB_CLIENT"],
    client_secret=os.environ["FAB_SECRET"],
)

print("== test_connection ==")
res = client.test_connection()
print(res)

if res.get("success"):
    print("== tables in schema 'ods' ==")
    tables = client.get_tables()
    for t in tables:
        print(f"  {t.name}  ({len(t.columns)} cols)")
    print(f"total: {len(tables)} tables")
