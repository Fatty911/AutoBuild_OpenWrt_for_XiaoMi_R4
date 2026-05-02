#!/usr/bin/env python3
"""
Clean up GitHub Actions workflow runs per workflow, keeping specified number of runs per conclusion type.
Each workflow will keep the latest N successful and N failed runs, while deleting older ones.

Requirements:
- GitHub CLI (gh) installed and authenticated
- Repository set via GITHUB_REPOSITORY environment variable or --repo flag
"""

import os
import sys
import json
import subprocess
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

def get_repo_info() -> Tuple[str, str]:
    """Extract owner and repo from GITHUB_REPOSITORY environment variable."""
    repo_env = os.environ.get("GITHUB_REPOSITORY")
    if repo_env:
        if "/" in repo_env:
            owner, repo = repo_env.split("/", 1)
            return owner, repo
    
    # Fallback: try to get from git remote
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True
        )
        url = result.stdout.strip()
        # Extract from git URL (git@github.com:owner/repo.git or https://github.com/owner/repo)
        if "github.com" in url:
            if "git@" in url:
                # git@github.com:owner/repo.git
                path = url.split(":")[1].replace(".git", "")
            else:
                # https://github.com/owner/repo.git
                path = url.split("github.com/")[1].replace(".git", "")
            if "/" in path:
                owner, repo = path.split("/", 1)
                return owner, repo
    except Exception:
        pass
    
    # Last resort: use defaults (will likely fail)
    return "{owner}", "{repo}"

def run_gh_command(endpoint: str, method: str = "GET", params: Optional[List[str]] = None) -> Optional[dict]:
    """Run a gh command and return parsed JSON or None on failure."""
    owner, repo = get_repo_info()
    # Replace placeholders in endpoint
    endpoint = endpoint.format(owner=owner, repo=repo)
    
    cmd = ["gh", "api", endpoint]
    if method != "GET":
        cmd.extend(["-X", method])
    if params:
        cmd.extend(params)
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    
    if result.returncode != 0:
        print(f"Error running gh command (exit code: {result.returncode})")
        if result.stderr:
            print(f"stderr: {result.stderr}")
        return None
    
    if not result.stdout.strip():
        # Empty response (e.g., DELETE returns 204 No Content)
        return {}
    
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        print(f"Raw output: {result.stdout[:200]}...")
        return None

def get_workflows() -> List[Dict[str, Any]]:
    """Get list of all workflows in the repository."""
    response = run_gh_command("repos/{owner}/{repo}/actions/workflows")
    return response.get("workflows", []) if response else []

def get_workflow_runs(workflow_id: str, per_page: int = 100) -> List[Dict[str, Any]]:
    """Get all runs for a specific workflow."""
    runs = []
    page = 1
    
    while True:
        response = run_gh_command(
            f"repos/{{owner}}/{{repo}}/actions/workflows/{workflow_id}/runs",
            params=["-f", f"per_page={per_page}", "-f", f"page={page}"]
        )
        
        if not response or "workflow_runs" not in response:
            break
            
        workflow_runs = response["workflow_runs"]
        if not workflow_runs:
            break
            
        runs.extend(workflow_runs)
        
        # Check if there are more pages
        if len(workflow_runs) < per_page:
            break
        page += 1
    
    return runs

def delete_workflow_run(run_id: int) -> bool:
    """Delete a specific workflow run."""
    response = run_gh_command(
        f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}",
        method="DELETE"
    )
    
    # DELETE returns 204 No Content, so response will be empty dict {}
    # run_gh_command returns None on failure, {} on success
    if response is None:
        print(f"  Failed to delete run {run_id}")
        return False
    else:
        print(f"  Deleted run {run_id}")
        return True

