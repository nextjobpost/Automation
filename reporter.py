"""
reporter.py — Weekly SEO Report Generator
Part of the NextJobPost Automation Engine (D:/Automation)

Generates a beautiful weekly HTML SEO report covering:
  - SEO opportunity summary (from search_console.py)
  - Top performing keywords
  - Health check summary
  - Jobs posted with SEO metadata
  - Actionable recommendations
  - Keyword ranking changes

Run standalone: python reporter.py
Also called from bot1.py scheduler on weekly schedule.
"""

import os
import sys
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Force UTF-8 encoding for stdout and stderr to prevent UnicodeEncodeErrors on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace') # type: ignore
    except AttributeError:
        pass
if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace') # type: ignore
    except AttributeError:
        pass

load_dotenv(override=True)

# ── Config ────────────────────────────────────────────────────────────────────
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://nextjobpost.in")
API_URL = os.getenv("API_URL", "https://nextjobpost-backend-bblz.onrender.com/api/jobs")
API_TOKEN = os.getenv("API_TOKEN", "")
DB_PATH = os.getenv("DATA_DIR", ".") + "/automation.db"
REPORT_OUTPUT = os.getenv("SEO_REPORT_OUTPUT", "weekly_seo_report.html")


# ═══════════════════════════════════════════════════════════════════════════════
# DATA FETCHERS
# ═══════════════════════════════════════════════════════════════════════════════

