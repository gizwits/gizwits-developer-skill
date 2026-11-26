import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import firmware as fw


class FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.sdk = self.project / "gagent-sdk"
        self.sdk.mkdir(parents=True)
        (self.project / "main/generated").mkdir(parents=True)
        (self.sdk / "library.a").write_bytes(b"SDK fixture, not executable")
        self.lock = {"target":"esp32c3", "camera":False, "idf_revision":"a"*40, "compiler_version":"15.2.0"}
        manifest = {**self.lock,"files_sha256":{"library.a":fw.digest(self.sdk / "library.a")}}
        (self.sdk / "sdk-manifest.json").write_text(json.dumps(manifest))
        self.lock["manifest_sha256"] = fw.digest(self.sdk / "sdk-manifest.json")
        (self.project / "sdk.lock.json").write_text(json.dumps(self.lock))
        self.build = self.project / "build-skill"
        self.build.mkdir()

    def test_reject_camera_target(self):
        self.lock.update(target="esp32p4",camera=True)
        (self.project / "sdk.lock.json").write_text(json.dumps(self.lock))
        with self.assertRaisesRegex(ValueError,"P4"):
            fw.requirements(self.project)

    def test_sdk_tampering_stops_workflow(self):
        (self.sdk / "library.a").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError,"哈希"):
            fw.requirements(self.project)

    def test_credentials_saved_privately_without_echo(self):
        source = self.root / "private.json"
        source.write_text(json.dumps({"product_key":"1"*32,"product_secret":"2"*32}))
        result = fw.write_credentials(self.project,source=source)
        self.assertNotIn("2"*32,json.dumps(result))
        path = self.project / "main/product_secrets.hpp"
        self.assertIn('GAGENT_SOC_PRODUCT_SECRET "'+"2"*32+'"',path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        with self.assertRaisesRegex(ValueError,"已存在"):
            fw.write_credentials(self.project,source=source)

    def test_invalid_secret_not_written_or_echoed(self):
        source = self.root / "private.json"
        source.write_text(json.dumps({"product_key":"1"*32,"product_secret":"BAD_PRIVATE_VALUE"}))
        with self.assertRaises(ValueError) as error:
            fw.write_credentials(self.project,source=source)
        self.assertNotIn("BAD_PRIVATE_VALUE",str(error.exception))
        self.assertFalse((self.project/"main/product_secrets.hpp").exists())

    def test_doctor_detects_missing_and_wrong_environment(self):
        idf = self.root / "idf"
        (idf / "tools/cmake").mkdir(parents=True)
        (idf / "tools/cmake/version.cmake").write_text('set(IDF_VERSION_MAJOR 6)\nset(IDF_VERSION_MINOR 1)')
        def probe(command,cwd=None):
            if command[:2] == ["git","rev-parse"]: return "b"*40
            if command[:2] == ["git","status"]: return ""
            if command[0] == "riscv32-esp-elf-g++": return "14.2.0"
            if command[0] == "cmake": return "cmake version 3.24.0"
            if command[0] == "ninja": return "1.12.0"
            return "ESP-IDF v6.1"
        with patch.object(fw,"probe",side_effect=probe),patch.dict(os.environ,{"IDF_PATH":str(idf)}):
            result = fw.doctor(self.project)
        self.assertFalse(result["ready"])
        self.assertTrue(any("提交" in p for p in result["problems"]))
        self.assertTrue(any("GCC" in p for p in result["problems"]))

    def prepare_build(self):
        (self.build/"bootloader").mkdir()
        (self.build/"bootloader/bootloader.bin").write_bytes(b"BOOT")
        (self.build/"app.bin").write_bytes(b"APPLICATION")
        flash = {"extra_esptool_args":{"chip":"esp32c3"},
                 "flash_files":{"0x0":"bootloader/bootloader.bin","0x100":"app.bin"},
                 "flash_settings":{"flash_size":"4MB","flash_mode":"dio","flash_freq":"80m"}}
        (self.build/"flasher_args.json").write_text(json.dumps(flash))
        (self.build/"project_description.json").write_text(json.dumps({"target":"esp32c3","project_path":str(self.project),"app_bin":"app.bin"}))
        (self.build/"firmware.factory.bin").write_bytes(b"BOOT"+b"\xff"*252+b"APPLICATION")
        (self.project/"main/generated/generation.json").write_text(json.dumps({"product_key":"1"*32,"protocol_type":"var_len","datapoint_count":1}))
        (self.project/"main/generated/datapoints.json").write_text('{"protocolType":"var_len"}')
        (self.project/"main/product_secrets.hpp").write_text("DO_NOT_PACKAGE_THIS_SECRET")

    def test_package_preserves_offsets_hashes_excludes_sources(self):
        self.prepare_build()
        output = self.root/"firmware.zip"
        fw.package(self.project,self.build,output,self.lock)
        with zipfile.ZipFile(output) as archive:
            self.assertNotIn("main/product_secrets.hpp",archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["factory_offset"],"0x0")
            self.assertEqual(manifest["flash_files"]["0x100"],"app.bin")
            self.assertEqual(manifest["sha256"]["app.bin"],fw.digest(self.build/"app.bin"))
            self.assertNotIn(b"DO_NOT_PACKAGE_THIS_SECRET",b"".join(archive.read(p) for p in archive.namelist()))
        self.assertEqual(output.stat().st_mode & 0o777,0o600)

    def test_stale_or_wrong_merged_image_rejected(self):
        self.prepare_build()
        (self.build/"app.bin").write_bytes(b"DIFFERENT!!")
        with self.assertRaisesRegex(ValueError,"不一致"):
            fw.package(self.project,self.build,self.root/"firmware.zip",self.lock)

    def test_cross_chip_artifacts_rejected(self):
        self.prepare_build()
        data = fw.load(self.build/"project_description.json")
        data["target"] = "esp32c5"
        (self.build/"project_description.json").write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,"芯片"):
            fw.package(self.project,self.build,self.root/"firmware.zip",self.lock)

    def test_build_failure_prevents_merge_and_packaging(self):
        check = {"ready":True,"actual":{"idf_path":str(self.root/"idf")}}
        with patch.object(fw,"doctor",return_value=check),patch.object(fw.subprocess,"run",side_effect=fw.subprocess.CalledProcessError(1,["build"])) as run:
            with self.assertRaises(fw.subprocess.CalledProcessError):
                fw.build_package(self.project,self.build,self.root/"firmware.zip")
            self.assertEqual(run.call_count,1)
        self.assertFalse((self.root/"firmware.zip").exists())


if __name__ == "__main__":
    unittest.main()
