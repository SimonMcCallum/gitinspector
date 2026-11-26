# coding: utf-8
#
# Copyright © 2012-2026 Ejwa Hosting AB. All rights reserved.
#
# This file is part of gitinspector.
#
# gitinspector is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# gitinspector is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with gitinspector. If not, see <http://www.gnu.org/licenses/>.

from __future__ import unicode_literals
import json
import os
import sys
import threading
from xml.etree import ElementTree

try:
	import unittest2 as unittest
except ImportError:
	import unittest

from gitinspector import gitlab, llm, optval
from .harness import Repository, analyze_blame, analyze_changes
from .test_gitlab import write_dump
from .test_options import run_inside

try:
	from http.server import BaseHTTPRequestHandler, HTTPServer
except ImportError:
	BaseHTTPRequestHandler = HTTPServer = None

ANSWER = {
	"summary": "Two authors, one of whom wrote most of the code.",
	"process": "Short bursts of work, little review.",
	"members": [{"name": "Alice Able", "role": "builder", "contribution": "Wrote the menu.",
	             "evidence": "1 commit, 100% of the menu file.", "concerns": ""}],
	"milestones": "",
	"risks": ["One author matched no GitLab user."],
	"questions": ["Who is Mystery Person?"],
	"confidence": "medium",
}

class FakeChatServer(object):
	"""The smallest OpenAI-compatible chat server: records the request, answers with a canned
	completion. Run in a thread for the duration of a test."""

	def __init__(self, reply, status=200):
		server = self
		server.requests = []

		class Handler(BaseHTTPRequestHandler):
			def do_POST(self):
				length = int(self.headers.get("Content-Length") or 0)
				server.requests.append((self.path, json.loads(self.rfile.read(length).decode("utf-8"))))
				body = json.dumps(reply).encode("utf-8")
				self.send_response(status)
				self.send_header("Content-Type", "application/json")
				self.send_header("Content-Length", str(len(body)))
				self.end_headers()
				self.wfile.write(body)

			def log_message(self, *arguments):
				pass

		self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
		self.url = "http://127.0.0.1:{0}/v1".format(self.httpd.server_address[1])
		self.thread = threading.Thread(target=self.httpd.serve_forever)
		self.thread.daemon = True

	def __enter__(self):
		self.thread.start()
		return self

	def __exit__(self, *arguments):
		self.httpd.shutdown()
		self.httpd.server_close()

def completion(content):
	return {"choices": [{"message": {"role": "assistant", "content": content}}]}

class BackendSelectionTest(unittest.TestCase):
	def test_only_the_known_backends_are_accepted(self):
		self.assertEqual(llm.select("Local"), "local")
		self.assertEqual(llm.select("claude-code"), "claude-code")
		with self.assertRaises(optval.InvalidOptionArgument):
			llm.select("gpt")

	def test_the_defaults_follow_the_backend(self):
		settings = llm.Settings()
		self.assertFalse(settings.is_enabled())
		settings.backend = "claude"
		self.assertEqual(settings.resolved_model(), "claude-opus-5-5")
		settings.backend = "local"
		self.assertEqual(settings.resolved_url(), llm.DEFAULT_LOCAL_URL)
		settings.url = "http://box:1234/v1/"
		self.assertEqual(settings.resolved_url(), "http://box:1234/v1")

