"""Ask Claude to explain a device error and suggest a fix.

Credentials come from the environment, as the Anthropic SDK resolves them:
ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN, or an `ant auth login` profile).
"""

from collections.abc import Iterator

import anthropic

from nixync_front.sample_data import Machine, MachineError, Preset
from nixync_front.widgets import timestamp

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """\
You help the administrator of a small fleet of NixOS machines managed by Nixync, a \
desktop app that pushes NixOS configurations to devices over SSH and can roll a device \
back to its previous generation ("Undo update"). The administrator is not necessarily a \
Nix expert.

You'll get one error from one device, with the device's context and any log output. \
Reply in Markdown with these sections:

## What happened
One or two plain sentences.

## Likely cause
The most probable cause given the log and context. If the log doesn't support a \
confident answer, say what is uncertain instead of guessing.

## How to fix it
Numbered steps. Prefer actions available in Nixync (Undo update, Retry, editing the \
preset or the device's apps) when they fit. When a step needs the NixOS configuration \
or a shell on the device, give the exact option or command.

Keep it short and concrete. Don't repeat the log back."""


class NotConfigured(Exception):
    """No Anthropic credentials are available."""


def build_prompt(machine: Machine, error: MachineError, preset: Preset | None) -> str:
    running = machine.last_successful_build
    latest = machine.builds[0] if machine.builds else None
    lines = [
        f"Device: {machine.name} ({machine.address or 'no address'})",
        f"Status: {machine.health.value}",
        f"NixOS version: {machine.nixos_version}",
        f"Preset: {machine.preset}",
    ]
    if preset:
        enabled = [b.name for b in preset.bundles if b.enabled]
        lines.append(f"Preset bundles: {', '.join(enabled) or 'none'}")
        lines.append(f"Preset apps: {', '.join(preset.extra_apps) or 'none'}")
    lines.append(f"Device-only apps: {', '.join(machine.extra_apps) or 'none'}")
    if running:
        lines.append(f"Running generation: {running.generation} (built {timestamp(running.finished)})")
    if latest:
        result = "succeeded" if latest.ok else "failed"
        lines.append(f"Last update attempt: generation {latest.generation}, {result}: {latest.summary}")
    lines += [
        "",
        f"Error: {error.title}",
        f"When: {timestamp(error.when)}",
        "",
        "Log:",
        error.log or "(no log was recorded)",
    ]
    return "\n".join(lines)


def explain(machine: Machine, error: MachineError, preset: Preset | None) -> Iterator[str]:
    """Stream Claude's explanation as text chunks. Blocking; run it off the UI thread.

    Raises NotConfigured when there are no credentials, and the SDK's typed errors otherwise.
    """
    client = anthropic.Anthropic()
    request = client.beta.messages.stream(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium"},
        # If the model declines, the API retries on a fallback model in the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": build_prompt(machine, error, preset)}],
    )
    try:
        stream = request.__enter__()
    except TypeError as e:
        # The SDK only notices missing credentials when the request is built.
        if "authentication method" in str(e):
            raise NotConfigured(str(e)) from e
        raise
    try:
        yield from stream.text_stream
        final = stream.get_final_message()
    finally:
        request.__exit__(None, None, None)
    if final.stop_reason == "refusal":
        yield "\n\n_Claude declined to answer this one._"
    elif final.stop_reason == "max_tokens":
        yield "\n\n_The answer was cut off._"
