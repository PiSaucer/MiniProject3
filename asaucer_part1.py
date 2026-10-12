#!/usr/bin/env python3
# asaucer_part1.py
# MiniProject3 Part 1 validator for bslessma project statistics

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

PROJECT_OWNER_NETID = "bslessma"
VALIDATOR_NETID = "asaucer"
STATUS_CUTOFF = dt.datetime(2025, 9, 30, 23, 59, 59, tzinfo=dt.timezone.utc)
ACTIVE_SINCE = dt.datetime(2025, 4, 1, tzinfo=dt.timezone.utc)

DEFAULT_STATS_URL = (
    "https://raw.githubusercontent.com/breanna-s/MiniProject2/"
    "master/bslessma_project_stats.csv"
)
DEFAULT_GAP_COMMITS = Path("Miniproject2/bslessma_project_gap_commits.csv")
DEFAULT_TIMESERIES_DIR = Path("Miniproject2/bslessma_timeseries_csv")
DEFAULT_UPDATE = Path("asaucer_validation_log.csv")
DEFAULT_OUTPUT = Path("asaucer_validation_log.csv")

FIELD_SOURCE_COLUMNS = (
    ("HasRecovered", "HasRecovered"),
    ("WhyRecovered", "WhyRecovered"),
    ("ActivityPattern", "Activity Pattern"),
    ("Currentstatus", "Currentstatus"),
    ("RecentThemes", "RecentThemes"),
)
FIELDS = tuple(field for field, _ in FIELD_SOURCE_COLUMNS)
COLUMNS = (
    "WOCProjectID",
    "ProjectOwnerNetID",
    "ValidatorNetID",
    "Field",
    "AuthorValue",
    "ValidatorValue",
    "PreDiscussAgreementstatus(Yes/No)",
    "AdjudicatedValue",
    "KeyEvidence",
    "Comments",
)
REQUIRED_PART1_COLUMNS = (
    "WOCProjectID",
    "ProjectOwnerNetID",
    "ValidatorNetID",
    "Field",
    "AuthorValue",
    "ValidatorValue",
    "PreDiscussAgreementstatus(Yes/No)",
    "KeyEvidence",
)

ACTIVITY_LABELS = {
    "steady",
    "rising",
    "declining",
    "u-shaped",
    "stopped",
    "cyclical",
    "irregular",
}
THEME_LABELS = {
    "feature development",
    "bug fixes",
    "documentation updates",
    "dependency updates",
    "release",
    "security patches",
    "automated bot contributions",
    "other",
}
REPOSITORY_REDIRECTS = {
    "intellistream/alliancedb": "DataSysResearch/AllianceDB",
    "great-expectations/great_expectations": "fivetran/great_expectations",
    "andreasrupp/hyperhdg": "HyperHDG/HyperHDG",
}
REVIEWED_SHA_RE = re.compile(r"ReviewedSHAs=([0-9a-f,]+)", re.IGNORECASE)
VERIFIED_GAP_BOUNDARIES = {
    "projectcypress_cypress": {
        "pre": {
            "commit": "e20941e8ae9d72c3083e72189bc5159da042e158",
            "time": "2024-03-18 00:00:00",
            "message": "Mongoid8",
        },
        "post": {
            "commit": "71879389014e6d05721e8de0490cea38f29006ad",
            "time": "2024-05-09 00:00:00",
            "message": "use gem versions",
        },
    }
}

class SourceError(RuntimeError):
    pass

class GitHubError(RuntimeError):
    pass