class AnswerParsingTest(unittest.TestCase):
	def test_a_fenced_or_chatty_answer_still_yields_the_object(self):
		self.assertEqual(llm.parse_json_object('{"a": 1}'), {"a": 1})
		self.assertEqual(llm.parse_json_object('Here you go:\n```json\n{"a": 1}\n```'), {"a": 1})
		self.assertEqual(llm.parse_json_object('Sure. {"a": {"b": 2}} Done.'), {"a": {"b": 2}})
		with self.assertRaises(llm.LLMError):
			llm.parse_json_object("no object here")

	def test_missing_fields_are_filled_and_odd_types_flattened(self):
		result = llm.normalize({"summary": ["two", "parts"], "members": [{"name": "A"}, "B"], "risks": "one risk",
		                        "confidence": "certain"})
		self.assertEqual(result["summary"], "two parts")
		self.assertEqual(result["members"][0], {"name": "A", "role": "", "contribution": "", "evidence": "", "concerns": ""})
		self.assertEqual(result["members"][1]["name"], "B")
		self.assertEqual(result["risks"], ["one risk"])
		self.assertEqual(result["questions"], [])
		self.assertEqual(result["confidence"], "low")
		with self.assertRaises(llm.LLMError):
			llm.normalize(["not", "an", "object"])

class EvidenceTest(unittest.TestCase):
	def setUp(self):
		self.repository = Repository()
		self.repository.commit("Closes #2 menu", {"menu.py": "y = 2\nz = 3\n"}, "Alice Able", "alice@example.com")
		self.repository.commit("Start #1", {"player.py": "x = 1\n"}, "Bob Baker", "bob@example.com",
		                       "2015-02-01T12:00:00+0000")
		self.dump = write_dump(os.path.join(self.repository.location, "dump.json"))

	def tearDown(self):
		self.repository.remove()

	def test_the_pack_holds_the_numbers_of_the_report(self):
		class Repo(object):
			name = "game"
			branch = "main"

		changes = analyze_changes(self.repository)
		blame = analyze_blame(self.repository, changes)
		data = gitlab.GitLabData.from_dump(self.dump).join(self.repository.location)
		evidence = llm.build_evidence([Repo()], changes, blame, None, data, useweeks=True)

		self.assertEqual(evidence["commits_analyzed"], 2)
		self.assertEqual(evidence["period_length"], "week")
		authors = dict((author["name"], author) for author in evidence["authors"])
		self.assertEqual(authors["Alice Able"]["commits"], 1)
		self.assertEqual(authors["Alice Able"]["insertions"], 2)
		self.assertEqual(authors["Alice Able"]["owned_lines_now"], 2)
		self.assertEqual(authors["Alice Able"]["most_responsible_for"], [{"file": "menu.py", "lines": 2}])
		self.assertEqual(len(evidence["timeline"]), 2)
		self.assertEqual(evidence["gitlab"]["totals"]["issues"], 4)
		self.assertEqual(evidence["gitlab"]["issues_sample"][1]["committers"], {"alice": 1})
		prompt = llm.build_user_prompt(evidence, "Mark the menu generously.")
		self.assertIn("\"commits_analyzed\":2", prompt)
		self.assertIn("Mark the menu generously.", prompt)

