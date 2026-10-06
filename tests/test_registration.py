import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wda_registration",ROOT/"scripts/register_mcp.py")
registration=importlib.util.module_from_spec(spec)
spec.loader.exec_module(registration)


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix="wda install ")
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name).resolve()
        (self.root/"server").mkdir()
        (self.root/"server/iphone_wda.py").write_text("# synthetic entrypoint\n")
        self.installation={"pluginId":"iphone-use-wda@iphone-wda-local","installedPath":str(self.root),"version":"0.1.6"}

    def invoke(self,data):
        with patch.object(registration.sys,"stdin",io.StringIO(json.dumps(data))), contextlib.redirect_stdout(io.StringIO()):
            registration.main()

    def test_registers_same_namespace_and_installed_entrypoint_without_phone_requests(self):
        with patch.object(registration.subprocess,"run") as run:
            self.invoke(self.installation)
        run.assert_called_once_with(["codex","mcp","add","iphone_wda","--","python3",str(self.root/"server/iphone_wda.py")],check=True)

    def test_wrong_plugin_and_missing_entrypoint_do_not_change_config(self):
        for data in ({**self.installation,"pluginId":"iphone-use-wda-vision@iphone-wda-vision-local"},self.installation):
            if data==self.installation:(self.root/"server/iphone_wda.py").unlink()
            with self.subTest(data=data), patch.object(registration.subprocess,"run") as run, self.assertRaises(SystemExit):
                self.invoke(data)
            run.assert_not_called()

    def test_registration_failure_propagates_instead_of_reporting_success(self):
        with patch.object(registration.subprocess,"run",side_effect=subprocess.CalledProcessError(1,["codex","mcp","add"])), self.assertRaises(subprocess.CalledProcessError):
            self.invoke(self.installation)


if __name__=="__main__":unittest.main()
