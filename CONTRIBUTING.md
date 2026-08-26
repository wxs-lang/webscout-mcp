# Contributing to webscout-mcp

First off, thanks for taking the time to contribute! 🎉

The following is a set of guidelines for contributing to webscout-mcp. These are mostly guidelines, not rules. Use your best judgment, and feel free to propose changes to this document in a pull request.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Enhancements](#suggesting-enhancements)
  - [Pull Requests](#pull-requests)
- [Development Setup](#development-setup)
- [Style Guidelines](#style-guidelines)
- [Testing](#testing)
- [Commit Messages](#commit-messages)

## Code of Conduct

This project and everyone participating in it is governed by the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/0/code_of_conduct/). By participating, you are expected to uphold this code.

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check the [existing issues](https://github.com/wxs-lang/webscout-mcp/issues) to avoid duplicates.

When you create a bug report, please include:

- **A clear and descriptive title**
- **Steps to reproduce the issue**
- **Expected behavior**
- **Actual behavior**
- **Your environment** (Python version, OS, etc.)
- **Any relevant logs or error messages**

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When suggesting an enhancement, please include:

- **A clear and descriptive title**
- **A detailed description of the proposed enhancement**
- **Any use cases or examples**
- **Why this enhancement would be useful**

### Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run the tests (`pytest`)
5. Commit your changes (`git commit -m 'feat: add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Development Setup

### Prerequisites

- Python 3.10 or higher
- pip

### Setup

```bash
# Clone the repository
git clone https://github.com/wxs-lang/webscout-mcp.git
cd webscout-mcp

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Running the project

```bash
# Run as MCP server (default)
webscout-mcp

# Run CLI commands
webscout-mcp search "python async libraries"
webscout-mcp fetch https://example.com
```

## Style Guidelines

### Python Style

We use:
- **Black** for code formatting (line length: 100)
- **Ruff** for linting
- **mypy** for type checking

Run these before committing:

```bash
# Format code
black webscout_mcp/ tests/

# Lint
ruff check webscout_mcp/ tests/

# Type check
mypy webscout_mcp/
```

### Docstrings

Use Google-style docstrings:

```python
def fetch_url(url: str, timeout: float = 10.0) -> str:
    """Fetch a URL and return its content.

    Args:
        url: The URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        The response content as a string.

    Raises:
        FetchError: If the request fails.
    """
```

## Testing

### Running tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_basic.py

# Run a specific test class
pytest tests/test_basic.py::TestCache

# Run with coverage
pytest --cov=webscout_mcp --cov-report=html
```

### Writing tests

- Write tests for all new features
- Keep tests fast and deterministic (avoid network calls in unit tests)
- Use descriptive test names
- Follow the Arrange-Act-Assert pattern

## Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Types

- `feat`: A new feature
- `fix`: A bug fix
- `docs`: Documentation only changes
- `style`: Changes that do not affect the meaning of the code
- `refactor`: A code change that neither fixes a bug nor adds a feature
- `perf`: A code change that improves performance
- `test`: Adding missing tests or correcting existing tests
- `build`: Changes that affect the build system or external dependencies
- `ci`: Changes to our CI configuration files and scripts
- `chore`: Other changes that don't modify src or test files

### Examples

```
feat(search): add Google search backend
fix(fetcher): handle timeout errors gracefully
docs: update installation instructions
test(cache): add tests for cache expiry
```

## Getting Help

If you have questions, feel free to:
- Open an issue with the `question` label
- Check the [documentation](https://github.com/wxs-lang/webscout-mcp#readme)

Thanks again for contributing! 🚀
