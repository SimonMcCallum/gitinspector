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

"""The level of the code each author owns, read from the script lines git blame gives them.

Every line of every script file is attributed to the author who last wrote it, and the lines of
one author are then read the way a marker reads a submission: are the functions short and
documented, are the names consistent, are parameters and returns typed, are there debug prints,
magic numbers, commented-out code and copy-pasted blocks left behind, how deep does the nesting
go. Each of those becomes a number per author, the numbers become four sub-scores (clarity,
structure, robustness, hygiene) and the sub-scores one score with a level band.

The same measures are then taken per chunk, where a chunk is what one author added to one file in
one commit, so that the polish of each piece of work can be compared with the author's own usual.
A chunk that is far more polished than the rest of what the author wrote, and that carries the
marks of generated code (full typing, a doc comment on every function, sentence-case explanatory
comments, long descriptive names, nothing left over), is flagged as likely AI-assisted. That is a
heuristic and the report says so: it gives the ratio of good, fair and poor code and a list of
places worth asking about, not a verdict."""

from __future__ import division
from __future__ import unicode_literals
import re
import subprocess
import threading
from .changes import FileDiff
from .localization import N_
from . import comment, extensions, filtering, format, git, interval, terminal, workers

PROGRESS_TEXT = N_("Reading the script lines of each author (3 of 3): {0:.0f}%")

#Fewer code lines than this and a judgement on an author or a chunk would be guesswork.
MIN_AUTHOR_LINES = 30
MIN_CHUNK_LINES = 15
#Polish bands for a chunk: good at or above the first, poor below the second, fair between.
GOOD_POLISH = 70.0
POOR_POLISH = 50.0
LONG_LINE = 110
DEEP_NESTING = 5
DUPLICATE_MIN_LENGTH = 18
DUPLICATE_MIN_COUNT = 3

LEVELS = [(85, "strong"), (70, "competent"), (55, "developing"), (0, "beginning")]
LEVEL_TEXT = {"strong": N_("strong"), "competent": N_("competent"), "developing": N_("developing"),
              "beginning": N_("beginning"), "unknown": N_("too little code to judge")}

__lock__ = threading.Lock()

#--- language profiles --------------------------------------------------------------------------

class Profile(object):
	"""The regular expressions that find the structure of one language. A field left None means
	the measure does not apply to that language and stays out of its scores."""

	def __init__(self, func, params_typed=None, return_typed=None, var=None, var_typed=None, klass=None,
	             branch=None, debug=None, safety=None, doc=None, docstring_below=False, func_naming=None,
	             var_naming=None, const_naming=None, class_naming=None, indent_tabs=False, idiom=None):
		self.func = func
		self.params_typed = params_typed
		self.return_typed = return_typed
		self.var = var
		self.var_typed = var_typed
		self.klass = klass
		self.branch = branch
		self.debug = debug
		self.safety = safety
		self.doc = doc
		self.docstring_below = docstring_below
		self.func_naming = func_naming
		self.var_naming = var_naming
		self.const_naming = const_naming
		self.class_naming = class_naming
		self.indent_tabs = indent_tabs
		self.idiom = idiom

SNAKE = re.compile(r"^_{0,2}[a-z][a-z0-9_]*$")
CAMEL = re.compile(r"^_?[a-z][a-zA-Z0-9]*$")
PASCAL = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
UPPER = re.compile(r"^[A-Z][A-Z0-9_]*$")
LENIENT = re.compile(r"^_?[a-zA-Z][a-zA-Z0-9_]*$")

GD_TYPE = r"[\w\.\[\], ]+"
GDSCRIPT = Profile(
	func=re.compile(r"^\s*(?:static\s+)?func\s+(\w+)\s*\((.*?)\)\s*(->\s*" + GD_TYPE + r")?\s*:"),
	params_typed=re.compile(r"\w+\s*(?::\s*\w|:=)"),
	return_typed=re.compile(r"\)\s*->\s*\w"),
	var=re.compile(r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:static\s+)?(var|const)\s+(\w+)\s*(:\s*" + GD_TYPE + r")?\s*(:=|=)?"),
	var_typed=re.compile(r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:static\s+)?(?:var|const)\s+\w+\s*(?::\s*\w|:=)"),
	klass=re.compile(r"^\s*class(?:_name)?\s+(\w+)"),
	branch=re.compile(r"^\s*(?:if|elif|for|while|match)\b"),
	debug=re.compile(r"\bprint(?:_debug|_rich|err|raw|s|t)?\s*\("),
	safety=re.compile(r"\bassert\s*\(|\bis_instance_valid\s*\(|\bpush_error\s*\(|\bpush_warning\s*\(|[=!]=\s*null\b|"
	                  r"\bif\s+not\s+\w+|\bhas_node\s*\(|\bget_node_or_null\s*\(|\bis_empty\s*\(|\bclamp[fi]?\s*\("),
	doc=re.compile(r"^\s*##"),
	func_naming=SNAKE, var_naming=SNAKE, const_naming=UPPER, class_naming=PASCAL, indent_tabs=True,
	idiom=re.compile(r"^\s*signal\s+\w+|\.connect\s*\(|\.emit\s*\(|\bemit_signal\s*\(|^\s*@(?:export|onready)"))

