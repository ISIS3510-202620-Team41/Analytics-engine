"""Utilidades compartidas por los tests."""
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from db import COLUMNS, connect, insert_rows
from filters import to_db_time

try:
    from fastapi.testclient import TestClient
    from main import app
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

NOW = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
U1, U2, U3, U4, U5 = (str(uuid4()) for _ in range(5))

_ENV_KEYS = ("ANALYTICS_DB_PATH", "ANALYTICS_INGEST_KEY", "ANALYTICS_ADMIN_KEY")


def row(event_type, user=U1, at=NOW, **fields):
    """Fila lista para insertar, con todas las columnas en None salvo las indicadas."""
    base = {c: None for c in COLUMNS}
    base.update(event_id=str(uuid4()), event_type=event_type, user_id=user,
                occurred_at=to_db_time(at), received_at=to_db_time(at))
    base.update(fields)
    return base


class DbTestCase(unittest.TestCase):
    """Cada test usa su propia base SQLite temporal y sin llaves de API."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        os.environ["ANALYTICS_DB_PATH"] = str(Path(self._tmp.name) / "test.db")
        os.environ.pop("ANALYTICS_INGEST_KEY", None)
        os.environ.pop("ANALYTICS_ADMIN_KEY", None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def load(self, rows):
        with connect() as conn:
            insert_rows(conn, rows)


class ApiTestCase(DbTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app)