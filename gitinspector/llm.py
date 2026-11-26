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

"""A written assessment of the repository, produced by a language model from the statistics.

The numbers in the rest of the report are the evidence; this section is a reading of them. The
model only ever sees the evidence pack built here (per-author changes, ownership, timeline, the
metric violations and, when fetched, the GitLab issues and milestones), never the source, so what
it writes can be checked line by line against the tables above it.

Three backends. "local" talks to any OpenAI-compatible chat server on the machine (Ollama, LM
Studio, llama.cpp), which keeps student data on the premises. "claude" uses the Anthropic SDK and
an API key or an `ant auth login` profile. "claude-code" drives the Claude Code command line
tool, which runs on a Claude subscription rather than API credit. All three must return the same
JSON document, so the section reads the same whichever wrote it."""

from __future__ import print_function
from __future__ import unicode_literals
import json
import os
import re
import subprocess
import sys

try:
	from urllib.request import Request, urlopen
	from urllib.error import HTTPError, URLError
except ImportError:
	from urllib2 import Request, urlopen, HTTPError, URLError

from . import optval, responsibilities, timeline

BACKENDS = ["none", "local", "claude", "claude-code"]
DEFAULT_BACKEND = BACKENDS[0]
DEFAULT_LOCAL_URL = "http://localhost:11434/v1"
DEFAULT_MODELS = {"local": "llama3.1", "claude": "claude-opus-5-5", "claude-code": None}
DEFAULT_MAX_TOKENS = 16000
DEFAULT_TIMEOUT = 600

#Caps on the evidence pack, so that a long-lived repository does not turn into a prompt the local
#models cannot hold. The tables in the report keep the full detail.
MAX_AUTHORS = 40
MAX_PERIODS = 60
MAX_FILES_PER_AUTHOR = 6
MAX_VIOLATIONS = 12
MAX_ISSUES_LISTED = 40

class InvalidBackendError(optval.InvalidOptionArgument):
	pass

class LLMError(Exception):
	def __init__(self, msg):
		super(LLMError, self).__init__(msg)
		self.msg = msg

class Settings(object):
	def __init__(self):
		self.backend = DEFAULT_BACKEND
		self.model = None
		self.url = None
		self.prompt_file = None
		self.max_tokens = DEFAULT_MAX_TOKENS
		self.timeout = DEFAULT_TIMEOUT

	def is_enabled(self):
		return self.backend != "none"

	def resolved_model(self):
		return self.model or DEFAULT_MODELS.get(self.backend)

	def resolved_url(self):
		return (self.url or DEFAULT_LOCAL_URL).rstrip("/")

def select(name):
	"""The backend named on the command line, or an error the option parser reports."""
	name = (name or "").strip().lower()

	if name not in BACKENDS:
		raise InvalidBackendError("the LLM backend must be one of {0}.".format(", ".join(BACKENDS)))

	return name

#The shape every backend has to answer in. It is sent to Claude as a structured output schema and
#described to the local models in the prompt; what comes back is normalised either way.
SCHEMA = {
	"type": "object",
	"properties": {
		"summary": {"type": "string", "description": "Three to six sentences on the repository as a whole."},
		"process": {"type": "string", "description": "How the team worked: cadence, planning, review, use of the tracker."},
		"members": {
			"type": "array",
			"items": {
				"type": "object",
				"properties": {
					"name": {"type": "string"},
					"role": {"type": "string", "description": "A few words: what this person's work mostly was."},
					"contribution": {"type": "string", "description": "What they did, in two or three sentences."},
					"evidence": {"type": "string", "description": "The numbers from the pack that support it."},
					"concerns": {"type": "string", "description": "What a grader should look at or ask about; empty if nothing."}
				},
				"required": ["name", "role", "contribution", "evidence", "concerns"],
				"additionalProperties": False
			}
		},
		"milestones": {"type": "string", "description": "Whether the plan held: milestones, due dates, issue completion. Empty when no tracker data was given."},
		"risks": {"type": "array", "items": {"type": "string"}, "description": "Things that may be wrong with the picture: unmatched authors, bulk commits, generated files."},
		"questions": {"type": "array", "items": {"type": "string"}, "description": "Questions to put to the team or to individuals."},
		"confidence": {"type": "string", "enum": ["low", "medium", "high"]}
	},
	"required": ["summary", "process", "members", "milestones", "risks", "questions", "confidence"],
	"additionalProperties": False
}

