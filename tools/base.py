"""
BaseTool: abstract base class for all tool implementations.
Provides a unified execute() interface for the dispatcher and agent layers.
"""
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """Abstract base class for all tools in the OpenOctopus tool layer.

    Subclasses must define ``name``, ``description``, and implement ``execute()``.
    The ``execute()`` method must always return a JSON-serialisable dict so the
    dispatcher can forward the result directly to the agent without transformation.
    """

    #: Machine-readable identifier used as the registry key in dispatcher.
    name: str

    #: Human-readable description surfaced to the LLM agent as tool metadata.
    description: str

    @abstractmethod
    def execute(self, input: dict) -> dict:
        """Run the tool with the given input parameters.

        Args:
            input: A JSON-serialisable dict of tool-specific parameters.
                   Typical keys: ``ticker``, ``period``, etc.

        Returns:
            A JSON-serialisable dict containing the tool result.
            On success the dict should contain the requested data.
            On failure it should contain ``{"error": "<message>"}`` so the
            caller can handle gracefully without raising.

        Raises:
            NotImplementedError: If the subclass forgot to implement this method.
        """
        ...  # pragma: no cover
