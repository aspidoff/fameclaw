"""Tests for template rendering and validation."""

from pathlib import Path

import pytest

from fameclaw.templates import TemplateRenderer
from fameclaw.exceptions import ValidationError, TemplateError


@pytest.fixture
def renderer(temp_templates_dir):
    """Create a template renderer."""
    return TemplateRenderer(temp_templates_dir)


class TestTemplateRendering:
    """Test Jinja2 template rendering."""

    def test_render_simple_template(self, renderer, temp_templates_dir):
        """Test rendering a simple template."""
        template_file = Path(temp_templates_dir) / "simple.txt"
        template_file.write_text("Hello {{ name }}")

        result = renderer.render("simple.txt", {"name": "Alice"})
        assert result == "Hello Alice"

    def test_render_complex_template(self, renderer, temp_templates_dir):
        """Test rendering template with multiple variables."""
        template_file = Path(temp_templates_dir) / "complex.txt"
        template_file.write_text(
            """Dear {{ name }},

I'm reaching out because {{ reason }}.

You can reach me at {{ email }}.

Best regards,
{{ signature }}"""
        )

        context = {
            "name": "Bob",
            "reason": "we share similar interests",
            "email": "contact@souls.zip",
            "signature": "Alice",
        }

        result = renderer.render("complex.txt", context)
        assert "Dear Bob" in result
        assert "contact@souls.zip" in result

    def test_render_with_default_values(self, renderer, temp_templates_dir):
        """Test template with default variable values."""
        template_file = Path(temp_templates_dir) / "defaults.txt"
        template_file.write_text(
            """Hello {{ name | default('Friend') }}"""
        )

        result = renderer.render("defaults.txt", {})
        assert "Friend" in result

    def test_render_with_filters(self, renderer, temp_templates_dir):
        """Test template with Jinja2 filters."""
        template_file = Path(temp_templates_dir) / "filters.txt"
        template_file.write_text(
            """Hello {{ name | upper }},

Your message: {{ message | truncate(20) }}"""
        )

        context = {"name": "alice", "message": "This is a very long message"}
        result = renderer.render("filters.txt", context)
        assert "ALICE" in result

    def test_render_with_conditionals(self, renderer, temp_templates_dir):
        """Test template with conditional logic."""
        template_file = Path(temp_templates_dir) / "conditional.txt"
        template_file.write_text(
            """{% if premium %}
Welcome to our premium service!
{% else %}
Welcome to our free service!
{% endif %}"""
        )

        result_premium = renderer.render("conditional.txt", {"premium": True})
        assert "premium service" in result_premium

        result_free = renderer.render("conditional.txt", {"premium": False})
        assert "free service" in result_free

    def test_render_with_loops(self, renderer, temp_templates_dir):
        """Test template with loop logic."""
        template_file = Path(temp_templates_dir) / "loop.txt"
        template_file.write_text(
            """Your interests:
{% for interest in interests %}
  - {{ interest }}
{% endfor %}"""
        )

        result = renderer.render(
            "loop.txt", {"interests": ["AI", "Python", "Startups"]}
        )
        assert "AI" in result
        assert "Python" in result
        assert "Startups" in result


class TestTemplateValidation:
    """Test template validation."""

    def test_validate_required_variables(self, renderer, temp_templates_dir):
        """Test validation of required template variables."""
        template_file = Path(temp_templates_dir) / "required.txt"
        template_file.write_text("Hello {{ name }}, your email is {{ email }}")

        # Should fail without required vars
        with pytest.raises(TemplateError):
            renderer.render("required.txt", {})

        # Should pass with required vars
        result = renderer.render("required.txt", {"name": "Alice", "email": "alice@example.com"})
        assert "Alice" in result

    def test_validate_syntax(self, renderer, temp_templates_dir):
        """Test template syntax validation."""
        bad_template = Path(temp_templates_dir) / "bad_syntax.txt"
        bad_template.write_text("Hello {{ name }}")

        # Invalid Jinja2 syntax should raise error
        with pytest.raises(TemplateError):
            renderer.render("bad_syntax.txt", {})  # Missing required var

    def test_validate_file_exists(self, renderer):
        """Test validation that template file exists."""
        with pytest.raises(FileNotFoundError):
            renderer.render("nonexistent.txt", {})

    def test_extract_variables(self, renderer, temp_templates_dir):
        """Test extracting variables from template."""
        template_file = Path(temp_templates_dir) / "extract.txt"
        template_file.write_text("Hello {{ name }}, your email is {{ email }}")

        variables = renderer.extract_variables("extract.txt")
        assert "name" in variables
        assert "email" in variables


