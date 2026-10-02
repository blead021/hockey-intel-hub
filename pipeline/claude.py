"""One place to create the Claude API client for every job.

If ANTHROPIC_WORKSPACE_ID is set, it is sent with each request. Anthropic requires it for API keys that
are not tied to a workspace (the error says "This API key is not scoped to a workspace").
"""

import os


def client():
    import anthropic

    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    headers = {"anthropic-workspace-id": workspace} if workspace else None
    return anthropic.Anthropic(default_headers=headers)
