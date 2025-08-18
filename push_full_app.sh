set -euo pipefail

APP_DIR=~/frappe-bench/apps/firtrackpro
REMOTE_SSH=git@github.com:mrkilvo/Fire-Track-Pro.git

cd "$APP_DIR"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || git init
git config user.name "Steve Kilvington"
git config user.email "${GIT_USER_EMAIL:-steve@example.com}"

if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  git add -A
  git commit -m "initial"
fi

git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE_SSH"

# Ensure required top-level files exist (safe if already there)
[ -f hooks.py ] || cat > hooks.py <<'PY'
app_name = "firtrackpro"
app_title = "FireTrack Pro"
app_publisher = "Steve Kilvington"
app_description = "Fire compliance and asset management on Frappe v15"
app_email = "noreply@example.com"
app_license = "MIT"
app_version = "0.1.0"
fixtures = [
  {"doctype": "Custom Field"},
  {"doctype": "Property Setter"},
  {"doctype": "Client Script"},
  {"doctype": "Server Script"},
  {"doctype": "Print Format"},
  {"doctype": "Workspace"},
  {"doctype": "Role"},
]
PY

[ -f MANIFEST.in ] || printf "%s\n" "graft firtrackpro" "global-exclude *.pyc __pycache__ .DS_Store" > MANIFEST.in

[ -f .gitattributes ] || cat > .gitattributes <<'GA'
* text=auto eol=lf
*.py text eol=lf
*.js text eol=lf
*.ts text eol=lf
*.css text eol=lf
*.html text eol=lf
*.json text eol=lf
*.yml text eol=lf
*.yaml text eol=lf
public/images/** filter=lfs diff=lfs merge=lfs -text
public/files/**   filter=lfs diff=lfs merge=lfs -text
GA

# Stage everything, including files that might be ignored by global rules
git add -A
git add -f firtrackpro/**/*.json || true
git add -f **/doctype/**/*.json || true
git add -f firtrackpro/public/** || true
git add -f www/** || true

# Commit if there are changes
git diff --cached --quiet || git commit -m "chore: push full app (doctypes, public, hooks, manifest)"

# Standardize branch and push
git branch -M main
if git ls-remote --exit-code --heads origin main >/dev/null 2>&1; then
  git pull --rebase origin main || true
fi
git push -u origin main
