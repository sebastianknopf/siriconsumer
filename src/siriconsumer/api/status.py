from __future__ import annotations

from datetime import datetime
from html import escape
from urllib.parse import quote

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


def _action_buttons(subscription_ref: str) -> str:
    encoded_ref = quote(subscription_ref, safe="")
    label_ref = escape(subscription_ref, quote=True)
    return (
        '<div class="actions">'
        f'<button class="icon-button download-logs" type="button" data-ref="{label_ref}" '
        f'data-url="/api/subscriptions/{encoded_ref}/logs/download" title="Download Logs" aria-label="Download logs for {label_ref}">'
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 20h14v-2H5v2Zm7-18v10.17l3.59-3.58L17 10l-5 5-5-5 1.41-1.41L11 12.17V2h1Z"/></svg></button>'
        f'<button class="icon-button clear-logs" type="button" data-ref="{label_ref}" '
        f'data-url="/api/subscriptions/{encoded_ref}/logs" title="Clear Logs" aria-label="Clear logs for {label_ref}">'
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m16.24 3.56 4.2 4.2a2 2 0 0 1 0 2.83l-8.49 8.48a2 2 0 0 1-2.83 0l-5.56-5.55a2 2 0 0 1 0-2.83l9.85-9.85 2.83 2.72ZM4.97 12.1l5.56 5.56.71-.71-5.56-5.56-.71.71ZM3 21v-2h18v2H3Z"/></svg></button>'
        '</div>'
    )


