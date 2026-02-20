import os
import shutil
import subprocess
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.panel import Panel

from pastepy import __version__
from pastepy.config import APP_DIR, LAUNCHD_LABEL, LAUNCHD_PLIST, PID_FILE
from pastepy.db import (
    clear_all,
    delete_item,
    get_item,
    get_items,
    get_stats,
    init_db,
    bump_item,
)
from pastepy.monitor import ClipboardMonitor, is_running, stop_daemon

app = typer.Typer(
    name="pst",
    help="A lightweight macOS clipboard manager.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


# ── Daemon commands ──────────────────────────────────────────────

@app.command()
def start(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground (don't daemonize)."),
):
    """Start the clipboard monitor daemon."""
    running, pid = is_running()
    if running:
        console.print(f"[yellow]Daemon already running (PID: {pid})[/yellow]")
        raise typer.Exit()

    init_db()

    if foreground:
        console.print("[green]Starting clipboard monitor (foreground)...[/green]")
        monitor = ClipboardMonitor()
        monitor.start()
    else:
        # Daemonize by spawning a background process
        APP_DIR.mkdir(parents=True, exist_ok=True)
        log_file = open(APP_DIR / "daemon.log", "a")
        proc = subprocess.Popen(
            [sys.executable, "-m", "pastepy", "start", "--foreground"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log_file.close()
        import time
        time.sleep(0.5)
        running, pid = is_running()
        if running:
            console.print(f"[green]Daemon started (PID: {pid})[/green]")
        else:
            console.print(f"[green]Daemon starting (PID: {proc.pid})[/green]")


@app.command()
def stop():
    """Stop the clipboard monitor daemon."""
    if stop_daemon():
        console.print("[green]Daemon stopped.[/green]")
    else:
        console.print("[yellow]No daemon running.[/yellow]")


@app.command()
def status():
    """Check if the daemon is running."""
    running, pid = is_running()
    if running:
        console.print(f"[green]Daemon is running (PID: {pid})[/green]")
    else:
        console.print("[dim]Daemon is not running.[/dim]")


@app.command()
def restart():
    """Restart the clipboard monitor daemon."""
    stop_daemon()
    import time
    time.sleep(0.3)
    APP_DIR.mkdir(parents=True, exist_ok=True)
    log_file = open(APP_DIR / "daemon.log", "a")
    subprocess.Popen(
        [sys.executable, "-m", "pastepy", "start", "--foreground"],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_file.close()
    time.sleep(0.5)
    running, pid = is_running()
    if running:
        console.print(f"[green]Daemon restarted (PID: {pid})[/green]")
    else:
        console.print("[green]Daemon restarting...[/green]")


# ── History commands ─────────────────────────────────────────────

@app.command(name="list")
def list_items(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of items to show."),
    type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by type: text, image, file."),
    app_filter: Optional[str] = typer.Option(None, "--app", "-a", help="Filter by source app name."),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Search content."),
):
    """List clipboard history."""
    init_db()
    items = get_items(limit=limit, content_type=type, app=app_filter, search=search)

    if not items:
        console.print("[dim]No items found.[/dim]")
        raise typer.Exit()

    table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    table.add_column("ID", style="dim", width=5, justify="right")
    table.add_column("Type", width=5)
    table.add_column("Content", min_width=30, max_width=60)
    table.add_column("App", style="dim", width=14)
    table.add_column("Time", style="green", width=12)

    for item in items:
        content = item["content"]
        ctype = item["content_type"]

        if ctype == "image":
            preview = "[Image]"
        elif ctype == "file":
            paths = content.split("\n")
            preview = paths[0] if len(paths) == 1 else f"[{len(paths)} files]"
        else:
            preview = content.replace("\n", " ").replace("\t", " ").strip()
            if len(preview) > 55:
                preview = preview[:54] + "\u2026"

        type_badge = {"text": "[white]TXT[/white]", "image": "[yellow]IMG[/yellow]", "file": "[blue]FILE[/blue]"}.get(ctype, ctype)

        from datetime import datetime
        try:
            dt = datetime.strptime(item["last_used_at"], "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            diff = now - dt
            if diff.days == 0:
                if diff.seconds < 60:
                    time_str = "just now"
                elif diff.seconds < 3600:
                    time_str = f"{diff.seconds // 60}m ago"
                else:
                    time_str = f"{diff.seconds // 3600}h ago"
            elif diff.days == 1:
                time_str = "yesterday"
            elif diff.days < 7:
                time_str = f"{diff.days}d ago"
            else:
                time_str = dt.strftime("%b %d")
        except Exception:
            time_str = item["last_used_at"]

        app_name = item["source_app"] or ""
        if item["source_url"]:
            try:
                from urllib.parse import urlparse
                domain = urlparse(item["source_url"]).netloc
                if domain:
                    app_name = domain
            except Exception:
                pass

        table.add_row(str(item["id"]), type_badge, preview, app_name, time_str)

    console.print(table)


@app.command()
def show(item_id: int = typer.Argument(..., help="Item ID to show.")):
    """Show full details of a clipboard item."""
    init_db()
    item = get_item(item_id)
    if not item:
        console.print(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    meta_lines = []
    meta_lines.append(f"[bold]ID:[/bold] {item['id']}")
    meta_lines.append(f"[bold]Type:[/bold] {item['content_type']}")
    meta_lines.append(f"[bold]Size:[/bold] {item['size_bytes']} bytes")
    meta_lines.append(f"[bold]Copied:[/bold] {item['created_at']}")
    meta_lines.append(f"[bold]Last used:[/bold] {item['last_used_at']}")
    meta_lines.append(f"[bold]Use count:[/bold] {item['use_count']}")
    if item["source_app"]:
        meta_lines.append(f"[bold]App:[/bold] {item['source_app']}")
    if item["source_url"]:
        meta_lines.append(f"[bold]URL:[/bold] {item['source_url']}")

    console.print(Panel("\n".join(meta_lines), title="Metadata", border_style="cyan"))

    if item["content_type"] == "image":
        console.print(Panel("[dim]<base64 image data>[/dim]", title="Content", border_style="dim"))
    else:
        console.print(Panel(item["content"], title="Content", border_style="dim"))


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query."),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results."),
):
    """Search clipboard history."""
    init_db()
    items = get_items(limit=limit, search=query)
    if not items:
        console.print(f"[dim]No results for '{query}'[/dim]")
        raise typer.Exit()

    # Reuse list display
    list_items(limit=limit, type=None, app_filter=None, search=query)


@app.command()
def copy(item_id: int = typer.Argument(..., help="Item ID to copy to clipboard.")):
    """Copy a history item back to the clipboard."""
    init_db()
    item = get_item(item_id)
    if not item:
        console.print(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    from pastepy.picker import copy_to_clipboard
    copy_to_clipboard(item["content"], item["content_type"])
    bump_item(item_id)

    preview = item["content"][:60] + "\u2026" if len(item["content"]) > 60 else item["content"]
    if item["content_type"] == "image":
        preview = "[Image]"
    console.print(f"[green]Copied:[/green] {preview}")


@app.command()
def pick(
    tui: bool = typer.Option(False, "--tui", help="Use terminal picker instead of native GUI."),
):
    """Interactive picker to select from clipboard history."""
    init_db()
    if tui:
        from pastepy.picker import run_picker, copy_to_clipboard

        selected = run_picker()
        if selected:
            copy_to_clipboard(selected["content"], selected["content_type"])
            bump_item(selected["id"])
            preview = selected["content"][:60] if selected["content_type"] != "image" else "[Image]"
            console.print(f"[green]Copied:[/green] {preview}")
        else:
            console.print("[dim]Cancelled.[/dim]")
    else:
        import subprocess
        subprocess.run([sys.executable, "-m", "pastepy.gui"])


@app.command()
def delete(item_id: int = typer.Argument(..., help="Item ID to delete.")):
    """Delete an item from history."""
    init_db()
    if delete_item(item_id):
        console.print(f"[green]Deleted item {item_id}.[/green]")
    else:
        console.print(f"[red]Item {item_id} not found.[/red]")


@app.command()
def clear(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation."),
):
    """Clear all clipboard history."""
    init_db()
    if not force:
        stats = get_stats()
        confirm = typer.confirm(f"Delete all {stats['total']} items?")
        if not confirm:
            raise typer.Abort()
    count = clear_all()
    console.print(f"[green]Cleared {count} items.[/green]")


@app.command()
def stats():
    """Show clipboard history statistics."""
    init_db()
    s = get_stats()
    console.print(Panel(
        f"[bold]Total items:[/bold] {s['total']}\n"
        f"[bold]Text:[/bold] {s['text']}\n"
        f"[bold]Images:[/bold] {s['image']}\n"
        f"[bold]Files:[/bold] {s['file']}\n"
        f"[bold]DB size:[/bold] {s['db_size_mb']} MB",
        title="Clipboard Stats",
        border_style="cyan",
    ))


# ── Service (launchd) commands ───────────────────────────────────

service_app = typer.Typer(help="Manage the background service (launchd).")
app.add_typer(service_app, name="service")


@service_app.command(name="install")
def service_install():
    """Install the daemon as a macOS launch agent (auto-start on login)."""
    pst_bin = shutil.which("pst")
    if not pst_bin:
        # Fallback: use python -m
        python_bin = sys.executable
        pst_bin = None

    if pst_bin:
        program_args = f"""    <array>
        <string>{pst_bin}</string>
        <string>start</string>
        <string>--foreground</string>
    </array>"""
    else:
        python_bin = sys.executable
        program_args = f"""    <array>
        <string>{python_bin}</string>
        <string>-m</string>
        <string>pastepy</string>
        <string>start</string>
        <string>--foreground</string>
    </array>"""

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
{program_args}
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{APP_DIR / "daemon.log"}</string>
    <key>StandardErrorPath</key>
    <string>{APP_DIR / "daemon.log"}</string>
</dict>
</plist>
"""
    LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    LAUNCHD_PLIST.write_text(plist_content)
    subprocess.run(["launchctl", "load", str(LAUNCHD_PLIST)], check=True)
    console.print(f"[green]Service installed and started.[/green]")
    console.print(f"[dim]Plist: {LAUNCHD_PLIST}[/dim]")


@service_app.command(name="uninstall")
def service_uninstall():
    """Remove the launch agent."""
    if LAUNCHD_PLIST.exists():
        subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST)], check=False)
        LAUNCHD_PLIST.unlink()
        console.print("[green]Service uninstalled.[/green]")
    else:
        console.print("[yellow]Service not installed.[/yellow]")
    stop_daemon()


@service_app.command(name="status")
def service_status():
    """Check the launch agent status."""
    if LAUNCHD_PLIST.exists():
        result = subprocess.run(
            ["launchctl", "list", LAUNCHD_LABEL],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print(f"[green]Service is loaded.[/green]")
            running, pid = is_running()
            if running:
                console.print(f"[green]Daemon running (PID: {pid})[/green]")
            else:
                console.print("[yellow]Daemon not running (service loaded but process not found).[/yellow]")
        else:
            console.print("[yellow]Service plist exists but not loaded.[/yellow]")
    else:
        console.print("[dim]Service not installed.[/dim]")


# ── Hotkey setup ─────────────────────────────────────────────────

@app.command()
def hotkey():
    """Show instructions to set up a global hotkey for the picker."""
    init_db()
    pst_bin = shutil.which("pst")
    if pst_bin:
        pick_cmd = f"{pst_bin} pick"
    else:
        pick_cmd = f"{sys.executable} -m pastepy pick"

    # Build an AppleScript that opens Terminal, runs pst pick, and closes
    applescript = (
        f'tell application "Terminal"\n'
        f'    activate\n'
        f'    set w to do script "{pick_cmd}"\n'
        f'    repeat\n'
        f'        delay 0.5\n'
        f'        if not busy of w then exit repeat\n'
        f'    end repeat\n'
        f'    close (every window whose name contains "pst")\n'
        f'end tell'
    )

    console.print(Panel(
        "[bold]Option 1: macOS Automator + Keyboard Shortcut[/bold]\n"
        "1. Open Automator > New > Quick Action\n"
        "2. Add 'Run Shell Script' action\n"
        f"3. Set shell command to: [cyan]{pick_cmd}[/cyan]\n"
        "4. Save as 'Paste Picker'\n"
        "5. System Settings > Keyboard > Shortcuts > Services\n"
        "6. Assign a shortcut (e.g. Cmd+Shift+V)\n"
        "\n"
        "[bold]Option 2: skhd (if installed)[/bold]\n"
        f'Add to ~/.skhdrc: [cyan]cmd + shift - v : open -a Terminal "{pick_cmd}"[/cyan]\n'
        "\n"
        "[bold]Option 3: Raycast / Alfred[/bold]\n"
        f"Create a script command that runs: [cyan]{pick_cmd}[/cyan]\n",
        title="Global Hotkey Setup",
        border_style="cyan",
    ))


# ── Version ──────────────────────────────────────────────────────

def version_callback(value: bool):
    if value:
        console.print(f"pst v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True, help="Show version."),
):
    """pst - A lightweight macOS clipboard manager."""
    pass
