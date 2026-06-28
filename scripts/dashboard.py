#!/usr/bin/env python3
"""
Dashboard generator for claude-productivity-kit.
Reads discernment logs, session contracts, replays, and knowledge DB
to generate a self-contained HTML dashboard.
"""

import json
import sqlite3
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

CLAUDE_HOME = Path.home() / ".claude"
DISCERNMENT_LOG = CLAUDE_HOME / "discernment-log.jsonl"
SESSION_CONTRACTS_DIR = CLAUDE_HOME / "session-contracts"
SESSION_REPLAYS_DIR = CLAUDE_HOME / "session-replays"
KNOWLEDGE_DB = CLAUDE_HOME / "knowledge.db"
DAILY_BRIEF_REPOS = CLAUDE_HOME / "daily-brief-repos.json"
OUTPUT_HTML = CLAUDE_HOME / "dashboard.html"

# Anthropic brand colors
COLORS = {
    "background": "#faf9f5",
    "text": "#141413",
    "orange": "#d97757",
    "blue": "#6a9bcc",
    "green": "#788c5d",
    "gray": "#b0aea5",
    "card_bg": "#ffffff",
    "border": "#e5e4e0",
}


def load_discernment_log() -> list[dict]:
    """Load all entries from discernment log."""
    if not DISCERNMENT_LOG.exists():
        return []
    entries = []
    with open(DISCERNMENT_LOG, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def load_session_contracts() -> dict[str, dict]:
    """Load all session contracts, keyed by session_id."""
    contracts = {}
    if not SESSION_CONTRACTS_DIR.exists():
        return contracts
    for file in SESSION_CONTRACTS_DIR.glob("*.json"):
        try:
            with open(file, "r") as f:
                data = json.load(f)
                session_id = data.get("session_id") or file.stem
                contracts[session_id] = data
        except (json.JSONDecodeError, IOError):
            continue
    return contracts


def load_session_replays() -> list[dict]:
    """Load session replay metadata, sorted by date descending."""
    replays = []
    if not SESSION_REPLAYS_DIR.exists():
        return replays
    for file in SESSION_REPLAYS_DIR.glob("*.md"):
        # Parse filename: 2026-06-28_14-30_<8-char-id>_<title>.md
        name = file.stem
        parts = name.split("_", 3)
        if len(parts) >= 3:
            date_str = parts[0]
            time_str = parts[1]
            session_id = parts[2]
            title = parts[3] if len(parts) > 3 else "Untitled"
            title = title.replace("-", " ").replace("_", " ")
        else:
            date_str = ""
            time_str = ""
            session_id = ""
            title = name

        # Try to extract goal from file content
        goal = None
        try:
            content = file.read_text()
            goal_match = re.search(r"^## Goal\s*\n(.+?)(?=\n##|\n#|\Z)", content, re.MULTILINE | re.DOTALL)
            if goal_match:
                goal = goal_match.group(1).strip()[:200]
        except IOError:
            pass

        replays.append({
            "path": str(file),
            "filename": file.name,
            "date_str": date_str,
            "time_str": time_str,
            "session_id": session_id,
            "title": title,
            "goal": goal,
        })

    # Sort by date descending
    replays.sort(key=lambda x: (x["date_str"], x["time_str"]), reverse=True)
    return replays


def load_knowledge_stats() -> dict:
    """Load knowledge base statistics."""
    stats = {
        "total": 0,
        "by_type": {},
        "recent_facts": [],
    }
    if not KNOWLEDGE_DB.exists():
        return stats
    try:
        conn = sqlite3.connect(str(KNOWLEDGE_DB))
        cursor = conn.cursor()

        # Total count
        cursor.execute("SELECT COUNT(*) FROM knowledge")
        stats["total"] = cursor.fetchone()[0]

        # Count by type
        cursor.execute("SELECT source_type, COUNT(*) FROM knowledge GROUP BY source_type")
        for row in cursor.fetchall():
            stats["by_type"][row[0]] = row[1]

        # Recent facts
        cursor.execute("""
            SELECT fact, source_url, source_type, added_at
            FROM knowledge
            ORDER BY added_at DESC
            LIMIT 5
        """)
        for row in cursor.fetchall():
            stats["recent_facts"].append({
                "fact": row[0],
                "source_url": row[1],
                "source_type": row[2],
                "added_at": row[3],
            })

        conn.close()
    except sqlite3.Error:
        pass
    return stats


def calculate_averages(entries: list[dict]) -> dict:
    """Calculate average scores for each dimension."""
    if not entries:
        return {"overall": 0, "product": 0, "process": 0, "performance": 0}

    overall_scores = [e.get("composite", 0) for e in entries if e.get("composite")]
    product_scores = [e["product"]["score"] for e in entries if e.get("product", {}).get("score")]
    process_scores = [e["process"]["score"] for e in entries if e.get("process", {}).get("score")]
    performance_scores = [e["performance"]["score"] for e in entries if e.get("performance", {}).get("score")]

    return {
        "overall": sum(overall_scores) / len(overall_scores) if overall_scores else 0,
        "product": sum(product_scores) / len(product_scores) if product_scores else 0,
        "process": sum(process_scores) / len(process_scores) if process_scores else 0,
        "performance": sum(performance_scores) / len(performance_scores) if performance_scores else 0,
    }


def calculate_trend(entries: list[dict], key: str) -> str:
    """Calculate trend arrow based on first 5 vs last 5 entries."""
    if len(entries) < 5:
        return "→"

    if key == "overall":
        first_5 = [e.get("composite", 0) for e in entries[:5] if e.get("composite")]
        last_5 = [e.get("composite", 0) for e in entries[-5:] if e.get("composite")]
    else:
        first_5 = [e.get(key, {}).get("score", 0) for e in entries[:5] if e.get(key, {}).get("score")]
        last_5 = [e.get(key, {}).get("score", 0) for e in entries[-5:] if e.get(key, {}).get("score")]

    if not first_5 or not last_5:
        return "→"

    first_avg = sum(first_5) / len(first_5)
    last_avg = sum(last_5) / len(last_5)
    diff = last_avg - first_avg

    if diff > 0.2:
        return "↑"
    elif diff < -0.2:
        return "↓"
    return "→"


def find_weakest_dimension(entries: list[dict]) -> Optional[dict]:
    """Find the weakest dimension and its most recent reason."""
    if not entries:
        return None

    recent_30 = entries[-30:] if len(entries) > 30 else entries
    avgs = calculate_averages(recent_30)

    dimensions = [
        ("Product", avgs["product"], "product"),
        ("Process", avgs["process"], "process"),
        ("Performance", avgs["performance"], "performance"),
    ]

    # Filter out zero averages
    valid_dims = [(name, avg, key) for name, avg, key in dimensions if avg > 0]
    if not valid_dims:
        return None

    weakest = min(valid_dims, key=lambda x: x[1])

    # Get most recent reason for this dimension
    reason = ""
    for entry in reversed(entries):
        if entry.get(weakest[2], {}).get("reason"):
            reason = entry[weakest[2]]["reason"]
            break

    return {
        "name": weakest[0],
        "average": weakest[1],
        "key": weakest[2],
        "reason": reason,
    }


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def truncate(text: str, length: int) -> str:
    """Truncate text to specified length."""
    if not text:
        return ""
    if len(text) <= length:
        return text
    return text[:length - 3] + "..."


def generate_html(
    entries: list[dict],
    contracts: dict[str, dict],
    replays: list[dict],
    knowledge_stats: dict,
) -> str:
    """Generate the complete HTML dashboard."""

    today = datetime.now().strftime("%B %d, %Y")
    total_sessions = len(set(e.get("session_id", "") for e in entries))

    # Prepare chart data (last 30 entries)
    chart_entries = entries[-30:] if len(entries) > 30 else entries
    chart_labels = [f"#{i+1}" for i in range(len(chart_entries))]
    composite_data = [e.get("composite", 0) for e in chart_entries]
    product_data = [e.get("product", {}).get("score", 0) for e in chart_entries]
    process_data = [e.get("process", {}).get("score", 0) for e in chart_entries]
    performance_data = [e.get("performance", {}).get("score", 0) for e in chart_entries]

    # Calculate averages
    avgs = calculate_averages(entries)

    # Calculate trends
    trends = {
        "overall": calculate_trend(entries, "overall"),
        "product": calculate_trend(entries, "product"),
        "process": calculate_trend(entries, "process"),
        "performance": calculate_trend(entries, "performance"),
    }

    # Find weakest dimension
    weakest = find_weakest_dimension(entries)

    # Get last 10 sessions for timeline
    session_ids_ordered = []
    seen = set()
    for entry in reversed(entries):
        sid = entry.get("session_id", "")
        if sid and sid not in seen:
            seen.add(sid)
            session_ids_ordered.append(sid)
            if len(session_ids_ordered) >= 10:
                break

    # Build session timeline HTML
    timeline_html = ""
    for sid in session_ids_ordered:
        contract = contracts.get(sid, {})
        title = contract.get("session_title", sid[:8] if sid else "Unknown")
        effort = contract.get("effort", "normal")
        effort_badge_color = {
            "quick": COLORS["orange"],
            "normal": COLORS["blue"],
            "deep": COLORS["green"],
        }.get(effort, COLORS["gray"])

        # Get composite score for this session
        session_entries = [e for e in entries if e.get("session_id") == sid]
        if session_entries:
            composite = session_entries[-1].get("composite", 0)
        else:
            composite = 0

        # Score bar color
        if composite < 7:
            score_color = "#e57373"  # red
        elif composite < 8:
            score_color = "#ffd54f"  # yellow
        else:
            score_color = COLORS["green"]

        # Domain keywords
        keywords = contract.get("domain_keywords", [])
        keywords_html = "".join(
            f'<span class="chip">{escape_html(kw)}</span>'
            for kw in keywords[:5]
        )

        bar_width = min(100, max(0, composite * 10))

        timeline_html += f"""
        <div class="timeline-item">
            <div class="timeline-header">
                <span class="session-title">{escape_html(truncate(title, 50))}</span>
                <span class="effort-badge" style="background: {effort_badge_color};">{escape_html(effort)}</span>
            </div>
            <div class="score-bar-container">
                <div class="score-bar" style="width: {bar_width}%; background: {score_color};"></div>
                <span class="score-label">{composite:.1f}</span>
            </div>
            <div class="keywords">{keywords_html if keywords_html else '<span class="no-data">—</span>'}</div>
        </div>
        """

    if not timeline_html:
        timeline_html = '<p class="no-data">No session data yet</p>'

    # Build knowledge stats HTML
    knowledge_html = ""
    if knowledge_stats["total"] > 0:
        type_badges = "".join(
            f'<span class="type-badge">{escape_html(t)}: {c}</span>'
            for t, c in knowledge_stats["by_type"].items()
        )
        facts_html = ""
        for fact in knowledge_stats["recent_facts"]:
            url = truncate(fact.get("source_url", ""), 40)
            facts_html += f"""
            <div class="fact-item">
                <div class="fact-text">{escape_html(truncate(fact.get("fact", ""), 100))}</div>
                <div class="fact-source">{escape_html(url)}</div>
            </div>
            """
        knowledge_html = f"""
        <div class="stat-row">
            <span class="stat-label">Total Facts:</span>
            <span class="stat-value">{knowledge_stats["total"]}</span>
        </div>
        <div class="type-badges">{type_badges}</div>
        <h4>Recent Facts</h4>
        {facts_html}
        """
    else:
        knowledge_html = '<p class="no-data">No knowledge entries yet</p>'

    # Build replays HTML
    replays_html = ""
    for replay in replays[:5]:
        title = replay.get("goal") or replay.get("title") or "Untitled"
        date_str = replay.get("date_str", "")
        file_url = f"file://{replay['path']}"
        replays_html += f"""
        <a href="{file_url}" class="replay-card">
            <div class="replay-title">{escape_html(truncate(title, 80))}</div>
            <div class="replay-date">{escape_html(date_str)}</div>
        </a>
        """
    if not replays_html:
        replays_html = '<p class="no-data">No session replays yet</p>'

    # Build weakest dimension HTML
    weakest_html = ""
    if weakest:
        weakest_html = f"""
        <div class="weakest-box">
            <div class="weakest-header">
                <span class="weakest-label">Weakest Dimension:</span>
                <span class="weakest-name">{escape_html(weakest["name"])}</span>
                <span class="weakest-score">{weakest["average"]:.1f}</span>
            </div>
            <div class="weakest-reason">{escape_html(weakest.get("reason", "No reason available"))}</div>
        </div>
        """
    else:
        weakest_html = '<p class="no-data">Not enough data for analysis</p>'

    # Assemble final HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude Code Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Poppins', sans-serif;
            background: {COLORS["background"]};
            color: {COLORS["text"]};
            line-height: 1.6;
            padding: 24px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        header {{
            text-align: center;
            margin-bottom: 32px;
        }}
        header h1 {{
            font-size: 2rem;
            font-weight: 600;
            color: {COLORS["text"]};
            margin-bottom: 8px;
        }}
        header .subtitle {{
            color: {COLORS["gray"]};
            font-size: 0.95rem;
        }}
        .card {{
            background: {COLORS["card_bg"]};
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
            padding: 24px;
            margin-bottom: 24px;
        }}
        .card h2 {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 16px;
            color: {COLORS["text"]};
        }}
        .card h4 {{
            font-size: 0.9rem;
            font-weight: 500;
            margin: 16px 0 8px 0;
            color: {COLORS["gray"]};
        }}
        .chart-container {{
            width: 100%;
            height: 220px;
        }}
        .score-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .score-card {{
            background: {COLORS["card_bg"]};
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
            padding: 20px;
            text-align: center;
        }}
        .score-card .label {{
            font-size: 0.85rem;
            color: {COLORS["gray"]};
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }}
        .score-card .dot {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }}
        .score-card .value {{
            font-size: 2rem;
            font-weight: 600;
        }}
        .score-card .trend {{
            font-size: 1.2rem;
            margin-left: 8px;
        }}
        .trend-up {{ color: {COLORS["green"]}; }}
        .trend-down {{ color: #e57373; }}
        .trend-flat {{ color: {COLORS["gray"]}; }}
        .two-col {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }}
        @media (max-width: 768px) {{
            .two-col {{
                grid-template-columns: 1fr;
            }}
        }}
        .timeline-item {{
            padding: 12px 0;
            border-bottom: 1px solid {COLORS["border"]};
        }}
        .timeline-item:last-child {{
            border-bottom: none;
        }}
        .timeline-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 8px;
        }}
        .session-title {{
            font-weight: 500;
            flex: 1;
        }}
        .effort-badge {{
            font-size: 0.7rem;
            padding: 2px 8px;
            border-radius: 10px;
            color: white;
            text-transform: uppercase;
            font-weight: 500;
        }}
        .score-bar-container {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 8px;
        }}
        .score-bar {{
            height: 8px;
            border-radius: 4px;
            transition: width 0.3s ease;
        }}
        .score-label {{
            font-size: 0.85rem;
            font-weight: 500;
            color: {COLORS["gray"]};
            min-width: 35px;
        }}
        .keywords {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }}
        .chip {{
            font-size: 0.7rem;
            padding: 2px 8px;
            background: {COLORS["border"]};
            border-radius: 10px;
            color: {COLORS["text"]};
        }}
        .no-data {{
            color: {COLORS["gray"]};
            font-style: italic;
        }}
        .stat-row {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid {COLORS["border"]};
        }}
        .stat-label {{
            color: {COLORS["gray"]};
        }}
        .stat-value {{
            font-weight: 600;
        }}
        .type-badges {{
            display: flex;
            gap: 8px;
            margin: 12px 0;
            flex-wrap: wrap;
        }}
        .type-badge {{
            font-size: 0.75rem;
            padding: 4px 10px;
            background: {COLORS["blue"]};
            color: white;
            border-radius: 12px;
        }}
        .fact-item {{
            padding: 8px 0;
            border-bottom: 1px solid {COLORS["border"]};
        }}
        .fact-item:last-child {{
            border-bottom: none;
        }}
        .fact-text {{
            font-size: 0.85rem;
            margin-bottom: 4px;
        }}
        .fact-source {{
            font-size: 0.75rem;
            color: {COLORS["gray"]};
        }}
        .replay-card {{
            display: block;
            padding: 12px;
            margin-bottom: 8px;
            background: {COLORS["background"]};
            border-radius: 8px;
            text-decoration: none;
            color: {COLORS["text"]};
            transition: box-shadow 0.2s ease;
        }}
        .replay-card:hover {{
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }}
        .replay-title {{
            font-weight: 500;
            margin-bottom: 4px;
        }}
        .replay-date {{
            font-size: 0.8rem;
            color: {COLORS["gray"]};
        }}
        .weakest-box {{
            background: linear-gradient(135deg, {COLORS["orange"]}15 0%, {COLORS["orange"]}05 100%);
            border-left: 4px solid {COLORS["orange"]};
            padding: 16px;
            border-radius: 0 8px 8px 0;
        }}
        .weakest-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;
            flex-wrap: wrap;
        }}
        .weakest-label {{
            font-size: 0.85rem;
            color: {COLORS["gray"]};
        }}
        .weakest-name {{
            font-weight: 600;
            color: {COLORS["orange"]};
        }}
        .weakest-score {{
            font-size: 0.85rem;
            padding: 2px 8px;
            background: {COLORS["orange"]};
            color: white;
            border-radius: 10px;
        }}
        .weakest-reason {{
            font-size: 0.9rem;
            line-height: 1.5;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Claude Code Dashboard</h1>
            <div class="subtitle">{today} &bull; {total_sessions} sessions tracked</div>
        </header>

        <div class="card">
            <h2>Discernment Trend (Last 30 Scores)</h2>
            <div class="chart-container">
                <canvas id="trendChart"></canvas>
            </div>
        </div>

        <div class="score-cards">
            <div class="score-card">
                <div class="label">Overall Avg</div>
                <div class="value">
                    {avgs["overall"]:.1f}
                    <span class="trend {"trend-up" if trends["overall"] == "↑" else "trend-down" if trends["overall"] == "↓" else "trend-flat"}">{trends["overall"]}</span>
                </div>
            </div>
            <div class="score-card">
                <div class="label"><span class="dot" style="background: {COLORS["orange"]};"></span> Product Avg</div>
                <div class="value">
                    {avgs["product"]:.1f}
                    <span class="trend {"trend-up" if trends["product"] == "↑" else "trend-down" if trends["product"] == "↓" else "trend-flat"}">{trends["product"]}</span>
                </div>
            </div>
            <div class="score-card">
                <div class="label"><span class="dot" style="background: {COLORS["blue"]};"></span> Process Avg</div>
                <div class="value">
                    {avgs["process"]:.1f}
                    <span class="trend {"trend-up" if trends["process"] == "↑" else "trend-down" if trends["process"] == "↓" else "trend-flat"}">{trends["process"]}</span>
                </div>
            </div>
            <div class="score-card">
                <div class="label"><span class="dot" style="background: {COLORS["green"]};"></span> Performance Avg</div>
                <div class="value">
                    {avgs["performance"]:.1f}
                    <span class="trend {"trend-up" if trends["performance"] == "↑" else "trend-down" if trends["performance"] == "↓" else "trend-flat"}">{trends["performance"]}</span>
                </div>
            </div>
        </div>

        <div class="two-col">
            <div class="card">
                <h2>Session Timeline (Last 10)</h2>
                {timeline_html}
            </div>
            <div class="card">
                <h2>Knowledge Base</h2>
                {knowledge_html}
            </div>
        </div>

        <div class="two-col">
            <div class="card">
                <h2>Recent Replays</h2>
                {replays_html}
            </div>
            <div class="card">
                <h2>Weakest Dimension</h2>
                {weakest_html}
            </div>
        </div>
    </div>

    <script>
        const ctx = document.getElementById('trendChart').getContext('2d');
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: {json.dumps(chart_labels)},
                datasets: [
                    {{
                        label: 'Product',
                        data: {json.dumps(product_data)},
                        borderColor: '{COLORS["orange"]}',
                        backgroundColor: '{COLORS["orange"]}20',
                        tension: 0.3,
                        fill: false,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                    }},
                    {{
                        label: 'Process',
                        data: {json.dumps(process_data)},
                        borderColor: '{COLORS["blue"]}',
                        backgroundColor: '{COLORS["blue"]}20',
                        tension: 0.3,
                        fill: false,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                    }},
                    {{
                        label: 'Performance',
                        data: {json.dumps(performance_data)},
                        borderColor: '{COLORS["green"]}',
                        backgroundColor: '{COLORS["green"]}20',
                        tension: 0.3,
                        fill: false,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                    }},
                    {{
                        label: 'Threshold',
                        data: Array({len(chart_labels)}).fill(6.5),
                        borderColor: '{COLORS["gray"]}',
                        borderDash: [5, 5],
                        fill: false,
                        pointRadius: 0,
                        pointHoverRadius: 0,
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        position: 'top',
                        labels: {{
                            usePointStyle: true,
                            padding: 20,
                            font: {{
                                family: "'Poppins', sans-serif",
                                size: 12
                            }}
                        }}
                    }}
                }},
                scales: {{
                    y: {{
                        min: 0,
                        max: 10,
                        grid: {{
                            color: '{COLORS["border"]}'
                        }},
                        ticks: {{
                            font: {{
                                family: "'Poppins', sans-serif"
                            }}
                        }}
                    }},
                    x: {{
                        grid: {{
                            display: false
                        }},
                        ticks: {{
                            font: {{
                                family: "'Poppins', sans-serif"
                            }}
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    return html


def main():
    """Generate and open the dashboard."""
    # Load all data sources
    entries = load_discernment_log()
    contracts = load_session_contracts()
    replays = load_session_replays()
    knowledge_stats = load_knowledge_stats()

    # Generate HTML
    html = generate_html(entries, contracts, replays, knowledge_stats)

    # Write to file
    OUTPUT_HTML.write_text(html)
    print(f"Dashboard generated: {OUTPUT_HTML}")

    # Open in browser
    subprocess.Popen(["open", str(OUTPUT_HTML)])


if __name__ == "__main__":
    main()
