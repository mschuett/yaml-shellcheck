#!/usr/bin/env sh

# very simple shell loop, I should probably rewrite this in pytest...

GLOBIGNORE=".."
for f in test-input/.*.y*ml test-input/*.y*ml; do
  echo "== test file $f"
  if [ ! -f "$f.test_expected" ]; then
    echo "ERROR: missing test spec file $f.test_expected"
    touch found_error
    continue
  fi

  python3 yaml_shellcheck.py "$f" 2>&1 \
    | grep -o '\bSC[0-9]*\b' \
    > "$f.test_findings"

  if diff "$f.test_expected" "$f.test_findings"; then
    echo "OK"
  else
    echo "ERROR"
    touch found_error
  fi
done

# fail test job on error
if [ -f found_error ]; then
  exit 1
fi
