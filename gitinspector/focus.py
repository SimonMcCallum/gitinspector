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

"""Where each author's work went: scripts, shaders, scenes, assets, documents or generated files.

A game project is not only source. The scene files an engine writes when a level is laid out, the
textures and models that are dropped in, the .import files Godot regenerates on every open, all
land in the history as lines, and a line count that mixes them makes the person who committed the
asset pack look like the main programmer. This pass reads every file of every commit in the
interval, puts each file in a category by its extension and path, and keeps the categories apart
per author, so the report can say "scripts 70%, scenes 25%, and 40 asset files" instead of one
number."""

from __future__ import division
from __future__ import unicode_literals
import os
import subprocess
from . import filtering, git, interval

#The categories, in the order they are shown. The first four are what a person writes by hand or
#in an editor; assets are dropped in; generated files are written by the engine.
CATEGORIES = ["scripts", "shaders", "scenes", "docs", "data", "config", "assets", "generated", "other"]
AUTHORED = ["scripts", "shaders", "scenes", "docs", "data", "config"]

CATEGORY_TEXT = {"scripts": "scripts", "shaders": "shaders", "scenes": "scenes", "docs": "docs", "data": "data",
                 "config": "config", "assets": "assets", "generated": "generated", "other": "other"}

__extensions__ = {
	"scripts": ["gd", "cs", "py", "js", "ts", "tsx", "jsx", "cpp", "cc", "c", "h", "hh", "hpp", "java", "kt", "rs", "go",
	            "swift", "rb", "php", "lua", "dart", "groovy", "scala", "m", "mm"],
	"shaders": ["gdshader", "gdshaderinc", "glsl", "hlsl", "shader", "usf", "ush", "frag", "vert", "fsh", "vsh", "gsh",
	            "csh", "wgsl", "cginc", "compute", "metal"],
	"scenes": ["tscn", "tres", "godot", "unity", "prefab", "mat", "anim", "controller", "umap", "uasset", "theme",
	           "material", "escn", "scn", "res", "uproject", "physicsmaterial", "shadergraph", "asset"],
	"docs": ["md", "txt", "rst", "pdf", "docx", "doc", "odt", "html", "htm", "tex"],
	"data": ["json", "csv", "tsv", "yaml", "yml", "cfg", "ini", "toml", "xml", "plist", "properties", "po", "pot",
	         "translation", "dialogue"],
	"assets": ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "tga", "psd", "aseprite", "ase", "kra", "exr", "hdr",
	           "wav", "mp3", "ogg", "flac", "aiff", "mid", "glb", "gltf", "fbx", "obj", "blend", "dae", "stl", "ttf",
	           "otf", "woff", "woff2", "fnt", "mp4", "webm", "mov", "avi", "ico", "cur", "icns", "tilemap", "tileset"],
	"generated": ["import", "uid", "meta", "tmp", "csproj", "sln", "pyc", "lock", "DS_Store", "suo", "user"],
}

__by_extension__ = dict((extension.lower(), category) for (category, extensions) in __extensions__.items()
                        for extension in extensions)

#Folders the engines own; nothing a person wrote lives in them whatever the extension says.
__generated_folders__ = (".godot/", ".import/", "library/", "temp/", "obj/", "bin/", "intermediate/", "saved/",
                         "deriveddatacache/", "binaries/", "node_modules/", "__pycache__/", ".vs/", ".idea/", "build/")
__config_names__ = (".gitignore", ".gitattributes", ".gitlab-ci.yml", ".editorconfig", ".gitmodules", "dockerfile",
                    "makefile", "cmakelists.txt", "package.json", "requirements.txt", "pyproject.toml", "setup.py")

def categorize(path):
	"""The category of a file, judged by where it is first and by what it is second."""
	lower = path.replace("\\", "/").lower()
	name = lower.rsplit("/", 1)[-1]

	for folder in __generated_folders__:
		if lower.startswith(folder) or "/" + folder in lower:
			return "generated"
	if name in __config_names__:
		return "config"
	if name == "project.godot":
		return "scenes"

	extension = os.path.splitext(name)[1][1:]
	return __by_extension__.get(extension, "other")

