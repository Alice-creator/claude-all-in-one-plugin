#!/usr/bin/env python3
"""Validate a competition.json (the per-competition fact sheet) and list what is still unknown.

A field set to null means "not yet confirmed from the rules page" — it is an open question,
never a default. Required fields must be filled before any modeling starts; the rest are
reported as open questions so nothing about the rules is silently assumed.

Writes competition_check.json (machine-readable sidecar) next to competition.json.

Exit codes: 0 ok · 1 required fields missing · 3 bad/missing json.

NOTE: helpers here are deliberately self-contained (helpers are copied byte-identical
across scripts rather than importing a shared module).
"""
import argparse
import datetime
import json
import os
import sys

PLATFORMS = {"kaggle", "drivendata", "aicrowd", "zindi", "codalab", "huggingface", "other"}
TRACKS = {"tabular": "model-builder", "game-agent": "game-agent-builder",
          "cv-detection": "cv-modeler", "other": None}
DIRECTIONS = {"maximize", "minimize"}

# (dotted path, why it must be known before modeling)
REQUIRED_FIELDS = [
    ("name", "names every artifact"),
    ("platform", "decides the submission mechanics"),
    ("track", "routes to the right pipeline"),
    ("metric.name", "every experiment is scored with it"),
    ("metric.direction", "decides what 'better' means"),
    ("deadlines.final_submission", "bounds the whole plan"),
    ("rules.rules_accepted", "you cannot submit before accepting the rules"),
    ("validation.scheme", "the local CV must mirror how the test set was split"),
]

# (dotted path, what goes wrong if it is assumed instead of checked)
OPEN_QUESTION_FIELDS = [
    ("rules.external_data_allowed", "using external data where it is banned disqualifies the team"),
    ("rules.pretrained_models_allowed", "same risk as external data"),
    ("rules.team_size_max", "team mergers past the limit are refused"),
    ("submission.daily_limit", "the submission budget cannot be planned"),
    ("submission.final_selection_count", "how many final submissions count toward the private leaderboard"),
    ("submission.code_competition", "code competitions run your notebook offline under a runtime limit"),
    ("submission.runtime_limit_hours", "an over-limit notebook scores nothing"),
    ("submission.internet_allowed", "a notebook that downloads weights fails when internet is off"),
    ("submission.format_file", "check-submission needs the sample/format file"),
    ("leaderboard.public_fraction", "how much the public leaderboard can mislead (shake-up risk)"),
    ("validation.mirrors_test_because", "a scheme without a reason is a guess"),
]


def die(msg, code):
    print(msg, file=sys.stderr)
    sys.exit(code)


def lookup(document, dotted_path):
    value = document
    for key in dotted_path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def is_unknown(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--competition", default="competition.json")
    arguments = parser.parse_args()

    if not os.path.exists(arguments.competition):
        die(f"not found: {arguments.competition} — copy the template's competition.json first", 3)
    try:
        with open(arguments.competition) as handle:
            competition = json.load(handle)
    except Exception as error:
        die(f"could not parse {arguments.competition}: {error}", 3)

    missing_required = [(path, reason) for path, reason in REQUIRED_FIELDS
                        if is_unknown(lookup(competition, path))]
    if lookup(competition, "rules.rules_accepted") is False:
        missing_required.append(("rules.rules_accepted", "is false — accept the rules on the platform first"))
    open_questions = [(path, reason) for path, reason in OPEN_QUESTION_FIELDS
                      if is_unknown(lookup(competition, path))]

    problems = []
    platform = lookup(competition, "platform")
    if platform and platform not in PLATFORMS:
        problems.append(f"platform '{platform}' not in {sorted(PLATFORMS)} — use 'other' and describe it in notes")
    track = lookup(competition, "track")
    if track and track not in TRACKS:
        problems.append(f"track '{track}' not in {sorted(TRACKS)}")
    direction = lookup(competition, "metric.direction")
    if direction and direction not in DIRECTIONS:
        problems.append(f"metric.direction '{direction}' must be one of {sorted(DIRECTIONS)}")

    days_left = None
    deadline_text = lookup(competition, "deadlines.final_submission")
    if deadline_text:
        try:
            deadline = datetime.date.fromisoformat(str(deadline_text)[:10])
            days_left = (deadline - datetime.date.today()).days
        except ValueError:
            problems.append(f"deadlines.final_submission '{deadline_text}' is not YYYY-MM-DD")

    format_file = lookup(competition, "submission.format_file")
    if format_file:
        base_directory = os.path.dirname(os.path.abspath(arguments.competition))
        if not os.path.exists(os.path.join(base_directory, format_file)):
            problems.append(f"submission.format_file '{format_file}' does not exist yet (download it into data/raw/)")

    status = "READY" if not missing_required and not problems else "INCOMPLETE"
    summary = {
        "status": status,
        "name": lookup(competition, "name"),
        "platform": platform,
        "track": track,
        "pipeline_agent": TRACKS.get(track),
        "metric": lookup(competition, "metric"),
        "days_left": days_left,
        "missing_required": [path for path, _ in missing_required],
        "open_questions": [path for path, _ in open_questions],
        "problems": problems,
        "checked_on": datetime.date.today().isoformat(),
    }
    sidecar_path = os.path.join(os.path.dirname(os.path.abspath(arguments.competition)), "competition_check.json")
    with open(sidecar_path, "w") as handle:
        json.dump(summary, handle, indent=2)

    print(f"status: {status}")
    if days_left is not None:
        print(f"days left to final submission: {days_left}" + ("  ⚠ under 7 days" if days_left < 7 else ""))
    for path, reason in missing_required:
        print(f"  ✗ required: {path} — {reason}")
    for problem in problems:
        print(f"  ✗ {problem}")
    for path, reason in open_questions:
        print(f"  ? open: {path} — {reason}")
    if track in TRACKS and TRACKS[track]:
        print(f"pipeline: {TRACKS[track]}")
    print(f"wrote {sidecar_path}")
    sys.exit(0 if status == "READY" else 1)


if __name__ == "__main__":
    main()
