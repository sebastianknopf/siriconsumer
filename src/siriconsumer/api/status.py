from __future__ import annotations



from datetime import UTC, datetime

from html import escape

from pathlib import Path

from urllib.parse import quote



from fastapi import APIRouter, Request

from fastapi.responses import HTMLResponse



from siriconsumer.api.subscription_logs import COMMUNICATION_LOG_ROOT, log_generation



try:

    from siriconsumer.version import __version__

except ImportError:

    __version__ = "0.0.0"



router = APIRouter(tags=["status"])





def _format_datetime(value: datetime | None) -> str:

    if value is None:

        return "—"

    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")





def _format_generation(generation: str) -> str:
    try:
        value = datetime.strptime(generation, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
    except ValueError:
        return generation
    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


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





def _log_stats(path: Path) -> tuple[int, int]:

    size = 0

    count = 0

    if not path.is_dir():

        return size, count

    for item in path.rglob("*.xml"):

        try:

            size += item.stat().st_size

            count += 1

        except FileNotFoundError:

            continue

    return size, count





def _log_buttons(subscription_ref: str, generation: str | None = None) -> str:

    encoded_ref = quote(subscription_ref, safe="")

    label_ref = escape(subscription_ref, quote=True)

    query = f"?generation={quote(generation, safe='')}" if generation else ""

    return (

        '<div class="actions">'

        f'<button class="icon-button download-logs" type="button" data-ref="{label_ref}" '

        f'data-url="/api/subscriptions/{encoded_ref}/logs/download{query}" title="Download Logs" '

        f'aria-label="Download logs for {label_ref}">'

        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 20h14v-2H5v2Zm7-18v10.17l3.59-3.58L17 10l-5 5-5-5 1.41-1.41L11 12.17V2h1Z"/></svg></button>'

        f'<button class="icon-button clear-logs" type="button" data-ref="{label_ref}" '

        f'data-url="/api/subscriptions/{encoded_ref}/logs{query}" title="Clear Logs" '

        f'aria-label="Clear logs for {label_ref}">'

        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m16.24 3.56 4.2 4.2a2 2 0 0 1 0 2.83l-8.49 8.48a2 2 0 0 1-2.83 0l-5.56-5.55a2 2 0 0 1 0-2.83l9.85-9.85 2.83 2.72ZM4.97 12.1l5.56 5.56.71-.71-5.56-5.56-.71.71ZM3 21v-2h18v2H3Z"/></svg></button>'

        '</div>'

    )





def _subscription_actions(subscription_ref: str) -> str:

    encoded_ref = quote(subscription_ref, safe="")

    label_ref = escape(subscription_ref, quote=True)

    return (

        _log_buttons(subscription_ref)[:-6]

        + f'<button class="icon-button force-terminate" type="button" data-ref="{label_ref}" '

        f'data-url="/api/subscriptions/{encoded_ref}?force" title="Force Terminate" '

        f'aria-label="Force terminate {label_ref}">'

        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 21h-1l1-7H7.5c-.88 0-.33-.75-.31-.78C8.48 10.94 10.42 7.54 13 3h1l-1 7h3.5c.4 0 .62.19.4.66C12.97 17.53 11 21 11 21Z"/></svg></button>'

        '</div>'

    )





def _archived_log_rows(active_generations: set[tuple[str, str]], active_refs: set[str]) -> str:

    rows: list[str] = []

    if not COMMUNICATION_LOG_ROOT.is_dir():

        return '<tr><td class="empty" colspan="5">No Archived Logs.</td></tr>'



    for ref_directory in sorted(path for path in COMMUNICATION_LOG_ROOT.iterdir() if path.is_dir()):

        subscription_ref = ref_directory.name

        for generation_directory in sorted(path for path in ref_directory.iterdir() if path.is_dir()):

            generation = generation_directory.name

            if (subscription_ref, generation) in active_generations:

                continue

            size, count = _log_stats(generation_directory)

            if count == 0:

                continue

            rows.append(

                "<tr>"

                f'<td class="mono">{escape(subscription_ref)}</td>'

                f'<td class="mono">{escape(_format_generation(generation))}</td>'

                f'<td class="numeric">{escape(_format_bytes(size))}</td>'

                f'<td class="numeric">{count}</td>'

                f'<td>{_log_buttons(subscription_ref, generation)}</td>'

                "</tr>"

            )



        # Compatibility for pre-generation flat logs. They are shown only when the ref is inactive,

        # because the legacy API path can then safely address the whole archived directory.

        if subscription_ref not in active_refs:

            flat_files = [path for path in ref_directory.glob("*.xml") if path.is_file()]

            if flat_files:

                size = sum(path.stat().st_size for path in flat_files)

                rows.append(

                    "<tr>"

                    f'<td class="mono">{escape(subscription_ref)}</td>'

                    '<td class="mono">Legacy</td>'

                    f'<td class="numeric">{escape(_format_bytes(size))}</td>'

                    f'<td class="numeric">{len(flat_files)}</td>'

                    f'<td>{_log_buttons(subscription_ref)}</td>'

                    "</tr>"

                )



    return "".join(rows) or '<tr><td class="empty" colspan="5">No Archived Logs.</td></tr>'





@router.get("/status", response_class=HTMLResponse, include_in_schema=False)

async def status_page(request: Request) -> HTMLResponse:

    services = request.app.state.services

    records = await services.repository.list_all()

    rows: list[str] = []

    total_spool_bytes = 0

    total_spool_files = 0

    active_count = 0

    active_generations: set[tuple[str, str]] = set()

    active_refs: set[str] = set()



    for record in records:

        config = record.config

        active_refs.add(config.subscription_ref)

        active_generations.add((quote(config.subscription_ref, safe=""), log_generation(record.created_at)))

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

            f"<td>{_subscription_actions(config.subscription_ref)}</td>"

            "</tr>"

        )



    table_body = "".join(rows) if rows else '<tr><td class="empty" colspan="11">No Subscriptions Configured.</td></tr>'

    archived_rows = _archived_log_rows(active_generations, {quote(ref, safe="") for ref in active_refs})

    html = f'''<!doctype html>

<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">

<title>SIRI Consumer Status</title><style>

:root {{ color-scheme:light dark; --md-primary:#008c99; --md-secondary:#99cc04; --md-on-primary:#fff; --md-surface:#fbfcf8; --md-container:#f0f4eb; --md-on-surface:#1b1d1a; --md-outline:#747970; --md-ok:#146c2e; --md-ok-bg:#c4eed0; --md-warn:#7a5900; --md-warn-bg:#ffdea6; --md-error:#ba1a1a; --md-error-bg:#ffdad6; --md-progress:#008c99; --md-progress-bg:#d9f2f4; }}

* {{ box-sizing:border-box }} body {{ margin:0;background:var(--md-surface);color:var(--md-on-surface);font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif }}

header {{ background:var(--md-primary);color:var(--md-on-primary);padding:20px 32px }} header h1 {{ margin:0;font-size:22px;font-weight:500 }} header p {{ margin:3px 0 0;opacity:.85 }}

main {{ max-width:1600px;margin:0 auto;padding:24px 32px 40px }} .summary {{ display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:12px;margin-bottom:24px }}

.card {{ background:var(--md-container);border-top:3px solid var(--md-secondary);border-radius:12px;padding:16px 18px }} .label {{ color:var(--md-outline);font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase }} .value {{ margin-top:5px;font-size:22px;font-weight:500 }}

.section-header {{ display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 12px }} h2 {{ margin:0;font-size:18px;font-weight:500 }} .archived {{ margin-top:28px }}

.refresh-button {{ display:inline-flex;align-items:center;gap:8px;border:0;border-radius:20px;padding:9px 16px;background:var(--md-secondary);color:#1b1d1a;font:600 14px/1 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;cursor:pointer }} .refresh-button:hover {{ filter:brightness(.96) }} .refresh-button:focus-visible {{ outline:2px solid var(--md-primary);outline-offset:2px }} .refresh-button svg {{ width:18px;height:18px;fill:currentColor }}

.table-wrap {{ overflow-x:auto;border:1px solid color-mix(in srgb,var(--md-outline) 35%,transparent);border-radius:12px }} table {{ width:100%;border-collapse:collapse;white-space:nowrap }} th,td {{ padding:13px 14px;text-align:left;border-bottom:1px solid color-mix(in srgb,var(--md-outline) 22%,transparent) }} th {{ background:var(--md-container);font-size:12px;font-weight:600;letter-spacing:.025em }} tbody tr:last-child td {{ border-bottom:0 }} tbody tr:hover {{ background:color-mix(in srgb,var(--md-primary) 5%,transparent) }}

.numeric {{ text-align:right;font-variant-numeric:tabular-nums }} .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace }} .chip {{ display:inline-block;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:600;text-transform:uppercase }} .chip.ok {{ color:var(--md-ok);background:var(--md-ok-bg) }} .chip.warn {{ color:var(--md-warn);background:var(--md-warn-bg) }} .chip.error {{ color:var(--md-error);background:var(--md-error-bg) }} .chip.progress {{ color:var(--md-progress);background:var(--md-progress-bg) }}

.actions {{ display:flex;align-items:center;gap:4px }} .icon-button {{ display:inline-grid;place-items:center;width:36px;height:36px;padding:0;border:0;border-radius:50%;color:var(--md-primary);background:transparent;cursor:pointer }} .icon-button:hover {{ background:color-mix(in srgb,var(--md-primary) 12%,transparent) }} .icon-button:focus-visible {{ outline:2px solid var(--md-secondary);outline-offset:2px }} .icon-button:disabled {{ opacity:.4;cursor:wait }} .icon-button svg {{ width:20px;height:20px;fill:currentColor }} .force-terminate {{ color:var(--md-error) }}

.empty {{ color:var(--md-outline);text-align:center;padding:32px }} footer {{ margin-top:12px;color:var(--md-outline);font-size:12px }} @media(max-width:800px) {{ header {{ padding:18px 16px }} main {{ padding:18px 16px 32px }} .summary {{ grid-template-columns:repeat(2,1fr) }} }} @media(prefers-color-scheme:dark) {{ :root {{ --md-surface:#101516;--md-container:#192224;--md-on-surface:#e2e8e9;--md-outline:#98a3a5;--md-progress-bg:#173f43 }} }}

</style></head><body><header><h1>SIRI Consumer</h1><p>Version {escape(__version__)}</p></header><main>

<section class="summary" aria-label="Consumer Status"><div class="card"><div class="label">Consumer</div><div class="value">Running</div></div><div class="card"><div class="label">Subscriptions</div><div class="value">{len(records)}</div></div><div class="card"><div class="label">Active</div><div class="value">{active_count}</div></div><div class="card"><div class="label">Spool Payload</div><div class="value">{escape(_format_bytes(total_spool_bytes))} / {total_spool_files}</div></div></section>

<section><div class="section-header"><h2>Subscriptions</h2><button class="refresh-button" type="button" id="refresh-page"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.09 0-7.19 3.72-6.39 7.69l-2.08.68C2.42 7.16 6.38 2 12 2c2.76 0 5.26 1.12 7.07 2.93L22 2v8h-8l3.65-3.65ZM6.35 17.65C7.8 19.1 9.79 20 12 20c4.09 0 7.19-3.72 6.39-7.69l2.08-.68C21.58 16.84 17.62 22 12 22c-2.76 0-5.26-1.12-7.07-2.93L2 22v-8h8l-3.65 3.65Z"/></svg>Refresh</button></div><div class="table-wrap"><table><thead><tr><th>ID</th><th>Profile</th><th>Version</th><th>mTLS</th><th>Termination Time</th><th>Status</th><th>Last Data Received</th><th>Last Heartbeat</th><th class="numeric">Spool Size</th><th>Logging</th><th>Actions</th></tr></thead><tbody>{table_body}</tbody></table></div><footer>Spool Size shows payload bytes / data files only, excluding metadata. Refresh is manual.</footer></section>

<section class="archived"><div class="section-header"><h2>Archived Logs</h2></div><div class="table-wrap"><table><thead><tr><th>Subscription ID</th><th>Generation</th><th class="numeric">Log Size</th><th class="numeric">Files</th><th>Actions</th></tr></thead><tbody>{archived_rows}</tbody></table></div></section></main>

<script>

async function downloadLogs(button) {{ button.disabled=true; try {{ const response=await fetch(button.dataset.url); if(!response.ok) throw new Error(\`Download failed (${{response.status}})\`); const blob=await response.blob(); const objectUrl=URL.createObjectURL(blob); const link=document.createElement("a"); link.href=objectUrl; link.download=\`${{button.dataset.ref}}-logs.zip\`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(objectUrl); }} catch(error) {{ window.alert(error.message); }} finally {{ button.disabled=false; }} }}

async function clearLogs(button) {{ if(!window.confirm(\`Clear all communication logs for ${{button.dataset.ref}}?\`)) return; button.disabled=true; try {{ const response=await fetch(button.dataset.url,{{method:"DELETE"}}); if(!response.ok) throw new Error(\`Clear failed (${{response.status}})\`); window.location.reload(); }} catch(error) {{ window.alert(error.message); button.disabled=false; }} }}

async function forceTerminate(button) {{ if(!window.confirm(\`Force terminate subscription "${{button.dataset.ref}}"?\n\nA termination request will be sent to the producer, but its result will be ignored. Already accepted deliveries and queued spool items will be drained before the subscription is removed.\`)) return; button.disabled=true; try {{ const response=await fetch(button.dataset.url,{{method:"DELETE"}}); if(!response.ok) {{ const detail=await response.text(); throw new Error(\`Force termination failed (${{response.status}}): ${{detail}}\`); }} window.location.reload(); }} catch(error) {{ window.alert(error.message); button.disabled=false; }} }}

document.getElementById("refresh-page").addEventListener("click",()=>window.location.reload());

document.addEventListener("click",event=>{{ const downloadButton=event.target.closest(".download-logs"); if(downloadButton) {{ downloadLogs(downloadButton); return; }} const clearButton=event.target.closest(".clear-logs"); if(clearButton) {{ clearLogs(clearButton); return; }} const forceButton=event.target.closest(".force-terminate"); if(forceButton) forceTerminate(forceButton); }});

</script></body></html>'''

    return HTMLResponse(html)