def request_bytes(url: str, *, token: str | None = None) -> tuple[bytes, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=35) as response:
            return response.read(), response.headers
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        remaining = exc.headers.get("X-RateLimit-Remaining", "unknown")
        reset = exc.headers.get("X-RateLimit-Reset", "unknown")
        detail = ""
        try:
            detail = json.loads(body).get("message", "")
        except json.JSONDecodeError:
            detail = body[:200]
        raise GitHubError(
            f"GitHub request failed ({exc.code}) for {url}: {detail}; "
            f"rate-limit remaining={remaining}, reset={reset}. "
            "Set GH_TOKEN or GITHUB_TOKEN and retry."
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise GitHubError(f"GitHub request failed for {url}: {exc}") from exc

def fetch_text(source: str | Path) -> str:
    source_text = str(source)
    if source_text.startswith(("https://", "http://")):
        try:
            data, _ = request_bytes(source_text)
        except GitHubError as exc:
            raise SourceError(str(exc)) from exc
        return data.decode("utf-8-sig")
    try:
        return Path(source).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SourceError(f"Cannot read {source}: {exc}") from exc

def read_csv_source(source: str | Path, delimiter: str = ",") -> list[dict[str, str]]:
    text = fetch_text(source)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not reader.fieldnames:
        raise SourceError(f"CSV has no header: {source}")
    return rows

def read_validation_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source, delimiter=";")
            if tuple(reader.fieldnames or ()) != COLUMNS:
                raise ValueError(f"Unexpected columns in {path}. Expected: {', '.join(COLUMNS)}")
            return list(reader)
    except OSError as exc:
        raise SourceError(f"Cannot read validation CSV {path}: {exc}") from exc

def read_partner_stats(source: str) -> list[dict[str, str]]:
    rows = read_csv_source(source)
    required = {"project", *(column for _, column in FIELD_SOURCE_COLUMNS)}
    if not rows or not required.issubset(rows[0]):
        missing = required.difference(rows[0] if rows else ())
        raise SourceError(f"Partner stats CSV is missing columns: {sorted(missing)}")
    projects = [
        row
        for row in rows
        if "_" in row.get("project", "")
        and all(row.get(column, "").strip() for _, column in FIELD_SOURCE_COLUMNS)
    ]
    if len(projects) != 10:
        raise SourceError(f"Expected 10 complete project rows, got {len(projects)}")
    if len({row["project"] for row in projects}) != 10:
        raise SourceError("Partner stats CSV contains duplicate project identifiers")
    return projects

def repository_from_url(url: str) -> str:
    prefix = "https://github.com/"
    if not url.startswith(prefix):
        raise ValueError(f"Expected a GitHub repository URL, got {url!r}")
    repository = url[len(prefix):].strip("/")
    if repository.count("/") != 1:
        raise ValueError(f"Expected an owner/repository URL, got {url!r}")
    return repository

def project_repository_name(project_id: str) -> str:
    try:
        return project_id.split("_", 1)[1].casefold()
    except (IndexError, AttributeError) as exc:
        raise ValueError(f"Invalid project identifier {project_id!r}") from exc

def canonical_repository(original_repository: str) -> str:
    return REPOSITORY_REDIRECTS.get(original_repository.casefold(), original_repository)

