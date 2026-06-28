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
from datetime import datetime, date, timedelta
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


def get_today_at_a_glance(entries: list[dict]) -> dict:
    """Return today's session count, current streak, and today's discernment avg."""
    today = date.today()
    skip = ("_weekly", "_ondemand")
    filename_re = re.compile(r"^(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}")

    # Count today's replay files and collect today's session IDs
    today_session_ids: set[str] = set()
    today_replay_count = 0
    dated_days: set[date] = set()

    if SESSION_REPLAYS_DIR.exists():
        for f in SESSION_REPLAYS_DIR.iterdir():
            if f.suffix != ".md" or any(kw in f.name for kw in skip):
                continue
            m = filename_re.match(f.name)
            if not m:
                continue
            try:
                file_date = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            dated_days.add(file_date)
            if file_date == today:
                today_replay_count += 1
                # Extract 8-char session ID from filename (3rd underscore segment)
                parts = f.stem.split("_", 3)
                if len(parts) >= 3:
                    today_session_ids.add(parts[2])

    # Current streak: consecutive days ending today (or yesterday if today has none)
    streak = 0
    check = today
    while check in dated_days:
        streak += 1
        check -= timedelta(days=1)

    # Today's discernment avg using session IDs from today's replays
    today_scores = [
        e.get("composite", 0)
        for e in entries
        if e.get("session_id", "")[:8] in today_session_ids and e.get("composite")
    ]
    discernment_avg = sum(today_scores) / len(today_scores) if today_scores else None

    return {
        "today_sessions": today_replay_count,
        "streak": streak,
        "discernment_avg": discernment_avg,
    }


def get_activity_heatmap() -> dict[str, int]:
    """Return a dict of {'YYYY-MM-DD': session_count} from session replay filenames."""
    counts: dict[str, int] = {}
    if not SESSION_REPLAYS_DIR.exists():
        return counts
    skip = ("_weekly", "_ondemand")
    filename_re = re.compile(r"^(\d{4}-\d{2}-\d{2})_")
    for f in SESSION_REPLAYS_DIR.iterdir():
        if f.suffix != ".md" or any(kw in f.name for kw in skip):
            continue
        m = filename_re.match(f.name)
        if not m:
            continue
        day = m.group(1)
        counts[day] = counts.get(day, 0) + 1
    return counts


_STOPWORDS = frozenset(
    "a an the and or in on at to of is was are were be been for from with this that it its"
    " i we you they he she what how when where which who by as up do did can could will"
    " build built add added run ran fix fixed make made use used create created update updated".split()
)


def get_knowledge_gaps() -> list[str]:
    """Return up to 5 topics from recent replays with no knowledge DB entries."""
    cutoff = date.today() - timedelta(days=7)
    skip = ("_weekly", "_ondemand")
    filename_re = re.compile(r"^(\d{4}-\d{2}-\d{2})_")

    bullet_re = re.compile(r"^- (.+)", re.MULTILINE)
    section_re = re.compile(
        r"## What Was (?:Done|Built)\s*\n(.*?)(?=\n##|\Z)", re.DOTALL
    )

    extracted: list[str] = []
    if SESSION_REPLAYS_DIR.exists():
        for f in SESSION_REPLAYS_DIR.iterdir():
            if f.suffix != ".md" or any(kw in f.name for kw in skip):
                continue
            m = filename_re.match(f.name)
            if not m:
                continue
            try:
                file_date = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if file_date < cutoff:
                continue
            try:
                content = f.read_text(errors="replace")
            except IOError:
                continue
            sec = section_re.search(content)
            if not sec:
                continue
            for bullet in bullet_re.findall(sec.group(1)):
                # Strip bold markers and take the first meaningful noun phrase (up to 3 words)
                clean = re.sub(r"\*\*(.+?)\*\*", r"\1", bullet).strip()
                words = [w for w in re.split(r"[\s:,\-–]+", clean) if w.lower() not in _STOPWORDS and len(w) > 2]
                if words:
                    extracted.append(" ".join(words[:3]))

    if not extracted or not KNOWLEDGE_DB.exists():
        return []

    gaps: list[str] = []
    seen_topics: set[str] = set()
    try:
        conn = sqlite3.connect(str(KNOWLEDGE_DB))
        cursor = conn.cursor()
        for topic in extracted:
            if topic.lower() in seen_topics:
                continue
            seen_topics.add(topic.lower())
            try:
                cursor.execute(
                    "SELECT rowid FROM knowledge_fts WHERE knowledge_fts MATCH ? LIMIT 1",
                    (topic,),
                )
                if cursor.fetchone() is None:
                    gaps.append(topic)
            except sqlite3.OperationalError:
                pass
            if len(gaps) >= 5:
                break
        conn.close()
    except sqlite3.Error:
        pass

    return gaps[:5]


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


