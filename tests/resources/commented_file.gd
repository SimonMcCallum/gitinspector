# A line comment at the top.
extends Node

## A doc comment.
var speed := 10 # trailing comments do not count as comment lines

"""
A string used as a block comment,
three lines long.
"""

func _ready() -> void:
	# an indented comment
	speed = 20
	#another one, no space
	pass
