---
kind: code
label: Code
seeded_from: agentic-engineering
---
# Method for code work

Code you write on a bench has to be easy to read, easy to test and hard to get wrong. Every rule below serves that:
make bugs hard to create and easy to find.

## Before writing

- Say in one sentence what the code does for the person and what a correct result looks like. If you cannot, ask.
- Look at what the bench already holds. A code piece beside yours may already do part of it; extend it before you
  start a second one that does the same thing differently.
- If the job is a new kind of thing (a new data source, a new schedule, a second copy of something that exists), ask
  first what it is an instance of and what already does that kind of job. Extend or combine; build a new one only when
  nothing fits, and say why to the person.

## Shape

- **One function, one job, small.** If you need "and" to describe it, it is two functions. A function that does not
  fit on a screen is two or three. A file that groups unrelated jobs is several files.
- **Narrow interfaces.** A function takes the values it uses, not a whole record or a bag of settings. State that
  many functions write to is the usual home of bugs; pass values in and return values out.
- **Data, not branches, for content.** When a new case is a new row in a table, write the table. A new kind should
  be data, not another `if`.
- **Name things for what they are.** A reader should know what a function does from its name and arguments without
  opening it.
- **Never decide by reading words in natural-language text.** If behaviour depends on what a text says, the place that
  writes the text carries an explicit field for it, and the code reads the field.
- **Comments say what a reader of the code could not guess**: the contract of a public function, or the one reason a
  strange-looking line is not a mistake. Do not narrate history or restate the code.

## Tests

A test earns its place only if it can fail. Every test you write:

1. Names the behaviour it protects, not the function it calls.
2. Has been seen failing: break the code on purpose (change a comparison, drop a line) and confirm the test goes red,
   then put the code back. A test that passes against broken code is worse than none, because it reads as safety.
3. Checks a result, not that nothing raised. An empty result, a zero or a skipped case passes silently, so assert
   that the thing you scanned or counted was not empty.
4. Is not written only from the code. Write the expected values from the stated contract or from real captured
   output. Expected values you made up while reading your own code only confirm what you already assumed.

Include the boring edges: empty input, one item, the boundary of a limit, the same input twice. When you fix a bug,
the fix comes with the test that would have caught it.

## Running on the bench

- Run the piece with the bench's run tool and read the actual output before saying it works. "It should work" is not a
  result. The sandbox runs the standard library only, has no network, and stops a script after a few seconds, so keep
  runs small and say plainly when something could not be run there.
- When the run fails, read the error, change one thing and run again. Several edits at once leave you unable to tell
  which one helped.
- Say what you ran and what it showed. Separate "I ran this and saw X" from "I expect X".

## Changing existing code

- Keep a restructuring and a behaviour change apart. First move or rename with the behaviour identical, and show it is
  identical (same output on the same inputs). Then change behaviour as its own step with its own test.
- If the same behaviour needs patch after patch, the design cannot express what is wanted. Stop, restate what is
  wanted in plain words, and rewrite that part, keeping the old cases as tests.
- Never make a limit or check weaker to get a change through. If a check fails, find what your change did and fix that,
  or tell the person exactly which check and why.
- Do not add guards for cases that cannot happen. Each addition is something to read and maintain.

## Handing it back

Tell the person what the code does, how you checked it, what you did not check, and anything you assumed. Keep it
short and put the thing they must decide where they will see it.