SYSTEM_PROMPT = """You are assisting a university lecturer who grades student software projects from their git repositories.
You are given an evidence pack: statistics gitinspector computed from the repository (changes per author, line ownership,
a timeline of activity, code metric violations) and, when available, the GitLab issues and milestones joined to the commits.
You never see the source code or the students, only these numbers.

Rules:
- Every claim must follow from the evidence pack. Quote the numbers you rely on. Where the evidence is thin or ambiguous,
  say so instead of guessing.
- Describe; do not award marks or grades. The lecturer decides those.
- Treat line counts with suspicion: generated files, asset dumps and reformatting commits inflate them. Flag anything
  that looks like it, and prefer commit counts, active periods and ownership when they disagree with raw churn.
- A git author that matched no GitLab user, or a user with no commits, is worth a question, not a verdict.
- When contribution_focus is given, say where each person's work went (scripts, shaders, scenes the editor wrote,
  docs, assets) and weigh scripts and shaders above scene and asset churn when judging programming effort.
- When code_quality is given, describe each author's code level from the sub-scores (clarity, structure, robustness,
  hygiene) and the good/fair/poor ratio, and report the polished share and the flagged chunks as "looks generated or
  AI-assisted". That is allowed in this course and is not misconduct; the point is the ratio of polished to rough code
  per person and what to ask them about, never an accusation.
- Write in plain, neutral British English. No headings inside the fields, no bullet characters inside strings.
- Answer with a single JSON object that matches the schema you were given, and nothing else."""