def combine_stats_and_judgments(stats_rows: list[dict[str, str]], judgment_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    judgments: dict[tuple[str, str], dict[str, str]] = {}
    for row in judgment_rows:
        repository_name = repository_from_url(row["WOCProjectID"]).split("/", 1)[1]
        key = (repository_name.casefold(), row["Field"])
        if key in judgments:
            raise ValueError(f"Duplicate validation judgment for {key}")
        judgments[key] = row

    combined = []
    for field, source_column in FIELD_SOURCE_COLUMNS:
        for stats_row in stats_rows:
            key = (project_repository_name(stats_row["project"]), field)
            if key not in judgments:
                raise ValueError(
                    f"Validation CSV has no {field} row for {stats_row['project']}"
                )
            row = judgments[key].copy()
            source_author_value = stats_row[source_column].strip()
            if row["AuthorValue"] != source_author_value:
                raise ValueError(
                    f"AuthorValue changed for {stats_row['project']} / {field}: "
                    f"validation CSV has {row['AuthorValue']!r}, partner stats has "
                    f"{source_author_value!r}. Refusing to overwrite the original label."
                )
            combined.append(row)
    return combined

def parse_month(value: str) -> dt.date:
    try:
        return dt.datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except ValueError as exc:
        raise SourceError(f"Invalid month {value!r}; expected YYYY-MM") from exc

def next_month(value: dt.date) -> dt.date:
    year = value.year + (value.month == 12)
    month = 1 if value.month == 12 else value.month + 1
    return dt.date(year, month, 1)

def load_timeseries(directory: str | Path, project_id: str) -> list[tuple[str, int]]:
    filename = f"bslessma_timeseries_{project_id}.csv"
    directory_text = str(directory)
    if directory_text.startswith(("https://", "http://")):
        source: str | Path = f"{directory_text.rstrip('/')}/{filename}"
    else:
        source = Path(directory) / filename
    rows = read_csv_source(source)
    if not rows or not {"Month", "Commits"}.issubset(rows[0]):
        raise SourceError(f"Unexpected time-series schema in {source}")

    result = []
    previous = None
    for row in rows:
        month = parse_month(row["Month"])
        if previous and month != next_month(previous):
            raise SourceError(f"Non-contiguous monthly series in {source} at {row['Month']}")
        try:
            count_float = float(row["Commits"])
        except (TypeError, ValueError) as exc:
            raise SourceError(f"Invalid commit count in {source}: {row['Commits']!r}") from exc
        if count_float < 0 or not count_float.is_integer():
            raise SourceError(f"Commit count must be a nonnegative integer in {source}")
        result.append((row["Month"], int(count_float)))
        previous = month
    return result

def activity_summary(series: list[tuple[str, int]]) -> str:
    if not series:
        raise SourceError("Time series is empty")
    counts = [count for _, count in series]
    length = len(counts)
    segments = []
    for segment in range(4):
        start = round(segment * length / 4)
        end = round((segment + 1) * length / 4)
        segments.append(statistics.mean(counts[start:end]))
    peak_index = max(range(length), key=counts.__getitem__)
    active_months = sum(count > 0 for count in counts)
    annual: dict[str, int] = defaultdict(int)
    for month, count in series:
        annual[month[:4]] += count
    recent_years = list(annual.items())[-3:]
    return (
        f"Monthly series {series[0][0]}–{series[-1][0]} ({length} months): "
        f"{sum(counts):,} commits; {active_months}/{length} active months; "
        f"quarter-period mean commits/month "
        f"{segments[0]:.1f}/{segments[1]:.1f}/{segments[2]:.1f}/{segments[3]:.1f}; "
        f"peak {counts[peak_index]} in {series[peak_index][0]}; "
        f"last 12 months {sum(counts[-12:]):,}; recent annual totals "
        + ", ".join(f"{year}={count:,}" for year, count in recent_years)
        + "."
    )

def load_gap_commits(source: str | Path) -> dict[str, dict[str, list[dict[str, str]]]]:
    rows = read_csv_source(source)
    required = {"pre/post", "project", "commit", "time", "message"}
    if not rows or not required.issubset(rows[0]):
        raise SourceError(f"Gap-commit CSV is missing columns: {sorted(required)}")
    grouped: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: {"pre": [], "post": []})
    for row in rows:
        side = row["pre/post"].strip().casefold()
        if side not in ("pre", "post"):
            raise SourceError(f"Unexpected pre/post value {row['pre/post']!r}")
        grouped[row["project"]][side].append(row)
    for sides in grouped.values():
        for commits in sides.values():
            commits.sort(key=lambda row: row["time"])
    return grouped

def brief_commit(commit: dict[str, str]) -> str:
    message = " ".join(commit["message"].split())
    if len(message) > 100:
        message = message[:97] + "..."
    return f"{commit['time'][:10]} {commit['commit'][:9]} {message!r}"

def month_distance(left: dt.date, right: dt.date) -> int:
    return (right.year - left.year) * 12 + right.month - left.month

def gap_commits_match_stats(stats_row: dict[str, str], pre: list[dict[str, str]], post: list[dict[str, str]]) -> bool:
    """Return whether stored boundary commits are adjacent to the reported gap."""
    try:
        gap_start = parse_month(stats_row["LongestGapStart"])
        gap_end = parse_month(stats_row["LongestGapEnd"])
        pre_month = parse_month(pre[-1]["time"][:7])
        post_month = parse_month(post[0]["time"][:7])
    except (KeyError, IndexError) as exc:
        raise SourceError(
            f"Incomplete gap boundary data for {stats_row.get('project', '?')}"
        ) from exc
    # Partner files normally place the pre commit in the preceding month and the
    # post commit in the reported end month or the immediately following month.
    return month_distance(pre_month, gap_start) == 1 and month_distance(gap_end, post_month) in (0, 1)

