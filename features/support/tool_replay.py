"""Tool response replay used by end-to-end turn scenarios."""
from unittest.mock import Mock, patch
from agavai.outcomes import ToolOutcome


def tool_patch(target, *, return_value=None, side_effect=None, wraps=None):
    mocked = Mock(return_value=return_value)
    def dispatch(*args, **kwargs):
        if side_effect:
            result = side_effect(*args, **kwargs)
        elif mocked.return_value is not None:
            result = mocked.return_value
        else:
            result = wraps(*args, **kwargs)
        return result if isinstance(result, ToolOutcome) else ToolOutcome(result)
    mocked.side_effect = dispatch
    return patch(target, new=mocked)