class FocusEntry(object):
	def __init__(self):
		self.lines = dict((category, 0) for category in CATEGORIES)
		self.files = dict((category, 0) for category in CATEGORIES)
		self.commits = 0

	def __iadd__(self, other):
		for category in CATEGORIES:
			self.lines[category] += other.lines[category]
			self.files[category] += other.files[category]
		self.commits += other.commits
		return self

	def authored_lines(self):
		return sum(self.lines[category] for category in AUTHORED)

	def total_lines(self):
		return sum(self.lines.values())

	def total_files(self):
		return sum(self.files.values())

	def shares(self):
		"""Each category's share of the authored lines; assets and generated files stay out of
		the denominator, since their line counts say nothing about who wrote what."""
		authored = float(self.authored_lines())
		return dict((category, (100.0 * self.lines[category] / authored) if authored else 0.0) for category in AUTHORED)

	def label(self):
		"""A few words a grader can read at a glance: the authored categories that matter, then the
		number of asset files when there are any."""
		shares = self.shares()
		parts = ["{0} {1:.0f}%".format(CATEGORY_TEXT[category], shares[category])
		         for category in sorted(AUTHORED, key=lambda category: -shares[category]) if shares[category] >= 5.0]
		if not parts:
			parts = ["no authored lines"]
		if self.files["assets"]:
			parts.append("{0} asset file{1}".format(self.files["assets"], "" if self.files["assets"] == 1 else "s"))
		if self.files["generated"]:
			parts.append("{0} generated".format(self.files["generated"]))
		return ", ".join(parts)

class Focus(object):
	def __init__(self, repo=None, resolver=None):
		self.entries = {}
		self.total = FocusEntry()
		self.resolver = resolver
		self.__read__()

	def __iadd__(self, other):
		try:
			for (author, entry) in other.entries.items():
				self.entries.setdefault(author, FocusEntry())
				self.entries[author] += entry
			self.total += other.total
			return self
		except AttributeError:
			return other

	def __read__(self):
		separator = "\x1e"
		command = ["git", "log", "--no-merges", "--numstat", "--format=" + separator + "%H%x00%aN%x00%aE"]
		command += interval.get_rev_list_arguments()

		with open(os.devnull, "w") as devnull:
			process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=devnull)
			output = git.decode(process.communicate()[0])

		if process.returncode != 0:
			return

		for block in output.split(separator):
			lines = block.strip("\n").splitlines()
			if not lines:
				continue

			head = lines[0].split("\x00")
			if len(head) != 3:
				continue

			(sha, author, email) = (head[0], head[1].strip() or "No Author", head[2].strip())
			if filtering.set_filtered(author, "author") or filtering.set_filtered(email, "email") or \
			   filtering.set_filtered(sha, "revision") or filtering.set_filtered(sha, "message"):
				continue

			key = self.resolver(author, email) if self.resolver else author
			entry = self.entries.setdefault(key, FocusEntry())
			touched = False

			for line in lines[1:]:
				fields = line.split("\t")
				if len(fields) != 3:
					continue

				path = git.unquote(fields[2].strip())
				if filtering.set_filtered(path):
					continue

				category = categorize(path)
				changed = (int(fields[0]) + int(fields[1])) if fields[0].isdigit() and fields[1].isdigit() else 0
				entry.lines[category] += changed
				entry.files[category] += 1
				self.total.lines[category] += changed
				self.total.files[category] += 1
				touched = True

			if touched:
				entry.commits += 1
				self.total.commits += 1

	def get_entries(self):
		return self.entries

	def as_dict(self):
		return {
			"categories": CATEGORIES,
			"total": {"lines": dict(self.total.lines), "files": dict(self.total.files), "commits": self.total.commits},
			"authors": [{
				"name": author, "commits": entry.commits, "lines": dict(entry.lines), "files": dict(entry.files),
				"authored_lines": entry.authored_lines(),
				"shares": dict((category, round(share, 1)) for (category, share) in entry.shares().items()),
				"focus": entry.label(),
			} for (author, entry) in sorted(self.entries.items())],
		}
