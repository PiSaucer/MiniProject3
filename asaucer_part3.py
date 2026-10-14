#!/usr/bin/env python3
# asaucer_part3.py
# Part 3 validation statistics and reflection

import argparse
import csv
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

FIELDS = ["HasRecovered", "WhyRecovered", "ActivityPattern", "Currentstatus", "RecentThemes"]
KAPPA_FIELDS = {"HasRecovered", "ActivityPattern", "Currentstatus"}
STATS_HEADER = ["Field", "PercentAgree_Pre", "PercentAgree_Post", "CohenKappa_Pre", "CohenKappa_Post", "NumDisagreements", "NumResolved", "MeanResolutionTime_min", "Notes"]
LOG_COLUMNS = {"WOCProjectID", "ProjectOwnerNetID", "ValidatorNetID", "Field", "AuthorValue", "ValidatorValue", "PreDiscussAgreementstatus(Yes/No)", "AdjudicatedValue", "KeyEvidence", "Comments"}
RES_COLUMNS = {"WOCProjectID", "ProjectOwnerNetID", "ValidatorNetID", "Field", "AuthorValue", "ValidatorValue", "AdjudicatedValue", "ResolutionType", "PostDiscussAgreementstatus(Yes/No)", "KeyEvidence", "Comments"}

class InputError(Exception):
    pass

@dataclass(frozen=True)
class Record:
    values: dict[str, str]

    @property
    def key(self):
        return (self.values["WOCProjectID"].strip(), self.values["Field"].strip())

def clean(value: str | None) -> str:
    return "" if value is None else " ".join(value.strip().split())

def norm(value: str | None) -> str:
    return clean(value).casefold()

def discover(root: Path, filename: str) -> Path:
    candidates = sorted(p for p in root.rglob(filename) if p.is_file() and "README.md" not in p.name)
    preferred = [p for p in candidates if p.name.startswith("asaucer_")]
    direct = root / filename
    if direct.is_file() and direct in preferred:
        return direct
    if len(preferred) != 1:
        raise InputError(f"expected exactly one asaucer {filename}, found: {', '.join(map(str, preferred or candidates))}")
    return preferred[0]

def read_csv(path: Path, required: set[str], delimiter: str = ";") -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if not reader.fieldnames:
                raise InputError(f"{path}: missing header")
            missing = required - set(reader.fieldnames)
            if missing:
                raise InputError(f"{path}: missing required columns: {', '.join(sorted(missing))}")
            rows = []
            for number, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise InputError(f"{path}:{number}: malformed record or inconsistent column count")
                rows.append({key: clean(value) for key, value in row.items()})
            return rows
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc

def validate_records(rows: list[dict[str, str]], path: Path, resolution: bool = False) -> list[Record]:
    allowed = set(FIELDS)
    records = [Record(row) for row in rows]
    seen: set[tuple[str, str]] = set()
    errors: list[str] = []
    for index, record in enumerate(records, 2):
        row = record.values
        if not row["WOCProjectID"] or not row["Field"] or row["Field"] not in allowed:
            errors.append(f"{path}:{index}: invalid project or field {row['WOCProjectID']!r}/{row['Field']!r}")
        if record.key in seen:
            errors.append(f"{path}:{index}: duplicate project-field combination {record.key}")
        seen.add(record.key)
        if not resolution and norm(row["PreDiscussAgreementstatus(Yes/No)"]) not in {"yes", "no"}:
            errors.append(f"{path}:{index}: invalid pre-discussion status")
        if resolution and norm(row["PostDiscussAgreementstatus(Yes/No)"]) not in {"yes", "no"}:
            errors.append(f"{path}:{index}: invalid post-discussion status")
    if errors:
        raise InputError("\n".join(errors))
    return records

def agreement(a: list[str], b: list[str]) -> float:
    return 100.0 * sum(norm(x) == norm(y) for x, y in zip(a, b)) / len(a) if a else math.nan

def kappa(a: list[str], b: list[str]) -> float:
    pairs = list(zip(map(norm, a), map(norm, b)))
    if not pairs:
        return math.nan
    po = sum(x == y for x, y in pairs) / len(pairs)
    left, right = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum(left[label] * right[label] for label in set(left) | set(right)) / (len(pairs) ** 2)
    return 1.0 if po == pe == 1.0 else ((po - pe) / (1.0 - pe) if pe != 1.0 else 0.0)