PYTHON = Profile(
	func=re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\((.*?)\)\s*(->\s*[\w\.\[\], |]+)?\s*:"),
	params_typed=re.compile(r"\w+\s*:\s*\w"),
	return_typed=re.compile(r"\)\s*->\s*\w"),
	var=re.compile(r"^\s*(?!(?:if|elif|while|for|return|assert|yield|del|raise|print)\b)()([A-Za-z_]\w*)\s*(:\s*[\w\.\[\], |]+)?\s*(=)(?!=)"),
	var_typed=re.compile(r"^\s*[A-Za-z_]\w*\s*:\s*\w[\w\.\[\], |]*\s*="),
	klass=re.compile(r"^\s*class\s+(\w+)"),
	branch=re.compile(r"^\s*(?:if|elif|for|while|try|except|with)\b"),
	debug=re.compile(r"\bprint\s*\(|\bpdb\.set_trace\s*\(|\bbreakpoint\s*\("),
	safety=re.compile(r"\btry\b|\bexcept\b|\bassert\b|\bis\s+(?:not\s+)?None\b|\bisinstance\s*\(|\braise\b"),
	doc=re.compile(r"^\s*(?:\"\"\"|''')"), docstring_below=True,
	func_naming=SNAKE, var_naming=SNAKE, const_naming=UPPER, class_naming=PASCAL)

CS_MODIFIERS = r"(?:(?:public|private|protected|internal|static|override|virtual|abstract|async|sealed|new|partial|unsafe|extern)\s+)*"
CSHARP = Profile(
	func=re.compile(r"^\s*" + CS_MODIFIERS + r"(?!(?:if|for|foreach|while|switch|return|new|else|using|catch|lock|throw)\b)"
	                r"[\w<>\[\],\.?]+\s+(\w+)\s*\(([^;]*)\)\s*(?:where\s+.*)?(?:\{|=>|$)"),
	var=re.compile(r"^\s*" + CS_MODIFIERS + r"(?:readonly\s+)?(const\s+)?(?!(?:return|new|else|throw|using|yield|case|await)\b)"
	               r"[\w<>\[\],\.?]+\s+(\w+)\s*()(=|;)"),
	klass=re.compile(r"^\s*" + CS_MODIFIERS + r"(?:class|struct|interface|enum|record)\s+(\w+)"),
	branch=re.compile(r"^\s*(?:if|else|for|foreach|while|switch|case|catch|do)\b"),
	debug=re.compile(r"\bDebug\.Log\w*\s*\(|\bConsole\.Write\w*\s*\(|\bGD\.Print\w*\s*\(|\bprint\s*\("),
	safety=re.compile(r"\btry\b|\bcatch\b|\?\.|\?\?|[=!]=\s*null\b|\bis\s+(?:not\s+)?null\b|\bDebug\.Assert\b|\bTryGet\w*\("),
	doc=re.compile(r"^\s*///"),
	func_naming=PASCAL, var_naming=LENIENT, const_naming=LENIENT, class_naming=PASCAL,
	idiom=re.compile(r"\[Export\]|\[Signal\]|\bEmitSignal\s*\(|\[SerializeField\]|\bGetComponent<"))

JAVASCRIPT = Profile(
	func=re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)\s*\((.*?)\)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(?(.*?)\)?\s*=>|(\w+)\s*\((.*?)\)\s*(?::\s*[\w<>\[\]|, ]+)?\s*\{)"),
	params_typed=re.compile(r"\w+\s*\??:\s*\w"),
	return_typed=re.compile(r"\)\s*:\s*\w"),
	var=re.compile(r"^\s*(?:export\s+)?(const|let|var)\s+(\w+)\s*(:\s*[\w<>\[\]|, ]+)?\s*(=)?"),
	var_typed=re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+\w+\s*:\s*\w"),
	klass=re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+(\w+)"),
	branch=re.compile(r"^\s*(?:if|else|for|while|switch|case|catch|do)\b"),
	debug=re.compile(r"\bconsole\.(?:log|debug|info)\s*\(|\bdebugger\b|\balert\s*\("),
	safety=re.compile(r"\btry\b|\bcatch\b|\?\.|\?\?|[=!]==?\s*(?:null|undefined)\b|\btypeof\b"),
	doc=re.compile(r"^\s*/\*\*"),
	func_naming=CAMEL, var_naming=LENIENT, const_naming=LENIENT, class_naming=PASCAL)