def classify_runs(runs: List[Dict[str, Any]], keep_per_conclusion: int = 2, 
                  allowed_conclusions: List[str] = None) -> Tuple[List[Dict], List[Dict]]:
    """Classify runs into those to keep and those to delete.
    
    Args:
        runs: List of workflow runs
        keep_per_conclusion: Number of runs to keep per conclusion type
        allowed_conclusions: List of conclusion types to keep (None = keep all types)
    
    Returns:
        Tuple of (runs_to_keep, runs_to_delete)
    """
    if allowed_conclusions is None:
        allowed_conclusions = ["success", "failure"]  # Default: only success and failure
    
    # Group runs by conclusion
    runs_by_conclusion: Dict[str, List[Dict[str, Any]]] = {}
    
    for run in runs:
        # Skip runs that are not completed (e.g., in_progress, queued, pending)
        status = run.get("status", "unknown")
        if status != "completed":
            print(f"  Skipping run {run['id']} with status '{status}'")
            continue
            
        conclusion = run.get("conclusion", "unknown")
        
        # Filter by allowed conclusions
        if allowed_conclusions and conclusion not in allowed_conclusions:
            # If conclusion is not in allowed list, mark for deletion
            if "other" not in runs_by_conclusion:
                runs_by_conclusion["other"] = []
            runs_by_conclusion["other"].append(run)
            continue
            
        if conclusion not in runs_by_conclusion:
            runs_by_conclusion[conclusion] = []
        runs_by_conclusion[conclusion].append(run)
    
    # Sort runs within each conclusion group by creation date (newest first)
    for conclusion in runs_by_conclusion:
        runs_by_conclusion[conclusion].sort(
            key=lambda x: datetime.fromisoformat(x["created_at"].replace("Z", "+00:00")),
            reverse=True
        )
    
    # Identify runs to keep and delete
    runs_to_keep = []
    runs_to_delete = []
    
    for conclusion, runs_list in runs_by_conclusion.items():
        if conclusion == "other":
            # Delete all runs not in allowed conclusions
            runs_to_delete.extend(runs_list)
            print(f"  Conclusion '{conclusion}': {len(runs_list)} runs (all will be deleted)")
            continue
            
        print(f"  Conclusion '{conclusion}': {len(runs_list)} runs")
        
        # Keep the latest N runs for this conclusion
        keep_runs = runs_list[:keep_per_conclusion]
        delete_runs = runs_list[keep_per_conclusion:]
        
        print(f"    Keeping: {len(keep_runs)} (newest)")
        print(f"    Deleting: {len(delete_runs)} (older)")
        
        runs_to_keep.extend(keep_runs)
        runs_to_delete.extend(delete_runs)
    
    return runs_to_keep, runs_to_delete

def cleanup_workflow(workflow_id: str, workflow_name: str, keep_per_conclusion: int = 2) -> Dict[str, int]:
    """Clean up runs for a specific workflow, keeping N runs per conclusion type."""
    print(f"\nProcessing workflow: {workflow_name} (ID: {workflow_id})")
    
    # Get all runs for this workflow
    all_runs = get_workflow_runs(workflow_id)
    print(f"  Total runs: {len(all_runs)}")
    
    # Classify runs
    runs_to_keep, runs_to_delete = classify_runs(all_runs, keep_per_conclusion)
    
    # Delete runs
    deleted_count = 0
    for run in runs_to_delete:
        if delete_workflow_run(run["id"]):
            deleted_count += 1
    
    return {
        "workflow_name": workflow_name,
        "total_runs": len(all_runs),
        "deleted": deleted_count,
        "remaining": len(runs_to_keep)
    }

def simulate_cleanup(workflow_id: str, workflow_name: str, keep_per_conclusion: int = 2) -> Dict[str, int]:
    """Simulate cleanup for dry run."""
    print(f"\n[DRY RUN] Processing workflow: {workflow_name}")
    
    all_runs = get_workflow_runs(workflow_id)
    print(f"  Total runs: {len(all_runs)}")
    
    runs_to_keep, runs_to_delete = classify_runs(all_runs, keep_per_conclusion)
    
    return {
        "workflow_name": workflow_name,
        "total_runs": len(all_runs),
        "deleted": len(runs_to_delete),
        "remaining": len(runs_to_keep)
    }

