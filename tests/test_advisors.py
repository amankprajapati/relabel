"""Advisor tests with stand-ins for the model providers:  python -m unittest discover tests"""
import json
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "relabel_gui_app"))
from advisors import AdviceRequest, AdvisorError, AdvisorRegistry  # noqa: E402
from advisors.base import answer_schema, build_prompt, parse_answer  # noqa: E402
from advisors.claude_api import ClaudeAPIAdvisor  # noqa: E402
from advisors.cli_agents import ClaudeCodeAdvisor, CliAgentAdvisor, CodexAdvisor  # noqa: E402

try:
    import anthropic  # noqa: F401
    HAVE_ANTHROPIC = True
except ImportError:
    HAVE_ANTHROPIC = False

CLASSES = ["person", "car", "truck"]
REQUEST = AdviceRequest(crop_jpeg=b"\xff\xd8crop", context_jpeg=b"\xff\xd8frame", classes=CLASSES, current_class="car")


class ParseAnswerTest(unittest.TestCase):
    def test_plain_json(self):
        s = parse_answer('{"class": "truck", "reason": "Open cargo bed behind the cab."}', CLASSES)
        self.assertEqual((s.cls, s.reason, s.in_list), ("truck", "Open cargo bed behind the cab.", True))

    def test_json_inside_prose_or_code_fence(self):
        s = parse_answer('Here you go:\n```json\n{"class": "Person", "reason": "walking"}\n```', CLASSES)
        self.assertEqual((s.cls, s.in_list), ("person", True))       # mapped onto the project's spelling

    def test_class_outside_the_list_is_flagged(self):
        s = parse_answer('{"class": "bus", "reason": "long vehicle"}', CLASSES)
        self.assertEqual((s.cls, s.in_list), ("bus", False))

    def test_unparseable_reply_raises(self):
        with self.assertRaises(AdvisorError):
            parse_answer("I think it is a truck.", CLASSES)

    def test_schema_restricts_class_to_the_list(self):
        self.assertEqual(answer_schema(CLASSES)["properties"]["class"]["enum"], CLASSES)
        self.assertNotIn("enum", answer_schema([])["properties"]["class"])

    def test_prompt_names_classes_and_current_label(self):
        p = build_prompt(REQUEST)
        self.assertIn("person, car, truck", p)
        self.assertIn('currently labelled "car"', p)


class FakeMessages:
    def __init__(self, response):
        self.response, self.calls = response, []

    def create(self, **params):
        self.calls.append(params)
        return self.response


def fake_client(text, stop_reason="end_turn"):
    response = SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(response)))


@unittest.skipUnless(HAVE_ANTHROPIC, "anthropic SDK not installed")
class ClaudeAPIAdvisorTest(unittest.TestCase):
    def make(self, text, stop_reason="end_turn", model=None):
        advisor = ClaudeAPIAdvisor(model=model)
        advisor._client = fake_client(text, stop_reason)
        return advisor

    def test_sends_both_images_and_a_constrained_schema(self):
        advisor = self.make('{"class": "truck", "reason": "Cargo bed."}')
        s = advisor.suggest(REQUEST)
        self.assertEqual((s.cls, s.reason), ("truck", "Cargo bed."))
        params = advisor._client.beta.messages.calls[0]
        self.assertEqual(params["model"], "claude-opus-5")
        blocks = params["messages"][0]["content"]
        self.assertEqual([b["type"] for b in blocks], ["image", "image", "text"])
        self.assertEqual(params["output_config"]["format"]["schema"]["properties"]["class"]["enum"], CLASSES)
        self.assertEqual((params["fallbacks"], params["betas"]), ("default", ["server-side-fallback-2026-07-01"]))

    def test_no_fallbacks_for_models_that_do_not_take_them(self):
        advisor = self.make('{"class": "car", "reason": "x"}', model="claude-haiku-4-5")
        advisor.suggest(REQUEST)
        self.assertNotIn("fallbacks", advisor._client.beta.messages.calls[0])

    def test_refusal_becomes_a_user_message(self):
        with self.assertRaises(AdvisorError):
            self.make("", stop_reason="refusal").suggest(REQUEST)


class PythonStandInCli(CliAgentAdvisor):
    """Exercises the CLI template method with the Python interpreter standing in for an agent CLI."""
    id, label, executable = "stand-in", "Stand-in CLI", sys.executable

    def __init__(self, script):
        super().__init__(timeout=30)
        self.script = script

    def command(self, exe, images, workdir):
        return [exe, "-c", self.script] + images

    def reply(self, stdout, workdir):
        return stdout


class CliAgentAdvisorTest(unittest.TestCase):
    def test_images_reach_the_cli_and_the_prompt_arrives_on_stdin(self):
        script = ("import sys, os, json; prompt = sys.stdin.read(); "
                  "ok = all(os.path.getsize(p) > 0 for p in sys.argv[1:]) and 'truck' in prompt; "
                  "print(json.dumps({'class': 'truck' if ok else 'person', 'reason': str(len(sys.argv) - 1) + ' images'}))")
        s = PythonStandInCli(script).suggest(REQUEST)
        self.assertEqual((s.cls, s.reason), ("truck", "2 images"))

    def test_a_failing_cli_raises_with_its_error(self):
        with self.assertRaises(AdvisorError) as ctx:
            PythonStandInCli("import sys; sys.stderr.write('not logged in'); sys.exit(1)").suggest(REQUEST)
        self.assertIn("not logged in", str(ctx.exception))

    def test_missing_cli_is_reported_not_ready(self):
        advisor = ClaudeCodeAdvisor()
        advisor.executable = "definitely-not-installed-relabel-test"
        self.assertFalse(advisor.availability()[0])
        with self.assertRaises(AdvisorError):
            advisor.suggest(REQUEST)

    def test_claude_code_reply_is_read_from_its_json_envelope(self):
        out = json.dumps({"type": "result", "is_error": False, "result": '{"class": "car", "reason": "sedan"}'})
        self.assertIn('"car"', ClaudeCodeAdvisor().reply(out, "."))

    def test_codex_command_attaches_each_image(self):
        argv = CodexAdvisor().command("codex", ["a.jpg", "b.jpg"], "w")
        self.assertEqual(argv.count("--image"), 2)
        self.assertEqual(argv[-1], "-")


class RegistryTest(unittest.TestCase):
    def test_describe_and_get(self):
        reg = AdvisorRegistry([PythonStandInCli("print(1)")])
        self.assertEqual(reg.describe(), [{"id": "stand-in", "label": "Stand-in CLI", "ready": True,
                                           "hint": sys.executable}])
        with self.assertRaises(AdvisorError):
            reg.get("nope")


if __name__ == "__main__":
    unittest.main()