@router.get("/status", response_class=HTMLResponse, include_in_schema=False)
async def status_page(request: Request) -> HTMLResponse:
    services = request.app.state.services
    records = await services.repository.list_all()
    rows: list[str] = []
    total_spool_bytes = 0
    total_spool_files = 0
    active_count = 0

    for record in records:
        config = record.config
        spool_bytes = services.spool.payload_size_bytes(config.subscription_ref)
        spool_files = services.spool.pending_count(config.subscription_ref)
        total_spool_bytes += spool_bytes
        total_spool_files += spool_files
        if record.status.value.lower() == "active":
            active_count += 1
        rows.append(
            "<tr>"
            f'<td class="mono">{escape(config.subscription_ref)}</td>'
            f"<td>{escape(config.profile)}</td>"
            f"<td>{escape(config.version)}</td>"
            f"<td>{'Yes' if config.mtls is not None else 'No'}</td>"
            f"<td>{escape(_format_datetime(config.initial_termination_time))}</td>"
            f'<td><span class="chip {_status_class(record.status.value)}">{escape(record.status.value)}</span></td>'
            f"<td>{escape(_format_datetime(record.last_message_at))}</td>"
            f"<td>{escape(_format_datetime(record.last_heartbeat_at))}</td>"
            f'<td class="numeric" title="{spool_bytes} bytes / {spool_files} data files">{escape(_format_bytes(spool_bytes))} / {spool_files}</td>'
            f"<td>{'Active' if config.logging else 'Inactive'}</td>"
            f"<td>{_action_buttons(config.subscription_ref)}</td>"
            "</tr>"
        )

    table_body = "".join(rows) if rows else '<tr><td class="empty" colspan="11">No Subscriptions Configured.</td></tr>'
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SIRI Consumer Status</title><style>
:root {{ color-scheme:light dark; --md-primary:#008c99; --md-secondary:#99cc04; --md-on-primary:#fff; --md-surface:#fbfcf8; --md-container:#f0f4eb; --md-on-surface:#1b1d1a; --md-outline:#747970; --md-ok:#146c2e; --md-ok-bg:#c4eed0; --md-warn:#7a5900; --md-warn-bg:#ffdea6; --md-error:#ba1a1a; --md-error-bg:#ffdad6; --md-progress:#008c99; --md-progress-bg:#d9f2f4; }}
* {{ box-sizing:border-box }} body {{ margin:0;background:var(--md-surface);color:var(--md-on-surface);font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif }}
header {{ background:var(--md-primary);color:var(--md-on-primary);padding:20px 32px }} header h1 {{ margin:0;font-size:22px;font-weight:500 }} header p {{ margin:3px 0 0;opacity:.85 }}
main {{ max-width:1600px;margin:0 auto;padding:24px 32px 40px }} .summary {{ display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:12px;margin-bottom:24px }}
.card {{ background:var(--md-container);border-top:3px solid var(--md-secondary);border-radius:12px;padding:16px 18px }} .label {{ color:var(--md-outline);font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase }} .value {{ margin-top:5px;font-size:22px;font-weight:500 }}
.table-heading {{ display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:12px }} h2 {{ margin:0;font-size:18px;font-weight:500 }} .refresh-button {{ display:inline-flex;align-items:center;gap:8px;padding:9px 16px;border:0;border-radius:20px;background:var(--md-secondary);color:#1b1d1a;font:600 14px/1 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;cursor:pointer;box-shadow:0 1px 2px color-mix(in srgb,#000 25%,transparent) }} .refresh-button:hover {{ filter:brightness(.96) }} .refresh-button:focus-visible {{ outline:2px solid var(--md-primary);outline-offset:2px }} .refresh-button svg {{ width:18px;height:18px;fill:currentColor }} .table-wrap {{ overflow-x:auto;border:1px solid color-mix(in srgb,var(--md-outline) 35%,transparent);border-radius:12px }} table {{ width:100%;border-collapse:collapse;white-space:nowrap }} th,td {{ padding:13px 14px;text-align:left;border-bottom:1px solid color-mix(in srgb,var(--md-outline) 22%,transparent) }} th {{ background:var(--md-container);font-size:12px;font-weight:600;letter-spacing:.025em }} tbody tr:last-child td {{ border-bottom:0 }} tbody tr:hover {{ background:color-mix(in srgb,var(--md-primary) 5%,transparent) }}
.numeric {{ text-align:right;font-variant-numeric:tabular-nums }} .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace }} .chip {{ display:inline-block;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:600;text-transform:uppercase }} .chip.ok {{ color:var(--md-ok);background:var(--md-ok-bg) }} .chip.warn {{ color:var(--md-warn);background:var(--md-warn-bg) }} .chip.error {{ color:var(--md-error);background:var(--md-error-bg) }} .chip.progress {{ color:var(--md-progress);background:var(--md-progress-bg) }}
.actions {{ display:flex;align-items:center;gap:4px }} .icon-button {{ display:inline-grid;place-items:center;width:36px;height:36px;padding:0;border:0;border-radius:50%;color:var(--md-primary);background:transparent;cursor:pointer }} .icon-button:hover {{ background:color-mix(in srgb,var(--md-primary) 12%,transparent) }} .icon-button:focus-visible {{ outline:2px solid var(--md-secondary);outline-offset:2px }} .icon-button:disabled {{ opacity:.4;cursor:wait }} .icon-button svg {{ width:20px;height:20px;fill:currentColor }}
.empty {{ color:var(--md-outline);text-align:center;padding:32px }} footer {{ margin-top:12px;color:var(--md-outline);font-size:12px }} @media(max-width:800px) {{ header {{ padding:18px 16px }} main {{ padding:18px 16px 32px }} .summary {{ grid-template-columns:repeat(2,1fr) }} }} @media(prefers-color-scheme:dark) {{ :root {{ --md-surface:#101516;--md-container:#192224;--md-on-surface:#e2e8e9;--md-outline:#98a3a5;--md-progress-bg:#173f43 }} }}
</style></head><body><header><h1>SIRI Consumer</h1><p>Version {escape(__version__)}</p></header><main>
<section class="summary" aria-label="Consumer Status"><div class="card"><div class="label">Consumer</div><div class="value">Running</div></div><div class="card"><div class="label">Subscriptions</div><div class="value">{len(records)}</div></div><div class="card"><div class="label">Active</div><div class="value">{active_count}</div></div><div class="card"><div class="label">Spool Payload</div><div class="value">{escape(_format_bytes(total_spool_bytes))} / {total_spool_files}</div></div></section>
<section><div class="table-heading"><h2>Subscriptions</h2><button class="refresh-button" type="button" onclick="window.location.reload()" title="Refresh Status"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.65 6.35A7.95 7.95 0 0 0 12 4a8 8 0 1 0 7.75 10h-2.1A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35Z"/></svg>Refresh</button></div><div class="table-wrap"><table><thead><tr><th>ID</th><th>Profile</th><th>Version</th><th>mTLS</th><th>Termination Time</th><th>Status</th><th>Last Data Received</th><th>Last Heartbeat</th><th class="numeric">Spool Size</th><th>Logging</th><th>Actions</th></tr></thead><tbody>{table_body}</tbody></table></div><footer>Spool Size shows payload bytes / data files only, excluding metadata.</footer></section></main>
<script>
async function downloadLogs(button) {{ button.disabled=true; try {{ const response=await fetch(button.dataset.url); if(!response.ok) throw new Error(`Download failed (${{response.status}})`); const blob=await response.blob(); const objectUrl=URL.createObjectURL(blob); const link=document.createElement("a"); link.href=objectUrl; link.download=`${{button.dataset.ref}}-logs.zip`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(objectUrl); }} catch(error) {{ window.alert(error.message); }} finally {{ button.disabled=false; }} }}
async function clearLogs(button) {{ if(!window.confirm(`Clear all communication logs for ${{button.dataset.ref}}?`)) return; button.disabled=true; try {{ const response=await fetch(button.dataset.url,{{method:"DELETE"}}); if(!response.ok) throw new Error(`Clear failed (${{response.status}})`); }} catch(error) {{ window.alert(error.message); }} finally {{ button.disabled=false; }} }}
document.addEventListener("click",event=>{{ const downloadButton=event.target.closest(".download-logs"); if(downloadButton) {{ downloadLogs(downloadButton); return; }} const clearButton=event.target.closest(".clear-logs"); if(clearButton) clearLogs(clearButton); }});
</script></body></html>'''
    return HTMLResponse(html)
