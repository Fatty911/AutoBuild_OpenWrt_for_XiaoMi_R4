#!/usr/bin/env python3
"""
Clean up GitHub releases by tag prefix, keeping specified number of latest releases per prefix.
Each workflow should only delete releases it created (identified by tag prefix).

Requirements:
- GitHub CLI (gh) installed and authenticated
- Repository set via GITHUB_REPOSITORY environment variable
"""

import os
import sys
import json
import subprocess
import argparse
import re
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
        if "github.com" in url:
            if "git@" in url:
                path = url.split(":")[1].replace(".git", "")
            else:
                path = url.split("github.com/")[1].replace(".git", "")
            if "/" in path:
                owner, repo = path.split("/", 1)
                return owner, repo
    except Exception:
        pass
    
    return "{owner}", "{repo}"

def run_gh_command(args: List[str]) -> Optional[dict]:
    """Run a gh command and return parsed JSON or None on failure."""
    try:
        cmd = ["gh"] + args
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        if result.returncode != 0:
            print(f"Error running gh command (exit code: {result.returncode})")
            if result.stderr:
                print(f"stderr: {result.stderr}")
            return None
        
        if not result.stdout.strip():
            return {}
        
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None

def get_releases() -> List[Dict[str, Any]]:
    """Get list of all releases in the repository."""
    result = run_gh_command([
        "release", "list",
        "--limit", "100",
        "--json", "tagName,name,createdAt,publishedAt"
    ])
    
    if result is None:
        return []
    
    # gh release list returns a list directly
    if isinstance(result, list):
        return result
    return []

def delete_release(tag_name: str) -> bool:
    """Delete a release by tag name."""
    result = run_gh_command([
        "release", "delete", tag_name,
        "--yes",  # Skip confirmation
        "--cleanup-tag"  # Also delete the git tag
    ])
    
    if result is None:
        print(f"  Failed to delete release {tag_name}")
        return False
    else:
        print(f"  Deleted release {tag_name}")
        return True

def classify_releases_by_prefix(
    releases: List[Dict[str, Any]], 
    tag_prefixes: List[str],
    keep_per_prefix: int = 3
) -> Tuple[Dict[str, List[Dict]], Dict[str, List[Dict]]]:
    """Classify releases by tag prefix.
    
    Args:
        releases: List of releases
        tag_prefixes: List of tag prefixes to match (e.g., ["OpenWRT.org_", "OpenWRT_Lienol_"])
        keep_per_prefix: Number of releases to keep per prefix
    
    Returns:
        Tuple of (releases_to_keep_by_prefix, releases_to_delete_by_prefix)
    """
    # Group releases by prefix
    releases_by_prefix: Dict[str, List[Dict[str, Any]]] = {}
    unmatched_releases: List[Dict[str, Any]] = []
    
    for release in releases:
        tag_name = release.get("tagName", "")
        matched = False
        
        for prefix in tag_prefixes:
            if tag_name.startswith(prefix):
                if prefix not in releases_by_prefix:
                    releases_by_prefix[prefix] = []
                releases_by_prefix[prefix].append(release)
                matched = True
                break
        
        if not matched:
            unmatched_releases.append(release)
    
    # Sort each group by creation date (newest first)
    for prefix in releases_by_prefix:
        releases_by_prefix[prefix].sort(
            key=lambda x: x.get("createdAt") or x.get("publishedAt") or "",
            reverse=True
        )
    
    # Identify releases to keep and delete
    releases_to_keep: Dict[str, List[Dict]] = {}
    releases_to_delete: Dict[str, List[Dict]] = {}
    
    for prefix, releases_list in releases_by_prefix.items():
        print(f"\n  Prefix '{prefix}': {len(releases_list)} releases")
        
        keep_releases = releases_list[:keep_per_prefix]
        delete_releases = releases_list[keep_per_prefix:]
        
        print(f"    Keeping: {len(keep_releases)} (newest)")
        print(f"    Deleting: {len(delete_releases)} (older)")
        
        releases_to_keep[prefix] = keep_releases
        releases_to_delete[prefix] = delete_releases
    
    if unmatched_releases:
        print(f"\n  Unmatched releases (not in any prefix): {len(unmatched_releases)}")
        for r in unmatched_releases:
            print(f"    - {r.get('tagName', 'unknown')}")
    
    return releases_to_keep, releases_to_delete

def cleanup_releases(
    tag_prefixes: List[str],
    keep_per_prefix: int = 3,
    dry_run: bool = False
) -> Dict[str, Any]:
    """Clean up releases by tag prefix.
    
    Args:
        tag_prefixes: List of tag prefixes to clean up
        keep_per_prefix: Number of releases to keep per prefix
        dry_run: If True, only show what would be deleted
    
    Returns:
        Summary of cleanup operation
    """
    print(f"Release Cleanup Script")
    print(f"======================")
    print(f"Keeping {keep_per_prefix} releases per prefix")
    print(f"Tag prefixes: {tag_prefixes}")
    if dry_run:
        print("DRY RUN - No releases will be deleted")
    
    # Get all releases
    releases = get_releases()
    print(f"\nTotal releases: {len(releases)}")
    
    if not releases:
        print("No releases found")
        return {"total": 0, "deleted": 0, "kept": 0}
    
    # Classify releases
    releases_to_keep, releases_to_delete = classify_releases_by_prefix(
        releases, tag_prefixes, keep_per_prefix
    )
    
    # Delete releases
    total_deleted = 0
    total_kept = 0
    
    for prefix, delete_list in releases_to_delete.items():
        print(f"\nProcessing prefix '{prefix}':")
        for release in delete_list:
            tag_name = release.get("tagName", "unknown")
            if dry_run:
                print(f"  Would delete: {tag_name}")
                total_deleted += 1
            else:
                if delete_release(tag_name):
                    total_deleted += 1
    
    for prefix, keep_list in releases_to_keep.items():
        total_kept += len(keep_list)
    
    return {
        "total": len(releases),
        "deleted": total_deleted,
        "kept": total_kept
    }

def main():
    parser = argparse.ArgumentParser(
        description="Clean up GitHub releases by tag prefix",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --prefix "OpenWRT.org_" --keep 3
  %(prog)s --prefix "OpenWRT.org_" --prefix "OpenWRT_Lienol_" --keep 3
  %(prog)s --prefix "OpenWRT.org_" --dry-run
        
This script requires:
  1. GitHub CLI (gh) installed and authenticated
  2. Repository context (GITHUB_REPOSITORY env var or run from within repo)
        """
    )
    
    parser.add_argument(
        "--prefix",
        action="append",
        required=True,
        help="Tag prefix to match (can be specified multiple times)"
    )
    
    parser.add_argument(
        "--keep",
        type=int,
        default=3,
        help="Number of releases to keep per prefix (default: 3)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )
    
    args = parser.parse_args()
    
    # Run cleanup
    summary = cleanup_releases(
        tag_prefixes=args.prefix,
        keep_per_prefix=args.keep,
        dry_run=args.dry_run
    )
    
    print(f"\n{'='*60}")
    print("CLEANUP SUMMARY")
    print("="*60)
    print(f"Total releases: {summary['total']}")
    print(f"Deleted: {summary['deleted']}")
    print(f"Kept: {summary['kept']}")
    
    if args.dry_run:
        print("\nNOTE: This was a dry run. Remove --dry-run to actually delete.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())