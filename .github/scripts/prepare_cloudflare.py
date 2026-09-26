"""Prepare a validated Pages artifact; never send credentials to the browser."""
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError

def gh(*args):
    return json.loads(subprocess.check_output(["gh", *args], text=True))

def extract(archive, target):
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if any(not (m.isfile() or m.isdir()) for m in members):
            raise RuntimeError("Only regular static files and directories are allowed")
        tar.extractall(target, filter="data")
    if not (target / "index.html").is_file():
        raise RuntimeError("Missing public index.html")

def main():
    repo = os.environ["GH_REPO"]
    run_id = os.environ.get("SOURCE_RUN_ID", "")
    if not run_id:
        runs = gh("api", f"repos/{repo}/actions/workflows/pages.yml/runs?branch=main&status=success&per_page=1")
        if not runs["workflow_runs"]:
            raise RuntimeError("No successful main-branch snapshot available")
        run_id = str(runs["workflow_runs"][0]["id"])
    if not run_id.isdigit():
        raise RuntimeError("Invalid source run ID")
    run = gh("api", f"repos/{repo}/actions/runs/{run_id}")
    if (run["conclusion"] != "success" or run["head_branch"] != "main"
            or run["head_repository"]["full_name"] != repo
            or run["path"] != ".github/workflows/pages.yml"):
        raise RuntimeError("Source must be a successful snapshot build from this repository's main branch")
    artifact_dir = Path("cf-artifact")
    subprocess.run(["gh", "run", "download", run_id, "--repo", repo,
                    "--name", "github-pages", "--dir", str(artifact_dir)], check=True)
    public = Path("cf-public")
    public.mkdir()
    extract(artifact_dir / "artifact.tar", public)

    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    project = os.environ["CLOUDFLARE_PROJECT"]
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not token:
        raise RuntimeError("Add the CLOUDFLARE_API_TOKEN repository secret before publishing")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", project):
        raise RuntimeError("Invalid project name")
    base = f"https://api.cloudflare.com/client/v4/accounts/{account}/pages/projects"
    def api(url, method="GET", payload=None):
        req = Request(url, data=json.dumps(payload).encode() if payload else None,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method=method)
        try:
            with urlopen(req, timeout=60) as response:
                result = json.load(response)
        except HTTPError as error:
            if error.code == 404 and method == "GET":
                return None
            # Never print request headers or credentials.
            raise RuntimeError(f"Cloudflare request failed: HTTP {error.code}") from None
        if not result.get("success"):
            raise RuntimeError("Cloudflare rejected the project request")
        return result["result"]
    existing = api(f"{base}/{project}")
    create = os.environ.get("CREATE_PROJECT") == "true"
    if create:
        if existing:
            raise RuntimeError("Project already exists. Inspect it before allowing a deployment; no files were uploaded.")
        existing = api(base, "POST", {"name": project, "production_branch": "main"})
    if not existing:
        raise RuntimeError("Project does not exist. Run the one-time create_project action.")
    if existing.get("source") or existing.get("production_branch") != "main":
        raise RuntimeError("Expected a Direct Upload project using main")
    domain = existing.get("subdomain", "")
    if not re.fullmatch(r"[a-z0-9-]+\.pages\.dev", domain):
        raise RuntimeError("Cloudflare returned an unexpected project domain")
    sha = run["head_sha"]
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise RuntimeError("Invalid source SHA")
    with open(os.environ["GITHUB_OUTPUT"], "a") as out:
        out.write(f"commit_sha={sha}\nsite_url=https://{domain}\n")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as out:
        out.write(f"Cloudflare project: {project}\n\nSource snapshot run: {run_id}\n\nURL: https://{domain}\n")
    print(f"Prepared validated snapshot run {run_id} for {domain}")

if __name__ == "__main__":
    main()

