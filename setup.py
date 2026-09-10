"""Setup script for webscout-mcp.

Version is managed by setuptools-scm (Git tag as single source of truth).
Do NOT hardcode version here - it will be auto-detected from Git tags.
"""
from setuptools import find_packages, setup

setup(
    name="webscout-mcp",
    use_scm_version=True,
    packages=find_packages(),
    python_requires=">=3.10",
)
