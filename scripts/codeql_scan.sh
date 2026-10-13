#!/bin/sh
# Runs the same CodeQL analysis GitHub's code scanning runs on this repo
# (default setup: Python and JavaScript/TypeScript, "default" query suite),
# locally, so a finding is caught before it is pushed. Exits non-zero if any
# alert is found and prints each one.
#
# Needs the CodeQL CLI (brew install --cask codeql). Keep its version equal to
# the one GitHub reports for the repo's alerts. Databases go in .codeql/
# (gitignored); query packs download on first run.
set -u
repo_root=$(git rev-parse --show-toplevel) || exit 1
cd "$repo_root" || exit 1

if ! command -v codeql >/dev/null 2>&1; then
  echo "CodeQL CLI not installed (brew install --cask codeql)." >&2
  exit 1
fi

out="$repo_root/.codeql"
mkdir -p "$out"
total=0

for lang in python javascript-typescript; do
  db="$out/db-$lang"
  sarif="$out/$lang.sarif"
  echo "CodeQL: building $lang database..."
  if ! codeql database create "$db" --language="$lang" --source-root="$repo_root" \
      --overwrite --quiet --codescanning-config="$repo_root/.github/codeql/codeql-config.yml" >/dev/null 2>&1; then
    echo "CodeQL: database build failed for $lang." >&2
    exit 1
  fi
  echo "CodeQL: analyzing $lang..."
  if ! codeql database analyze "$db" "codeql/$( [ "$lang" = python ] && echo python || echo javascript )-queries:codeql-suites/$( [ "$lang" = python ] && echo python || echo javascript )-code-scanning.qls" \
      --download --format=sarif-latest --output="$sarif" --quiet >/dev/null 2>&1; then
    echo "CodeQL: analysis failed for $lang." >&2
    exit 1
  fi
  found=$(python3 - "$sarif" <<'PY'
import json, sys
runs = json.load(open(sys.argv[1]))["runs"]
results = [r for run in runs for r in run.get("results", [])]
for r in results:
    loc = r["locations"][0]["physicalLocation"]
    print(f'  {r["ruleId"]}: {loc["artifactLocation"]["uri"]}:{loc["region"]["startLine"]}  {r["message"]["text"].splitlines()[0]}', file=sys.stderr)
print(len(results))
PY
)
  echo "CodeQL: $lang: $found finding(s)"
  total=$((total + found))
done

if [ "$total" -gt 0 ]; then
  echo "CodeQL found $total issue(s). Fix them before pushing." >&2
  exit 1
fi
echo "CodeQL: clean."