SHADER = Profile(
	func=re.compile(r"^\s*(?:void|float|int|uint|bool|half|double|vec[234]|ivec[234]|uvec[234]|bvec[234]|mat[234](?:x[234])?|"
	                r"float[234](?:x[234])?|half[234]|sampler\w*|texture\w*)\s+(\w+)\s*\((.*?)\)\s*(?:\{|$)"),
	var=re.compile(r"^\s*(?:(const|uniform|varying|in|out|inout|attribute|instance|static|global)\s+)*(?:lowp\s+|mediump\s+|highp\s+)?"
	               r"(?:float|int|uint|bool|half|double|vec[234]|ivec[234]|uvec[234]|bvec[234]|mat[234](?:x[234])?|float[234](?:x[234])?|half[234]|sampler\w*)\s+(\w+)\s*()(=|;|:)"),
	branch=re.compile(r"^\s*(?:if|else|for|while|switch|case)\b"),
	doc=re.compile(r"^\s*/\*\*|^\s*///"),
	func_naming=LENIENT, var_naming=LENIENT, const_naming=LENIENT, class_naming=LENIENT)

CPP = Profile(
	func=re.compile(r"^\s*(?:(?:static|inline|virtual|explicit|constexpr|extern|friend)\s+)*(?!(?:if|for|while|switch|return|new|else|catch|delete|sizeof)\b)"
	                r"[\w:<>\[\],\.\*&]+\s+[\*&]?(\w+)\s*\(([^;]*)\)\s*(?:const\s*)?(?:override\s*)?(?:\{|$)"),
	var=re.compile(r"^\s*(?:static\s+)?(const\s+)?(?!(?:return|new|else|throw|delete|case)\b)[\w:<>\[\],\.\*&]+\s+[\*&]?(\w+)\s*()(=|;|\{)"),
	klass=re.compile(r"^\s*(?:class|struct)\s+(\w+)"),
	branch=re.compile(r"^\s*(?:if|else|for|while|switch|case|catch|do)\b"),
	debug=re.compile(r"\bprintf\s*\(|\bstd::cout\b|\bUE_LOG\s*\(|\bqDebug\s*\(|\bprint_line\s*\("),
	safety=re.compile(r"\btry\b|\bcatch\b|\bassert\s*\(|\bnullptr\b|\bcheck\s*\(|\bensure\s*\(|\bERR_FAIL\w*\("),
	doc=re.compile(r"^\s*/\*\*|^\s*///"),
	func_naming=LENIENT, var_naming=LENIENT, const_naming=LENIENT, class_naming=PASCAL)

PROFILES = {"gd": GDSCRIPT, "py": PYTHON, "cs": CSHARP, "js": JAVASCRIPT, "jsx": JAVASCRIPT, "ts": JAVASCRIPT,
            "tsx": JAVASCRIPT, "gdshader": SHADER, "gdshaderinc": SHADER, "glsl": SHADER, "hlsl": SHADER,
            "shader": SHADER, "usf": SHADER, "ush": SHADER, "frag": SHADER, "vert": SHADER, "fsh": SHADER,
            "vsh": SHADER, "wgsl": SHADER, "cpp": CPP, "cc": CPP, "c": CPP, "h": CPP, "hh": CPP, "hpp": CPP,
            "java": CSHARP, "kt": CSHARP, "swift": CSHARP, "rs": CPP, "go": CPP}

def profile_of(extension):
	return PROFILES.get(extension)

#--- line level helpers -------------------------------------------------------------------------

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
PLAIN_NUMBERS = set(["0", "1", "2", "-1", "0.0", "1.0", "0.5", "10", "100", "255", "0.1", "3", "4", "-2"])
NUMBER_CONTEXT = re.compile(r"\b(?:const|enum|range|Vector[234]i?|Color|Rect2|@export|export|\[\s*-?\d+\s*\]|size|version)\b")
CODE_IN_COMMENT = re.compile(r"^\s*(?:#|//)\s*(?:var|const|if|elif|else|for|while|func|def|return|print|self\.|\w+\s*=\s*\w|\w+\s*\(.*\)\s*;?\s*$)")
TODO = re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\b")
SECTION_HEADER = re.compile(r"^\s*(?:#|//)\s*(?:-{3,}|={3,}|#{3,}|region\b|section\b|\[\s*\w)")
EXPLAIN_WORDS = re.compile(r"\b(?:Initiali[sz]e|Ensure|Handle|Check if|Calculate|Compute|Update the|Returns?|This (?:function|method|"
                           r"script|class)|Note:|Optional(?:ly)?:|Example:|Helper|Validate|Iterate|Retrieve|Determine|Fallback)\b")
