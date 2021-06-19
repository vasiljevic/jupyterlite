import json
import os
import shutil

import jsonschema
from traitlets import Instance
from traitlets.config import LoggingConfigurable

from ..constants import (
    DISABLED_EXTENSIONS,
    FEDERATED_EXTENSIONS,
    SETTINGS_OVERRIDES,
    SOURCE_DATE_EPOCH,
)
from ..manager import LiteManager


class BaseAddon(LoggingConfigurable):
    """A base class for addons to the JupyterLite build chain

    Subclassing this is optional, but provides some useful utilities
    """

    manager: LiteManager = Instance(LiteManager)

    @property
    def log(self):
        return self.manager.log

    def copy_one(self, src, dest):
        """copy one Path (a file or folder)"""
        if dest.is_dir():
            shutil.rmtree(dest)
        elif dest.exists():
            dest.unlink()

        if not dest.parent.exists():
            self.log.debug(f"creating folder {dest.parent}")
            dest.parent.mkdir(parents=True)

        self.maybe_timestamp(dest.parent)

        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)

        self.maybe_timestamp(dest)

    def maybe_timestamp(self, path):
        if SOURCE_DATE_EPOCH not in os.environ:
            return

        if path.is_dir():
            for p in path.rglob("*"):
                self.timestamp_one(p)

        self.timestamp_one(path)

    def timestamp_one(self, path):
        """adjust the timestamp to be SOURCE_DATE_EPOCH for files newer than then

        see https://reproducible-builds.org/specs/source-date-epoch
        """
        stat = path.stat()
        sde = int(os.environ[SOURCE_DATE_EPOCH])
        if stat.st_mtime > sde:
            cls = self.__class__.__name__
            self.log.debug(
                f"[lite][base] <{cls}> set time to SOURCE_DATE_EPOCH {sde} on {path}"
            )
            os.utime(path, (sde, sde))
            return
        return

    def delete_one(self, src):
        """delete... something"""
        if src.is_dir():
            shutil.rmtree(src)
        elif src.exists():
            src.unlink()

    def validate_one_json_file(self, validator, path=None, data=None):
        if path:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        else:
            loaded = data

        if validator is None:
            return True

        validator.validate(loaded)

    def get_validator(self, schema_path, klass=jsonschema.Draft7Validator):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        return klass(schema)

    def merge_one_jupyterlite(self, out_path, in_paths):
        """write the out_path with all of the in_paths, where all are valid
        jupyter-lite.json files.

        TODO: notebooks
        """
        config = {}

        for in_path in in_paths:
            in_config = json.loads(in_path.read_text(encoding="utf-8"))

            for k, v in in_config.items():
                if k in [DISABLED_EXTENSIONS, FEDERATED_EXTENSIONS]:
                    config[k] = sorted({*config.get(k, []), *v})
                elif k in [SETTINGS_OVERRIDES]:
                    config[k] = config.get(k, {})
                    for pkg, pkg_config in v.items():
                        config[k][pkg] = config[k].get(pkg, {})
                        config[k][pkg].update(pkg_config)
                else:
                    config[k] = v

        self.dedupe_federated_extensions(config)

        out_path.write_text(
            json.dumps(config, indent=2, sort_keys=True), encoding="utf-8"
        )

        self.maybe_timestamp(out_path)

    def dedupe_federated_extensions(self, config):
        """update a federated_extension list in-place, ensuring unique names.

        TODO: best we can do, for now.
        """
        if FEDERATED_EXTENSIONS not in config:
            return

        named = {}

        for ext in config[FEDERATED_EXTENSIONS]:
            named[ext["name"]] = ext

        config[FEDERATED_EXTENSIONS] = sorted(named.values(), key=lambda x: x["name"])
