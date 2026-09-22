from __future__ import annotations

from datetime import datetime
from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

try:
    from siriconsumer.version import __version__
except ImportError:
    __version__ = "0.0.0"

router = APIRouter(tags=["status"])


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024

    return f"{value} B"


def _status_class(status: str) -> str:
    normalized = status.lower()
    if normalized == "active":
        return "ok"
    if normalized in {"creating", "terminating"}:
        return "progress"
    if normalized == "degraded":
        return "warn"

    return "error"


@router.get("/status", response_class=HTMLResponse, include_in_schema=False)
async def status_page(request: Request) -> HTMLResponse:
    services = request.app.state.services
    records = await services.repository.list_all()

    rows: list[str] = []
    total_spool_bytes = 0
    active_count = 0

    for record in records:
        config = record.config
        spool_bytes = services.spool.payload_size_bytes(config.subscription_ref)
        total_spool_bytes += spool_bytes
        if record.status.value.lower() == "active":
            active_count += 1

        rows.append(
            "<tr>"
            f'<td class="mono">{escape(config.subscription_ref)}</td>'
            f"<td>{escape(config.profile)}</td>"
            f"<td>{escape(config.version)}</td>"
            f"<td>{escape(_format_datetime(config.initial_termination_time))}</td>"
            f'<td><span class="chip {_status_class(record.status.value)}">'
            f"{escape(record.status.value)}</span></td>"
            f"<td>{escape(_format_datetime(record.last_message_at))}</td>"
            f"<td>{escape(_format_datetime(record.last_heartbeat_at))}</td>"
            f'<td class="numeric" title="{spool_bytes} bytes">{escape(_format_bytes(spool_bytes))}</td>'
            "</tr>"
        )

    table_body = "".join(rows) if rows else (
        '<tr><td class="empty" colspan="8">No subscriptions configured.</td></tr>'
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="15">
  <title>SIRI Consumer Status</title>
  <style>
    :root {{
      color-scheme: light dark;
      --md-primary: #6750a4; --md-on-primary: #fff; --md-surface: #fffbfe;
      --md-container: #f3edf7; --md-on-surface: #1d1b20; --md-outline: #79747e;
      --md-ok: #146c2e; --md-ok-bg: #c4eed0; --md-warn: #7a5900; --md-warn-bg: #ffdea6;
      --md-error: #ba1a1a; --md-error-bg: #ffdad6; --md-progress: #415f91; --md-progress-bg: #d6e3ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:var(--md-surface); color:var(--md-on-surface);
      font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    header {{ background:var(--md-primary); color:var(--md-on-primary); padding:20px 32px; }}
    header h1 {{ margin:0; font-size:22px; font-weight:500; }}
    header p {{ margin:3px 0 0; opacity:.82; }}
    main {{ max-width:1440px; margin:0 auto; padding:24px 32px 40px; }}
    .summary {{ display:grid; grid-template-columns:repeat(4,minmax(150px,1fr)); gap:12px; margin-bottom:24px; }}
    .card {{ background:var(--md-container); border-radius:12px; padding:16px 18px; }}
    .label {{ color:var(--md-outline); font-size:12px; font-weight:600; letter-spacing:.04em; text-transform:uppercase; }}
    .value {{ margin-top:5px; font-size:22px; font-weight:500; }}
    h2 {{ margin:0 0 12px; font-size:18px; font-weight:500; }}
    .table-wrap {{ overflow-x:auto; border:1px solid color-mix(in srgb,var(--md-outline) 35%,transparent); border-radius:12px; }}
    table {{ width:100%; border-collapse:collapse; white-space:nowrap; }}
    th,td {{ padding:13px 14px; text-align:left; border-bottom:1px solid color-mix(in srgb,var(--md-outline) 22%,transparent); }}
    th {{ background:var(--md-container); font-size:12px; font-weight:600; letter-spacing:.025em; }}
    tbody tr:last-child td {{ border-bottom:0; }}
    tbody tr:hover {{ background:color-mix(in srgb,var(--md-primary) 5%,transparent); }}
    .numeric {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
    .chip {{ display:inline-block; border-radius:999px; padding:4px 9px; font-size:12px; font-weight:600; text-transform:uppercase; }}
    .chip.ok {{ color:var(--md-ok); background:var(--md-ok-bg); }}
    .chip.warn {{ color:var(--md-warn); background:var(--md-warn-bg); }}
    .chip.error {{ color:var(--md-error); background:var(--md-error-bg); }}
    .chip.progress {{ color:var(--md-progress); background:var(--md-progress-bg); }}
    .empty {{ color:var(--md-outline); text-align:center; padding:32px; }}
    footer {{ margin-top:12px; color:var(--md-outline); font-size:12px; }}
    @media(max-width:800px) {{ header {{ padding:18px 16px; }} main {{ padding:18px 16px 32px; }}
      .summary {{ grid-template-columns:repeat(2,1fr); }} }}
    @media(prefers-color-scheme:dark) {{ :root {{ --md-surface:#141218; --md-container:#211f26;
      --md-on-surface:#e6e0e9; --md-outline:#938f99; }} }}
  </style>
</head>
<body>
  <header><h1>SIRI Consumer</h1><p>Status overview · version {escape(__version__)}</p></header>
  <main>
    <section class="summary" aria-label="Consumer status">
      <div class="card"><div class="label">Consumer</div><div class="value">Running</div></div>
      <div class="card"><div class="label">Subscriptions</div><div class="value">{len(records)}</div></div>
      <div class="card"><div class="label">Active</div><div class="value">{active_count}</div></div>
      <div class="card"><div class="label">Spool payload</div><div class="value">{escape(_format_bytes(total_spool_bytes))}</div></div>
    </section>
    <section><h2>Subscriptions</h2><div class="table-wrap"><table>
      <thead><tr><th>ID</th><th>Profile</th><th>Version</th><th>Termination time</th><th>Status</th>
      <th>Last data received</th><th>Last heartbeat</th><th class="numeric">Spool size</th></tr></thead>
      <tbody>{table_body}</tbody>
    </table></div>
    <footer>Spool size counts payload bytes only, excluding metadata. Page refreshes every 15 seconds.</footer>
    </section>
  </main>
</body>
</html>"""
    return HTMLResponse(html)