def _get_opportunities(limit: int = 30) -> list:
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        cur = conn.execute("""
            SELECT query, page, impressions, clicks, ctr, position, opportunity_type, suggestion, date_range
            FROM seo_opportunities
            ORDER BY recorded_at DESC, impressions DESC
            LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        return [{"query": r[0], "page": r[1], "impressions": r[2], "clicks": r[3], "ctr": r[4], "position": r[5], "type": r[6], "suggestion": r[7], "date_range": r[8]} for r in rows]
    except Exception:
        return []


def _get_top_keywords(limit: int = 20) -> list:
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        cur = conn.execute("""
            SELECT keyword, AVG(position) as avg_pos, SUM(impressions) as total_imp, SUM(clicks) as total_clicks
            FROM seo_rankings
            WHERE recorded_at > ?
            GROUP BY keyword
            ORDER BY total_imp DESC
            LIMIT ?
        """, ((datetime.now() - timedelta(days=7)).timestamp(), limit))
        rows = cur.fetchall()
        conn.close()
        return [{"keyword": r[0], "position": round(r[1], 1), "impressions": int(r[2]), "clicks": int(r[3])} for r in rows]
    except Exception:
        return []


async def _get_recent_jobs_with_seo(limit: int = 20) -> list:
    import aiohttp
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_URL}?limit={limit}&sort=-createdAt&fields=title,slug,metaTitle,metaDescription,postType,isGovernment,createdAt",
                headers=headers,
                timeout=15,
            ) as res:
                if res.status == 200:
                    data = await res.json()
                    return data.get("data", [])
    except Exception as e:
        logging.warning(f"[REPORT] Could not fetch recent jobs: {e}")
    return []


def _get_queue_stats() -> dict:
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        total_q = conn.execute("SELECT COUNT(*) FROM job_queue").fetchone()[0]
        total_seen = conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
        total_failed = conn.execute("SELECT COUNT(*) FROM failed_jobs").fetchone()[0]
        recent_failed = conn.execute("SELECT COUNT(*) FROM failed_jobs WHERE timestamp > ?", ((datetime.now() - timedelta(days=7)).timestamp(),)).fetchone()[0]
        conn.close()
        return {"queue": total_q, "seen": total_seen, "failed_total": total_failed, "failed_week": recent_failed}
    except Exception:
        return {"queue": 0, "seen": 0, "failed_total": 0, "failed_week": 0}


# ═══════════════════════════════════════════════════════════════════════════════
# HTML REPORT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _build_html_report(opportunities: list, keywords: list, jobs: list, queue_stats: dict) -> str:
    now = datetime.now()
    week_start = (now - timedelta(days=7)).strftime("%d %b %Y")
    week_end = now.strftime("%d %b %Y")

    jobs_with_seo = [j for j in jobs if j.get("metaTitle")]
    jobs_without_seo = [j for j in jobs if not j.get("metaTitle")]
    seo_coverage = f"{len(jobs_with_seo)}/{len(jobs)}".rstrip("/0") if jobs else "0/0"

    # Opportunity type badges
    type_colors = {
        "high_impressions_low_ctr": "#f59e0b",
        "page_2_ranking": "#3b82f6",
        "top5_no_clicks": "#ef4444",
    }
    type_labels = {
        "high_impressions_low_ctr": "High Impressions, Low CTR",
        "page_2_ranking": "Page 2 — Push to Page 1",
        "top5_no_clicks": "Top 5 but Zero Clicks",
    }

    opp_rows = ""
    for opp in opportunities[:25]:
        opp_type = opp.get("type", "")
        badge_color = type_colors.get(opp_type, "#6b7280")
        badge_label = type_labels.get(opp_type, opp_type)
        ctr_pct = f"{opp.get('ctr', 0) * 100:.1f}%"
        page = opp.get("page", "").replace(SITE_BASE_URL, "")
        opp_rows += f"""
        <tr>
            <td><strong>{opp.get("query", "")}</strong></td>
            <td><a href="{opp.get('page','')}" target="_blank" style="color:#6366f1;text-decoration:none">{page[:50]}</a></td>
            <td style="text-align:center">{int(opp.get("impressions",0)):,}</td>
            <td style="text-align:center">{int(opp.get("clicks",0)):,}</td>
            <td style="text-align:center">{ctr_pct}</td>
            <td style="text-align:center">{opp.get("position",0):.0f}</td>
            <td><span style="background:{badge_color};color:white;padding:2px 8px;border-radius:12px;font-size:11px">{badge_label}</span></td>
        </tr>
        <tr><td colspan="7" style="font-size:12px;color:#6b7280;padding:4px 12px 12px;border-bottom:1px solid #f3f4f6">💡 {opp.get("suggestion","")}</td></tr>
        """

    kw_rows = ""
    for i, kw in enumerate(keywords[:15], 1):
        pos = kw.get("position", 0)
        pos_color = "#22c55e" if pos <= 5 else "#f59e0b" if pos <= 10 else "#6b7280"
        kw_rows += f"""
        <tr>
            <td style="text-align:center;color:#9ca3af">{i}</td>
            <td><strong>{kw.get("keyword","")}</strong></td>
            <td style="text-align:center;color:{pos_color};font-weight:bold">{pos}</td>
            <td style="text-align:center">{kw.get("impressions",0):,}</td>
            <td style="text-align:center">{kw.get("clicks",0):,}</td>
        </tr>
        """

    job_rows = ""
    for job in jobs[:15]:
        has_seo = bool(job.get("metaTitle"))
        icon = "✅" if has_seo else "⚠️"
        slug = job.get("slug", "")
        meta = job.get("metaTitle", "")
        job_rows += f"""
        <tr>
            <td>{icon} <a href="{SITE_BASE_URL}/{slug}" target="_blank" style="color:#6366f1;text-decoration:none">{job.get("title","")[:50]}</a></td>
            <td style="font-size:12px;color:#6b7280">{meta[:60] if meta else '<em style="color:#ef4444">Missing SEO</em>'}</td>
            <td style="text-align:center"><span style="background:{'#dcfce7;color:#16a34a' if job.get('isGovernment') else '#dbeafe;color:#1d4ed8'};padding:2px 8px;border-radius:12px;font-size:11px">{'Govt' if job.get('isGovernment') else 'Private'}</span></td>
        </tr>
        """

    opportunities_html = ""
    if not opportunities:
        opportunities_html = "<p style='color:#64748b;font-size:14px'>No Search Console data available. Configure GSC credentials to see opportunities.</p>"
    else:
        opportunities_html = f"""
    <table>
      <thead><tr><th>Query</th><th>Page</th><th>Impressions</th><th>Clicks</th><th>CTR</th><th>Pos.</th><th>Type</th></tr></thead>
      <tbody>{opp_rows}</tbody>
    </table>"""

    keywords_html = ""
    if not keywords:
        keywords_html = "<p style='color:#64748b;font-size:14px'>Keyword ranking data will appear here once GSC is configured.</p>"
    else:
        keywords_html = f"""
    <table>
      <thead><tr><th>#</th><th>Keyword</th><th>Avg Position</th><th>Impressions</th><th>Clicks</th></tr></thead>
      <tbody>{kw_rows}</tbody>
    </table>"""

    jobs_html = ""
    if not jobs:
        jobs_html = "<p style='color:#64748b;font-size:14px'>No recent jobs found.</p>"
    else:
        jobs_html = f"""
    <table>
      <thead><tr><th>Job Title</th><th>Meta Title</th><th>Type</th></tr></thead>
      <tbody>{job_rows}</tbody>
    </table>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>NextJobPost Weekly SEO Report — {week_end}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8fafc;color:#1e293b;line-height:1.6}}
.container{{max-width:1100px;margin:0 auto;padding:32px 16px}}
.header{{background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;border-radius:16px;padding:40px;margin-bottom:32px;text-align:center}}
.header h1{{font-size:28px;margin-bottom:8px}}
.header p{{opacity:.8;font-size:15px}}
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:32px}}
.stat-card{{background:white;border-radius:12px;padding:24px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.stat-card .value{{font-size:36px;font-weight:700;color:#6366f1}}
.stat-card .label{{font-size:13px;color:#64748b;margin-top:4px}}
.section{{background:white;border-radius:12px;padding:24px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.section h2{{font-size:18px;margin-bottom:16px;display:flex;align-items:center;gap:8px;padding-bottom:12px;border-bottom:1px solid #f1f5f9}}
table{{width:100%;border-collapse:collapse}}
th{{background:#f8fafc;padding:10px 12px;text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:#64748b;border-bottom:2px solid #e2e8f0}}
td{{padding:10px 12px;border-bottom:1px solid #f1f5f9;font-size:14px}}
tr:last-child td{{border-bottom:none}}
.badge-green{{background:#dcfce7;color:#16a34a;padding:3px 10px;border-radius:12px;font-size:12px}}
.badge-yellow{{background:#fef9c3;color:#854d0e;padding:3px 10px;border-radius:12px;font-size:12px}}
.badge-red{{background:#fee2e2;color:#dc2626;padding:3px 10px;border-radius:12px;font-size:12px}}
.footer{{text-align:center;color:#94a3b8;font-size:13px;margin-top:32px}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📊 NextJobPost Weekly SEO Report</h1>
    <p>Performance period: {week_start} – {week_end}</p>
    <p style="margin-top:8px;font-size:13px;opacity:.7">Generated automatically by the SEO Automation Engine</p>
  </div>

  <!-- STATS GRID -->
  <div class="stats-grid">
    <div class="stat-card">
      <div class="value">{len(opportunities)}</div>
      <div class="label">SEO Opportunities Found</div>
    </div>
    <div class="stat-card">
      <div class="value">{len(keywords)}</div>
      <div class="label">Tracked Keywords</div>
    </div>
    <div class="stat-card">
      <div class="value">{seo_coverage}</div>
      <div class="label">Jobs with SEO Metadata</div>
    </div>
    <div class="stat-card">
      <div class="value">{queue_stats.get("seen",0):,}</div>
      <div class="label">Total Jobs Processed</div>
    </div>
    <div class="stat-card">
      <div class="value">{queue_stats.get("failed_week",0)}</div>
      <div class="label">Failed Posts (7 days)</div>
    </div>
  </div>

  <!-- SEO OPPORTUNITIES TABLE -->
  <div class="section">
    <h2>🎯 SEO Opportunities
      <span style="font-size:13px;background:#f1f5f9;padding:3px 10px;border-radius:20px;font-weight:400;margin-left:auto">
        {len(opportunities)} total
      </span>
    </h2>
    {opportunities_html}
  </div>

  <!-- TOP KEYWORDS TABLE -->
  <div class="section">
    <h2>🔑 Top Ranking Keywords</h2>
    {keywords_html}
  </div>

  <!-- RECENT JOBS WITH SEO -->
  <div class="section">
    <h2>📄 Recent Jobs – SEO Coverage</h2>
    {jobs_html}
    {f'<p style="margin-top:12px;font-size:13px;color:#ef4444">⚠️ {len(jobs_without_seo)} jobs are missing SEO metadata — health checker will auto-fix these.</p>' if jobs_without_seo else ''}
  </div>

  <!-- RECOMMENDATIONS -->
  <div class="section">
    <h2>💡 This Week's Action Items</h2>
    <ol style="padding-left:20px;line-height:2">
      <li>Review the top 5 SEO opportunities above and update meta titles/descriptions for those pages</li>
      <li>Add internal links from high-traffic pages to newer job posts</li>
      <li>Ensure all job posts from the last 7 days have <code>metaTitle</code> set (check "SEO Coverage" above)</li>
      <li>Run <code>python health_checker.py</code> to auto-fix any missing SEO metadata</li>
      <li>Check Google Search Console manually for any manual actions or indexing issues</li>
    </ol>
  </div>

  <div class="footer">
    <p>NextJobPost SEO Automation Engine • Generated {now.strftime("%d %b %Y at %H:%M")} IST</p>
    <p style="margin-top:4px">To disable this report, remove the reporter.py weekly schedule from bot1.py</p>
  </div>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN REPORTER
# ═══════════════════════════════════════════════════════════════════════════════

async def generate_weekly_report() -> str:
    """
    Generates the weekly HTML SEO report.
    Returns the path to the generated report file.
    Called from bot1.py scheduler once per week.
    """
    logging.info("[REPORT] ────────── Generating Weekly SEO Report ──────────")

    # Gather all data
    opportunities = _get_opportunities(50)
    keywords = _get_top_keywords(20)
    jobs = await _get_recent_jobs_with_seo(20)
    queue_stats = _get_queue_stats()

    logging.info(f"[REPORT] 📊 {len(opportunities)} opportunities | {len(keywords)} keywords | {len(jobs)} jobs")

    # Build HTML
    html = _build_html_report(opportunities, keywords, jobs, queue_stats)

    # Save to file
    output_path = REPORT_OUTPUT
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logging.info(f"[REPORT] ✅ Weekly SEO report saved to: {output_path}")
    logging.info("[REPORT] ─────────────────────────────────────────────────")

    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv(override=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    path = asyncio.run(generate_weekly_report())
    print(f"\n✅ Report generated: {path}")
    print(f"Open in browser: file:///{os.path.abspath(path)}")