@unittest.skipUnless(HTTPServer, "the fake chat server needs http.server")
class LocalBackendTest(unittest.TestCase):
	def setUp(self):
		self.repository = Repository()
		self.repository.commit("Closes #2 menu", {"menu.py": "y = 2\n"}, "Alice Able", "alice@example.com")
		self.dump = write_dump(os.path.join(self.repository.location, "dump.json"))

	def tearDown(self):
		self.repository.remove()

	def test_the_request_is_a_chat_completion_in_json_mode(self):
		with FakeChatServer(completion(json.dumps(ANSWER))) as server:
			settings = llm.Settings()
			settings.backend = "local"
			settings.url = server.url
			settings.model = "tiny"
			result = llm.assess(settings, {"commits_analyzed": 1})

			self.assertEqual(result["summary"], ANSWER["summary"])
			(path, body) = server.requests[0]
			self.assertEqual(path, "/v1/chat/completions")
			self.assertEqual(body["model"], "tiny")
			self.assertEqual(body["response_format"], {"type": "json_object"})
			self.assertEqual([message["role"] for message in body["messages"]], ["system", "user"])
			self.assertIn("\"commits_analyzed\":1", body["messages"][1]["content"])

	def test_a_server_that_answers_in_prose_is_still_read(self):
		with FakeChatServer(completion("Sure:\n```json\n" + json.dumps(ANSWER) + "\n```")) as server:
			settings = llm.Settings()
			settings.backend = "local"
			settings.url = server.url
			self.assertEqual(llm.assess(settings, {})["questions"], ANSWER["questions"])

	def test_a_server_error_is_an_llm_error(self):
		with FakeChatServer({"error": "model not found"}, status=404) as server:
			settings = llm.Settings()
			settings.backend = "local"
			settings.url = server.url
			with self.assertRaises(llm.LLMError):
				llm.assess(settings, {})

	def test_no_server_is_an_llm_error_not_a_crash(self):
		settings = llm.Settings()
		settings.backend = "local"
		settings.url = "http://127.0.0.1:9/v1"
		with self.assertRaises(llm.LLMError):
			llm.assess(settings, {})

	def test_the_assessment_lands_in_every_output_format(self):
		with FakeChatServer(completion(json.dumps(ANSWER))) as server:
			options = ["-f", "**", "--gitlab-dump", self.dump, "--llm=local", "--llm-url", server.url, "--llm-model", "tiny"]

			(status, output, errors) = run_inside(self.repository.location, "-F", "json", *options)
			self.assertEqual(status, 0, errors)
			section = json.loads(output)["gitinspector"]["assessment"]
			self.assertEqual(section["backend"], "local")
			self.assertEqual(section["model"], "tiny")
			self.assertEqual(section["members"][0]["name"], "Alice Able")
			self.assertEqual(section["risks"], ANSWER["risks"])
			#The pack the model saw carried the tracker data.
			self.assertIn("\"gitlab\":", server.requests[-1][1]["messages"][1]["content"])

			(status, output, errors) = run_inside(self.repository.location, "-F", "xml", *options)
			self.assertEqual(status, 0, errors)
			section = ElementTree.fromstring(output.encode("utf-8")).find("assessment")
			self.assertEqual(section.findtext("summary"), ANSWER["summary"])

			(status, output, errors) = run_inside(self.repository.location, "-F", "text", *options)
			self.assertEqual(status, 0, errors)
			self.assertIn("Who is Mystery Person?", output)
			self.assertIn("tiny at " + server.url, output)

			(status, output, errors) = run_inside(self.repository.location, "-F", "html", *options)
			self.assertEqual(status, 0, errors)
			self.assertIn("Who is Mystery Person?", output)

	def test_an_unreachable_model_leaves_the_report_intact_and_says_why(self):
		(status, output, errors) = run_inside(self.repository.location, "-F", "json", "-f", "**", "--llm=local",
		                                      "--llm-url", "http://127.0.0.1:9/v1")
		self.assertEqual(status, 0, errors)
		report = json.loads(output)["gitinspector"]
		self.assertIn("changes", report)
		self.assertIn("no model server", report["assessment"]["error"])

class OptionsTest(unittest.TestCase):
	def setUp(self):
		self.repository = Repository()
		self.repository.commit("add", {"a.py": "x = 1\n"})

	def tearDown(self):
		self.repository.remove()

	def test_an_unknown_backend_is_rejected_like_any_bad_option(self):
		(status, output, errors) = run_inside(self.repository.location, "--llm=gpt")
		self.assertEqual(status, 2)
		self.assertIn("backend", errors)

	def test_a_bad_token_count_is_rejected(self):
		(status, output, errors) = run_inside(self.repository.location, "--llm-max-tokens=lots")
		self.assertEqual(status, 2)
		self.assertIn("positive integer", errors)

	def test_the_help_lists_the_new_options(self):
		(status, output, errors) = run_inside(self.repository.location, "--help")
		self.assertEqual(status, 0)
		for option in ("--gitlab", "--gitlab-dump=FILE", "--llm=BACKEND", "claude-code", llm.DEFAULT_LOCAL_URL):
			self.assertIn(option, output)
