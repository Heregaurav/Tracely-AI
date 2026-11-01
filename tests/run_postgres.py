"""Create a fresh database in the private temporary cluster and run all Python tests.

This helper never drops or resets a database. It is deliberately limited to the
local tracely_test role and /tmp socket; use normal pytest for other test services.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import psycopg2
from psycopg2 import sql

if __name__=="__main__":
    name="tracely_test_"+uuid.uuid4().hex[:12]
    connection=psycopg2.connect(dbname="postgres",user="tracely_test",host="/tmp/tracely-test-pg",port=55439)
    try:
        connection.autocommit=True
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    finally:
        connection.close()
    url=f"postgresql+psycopg2://tracely_test@/{name}?host=/tmp/tracely-test-pg&port=55439"
    env={**os.environ,"TEST_DATABASE_URL":url,"TRACELY_TEST_STATE_PATH":"/tmp/tracely-e2e-state.json"}
    result=subprocess.run([sys.executable,"-m","pytest","tests","-q","--tb=short"],env=env)
    print("Isolated test database:",name)
    print("Browser fixture state: /tmp/tracely-e2e-state.json")
    sys.exit(result.returncode)
