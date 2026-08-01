from uuid import uuid4

import pytest
from autonoesis_runtime import TaskResult, TaskStatus


def test_blocked_result_requires_reason() -> None:
    with pytest.raises(ValueError, match="blocked_reason"):
        TaskResult(
            task_id=uuid4(),
            status=TaskStatus.BLOCKED,
            summary="Unable to continue",
        )
