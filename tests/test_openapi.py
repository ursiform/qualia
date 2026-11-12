"""Portable contract checks and real request/response validation."""

import json
import os
from pathlib import Path
import unittest

from qualia import Consequence, Intention, openapi, schema
from http_support import initial, request, running_server


def references(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref":
                yield item
            else:
                yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


def require(module):
    try:
        return __import__(module)
    except ImportError:
        if os.environ.get("CI"):
            raise AssertionError(f"Install qualia[test]: {module} is required in CI")
        raise unittest.SkipTest(f"Install qualia[test] for {module} checks")


class TestPortableContract(unittest.TestCase):
    def test_bundled_references_are_local_and_resolve(self):
        document = openapi()
        self.assertEqual(document["openapi"], "3.1.0")
        self.assertTrue(list(references(document)))
        for reference in references(document):
            self.assertTrue(reference.startswith("#/"), reference)
            target = document
            for part in reference[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
        for name in schema()["$defs"]:
            self.assertIn(name, document["components"]["schemas"])
        document["components"]["schemas"].clear()
        self.assertTrue(openapi()["components"]["schemas"])

    def test_authored_contract_reuses_the_canonical_schema(self):
        path = Path(__file__).resolve().parents[1] / "src/qualia/openapi.json"
        document = json.loads(path.read_text())
        for name in schema()["$defs"]:
            self.assertEqual(
                document["components"]["schemas"][name],
                {"$ref": f"qtp.v1.schema.json#/$defs/{name}"},
            )

    def test_document_is_valid_openapi_31(self):
        validator = require("openapi_spec_validator")
        validator.validate(openapi())
        from openapi_spec_validator.readers import read_from_filename

        path = Path(__file__).resolve().parents[1] / "src/qualia/openapi.json"
        document, base_uri = read_from_filename(str(path))
        validator.validate(document, base_uri=base_uri)


class TestOpenAPIExchange(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jsonschema = require("jsonschema")
        cls.contract = openapi()

    def validate(self, value, definition):
        self.jsonschema.Draft202012Validator(
            {"components": self.contract["components"], **definition}
        ).validate(value)

    def response(self, path, method, code, value):
        responses = self.contract["paths"][path][method]["responses"]
        definition = responses.get(str(code), responses.get("default"))
        self.assertIsNotNone(definition, (path, method, code))
        if "content" in definition:
            self.validate(value, definition["content"]["application/json"]["schema"])
        else:
            self.assertIsNone(value)

    def test_examples_follow_their_message_schemas(self):
        found = 0
        for route in self.contract["paths"].values():
            for operation in route.values():
                bodies = [operation.get("requestBody", {})]
                bodies.extend(operation["responses"].values())
                for body in bodies:
                    media = body.get("content", {}).get("application/json", {})
                    if "example" in media:
                        self.validate(media["example"], media["schema"])
                        found += 1
        self.assertGreaterEqual(found, 2)

    def test_initial_and_later_request_requirements(self):
        definition = {"$ref": "#/components/schemas/StepRequest"}
        payload = initial()
        self.validate(payload, definition)
        self.validate({**payload, "step": 1, "action": "forward"}, definition)
        for change in (
            {"action": "forward"},
            {"consequence": Consequence().to_dict()},
            {"step": 1},
            {"protocol": "unknown"},
            {"step": True},
            {"step": -1},
        ):
            with self.subTest(change=change):
                with self.assertRaises(self.jsonschema.ValidationError):
                    self.validate({**payload, **change}, definition)

    def test_remote_response_requires_remote_provenance(self):
        definition = {"$ref": "#/components/schemas/RemoteResponse"}
        value = Intention().to_dict()
        self.validate(value, definition)
        self.validate({"intention": value}, definition)
        for value in (
            {},
            {**value, "fallback": True},
            {"intention": {**value, "fallback": True}},
        ):
            with self.assertRaises(self.jsonschema.ValidationError):
                self.validate(value, definition)

    def test_real_http_success_and_error_bodies_follow_openapi(self):
        origin = "https://notebook.example"
        with running_server(origins=(origin,)) as server:
            for path in ("/api/status", "/openapi.json"):
                code, _, body = request(server, "GET", path)
                self.assertEqual(code, 200)
                self.response(path, "get", code, body)
            payload = initial()
            self.validate(
                payload,
                self.contract["paths"]["/api/qtp/step"]["post"]["requestBody"][
                    "content"
                ]["application/json"]["schema"],
            )
            code, _, body = request(server, "POST", "/api/qtp/step", payload)
            self.assertEqual(code, 200)
            self.response("/api/qtp/step", "post", code, body)
            for payload, headers, expected in [
                (payload, {}, 409),
                ({**payload, "protocol": "unknown"}, {}, 400),
                (payload, {"Origin": "https://untrusted.example"}, 403),
                (payload, {"Content-Type": "text/plain"}, 415),
                (b"", {"Content-Length": str(server.limit + 1)}, 413),
            ]:
                code, _, body = request(
                    server, "POST", "/api/qtp/step", payload, headers=headers
                )
                self.assertEqual(code, expected)
                self.response("/api/qtp/step", "post", code, body)
            code, _, body = request(
                server,
                "OPTIONS",
                "/api/qtp/step",
                headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
            )
            self.assertEqual(code, 204)
            self.response("/api/qtp/step", "options", code, body)
            self.assertEqual(server.status()["steps"], 1)