def fmt(value: float | int | str, decimals: int = 6) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    return "NA" if math.isnan(value) else f"{value:.{decimals}f}"

def load_inputs(root: Path):
    log_path = discover(root, "asaucer_validation_log.csv")
    res_path = discover(root, "asaucer_disagreement_resolution.csv")
    log = validate_records(read_csv(log_path, LOG_COLUMNS), log_path)
    resolutions = validate_records(read_csv(res_path, RES_COLUMNS), res_path, resolution=True)
    log_map = {r.key: r for r in log}
    res_map = {r.key: r for r in resolutions}
    if len(log) != 50 or set(log_map) != {(p, f) for p in {r.key[0] for r in log} for f in FIELDS}:
        raise InputError(f"{log_path}: expected a complete 10-project by 5-field validation matrix")
    unresolved = [r.key for r in log if norm(r.values["PreDiscussAgreementstatus(Yes/No)"]) == "no" and r.key not in res_map]
    extra = sorted(set(res_map) - set(log_map))
    if unresolved or extra:
        raise InputError(f"unresolved disagreements: {unresolved}; resolutions without log records: {extra}")
    return log, resolutions, log_path, res_path

def load_gap_evidence(root: Path) -> list[dict[str, str]]:
    paths = sorted(root.rglob("bslessma_project_gap_commits.csv"))
    if not paths:
        raise InputError("could not discover MiniProject2 bslessma_project_gap_commits.csv")
    rows = read_csv(paths[0], {"pre/post", "project", "commit", "time", "message"}, delimiter=",")
    return rows

def make_stats(log: list[Record], resolutions: list[Record]) -> list[list[str]]:
    by_field = {field: sorted((r for r in log if r.values["Field"] == field), key=lambda r: r.key) for field in FIELDS}
    res_map = {r.key: r for r in resolutions}
    output = []
    for field in FIELDS:
        records = by_field[field]
        authors = [r.values["AuthorValue"] for r in records]
        validators = [r.values["ValidatorValue"] for r in records]
        disagreements = [r for r in records if norm(r.values["PreDiscussAgreementstatus(Yes/No)"]) == "no"]
        post_a, post_b = [], []
        for r in records:
            if r.key in res_map:
                value = res_map[r.key].values["AdjudicatedValue"]
                post_a.append(value); post_b.append(value)
            else:
                post_a.append(r.values["AuthorValue"]); post_b.append(r.values["ValidatorValue"])
        notes = "Consensus-based post kappa; disagreements use adjudicated value for both ratings." if field in KAPPA_FIELDS else "Kappa not applicable for this qualitative field."
        output.append([field, fmt(agreement(authors, validators), 1), fmt(agreement(post_a, post_b), 1), fmt(kappa(authors, validators)) if field in KAPPA_FIELDS else "NA", fmt(kappa(post_a, post_b)) if field in KAPPA_FIELDS else "NA", str(len(disagreements)), str(sum(r.key in res_map for r in disagreements)), "NA", notes])
    return output

