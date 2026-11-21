---
kind: engineering
label: Engineering
seeded_from: cad-design
---
# Method for engineering analysis

A judgement about strength, stiffness or fit under load is only as good as the number behind it. This is how to get a
number you can stand behind, and how to say it, including when there is none.

## When an analysis is worth running

- The part carries a load a person will notice if it fails: a bracket, hook, mount, gear tooth, arm, clip, anything a
  hand or a weight pulls on. A decorative part or one that only holds its own weight needs none.
- A choice rests on it: which material, how thick, whether a rib is needed, which way to print it.
- Do not run one to decorate an answer. If the loads are unknown and cannot be bounded, say so and ask; an analysis of
  an invented load is a guess with decimals.

## State the problem before running anything

Write down, and show the person, each of these. Each is a fact with a source, as any measurement is.

- **The load**: its size in newtons, its direction and the face it acts on. A mass is a force of about 9.8 N per
  kilogram, and a part that is dropped or pulled hard sees several times its resting load: say which case you analysed.
  Ask for the load when only the person knows it.
- **What holds the part still**: the faces that are bolted, glued or clamped. A fixed face holds the part rigidly there,
  which is stiffer than a real bolt, so stress next to it is only a rough guide.
- **The material**, by name, from the materials file the helper reads. A material not in it is not analysed: say so
  instead of borrowing the nearest one.
- **The print orientation.** Layers stack along Z. A part pulled apart across its layers fails far below the strength
  along them, and the analysis takes the weaker figure.

## Running it

In a build123d model run, declare the study before `show`, naming the part as `show` names it. Faces come from that
part's own shape, never from a typed coordinate:

```
faces = bracket.faces().sort_by(Axis.Z)
study("bracket", "PETG", {"mount": faces[0]}, {"pull": (faces[-1], (0, -30, 0))})
show(("bracket", bracket, "structural"))
```

`fixed` and `loads` map names to faces, a load as `(face, (fx, fy, fz))` in newtons spread over that face. `mesh_mm`
sets the element size; left out, the helper picks a coarse one from the part's thickness and coarsens it to fit the
sandbox, and the report says what it used. `min_safety_factor` is what the part must reach.

## Reading the result

The report's `fea` section has one entry per study. Read it before saying anything.

- **A safety factor is a range, `low` to `high`.** It is the material's across-layer strength (less its stated
  tolerance for `low`) over the peak stress. Report the range and the strength it is against. Below 1 the part yields
  under that load; the check `fea_safety_factor:<part>` asks `low` to reach `min_safety_factor`, and the app judges it
  as any check. The helper's default minimum is 2, a choice and not a rule: ask the person how much margin they want.
- **Say where it fails first**: the peak stress's point and the named face nearest it, and what that tells the person to
  change (a thicker wall, a fillet, a rib, another orientation).
- **Distrust a peak at a fixed edge or a load edge.** A sharp corner there makes stress that grows as the mesh gets
  finer. Re-run with `mesh_mm` halved: if the peak moves by more than a few percent, say it is not settled, and read
  the stress a little away from the corner instead of quoting the spike. Deflection settles much sooner than stress.
- **A `skip_reason` means there is no number.** `too_large`: the mesh is over what the sandbox solves, so coarsen
  `mesh_mm` or analyse a smaller part (a cut-out of the loaded region). `mesh_failed`: the shape has slivers or bad
  faces; simplify it. `not_solved`: the solve did not converge, for instance on a mesh of badly shaped elements. `over_time`: too
  slow. `face_not_found`: a face did not come from that part's shape. `unknown_material`: not in the file. Report a
  skipped study as "not analysed, because ...", never as safe.
- The material file lists values it took on assumption (`assumed`). Name them when the answer is close to the limit.

## Check it against a hand calculation

A solver can be wrong in ways its output does not show. Before relying on a result, work the simplest version by
hand and see that the two agree to within a few percent.

- A beam fixed at one end with a force `F` at the free end, length `L`, rectangular section width `b` and height `h`
  (bending about the axis with height `h`): stress at the root `6FL/(bh²)`, tip deflection `4FL³/(Ebh³)`. With `L` under
  about ten times `h`, shear adds a little to the deflection.
- A bar pulled along its length: stress `F/A`, stretch `FL/(EA)`.
- Use millimetres, newtons and megapascals (N/mm²) throughout; `E` is in megapascals.
- If the hand figure and the report differ by much more than a few percent, find out why before reporting either: the
  load direction, the fixed face and the units are the usual causes. Say which you used to check.

## What it cannot tell you

The material file is a printed test bar from one maker, at one setting. Infill, wall count, temperature, creep under a
steady load, heat and impact all change the real part, and none of them are in the number. Say that the figure is an
estimate for a solid part, that a hand-held print test is the real check, and that for anything where failure hurts
someone the answer is not this analysis alone.
