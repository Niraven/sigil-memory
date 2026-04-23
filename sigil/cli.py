#!/usr/bin/env python3
"""
Sigil CLI — Quick command-line interface for Sigil operations.

Usage:
    sigil remember "User prefers dark mode" --type semantic --importance 0.9
    sigil recall "interface preferences" --top-k 5
    sigil learn niam works_on zo.space
    sigil about niam
    sigil activate --persona engineer --context "fixing auth bugs"
    sigil stats
    sigil sleep
    sigil health --output "same thing again" --error "timeout"
    sigil persona list
    sigil persona set engineer
    sigil project create auth-migration --description "JWT migration"
    sigil export backup.json
    sigil import backup.json
"""

import argparse
import json
import sys
from pathlib import Path

from sigil.core import Sigil


def get_sigil(args) -> Sigil:
    """Create Sigil instance from CLI args."""
    return Sigil(
        db_path=args.db,
        agent_id=args.agent,
    )


def cmd_remember(args):
    cx = get_sigil(args)
    kwargs = {}
    if args.importance:
        kwargs["importance"] = args.importance
    if args.category:
        kwargs["category"] = args.category
    if args.source:
        kwargs["source"] = args.source

    # Episodic-specific
    if args.type == "episodic":
        if args.outcome:
            kwargs["outcome"] = args.outcome

    # Procedural-specific
    if args.type == "procedural":
        if args.name:
            kwargs["name"] = args.name
        if args.steps:
            kwargs["steps"] = args.steps.split(",")

    mid = cx.remember(args.content, type=args.type, **kwargs)
    print(f"Stored: {mid}")
    cx.close()


def cmd_recall(args):
    cx = get_sigil(args)
    results = cx.recall(args.query, top_k=args.top_k)
    if not results:
        print("No results found.")
    else:
        for i, r in enumerate(results, 1):
            print(f"\n[{i}] ({r.table}) score={r.score:.3f}")
            print(f"    {r.content}")
    cx.close()


def cmd_recall_compressed(args):
    cx = get_sigil(args)
    result = cx.recall_compressed(args.query, top_k=args.top_k,
                                   max_tokens=args.max_tokens)
    if result:
        print(result)
    else:
        print("No results found.")
    cx.close()


def cmd_learn(args):
    cx = get_sigil(args)
    tid = cx.learn(args.subject, args.predicate, args.object,
                   confidence=args.confidence)
    print(f"Triple: {tid}")
    cx.close()


def cmd_about(args):
    cx = get_sigil(args)
    entity = cx.about(args.entity)
    print(f"Entity: {entity.name}")
    print(f"  Out-degree: {entity.out_degree}")
    print(f"  In-degree: {entity.in_degree}")
    if entity.triples_out:
        print("  Outgoing:")
        for t in entity.triples_out:
            print(f"    → {t.predicate} → {t.object}")
    if entity.triples_in:
        print("  Incoming:")
        for t in entity.triples_in:
            print(f"    ← {t.subject} ← {t.predicate}")
    cx.close()


def cmd_activate(args):
    cx = get_sigil(args)
    brief = cx.activate(
        persona=args.persona,
        session_context=args.context or "",
    )
    if args.format == "json":
        print(json.dumps(brief, indent=2))
    else:
        prompt = cx.activation_prompt(
            persona=args.persona,
            session_context=args.context or "",
        )
        print(prompt)
    cx.close()


def cmd_stats(args):
    cx = get_sigil(args)
    stats = cx.stats()
    print(json.dumps(stats, indent=2, default=str))
    cx.close()


def cmd_sleep(args):
    cx = get_sigil(args)
    result = cx.sleep(max_age_hours=args.max_age)
    print(f"Consolidated: {result['consolidated']} sessions")
    print(f"Removed: {result['removed']} working memories")
    cx.close()


def cmd_health(args):
    cx = get_sigil(args)
    if args.report:
        report = cx.health_report()
        print(json.dumps(report, indent=2, default=str))
    else:
        result = cx.check_health(
            output=args.output or "",
            progress=args.progress,
            error=args.error or "",
            context=args.context or "",
        )
        if result["healthy"]:
            print("Healthy")
        else:
            print("Issues detected:")
            for issue in result["issues"]:
                print(f"  - {issue}")
            for rec in result["recommendations"]:
                if rec:
                    print(f"  Recommendation: {rec}")
    cx.close()


def cmd_persona(args):
    cx = get_sigil(args)
    if args.persona_action == "list":
        personas = cx.persona.list_personas()
        for p in personas:
            active = " *ACTIVE*" if p["active"] else ""
            source = f" [{p['source']}]" if "source" in p else ""
            print(f"  {p['id']:20s} {p['name']:20s}{source}{active}")
    elif args.persona_action == "set":
        if cx.set_persona(args.persona_id):
            print(f"Activated: {args.persona_id}")
        else:
            print(f"Persona not found: {args.persona_id}")
    elif args.persona_action == "prompt":
        prompt = cx.persona.generate_system_prompt(args.persona_id)
        print(prompt)
    elif args.persona_action == "info":
        p = cx.persona.get(args.persona_id)
        if p:
            print(json.dumps(p, indent=2, default=str))
        else:
            print(f"Not found: {args.persona_id}")
    cx.close()


