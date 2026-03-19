"""
Template rendering with Jinja2. Plaintext only, no HTML.
"""

from pathlib import Path
from typing import Optional
from jinja2 import Template, TemplateSyntaxError, UndefinedError, StrictUndefined
from jinja2 import meta as jinja2_meta

from .exceptions import TemplateValidationError


class TemplateRenderer:
    """Render Jinja2 templates for campaigns."""

    def __init__(self, templates_dir: Optional[str] = None):
        """
        Initialize renderer.
        
        Args:
            templates_dir: Base directory for templates (optional for static usage)
        """
        self.templates_dir = templates_dir

    def render(
        self, template_filename: str, context: dict, recipient_email: str = ""
    ) -> str:
        """
        Render a template file from templates_dir.

        Args:
            template_filename: Filename relative to templates_dir
            context: Context dict
            recipient_email: Email being rendered (for error messages)

        Returns:
            Rendered template string (raises exception on error)
        """
        from .exceptions import TemplateError
        
        if not self.templates_dir:
            raise ValueError("templates_dir not set")
        
        path = Path(self.templates_dir) / template_filename
        if not path.exists():
            raise FileNotFoundError(f"Template file not found: {path}")
        
        with open(path, "r") as f:
            template_content = f.read()
        
        rendered, errors = self._render_content(template_content, context, recipient_email)
        if errors:
            raise TemplateError("; ".join(errors))
        return rendered

    def validate(self, template_filename: str, required_variables: Optional[set[str]] = None) -> list[str]:
        """
        Validate a template file.

        Args:
            template_filename: Filename relative to templates_dir
            required_variables: Set of variables that must be in template

        Returns:
            List of error messages (empty = valid)
        """
        if not self.templates_dir:
            raise ValueError("templates_dir not set")
        
        path = Path(self.templates_dir) / template_filename
        if not path.exists():
            return [f"Template file not found: {path}"]
        
        with open(path, "r") as f:
            template_content = f.read()
        
        return self.validate_template(template_content, required_variables)

    def extract_variables(self, template_filename: str) -> set[str]:
        """
        Extract variable names from a template file.

        Args:
            template_filename: Filename relative to templates_dir

        Returns:
            Set of variable names used in template
        """
        if not self.templates_dir:
            raise ValueError("templates_dir not set")
        
        path = Path(self.templates_dir) / template_filename
        if not path.exists():
            raise FileNotFoundError(f"Template file not found: {path}")
        
        with open(path, "r") as f:
            template_content = f.read()
        
        return self._extract_variables(template_content)

    def validate_recipients(self, template_filename: str, recipients: list[dict]) -> bool | list[str]:
        """
        Validate that all recipients have required template variables.

        Args:
            template_filename: Filename relative to templates_dir
            recipients: List of recipient dicts

        Returns:
            True if valid, list of error messages otherwise
        """
        if not self.templates_dir:
            raise ValueError("templates_dir not set")
        
        path = Path(self.templates_dir) / template_filename
        if not path.exists():
            return [f"Template file not found: {path}"]
        
        with open(path, "r") as f:
            template_content = f.read()
        
        # Extract required variables from template
        try:
            required_vars = self._extract_variables(template_content)
        except Exception as e:
            return [f"Failed to extract template variables: {e}"]
        
        errors = []
        for recipient in recipients:
            email = recipient.get("email", "unknown")
            
            for var in required_vars:
                # Check if variable exists in recipient dict
                if var not in recipient or recipient[var] is None or recipient[var] == "":
                    errors.append(f"Recipient {email}: missing '{var}'")
        
        return True if not errors else errors

    @staticmethod
    def _extract_variables(template_content: str) -> set[str]:
        """
        Extract variable names from a Jinja2 template.

        Args:
            template_content: Jinja2 template string

        Returns:
            Set of variable names used in template
        """
        try:
            env = Template("").environment
            ast = env.parse(template_content)
            variables = jinja2_meta.find_undeclared_variables(ast)
            return variables
        except TemplateSyntaxError as e:
            raise TemplateValidationError(f"Template syntax error: {e.message}")
        except Exception as e:
            raise TemplateValidationError(f"Failed to extract variables: {e}")

    @staticmethod
    def validate_template(
        template_content: str, required_variables: Optional[set[str]] = None
    ) -> list[str]:
        """
        Validate a template.

        Args:
            template_content: Jinja2 template string
            required_variables: Set of variables that must be in template

        Returns:
            List of error messages (empty = valid)
        """
        errors = []

        # Check syntax
        try:
            Template(template_content, autoescape=False)
        except TemplateSyntaxError as e:
            errors.append(f"Template syntax error: {e.message}")
            return errors

        # Check for required variables
        if required_variables:
            try:
                variables = TemplateRenderer._extract_variables(template_content)
                missing = required_variables - variables
                if missing:
                    errors.append(
                        f"Template missing required variables: {', '.join(sorted(missing))}"
                    )
            except TemplateValidationError as e:
                errors.append(str(e))

        return errors

    @staticmethod
    def _render_content(
        template_content: str, context: dict, recipient_email: str = ""
    ) -> tuple[str, list[str]]:
        """
        Render template content with context.

        Args:
            template_content: Jinja2 template string
            context: Context dict (must include all required variables)
            recipient_email: Email being rendered (for error messages)

        Returns:
            (rendered_content: str, errors: list[str])
        """
        errors = []

        try:
            tmpl = Template(template_content, autoescape=False, undefined=StrictUndefined)
            rendered = tmpl.render(**context)
            return rendered, errors
        except UndefinedError as e:
            errors.append(f"Template error for {recipient_email}: {e}")
            return "", errors
        except TemplateSyntaxError as e:
            errors.append(f"Template syntax error: {e.message}")
            return "", errors
        except Exception as e:
            errors.append(f"Template rendering failed for {recipient_email}: {e}")
            return "", errors

    @staticmethod
    def render_from_file(
        template_path: str, context: dict, recipient_email: str = ""
    ) -> tuple[str, list[str]]:
        """
        Render a template from a file.

        Args:
            template_path: Path to template file
            context: Context dict
            recipient_email: Email being rendered

        Returns:
            (rendered_content: str, errors: list[str])
        """
        errors = []

        try:
            path = Path(template_path).expanduser()
            if not path.exists():
                errors.append(f"Template file not found: {template_path}")
                return "", errors

            with open(path, "r") as f:
                template_content = f.read()

            return TemplateRenderer._render_content(template_content, context, recipient_email)
        except Exception as e:
            errors.append(f"Failed to read template: {e}")
            return "", errors

    @staticmethod
    def validate_recipient_has_variables(
        recipient, required_variables: set[str]
    ) -> list[str]:
        """
        Check if a recipient has all required template variables.

        Args:
            recipient: Recipient dict or object
            required_variables: Set of required variable names

        Returns:
            List of missing variable names
        """
        if isinstance(recipient, dict):
            email = recipient.get("email", "unknown")
            personalization = recipient.get("personalization", {})
        else:
            # Recipient object
            email = getattr(recipient, "email", "unknown")
            personalization = getattr(recipient, "personalization", {})

        missing = []
        for var in required_variables:
            if var == "email":
                if not email:
                    missing.append(var)
            elif var == "display_name":
                display_name = recipient.get("display_name", "") if isinstance(recipient, dict) else getattr(recipient, "display_name", "")
                if not display_name:
                    missing.append(var)
            else:
                # Check in personalization
                if var not in personalization or not personalization[var]:
                    missing.append(var)

        return missing