_HEATMAP_COLORS = ["#e5e4e0", "#f5c4b4", "#eda98a", "#d97757"]


def _build_heatmap_html(activity: dict[str, int]) -> str:
    """Build the GitHub-style contribution heatmap HTML."""
    today = date.today()

    # Grid starts on the Monday of the week 52 weeks ago from today's week.
    # "Today's week" Monday:
    week_start_monday = today - timedelta(days=today.weekday())
    grid_start = week_start_monday - timedelta(weeks=52)  # 53 weeks total displayed

    # Total days: from grid_start to the Sunday of today's week (inclusive)
    week_end_sunday = week_start_monday + timedelta(days=6)
    total_days = (week_end_sunday - grid_start).days + 1  # always 53*7 = 371
    num_weeks = total_days // 7  # 53

    # Build week columns: list of 7-day lists
    weeks: list[list[date]] = []
    for w in range(num_weeks):
        col = [grid_start + timedelta(days=w * 7 + d) for d in range(7)]
        weeks.append(col)

    # Month labels: one per column where the month changes
    MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    month_labels: list[tuple[int, str]] = []  # (col_index, label)
    prev_month = None
    for w_idx, col in enumerate(weeks):
        col_month = col[0].month
        if col_month != prev_month:
            month_labels.append((w_idx, MONTH_ABBR[col_month - 1]))
            prev_month = col_month

    # Build month label row (each cell = 13px wide: 11px + 2px gap)
    cell_w = 13  # 11px cell + 2px gap
    months_html_parts = []
    for i, (col_idx, label) in enumerate(month_labels):
        left_px = col_idx * cell_w
        next_left = month_labels[i + 1][0] * cell_w if i + 1 < len(month_labels) else num_weeks * cell_w
        width_px = next_left - left_px
        months_html_parts.append(
            f'<div class="heatmap-month-label" style="width:{width_px}px;">{label}</div>'
        )
    months_row = f'<div class="heatmap-months">{"".join(months_html_parts)}</div>'

    # Build grid columns
    cols_html = []
    for col in weeks:
        cells = []
        for d in col:
            if d > today:
                # Future days: render as empty/gray placeholder
                color = _HEATMAP_COLORS[0]
                tooltip = ""
            else:
                day_str = d.isoformat()
                count = activity.get(day_str, 0)
                color_idx = min(count, 3)
                color = _HEATMAP_COLORS[color_idx]
                label = f"{count} session{'s' if count != 1 else ''}"
                tooltip = f'{d.strftime("%b %d, %Y")} — {label}'
            title_attr = f' title="{tooltip}"' if tooltip else ""
            cells.append(
                f'<div class="heatmap-cell" style="background:{color};"{title_attr}></div>'
            )
        cols_html.append(f'<div class="heatmap-col">{"".join(cells)}</div>')

    grid_rows = f'<div class="heatmap-rows">{"".join(cols_html)}</div>'

    legend = (
        '<div class="heatmap-legend">'
        '<span>Less</span>'
        f'<span class="heatmap-legend-cell" style="background:{_HEATMAP_COLORS[0]};" title="0 sessions"></span>'
        f'<span class="heatmap-legend-cell" style="background:{_HEATMAP_COLORS[1]};" title="1 session"></span>'
        f'<span class="heatmap-legend-cell" style="background:{_HEATMAP_COLORS[2]};" title="2 sessions"></span>'
        f'<span class="heatmap-legend-cell" style="background:{_HEATMAP_COLORS[3]};" title="3+ sessions"></span>'
        '<span>More</span>'
        '</div>'
    )

    return (
        f'<div class="heatmap-wrapper">'
        f'<div class="heatmap-grid">'
        f'{months_row}'
        f'{grid_rows}'
        f'</div>'
        f'{legend}'
        f'</div>'
    )