def cmd_project(args):
    cx = get_sigil(args)
    if args.project_action == "create":
        pid = cx.project.create(
            args.name,
            description=args.description or "",
            milestone=args.milestone or "",
            deadline=args.deadline or None,
        )
        print(f"Created: {pid}")
    elif args.project_action == "list":
        projects = cx.project.list_projects()
        for p in projects:
            print(f"  {p.id:20s} {p.name:20s} [{p.status}]")
    elif args.project_action == "status":
        status = cx.project.status(args.project_id)
        print(json.dumps(status, indent=2, default=str))
    elif args.project_action == "add-task":
        tid = cx.project.add_task(
            args.project_id, args.title,
            priority=args.priority,
            assignee=args.assignee or None,
        )
        print(f"Task: {tid}")
    cx.close()


def cmd_export(args):
    cx = get_sigil(args)
    cx.export_json(args.path)
    print(f"Exported to: {args.path}")
    cx.close()


def cmd_import(args):
    cx = get_sigil(args)
    cx.import_json(args.path)
    print(f"Imported from: {args.path}")
    cx.close()


def main():
    parser = argparse.ArgumentParser(
        prog="sigil",
        description="Sigil — Cognitive backbone for multi-agent AI systems"
    )
    parser.add_argument("--db", default="~/.sigil/brain.db",
                        help="Database path (default: ~/.sigil/brain.db)")
    parser.add_argument("--agent", default="default",
                        help="Agent ID (default: 'default')")

    sub = parser.add_subparsers(dest="command", help="Command")

    # remember
    p = sub.add_parser("remember", help="Store a memory")
    p.add_argument("content", help="Content to remember")
    p.add_argument("--type", "-t", default="semantic",
                   choices=["semantic", "episodic", "procedural", "working"])
    p.add_argument("--importance", "-i", type=float, default=None)
    p.add_argument("--category", "-c", default=None)
    p.add_argument("--source", "-s", default=None)
    p.add_argument("--outcome", default=None)
    p.add_argument("--name", default=None)
    p.add_argument("--steps", default=None, help="Comma-separated steps")

    # recall
    p = sub.add_parser("recall", help="Recall memories")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", "-k", type=int, default=5)

    # recall-compressed
    p = sub.add_parser("recall-compressed", help="Recall compressed for LLM")
    p.add_argument("query", help="Search query")
    p.add_argument("--top-k", "-k", type=int, default=5)
    p.add_argument("--max-tokens", type=int, default=2000)

    # learn
    p = sub.add_parser("learn", help="Add a knowledge graph triple")
    p.add_argument("subject")
    p.add_argument("predicate")
    p.add_argument("object")
    p.add_argument("--confidence", type=float, default=1.0)

    # about
    p = sub.add_parser("about", help="Get entity profile")
    p.add_argument("entity")

    # activate
    p = sub.add_parser("activate", help="Generate activation briefing")
    p.add_argument("--persona", default="default")
    p.add_argument("--context", default=None)
    p.add_argument("--format", choices=["text", "json"], default="text")

    # stats
    sub.add_parser("stats", help="Show system statistics")

    # sleep
    p = sub.add_parser("sleep", help="Consolidate working memory")
    p.add_argument("--max-age", type=int, default=24,
                   help="Max age in hours (default: 24)")

    # health
    p = sub.add_parser("health", help="Health check")
    p.add_argument("--output", default=None)
    p.add_argument("--progress", type=float, default=-1)
    p.add_argument("--error", default=None)
    p.add_argument("--context", default=None)
    p.add_argument("--report", action="store_true",
                   help="Show full health report")

    # persona
    p = sub.add_parser("persona", help="Persona management")
    psub = p.add_subparsers(dest="persona_action")
    psub.add_parser("list", help="List all personas")
    pp = psub.add_parser("set", help="Activate a persona")
    pp.add_argument("persona_id")
    pp = psub.add_parser("prompt", help="Show persona system prompt")
    pp.add_argument("persona_id")
    pp = psub.add_parser("info", help="Show persona details")
    pp.add_argument("persona_id")

    # project
    p = sub.add_parser("project", help="Project management")
    psub = p.add_subparsers(dest="project_action")
    pp = psub.add_parser("create", help="Create a project")
    pp.add_argument("name")
    pp.add_argument("--description", default=None)
    pp.add_argument("--milestone", default=None)
    pp.add_argument("--deadline", default=None)
    psub.add_parser("list", help="List projects")
    pp = psub.add_parser("status", help="Project status")
    pp.add_argument("project_id")
    pp = psub.add_parser("add-task", help="Add task to project")
    pp.add_argument("project_id")
    pp.add_argument("title")
    pp.add_argument("--priority", default="medium",
                    choices=["critical", "high", "medium", "low"])
    pp.add_argument("--assignee", default=None)

    # export / import
    p = sub.add_parser("export", help="Export state to JSON")
    p.add_argument("path")
    p = sub.add_parser("import", help="Import state from JSON")
    p.add_argument("path")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    commands = {
        "remember": cmd_remember,
        "recall": cmd_recall,
        "recall-compressed": cmd_recall_compressed,
        "learn": cmd_learn,
        "about": cmd_about,
        "activate": cmd_activate,
        "stats": cmd_stats,
        "sleep": cmd_sleep,
        "health": cmd_health,
        "persona": cmd_persona,
        "project": cmd_project,
        "export": cmd_export,
        "import": cmd_import,
    }

    fn = commands.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
