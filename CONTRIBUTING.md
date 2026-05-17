# Contributing to nanobot-channel-dingtalk

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing to the project.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Code Style](#code-style)
- [Commit Messages](#commit-messages)
- [Release Process](#release-process)

---

## Code of Conduct

Please be respectful and inclusive when interacting with other contributors. We aim to maintain a welcoming environment for everyone.

---

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Git
- pip (Python package manager)

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/nanobot_channel_dingtalk.git
   cd nanobot_channel_dingtalk
   ```
3. Add the upstream remote:
   ```bash
   git remote add upstream https://github.com/codeLong1024/nanobot_channel_dingtalk.git
   ```

---

## Development Setup

### Install Dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"
```

If `[dev]` extras are not defined in `pyproject.toml`, install manually:
```bash
pip install pytest pytest-cov black isort mypy
```

### Verify Installation

```bash
# Run tests
python -m pytest tests/ -v

# Check imports
python -c "from nanobot_channel_dingtalk import DingTalkChannel; print('OK')"
```

---

## Making Changes

### Branch Strategy

- **main**: Stable release branch
- **develop**: Active development branch (if exists)
- **feature/\***: New features
- **bugfix/\***: Bug fixes
- **docs/\***: Documentation updates

Create a new branch:
```bash
git checkout -b feature/your-feature-name
```

### Workflow

1. Sync with upstream:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. Make your changes
3. Write/update tests
4. Update documentation if needed
5. Commit your changes
6. Push to your fork
7. Submit a Pull Request

---

## Testing

### Run Tests

```bash
# All tests
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=nanobot_channel_dingtalk --cov-report=html

# Specific test file
python -m pytest tests/test_import.py -v
```

### Test Guidelines

- Write tests for new features
- Ensure existing tests pass
- Aim for high code coverage
- Test edge cases and error conditions

---

## Submitting Changes

### Pull Request Checklist

- [ ] Code follows style guidelines
- [ ] Tests added/updated and passing
- [ ] Documentation updated
- [ ] Commit messages are clear
- [ ] Branch is up-to-date with upstream
- [ ] No merge conflicts

### PR Process

1. Open a Pull Request from your fork
2. Fill out the PR template (if available)
3. Address review comments
4. Wait for CI checks to pass
5. Merge after approval

---

## Code Style

### Python Style Guide

We follow [PEP 8](https://peps.python.org/pep-0008/) with these tools:

- **Black**: Code formatting
- **isort**: Import sorting
- **mypy**: Type checking
- **flake8/pylint**: Linting

### Format Code

```bash
# Auto-format
black src/ tests/
isort src/ tests/

# Type checking
mypy src/

# Linting
flake8 src/ tests/
```

### Naming Conventions

- **Modules**: `snake_case` (e.g., `emotion_handler.py`)
- **Classes**: `PascalCase` (e.g., `DingTalkChannel`)
- **Functions/Methods**: `snake_case` (e.g., `send_message`)
- **Constants**: `UPPER_CASE` (e.g., `MAX_RETRIES`)
- **Private**: Leading underscore (e.g., `_internal_method`)

### Type Hints

Use type hints for all public APIs:
```python
def send_message(self, text: str, session_id: str) -> bool:
    """Send a message to DingTalk."""
    ...
```

### Docstrings

Use Google-style docstrings:
```python
def process_image(self, path: str) -> dict:
    """Process an image file.
    
    Args:
        path: Path to the image file.
        
    Returns:
        Dictionary containing processed image data.
        
    Raises:
        FileNotFoundError: If image doesn't exist.
    """
    ...
```

---

## Commit Messages

### Format

```
type(scope): subject

body (optional)

footer (optional)
```

### Types

- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation only
- **style**: Code style (formatting, semicolons, etc.)
- **refactor**: Code refactoring
- **test**: Adding/updating tests
- **chore**: Maintenance tasks

### Examples

```
feat(emotion): add thinking emoji support

Implement 🤔 emoji display on message receive and auto-recall
on reply completion.

Closes #123
```

```
fix(media): handle chunked upload timeout

Increase timeout from 30s to 60s for large file uploads.
Add retry logic for transient network errors.
```

---

## Release Process

Releases are managed by maintainers. The process:

1. Update version in `pyproject.toml`
2. Update CHANGELOG.md (if exists)
3. Create release tag: `git tag v1.0.0`
4. Push tag: `git push upstream v1.0.0`
5. CI builds and publishes to PyPI

---

## Questions?

- **Issues**: Use GitHub Issues for bugs and feature requests
- **Discussions**: Use GitHub Discussions for questions
- **Email**: Contact maintainers directly for sensitive matters

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing! 🎉