ASSIGNMENT = re.compile(r"(?<![=!<>:+\-*/%])=(?!=)")
SPACED_ASSIGNMENT = re.compile(r" =(?!=) ")
WORD = re.compile(r"[A-Za-z]+")

def __indent__(line, tabs):
	stripped = line.lstrip("\t ")
	leading = line[:len(line) - len(stripped)]
	if tabs:
		return leading.count("\t") + leading.count(" ") // 4
	return leading.count("\t") + leading.count(" ") // 4

def __comment_text__(line):
	stripped = line.strip()
	for marker in ("///", "//", "##", "#", "/**", "/*", "*", "\"\"\"", "'''"):
		if stripped.startswith(marker):
			return stripped[len(marker):].strip(" */")
	return stripped

def __is_sentence__(text):
	words = WORD.findall(text)
	return len(words) >= 3 and text[:1].isupper()

def __median__(values):
	values = sorted(values)
	if not values:
		return 0.0
	middle = len(values) // 2
	return float(values[middle]) if len(values) % 2 else (values[middle - 1] + values[middle]) / 2.0

def __clamp__(value, low=0.0, high=100.0):
	return max(low, min(high, value))

def __band__(value, best, worst):
	"""100 at best or better, 0 at worst or beyond, linear between; works whichever way round."""
	if best == worst:
		return 100.0
	position = (value - worst) / float(best - worst)
	return __clamp__(100.0 * position)

#--- the per-author and per-chunk measures ------------------------------------------------------

