import sqlite3
import json

conn = sqlite3.connect("db/db.sqlite3")
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT failure_reason, failure_detail, status FROM product_runs WHERE sku = 'AG-01' ORDER BY created_at DESC LIMIT 1")
row = c.fetchone()
print(json.dumps(dict(row) if row else {}))