def gap_evidence(stats_row: dict[str, str],gap_rows: dict[str, dict[str, list[dict[str, str]]]]) -> tuple[str, bool]:
    project = stats_row["project"]
    try:
        gap_length = int(float(stats_row.get("LongestGapLength", "0") or 0))
    except ValueError as exc:
        raise SourceError(f"Invalid LongestGapLength for {project}") from exc
    sides = gap_rows.get(project, {"pre": [], "post": []})
    if gap_length == 0:
        return (
            "Partner statistics report LongestGapLength=0 months and the gap-commit "
            "file has no recovery boundary to interpret.",
            False,
        )
    pre = sides["pre"]
    post = sides["post"]
    if not pre or not post:
        raise SourceError(f"{project} has a {gap_length}-month gap but lacks pre/post gap commits")
    source_note = "gap-commit CSV"
    if not gap_commits_match_stats(stats_row, pre, post):
        verified = VERIFIED_GAP_BOUNDARIES.get(project)
        if not verified:
            raise SourceError(
                f"{project} gap-commit dates disagree with reported longest gap "
                f"{stats_row.get('LongestGapStart', '?')}–{stats_row.get('LongestGapEnd', '?')}"
            )
        pre = [verified["pre"]]
        post = [verified["post"]]
        if not gap_commits_match_stats(stats_row, pre, post):
            raise SourceError(f"Verified gap boundaries are inconsistent for {project}")
        source_note = "verified GitHub commits (gap-commit CSV dates rejected as inconsistent)"
    examples = [brief_commit(pre[-1]), brief_commit(post[0])]
    if len(post) > 1:
        examples.append(brief_commit(post[1]))
    return (
        f"Longest gap {stats_row.get('LongestGapStart', '?')}–"
        f"{stats_row.get('LongestGapEnd', '?')} ({gap_length} "
        f"{'month' if gap_length == 1 else 'months'}). "
        f"Boundary commits from {source_note}: {'; '.join(examples)}.",
        True,
    )

def github_json(url: str, token: str | None) -> tuple[Any, Any]:
    data, headers = request_bytes(url, token=token)
    try:
        return json.loads(data), headers
    except json.JSONDecodeError as exc:
        raise GitHubError(f"GitHub returned invalid JSON for {url}") from exc

def require_commit_schema(item: Any, repository: str) -> dict[str, str]:
    try:
        sha = item["sha"]
        commit = item["commit"]
        message = commit["message"].splitlines()[0]
        date = commit["committer"]["date"]
        author = (item.get("author") or {}).get("login", "")
    except (KeyError, TypeError, AttributeError) as exc:
        raise GitHubError(f"Unexpected GitHub commit schema for {repository}") from exc
    if not all(isinstance(value, str) for value in (sha, message, date, author)):
        raise GitHubError(f"Unexpected GitHub commit types for {repository}")
    return {"sha": sha, "message": message, "date": date, "author": author}