class Measures(object):
	"""Counts over a set of lines. Everything is a plain count, so that measures of chunks can be
	added up into measures of an author."""

	def __init__(self):
		self.lines = 0
		self.code = 0
		self.comments = 0
		self.blank = 0
		self.functions = 0
		self.functions_documented = 0
		self.functions_doc_syntax = 0
		self.functions_typed_return = 0
		self.functions_with_return_type_info = 0
		self.params = 0
		self.params_typed = 0
		self.vars = 0
		self.vars_typed = 0
		self.vars_with_type_info = 0
		self.names = 0
		self.names_conforming = 0
		self.name_length = 0
		self.function_lengths = []
		self.branches = 0
		self.max_nesting = 0
		self.nesting_sum = 0
		self.deep_lines = 0
		self.magic_numbers = 0
		self.long_lines = 0
		self.mixed_indent = 0
		self.debug_prints = 0
		self.commented_code = 0
		self.todos = 0
		self.safety = 0
		self.idioms = 0
		self.explanatory = 0
		self.sentence_comments = 0
		self.section_headers = 0
		self.explain_words = 0
		self.assignments = 0
		self.spaced_assignments = 0
		self.duplicates = 0
		self.normalized = {}

	def __iadd__(self, other):
		for (key, value) in other.__dict__.items():
			if key == "normalized":
				for (line, count) in value.items():
					self.normalized[line] = self.normalized.get(line, 0) + count
			elif key == "function_lengths":
				self.function_lengths = self.function_lengths + value
			elif key == "max_nesting":
				self.max_nesting = max(self.max_nesting, value)
			else:
				setattr(self, key, getattr(self, key) + value)
		return self

	def count_duplicates(self):
		self.duplicates = sum(count for count in self.normalized.values() if count >= DUPLICATE_MIN_COUNT)

	def per_hundred(self, value):
		return (100.0 * value / self.code) if self.code else 0.0

	def ratio(self, part, whole):
		return (float(part) / whole) if whole else None

	#--- the four sub-scores, each None when the language gives nothing to score it on

	def clarity(self):
		parts = []
		naming = self.ratio(self.names_conforming, self.names)
		if naming is not None:
			parts.append((100.0 * naming, 2.0))
		if self.code:
			#Commented-out code is not commentary; it is counted against hygiene instead.
			real_comments = max(0, self.comments - self.commented_code)
			density = 100.0 * real_comments / float(self.code + real_comments)
			parts.append((100.0 if 5.0 <= density <= 35.0 else __band__(density, 5.0, 0.0) if density < 5.0
			              else __band__(density, 35.0, 70.0), 1.0))
		documented = self.ratio(self.functions_documented, self.functions)
		if documented is not None:
			parts.append((100.0 * documented, 1.0))
		return self.__weighted__(parts)

	def structure(self):
		parts = []
		if self.function_lengths:
			parts.append((__band__(__median__(self.function_lengths), 25.0, 90.0), 1.5))
		if self.code:
			parts.append((__band__(self.max_nesting, 3.0, 7.0), 1.0))
			parts.append((__band__(self.per_hundred(self.deep_lines), 0.0, 20.0), 1.0))
		if self.functions:
			parts.append((__band__(self.branches / float(self.functions), 5.0, 14.0), 1.0))
		return self.__weighted__(parts)

	def robustness(self):
		parts = []
		typed = self.typing()
		if typed is not None:
			parts.append((100.0 * typed, 2.0))
		if self.code and self.code >= MIN_AUTHOR_LINES:
			parts.append((__band__(self.per_hundred(self.safety), 2.0, 0.0), 1.0))
		return self.__weighted__(parts)

	def hygiene(self):
		if not self.code:
			return None
		parts = [(__band__(self.per_hundred(self.debug_prints), 0.0, 5.0), 1.5),
		         (__band__(self.per_hundred(self.commented_code), 0.0, 6.0), 1.0),
		         (__band__(self.per_hundred(self.magic_numbers), 2.0, 14.0), 1.0),
		         (__band__(self.per_hundred(self.long_lines), 0.0, 15.0), 0.5),
		         (__band__(self.per_hundred(self.duplicates), 0.0, 25.0), 1.0),
		         (__band__(self.per_hundred(self.mixed_indent), 0.0, 10.0), 0.5)]
		return self.__weighted__(parts)

	def typing(self):
		"""Share of parameters, returns and variables that carry a type, where the language has
		optional types; None where every declaration is typed anyway."""
		whole = self.params + self.functions_with_return_type_info + self.vars_with_type_info
		if not whole:
			return None
		return (self.params_typed + self.functions_typed_return + self.vars_typed) / float(whole)

	def score(self):
		#Clarity weighs most: it is where a student's own habits show. Hygiene is what any linter
		#catches and what generated code never fails, so it counts for less.
		parts = [(self.clarity(), 3.0), (self.structure(), 2.0), (self.robustness(), 2.5), (self.hygiene(), 2.5)]
		return self.__weighted__([(value, weight) for (value, weight) in parts if value is not None])

	@staticmethod
	def __weighted__(parts):
		parts = [(value, weight) for (value, weight) in parts if value is not None]
		if not parts:
			return None
		return sum(value * weight for (value, weight) in parts) / sum(weight for (_unused, weight) in parts)

	def level(self):
		if self.code < MIN_AUTHOR_LINES or self.score() is None:
			return "unknown"
		for (floor, name) in LEVELS:
			if self.score() >= floor:
				return name
		return "beginning"

	def signals(self):
		"""The marks of generated code, as (name, present) pairs; the names are what the report
		shows next to a flagged chunk."""
		typed = self.typing()
		documented = self.ratio(self.functions_doc_syntax, self.functions)
		explanatory = self.per_hundred(self.explanatory)
		sentences = self.ratio(self.sentence_comments, self.comments)
		average_name = (self.name_length / float(self.names)) if self.names else 0.0
		hygiene = self.hygiene()
		spacing = self.ratio(self.spaced_assignments, self.assignments)
		return [
			("fully typed", typed is not None and typed >= 0.8 and self.params + self.vars_with_type_info >= 4),
			("doc comment on most functions", documented is not None and documented >= 0.6 and self.functions >= 2),
			("sentence-case explanatory comments", explanatory >= 12.0 and sentences is not None and sentences >= 0.6
			 and self.comments >= 4),
			("section-header comments", self.section_headers >= 2),
			("long descriptive names", average_name >= 10.0 and self.names >= 6),
			("nothing left over", hygiene is not None and hygiene >= 92.0 and self.code >= 40),
			("a large single-commit chunk", self.code >= 80),
			("explanatory wording in comments", self.explain_words >= 2),
			("uniformly spaced assignments", spacing is not None and spacing >= 0.97 and self.assignments >= 12),
		]

	def signal_count(self):
		return sum(1 for (_unused, present) in self.signals() if present)

	def as_dict(self):
		typed = self.typing()
		return {
			"lines": self.lines, "code_lines": self.code, "comment_lines": self.comments,
			"functions": self.functions,
			"functions_documented_pct": round(100.0 * self.functions_documented / self.functions, 1) if self.functions else None,
			"typed_pct": round(100.0 * typed, 1) if typed is not None else None,
			"naming_conforming_pct": round(100.0 * self.names_conforming / self.names, 1) if self.names else None,
			"median_function_length": __median__(self.function_lengths) if self.function_lengths else None,
			"max_nesting": self.max_nesting,
			"branches_per_function": round(self.branches / float(self.functions), 2) if self.functions else None,
			"debug_prints_per_100": round(self.per_hundred(self.debug_prints), 2),
			"magic_numbers_per_100": round(self.per_hundred(self.magic_numbers), 2),
			"commented_out_code_per_100": round(self.per_hundred(self.commented_code), 2),
			"long_lines_pct": round(self.per_hundred(self.long_lines), 2),
			"duplicate_lines_pct": round(self.per_hundred(self.duplicates), 2),
			"safety_checks_per_100": round(self.per_hundred(self.safety), 2),
			"todos": self.todos, "idioms": self.idioms,
			"clarity": None if self.clarity() is None else round(self.clarity(), 1),
			"structure": None if self.structure() is None else round(self.structure(), 1),
			"robustness": None if self.robustness() is None else round(self.robustness(), 1),
			"hygiene": None if self.hygiene() is None else round(self.hygiene(), 1),
			"score": None if self.score() is None else round(self.score(), 1),
			"level": self.level(),
		}

