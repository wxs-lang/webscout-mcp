# Contributing to webscout-mcp

First off, thanks for taking the time to contribute! ❤️

All types of contributions are encouraged and valued. Please make sure to read the relevant section before making your contribution. It will make it a lot easier for us maintainers and smooth out the experience for all involved.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [I Have a Question](#i-have-a-question)
- [I Want To Contribute](#i-want-to-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Enhancements](#suggesting-enhancements)
  - [Contributing Code](#contributing-code)
  - [Improving Documentation](#improving-documentation)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Coding Standards](#coding-standards)
- [Testing Guidelines](#testing-guidelines)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Pull Request Process](#pull-request-process)

---

## Code of Conduct

This project and everyone participating in it is governed by the [webscout-mcp Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

---

## I Have a Question

Before you ask a question, it is best to search for existing [Issues](https://github.com/wxs-lang/webscout-mcp/issues) that might help you. If you then still feel the need to ask a question:

- Open an [Issue](https://github.com/wxs-lang/webscout-mcp/issues/new)
- Provide as much context as you can about what you're running into
- Provide project and platform versions (Python version, OS, etc.)

---

## I Want To Contribute

### Reporting Bugs

#### Before Submitting a Bug Report

- Make sure that you are using the latest version
- Determine if your bug is really a bug and not an error on your side
- Check if there is not already a bug report existing in the [bug tracker](https://github.com/wxs-lang/webscout-mcp/issues?q=label%3Abug)
- Collect information about the bug:
  - Stack trace (Traceback)
  - OS, Platform and Version
  - Version of the Python interpreter and dependencies
  - Your input/code and the output you're seeing
  - Whether you can reliably reproduce the issue

#### How Do I Submit a Good Bug Report?

> You must never report security related issues to the issue tracker. Instead sensitive bugs must be sent by email to [security@webscout-mcp.dev](mailto:security@webscout-mcp.dev).

We use GitHub issues to track bugs and errors. If you run into an issue:

- Open an [Issue](https://github.com/wxs-lang/webscout-mcp/issues/new)
- Explain the behavior you would expect and the actual behavior
- Provide as much context as possible and describe the reproduction steps
- Include any relevant code snippets, error messages, or stack traces
- Include information about your environment

### Suggesting Enhancements

This section guides you through submitting an enhancement suggestion, including completely new features and minor improvements.

#### Before Submitting an Enhancement

- Make sure that you are using the latest version
- Read the [documentation](README.md) carefully
- Perform a [search](https://github.com/wxs-lang/webscout-mcp/issues) to see if the enhancement has already been suggested
- Find out whether your idea fits with the scope and aims of the project

#### How Do I Submit a Good Enhancement Suggestion?

Enhancement suggestions are tracked as [GitHub issues](https://github.com/wxs-lang/webscout-mcp/issues).

- Use a **clear and descriptive title**
- Provide a **step-by-step description** in as many details as possible
- **Describe the current behavior** and **explain which behavior you expected**
- **Explain why this enhancement would be useful**
- Include any relevant code snippets or pseudocode

### Contributing Code

#### Prerequisites

- Python 3.10 or higher
- Git
- A GitHub account

#### Setting Up Development Environment

1. **Fork the repository**
   - Go to https://github.com/wxs-lang/webscout-mcp
   - Click the "Fork" button

2. **Clone your fork**
   ```bash
   git clone https://github.com/your-username/webscout-mcp.git
   cd webscout-mcp
   ```

3. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. **Install development dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

5. **Run tests to verify setup**
   ```bash
   pytest tests/ -v
   ```

#### Creating a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-fix-name
```

#### Making Changes

1. Follow the [Coding Standards](#coding-standards)
2. Write or update tests for your changes
3. Update documentation if needed
4. Run tests to ensure everything passes
5. Run linters to ensure code quality

#### Submitting a Pull Request

1. **Commit your changes**
   ```bash
   git add .
   git commit -m "feat: add new search backend"
   ```

2. **Push to your fork**
   ```bash
   git push origin feature/your-feature-name
   ```

3. **Create a Pull Request**
   - Go to your fork on GitHub
   - Click "Compare & pull request"
   - Fill in the PR template
   - Submit the pull request

### Improving Documentation

We welcome contributions to:

- **README.md** - Project overview, installation, usage
- **docs/** - Detailed documentation, guides, tutorials
- **API documentation** - Docstrings in code
- **Examples** - Usage examples and tutorials
- **CHANGELOG.md** - Update with notable changes

---

## Development Setup

### Requirements

- Python 3.10+
- pip
- Git

### Installation for Development

```bash
# Clone the repository
git clone https://github.com/wxs-lang/webscout-mcp.git
cd webscout-mcp

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install in development mode with all dependencies
pip install -e ".[dev,all]"
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run unit tests only
pytest tests/ -v -m "not integration and not performance"

# Run integration tests
pytest tests/test_integration.py -v

# Run with coverage
pytest tests/ --cov=webscout_mcp --cov-report=term-missing
```

### Running Linters

```bash
# Run flake8
flake8 webscout_mcp/ --max-line-length=120

# Run black (auto-format)
black --line-length=120 webscout_mcp/

# Run isort (auto-fix)
isort --profile black webscout_mcp/
```

---

## Project Structure

```
webscout-mcp/
├── webscout_mcp/              # Main package
│   ├── search.py             # Web search module
│   ├── fetcher.py            # Web content fetcher
│   ├── crawler.py            # Web crawler
│   ├── ai_processor.py       # AI content processing
│   ├── vector_store.py       # Vector store
│   ├── browser_fetcher.py    # Headless browser
│   ├── seo_analyzer.py       # SEO analysis
│   ├── config.py             # Configuration
│   ├── # Core optimization modules
│   ├── search_optimizer.py   # Search optimization
│   ├── content_extractor.py  # Content extraction
│   ├── rag_optimizer.py      # RAG optimization
│   ├── browser_optimizer.py  # Browser optimization
│   ├── ai_optimizer.py       # AI optimization
│   ├── # Infrastructure modules
│   ├── errors.py             # Unified error hierarchy
│   ├── security.py           # Security module
│   ├── async_utils.py        # Async utilities
│   ├── architecture.py       # Architecture patterns
│   └── health.py             # Health checks
├── tests/                     # Test suite
│   ├── conftest.py           # Test configuration
│   ├── test_*.py             # Unit tests
│   ├── test_integration.py   # Integration tests
│   └── test_performance.py   # Performance benchmarks
├── docs/                      # Documentation
├── pyproject.toml             # Project configuration
├── Dockerfile                 # Docker configuration
├── docker-compose.yml         # Docker Compose
├── CHANGELOG.md               # Changelog
├── CONTRIBUTING.md            # Contributing guide
├── LICENSE                    # License
└── README.md                  # Readme
```

---

## Coding Standards

### Python Style

We follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) with these conventions:

- **Line length**: 120 characters maximum
- **Indentation**: 4 spaces, no tabs
- **Quotes**: Double quotes for strings
- **Naming**:
  - Classes: `PascalCase`
  - Functions and variables: `snake_case`
  - Constants: `UPPER_SNAKE_CASE`

### Type Hints

We use type hints for all public APIs:

```python
def search(query: str, max_results: int = 10) -> list[dict]:
    """Search for query.

    Args:
        query: Search query string.
        max_results: Maximum number of results.

    Returns:
        List of search results.
    """
```

### Docstrings

We use Google-style docstrings:

```python
def function_name(arg1: str, arg2: int = 0) -> str:
    """Brief description.

    More detailed description if needed.

    Args:
        arg1: Description of arg1.
        arg2: Description of arg2. Defaults to 0.

    Returns:
        Description of return value.

    Raises:
        ValueError: If arg1 is empty.

    Examples:
        >>> function_name("test", 5)
        "result"
    """
```

### Error Handling

- Use the unified error hierarchy from `webscout_mcp.errors`
- Catch specific exceptions, not bare `Exception`
- Include context in error messages
- Use `raise ... from ...` for exception chaining

---

## Testing Guidelines

### Test Coverage

- All new code must include tests
- Aim for 80%+ code coverage
- Test both success and failure cases
- Include edge cases and boundary conditions

### Test Structure

```python
import pytest
from webscout_mcp.search import SearchEngine

class TestSearchEngine:
    """Test suite for SearchEngine class."""

    def setup_method(self):
        """Set up before each test."""
        self.engine = SearchEngine()

    def test_search_success(self):
        """Test successful search."""
        results = self.engine.search("test query")
        assert len(results) > 0

    def test_search_empty_query(self):
        """Test empty query raises error."""
        with pytest.raises(ValueError):
            self.engine.search("")
```

### Test Categories

- **Unit tests**: Test individual functions/classes in isolation
- **Integration tests**: Test interactions between modules
- **Performance tests**: Benchmark performance characteristics

---

## Commit Message Guidelines

We use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Commit Types

- `feat`: A new feature
- `fix`: A bug fix
- `docs`: Documentation only changes
- `style`: Formatting changes
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `perf`: Performance improvement
- `test`: Adding or correcting tests
- `build`: Build system or dependencies
- `ci`: CI configuration
- `chore`: Other changes

### Examples

```
feat(search): add DuckDuckGo search backend

Add support for DuckDuckGo HTML search backend with
automatic failover from Bing. Includes rate limiting
and result deduplication.

Closes #123
```

```
fix(extractor): fix content extraction for JS-heavy pages

Content extraction was failing on pages with heavy JavaScript
rendering. Added wait-for-selector option and improved
fallback extraction logic.

Fixes #456
```

---

## Pull Request Process

### PR Template

When creating a pull request, please include:

1. **Description**: What does this PR do?
2. **Related Issue**: Link to any related issues
3. **Type of Change**: Bug fix / New feature / Documentation / Performance / Refactoring
4. **Testing**: How has this been tested?
5. **Checklist**:
   - [ ] Code follows project style guidelines
   - [ ] Tests have been added/updated
   - [ ] Documentation has been updated
   - [ ] No new warnings or errors
   - [ ] All tests pass locally

### Review Process

1. **Automated checks**: CI/CD pipeline runs tests and linters
2. **Code review**: At least one maintainer reviews the code
3. **Feedback**: Address any comments or requested changes
4. **Approval**: Get approval from at least one maintainer
5. **Merge**: PR is merged by a maintainer

---

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).

---

**Thank you for contributing to webscout-mcp! 🎉**