def fetch_repository_evidence(original_repository: str, token: str | None, review_as_of: dt.date) -> dict[str, Any]:
    repository = canonical_repository(original_repository)
    encoded = quote(repository, safe="/")
    base = f"https://api.github.com/repos/{encoded}/commits"
    status_query = urlencode(
        {"per_page": 1, "until": STATUS_CUTOFF.isoformat().replace("+00:00", "Z")}
    )
    review_until = f"{review_as_of.isoformat()}T23:59:59Z"
    recent_query = urlencode({"per_page": 10, "until": review_until})
    status_payload, _ = github_json(f"{base}?{status_query}", token)
    recent_payload, headers = github_json(f"{base}?{recent_query}", token)
    if not isinstance(status_payload, list) or not status_payload:
        raise GitHubError(f"No commit on or before status cutoff for {repository}")
    if not isinstance(recent_payload, list) or not recent_payload:
        raise GitHubError(f"No recent commits returned for {repository}")
    if len(recent_payload) > 10:
        raise GitHubError(f"GitHub returned more than 10 commits for {repository}")
    status_commit = require_commit_schema(status_payload[0], repository)
    recent_commits = [require_commit_schema(item, repository) for item in recent_payload]
    try:
        cutoff_date = dt.datetime.fromisoformat(
            status_commit["date"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise GitHubError(f"Invalid GitHub commit date for {repository}") from exc
    return {
        "repository": repository,
        "status_commit": status_commit,
        "status": "Active" if cutoff_date >= ACTIVE_SINCE else "Inactive",
        "recent": recent_commits,
        "rate_remaining": headers.get("X-RateLimit-Remaining", "unknown"),
    }

def classify_commit(commit: dict[str, str]) -> str:
    text = f"{commit['message']} {commit.get('author', '')}".casefold()
    author = commit.get("author", "").casefold()
    if author.endswith("[bot]") or "dependabot" in author:
        return "Automated bot contributions"
    if any(word in text for word in ("idor", "security", "authorization", "access validation", "information exposure")):
        return "Security patches"
    if any(word in text for word in ("build(deps)", "dependency", "dependencies", "bump ", "update gems", "pybind")):
        return "Dependency updates"
    if any(word in text for word in ("release", "version bump", "changelog and bump")):
        return "Release"
    if any(word in text for word in ("readme", "documentation", "docs:", "comment", "typo", "doxygen", "manuscript", "publication", "update links")):
        return "Documentation updates"
    if any(word in text for word in ("fix", "bug", "broken", "workaround", "correct", "prevent", "avoid")):
        return "Bug fixes"
    if any(word in text for word in ("feat", "add ", "added ", "implement", "paginate", "new option", "filter")):
        return "Feature development"
    return "Other"

def suggested_themes(commits: list[dict[str, str]]) -> tuple[str, Counter[str]]:
    counts = Counter(classify_commit(commit) for commit in commits)
    order = {label: index for index, label in enumerate(sorted(THEME_LABELS))}
    ranked = sorted(counts, key=lambda label: (-counts[label], order[label.casefold()]))
    while len(ranked) < 2:
        ranked.append("Other")
    return ":".join(ranked[:2]), counts

def truncate_message(message: str, length: int = 88) -> str:
    message = " ".join(message.split())
    return message if len(message) <= length else message[: length - 3] + "..."

def recent_evidence(repository_data: dict[str, Any], review_as_of: dt.date) -> str:
    commits = repository_data["recent"]
    examples = "; ".join(
        f"{commit['date'][:10]} {commit['sha'][:9]} "
        f"{truncate_message(commit['message'])!r}"
        for commit in commits[:3]
    )
    return (
        f"GitHub REST review as of {review_as_of.isoformat()}: "
        f"{len(commits)} most recent commits in {repository_data['repository']}; "
        f"examples: {examples}. https://github.com/"
        f"{repository_data['repository']}/commits"
    )

def reviewed_sha_fingerprint(commits: list[dict[str, str]]) -> str:
    return ",".join(commit["sha"][:12] for commit in commits)

def normalize_recovery(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in ("yes", "no"):
        return normalized
    if "has not" in normalized or "not recovered" in normalized:
        return "no"
    return normalized

def normalize_activity(value: str) -> str:
    return value.strip().casefold().replace("u shaped", "u-shaped")

def normalize_theme_token(value: str) -> str:
    token = value.strip().casefold().replace("bugfixes", "bug fixes").replace("bugfix", "bug fixes")
    if token == "maintenance" or token.startswith("other ("):
        return "other"
    for label in THEME_LABELS:
        if token.startswith(label):
            return label
    return token

def normalize_themes(value: str) -> frozenset[str]:
    text = value.strip().casefold()
    if "bug fixes and documentation updates" in text:
        return frozenset(("bug fixes", "documentation updates"))
    return frozenset(normalize_theme_token(part) for part in text.split(":") if part.strip())

def normalize_recovery_reason(value: str) -> frozenset[str]:
    text = value.strip().casefold()
    if "no true gap" in text:
        return frozenset({"no true gap"})
    if "unknowable" in text or "unknown" in text:
        return frozenset({"unknown"})
    categories = set()
    if "bug" in text:
        categories.add("bug fixes")
    if any(word in text for word in ("documentation", "readme", "docs")):
        categories.add("documentation")
    if any(word in text for word in ("feature", "algorithm", "implementation")):
        categories.add("implementation")
    if any(word in text for word in ("compatibility", "ci", "build")):
        categories.add("compatibility/build")
    if any(word in text for word in ("repository", "synchronization", "sync")):
        categories.add("repository sync")
    if any(word in text for word in ("research", "manuscript", "testing")):
        categories.add("research/testing")
    if any(word in text for word in ("release", "launch")):
        categories.add("release")
    return frozenset(categories or {re.sub(r"[^a-z0-9]+", " ", text).strip()})

def values_agree(field: str, author: str, validator: str) -> bool:
    if field == "HasRecovered":
        return normalize_recovery(author) == normalize_recovery(validator)
    if field == "ActivityPattern":
        return normalize_activity(author) == normalize_activity(validator)
    if field == "WhyRecovered":
        return normalize_recovery_reason(author) == normalize_recovery_reason(validator)
    if field == "RecentThemes":
        return normalize_themes(author) == normalize_themes(validator)
    return author.strip().casefold() == validator.strip().casefold()

def index_stats(stats_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["project"]: row for row in stats_rows}

def project_id_for_row(row: dict[str, str], stats_rows: list[dict[str, str]]) -> str:
    repository_name = repository_from_url(row["WOCProjectID"]).split("/", 1)[1].casefold()
    matches = [
        stats["project"]
        for stats in stats_rows
        if project_repository_name(stats["project"]) == repository_name
    ]
    if len(matches) != 1:
        raise ValueError(f"Cannot map {row['WOCProjectID']} to one partner project")
    return matches[0]

def audit_rows(
    rows: list[dict[str, str]],
    stats_rows: list[dict[str, str]],
    timeseries_dir: str | Path,
    gap_source: str | Path,
    repository_evidence: dict[str, dict[str, Any]],
    review_as_of: dt.date,
    confirm_recent: bool,
) -> list[str]:
    stats_by_project = index_stats(stats_rows)
    gap_rows = load_gap_commits(gap_source)
    activity_evidence = {
        project: activity_summary(load_timeseries(timeseries_dir, project))
        for project in stats_by_project
    }
    uncertainties = []

    for row in rows:
        project = project_id_for_row(row, stats_rows)
        stats = stats_by_project[project]
        repo_data = repository_evidence[row["WOCProjectID"]]
        field = row["Field"]
        if field == "ActivityPattern":
            row["KeyEvidence"] = activity_evidence[project]
            prior = row["Comments"]
            if "[VERIFIED]" in prior:
                row["Comments"] = "[VERIFIED] Independently reviewed monthly commit series."
            elif "[UNCERTAIN]" in prior:
                row["Comments"] = prior
                uncertainties.append(f"{project} ActivityPattern={row['ValidatorValue']}")
            else:
                row["Comments"] = (
                    "[UNCERTAIN] Monthly evidence summarized; preserve this label until "
                    "the validator confirms the qualitative pattern."
                )
                uncertainties.append(f"{project} ActivityPattern={row['ValidatorValue']}")
        elif field in ("HasRecovered", "WhyRecovered"):
            evidence, has_post_gap = gap_evidence(stats, gap_rows)
            row["KeyEvidence"] = evidence
            if field == "HasRecovered":
                expected = "yes" if has_post_gap else "no"
                if normalize_recovery(row["ValidatorValue"]) == expected:
                    row["Comments"] = "[VERIFIED] Based on presence or absence of post-gap commits."
                else:
                    row["Comments"] = (f"[UNCERTAIN] Gap data implies {expected.title()}; validator label preserved.")
                    uncertainties.append(f"{project} HasRecovered={row['ValidatorValue']}")
            elif not has_post_gap and row["ValidatorValue"].strip().casefold() == "no true gap":
                row["Comments"] = "[VERIFIED] No qualifying longest-gap recovery to explain."
            elif row["ValidatorValue"].strip().casefold() == "unknowable with current data":
                row["Comments"] = (
                    "[VERIFIED] Boundary commits do not establish a recovery trigger; "
                    "the conservative label is retained."
                )
            elif (
                row["ValidatorValue"].strip().casefold() == "release"
                and gap_rows.get(project, {}).get("post")
                and "release" in gap_rows[project]["post"][0]["message"].casefold()
            ):
                row["Comments"] = "[VERIFIED] The first post-gap commit explicitly records a release."
            else:
                row["Comments"] = (
                    "[UNCERTAIN] Boundary commits show what resumed, but do not by "
                    "themselves establish why activity resumed."
                )
                uncertainties.append(f"{project} WhyRecovered={row['ValidatorValue']}")
        elif field == "Currentstatus":
            row["ValidatorValue"] = repo_data["status"]
            commit = repo_data["status_commit"]
            row["KeyEvidence"] = (
                f"Fixed course cutoff 2025-09-30: latest commit on/before cutoff is "
                f"{commit['date']} {commit['sha'][:12]} "
                f"{truncate_message(commit['message'])!r}; Active iff dated on/after "
                f"2025-04-01. https://github.com/{repo_data['repository']}/commit/"
                f"{commit['sha']}"
            )
            row["Comments"] = "[VERIFIED] Uses the Coding Guide's historical cutoff."
        elif field == "RecentThemes":
            row["KeyEvidence"] = recent_evidence(repo_data, review_as_of)
            fingerprint = reviewed_sha_fingerprint(repo_data["recent"])
            previous_match = REVIEWED_SHA_RE.search(row["Comments"])
            previous = previous_match.group(1).casefold() if previous_match else None
            suggestion, counts = suggested_themes(repo_data["recent"])
            counts_text = ", ".join(f"{name}={count}" for name, count in counts.most_common())
            if confirm_recent:
                status = "[VERIFIED]"
            elif previous == fingerprint.casefold() and "[VERIFIED]" in row["Comments"]:
                status = "[VERIFIED]"
            elif previous and previous != fingerprint.casefold():
                status = "[STALE]"
                uncertainties.append(f"{project} RecentThemes commit set changed")
            else:
                status = "[UNCERTAIN]"
                uncertainties.append(f"{project} RecentThemes lacks a confirmed SHA set")
            row["Comments"] = (
                f"{status} Recent commits reviewed as of {review_as_of.isoformat()}; "
                f"rule-screen={suggestion} ({counts_text}); qualitative label preserved. "
                f"ReviewedSHAs={fingerprint}"
            )

        row["PreDiscussAgreementstatus(Yes/No)"] = ("Yes" if values_agree(field, row["AuthorValue"], row["ValidatorValue"]) else "No")
    return uncertainties


def validate_theme_value(value: str) -> bool:
    themes = normalize_themes(value)
    return len(themes) == 2 and themes.issubset(THEME_LABELS)

def validate_rows(rows: list[dict[str, str]], stats_rows: list[dict[str, str]]) -> None:
    if len(rows) != 50:
        raise ValueError(f"Expected 50 project-field rows, got {len(rows)}")
    if any(tuple(row) != COLUMNS for row in rows):
        raise ValueError("Rows do not have exactly the expected ten columns")
    projects = [
        next(
            row["WOCProjectID"]
            for row in rows
            if project_id_for_row(row, stats_rows) == stats["project"]
        )
        for stats in stats_rows
    ]
    expected_pairs = {(project, field) for project in projects for field in FIELDS}
    actual_pairs = {(row["WOCProjectID"], row["Field"]) for row in rows}
    if len(actual_pairs) != 50 or actual_pairs != expected_pairs:
        raise ValueError("Expected 50 unique project-field combinations")
    expected_order = [field for field in FIELDS for _ in projects]
    if [row["Field"] for row in rows] != expected_order:
        raise ValueError("Rows must be grouped by the five required fields")

    for row in rows:
        missing = [column for column in REQUIRED_PART1_COLUMNS if not row[column].strip()]
        if missing:
            raise ValueError(
                f"Missing {', '.join(missing)} for {row['WOCProjectID']} / {row['Field']}"
            )
        if row["ProjectOwnerNetID"] != PROJECT_OWNER_NETID:
            raise ValueError("ProjectOwnerNetID must be bslessma in every row")
        if row["ValidatorNetID"] != VALIDATOR_NETID:
            raise ValueError("ValidatorNetID must be asaucer in every row")
        if row["AdjudicatedValue"].strip():
            raise ValueError("Part 1 must leave AdjudicatedValue blank")
        expected_agreement = (
            "Yes"
            if values_agree(row["Field"], row["AuthorValue"], row["ValidatorValue"])
            else "No"
        )
        if row["PreDiscussAgreementstatus(Yes/No)"] != expected_agreement:
            raise ValueError("Agreement status does not match the two labels")
        if row["Field"] == "HasRecovered" and normalize_recovery(row["ValidatorValue"]) not in {"yes", "no"}:
            raise ValueError("Validator HasRecovered must be Yes or No")
        if row["Field"] == "ActivityPattern" and normalize_activity(row["ValidatorValue"]) not in ACTIVITY_LABELS:
            raise ValueError(f"Invalid ActivityPattern {row['ValidatorValue']!r}")
        if row["Field"] == "Currentstatus" and row["ValidatorValue"] not in {"Active", "Inactive"}:
            raise ValueError("Currentstatus must be Active or Inactive")
        if row["Field"] == "RecentThemes" and not validate_theme_value(row["ValidatorValue"]):
            raise ValueError(f"RecentThemes must contain two Coding Guide themes: {row['ValidatorValue']!r}")
            
def write_rows_safely(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=COLUMNS, delimiter=";", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise

def decision_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], str]:
    return {(row["WOCProjectID"], row["Field"]): row["ValidatorValue"] for row in rows}

def print_report(
    rows: list[dict[str, str]],
    baseline_rows: list[dict[str, str]],
    uncertainties: list[str],
) -> None:
    print("Agreement summary by field:")
    for field in FIELDS:
        counts = Counter(
            row["PreDiscussAgreementstatus(Yes/No)"]
            for row in rows
            if row["Field"] == field
        )
        print(f"  {field}: {counts['Yes']} agree, {counts['No']} disagree")
    before = decision_index(baseline_rows)
    changes = [
        (row["WOCProjectID"], row["Field"], before.get((row["WOCProjectID"], row["Field"])), row["ValidatorValue"])
        for row in rows
        if before.get((row["WOCProjectID"], row["Field"])) is None
        or not values_agree(
            row["Field"],
            before[(row["WOCProjectID"], row["Field"])],
            row["ValidatorValue"],
        )
    ]
    print(f"Changed validator decisions: {len(changes)}")
    for project, field, old, new in changes:
        print(f"  {project} / {field}: {old!r} -> {new!r}")
    print(f"Manual-review items: {len(uncertainties)}")
    for item in uncertainties:
        print(f"  {item}")

def parse_review_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-i", "--input", default=DEFAULT_STATS_URL, help="partner project-stats CSV path or raw URL")
    parser.add_argument("-u", "--update", type=Path, default=DEFAULT_UPDATE, help="existing validation CSV with reviewed judgments")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="validated Part 1 output CSV")
    parser.add_argument("--timeseries-dir", default=str(DEFAULT_TIMESERIES_DIR), help="directory or raw GitHub base URL for ten time-series CSVs")
    parser.add_argument("--gap-commits", default=str(DEFAULT_GAP_COMMITS), help="gap-commit CSV path or raw URL")
    parser.add_argument("--review-as-of", type=parse_review_date, default=dt.date.today(), help="recent-commit review date, YYYY-MM-DD")
    parser.add_argument("--confirm-recent", action="store_true", help="record that current recent-commit themes were manually reviewed")
    parser.add_argument("--compare-to", type=Path, help="baseline validation CSV for changed-decision reporting")
    parser.add_argument("--dry-run",  action="store_true", dest="dry_run", help="audit and report without writing output")
    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    baseline_rows = read_validation_rows(args.compare_to or args.update)
    judgment_rows = read_validation_rows(args.update)
    stats_rows = read_partner_stats(args.input)
    rows = combine_stats_and_judgments(stats_rows, judgment_rows)
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    repository_evidence = {}
    for row in rows:
        url = row["WOCProjectID"]
        if url not in repository_evidence:
            repository_evidence[url] = fetch_repository_evidence(repository_from_url(url), token, args.review_as_of)
    uncertainties = audit_rows(
        rows,
        stats_rows,
        args.timeseries_dir,
        args.gap_commits,
        repository_evidence,
        args.review_as_of,
        args.confirm_recent,
    )
    validate_rows(rows, stats_rows)
    print_report(rows, baseline_rows, uncertainties)
    if args.dry_run:
        print("DRY RUN: output CSV was not changed")
    else:
        write_rows_safely(args.output, rows)
        print(f"Wrote validated Part 1 CSV: {args.output}")
    print(f"Recent-commit review date: {args.review_as_of.isoformat()}")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SourceError, GitHubError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