class Line(object):
	__slots__ = ("author", "email", "revision", "content", "is_comment", "indent", "number")

	def __init__(self, author, revision, content, is_comment, indent, number, email=""):
		self.author = author
		self.email = email
		self.revision = revision
		self.content = content
		self.is_comment = is_comment
		self.indent = indent
		self.number = number

def __function_length__(lines, start):
	"""Lines from the definition to the last line indented deeper than it, blank lines and
	trailing comments not counted."""
	depth = lines[start].indent
	length = 1
	last = start

	for index in range(start + 1, len(lines)):
		line = lines[index]
		if not line.content.strip():
			continue
		if line.indent <= depth and not (line.is_comment and lines[last].indent > depth):
			break
		if not line.is_comment:
			last = index
		length += 1

	return length

def __closing_brace_language__(profile):
	return profile in (CSHARP, JAVASCRIPT, SHADER, CPP)

def measure(lines, profile, selected):
	"""Measures over the lines for which selected(line) holds, read in the context of all the
	lines of the file, so that a function's length and its doc comment are judged whole."""
	result = Measures()
	previous_code = None

	for (index, line) in enumerate(lines):
		content = line.content
		stripped = content.strip()
		mine = selected(line)

		if mine:
			result.lines += 1
			if not stripped:
				result.blank += 1
			elif line.is_comment:
				result.comments += 1
				text = __comment_text__(content)
				if CODE_IN_COMMENT.match(content) and not (profile.doc and profile.doc.match(content)):
					result.commented_code += 1
				if TODO.search(content):
					result.todos += 1
				if SECTION_HEADER.match(content):
					result.section_headers += 1
				if __is_sentence__(text):
					result.sentence_comments += 1
				result.explain_words += len(EXPLAIN_WORDS.findall(text))
				following = next((candidate for candidate in lines[index + 1:index + 2]), None)
				if following is not None and following.content.strip() and not following.is_comment and \
				   not (profile.doc and profile.doc.match(content)):
					result.explanatory += 1
			else:
				result.code += 1
				result.nesting_sum += line.indent
				result.max_nesting = max(result.max_nesting, line.indent)
				if line.indent >= DEEP_NESTING:
					result.deep_lines += 1
				if len(content.rstrip("\r\n").expandtabs(4)) > LONG_LINE:
					result.long_lines += 1
				if profile.indent_tabs and content[:1] == " " and content.strip():
					result.mixed_indent += 1
				if profile.debug and profile.debug.search(stripped):
					result.debug_prints += 1
				if profile.safety and profile.safety.search(stripped):
					result.safety += 1
				if profile.idiom and profile.idiom.search(content):
					result.idioms += 1
				if profile.branch and profile.branch.match(content):
					result.branches += 1
				if TODO.search(stripped):
					result.todos += 1
				if not NUMBER_CONTEXT.search(stripped):
					result.magic_numbers += sum(1 for number in NUMBER.findall(stripped) if number not in PLAIN_NUMBERS)
				if ASSIGNMENT.search(stripped) and not stripped.startswith(("if", "elif", "while", "for")):
					result.assignments += 1
					if SPACED_ASSIGNMENT.search(stripped):
						result.spaced_assignments += 1
				if len(stripped) >= DUPLICATE_MIN_LENGTH and stripped not in ("}", "};", ")", "end"):
					key = re.sub(r"\s+", " ", stripped)
					result.normalized[key] = result.normalized.get(key, 0) + 1

				function = profile.func.match(content) if profile.func else None
				if function:
					groups = [group for group in function.groups() if group is not None]
					name = next((group for group in function.groups()[0::2] if group), "")
					params = next((group for group in function.groups()[1::2] if group is not None), "") if len(groups) > 1 else ""
					result.functions += 1
					result.function_lengths.append(__function_length__(lines, index))
					if name:
						result.names += 1
						result.name_length += len(name)
						if profile.func_naming and profile.func_naming.match(name):
							result.names_conforming += 1
					if profile.params_typed is not None:
						items = [item.strip() for item in params.split(",") if item.strip() and item.strip() != "self"]
						result.params += len(items)
						result.params_typed += sum(1 for item in items if profile.params_typed.search(item))
					if profile.return_typed is not None:
						result.functions_with_return_type_info += 1
						if profile.return_typed.search(content):
							result.functions_typed_return += 1
					above = next((candidate for candidate in reversed(lines[max(0, index - 1):index])
					              if candidate.content.strip()), None)
					below = next((candidate for candidate in lines[index + 1:index + 2] if candidate.content.strip()), None)
					documented = False
					doc_syntax = False
					if profile.docstring_below:
						documented = below is not None and profile.doc.match(below.content) is not None
						doc_syntax = documented
					else:
						documented = above is not None and above.is_comment
						doc_syntax = above is not None and profile.doc is not None and profile.doc.match(above.content) is not None
					result.functions_documented += 1 if documented else 0
					result.functions_doc_syntax += 1 if doc_syntax else 0
				elif profile.var and profile.var.match(content):
					match = profile.var.match(content)
					keyword = match.group(1) or ""
					name = match.group(2)
					result.vars += 1
					result.names += 1
					result.name_length += len(name)
					rule = profile.const_naming if keyword.strip() == "const" else profile.var_naming
					if rule and (rule.match(name) or (profile.const_naming and profile.const_naming.match(name))):
						result.names_conforming += 1
					if profile.var_typed is not None:
						result.vars_with_type_info += 1
						if profile.var_typed.match(content):
							result.vars_typed += 1
				elif profile.klass and profile.klass.match(content):
					name = profile.klass.match(content).group(1)
					result.names += 1
					result.name_length += len(name)
					if profile.class_naming and profile.class_naming.match(name):
						result.names_conforming += 1

		if stripped and not line.is_comment:
			previous_code = line

	result.count_duplicates()
	return result

