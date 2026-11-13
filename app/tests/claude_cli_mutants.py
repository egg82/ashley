"""Plants each wrong implementation below in a copy of `app/` and runs `tests/test_claude_cli.py` there; a mutant is
caught when that run exits 1 naming a FAILED test. Run from `app/`: `python tests/claude_cli_mutants.py`."""

import os, shutil, subprocess, sys, tempfile
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent)
M = [
 ("ashley/inference/claude_cli.py", 'env = {"PATH": os.environ.get("PATH", ""), "HOME": home, "CLAUDE_CONFIG_DIR": home,', 'env = {**os.environ, "HOME": home, "CLAUDE_CONFIG_DIR": home,'),
 ("ashley/inference/claude_cli.py", '        if tools:\n            raise ProviderFailed("error", "the claude CLI provider is offered no tools")\n', ''),
 ("ashley/inference/routes.py", "        if not provider.takes_tools and task not in TOOLLESS:", "        if False:"),
 ("ashley/inference/router.py", "        if prompt.tools and task in TOOLLESS:", "        if False:"),
 ("ashley/inference/claude_cli.py", "            totals[i] += value", "            totals[i] = value"),
 ("ashley/inference/claude_cli.py", "        return ProviderFailed(status_failure(status), reason, usage)", "        return ProviderFailed(\"error\", reason, usage)"),
 ("ashley/inference/claude_cli.py", '        if result.get("stop_reason") == "refusal":', '        if False:'),
 ("ashley/inference/claude_cli.py", 'if result.get("is_error") is False and result.get("stop_reason") == "max_tokens":', 'if False:'),
 ("ashley/inference/claude_cli.py", 'if result.get("api_error_status") in (401, 403):', 'if result.get("api_error_status") in (401,):'),
 ("ashley/inference/claude_cli.py", '    if system.moment:\n        parts.append', '    if False:\n        parts.append'),
 ("ashley/inference/claude_cli.py", 'with tempfile.TemporaryDirectory(prefix="claude-cli-") as home:', 'for home in [tempfile.mkdtemp(prefix="claude-cli-")]:'),
 ("ashley/inference/claude_cli.py", 'if isinstance(subtype, str) and subtype.startswith("error_max_structured_output"):', 'if False:'),
 ("ashley/inference/claude_cli.py", '    return "unreachable" if result.get("is_error") is not False else None', '    return None'),
 ("ashley/inference/claude_cli.py", '        args += ["--effort", effort] if isinstance(effort, str) else []', '        pass'),
]
killed = 0
for i, (path, old, new) in enumerate(M):
    tmp = tempfile.mkdtemp(prefix="plant-")
    shutil.copytree(SRC, tmp + "/app", ignore=shutil.ignore_patterns("node_modules", ".mypy_cache", "__pycache__"))
    p = tmp + "/app/" + path
    s = open(p).read()
    assert s.count(old) == 1, f"mutant {i} could not plant"
    open(p, "w").write(s.replace(old, new, 1))
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/test_claude_cli.py", "-n", "2", "-q", "-p", "no:randomly"],
                       cwd=tmp + "/app", capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    failed = [l for l in r.stdout.splitlines() if l.startswith("FAILED")]
    ok = r.returncode == 1 and failed
    killed += bool(ok)
    print(f"mutant {i}: {'KILLED' if ok else 'SURVIVED rc=%d' % r.returncode} {failed[0][:110] if failed else r.stdout[-300:]}")
    shutil.rmtree(tmp)
print(f"{killed}/{len(M)} killed")
sys.exit(0 if killed == len(M) else 1)