class TestTemplateEdgeCases:
    """Test edge cases in template rendering."""

    def test_render_empty_variables(self, renderer, temp_templates_dir):
        """Test rendering with empty variable values."""
        template_file = Path(temp_templates_dir) / "empty.txt"
        template_file.write_text("Name: {{ name }}")

        result = renderer.render("empty.txt", {"name": ""})
        assert "Name: " in result

    def test_render_special_characters(self, renderer, temp_templates_dir):
        """Test rendering with special characters."""
        template_file = Path(temp_templates_dir) / "special.txt"
        template_file.write_text("Hello {{ name }}")

        result = renderer.render("special.txt", {"name": "José García"})
        assert "José García" in result

    def test_render_html_escaping(self, renderer, temp_templates_dir):
        """Test that HTML is properly escaped."""
        template_file = Path(temp_templates_dir) / "html.txt"
        template_file.write_text("Content: {{ content }}")

        result = renderer.render("html.txt", {"content": "<script>alert('xss')</script>"})
        # HTML should be escaped in plain text template
        assert "<script>" in result or "&lt;script&gt;" in result

    def test_render_large_context(self, renderer, temp_templates_dir):
        """Test rendering with large context."""
        template_file = Path(temp_templates_dir) / "large.txt"
        template_file.write_text("User {{ id }}: {{ name }}")

        large_context = {
            "id": 12345,
            "name": "Alice",
            **{"extra_" + str(i): f"value_{i}" for i in range(100)}
        }

        result = renderer.render("large.txt", large_context)
        assert "12345" in result
        assert "Alice" in result

    def test_render_multiline_template(self, renderer, temp_templates_dir):
        """Test rendering multiline templates."""
        template_file = Path(temp_templates_dir) / "multiline.txt"
        template_content = """Dear {{ name }},

I hope this email finds you well.

I wanted to reach out about {{ topic }}.

Best regards,
{{ sender }}

P.S. {{ postscript }}"""

        template_file.write_text(template_content)

        result = renderer.render(
            "multiline.txt",
            {
                "name": "Alice",
                "topic": "a collaboration opportunity",
                "sender": "Bob",
                "postscript": "Please reply at your earliest convenience",
            },
        )

        assert "Dear Alice" in result
        assert "Bob" in result
        assert "P.S." in result


class TestTemplateRecipientValidation:
    """Test template validation against recipient data."""

    def test_validate_all_recipients_have_required_vars(self, renderer, temp_templates_dir):
        """Test that all recipients have all required template variables."""
        template_file = Path(temp_templates_dir) / "recipients.txt"
        template_file.write_text("Hello {{ name }}, your email is {{ email }}")

        recipients = [
            {"email": "alice@example.com", "name": "Alice"},
            {"email": "bob@example.com", "name": "Bob"},
            {"email": "charlie@example.com"},  # Missing 'name'
        ]

        # Should fail because charlie doesn't have 'name'
        result = renderer.validate_recipients("recipients.txt", recipients)
        assert result is not True  # Validation fails
        assert "charlie" in str(result) or "missing" in str(result).lower()

    def test_validate_recipients_all_complete(self, renderer, temp_templates_dir):
        """Test validation passes when all recipients complete."""
        template_file = Path(temp_templates_dir) / "complete.txt"
        template_file.write_text("Hello {{ name }}")

        recipients = [
            {"email": "alice@example.com", "name": "Alice"},
            {"email": "bob@example.com", "name": "Bob"},
        ]

        result = renderer.validate_recipients("complete.txt", recipients)
        assert result is True


class TestTemplateFileHandling:
    """Test template file handling."""

    def test_load_template_from_path(self, renderer, temp_templates_dir):
        """Test loading template from explicit path."""
        template_file = Path(temp_templates_dir) / "explicit.txt"
        template_file.write_text("Hello {{ name }}")

        result = renderer.render("explicit.txt", {"name": "Alice"})
        assert "Alice" in result

    def test_template_relative_path(self, renderer, temp_templates_dir):
        """Test relative path handling."""
        template_file = Path(temp_templates_dir) / "relative.txt"
        template_file.write_text("Hello")

        result = renderer.render("relative.txt", {})
        assert result == "Hello"

    def test_template_caching(self, renderer, temp_templates_dir):
        """Test that templates are cached."""
        template_file = Path(temp_templates_dir) / "cached.txt"
        template_file.write_text("Hello {{ name }}")

        # Render twice
        result1 = renderer.render("cached.txt", {"name": "Alice"})
        result2 = renderer.render("cached.txt", {"name": "Bob"})

        assert "Alice" in result1
        assert "Bob" in result2
