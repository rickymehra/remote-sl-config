import json

import jsonschema
import pytest

from conftest import COMMUNITY, ROOT
from slcfg import codec

SCHEMA = json.loads((ROOT / "schema/template.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def test_schema_is_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("path", COMMUNITY, ids=lambda p: p.name)
def test_decoded_dumps_match_schema(path):
    for t in codec.decode_file(path.read_bytes()):
        VALIDATOR.validate(t.to_json())


def test_schema_rejects_long_label(vstation):
    doc = codec.decode(vstation).to_json()
    doc["controls"]["encoder_1"]["name"] = "NineChars"
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(doc)
    doc["controls"]["encoder_1"]["name"] = "ok"
    doc["controls"]["encoder_1"]["number"] = 128
    with pytest.raises(jsonschema.ValidationError):
        VALIDATOR.validate(doc)
