#!/usr/bin/env python3
"""Parse and bind user approval receipts without performing promotion."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import sublation_run


ACTION_TERMS = {
    "pending": ("withdraw", "撤回", "取消决定", "取消"),
    "hold": ("hold", "暂缓", "搁置", "保留"),
    "reject": ("do not approve", "not approve", "reject", "不同意", "不批准", "不准", "驳回", "拒绝"),
    "approve": ("approve", "批准", "同意", "通过", "准"),
}
MODIFIED_ZH_ACTIONS = ("批准", "同意", "通过")
REJECT_ZH_MODIFIERS = (
    "不同意",
    "不打算",
    "请勿",
    "切勿",
    "不要",
    "不予",
    "尚未",
    "没有",
    "无法",
    "不能",
    "不可",
    "禁止",
    "拒绝",
    "无需",
    "无须",
    "不会",
    "无意",
    "勿",
    "别",
    "莫",
    "未",
    "不",
)
HOLD_ZH_MODIFIERS = (
    "请先不要",
    "请先别",
    "暂时不要",
    "暂时不",
    "先不要",
    "以后再",
    "先不",
    "先别",
    "暂缓",
    "暂不",
    "搁置",
    "保留",
    "待定",
    "延后",
    "推迟",
    "稍后",
)


def regex_terms(values: tuple[str, ...]) -> str:
    return "|".join(re.escape(value) for value in sorted(values, key=len, reverse=True))


ZH_ACTION_SOURCE = regex_terms(MODIFIED_ZH_ACTIONS)
REJECT_ACTION_SOURCE = (
    r"(?:(?:"
    + regex_terms(REJECT_ZH_MODIFIERS)
    + rf")\s*(?:{ZH_ACTION_SOURCE})"
    + r"|do\s+not\s+approve|don't\s+approve|not\s+approve(?:d)?|cannot\s+approve|can't\s+approve|unable\s+to\s+approve|never\s+approve)"
)
HOLD_ACTION_SOURCE = (
    r"(?:(?:"
    + regex_terms(HOLD_ZH_MODIFIERS)
    + rf")\s*(?:{ZH_ACTION_SOURCE})"
    + r"|(?:hold|defer|delay)\s+(?:approval|approve)|not\s+yet\s+approve(?:d)?|approve\s+later)"
)
MODIFIED_ACTION_SOURCE = rf"(?:{HOLD_ACTION_SOURCE}|{REJECT_ACTION_SOURCE})"
REJECT_ACTION_PATTERN = re.compile(REJECT_ACTION_SOURCE, re.IGNORECASE)
HOLD_ACTION_PATTERN = re.compile(HOLD_ACTION_SOURCE, re.IGNORECASE)
GENERIC_REJECT_CONTEXT_PATTERN = re.compile(
    r"(?:不|未|勿|别|莫|禁|拒|否|反对|无法|不能|不可|尚未|没有|没法|无需|无须"
    r"|\b(?:do\s+not|don't|never|not|cannot|can't|unable|refuse|avoid)\b)",
    re.IGNORECASE,
)
GENERIC_HOLD_CONTEXT_PATTERN = re.compile(
    r"(?:暂|缓|待定|延后|延迟|推迟|稍后|以后再|改日|择日|先(?:不|别|暂)"
    r"|\b(?:not\s+yet|later|defer|delay|hold|wait(?:ing)?\s+to)\b)",
    re.IGNORECASE,
)
ALL_TERMS = ("全部", "全体", "所有", "all")
TRANSLATION = str.maketrans(
    {
        "，": ",",
        "、": ",",
        "；": ";",
        "。": ";",
        "：": ":",
        "（": "(",
        "）": ")",
        "Ａ": "A",
    }
)


def normalize(text: str) -> str:
    normalized = text.translate(TRANSLATION).strip().casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def action_pattern() -> re.Pattern[str]:
    terms = sorted((term for values in ACTION_TERMS.values() for term in values), key=len, reverse=True)
    literal_source = "|".join(re.escape(term.casefold()) for term in terms)
    return re.compile(f"{MODIFIED_ACTION_SOURCE}|{literal_source}", re.IGNORECASE)


ACTION_PATTERN = action_pattern()
ITEM_PATTERN = re.compile(r"(?<![A-Za-z0-9])A\s*\d+(?!\d)", re.IGNORECASE)


def action_for_term(term: str) -> str:
    folded = term.casefold()
    if HOLD_ACTION_PATTERN.fullmatch(folded):
        return "hold"
    if REJECT_ACTION_PATTERN.fullmatch(folded):
        return "reject"
    for action, terms in ACTION_TERMS.items():
        if folded in {item.casefold() for item in terms}:
            return action
    raise ValueError(f"unknown decision term: {term}")


def contextual_action(text: str, term: str, start: int) -> str:
    action = action_for_term(term)
    if action != "approve":
        return action
    prefix = text[max(0, start - 24) : start]
    prior_items = list(ITEM_PATTERN.finditer(prefix))
    if prior_items:
        prefix = prefix[prior_items[-1].end() :]
    if GENERIC_HOLD_CONTEXT_PATTERN.search(prefix):
        return "hold"
    if GENERIC_REJECT_CONTEXT_PATTERN.search(prefix):
        return "reject"
    return action


def action_for_match(text: str, match: re.Match[str]) -> str:
    return contextual_action(text, match.group(0), match.start())


def detect_all_action(text: str) -> str | None:
    all_pattern = "(?:" + "|".join(re.escape(term) for term in ALL_TERMS) + ")"
    action_source = ACTION_PATTERN.pattern
    patterns = (
        re.compile(rf"{all_pattern}\s*(?:都\s*)?({action_source})", re.IGNORECASE),
        re.compile(rf"({action_source})\s*{all_pattern}", re.IGNORECASE),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            term = match.group(1)
            if term and ACTION_PATTERN.fullmatch(term):
                return contextual_action(text, term, match.start(1))
    if not ITEM_PATTERN.search(text) and re.search(all_pattern, text, flags=re.IGNORECASE):
        actions = {action_for_match(text, match) for match in ACTION_PATTERN.finditer(text)}
        if len(actions) == 1:
            return next(iter(actions))
        if len(actions) > 1:
            raise ValueError("ambiguous all-item decision; use one explicit action")
    return None


def parse_decisions(message: str, item_ids: list[str]) -> dict[str, str]:
    text = normalize(message)
    if re.search(r"(?:除了|除\s*A\s*\d+\s*之外|except)", text, flags=re.IGNORECASE):
        raise ValueError("exclusion syntax is unsupported; use '全部批准' or list each A item explicitly")
    allowed = {item.upper() for item in item_ids}
    mentioned = {match.upper() for match in ITEM_PATTERN.findall(text)}
    mentioned = {re.sub(r"\s+", "", item) for item in mentioned}
    unknown = sorted(mentioned - allowed)
    if unknown:
        raise ValueError("receipt references unknown item ids: " + ", ".join(unknown))

    decisions: dict[str, str] = {}
    all_action = detect_all_action(text)
    if all_action:
        decisions.update({item_id: all_action for item_id in allowed})

    # A semicolon starts a new decision group. Comma-only fragments may inherit
    # one unambiguous action, which preserves forms such as "批准 A1, A3".
    for group in re.split(r"[;\n]+", text):
        clauses = [clause.strip() for clause in group.split(",") if clause.strip()]
        clause_actions: list[str | None] = []
        for clause in clauses:
            actions = {action_for_match(clause, match) for match in ACTION_PATTERN.finditer(clause)}
            clause_actions.append(next(iter(actions)) if len(actions) == 1 else None)

        for index, clause in enumerate(clauses):
            id_matches = list(ITEM_PATTERN.finditer(clause))
            ids = [re.sub(r"\s+", "", match.group(0).upper()) for match in id_matches]
            if not ids:
                continue
            action_matches = list(ACTION_PATTERN.finditer(clause))
            distinct_actions = {action_for_match(clause, match) for match in action_matches}
            if not action_matches:
                previous = next(
                    (clause_actions[pos] for pos in range(index - 1, -1, -1) if clause_actions[pos]),
                    None,
                )
                following = next(
                    (clause_actions[pos] for pos in range(index + 1, len(clauses)) if clause_actions[pos]),
                    None,
                )
                inherited = {action for action in (previous, following) if action}
                if len(inherited) > 1:
                    raise ValueError(f"ambiguous inherited decision near: {clause}")
                if not inherited:
                    continue
                action = next(iter(inherited))
                for item_id in ids:
                    decisions[item_id] = action
                continue
            if len(distinct_actions) == 1:
                action = next(iter(distinct_actions))
                for item_id in ids:
                    decisions[item_id] = action
                continue
            for item_match, item_id in zip(id_matches, ids):
                distances = [
                    (
                        min(
                            abs(item_match.start() - action_match.end()),
                            abs(action_match.start() - item_match.end()),
                        ),
                        action_for_match(clause, action_match),
                    )
                    for action_match in action_matches
                ]
                nearest_distance = min(distance for distance, _action in distances)
                nearest_actions = {action for distance, action in distances if distance == nearest_distance}
                if len(nearest_actions) != 1:
                    raise ValueError(f"ambiguous decision near {item_id}; split it into explicit clauses")
                decisions[item_id] = next(iter(nearest_actions))

    if not decisions:
        raise ValueError("no deterministic approval decision found in receipt")
    return decisions


def load_latest_report(run_dir: Path, run: dict[str, Any]) -> dict[str, Any]:
    latest = run.get("latest_report")
    if not isinstance(latest, dict):
        raise ValueError("run has no finalized report")
    version = int(latest["report_version"])
    report = sublation_run.read_json(run_dir / f"report-v{version}.json")
    sublation_run.verify_plain_report(run_dir, report)
    return report


def matching_delivery(
    report: dict[str, Any], channel: str, in_reply_to: str, sender_id: str
) -> dict[str, Any] | None:
    deliveries = report.get("delivery")
    if not isinstance(deliveries, list):
        return None
    for delivery in deliveries:
        if not isinstance(delivery, dict) or delivery.get("channel") != channel:
            continue
        if delivery.get("message_ref") == in_reply_to:
            allowed = delivery.get("authorized_reply_senders")
            if isinstance(allowed, list) and sender_id in allowed:
                return delivery
    return None


def delivery_matches(report: dict[str, Any], channel: str, in_reply_to: str, sender_id: str) -> bool:
    return matching_delivery(report, channel, in_reply_to, sender_id) is not None


def empty_approval(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": report["run_id"],
        "report_version": report["report_version"],
        "report_hash": report["report_hash"],
        "report_body_hash": report["plain_report_sha256"],
        "scope_revision": report["scope_revision"],
        "state": "USER_DECISION_REQUIRED",
        "decisions": {
            item["item_id"]: {
                "decision": "pending",
                "updated_at": None,
                "event_id": None,
                "execution": "not_authorized",
            }
            for item in report.get("approval_items", [])
        },
        "events": [],
        "authorized_scope": [],
        "boundary": "Receipt parsing never executes promotion or formal writes.",
    }


def validate_cached_approval(report: dict[str, Any], approval: dict[str, Any]) -> None:
    if approval.get("report_body_hash") != report.get("plain_report_sha256"):
        raise ValueError("approval cache report_body_hash differs from the report delivery snapshot")
    item_ids = [str(item["item_id"]) for item in report.get("approval_items", [])]
    replay = {item_id: {"decision": "pending", "event_id": None} for item_id in item_ids}
    events = approval.get("events")
    if not isinstance(events, list):
        raise ValueError("approval cache events must be an array")
    seen: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("approval cache contains a malformed event")
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in seen:
            raise ValueError("approval cache event ids must be unique")
        seen.add(event_id)
        if event.get("report_body_hash") != report.get("plain_report_sha256"):
            raise ValueError(f"approval cache event report_body_hash drifted: {event_id}")
        parsed = parse_decisions(str(event.get("message") or ""), item_ids)
        if event.get("parsed") != parsed:
            raise ValueError(f"approval cache parsed decisions drifted: {event_id}")
        for item_id, decision in parsed.items():
            replay[item_id] = {"decision": decision, "event_id": event_id}
    decisions = approval.get("decisions")
    if not isinstance(decisions, dict) or set(decisions) != set(item_ids):
        raise ValueError("approval cache decision set differs from the report")
    for item_id, expected in replay.items():
        actual = decisions[item_id]
        if not isinstance(actual, dict) or any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError(f"approval cache decision cannot be replayed: {item_id}")
    authorized_scope = sorted(item_id for item_id, value in replay.items() if value["decision"] == "approve")
    if approval.get("authorized_scope") != authorized_scope:
        raise ValueError("approval cache authorized_scope cannot be replayed")
    values = [value["decision"] for value in replay.values()]
    expected_state = (
        "APPROVED_PENDING_EXECUTION"
        if "approve" in values
        else "USER_REJECTED"
        if values and all(value == "reject" for value in values)
        else "USER_DECISION_REQUIRED"
    )
    if approval.get("state") != expected_state:
        raise ValueError("approval cache state cannot be replayed")


def receipt_journal_payload(
    *,
    event_id: str,
    event_signature: str,
    channel: str,
    sender_id: str,
    in_reply_to: str,
    report: dict[str, Any],
    report_body_hash: str,
    decisions: dict[str, str],
    resulting_state: str,
    authorized_scope: list[str],
    receipt_evidence: dict[str, str],
    adapter_id: str,
    source_event_hash: str,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_signature": event_signature,
        "channel": channel,
        "sender_id": sender_id,
        "in_reply_to": in_reply_to,
        "report_version": report["report_version"],
        "report_hash": report["report_hash"],
        "report_body_hash": report_body_hash,
        "scope_revision": report["scope_revision"],
        "decisions": decisions,
        "resulting_state": resulting_state,
        "authorized_scope": authorized_scope,
        "receipt_evidence": receipt_evidence,
        "adapter_id": adapter_id,
        "source_event_hash": source_event_hash,
        "boundary": "No promotion executed.",
    }


def apply_receipt(
    run_dir: Path,
    *,
    receipt_evidence_path: str | Path,
    report_version: int | None = None,
    expected_report_hash: str | None = None,
    scope_revision: int | None = None,
) -> dict[str, Any]:
    evidence, evidence_record = sublation_run.verify_receipt_attestation(
        run_dir, Path(receipt_evidence_path)
    )
    message = str(evidence.get("message") or "")
    channel = str(evidence.get("channel") or "")
    sender_id = str(evidence.get("sender_id") or "")
    event_id = str(evidence.get("event_id") or "")
    in_reply_to = str(evidence.get("in_reply_to") or "")
    adapter_id = str(evidence.get("adapter_id") or "")
    source_event_hash = str(evidence.get("source_event_hash") or "")
    report_body_hash = str(evidence.get("report_body_hash") or "")
    if not all(value.strip() for value in (message, channel, sender_id, event_id, in_reply_to, adapter_id, source_event_hash)):
        raise ValueError("attested receipt is missing a required identity field")
    if not report_body_hash.strip():
        raise ValueError("attested receipt is missing required report_body_hash")
    with sublation_run.locked_run(run_dir):
        run = sublation_run.load_run(run_dir)
        report = load_latest_report(run_dir, run)
        if report_version is not None and report_version != report["report_version"]:
            raise ValueError("stale report version; receipt rejected")
        if expected_report_hash is not None and expected_report_hash != report["report_hash"]:
            raise ValueError("stale report hash; receipt rejected")
        if scope_revision is not None and scope_revision != report["scope_revision"]:
            raise ValueError("stale scope revision; receipt rejected")
        for field in ("report_version", "report_hash", "scope_revision", "approval_code"):
            if evidence.get(field) != report[field]:
                raise ValueError(f"attested receipt is stale for latest {field}")
        delivery = matching_delivery(report, channel, in_reply_to, sender_id)
        if delivery is None:
            raise ValueError("receipt channel/reply/sender binding does not match latest report delivery")
        if report_body_hash != report.get("plain_report_sha256"):
            raise ValueError("attested receipt report_body_hash differs from the latest report body")
        if report_body_hash != delivery.get("report_body_hash"):
            raise ValueError("attested receipt report_body_hash differs from the matched report delivery")
        item_ids = [item["item_id"] for item in report.get("approval_items", [])]
        if not item_ids:
            raise ValueError("latest report has no approval items")

        parsed = parse_decisions(message, item_ids)
        event_signature = str(evidence["attestation_mac"])
        approval_path = run_dir / "approval.json"
        if approval_path.exists():
            approval = sublation_run.read_json(approval_path)
            if approval.get("report_hash") != report["report_hash"]:
                approval = empty_approval(report)
            elif approval.get("report_body_hash") != report_body_hash:
                raise ValueError("approval cache report_body_hash differs from the attested report delivery")
        else:
            approval = empty_approval(report)

        for event in approval.get("events", []):
            if event.get("event_id") != event_id:
                continue
            if event.get("event_signature") != event_signature:
                raise ValueError(f"event id collision with different receipt: {event_id}")
            expected_event_fields = {
                "channel": channel,
                "sender_id": sender_id,
                "in_reply_to": in_reply_to,
                "message": message,
                "parsed": parsed,
                "report_body_hash": report_body_hash,
                "receipt_evidence": evidence_record,
                "adapter_id": adapter_id,
                "source_event_hash": source_event_hash,
            }
            if any(event.get(key) != value for key, value in expected_event_fields.items()):
                raise ValueError(f"approval cache event fields drifted: {event_id}")
            validate_cached_approval(report, approval)
            recorded_entries = [
                entry.get("payload", {})
                for entry in sublation_run.verified_journal_entries(run_dir)
                if entry.get("type") == "approval_receipt_recorded"
                and entry.get("payload", {}).get("event_id") == event_id
                and entry.get("payload", {}).get("event_signature") == event_signature
            ]
            if len(recorded_entries) > 1:
                raise ValueError(f"approval receipt is journaled more than once: {event_id}")
            if recorded_entries:
                if recorded_entries[0].get("report_body_hash") != report_body_hash:
                    raise ValueError(f"approval receipt journal report_body_hash drifted: {event_id}")
                return {"idempotent": True, "approval": approval, "parsed": parsed}
            if approval.get("events", [])[-1] is not event:
                raise ValueError("an unjournaled approval event must be the latest cache event")
            run["state"] = approval["state"]
            run["approval"] = {
                "path": str(approval_path),
                "report_version": report["report_version"],
                "report_hash": report["report_hash"],
                "report_body_hash": report_body_hash,
                "scope_revision": report["scope_revision"],
                "state": approval["state"],
                "authorized_scope": approval.get("authorized_scope", []),
            }
            run["revision"] = int(run.get("revision", 0)) + 1
            run["updated_at"] = sublation_run.utc_now()
            sublation_run.commit_run(
                run_dir,
                run,
                "approval_receipt_recorded",
                receipt_journal_payload(
                    event_id=event_id,
                    event_signature=event_signature,
                    channel=channel,
                    sender_id=sender_id,
                    in_reply_to=in_reply_to,
                    report=report,
                    report_body_hash=report_body_hash,
                    decisions=parsed,
                    resulting_state=approval["state"],
                    authorized_scope=approval.get("authorized_scope", []),
                    receipt_evidence=evidence_record,
                    adapter_id=adapter_id,
                    source_event_hash=source_event_hash,
                ),
            )
            return {"idempotent": True, "approval": approval, "parsed": parsed}

        now = sublation_run.utc_now()
        for item_id, decision in parsed.items():
            previous = approval["decisions"].get(item_id, {})
            if previous.get("execution") in {"running", "succeeded"} and decision != "approve":
                raise ValueError(f"cannot edit or withdraw {item_id} after promotion execution started")
            approval["decisions"][item_id] = {
                "decision": decision,
                "updated_at": now,
                "event_id": event_id,
                "execution": "pending" if decision == "approve" else "not_authorized",
            }
        approval.setdefault("events", []).append(
            {
                "event_id": event_id,
                "event_signature": event_signature,
                "channel": channel,
                "sender_id": sender_id,
                "in_reply_to": in_reply_to,
                "message": message,
                "parsed": parsed,
                "report_body_hash": report_body_hash,
                "timestamp": now,
                "receipt_evidence": evidence_record,
                "adapter_id": adapter_id,
                "source_event_hash": source_event_hash,
            }
        )

        values = [entry["decision"] for entry in approval["decisions"].values()]
        if "approve" in values:
            state = "APPROVED_PENDING_EXECUTION"
        elif values and all(value == "reject" for value in values):
            state = "USER_REJECTED"
        else:
            state = "USER_DECISION_REQUIRED"
        approval["state"] = state
        approval["authorized_scope"] = sorted(
            item_id for item_id, entry in approval["decisions"].items() if entry["decision"] == "approve"
        )
        approval["updated_at"] = now
        sublation_run.atomic_write_json(approval_path, approval)
        if os.environ.get("SUBLATION_TEST_CRASH_AFTER_APPROVAL_WRITE") == "1":
            os._exit(97)

        run["approval"] = {
            "path": str(approval_path),
            "report_version": report["report_version"],
            "report_hash": report["report_hash"],
            "report_body_hash": report_body_hash,
            "scope_revision": report["scope_revision"],
            "state": state,
            "authorized_scope": approval["authorized_scope"],
        }
        run["state"] = state
        run["revision"] = int(run.get("revision", 0)) + 1
        run["updated_at"] = now
        sublation_run.commit_run(
            run_dir,
            run,
            "approval_receipt_recorded",
            receipt_journal_payload(
                event_id=event_id,
                event_signature=event_signature,
                channel=channel,
                sender_id=sender_id,
                in_reply_to=in_reply_to,
                report=report,
                report_body_hash=report_body_hash,
                decisions=parsed,
                resulting_state=state,
                authorized_scope=approval["authorized_scope"],
                receipt_evidence=evidence_record,
                adapter_id=adapter_id,
                source_event_hash=source_event_hash,
            ),
        )
        return {"idempotent": False, "approval": approval, "parsed": parsed}


def command_apply(args: argparse.Namespace) -> int:
    result = apply_receipt(
        Path(args.run_dir),
        receipt_evidence_path=args.receipt_evidence,
        report_version=args.report_version,
        expected_report_hash=args.report_hash,
        scope_revision=args.scope_revision,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_show(args: argparse.Namespace) -> int:
    path = Path(args.run_dir) / "approval.json"
    if not path.exists():
        raise ValueError("approval.json does not exist")
    print(json.dumps(sublation_run.read_json(path), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    apply_parser = sub.add_parser("apply", help="parse and bind one receipt")
    apply_parser.add_argument("--run-dir", required=True)
    apply_parser.add_argument("--receipt-evidence", required=True)
    apply_parser.add_argument("--report-version", type=int)
    apply_parser.add_argument("--report-hash")
    apply_parser.add_argument("--scope-revision", type=int)
    apply_parser.set_defaults(func=command_apply)
    show_parser = sub.add_parser("show", help="show the current parsed authorization scope")
    show_parser.add_argument("--run-dir", required=True)
    show_parser.set_defaults(func=command_show)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