def __compact__(value):
	return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def build_evidence(repos, changes, blame, metrics=None, gitlab_data=None, useweeks=False, focus_data=None,
                   quality_data=None):
	"""The dict the model is shown. Everything in it comes from objects the report already holds."""
	authorinfo = changes.get_authorinfo_list()
	total_changes = float(sum(info.insertions + info.deletions for info in authorinfo.values())) or 1.0
	summed = blame.get_summed_blames() if blame is not None and hasattr(blame, "blames") else {}
	total_lines = float(sum(entry.lines for entry in summed.values())) or 1.0
	names = sorted(authorinfo, key=lambda name: -(authorinfo[name].insertions + authorinfo[name].deletions))

	authors = []
	for name in names[:MAX_AUTHORS]:
		info = authorinfo[name]
		entry = {
			"name": name,
			"email": changes.get_latest_email_by_author(name),
			"commits": info.commits,
			"insertions": info.insertions,
			"deletions": info.deletions,
			"share_of_changes_pct": round(100.0 * (info.insertions + info.deletions) / total_changes, 1),
		}
		blamed = summed.get(name)
		if blamed is not None:
			entry["owned_lines_now"] = blamed.lines
			entry["share_of_owned_lines_pct"] = round(100.0 * blamed.lines / total_lines, 1)
			entry["comment_lines_pct"] = round(100.0 * blamed.comments / blamed.lines, 1) if blamed.lines else 0.0
			files = sorted(responsibilities.Responsibilities.get(blame, name), key=lambda item: -item[1])
			entry["most_responsible_for"] = [{"file": path, "lines": lines} for (path, lines) in files[:MAX_FILES_PER_AUTHOR]]
		authors.append(entry)

	periods = []
	if changes.get_commits():
		data = timeline.TimelineData(changes, useweeks)
		all_periods = data.get_periods()
		step = max(1, (len(all_periods) + MAX_PERIODS - 1) // MAX_PERIODS)
		for period in all_periods[::step]:
			(insertions, deletions, total) = data.get_total_changes_in_period(period)
			by_author = {}
			for (name, _unused_email) in data.get_authors():
				if data.is_author_in_period(period, name):
					(ins, dels) = data.get_author_changes_in_period(name, period)
					if ins or dels:
						by_author[name] = [ins, dels]
			periods.append({"period": period, "insertions": insertions, "deletions": deletions,
			                "by_author": by_author})

	#Every shader file with who owns how many of its lines, so that a question such as "did the
	#student write the specular" can be answered from the pack rather than from the top files only.
	shader_files = {}
	for ((author, filename), entry) in getattr(blame, "blames", {}).items():
		if filename.rsplit(".", 1)[-1].lower() in ("gdshader", "gdshaderinc", "glsl", "hlsl", "shader", "usf", "ush",
		                                            "fsh", "vsh", "gsh", "csh", "frag", "vert", "wgsl"):
			shader_files.setdefault(filename, {})[author] = entry.lines

	violations = {}
	if metrics is not None:
		for (label, table) in (("estimated_lines_of_code", getattr(metrics, "eloc", {})),
		                       ("cyclomatic_complexity", getattr(metrics, "cyclomatic_complexity", {})),
		                       ("cyclomatic_complexity_density", getattr(metrics, "cyclomatic_complexity_density", {})),
		                       ("cognitive_complexity", getattr(metrics, "cognitive_complexity", {}))):
			if table:
				worst = sorted(table.items(), key=lambda item: -item[1])[:MAX_VIOLATIONS]
				violations[label] = [{"file": path, "value": value} for (path, value) in worst]

	evidence = {
		"note": ("commits_analyzed, authors and timeline count only the commits that touched the selected file types "
		         "(source files), which is why they can be fewer than gitlab.totals.commits, which counts every "
		         "non-merge commit in the interval whatever it touched."),
		"repositories": [{"name": repo.name, "branch": repo.branch} for repo in repos],
		"first_commit": changes.first_commit_date.isoformat() if changes.get_commits() else None,
		"last_commit": changes.last_commit_date.isoformat() if changes.get_commits() else None,
		"commits_analyzed": len(changes.get_commits()),
		"period_length": "week" if useweeks else "month",
		"authors": authors,
		"shader_files_owned_lines": shader_files,
		"timeline": periods,
		"metric_violations": violations,
	}

	if focus_data is not None:
		evidence["contribution_focus"] = focus_data.as_dict()

	if quality_data is not None:
		quality = quality_data.as_dict()
		quality["flagged_chunks"] = quality["flagged_chunks"][:MAX_VIOLATIONS]
		evidence["code_quality"] = quality

	if gitlab_data is not None:
		summary = gitlab_data.as_dict()
		summary["issues_sample"] = [{
			"iid": issue.iid, "title": issue.title, "state": issue.state, "author": issue.author,
			"assignees": issue.assignees, "milestone": issue.milestone, "labels": issue.labels,
			"weight": issue.weight, "committers": dict(issue.committers),
		} for issue in gitlab_data.issues[:MAX_ISSUES_LISTED]]
		evidence["gitlab"] = summary

	return evidence

def build_user_prompt(evidence, extra=None):
	text = ("Evidence pack, as JSON:\n" + __compact__(evidence) + "\n\n"
	        "Write the assessment as a JSON object with exactly these fields: summary (string), process (string), "
	        "members (array of objects with name, role, contribution, evidence, concerns, one per author in the pack; "
	        "contribution names where the work went and, when code_quality is present, the code level and the share "
	        "that looks AI-assisted), "
	        "milestones (string; empty if the pack has no gitlab section), risks (array of strings), "
	        "questions (array of strings), confidence (\"low\", \"medium\" or \"high\").")

	if extra:
		text += "\n\nThe lecturer adds these instructions, which take precedence over the general ones:\n" + extra

	return text

def read_prompt_file(path):
	if not path:
		return None
	try:
		with open(path, "rb") as handle:
			return handle.read().decode("utf-8", "replace").strip()
	except (IOError, OSError) as error:
		raise LLMError("the prompt file '{0}' could not be read: {1}".format(path, error))

def parse_json_object(text):
	"""The object in a model's answer, tolerating a code fence or a sentence around it."""
	text = (text or "").strip()

	try:
		return json.loads(text)
	except ValueError:
		pass

	fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
	if fenced:
		try:
			return json.loads(fenced.group(1))
		except ValueError:
			pass

	(first, last) = (text.find("{"), text.rfind("}"))
	if 0 <= first < last:
		try:
			return json.loads(text[first:last + 1])
		except ValueError:
			pass

	raise LLMError("the model did not answer with a JSON object.")

def __text__(value):
	if value is None:
		return ""
	if isinstance(value, (list, tuple)):
		return " ".join(__text__(item) for item in value)
	if isinstance(value, dict):
		return "; ".join("{0}: {1}".format(key, __text__(item)) for (key, item) in value.items())
	return "{0}".format(value).strip()

def __list__(value):
	if isinstance(value, (list, tuple)):
		return [__text__(item) for item in value if __text__(item)]
	return [__text__(value)] if __text__(value) else []

def normalize(data):
	"""Whatever came back, in the shape the output modules expect, with empty strings where the
	model left a field out."""
	if not isinstance(data, dict):
		raise LLMError("the model did not answer with a JSON object.")

	members = []
	for entry in data.get("members") or []:
		if isinstance(entry, dict):
			members.append({"name": __text__(entry.get("name")), "role": __text__(entry.get("role")),
			                "contribution": __text__(entry.get("contribution")),
			                "evidence": __text__(entry.get("evidence")), "concerns": __text__(entry.get("concerns"))})
		elif __text__(entry):
			members.append({"name": __text__(entry), "role": "", "contribution": "", "evidence": "", "concerns": ""})

	confidence = __text__(data.get("confidence")).lower()
	if confidence not in ("low", "medium", "high"):
		confidence = "low"

	return {
		"summary": __text__(data.get("summary")),
		"process": __text__(data.get("process")),
		"members": members,
		"milestones": __text__(data.get("milestones")),
		"risks": __list__(data.get("risks")),
		"questions": __list__(data.get("questions")),
		"confidence": confidence,
	}

#--- backends ----------------------------------------------------------------------------------

class LocalBackend(object):
	"""Any server that speaks the OpenAI chat completions API: Ollama on port 11434, LM Studio on
	1234, a llama.cpp server. The JSON mode is requested; servers that lack it answer in prose and
	the parser digs the object out of that."""

	def __init__(self, settings):
		self.settings = settings

	def complete(self, system, user):
		url = self.settings.resolved_url() + "/chat/completions"
		body = {
			"model": self.settings.resolved_model(),
			"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
			"temperature": 0.2,
			"stream": False,
			"response_format": {"type": "json_object"},
		}
		request = Request(url, data=json.dumps(body).encode("utf-8"))
		request.add_header("Content-Type", "application/json")
		key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
		if key:
			request.add_header("Authorization", "Bearer " + key)

		try:
			response = urlopen(request, timeout=self.settings.timeout)
			answer = json.loads(response.read().decode("utf-8", "replace"))
		except HTTPError as error:
			detail = error.read().decode("utf-8", "replace")[:300] if hasattr(error, "read") else ""
			raise LLMError("the local model server at {0} answered {1}: {2}".format(url, error.code, detail.strip()))
		except URLError as error:
			raise LLMError("no model server at {0} ({1}); start Ollama or LM Studio, or pass --llm-url.".format(
			               url, error.reason))
		except ValueError:
			raise LLMError("the local model server at {0} did not answer with JSON.".format(url))

		try:
			content = answer["choices"][0]["message"]["content"]
		except (KeyError, IndexError, TypeError):
			raise LLMError("the local model server answered without a message: {0}".format(__compact__(answer)[:300]))

		return parse_json_object(content)

class ClaudeBackend(object):
	"""Claude over the Anthropic SDK. Credentials come from ANTHROPIC_API_KEY or from a profile
	made with `ant auth login`; the SDK finds both on its own. The answer is constrained to the
	schema server-side, so it never needs repairing."""

	def __init__(self, settings):
		self.settings = settings

	def complete(self, system, user):
		try:
			import anthropic
		except ImportError:
			raise LLMError("the anthropic package is not installed; run `pip install anthropic` or use --llm=claude-code.")

		model = self.settings.resolved_model()
		messages = [{"role": "user", "content": user}]
		output_config = {"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}}

		try:
			client = anthropic.Anthropic(timeout=float(self.settings.timeout))
			try:
				#The server-side fallback re-runs a declined request on another model inside the same call.
				with client.beta.messages.stream(model=model, max_tokens=self.settings.max_tokens, system=system,
				                                 messages=messages, output_config=output_config,
				                                 betas=["server-side-fallback-2026-07-01"],
				                                 fallbacks="default") as stream:
					message = stream.get_final_message()
			except anthropic.BadRequestError as error:
				#An older gateway or model that knows neither the beta nor the fallback: ask plainly.
				if "fallback" not in str(error).lower() and "beta" not in str(error).lower():
					raise
				with client.messages.stream(model=model, max_tokens=self.settings.max_tokens, system=system,
				                            messages=messages, output_config=output_config) as stream:
					message = stream.get_final_message()
		except anthropic.AuthenticationError:
			raise LLMError("no Claude credentials were accepted; set ANTHROPIC_API_KEY, run `ant auth login`, "
			               "or use --llm=claude-code with a Claude subscription.")
		except anthropic.NotFoundError:
			raise LLMError("the Claude model '{0}' was not found; pass --llm-model.".format(model))
		except anthropic.RateLimitError:
			raise LLMError("Claude rate-limited the request; try again shortly.")
		except anthropic.APIStatusError as error:
			raise LLMError("Claude answered {0}: {1}".format(error.status_code, getattr(error, "message", error)))
		except anthropic.APIConnectionError as error:
			raise LLMError("Claude could not be reached: {0}".format(error))
		except anthropic.AnthropicError as error:
			raise LLMError("Claude could not be asked: {0}".format(error))
		except TypeError as error:
			#The SDK reports a request it cannot sign as a TypeError rather than as one of its own errors.
			if "authentication" not in str(error).lower():
				raise
			raise LLMError("no Claude credentials were found; set ANTHROPIC_API_KEY, run `ant auth login`, "
			               "or use --llm=claude-code with a Claude subscription.")

		if message.stop_reason == "refusal":
			details = getattr(message, "stop_details", None)
			raise LLMError("Claude declined to write the assessment{0}.".format(
			               " (" + __text__(getattr(details, "explanation", "")) + ")" if details else ""))
		if message.stop_reason == "max_tokens":
			raise LLMError("Claude ran out of output tokens; raise --llm-max-tokens.")

		text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
		return parse_json_object(text)

class ClaudeCodeBackend(object):
	"""Claude through the `claude` command line tool in its non-interactive mode, which runs on
	the subscription the tool is logged in with. The evidence goes in on standard input, so the
	size of the pack is not limited by the command line."""

	def __init__(self, settings):
		self.settings = settings

	@staticmethod
	def executable():
		try:
			from shutil import which
		except ImportError:
			return "claude"
		return which("claude") or which("claude.cmd") or "claude"

	def complete(self, system, user):
		command = [self.executable(), "-p", "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
		           "--system-prompt", system, "--bare", "--max-turns", "1", "--no-session-persistence"]
		model = self.settings.resolved_model()
		if model:
			command += ["--model", model]

		try:
			process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
			(output, errors) = process.communicate(user.encode("utf-8"))
		except OSError as error:
			raise LLMError("the claude command could not be started ({0}); install Claude Code and log in.".format(error))

		output = output.decode("utf-8", "replace").strip()
		if process.returncode != 0 and not output:
			raise LLMError("claude exited with {0}: {1}".format(process.returncode,
			               errors.decode("utf-8", "replace").strip()[:300]))

		try:
			answer = json.loads(output)
		except ValueError:
			raise LLMError("claude did not answer with JSON: {0}".format(output[:300]))

		if isinstance(answer, list):
			answer = next((entry for entry in answer if isinstance(entry, dict) and entry.get("type") == "result"), {})

		if answer.get("is_error"):
			raise LLMError("claude reported an error: {0}".format(__text__(answer.get("result"))[:300]))

		structured = answer.get("structured_output")
		if isinstance(structured, dict):
			return structured

		return parse_json_object(__text__(answer.get("result")))

def backend_for(settings):
	if settings.backend == "local":
		return LocalBackend(settings)
	if settings.backend == "claude":
		return ClaudeBackend(settings)
	if settings.backend == "claude-code":
		return ClaudeCodeBackend(settings)

	raise InvalidBackendError("the LLM backend must be one of {0}.".format(", ".join(BACKENDS)))

def assess(settings, evidence):
	"""The normalised assessment, or an LLMError that names what went wrong."""
	backend = backend_for(settings)
	extra = read_prompt_file(settings.prompt_file)
	answer = backend.complete(SYSTEM_PROMPT, build_user_prompt(evidence, extra))
	result = normalize(answer)

	#An empty object parses and normalises without complaint; it is still no assessment.
	if not result["summary"] and not result["members"] and not result["process"]:
		raise LLMError("the model returned an empty assessment; run again, or check the backend's usage limits.")

	return result

def describe(settings):
	model = settings.resolved_model()
	if settings.backend == "local":
		return "{0} at {1}".format(model, settings.resolved_url())
	if settings.backend == "claude-code":
		return (model or "the default model") + " via Claude Code"
	return model or settings.backend