#--- reading the repository ---------------------------------------------------------------------

class Chunk(object):
	def __init__(self, author, filename, revision):
		self.author = author
		self.filename = filename
		self.revision = revision
		self.measures = None
		self.polish = None
		self.verdict = "typical"
		self.reasons = []
		self.baseline = None

class BlameReader(workers.Worker):
	def __init__(self, changes, command, extension, filename, quality):
		workers.Worker.__init__(self)
		self.changes = changes
		self.command = command
		self.extension = extension
		self.filename = filename
		self.quality = quality

	def __author__(self, email, name):
		try:
			author = self.changes.get_latest_author_by_email(email)
		except KeyError:
			author = name
		if filtering.set_filtered(author, "author") or filtering.set_filtered(email, "email"):
			return None
		return author

	def work(self):
		raw = workers.lines_of(self.command)
		profile = profile_of(self.extension)
		lines = []
		(email, name, revision, number) = (None, None, None, 0)
		expect_content = False
		inside_comment = False

		for raw_line in raw:
			line = git.decode(raw_line).rstrip("\r\n")

			if expect_content:
				content = line[1:] if line.startswith("\t") else line
				(comments, inside_comment) = comment.handle_comment_block(inside_comment, self.extension, content)
				is_comment = comments > 0 or (inside_comment and not content.strip())
				number += 1
				lines.append(Line(self.__author__(email, name), revision, content, is_comment,
				                  __indent__(content, profile.indent_tabs if profile else False), number, email or ""))
				expect_content = False
				continue

			parts = line.split(" ", 2)
			if parts[0] == "author-mail":
				email = parts[1].lstrip("<").rstrip(">") if len(parts) > 1 else ""
			elif parts[0] == "author":
				name = line[7:].strip()
			elif parts[0] == "filename":
				expect_content = True
			elif len(parts[0]) == 40 and re.match(r"^[0-9a-f]{40}$", parts[0]):
				revision = parts[0]

		with __lock__:
			self.quality.files[self.filename] = (profile, lines)

