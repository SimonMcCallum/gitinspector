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

"""The issues and the milestones of a GitLab project, joined to the commit history.

The commits say what was written and by whom; the issue tracker says what was planned, who was
asked to do it and whether it got done. Reading the two together answers the questions a grader
of a student project asks: does the person assigned to an issue end up committing against it, is
the work tied to the plan at all, and did the milestones hold.

The data comes from the GitLab REST API (v4) over the standard library, or from a JSON dump of the
same API objects when the report is generated offline. The project is inferred from the origin
remote of the repository unless given explicitly."""

from __future__ import print_function
from __future__ import unicode_literals
import datetime
import json
import os
import re
import subprocess

try:
	from urllib.request import Request, urlopen
	from urllib.parse import quote, urlencode, urlparse
	from urllib.error import HTTPError, URLError
except ImportError:
	from urllib2 import Request, urlopen, HTTPError, URLError
	from urllib import quote, urlencode
	from urlparse import urlparse

from . import git, interval

#"#12" anywhere in a message, but not "#12" inside a word or a colour code such as "#123abc"... the
#trailing boundary keeps "#12" from matching "#123".
ISSUE_REFERENCE = re.compile(r"(?<![\w#])#(\d+)\b")
#GitLab's own closing pattern, simplified: "Closes #12", "fixes #3", "Resolved #4".
CLOSING_REFERENCE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[^#\n]{0,20}#(\d+)", re.I)

PER_PAGE = 100
TIMEOUT = 60

class GitLabError(Exception):
	def __init__(self, msg):
		super(GitLabError, self).__init__(msg)
		self.msg = msg

def __user__(data):
	data = data or {}
	return (data.get("username") or "", data.get("name") or "")

def __date__(value):
	return (value or "")[0:10]

class Issue(object):
	def __init__(self, data):
		self.iid = int(data.get("iid") or 0)
		self.title = data.get("title") or ""
		self.state = data.get("state") or ""
		(self.author, self.author_name) = __user__(data.get("author"))
		self.assignees = [__user__(entry)[0] for entry in (data.get("assignees") or [])]
		self.labels = list(data.get("labels") or [])
		self.milestone = (data.get("milestone") or {}).get("title") or ""
		self.weight = data.get("weight")
		self.created = __date__(data.get("created_at"))
		self.closed = __date__(data.get("closed_at"))
		(self.closed_by, _unused) = __user__(data.get("closed_by"))
		self.due = __date__(data.get("due_date"))
		self.web_url = data.get("web_url") or ""
		#Filled in by the join: git author -> number of commits that reference this issue.
		self.committers = {}
		self.closing_committers = {}

	def is_closed(self):
		return self.state == "closed"

class Milestone(object):
	def __init__(self, data):
		self.iid = int(data.get("iid") or 0)
		self.title = data.get("title") or ""
		self.state = data.get("state") or ""
		self.due = __date__(data.get("due_date"))
		self.start = __date__(data.get("start_date"))
		self.created = __date__(data.get("created_at"))
		self.web_url = data.get("web_url") or ""
		self.issues = []

	def closed_issues(self):
		return [issue for issue in self.issues if issue.is_closed()]

	def open_issues(self):
		return [issue for issue in self.issues if not issue.is_closed()]

	def is_overdue(self, today=None):
		today = today or datetime.date.today().isoformat()
		return bool(self.due) and self.due < today and bool(self.open_issues())

	def linked_commits(self):
		return sum(sum(issue.committers.values()) for issue in self.issues)

	def completion(self):
		return 0.0 if not self.issues else 100.0 * len(self.closed_issues()) / len(self.issues)

class UserStats(object):
	def __init__(self, username, name):
		self.username = username
		self.name = name
		self.git_authors = set()
		self.commits = 0
		self.commits_linked = 0
		self.commits_closing = 0
		self.issues_referenced = set()
		self.issues_created = 0
		self.issues_assigned = 0
		self.issues_closed = 0
		self.assigned_done_self = 0
		self.assigned_done_other = 0
		self.assigned_untouched = 0

def __normalize__(string):
	return re.sub(r"[^a-z0-9 ]+", " ", (string or "").lower()).strip()

def match_user(author, email, users, aliases=None):
	"""The GitLab username a git author most likely is, or None.

	Students commit with whatever name and address their client was set up with, so the match goes
	from the surest signal to the loosest: an alias the grader wrote down, the local part of the
	address is the username, the name is the name, the names share their tokens, or the username
	is spelled inside the name."""
	local = (email or "").split("@")[0].lower()
	name = __normalize__(author)

	for key in ((email or "").strip().lower(), (author or "").strip().lower()):
		if key and aliases and key in aliases:
			return aliases[key]

	for user in users:
		if local and local == user.username.lower():
			return user.username

	for user in users:
		if name and name == __normalize__(user.name):
			return user.username

	for user in users:
		(theirs, ours) = (set(__normalize__(user.name).split()), set(name.split()))
		if theirs and ours and (theirs <= ours or ours <= theirs):
			return user.username

	for user in users:
		username = user.username.lower()
		if len(username) > 4 and (username in name.replace(" ", "") or username in local):
			return user.username

	return None

def make_resolver(users=None, aliases=None):
	"""A function from a git (author, email) to the name a report row should carry: the GitLab
	username when the author matches one, else the author as git has it. The focus and the code
	quality sections use it so that a student who committed under four names gets one row."""
	users = list(users or [])
	aliases = dict(aliases or {})
	cache = {}

	def resolve(author, email):
		key = (author or "", email or "")
		if key not in cache:
			cache[key] = match_user(author, email, users, aliases) or author
		return cache[key]

	return resolve

def load_aliases(path):
	"""A JSON file mapping commit addresses (or author names) to GitLab usernames, either as a flat
	object or under an "aliases" key, which is how a grading tool tends to keep it next to its
	notes. Keys are compared case-insensitively."""
	try:
		with open(path, "rb") as handle:
			data = json.loads(handle.read().decode("utf-8", "replace"))
	except (IOError, OSError, ValueError) as error:
		raise GitLabError("the aliases file '{0}' could not be read: {1}".format(path, error))

	if isinstance(data, dict) and isinstance(data.get("aliases"), dict):
		data = data["aliases"]
	if not isinstance(data, dict):
		raise GitLabError("the aliases file '{0}' does not hold a JSON object.".format(path))

	return dict(("{0}".format(key).strip().lower(), "{0}".format(value).strip())
	            for (key, value) in data.items() if value and not "{0}".format(key).startswith("_"))

def project_from_remote(url):
	"""(api base, project path) from a clone URL, or None when it is not a GitLab-looking URL.

	Both the "git@host:group/project.git" and the "https://host/group/project.git" forms are
	common, and nothing in either says that the host is a GitLab, which is why the result is only
	a guess that the API call confirms."""
	url = (url or "").strip()

	if not url:
		return None

	match = re.match(r"^(?:ssh://)?(?:[\w.-]+@)?([\w.-]+)(?::\d+)?[:/](.+?)(?:\.git)?/?$", url)
	if url.startswith("http://") or url.startswith("https://"):
		parsed = urlparse(url)
		host = parsed.hostname or ""
		path = parsed.path.strip("/")
		if path.endswith(".git"):
			path = path[:-4]
		scheme = parsed.scheme
	elif match:
		(host, path) = (match.group(1), match.group(2).strip("/"))
		scheme = "https"
	else:
		return None

	if not host or "/" not in path:
		return None

	return (scheme + "://" + host + "/api/v4", path)

def __git_remote__(location):
	with open(os.devnull, "w") as devnull:
		process = subprocess.Popen(["git", "remote", "get-url", "origin"], cwd=location, stdout=subprocess.PIPE,
		                           stderr=devnull)
		return git.decode(process.communicate()[0]).strip()

class GitLabData(object):
	def __init__(self):
		self.source = ""
		self.project_name = ""
		self.project_url = ""
		self.issues = []
		self.milestones = []
		self.users = []
		self.commits = []
		self.unmatched = {}
		self.stats = {}
		self.aliases = {}

	#--- loading ------------------------------------------------------------------------------

	@staticmethod
	def from_dump(path):
		"""A JSON file holding the API objects: {"project": {...}, "issues": [...], "milestones": [...],
		"members": [...]}. The members and the group members are optional and only improve the
		matching of git authors."""
		try:
			with open(path, "rb") as handle:
				data = json.loads(handle.read().decode("utf-8", "replace"))
		except (IOError, OSError, ValueError) as error:
			raise GitLabError("the GitLab dump '{0}' could not be read: {1}".format(path, error))

		if not isinstance(data, dict):
			raise GitLabError("the GitLab dump '{0}' does not hold a JSON object.".format(path))

		result = GitLabData()
		result.source = "dump:" + path
		result.__load__(data.get("project") or {}, data.get("issues") or [], data.get("milestones") or [],
		                (data.get("members") or []) + (data.get("group_members") or []))
		return result

	@staticmethod
	def from_api(location, project_url=None, token=None):
		"""Everything the report needs, straight from the API of the GitLab that hosts the repository.
		The token is needed on a private project and on every ECS-style GitLab that hides the API."""
		if project_url:
			target = project_from_remote(project_url)
			if target is None:
				raise GitLabError("'{0}' does not look like a GitLab project URL.".format(project_url))
		else:
			remote = __git_remote__(location)
			target = project_from_remote(remote)
			if target is None:
				raise GitLabError("no GitLab project could be inferred from the origin remote '{0}'; "
				                  "use --gitlab-url.".format(remote))

		(api, path) = target
		client = __Client__(api, token)
		project = client.get("/projects/" + quote(path, safe=""))

		if project is None:
			raise GitLabError("the GitLab project '{0}' was not found on {1}, or the token has no access to it.".format(
			                  path, api))

		identifier = "/projects/{0}".format(project["id"])
		result = GitLabData()
		result.source = api
		result.__load__(project,
		                client.get_all(identifier + "/issues", state="all", scope="all"),
		                client.get_all(identifier + "/milestones"),
		                client.get_all(identifier + "/members/all"))
		return result

	def __load__(self, project, issues, milestones, members):
		self.project_name = project.get("path_with_namespace") or project.get("name") or ""
		self.project_url = project.get("web_url") or ""
		self.issues = sorted([Issue(entry) for entry in issues], key=lambda issue: issue.iid)
		self.milestones = sorted([Milestone(entry) for entry in milestones], key=lambda milestone: (milestone.due or "9999", milestone.iid))

		by_title = dict((milestone.title, milestone) for milestone in self.milestones)
		for issue in self.issues:
			if issue.milestone in by_title:
				by_title[issue.milestone].issues.append(issue)

		seen = {}
		for entry in members:
			(username, name) = __user__(entry)
			if username and entry.get("state") != "blocked":
				seen.setdefault(username.lower(), UserStats(username, name))
		for issue in self.issues:
			for (username, name) in [(issue.author, issue.author_name)] + [(entry, "") for entry in issue.assignees]:
				if username and username.lower() not in seen:
					seen[username.lower()] = UserStats(username, name)
			if issue.closed_by and issue.closed_by.lower() not in seen:
				seen[issue.closed_by.lower()] = UserStats(issue.closed_by, "")

		self.stats = dict((entry.username, entry) for entry in seen.values())
		self.users = sorted(self.stats.values(), key=lambda entry: entry.username.lower())

	#--- joining with the history ---------------------------------------------------------------

	def join(self, location=None):
		"""Read the commits the report covers and tie them to the issues they mention."""
		command = ["git", "log", "--no-merges", "--format=%H%x00%aN%x00%aE%x00%ad%x00%s", "--date=short"]
		command += interval.get_rev_list_arguments()

		with open(os.devnull, "w") as devnull:
			process = subprocess.Popen(command, cwd=location, stdout=subprocess.PIPE, stderr=devnull)
			output = git.decode(process.communicate()[0])

		self.commits = []
		for line in output.splitlines():
			fields = line.split("\x00")
			if len(fields) == 5:
				self.commits.append({"sha": fields[0], "author": fields[1].strip(), "email": fields[2].strip(),
				                     "date": fields[3].strip(), "subject": fields[4].strip()})

		self.__link__()
		return self

	def __link__(self):
		issues = dict((issue.iid, issue) for issue in self.issues)
		#An alias may name a user the dump never listed, such as a member who has since left.
		for username in set(self.aliases.values()):
			if username not in self.stats:
				self.stats[username] = UserStats(username, "")
		self.users = sorted(self.stats.values(), key=lambda entry: entry.username.lower())

		for entry in self.stats.values():
			entry.git_authors = set()
			(entry.commits, entry.commits_linked, entry.commits_closing) = (0, 0, 0)
			entry.issues_referenced = set()
		self.unmatched = {}
		authors = {}

		for commit in self.commits:
			key = (commit["author"], commit["email"])
			if key not in authors:
				authors[key] = match_user(commit["author"], commit["email"], self.users, self.aliases)
			username = authors[key]
			references = set(int(number) for number in ISSUE_REFERENCE.findall(commit["subject"]))
			closing = set(int(number) for number in CLOSING_REFERENCE.findall(commit["subject"]))
			who = username or commit["author"]

			for iid in references:
				if iid in issues:
					issues[iid].committers[who] = issues[iid].committers.get(who, 0) + 1
			for iid in closing:
				if iid in issues:
					issues[iid].closing_committers[who] = issues[iid].closing_committers.get(who, 0) + 1

			if username is None:
				self.unmatched[commit["author"]] = self.unmatched.get(commit["author"], 0) + 1
				continue

			entry = self.stats[username]
			entry.git_authors.add(commit["author"])
			entry.commits += 1
			if references & set(issues):
				entry.commits_linked += 1
				entry.issues_referenced |= (references & set(issues))
			if closing & set(issues):
				entry.commits_closing += 1

		for entry in self.stats.values():
			(entry.issues_created, entry.issues_assigned, entry.issues_closed) = (0, 0, 0)
			(entry.assigned_done_self, entry.assigned_done_other, entry.assigned_untouched) = (0, 0, 0)

		for issue in self.issues:
			if issue.author in self.stats:
				self.stats[issue.author].issues_created += 1
			if issue.closed_by in self.stats:
				self.stats[issue.closed_by].issues_closed += 1
			for assignee in issue.assignees:
				if assignee not in self.stats:
					continue
				entry = self.stats[assignee]
				entry.issues_assigned += 1
				if issue.committers.get(assignee):
					entry.assigned_done_self += 1
				elif issue.committers:
					entry.assigned_done_other += 1
				else:
					entry.assigned_untouched += 1

	#--- summaries ------------------------------------------------------------------------------

	@staticmethod
	def __is_active__(entry):
		return bool(entry.commits or entry.issues_created or entry.issues_assigned or entry.issues_closed)

	def active_users(self):
		"""The members who show up somewhere; the rest are staff, service accounts and the odd
		student who never did anything, which is a fact worth one line rather than a row each."""
		return [entry for entry in self.users if self.__is_active__(entry)]

	def inactive_users(self):
		return [entry for entry in self.users if not self.__is_active__(entry)]

	def totals(self):
		linked = sum(1 for commit in self.commits if set(int(n) for n in ISSUE_REFERENCE.findall(commit["subject"])) &
		             set(issue.iid for issue in self.issues))
		referenced = set()
		for issue in self.issues:
			if issue.committers:
				referenced.add(issue.iid)

		return {
			"issues": len(self.issues),
			"open": sum(1 for issue in self.issues if not issue.is_closed()),
			"closed": sum(1 for issue in self.issues if issue.is_closed()),
			"unassigned": sum(1 for issue in self.issues if not issue.assignees),
			"without_milestone": sum(1 for issue in self.issues if not issue.milestone),
			"weighted": sum(1 for issue in self.issues if issue.weight),
			"labelled": sum(1 for issue in self.issues if issue.labels),
			"referenced_by_commits": len(referenced),
			"commits": len(self.commits),
			"commits_linked": linked,
			"milestones": len(self.milestones),
			"milestones_overdue": sum(1 for milestone in self.milestones if milestone.is_overdue()),
		}

	def misassigned(self):
		"""Issues where somebody other than the assignee did the committing."""
		return [issue for issue in self.issues
		        if issue.assignees and issue.committers and not set(issue.assignees) & set(issue.committers)]

	def as_dict(self):
		totals = self.totals()
		return {
			"project": self.project_name,
			"url": self.project_url,
			"totals": totals,
			"users": [{
				"username": entry.username, "name": entry.name, "git_authors": sorted(entry.git_authors),
				"commits": entry.commits, "commits_linked": entry.commits_linked,
				"commits_closing": entry.commits_closing, "issues_referenced": len(entry.issues_referenced),
				"issues_created": entry.issues_created, "issues_assigned": entry.issues_assigned,
				"issues_closed": entry.issues_closed, "assigned_done_self": entry.assigned_done_self,
				"assigned_done_other": entry.assigned_done_other, "assigned_untouched": entry.assigned_untouched,
			} for entry in self.active_users()],
			"inactive_members": [entry.username for entry in self.inactive_users()],
			"unmatched_authors": [{"author": author, "commits": count}
			                      for (author, count) in sorted(self.unmatched.items())],
			"milestones": [{
				"title": milestone.title, "state": milestone.state, "due": milestone.due, "start": milestone.start,
				"issues": len(milestone.issues), "closed": len(milestone.closed_issues()),
				"open": len(milestone.open_issues()), "completion": round(milestone.completion(), 1),
				"overdue": milestone.is_overdue(), "linked_commits": milestone.linked_commits(),
			} for milestone in self.milestones],
			"misassigned": [{
				"iid": issue.iid, "title": issue.title, "assignees": issue.assignees,
				"committers": dict(issue.committers),
			} for issue in self.misassigned()],
		}

class __Client__(object):
	def __init__(self, api, token):
		self.api = api
		self.token = token

	def __open__(self, path, params):
		url = self.api + path + ("?" + urlencode(params) if params else "")
		request = Request(url)
		request.add_header("Accept", "application/json")
		if self.token:
			request.add_header("PRIVATE-TOKEN", self.token)

		try:
			return urlopen(request, timeout=TIMEOUT)
		except HTTPError as error:
			if error.code in (401, 403):
				raise GitLabError("GitLab at {0} refused the request ({1}); a personal access token with the "
				                  "read_api scope is needed (--gitlab-token or $GITLAB_TOKEN).".format(self.api, error.code))
			if error.code == 404:
				return None
			raise GitLabError("GitLab at {0} answered {1} for {2}.".format(self.api, error.code, path))
		except URLError as error:
			raise GitLabError("GitLab at {0} could not be reached: {1}".format(self.api, error.reason))

	def get(self, path, **params):
		response = self.__open__(path, params)
		if response is None:
			return None
		return json.loads(response.read().decode("utf-8", "replace"))

	def get_all(self, path, **params):
		params = dict(params, per_page=PER_PAGE, page=1)
		result = []

		while True:
			response = self.__open__(path, params)
			if response is None:
				return result
			result.extend(json.loads(response.read().decode("utf-8", "replace")))
			following = response.info().get("X-Next-Page")
			if not following:
				return result
			params["page"] = int(following)

def resolve_token(explicit, config_token=None):
	return explicit or os.environ.get("GITLAB_TOKEN") or config_token or None
