import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from budget.__main__ import main
from budget.storage import Store
from tests.fakes import ENV

EXPORT = Path(__file__).parent / "fixtures" / "result.json"


class CliTest(unittest.TestCase):
    def test_import_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "sub", "budget.db")
            env = {**ENV, "BUDGET_DB": db}
            out = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out):
                code = main(["import-export", str(EXPORT), "--env", os.path.join(tmp, "missing.env")])
            self.assertEqual(code, 0)
            self.assertIn("added 5, duplicates 0, ignored 2", out.getvalue())
            store = Store(db)
            self.assertEqual(len(store.all()), 5)
            store.close()

    def test_refuses_without_members(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True), \
                redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(main(["import-export", str(EXPORT), "--env", os.path.join(tmp, "x")]), 2)


if __name__ == "__main__":
    unittest.main()
