"""A2UI schema loading, prompt generation, parsing, fixing, and validation.

Provider-agnostic -- works the same for local and Gemini backends.
"""

import logging
from functools import lru_cache
from pathlib import Path

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.core.parser.parser import ResponsePart, parse_response
from a2ui.core.schema.common_modifiers import remove_strict_validation
from a2ui.core.schema.constants import A2UI_CLOSE_TAG, A2UI_OPEN_TAG, VERSION_0_8
from a2ui.core.schema.manager import A2uiSchemaManager

logger = logging.getLogger(__name__)

EXAMPLES_DIR = str(Path(__file__).parent / "examples")

# Components that work well with smaller models -- keep the schema compact
ALLOWED_COMPONENTS = [
    "Button",
    "Card",
    "Column",
    "Divider",
    "Icon",
    "Image",
    "List",
    "Row",
    "Text",
    "TextField",
]

ROLE_DESCRIPTION = (
    "You are a helpful assistant that generates rich UI responses using the A2UI JSON format. "
    "Your final output MUST include A2UI JSON blocks that render interactive UI components."
)

WORKFLOW_DESCRIPTION = """
When the user asks you a question or makes a request, respond with both conversational text
AND A2UI JSON blocks to render a visual UI.

Buttons that represent the main action on a card or view (e.g., 'Follow', 'Email', 'Search')
SHOULD include the `"primary": true` attribute.

IMPORTANT structural rules for v0.8 A2UI JSON:
- Every response is a JSON array of message objects.
- The first message MUST be a `beginRendering` with a `surfaceId` and `root` component ID.
- The second message MUST be a `surfaceUpdate` with the same `surfaceId` and a `components` array.
- Each component has an `id` (string) and a `component` object with exactly one key (the component type).
- String values use `{"literalString": "..."}` wrapper, not bare strings.
- Children references use `{"explicitList": ["id1", "id2"]}`, not bare arrays.
- Always start with a Card as the root component.
"""

UI_DESCRIPTION = """
Use these patterns:

- **Contact cards**: Card containing Column with Image (avatar), Text (h3 for name),
  Text (body for details like email, phone, department), and Button for actions.

- **Lists**: Card with a List containing multiple Row items, each with Icon + Text.

- **Information display**: Card with Column of Text components at different heading levels.

- **Forms**: Card with TextField inputs and a Button to submit.

Always wrap your UI in a Card component for visual grouping.

IMPORTANT Button component rules:
- Button uses `"child"` (a component ID pointing to a Text), NOT `"label"`.
- Button requires both `"child"` and `"action"` properties.
- Create a separate Text component for the button label and reference its ID.
  Example: {"Button": {"child": "btnLabel", "action": {"name": "click"}}}
  with a sibling: {"id": "btnLabel", "component": {"Text": {"text": {"literalString": "Click Me"}, "usageHint": "body"}}}
"""


def _build_schema_manager() -> A2uiSchemaManager:
    return A2uiSchemaManager(
        version=VERSION_0_8,
        catalogs=[BasicCatalog.get_config(version=VERSION_0_8, examples_path=EXAMPLES_DIR)],
        schema_modifiers=[remove_strict_validation],
    )


_schema_manager = _build_schema_manager()


@lru_cache(maxsize=1)
def get_system_prompt() -> str:
    """Generate the full system prompt with A2UI schema instructions (cached)."""
    prompt = _schema_manager.generate_system_prompt(
        role_description=ROLE_DESCRIPTION,
        workflow_description=WORKFLOW_DESCRIPTION,
        ui_description=UI_DESCRIPTION,
        allowed_components=ALLOWED_COMPONENTS,
        include_schema=True,
        include_examples=True,
        validate_examples=False,
    )
    logger.info(f"System prompt generated: {len(prompt)} chars")
    return prompt


@lru_cache(maxsize=1)
def get_catalog():
    """Return the pruned catalog for validation (cached)."""
    return _schema_manager.get_selected_catalog(
        allowed_components=ALLOWED_COMPONENTS,
    )


def parse_and_validate(llm_output: str) -> tuple[str, list[dict]]:
    """Parse LLM output, extract A2UI JSON blocks, validate, and return.

    Returns:
        (conversational_text, list_of_a2ui_messages)

    Raises on parse/validation failure (ValueError, JSONDecodeError,
    jsonschema ValidationError).
    """
    parts: list[ResponsePart] = parse_response(llm_output)

    text_parts = []
    a2ui_messages: list[dict] = []
    catalog = get_catalog()

    for part in parts:
        if part.text:
            text_parts.append(part.text.strip())

        if part.a2ui_json is not None:
            parsed = part.a2ui_json

            # Empty list is valid (no results)
            if parsed == []:
                continue

            # Validate against schema
            catalog.validator.validate(parsed)

            # Collect individual messages
            if isinstance(parsed, list):
                a2ui_messages.extend(parsed)
            else:
                a2ui_messages.append(parsed)

    text = " ".join(t for t in text_parts if t)
    logger.info(f"Parsed: {len(a2ui_messages)} A2UI messages, text={len(text)} chars")
    return text, a2ui_messages


def build_retry_prompt(original_query: str, error: str) -> str:
    """Build a retry message when validation fails."""
    return (
        f"Your previous response was invalid. {error} "
        "You MUST generate a valid response that strictly follows the A2UI JSON SCHEMA. "
        "The response MUST be a JSON list of A2UI messages. "
        f"Ensure each JSON part is wrapped in '{A2UI_OPEN_TAG}' and '{A2UI_CLOSE_TAG}' tags. "
        f"Please retry the original request: '{original_query}'"
    )