def write_stats(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(STATS_HEADER); writer.writerows(rows)

def make_reflection(log: list[Record], resolutions: list[Record], gaps: list[dict[str, str]], stats: list[list[str]]) -> str:
    res_map = {r.key: r for r in resolutions}
    projects = sorted({r.key[0] for r in log})
    disagreement_lines = []
    for field, pre, post, kp, kpost, nd, nr, _, _ in stats:
        disagreement_lines.append(f"- **{field}:** pre-discussion agreement {pre}% and post-discussion agreement {post}%; {nd} disagreement(s), {nr} resolved.")
    gap_groups = defaultdict(list)
    for row in gaps:
        gap_groups[row["project"]].append(row)
    gap_examples = []
    for project in sorted(gap_groups):
        rows = gap_groups[project]
        pre = [r for r in rows if norm(r["pre/post"]) == "pre"]
        post = [r for r in rows if norm(r["pre/post"]) == "post"]
        if pre and post:
            gap_examples.append(f"- `{project}`: preceding work included {clean(pre[0]['message'])!r}; subsequent work included {clean(post[0]['message'])!r}.")
    resolved = [r for r in log if norm(r.values["PreDiscussAgreementstatus(Yes/No)"]) == "no" and r.key in res_map]
    resolution_lines = [f"- `{r.key[0]}` — {r.key[1]}: adjudicated as {res_map[r.key].values['AdjudicatedValue']!r} ({res_map[r.key].values['ResolutionType']})." for r in sorted(resolved, key=lambda x: x.key)]
    pre_values = [(row[0], float(row[1])) for row in stats]
    highest = max(pre_values, key=lambda item: (item[1], item[0]))
    lowest = min(pre_values, key=lambda item: (item[1], item[0]))
    return "\n".join([
        "# Part 3 Validation Reflection", "", f"This reflection was generated from {len(projects)} projects and five validated fields; records and examples are sorted deterministically.", "",
        "## Agreement findings", "", *disagreement_lines, "", f"The highest pre-discussion agreement was {highest[1]:.1f}% for {highest[0]}; the lowest was {lowest[1]:.1f}% for {lowest[0]}.", "", "Post-discussion kappa is consensus-based: when a disagreement was resolved, the adjudicated value is assigned to both paired ratings. It therefore describes agreement after adjudication, not independent inter-rater reliability.", "",
        "## Differences among validated fields", "", "The five fields differ in both disagreement frequency and measurement type. HasRecovered, ActivityPattern, and Currentstatus have calculated kappa values; WhyRecovered and RecentThemes are reported with `NA` because their open-text/qualitative labels do not support the requested categorical kappa interpretation.", "",
        "## Patterns preceding long gaps and evidence of recovery", "", *(gap_examples or ["No paired pre/post gap evidence was available."]), "", "The gap records show activity before and after documented long gaps, but commit messages establish what work resumed, not the developers' private reason for returning. These post-gap records are the available evidence of recovery; no stronger causal claim is made.", "",
        "## Why inactivity does not necessarily mean abandonment", "", "The validation records contain projects with later commits after inactivity intervals, including bug fixes, compatibility work, algorithm changes, releases, and documentation or manuscript work. Thus an inactive interval can precede resumed activity. The records do not establish off-repository work or intent during the interval.", "",
        "## Recurring disagreements and evidence-based resolutions", "", *(resolution_lines or ["No disagreements were recorded."]), "", "Resolutions are included only where the resolution CSV supplies an adjudicated value and post-discussion agreement. The evidence fields and comments provide the basis for these outcomes.", "",
    ])

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate reproducible Part 3 agreement statistics and reflection.", epilog="Required inputs: asaucer_validation_log.csv, asaucer_disagreement_resolution.csv, and Miniproject2/bslessma_project_gap_commits.csv. Outputs: asaucer_agreement_stats.csv and asaucer_validation_reflection.md.")
    parser.add_argument("--input-dir", type=Path, default=Path("."), help="repository root containing Part 3 inputs")
    parser.add_argument("--output-dir", type=Path, default=Path("."), help="directory for generated deliverables")
    parser.add_argument("--validate-only", action="store_true", help="validate inputs without writing output files")
    parser.add_argument("--verbose", action="store_true", help="print counts, disagreement status, and statistics")
    args = parser.parse_args(argv)
    try:
        root = args.input_dir.resolve(); log, resolutions, _, _ = load_inputs(root); gaps = load_gap_evidence(root); stats = make_stats(log, resolutions)
        for row in stats:
            print(f"{row[0]}: pre_agreement={row[1]}% post_agreement={row[2]}% kappa_pre={row[3]} kappa_post={row[4]} disagreements={row[5]} resolved={row[6]} mean_resolution_min={row[7]}")
        if args.verbose:
            print(f"Validated {len(log)} records, {len(resolutions)} resolution records, and {len(gaps)} gap-evidence records.")
        if not args.validate_only:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            write_stats(args.output_dir / "asaucer_agreement_stats.csv", stats)
            (args.output_dir / "asaucer_validation_reflection.md").write_text(make_reflection(log, resolutions, gaps, stats), encoding="utf-8")
        elif args.verbose:
            print("Validation successful; no output files written.")
        return 0
    except InputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 1

if __name__ == "__main__":
    raise SystemExit(main())