def generate_html(
    entries: list[dict],
    contracts: dict[str, dict],
    replays: list[dict],
    knowledge_stats: dict,
    glance: dict,
    knowledge_gaps: list[str],
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

    # Build "Today at a Glance" cards HTML
    streak_display = f"{glance['streak']} day{'s' if glance['streak'] != 1 else ''}"
    avg_display = f"{glance['discernment_avg']:.1f}" if glance["discernment_avg"] is not None else "—"
    glance_html = f"""
        <div class="glance-row">
            <div class="glance-card">
                <div class="glance-number">{glance['today_sessions']}</div>
                <div class="glance-label">Today's Sessions</div>
            </div>
            <div class="glance-card">
                <div class="glance-number">{streak_display}</div>
                <div class="glance-label">Current Streak</div>
            </div>
            <div class="glance-card">
                <div class="glance-number">{avg_display}</div>
                <div class="glance-label">Discernment Avg Today</div>
            </div>
        </div>
        """

    # Build knowledge gaps HTML
    if knowledge_gaps:
        gap_items = "".join(
            f'<div class="gap-item"><span>{escape_html(gap)}</span>'
            f'<span class="gap-hint">Consider running `/knowledge add`</span></div>'
            for gap in knowledge_gaps
        )
        gaps_html = f'<div class="gaps-section">{gap_items}</div>'
    else:
        gaps_html = '<p class="no-data">Knowledge base covers recent work well.</p>'

    # Build activity heatmap
    activity = get_activity_heatmap()
    heatmap_html = _build_heatmap_html(activity)

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
        .glance-row {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }}
        @media (max-width: 600px) {{
            .glance-row {{
                grid-template-columns: 1fr;
            }}
        }}
        .glance-card {{
            background: {COLORS["card_bg"]};
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
            padding: 20px;
            text-align: center;
        }}
        .glance-card .glance-number {{
            font-size: 2.4rem;
            font-weight: 700;
            color: {COLORS["orange"]};
            line-height: 1.1;
        }}
        .glance-card .glance-label {{
            font-size: 0.8rem;
            color: {COLORS["gray"]};
            margin-top: 6px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .gaps-section {{
            margin-bottom: 24px;
        }}
        .gap-item {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid {COLORS["border"]};
            font-size: 0.9rem;
        }}
        .gap-item:last-child {{
            border-bottom: none;
        }}
        .gap-hint {{
            font-size: 0.75rem;
            color: {COLORS["blue"]};
            font-style: italic;
        }}
        .heatmap-wrapper {{
            overflow-x: auto;
        }}
        .heatmap-grid {{
            display: inline-flex;
            flex-direction: column;
            gap: 0;
        }}
        .heatmap-months {{
            display: flex;
            margin-bottom: 4px;
        }}
        .heatmap-month-label {{
            font-size: 0.7rem;
            color: {COLORS["gray"]};
            white-space: nowrap;
        }}
        .heatmap-rows {{
            display: flex;
            gap: 2px;
        }}
        .heatmap-col {{
            display: flex;
            flex-direction: column;
            gap: 2px;
        }}
        .heatmap-cell {{
            width: 11px;
            height: 11px;
            border-radius: 2px;
            cursor: default;
        }}
        .heatmap-legend {{
            display: flex;
            align-items: center;
            gap: 6px;
            margin-top: 12px;
            font-size: 0.75rem;
            color: {COLORS["gray"]};
        }}
        .heatmap-legend-cell {{
            width: 11px;
            height: 11px;
            border-radius: 2px;
            display: inline-block;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Claude Code Dashboard</h1>
            <div class="subtitle">{today} &bull; {total_sessions} sessions tracked</div>
        </header>

        {glance_html}

        <div class="card">
            <h2>Session Activity (last 52 weeks)</h2>
            {heatmap_html}
        </div>

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

        <div class="card">
            <h2>Knowledge Gaps</h2>
            {gaps_html}
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
    glance = get_today_at_a_glance(entries)
    knowledge_gaps = get_knowledge_gaps()

    # Generate HTML
    html = generate_html(entries, contracts, replays, knowledge_stats, glance, knowledge_gaps)

    # Write to file
    OUTPUT_HTML.write_text(html)
    print(f"Dashboard generated: {OUTPUT_HTML}")

    # Open in browser
    subprocess.Popen(["open", str(OUTPUT_HTML)])


if __name__ == "__main__":
    main()