class CodeQuality(object):
	def __init__(self, repo=None, changes=None, hard=False, resolver=None):
		self.files = {}
		self.authors = {}
		self.chunks = []
		self.flagged = []
		self.ratios = {}
		self.resolver = resolver

		if changes is None:
			return

		ls_tree = subprocess.Popen(["git", "ls-tree", "--name-only", "-r", "-z", interval.get_ref()],
		                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
		entries = [entry for entry in ls_tree.communicate()[0].split(b"\0") if entry]

		if ls_tree.returncode != 0:
			return

		progress = _(PROGRESS_TEXT)
		if repo is not None:
			progress = "[%s] " % repo.name + progress

		for (index, entry) in enumerate(entries):
			filename = git.decode(entry)
			extension = FileDiff.get_extension(filename)
			if profile_of(extension) is None or not FileDiff.is_valid_extension(filename) or \
			   filtering.set_filtered(FileDiff.get_filename(filename)):
				continue
			command = [item for item in ["git", "blame", "--line-porcelain", "--root", "-w"] +
			           (["-C", "-C", "-M"] if hard else []) + interval.get_blame_arguments() + ["--", filename] if item]
			BlameReader(changes, command, extension, filename, self).start()
			if format.is_interactive_format():
				terminal.output_progress(progress, index, len(entries))

		workers.join()
		self.__analyse__()

	def __iadd__(self, other):
		try:
			self.files.update(other.files)
			if other.resolver is not None:
				self.resolver = other.resolver
			self.__analyse__()
			return self
		except AttributeError:
			return other

	def __key__(self, line):
		if line.author is None:
			return None
		return self.resolver(line.author, line.email) if self.resolver else line.author

	def __analyse__(self):
		self.authors = {}
		self.chunks = []

		for (filename, (profile, lines)) in sorted(self.files.items()):
			if profile is None:
				continue
			keys = [self.__key__(line) for line in lines]
			revisions = {}
			for (line, key) in zip(lines, keys):
				if key is None:
					continue
				revisions.setdefault((key, line.revision), 0)
				revisions[(key, line.revision)] += 1
			for (author, revision) in revisions:
				chunk = Chunk(author, filename, revision)
				owned = set(index for (index, (line, key)) in enumerate(zip(lines, keys))
				            if key == author and line.revision == revision)
				chunk.measures = measure(lines, profile, lambda line, mine=owned: line.number - 1 in mine)
				self.chunks.append(chunk)
				self.authors.setdefault(author, Measures())
				self.authors[author] += chunk.measures

		for measures in self.authors.values():
			measures.count_duplicates()

		self.__judge_chunks__()

	def __judge_chunks__(self):
		"""Score every chunk, set each author's baseline at the median of their own chunks (or of
		everyone's when they have too few), and flag the ones that stand well above it."""
		for chunk in self.chunks:
			chunk.polish = chunk.measures.score() if chunk.measures.code >= MIN_CHUNK_LINES else None

		scored = [chunk for chunk in self.chunks if chunk.polish is not None]
		everyone = __median__([chunk.polish for chunk in scored])
		by_author = {}
		for chunk in scored:
			by_author.setdefault(chunk.author, []).append(chunk.polish)

		self.flagged = []
		for chunk in scored:
			own = by_author[chunk.author]
			chunk.baseline = __median__(own) if len(own) >= 3 else everyone
			signals = [name for (name, present) in chunk.measures.signals() if present]
			chunk.reasons = signals

			if chunk.polish < POOR_POLISH:
				chunk.verdict = "rough"
			elif (chunk.polish >= GOOD_POLISH and len(signals) >= 3) or (chunk.polish >= 80.0 and len(signals) >= 2):
				chunk.verdict = "polished"
			else:
				chunk.verdict = "typical"

			if chunk.polish >= 65.0 and chunk.polish >= chunk.baseline + 20.0 and len(signals) >= 2:
				self.flagged.append(chunk)

		self.flagged.sort(key=lambda chunk: -(chunk.polish - chunk.baseline))

		self.ratios = {}
		for author in self.authors:
			own = [chunk for chunk in scored if chunk.author == author]
			total = float(sum(chunk.measures.code for chunk in own)) or 1.0
			self.ratios[author] = {
				"good": 100.0 * sum(chunk.measures.code for chunk in own if chunk.polish >= GOOD_POLISH) / total,
				"fair": 100.0 * sum(chunk.measures.code for chunk in own if POOR_POLISH <= chunk.polish < GOOD_POLISH) / total,
				"poor": 100.0 * sum(chunk.measures.code for chunk in own if chunk.polish < POOR_POLISH) / total,
				"polished": 100.0 * sum(chunk.measures.code for chunk in own if chunk.verdict == "polished") / total,
				"flagged": sum(1 for chunk in self.flagged if chunk.author == author),
				"chunks": len(own),
				"unscored_lines": sum(chunk.measures.code for chunk in self.chunks
				                      if chunk.author == author and chunk.polish is None),
			}

	def get_authors(self):
		return self.authors

	def as_dict(self):
		return {
			"authors": [dict(name=author, ratios=dict((key, round(value, 1) if isinstance(value, float) else value)
			                                           for (key, value) in self.ratios.get(author, {}).items()),
			                 **measures.as_dict()) for (author, measures) in sorted(self.authors.items())],
			"flagged_chunks": [{
				"author": chunk.author, "file": chunk.filename, "revision": chunk.revision[:8],
				"code_lines": chunk.measures.code, "polish": round(chunk.polish, 1),
				"baseline": round(chunk.baseline, 1), "signals": chunk.reasons,
			} for chunk in self.flagged[:25]],
			"chunks_scored": sum(1 for chunk in self.chunks if chunk.polish is not None),
		}