def main():
    parser = argparse.ArgumentParser(
        description="Clean up GitHub Actions workflow runs per workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --keep 2                     # Keep 2 runs per conclusion per workflow
  %(prog)s --keep 3 --workflow-only Build_OpenWrt_Firmware  # Only clean specific workflow
  %(prog)s --dry-run                    # Dry run (no deletion)
        
This script requires:
  1. GitHub CLI (gh) installed and authenticated
  2. Repository context (run from within repo or use --repo flag)
        """
    )
    
    parser.add_argument(
        "--keep",
        type=int,
        default=2,
        help="Number of runs to keep per conclusion type (default: 2)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )
    
    parser.add_argument(
        "--workflow-only",
        type=str,
        help="Only clean runs for specific workflow name (partial match)"
    )
    
    parser.add_argument(
        "--exclude-workflow",
        action="append",
        default=[],
        help="Exclude workflow(s) from cleanup (can be specified multiple times)"
    )
    
    parser.add_argument(
        "--keep-all-conclusions",
        action="store_true",
        help="Keep runs for all conclusion types, not just success and failure"
    )
    
    args = parser.parse_args()
    
    if args.dry_run:
        print("DRY RUN - No runs will be deleted")
    
    print(f"Workflow Run Cleanup Script")
    print(f"==========================")
    print(f"Keeping {args.keep} runs per conclusion per workflow")
    if not args.keep_all_conclusions:
        print("Only keeping 'success' and 'failure' conclusion types")
    
    # Get all workflows
    response = run_gh_command("repos/{owner}/{repo}/actions/workflows")
    if not response:
        print("Error: Could not fetch workflows. Check authentication and permissions.")
        return 1
    
    workflows = response.get("workflows", [])
    
    if not workflows:
        print("No workflows found")
        return 0
    
    print(f"Found {len(workflows)} workflows")
    
    # Determine which conclusions to keep
    allowed_conclusions = None if args.keep_all_conclusions else ["success", "failure"]
    
    # Filter workflows if needed
    workflows_to_process = []
    for workflow in workflows:
        workflow_name = workflow["name"]
        workflow_id = str(workflow["id"])
        
        # Skip excluded workflows
        if any(excluded.lower() in workflow_name.lower() for excluded in args.exclude_workflow):
            print(f"Skipping excluded workflow: {workflow_name}")
            continue
        
        # Filter by workflow-only if specified
        if args.workflow_only:
            if args.workflow_only.lower() not in workflow_name.lower():
                continue
        
        workflows_to_process.append((workflow_id, workflow_name))
    
    print(f"Processing {len(workflows_to_process)} workflows")
    
    # Process each workflow
    summary = []
    for workflow_id, workflow_name in workflows_to_process:
        if args.dry_run:
            result = simulate_cleanup(workflow_id, workflow_name, args.keep)
            summary.append(result)
            print(f"  Would delete {result['deleted']} runs, keep {result['remaining']}")
        else:
            result = cleanup_workflow(workflow_id, workflow_name, args.keep)
            summary.append(result)
    
    # Print summary
    print(f"\n{'='*60}")
    print("CLEANUP SUMMARY")
    print("="*60)
    for item in summary:
        print(f"{item['workflow_name']}:")
        print(f"  Total runs: {item['total_runs']}")
        print(f"  Deleted: {item['deleted']}")
        print(f"  Remaining: {item['remaining']}")
    
    total_deleted = sum(item['deleted'] for item in summary)
    total_remaining = sum(item['remaining'] for item in summary)
    
    print(f"\nTOTAL:")
    print(f"  Deleted: {total_deleted} runs")
    print(f"  Remaining: {total_remaining} runs")
    
    if args.dry_run:
        print(f"\nNOTE: This was a dry run. Remove --dry-run flag to actually delete.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())