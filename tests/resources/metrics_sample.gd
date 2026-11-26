class_name MetricsSample extends Node

## A doc comment on a function.
func classify(value: int) -> String:
	if value < 0:
		return "negative"
	elif value == 0:
		return "zero"
	else:
		return "positive"

func count(items: Array) -> int:
	var total := 0
	for item in items:
		if item:
			total += 1
	while total > 100:
		total -= 1
	return total

func describe(kind: int) -> String:
	match kind:
		0:
			return "none"
		1:
			return "one"
	# an iffy comment with the word else in it
	var ifdef_count = 0
	return "many" if ifdef_count == 0 else "else"
