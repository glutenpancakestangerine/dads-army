"""tools/release_check.py: GitHub runs it on every pull request and push, and tags each new
version. The version in config.yaml is what Home Assistant offers, so server.py and the
changelog must say the same."""
import contextlib
import importlib.util
import io
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("release_check", os.path.join(ROOT, "tools", "release_check.py"))
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)

CHANGELOG = """# Changelog

## 1.3.0

**New**

- Scanning

### Fixes

- A fix

## 1.2.0

- Older
"""


class ReleaseCheckTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="release-")
        os.makedirs(os.path.join(self.dir, "dadsarmy"))
        self.write(config="1.3.0", server="1.3.0", changelog=CHANGELOG)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, config=None, server=None, changelog=None):
        files = {rc.CONFIG: config is not None and 'name: Dads Army\nversion: "%s"\nslug: dadsarmy\n' % config,
                 rc.SERVER: server is not None and 'import os\n\nVERSION = "%s"\n' % server,
                 rc.CHANGELOG: changelog}
        for path, text in files.items():
            if text is not None and text is not False:
                with open(os.path.join(self.dir, path), "w", encoding="utf-8") as f:
                    f.write(text)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rc.main(["--root", self.dir] + list(args))
        return code, out.getvalue().strip(), err.getvalue()

    def test_all_agree(self):
        self.assertEqual(rc.check(self.dir), ("1.3.0", []))
        self.assertEqual(self.run_main(), (0, "1.3.0", ""))

    def test_notes_are_the_whole_entry(self):
        code, out, _ = self.run_main("--notes")
        self.assertEqual(code, 0)
        self.assertEqual(out, "**New**\n\n- Scanning\n\n### Fixes\n\n- A fix")

    def test_server_out_of_step(self):
        self.write(server="1.2.0")
        version, problems = rc.check(self.dir)
        self.assertEqual(version, "1.3.0")
        self.assertEqual(len(problems), 1)
        self.assertIn("VERSION is 1.2.0", problems[0])

    def test_no_changelog_entry(self):
        self.write(config="1.4.0", server="1.4.0")
        code, out, err = self.run_main()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("the newest entry is 1.3.0", err)
        self.assertIn("Add '## 1.4.0' at the top", err)

    def test_github_shows_problems_on_the_change(self):
        self.write(server="1.2.0")
        os.environ["GITHUB_ACTIONS"] = "true"
        try:
            _, _, err = self.run_main()
        finally:
            os.environ.pop("GITHUB_ACTIONS", None)
        self.assertTrue(err.startswith("::error::dadsarmy/server.py"))

    def test_missing_or_odd_version(self):
        self.write(config="soon")
        self.assertIn("no version like 1.2.3", rc.check(self.dir)[1][0])
        os.remove(os.path.join(self.dir, rc.CONFIG))
        self.assertIn("found nothing", rc.check(self.dir)[1][0])

    def test_the_real_repository_agrees(self):
        version, problems = rc.check(ROOT)
        self.assertEqual(problems, [])
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        with open(os.path.join(ROOT, rc.CHANGELOG), encoding="utf-8") as f:
            self.assertTrue(rc.notes(f.read(), version))
