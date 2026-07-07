# Text Formatting (Markdown)

**Always use `markdown_description` instead of `description`** when creating or updating tasks to enable rich text formatting.

## Supported Markdown Syntax

| Format | Syntax | Example |
|--------|--------|---------|
| Heading 1 | `# Heading` | `# Overview` |
| Heading 2 | `## Heading` | `## Objective` |
| Heading 3 | `### Heading` | `### Details` |
| Bold | `**text**` | `**important**` |
| Italic | `*text*` | `*emphasis*` |
| Strikethrough | `~~text~~` | `~~removed~~` |
| Unordered list | `- item` | `- First item` |
| Ordered list | `1. item` | `1. Step one` |
| Inline code | `` `code` `` | `` `function()` `` |
| Code block | ` ```lang ` | ` ```python ` |
| Links | `[text](url)` | `[docs](https://...)` |
| Blockquotes | `> text` | `> Note this` |

## API Usage

```json
{
  "name": "My Task",
  "markdown_description": "## Objective\n\nImplement the feature.\n\n### Requirements\n\n- Requirement 1\n- Requirement 2\n\n**Note:** This is important."
}
```

## Escaping Special Characters

Escape double quotes with backslash in JSON:
```json
"markdown_description": "User said \"hello\" to the system"
```

## Comments Limitation

**Comments do NOT support markdown via API.** The `comment_text` field renders markdown as plain text. For rich formatting in comments, use the structured JSON format with `text` and `attributes` objects:

```json
{
  "comment": [
    {"text": "Bold text", "attributes": {"bold": true}},
    {"text": "\n"},
    {"text": "Normal text"}
  ]
}
```
